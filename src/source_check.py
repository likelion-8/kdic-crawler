"""답변 사후 검증 — 생성과 분리된 별도 LLM 1콜로 근거 실사용·질문-답변 적절성을 판정한다.

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

## 2026-08-14 팀 결정 — 단일 1콜(validate_answer)로 통일 + 모든 답변으로 확대

위 "[NO_SOURCE]일 때만" 원칙과 3표 다수결(judge_answer_majority)을 폐지했다. 이제 모든
경로(웹 api/rag/answer.py · CLI src/pipeline.py · 관리자 평가 api/routers/admin_prompt.py)가
validate_answer 1콜로 **모든 답변**을 검증한다 — 근거 실사용(used_source, 마커를 양방향
오버라이드)에 더해 질문-답변 적절성(appropriate: 질문에 실제로 답했는가, 근거와 모순되지
않는가)까지 함께 판정한다. 답변당 LLM +1콜의 지연 증가는 팀이 수용했다.
"""
import logging
import os
from typing import Literal, Optional

from pydantic import BaseModel, Field

from observability import record_openai_generation

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

# 2026-08-14 팀 결정: 검증을 모든 답변으로 확대하면서 "질문-답변 적절성" 축을 추가했다.
# 기존 판정 규칙(SYSTEM_INSTRUCTION)은 그대로 두고 축 하나만 덧붙인다.
VALIDATE_INSTRUCTION = SYSTEM_INSTRUCTION + """

추가로 판정할 것: "답변"이 "질문"에 대한 응답으로 적절한가? (appropriate)
- 답변이 질문이 물은 것에 실제로 답했으면 true입니다. 인사에 인사로 응대하거나,
  범위 밖·답변 불가 사유를 안내하는 정상 거절도 적절한 응답이므로 true입니다.
- 답변이 질문과 동떨어진 내용을 다루거나(동문서답), 자료에 있는 내용과 모순되는 사실을
  서술하면 false입니다."""


class AnswerJudgement(BaseModel):
    """근거 사용 여부 + 답변 성격. kind는 범위외 답변의 본문 교체 판단에 쓰인다(api/rag/answer.py)."""
    used_source: bool = Field(description="답변의 사실이 자료 내용과 대응되면 true. 인사·잡담·거절문이거나 자료와 무관하면 false.")
    kind: Literal["grounded", "greeting_or_smalltalk", "refusal", "ungrounded_claims"] = Field(
        description="grounded=자료 기반 답변, greeting_or_smalltalk=인사·정체성·잡담, "
                    "refusal=답변 거절·안내 불가 표명, ungrounded_claims=자료에 없는 내용을 사실처럼 서술")


class AnswerValidation(AnswerJudgement):
    """AnswerJudgement + 질문-답변 적절성 축(2026-08-14 팀 결정)."""
    appropriate: bool = Field(
        description="답변이 질문에 실제로 답했거나 정상적으로 응대·거절했으면 true. "
                    "동문서답이거나 자료 내용과 모순되면 false.")


# query_planner._parse와 같은 사정 — 일부 모델이 temperature 파라미터를 거부(400)하므로
# 실패 시 파라미터 없이 한 번 재시도한다.
_temperature_unsupported = set()


def _parse(client, model, messages, schema=AnswerJudgement):
    if model not in _temperature_unsupported:
        try:
            return client.beta.chat.completions.parse(
                model=model, messages=messages, response_format=schema, temperature=0)
        except Exception:
            _temperature_unsupported.add(model)
    return client.beta.chat.completions.parse(
        model=model, messages=messages, response_format=schema)


def validate_answer(question, answer_text, evidence) -> Optional[AnswerValidation]:
    """답변 하나를 단일 LLM 1콜로 검증한다 -> AnswerValidation | None.

    2026-08-14 팀 결정 2건의 구현체(모듈 docstring 참고):
    - 3표 다수결(judge_answer_majority) 폐지 — 모든 경로가 이 단일 호출로 통일.
    - [NO_SOURCE] 한정 재확인(recheck_source_usage) 폐지 — **모든 답변**을 검증하며
      used_source 가 마커 판정을 양방향으로 오버라이드하고, appropriate(질문에 실제로
      답했는가·근거와 모순되지 않는가) 축을 함께 판정한다.

    question: 사용자 질문. 판정 규칙들이 "질문에 대한 핵심 답" "질문이 뜻을 묻는 경우"처럼
              질문을 기준으로 삼으므로 반드시 넘긴다(2026-08-10: 질문 없이 판정하던 동안
              정의형 답변 판정이 롤마다 흔들리는 원인 중 하나였다).
    answer_text: 마커를 떼어낸 답변 본문.
    evidence: 그 답변을 만들 때 준 근거 텍스트. 검색 게이트로 근거가 비었으면 빈 문자열이어도
              된다 — 그 경우 used_source는 자연히 false, kind·appropriate 만 의미를 갖는다.

    실패(키 없음·호출 오류·파싱 오류)는 None — fail-open: 호출부는 마커의 원래 판정을
    유지하고 appropriate 는 통과로 다룬다(검증이 답변을 막으면 안 된다). 조용히 죽지
    않도록 경고 로그는 여기서 남긴다."""
    if not answer_text.strip():
        return None
    q_part = f"질문:\n{question}\n\n" if question else ""
    messages = [
        {"role": "system", "content": VALIDATE_INSTRUCTION},
        {"role": "user", "content": f"{q_part}자료:\n{evidence if str(evidence).strip() else '(검색된 근거 없음)'}\n\n답변:\n{answer_text}"},
    ]
    try:
        from openai import OpenAI
        client = OpenAI()
        model = os.environ["OPENAI_PLANNER_MODEL"]
        r = _parse(client, model, messages, schema=AnswerValidation)
        record_openai_generation("validate_answer_llm", r, input=messages)
        return r.choices[0].message.parsed
    except Exception:
        logger.warning("validate_answer 실패 — 마커의 원래 판정을 유지한다(fail-open)", exc_info=True)
        return None
