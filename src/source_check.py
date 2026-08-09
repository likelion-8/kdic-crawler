"""출처 부착 재확인 — 마커가 [NO_SOURCE]라고 판정했을 때만 LLM에게 한 번 더 묻는다.

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

## 왜 [NO_SOURCE]일 때만 부르는가

같은 107건에서 마커의 실패는 한 방향뿐이었다.
  - [SOURCE_USED]라고 말한 28건: 오판 0건
  - [NO_SOURCE]라고 말한 79건: 33건 오판(42%)
"썼다"는 판정은 틀린 적이 없으므로 건드리지 않는다. 틀리는 쪽만 재확인하면 (a) 마커가
완벽했던 축(거절·인사에 무관한 출처가 안 붙는 것)을 그대로 보존하고 (b) 추가 LLM 호출이
[NO_SOURCE] 답변에만 발생해 비용도 그만큼만 는다.

## 실패 시 방향

호출 실패·응답 파싱 실패는 전부 False(= 마커의 원래 [NO_SOURCE] 판정 유지)로 떨어진다.
이 모듈이 죽어도 동작은 이 기능을 켜기 전과 정확히 같아진다 — 절대 더 나빠지지 않는다.
"""
import re

from llm_client import call_hyperclova

SYSTEM_INSTRUCTION = """당신은 RAG 챗봇의 답변 검사기입니다. 질문에 답하지 말고, 아래 한 가지만 판정하세요.

판정할 것: "답변"이 "자료"에 담긴 내용을 실제로 가져다 썼는가?

- 답변에 담긴 사실(제도 이름, 절차, 조건, 금액, 기한, 대상 등)이 자료에 있는 내용과 대응되면 YES입니다.
  표현을 바꿔 쓰거나 요약했어도, 내용의 출처가 자료면 YES입니다.
- 답변이 인사말·잡담이거나, "확인할 수 없습니다" "안내가 어렵습니다"처럼 자료로 답하지
  못했다고 밝히는 내용뿐이면 NO입니다.
- 답변이 자료와 전혀 상관없는 주제를 다루면 NO입니다.
- 자료로 답한 부분과 거절이 섞여 있으면, 자료로 답한 부분이 하나라도 있으면 YES입니다.

출력은 다른 말 없이 정확히 YES 또는 NO 한 단어만 쓰세요."""

# 판정 응답은 한 단어여야 하지만, 앞에 볼드·따옴표·공백이 붙는 정도의 흔들림은 흡수한다
# (마커에서 겪은 표기 변형과 같은 계열). 그 외 형태는 파싱 실패로 보고 안전한 쪽으로 떨어진다.
_VERDICT_RE = re.compile(r"^\W*(YES|NO)\b", re.IGNORECASE)


def _build_prompt(answer_text, evidence):
    human = (
        f"자료:\n{evidence}\n\n"
        f"답변:\n{answer_text}\n\n"
        "판정(YES 또는 NO):"
    )
    return [("system", SYSTEM_INSTRUCTION), ("human", human)]


def recheck_source_usage(answer_text, evidence):
    """답변이 근거 자료를 실제로 썼는지 LLM에게 다시 묻는다 -> bool.

    answer_text: 마커를 떼어낸 답변 본문(prompt_builder._strip_no_source_marker 결과).
    evidence: 그 답변을 만들 때 준 근거 텍스트(informational은 청크 본문들, civil_petition은
              절차 안내 근거). 생성 때와 같은 자료를 그대로 넘겨야 판정이 의미를 갖는다.

    True면 "근거를 실제로 썼다"(= 마커의 [NO_SOURCE] 판정을 뒤집어 출처를 붙인다).
    호출·파싱 실패는 False로, 마커의 원래 판정을 그대로 둔다."""
    if not answer_text.strip() or not str(evidence).strip():
        return False
    try:
        response = call_hyperclova(_build_prompt(answer_text, evidence))
    except Exception:
        return False
    m = _VERDICT_RE.match(response.strip())
    return bool(m) and m.group(1).upper() == "YES"
