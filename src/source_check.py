"""출처 부착 재확인 — 마커가 [NO_SOURCE]라고 판정했을 때만 별도 LLM에게 한 번 더 묻는다.

## 왜 필요한가

prompt_builder의 자기보고 마커는 근거를 실제로 쓴 답변에도 [NO_SOURCE]를 붙이는 오표기가
있다(docs/pipeline_issue_history.md 이슈 5). 라벨 107건 실측에서 근거를 쓴 답변 61건 중 33건(54%)이
이 오표기로 출처를 통째로 잃었다. 착오송금 주제에서 특히 재현이 잘 된다(2026-08-03 팀 재확인).

## 왜 "다시 프롬프트를 고치는" 접근이 아닌가

이슈 5는 생성 프롬프트를 고쳐 마커 정확도를 올리는 시도를 가설 7종 x 5회(HCX 35회 호출)로
통제 검증했고 **전부 실패했다.** 그 경로는 다시 밟지 않는다.

여기서 바꾸는 건 프롬프트가 아니라 **누가 언제 판단하는가**다. 실패한 35회는 전부 "답을
생성하면서 동시에 자기가 근거를 썼는지 보고하라"는 한 번의 호출이었다. 이 모듈은 답변이
다 나온 뒤, 생성과 분리된 별도 호출에서 "이 답변 문장이 이 자료에서 나왔는가"만 묻는다 —
생성 부담이 없는 순수 텍스트 대조 과제라 자기평가와 성격이 다르다. 이슈 5가 인용한 업계
표준(생성자를 믿지 말고 사후 검증)과 같은 구조이고, 판정 주체만 학습 모델이 아니라
LLM이다(2026-08-03 팀 결정 — 판정은 LLM이 하는 방향이 맞다).

## 판정 모델 — 2026-08-10 HCX YES/NO → OpenAI structured output 교체

같은 HCX(DASH-002)에게 YES/NO 텍스트로 묻던 방식은 근거를 실제로 쓴 답변을 대부분
놓쳤다. 정답 라벨 36건 배치 실측(근거 원문 대조로 라벨링):
  - HCX YES/NO 판정: 36건 중 18건 정답(50%) — 근거 사용 답변 24건 중 6건만 회수
  - gpt-5.6-luna structured output: 36건 중 35건 정답(97%) — 24건 중 23건 회수
  - 마커 [SOURCE_USED] 신뢰 + 그 외만 luna 판정(현행 결합 구조): 36건 전건 정답
쿼리 플래너(src/query_planner.py)와 같은 모델·같은 structured output 방식이라 신규
의존성이 아니다. OpenAI 키가 없거나 호출이 실패하면 False(= 마커의 원래 [NO_SOURCE]
판정 유지)로 떨어진다 — 이 모듈이 죽어도 동작은 이 기능이 없던 때와 정확히 같아지며,
조용히 죽지 않도록 경고 로그를 남긴다(intent 분류기의 무음 폴백 전례 방지).

## 왜 [NO_SOURCE]일 때만 부르는가

같은 107건에서 마커의 실패는 한 방향뿐이었다.
  - [SOURCE_USED]라고 말한 28건: 오판 0건 (2026-08-10 배치에서도 6/6 정밀)
  - [NO_SOURCE]라고 말한 79건: 33건 오판(42%)
"썼다"는 판정은 틀린 적이 없으므로 건드리지 않는다. 틀리는 쪽만 재확인하면 (a) 마커가
완벽했던 축(거절·인사에 무관한 출처가 안 붙는 것)을 그대로 보존하고 (b) 추가 LLM 호출이
[NO_SOURCE] 답변에만 발생해 비용도 그만큼만 는다.
"""
import logging
import os
from typing import Literal, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = """당신은 RAG 챗봇의 답변 검사기입니다. 질문에 답하지 말고 판정만 하세요.

판정할 것: "답변"이 "자료"에 담긴 내용을 실제로 가져다 썼는가?

- 답변에 담긴 사실(제도 이름, 절차, 조건, 금액, 기한, 대상 등)이 자료에 있는 내용과 대응되면 used_source=true입니다.
  표현을 바꿔 쓰거나 요약했어도, 내용의 출처가 자료면 true입니다.
- 답변이 인사말·잡담이거나, "확인할 수 없습니다" "안내가 어렵습니다"처럼 자료로 답하지
  못했다고 밝히는 내용뿐이면 false입니다.
- 답변이 자료와 전혀 상관없는 주제를 다루면 false입니다.
- 답변이 질문의 표현·태도를 지적하거나 예의 있는 대화를 안내하는 내용(예: "위협적으로
  느껴질 수 있습니다")이면, 자료 내용을 쓴 것이 아니므로 false입니다.
- 답변이 "다른 기관(경찰·금융감독원 등)의 소관"이라거나 "공사 업무 범위 밖"이라고 밝히는
  경우, 뒤에 일반적인 조언·신고 안내가 붙어 있어도 false입니다 — 그 조언은 자료가 아니라
  일반 상식에서 나온 것입니다. 자료에 질문 주제와 같은 낱말이 스쳐 지나가는 것만으로는
  true가 되지 않습니다.
- 자료 내용과 자료에 없는 내용이 섞여 있으면, 질문에 대한 "핵심 답"(연락처·기관명·금액·
  기한·절차 등 사용자가 실제로 행동할 정보)이 자료에서 나왔을 때만 true입니다. 곁가지만
  자료와 겹치고 핵심 답(예: 전화번호, 신고처)이 자료에 없는 것이면 false입니다.
- 질문이 용어·개념의 뜻을 묻는 경우는 예외입니다: 자료에 명시적인 정의 문장이 없어도,
  자료에 쓰인 그 용어의 쓰임새(절차·조건·맥락)를 요약해 설명한 답변이면 true입니다.
- 자료로 답한 부분과 거절이 섞여 있으면, 그 자료 부분이 질문의 답이 될 때만 true입니다.
- used_source와 kind는 일관돼야 합니다: used_source=true는 kind="grounded"와만,
  false는 나머지 kind와만 짝지을 수 있습니다."""


class AnswerJudgement(BaseModel):
    """근거 사용 여부 + 답변 성격. kind는 범위외 답변의 본문 교체 판단에 쓰인다(api/rag/answer.py)."""
    used_source: bool = Field(description="답변의 사실이 자료 내용과 대응되면 true. 인사·잡담·거절문이거나 자료와 무관하면 false.")
    kind: Literal["grounded", "greeting_or_smalltalk", "refusal", "ungrounded_claims"] = Field(
        description="grounded=자료 기반 답변, greeting_or_smalltalk=인사·정체성·잡담, "
                    "refusal=답변 거절·안내 불가 표명, ungrounded_claims=자료에 없는 내용을 사실처럼 서술")


# query_planner._parse와 같은 사정 — 일부 모델이 temperature 파라미터를 거부(400)하므로
# 실패 시 파라미터 없이 한 번 재시도한다.
_temperature_unsupported = set()


def _parse(client, model, messages):
    if model not in _temperature_unsupported:
        try:
            return client.beta.chat.completions.parse(
                model=model, messages=messages, response_format=AnswerJudgement, temperature=0)
        except Exception:
            _temperature_unsupported.add(model)
    return client.beta.chat.completions.parse(
        model=model, messages=messages, response_format=AnswerJudgement)


def judge_answer(answer_text, evidence, question=None) -> Optional[AnswerJudgement]:
    """답변이 근거 자료를 실제로 썼는지 + 답변 성격을 별도 LLM으로 판정한다.

    answer_text: 마커를 떼어낸 답변 본문.
    evidence: 그 답변을 만들 때 준 근거 텍스트. 검색 게이트로 근거가 비었으면 빈 문자열이어도
              된다 — 그 경우 used_source는 자연히 false, kind 분류만 의미를 갖는다.
    question: 사용자 질문. 판정 규칙들이 "질문에 대한 핵심 답" "질문이 뜻을 묻는 경우"처럼
              질문을 기준으로 삼으므로 반드시 넘기는 것이 정확하다(2026-08-10: 질문 없이
              판정하던 동안 정의형 답변 판정이 롤마다 흔들리는 원인 중 하나였다).

    실패(키 없음·호출 오류·파싱 오류)는 None을 돌려준다. 호출부는 None을 "판정 불가 = 마커의
    원래 판정 유지"로 다뤄야 하며, 여기서 경고 로그를 남긴다."""
    if not answer_text.strip():
        return None
    q_part = f"질문:\n{question}\n\n" if question else ""
    messages = [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": f"{q_part}자료:\n{evidence if str(evidence).strip() else '(검색된 근거 없음)'}\n\n답변:\n{answer_text}"},
    ]
    try:
        from openai import OpenAI
        client = OpenAI()
        model = os.environ["OPENAI_PLANNER_MODEL"]
        r = _parse(client, model, messages)
        return r.choices[0].message.parsed
    except Exception:
        logger.warning("judge_answer 실패 — 마커의 원래 판정을 유지한다", exc_info=True)
        return None


def judge_answer_majority(answer_text, evidence, question=None, votes=3):
    """judge_answer 를 병렬 3회 돌려 다수결로 집계한다 -> AnswerJudgement | None.

    왜: 경계 사례(정의형 답변·소관 밖 응대)에서 단일 판정이 롤마다 뒤집히는 것이 실측됐고,
    규칙 문구를 조여도 오차가 자리만 옮겼다(2026-08-10: 자진반환 오기각 ↔ 보이스피싱 오채택).
    부착·본문 교체·재생성 채택은 전부 이 판정 하나에 걸려 있어, 노이즈 자체를 다수결로 줄인다.
    호출은 마커가 [NO_SOURCE]인 소수 경로에만 발생한다.

    집계: used_source 는 "used=true 이면서 kind=grounded" 표가 과반일 때 true(그때 kind 도
    grounded). 아니면 kind 는 나머지 표의 최빈값. 유효 표가 과반 미만이면 None(판정 불가)."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=votes) as ex:
        results = list(ex.map(lambda _: judge_answer(answer_text, evidence, question), range(votes)))
    valid = [j for j in results if j is not None]
    if len(valid) < (votes // 2 + 1):
        return None
    grounded = sum(1 for j in valid if j.used_source and j.kind == "grounded")
    if grounded >= (len(valid) // 2 + 1):
        return AnswerJudgement(used_source=True, kind="grounded")
    kinds = [j.kind for j in valid if not (j.used_source and j.kind == "grounded")]
    top_kind = max(set(kinds), key=kinds.count)
    return AnswerJudgement(used_source=False, kind=top_kind)


def recheck_source_usage(answer_text, evidence):
    """답변이 근거 자료를 실제로 썼는지 다시 묻는다 -> bool. (judge_answer의 bool 축약 —
    pipeline.py 등 kind가 필요 없는 호출부용. 계약은 교체 전과 동일하다.)

    True면 "근거를 실제로 썼다"(= 마커의 [NO_SOURCE] 판정을 뒤집어 출처를 붙인다).
    호출·파싱 실패는 False로, 마커의 원래 판정을 그대로 둔다."""
    if not str(evidence).strip():
        return False
    j = judge_answer(answer_text, evidence)
    return bool(j) and j.used_source
