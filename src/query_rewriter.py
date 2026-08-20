"""멀티턴 후속 질문 재작성 — 대화 맥락에 기대는 질문을 독립 질문으로 편다.

## 왜 필요한가 (2026-08-19)

session_id 로 대화가 저장·복원은 되지만, 답변 파이프라인은 현재 질문 문자열 하나만 본다.
그래서 "그거 신청 기한은요?" 같은 후속 질문이 오면:
  - 검색이 "그거"로 돌아 근거를 못 찾고,
  - Gate 2(임베딩 도메인 판정)가 도메인 신호 없는 파편 문장을 범위외로 오차단할 수 있고,
  - 질의 캐시 키도 파편 문장이라 적중이 안 된다.

## 왜 '입구에서 재작성'인가

파이프라인 입구가 가드레일 → 캐시 → Gate 1 → Gate 2 → 플래너 순서(2026-08-19 재편)라,
플래너에서 맥락을 풀면 이미 캐시·게이트가 파편 문장을 보고 지나간 뒤다. 그래서 가드레일
(원문 금칙어 검사) 직후, 캐시 조회 전에 재작성한다 — 이후 전 단계(캐시·게이트·분해·검색·
생성·캐시 적재)가 전부 독립 질문 기준으로 돌아 일관된다.

## 원칙

- 이전 턴이 없으면 호출하지 않는다(sse 가 가드) — 단일 턴 동작·비용은 정확히 종전과 같다.
- 자립적인 질문은 원문 그대로 돌려받는다(rewritten=false) — 불필요한 재작성은 검색 질의를
  오염시킨다(query_planner 의 "원문 낱말" 원칙과 동일한 이유).
- 재작성은 질문·이전 턴에 실제로 나온 낱말로만 한다. 새 기관명·제도명을 지어 붙이지 않는다.
- 실패는 None — 호출부가 원문으로 계속한다(fail-open). 무음 폴백 금지 원칙(source_check ·
  query_planner 전례)대로 경고 로그를 남긴다.

플래너(query_planner)와 같은 OpenAI structured output · 같은 모델을 쓴다(신규 의존성 없음).
후속 턴에만 LLM +1콜이 든다(첫 턴 0콜).
"""
import logging
import os

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from retrieval import ROOT  # .env 위치 재사용(query_planner 와 동일)

load_dotenv(ROOT / ".env")

logger = logging.getLogger(__name__)

_MODEL = os.environ.get("OPENAI_PLANNER_MODEL") or "gpt-5.6-luna"

# 재작성 컨텍스트에 넣는 최근 턴 수·턴당 길이 제한. 답변 전문을 다 넣으면 토큰만 늘고
# 재작성 품질에는 기여가 없다 — 지시어 해소에는 최근 주제가 무엇인지면 충분하다.
MAX_TURNS = 6          # user/assistant 합산 메시지 수 (= 최근 3문답)
MAX_CHARS_PER_TURN = 300

SYSTEM_PROMPT = """당신은 예금보험공사(KDIC) 챗봇의 질문 정리기입니다. 사용자의 새 질문이 이전 대화 없이도 이해되는지 판단하고, 아니라면 독립적인 질문으로 다시 씁니다. 질문에 답하지 마세요.

[재작성 규칙]
- 새 질문이 그 자체로 완결되면 rewritten=false, standalone_question 에는 새 질문을 **원문 그대로** 넣습니다.
- 새 질문이 "그거", "거기", "그럼", "위에서 말한" 같은 지시어나 생략으로 이전 대화에 기대고 있으면 rewritten=true, 이전 대화에서 가리키는 대상을 찾아 채운 독립 질문을 씁니다.
- 채울 때는 새 질문과 이전 대화에 실제로 나온 낱말만 씁니다. 대화에 없는 기관명·제도명·수식어를 지어내지 않습니다.
- 독립 질문은 검색어로 그대로 쓰입니다 — 짧고 명확한 한 문장의 정중한 의문문으로 만듭니다.
- 새 질문이 이전 대화와 무관한 새 주제면 rewritten=false 로 원문을 그대로 둡니다.
- 새 질문이 업무명 하나뿐인 짧은 답이고 직전 챗봇 턴이 어떤 업무를 찾는지 묻는 질문이면: 사용자가 그 직전에 하려던 질문에 선택한 업무를 채워 독립 질문으로 합성합니다(rewritten=true). 예: 사용자가 "신청한 결과 언제 받을 수 있어요?"라고 물었고 챗봇이 업무를 되물었으며 새 질문이 "예금보험금·가지급금"이면 → "예금보험금 신청 결과는 언제 받을 수 있나요?"

[되묻기 판단 — needs_clarification]
예금보험공사가 다루는 업무: 착오송금 반환지원 / 예금보험금·가지급금 / 미수령금 찾기 / 은닉재산 신고 / 채무조정 / 예금자보호제도.
- 새 질문이 특정 업무를 전제로 하는데(신청·접수·링크·절차·서류·자격·처리 결과·기한 등) 새 질문에도 이전 대화에도 어느 업무인지 정해져 있지 않으면 needs_clarification=true 로 표시합니다.
- 사용자가 지금까지의 업무를 제외하면서("다른 업무", "그거 말고") 새 업무를 지목하지 않은 경우도 needs_clarification=true 입니다 — 이전 대화의 업무로 채우면 안 됩니다.
- 어느 업무인지 정해지거나(질문에 명시, 또는 이전 대화로 자연스럽게 해소), 업무를 특정하지 않아도 답할 수 있는 일반 질문이면 needs_clarification=false 입니다.
- 확실하지 않으면 needs_clarification=false 입니다 — 되묻기가 잦으면 사용자를 번거롭게 합니다.
- needs_clarification=true 인 경우에도 standalone_question 에는 새 질문 원문을 넣습니다."""


class RewriteResult(BaseModel):
    """재작성 판단 + 결과. rewritten=false 면 standalone_question == 원문이어야 한다."""
    rewritten: bool = Field(description="이전 대화 맥락을 채워 다시 썼으면 true")
    standalone_question: str = Field(description="이전 대화 없이도 이해되는 독립 질문(원문 유지 포함)")
    needs_clarification: bool = Field(
        description="어느 업무에 대한 질문인지 정해지지 않아 업무를 되물어야 하면 true")


_openai = {}
_temperature_unsupported = set()   # query_planner 와 동일한 사정(모델별 temperature 지원 차이)


def _get_client():
    if "c" not in _openai:
        from openai import OpenAI
        _openai["c"] = OpenAI()
    return _openai["c"]


def _parse(client, model, messages):
    if model not in _temperature_unsupported:
        try:
            return client.beta.chat.completions.parse(
                model=model, messages=messages, response_format=RewriteResult, temperature=0)
        except Exception as e:
            if "temperature" not in str(e).lower():
                raise
            _temperature_unsupported.add(model)
    return client.beta.chat.completions.parse(
        model=model, messages=messages, response_format=RewriteResult)


def _format_history(history):
    """[(role, text)] → 재작성 컨텍스트 텍스트. 최근 MAX_TURNS 개만, 턴당 길이 제한."""
    lines = []
    for role, text in history[-MAX_TURNS:]:
        who = "사용자" if role == "user" else "챗봇"
        lines.append(f"{who}: {(text or '')[:MAX_CHARS_PER_TURN]}")
    return "\n".join(lines)


def _run(query: str, history_text: str) -> RewriteResult | None:
    """재작성·되묻기 판정 LLM 콜 공통 본체. 실패는 None(fail-open) — 호출부가 원문으로 계속."""
    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": f"[이전 대화]\n{history_text}\n\n[새 질문]\n{query}"},
        ]
        r = _parse(_get_client(), _MODEL, messages)
        parsed = r.choices[0].message.parsed
        if parsed is None or not parsed.standalone_question.strip():
            logger.warning("재작성 응답이 비어 원문으로 계속 — 질문: %r", query)
            return None
        parsed.standalone_question = parsed.standalone_question.strip()
        return parsed
    except Exception:
        logger.warning("질문 정리(재작성·되묻기 판정) 실패 — 원문으로 계속. 질문: %r",
                       query, exc_info=True)
        return None


def rewrite_followup(query: str, history: list) -> RewriteResult | None:
    """후속 질문 하나를 독립 질문으로 펴고, 업무 되묻기 필요 여부를 함께 판정한다.

    query: 이번 턴 사용자 질문 원문.
    history: [(role, text), ...] — conversation.recent_messages() 결과(과거→최근 순).
             비어 있으면 즉시 None (LLM 호출 없음 — 첫 턴 비용·동작 불변 보장).
    반환: RewriteResult — standalone_question 은 독립 질문(원문이 자립적이면 원문 그대로),
          needs_clarification 은 어느 업무인지 특정 불가 판정(호출부가 되묻기로 전환).
          실패(키 없음·호출 오류·파싱 오류·빈 결과)는 None — 호출부는 원문으로 계속한다.
    """
    if not history or not query.strip():
        return None
    return _run(query, _format_history(history))


def triage_first_turn(query: str) -> RewriteResult | None:
    """첫 턴(무이력) 질문의 되묻기 판정 — 재작성기와 같은 콜·같은 프롬프트를 이력 없이 돌린다.

    모든 첫 턴에 부르면 "첫 턴 0콜" 비용 약속이 깨진다 — 반드시 clarify.first_turn_candidate()
    프리스크린을 통과한 질문에만 부를 것(sse 0-2.5 가 그 규약을 지킨다). 실패는 None(fail-open).
    """
    if not query.strip():
        return None
    return _run(query, "(첫 대화 — 이전 턴 없음)")
