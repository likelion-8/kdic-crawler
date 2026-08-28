"""쿼리 플래너 — 멀티쿼리 분해 + intent 분류를 OpenAI structured output '한 번의 호출'로 처리.

기존 구조는 분해(query_decomposer.decompose_query, HCX-DASH-002)와 intent 분류
(query_classifier.classify_intent, OpenAI)가 서로 다른 호출·다른 벤더로 나뉘어 있었다. 둘 다
'질문 텍스트만' 보고 판단하며 검색·생성 이전 같은 단계에서 일어나므로, 한 번의 structured-output
호출로 합친다. 반환 구조:

    {"should_split": bool, "items": [{"question": str, "intent": "informational"|"civil_petition"}]}

- should_split=false(단일)면 items 원소 1개(원문 그대로 + 그 질문의 intent).
- should_split=true(복합)면 하위 질문마다 (question, intent) 한 쌍.

채택 근거(docs/query_planner_model_comparison.md, 100문항 joint 벤치마크 실측):
gpt-5.6-luna가 joint 정확도 89%·intent macro F1 0.946·false split 0%로 세 모델(HCX-007/
gpt-5.4-mini/gpt-5.6-luna) 중 최고. 현행(HCX 분해 + luna intent, 질문당 2.6콜) 대비 joint
정확도 79→89%, 질문당 토큰 2,007→539(-73%), 호출 2.6→1. HCX-007은 분해는 좋으나 intent가
붕괴(civil recall 50.5%)했고 native structured output 미지원(400), gpt-5.4-mini는 under split
17.2%로 복합 질문을 자주 놓쳐 제외.

intent 정의·라벨 기준은 intent_llm_common.py(기존 intent 분류)와 동일하게 유지한다 — 두 라벨
informational/civil_petition만 쓰며, 분해기가 만든 각 하위 질문에 적용한다.
"""
import logging
import os
from typing import List, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from observability import observe, record_openai_generation
from retrieval import ROOT  # .env 위치 재사용(다른 모듈과 동일 경로)

load_dotenv(ROOT / ".env")

logger = logging.getLogger(__name__)

# 2026-08-09: intent 분류 하나만 하던 OpenAI 모델을 '분해+intent'를 함께 하는 플래너로 확장하면서
# 환경변수 이름을 OPENAI_INTENT_MODEL -> OPENAI_PLANNER_MODEL 로 바꿨다(이름이 실제 역할과 맞게).
# query_classifier.classify_intent(플래너 실패 시 폴백 경로)도 같은 변수를 읽는다.
_PLANNER_MODEL = os.environ.get("OPENAI_PLANNER_MODEL") or "gpt-5.6-luna"

# 멀티쿼리+intent를 한 콜로 처리할지 스위치(USE_RERANKER/USE_SOURCE_RECHECK와 같은 패턴).
# True: 이 플래너 사용. False: 기존 분리 방식(decompose_query + classify_intent)으로 폴백.
# pipeline.py와 api/rag/answer.py가 이 값을 함께 import 해 두 경로의 동작을 일치시킨다.
USE_QUERY_PLANNER = True


class PlanItem(BaseModel):
    """하위 질문 하나 + 그 질문의 intent(두 라벨 중 하나로 제약 — intent_llm_common과 동일)."""
    question: str = Field(description="독립적으로 검색·답변할 수 있는 하위 질문")
    intent: Literal["informational", "civil_petition"] = Field(
        description="하위 질문의 의도. 제도·개념·사실·수치를 물으면 informational, "
                    "신청·신고·접수·조회·반환 등 절차를 실행하려 하면 civil_petition."
    )


class QueryPlan(BaseModel):
    """쿼리 플래너 결과 — 분해 여부 + (하위 질문, intent) 목록.

    2026-08-21 에 업무 되묻기 판정(needs_clarification)을 이 콜에 얹었다가 2026-08-25 에
    다시 뺐다. 이 콜은 Gate 2 **뒤**라, 업무 명사가 빠진 질문("신청 방법 알려줘")은 Gate 2 가
    먼저 범위외로 EXIT 시켜 판정 기회 자체가 없었다(실측 s_id 0.536 < s_ood 0.668). 판정은
    게이트 앞에서 도는 query_rewriter.triage_query 한 곳으로 모았다 — 사유·대가는
    query_rewriter 모듈 docstring "왜 첫 턴에도 부르는가"."""
    should_split: bool = Field(description="서로 다른 정보 요구가 여러 개면 true")
    items: List[PlanItem]


# 분해 규칙(query_decomposer.SYSTEM_INSTRUCTION 요지) + intent 규칙(intent_llm_common.SYSTEM_PROMPT
# 요지)을 한 지시로 합친 것. 세 모델 비교 때 쓴 것과 동일 프롬프트(공정 비교 근거).
#
# 2026-08-10 분해 규칙 1줄 수정: "주어(제도·업무명)를 채워" 지시가 원문에 없는 기관명까지
# 덧붙이게 만들어("지급명령이 뭐야" → "예금보험공사의 지급명령이란 무엇인가") 하위 질문
# 검색이 그 낱말에 끌려갔다 — 실측: 원문 검색은 지급명령 근거를 찾는데(top: receiver_attention)
# 재작성 검색은 예금보험금·제도 페이지로 밀려 근거를 잃음. 주어 보완은 원문 표현으로만 하도록
# 제한(하위 질문 문구 = 검색 질의라는 사실을 지시에 명시).
SYSTEM_PROMPT = """당신은 예금보험공사(KDIC) 챗봇의 질의 분석기입니다. 사용자 질문 하나를 받아 두 가지를 동시에 판단합니다. 질문에 답하지 말고 분석만 하세요.

[작업1 복합 질문 분해]
- 서로 다른 정보 요구가 여러 개면 should_split=true, 각 요구를 독립 검색 가능한 하위 질문으로 나눕니다.
- 요구가 하나면 should_split=false, items에는 원 질문 하나만 담습니다.
- "방법/절차"처럼 표현만 다르고 실제로 같은 요구는 나누지 않습니다. 원문에 없는 요구를 지어내지 않습니다.
- 두 대상을 비교하는 질문("A와 B는 뭐가 다른가요?", "A와 B의 차이는?")은 요구가 두 개입니다 — 반드시 should_split=true로 하고 A와 B 각각을 묻는 하위 질문으로 나눕니다. 두 대상의 근거 문서가 서로 달라, 나누지 않으면 한쪽 근거만 검색됩니다.
- 하위 질문의 문구는 그대로 검색어로 쓰입니다. 원문 구절을 최대한 그대로 잘라 쓰고, 낱말을 바꾸거나 더하지 않습니다.
- 주어가 없어 문맥 없이 이해되지 않는 하위 질문에만 주어를 채우되, 반드시 원문에 쓰인 낱말로만 채웁니다. 원문에 없는 기관명·제도명·수식어(예: "예금보험공사의", "예금보험제도에서")를 덧붙이지 않습니다.
- 단, 말투는 정중한 의문문으로 다듬습니다(예: "뭐야?" → "~이란 무엇인가요?", "어떻게 해?" → "어떻게 하나요?"). 낱말과 대상은 그대로 두고 어미만 바꿉니다.

[작업2 intent 분류]
- 각 하위 질문마다 intent를 informational 또는 civil_petition 중 하나로 판단합니다.
- informational: 제도·개념·정의·사실·수치를 알고 싶어 함 (무엇인가/한도/감면율/대상 상품/처리·지급 기간/포상금 개념 등).
- civil_petition: 신청·신고·접수·조회·반환·수령 등 절차를 실행하려 함. 필요한 서류·방법·절차·신청 자격·신청 기한을 묻는 것도 포함.

[예시]
- "미수령금 수령과 착오송금 반환신청은 뭐가 다른가요?" → should_split=true, items=["미수령금 수령은 무엇인가요?"(informational), "착오송금 반환신청은 무엇인가요?"(informational)] — 비교형은 두 대상의 근거 문서가 달라 반드시 나눕니다.
- "착오송금 반환까지 얼마나 걸리나요?" → should_split=false — 요구가 하나면 나누지 않습니다."""

_openai = {}
# 2026-08-04(query_classifier와 동일 처리): 모델마다 temperature 지원이 다르다. gpt-5.4-mini는 0
# 허용, gpt-5.6-luna는 기본값(1)만 허용하고 0을 주면 BadRequestError. 모델을 바꿔도 코드를 안
# 고치도록, 일단 temperature=0으로 시도하고 거부하면 그 모델에 한해 파라미터 없이 재호출한다.
_temperature_unsupported = set()


def _get_client():
    """OpenAI 클라이언트를 프로세스당 1회 생성(OPENAI_API_KEY 사용)."""
    if "c" not in _openai:
        from openai import OpenAI
        _openai["c"] = OpenAI()
    return _openai["c"]


def _parse(client, model, messages):
    """QueryPlan으로 파싱된 completion 반환 — temperature=0을 모델이 거부하면
    _temperature_unsupported에 기록하고 파라미터 없이 재시도(query_classifier._parse_intent와 동일)."""
    if model not in _temperature_unsupported:
        try:
            return client.beta.chat.completions.parse(
                model=model, messages=messages, response_format=QueryPlan, temperature=0)
        except Exception as e:
            if "temperature" not in str(e).lower():
                raise
            _temperature_unsupported.add(model)
    return client.beta.chat.completions.parse(
        model=model, messages=messages, response_format=QueryPlan)


def _fallback(query):
    """플래너 실패 시 안전 기본값 — 분해하지 않고 원문 1개, intent는 informational(안전 기본값,
    intent_llm_common 규칙 5 '애매하면 informational'과 동일). 분류 실패가 검색·답변을 막지 않게.

    fallback=True를 함께 돌려준다 — 이 값이 civil_petition 질문을 informational로 잘못
    강등시킨 결과일 수 있어(예: "착오송금 신청 링크줘"), 호출부(api/rag/sse.py)가 이 답변을
    질의 캐시에 적재하지 않도록 판단하는 근거가 된다(2026-08-28: 순간 API 장애로 만들어진
    불완전한 답변이 캐시를 통해 24시간 동안 다른 사용자에게 퍼지는 것을 막기 위함)."""
    return {"should_split": False, "items": [{"question": query, "intent": "informational"}],
            "fallback": True}


# 2026-08-19: 비교형 질문("미수령금 수령과 착오송금 반환신청은 뭐가 다른가요?")이 분해 없이
# 단일 검색을 타 한쪽(착오송금) 근거만 걷혔고, 생성이 나머지 반쪽을 지어내 사후 판정
# (ungrounded_claims)으로 본문이 교체되는 실사용 사례가 나왔다. 그런데 같은 질문을 플래너에
# 직접 넣으면 정상 분해된다 — 즉 프롬프트 문제가 아니라 (a) luna 가 temperature=0 을 거부해
# 온도 1로 돌면서 분해 판단이 롤마다 흔들리거나 (b) API 실패로 아래 무음 폴백에 떨어진 것.
# (a)는 위 SYSTEM_PROMPT 의 비교형 명시 규칙으로 눌렀고, (b)는 폴백이 로그를 안 남겨
# 사후 확인이 불가능했으므로 경고를 남긴다(source_check 의 "조용히 죽지 않도록" 원칙과 동일 —
# intent 분류기 무음 폴백 전례 방지).


@observe()
def plan_query(query):
    """질문 하나 -> {"should_split": bool, "items": [{"question", "intent"}], "fallback": bool}.

    OpenAI structured output(response_format=QueryPlan)으로 형식을 강제한다. 파싱 실패·API 실패·
    빈 items는 모두 _fallback으로 떨어져 파이프라인이 멈추지 않는다(입출력 계약은 항상 위 형태).

    fallback: 실제 LLM 판단이면 False, API 실패·빈 응답으로 안전 기본값을 대신 썼으면 True.
    호출부가 "플래너가 정말 단일+informational이라고 판단했다"와 "장애라 그렇게 때웠다"를
    구분해야 할 때(예: 질의 캐시 적재 여부) 이 값을 본다."""
    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": query}]
        completion = _parse(_get_client(), _PLANNER_MODEL, messages)
        record_openai_generation("plan_query_llm", completion, input=messages)
        plan = completion.choices[0].message.parsed
        if plan is None or not plan.items:
            logger.warning("플래너 응답이 비어 폴백(분해 없음) — 질문: %r", query)
            return _fallback(query)
        return {
            "should_split": bool(plan.should_split),
            "items": [{"question": it.question, "intent": it.intent} for it in plan.items],
            "fallback": False,
        }
    except Exception:
        logger.warning("플래너 호출 실패 — 폴백(분해 없음)으로 계속. 질문: %r", query, exc_info=True)
        return _fallback(query)


if __name__ == "__main__":
    import json
    for q in [
        "예금자보호제도가 뭐예요?",
        "예금보험금 신청 방법과 필요한 서류를 알려주세요.",
        "예금자보호 한도와 예금보험금 신청 방법을 알려주세요.",
    ]:
        print(q)
        print("  ", json.dumps(plan_query(q), ensure_ascii=False))
