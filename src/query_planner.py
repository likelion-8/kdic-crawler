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
import os
from typing import List, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from retrieval import ROOT  # .env 위치 재사용(다른 모듈과 동일 경로)

load_dotenv(ROOT / ".env")

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
    """쿼리 플래너 결과 — 분해 여부 + (하위 질문, intent) 목록."""
    should_split: bool = Field(description="서로 다른 정보 요구가 여러 개면 true")
    items: List[PlanItem]


# 분해 규칙(query_decomposer.SYSTEM_INSTRUCTION 요지) + intent 규칙(intent_llm_common.SYSTEM_PROMPT
# 요지)을 한 지시로 합친 것. 세 모델 비교 때 쓴 것과 동일 프롬프트(공정 비교 근거).
SYSTEM_PROMPT = """당신은 예금보험공사(KDIC) 챗봇의 질의 분석기입니다. 사용자 질문 하나를 받아 두 가지를 동시에 판단합니다. 질문에 답하지 말고 분석만 하세요.

[작업1 복합 질문 분해]
- 서로 다른 정보 요구가 여러 개면 should_split=true, 각 요구를 독립 검색 가능한 하위 질문으로 나눕니다.
- 요구가 하나면 should_split=false, items에는 원 질문 하나만 담습니다.
- "방법/절차"처럼 표현만 다르고 실제로 같은 요구는 나누지 않습니다. 원문에 없는 요구를 지어내지 않습니다.
- 나눌 때 각 하위 질문에 주어(제도·업무명)를 채워 문맥 없이 이해되게 합니다.

[작업2 intent 분류]
- 각 하위 질문마다 intent를 informational 또는 civil_petition 중 하나로 판단합니다.
- informational: 제도·개념·정의·사실·수치를 알고 싶어 함 (무엇인가/한도/감면율/대상 상품/처리·지급 기간/포상금 개념 등).
- civil_petition: 신청·신고·접수·조회·반환·수령 등 절차를 실행하려 함. 필요한 서류·방법·절차·신청 자격·신청 기한을 묻는 것도 포함."""

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
    intent_llm_common 규칙 5 '애매하면 informational'과 동일). 분류 실패가 검색·답변을 막지 않게."""
    return {"should_split": False, "items": [{"question": query, "intent": "informational"}]}


def plan_query(query):
    """질문 하나 -> {"should_split": bool, "items": [{"question", "intent"}]}.

    OpenAI structured output(response_format=QueryPlan)으로 형식을 강제한다. 파싱 실패·API 실패·
    빈 items는 모두 _fallback으로 떨어져 파이프라인이 멈추지 않는다(입출력 계약은 항상 위 형태)."""
    try:
        messages = [{"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": query}]
        completion = _parse(_get_client(), _PLANNER_MODEL, messages)
        plan = completion.choices[0].message.parsed
        if plan is None or not plan.items:
            return _fallback(query)
        return {
            "should_split": bool(plan.should_split),
            "items": [{"question": it.question, "intent": it.intent} for it in plan.items],
        }
    except Exception:
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
