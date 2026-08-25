"""질문 정리(triage) — 맥락에 기대는 질문을 독립 질문으로 펴고, 업무 되묻기를 판정한다.

## 왜 필요한가 (2026-08-19)

session_id 로 대화가 저장·복원은 되지만, 답변 파이프라인은 현재 질문 문자열 하나만 본다.
그래서 "그거 신청 기한은요?" 같은 후속 질문이 오면:
  - 검색이 "그거"로 돌아 근거를 못 찾고,
  - Gate 2(임베딩 도메인 판정)가 도메인 신호 없는 파편 문장을 범위외로 오차단할 수 있고,
  - 질의 캐시 키도 파편 문장이라 적중이 안 된다.

## 왜 '입구에서' 인가

파이프라인 입구가 가드레일 → Gate 1 → 질문 정리 → 캐시 → Gate 2 → 플래너 순서(2026-08-25
재편, 그 전 2026-08-19 순서는 가드레일 → 캐시 → Gate 1)라, 플래너에서 맥락을 풀면 이미
캐시·Gate 2 가 파편 문장을 보고 지나간 뒤다. 그래서 Gate 1(원문 기준 룰 필터 — 인사·노이즈·
인젝션은 재작성할 대상이 아니라 그 앞에서 끝낸다) 직후, 캐시 조회 전에 정리한다 — 이후
전 단계(캐시·Gate 2·분해·검색·생성·캐시 적재)가 전부 독립 질문 기준으로 돌아 일관된다.

## 왜 첫 턴에도 부르는가 (2026-08-25)

되묻기 판정이 **Gate 2 보다 앞에** 있어야 하기 때문이다. 종전에는 첫 턴 판정만 플래너
(QueryPlan.needs_clarification)에 얹혀 있었는데, 플래너는 Gate 2 뒤라 "신청 방법 알려줘"처럼
업무 명사가 빠진 질문은 Gate 2 에서 먼저 EXIT 돼 판정 기회 자체가 없었다(실측 s_id 0.536 <
s_ood 0.668, 최근접이 범위외 참조문 "저 대신 신청서를 접수해 줄 수 있나요?").

원인은 Gate 2 in_domain 참조 62문장이 **하나도 빠짐없이** 업무 명사를 달고 있어 '도메인 밖'과
'업무 미정'을 코사인으로 구분하지 못하는 것이다. 참조 사전에 업무 명사 없는 절차 문장을
더하는 교정은 s_id 를 모든 절차형 질문에 대해 올려(그 문장들은 인접도메인 OOD 와 0.6대로
붙는다 — "신청 방법 알려줘" ↔ "대출 상담 좀 받고 싶은데 어디로 문의하나요" 0.616) 차단력을
직접 깎으므로, 참조 사전 대신 판정 위치를 게이트 앞으로 옮겼다.

그래서 되묻기 판정은 이제 **이 모듈 한 곳**이고, 첫 턴과 후속 턴이 같은 경로를 돈다
(종전의 "이력 있으면 재작성기, 없으면 플래너" 이중 판정 규약은 사라졌다).

## 원칙

- 모든 턴에서 호출한다. 첫 턴은 펼 맥락이 없어 재작성이 항상 no-op(rewritten=false)이고
  되묻기 판정만 의미가 있다 — 그래서 첫 턴에는 캐시 키가 바뀌지 않는다.
- 자립적인 질문은 원문 그대로 돌려받는다(rewritten=false) — 불필요한 재작성은 검색 질의를
  오염시킨다(query_planner 의 "원문 낱말" 원칙과 동일한 이유).
- 재작성은 질문·이전 턴에 실제로 나온 낱말로만 한다. 새 기관명·제도명을 지어 붙이지 않는다.
- 실패는 None — 호출부가 원문으로 계속한다(fail-open). 무음 폴백 금지 원칙(source_check ·
  query_planner 전례)대로 경고 로그를 남긴다. **이 콜이 실패한 턴은 되묻기 판정이 없다**:
  백업 판정기를 두지 않는 것이 판정 일원화의 대가다(종전엔 플래너가 받아줬다).

플래너(query_planner)와 같은 OpenAI structured output · 같은 모델을 쓴다(신규 의존성 없음).
모든 턴에 LLM +1콜이 든다 — 첫 턴 +1콜은 2026-08-25 팀 결정으로 감수한 비용이다. 캐시(0-3)
보다 앞이라 캐시 적중 턴도 이 콜을 먼저 쓴다(캐시 앞이어야 후속 턴 캐시 키가 독립 질문이 된다).
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
- [이전 대화]가 "(없음)"이면 이번이 대화의 첫 질문입니다. 채워 넣을 맥락이 없으므로 rewritten=false, standalone_question 에는 새 질문을 **원문 그대로** 넣습니다 — 이때 판단할 것은 되묻기 여부뿐입니다.
- 새 질문이 그 자체로 완결되면 rewritten=false, standalone_question 에는 새 질문을 **원문 그대로** 넣습니다. 어투·문장부호·띄어쓰기도 바꾸지 않습니다.
- 새 질문이 "그거", "거기", "그럼", "위에서 말한" 같은 지시어나 생략으로 이전 대화에 기대고 있으면 rewritten=true, 이전 대화에서 가리키는 대상을 찾아 채운 독립 질문을 씁니다.
- rewritten=true 는 이전 대화의 내용을 **채워 넣어야만** 이해되는 경우에만 씁니다. 이미 완결된 질문을 더 정중하게·매끄럽게 고쳐 쓰기 위해 rewritten=true 를 쓰지 마세요 — 반말·비문·오타가 있어도 완결되면 rewritten=false 입니다.
- 채울 때는 새 질문과 이전 대화에 실제로 나온 낱말만 씁니다. 대화에 없는 기관명·제도명·수식어를 지어내지 않습니다.
- rewritten=true 로 다시 쓸 때만: 독립 질문은 검색어로 그대로 쓰이므로 짧고 명확한 한 문장의 정중한 의문문으로 만듭니다.
- 새 질문이 이전 대화와 무관한 새 주제면 rewritten=false 로 원문을 그대로 둡니다.
- 새 질문이 업무명 하나뿐인 짧은 답이고 직전 챗봇 턴이 어떤 업무를 찾는지 묻는 질문이면: 사용자가 그 직전에 하려던 질문에 선택한 업무를 채워 독립 질문으로 합성합니다(rewritten=true). 예: 사용자가 "신청한 결과 언제 받을 수 있어요?"라고 물었고 챗봇이 업무를 되물었으며 새 질문이 "예금보험금·가지급금"이면 → "예금보험금 신청 결과는 언제 받을 수 있나요?"

[되묻기 판단 — needs_clarification]
예금보험공사가 다루는 업무: 착오송금 반환지원 / 예금보험금·가지급금 / 미수령금 찾기 / 은닉재산 신고 / 채무조정 / 예금자보호제도.
- 새 질문이 특정 업무를 전제로 하는데(신청·접수·링크·절차·서류·자격·처리 결과·기한·금액·한도·대상 등) 새 질문에도 이전 대화에도 어느 업무인지 정해져 있지 않으면 needs_clarification=true 로 표시합니다.
- 사용자가 지금까지의 업무를 제외하면서("다른 업무", "그거 말고") 새 업무를 지목하지 않은 경우도 needs_clarification=true 입니다 — 이전 대화의 업무로 채우면 안 됩니다.
- 어느 업무인지 정해지거나(질문에 명시, 또는 이전 대화로 자연스럽게 해소), 업무를 특정하지 않아도 답할 수 있는 일반 질문이면 needs_clarification=false 입니다.
- 확실하지 않으면 needs_clarification=false 입니다 — 되묻기가 잦으면 사용자를 번거롭게 합니다.
- needs_clarification=true 인 경우에도 standalone_question 에는 새 질문 원문을 넣습니다.
- 예: (이전 대화 없음) "신청 링크 알려줘" → needs_clarification=true. 어느 업무의 신청인지 질문에도 없고 채울 근거도 없습니다.
- 예: (이전 대화 없음) "얼마까지 가능해?" → needs_clarification=true. 착오송금 반환 한도인지 예금자보호 한도인지 정해지지 않았습니다.
- 예: (이전 대화 없음) "종합소득세 신고는 어떻게 하나요?" → needs_clarification=false. 예금보험공사 업무가 아닌 주제는 되묻기 대상이 아닙니다 — 업무를 골라도 답할 수 없으므로 그대로 통과시킵니다."""


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


# 이력이 없는 첫 턴에도 이 모듈을 부르므로(모듈 docstring "왜 첫 턴에도 부르는가"),
# 빈 이력을 빈 문자열로 넘기면 프롬프트의 [이전 대화] 자리가 통째로 비어, LLM 이 이력이
# 잘려 나간 것인지 원래 없는 것인지 구분할 수 없다. 없음을 표식으로 명시한다.
NO_HISTORY = "(없음)"


def _format_history(history):
    """[(role, text)] → 재작성 컨텍스트 텍스트. 최근 MAX_TURNS 개만, 턴당 길이 제한.
    빈 이력(첫 턴)은 NO_HISTORY — 프롬프트의 첫 턴 규칙이 이 표식을 본다."""
    if not history:
        return NO_HISTORY
    lines = []
    for role, text in history[-MAX_TURNS:]:
        who = "사용자" if role == "user" else "챗봇"
        lines.append(f"{who}: {(text or '')[:MAX_CHARS_PER_TURN]}")
    return "\n".join(lines)


# LLM 이 독립 질문을 따옴표로 감싸 내놓는 경우가 있다 — 2026-08-21 실측: query_cache 에
# '"반환지원 대상이 아닌 경우는 어떤 경우인가요?"' 가 따옴표 없는 같은 질문(hit=3)과 별도
# 행으로 쌓여 있었다. standalone_question 은 그대로 검색 질의이자 캐시 키라, 감싼 따옴표
# 하나가 검색을 오염시키고 캐시 적중을 막는다. 짝이 맞을 때만 벗긴다 — 한쪽에만 있는
# 따옴표는 원문 인용의 일부일 수 있어 건드리지 않는다.
_QUOTE_PAIRS = (('"', '"'), ("'", "'"), ('“', '”'), ('‘', '’'),
                ('「', '」'), ('『', '』'))


def _unwrap_quotes(text: str) -> str:
    """양끝을 감싼 따옴표 한 쌍을 벗긴다. 중첩이면 반복하고, 짝이 안 맞으면 그대로 둔다."""
    while len(text) >= 2:
        for open_q, close_q in _QUOTE_PAIRS:
            if text.startswith(open_q) and text.endswith(close_q):
                text = text[len(open_q):-len(close_q)].strip()
                break
        else:
            return text
    return text


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
        if parsed is None:
            logger.warning("재작성 응답이 비어 원문으로 계속 — 질문: %r", query)
            return None
        parsed.standalone_question = _unwrap_quotes(parsed.standalone_question.strip())
        if not parsed.standalone_question:
            logger.warning("재작성 응답이 비어 원문으로 계속 — 질문: %r", query)
            return None
        return parsed
    except Exception:
        logger.warning("질문 정리(재작성·되묻기 판정) 실패 — 원문으로 계속. 질문: %r",
                       query, exc_info=True)
        return None


def triage_query(query: str, history: list) -> RewriteResult | None:
    """질문 하나를 독립 질문으로 펴고, 업무 되묻기 필요 여부를 함께 판정한다.

    2026-08-25 에 rewrite_followup 에서 이름을 바꿨다 — 이력이 없는 첫 턴에도 부르게 되면서
    "followup" 이 실제 동작과 어긋났고, 이 콜의 주된 값이 재작성이 아니라 되묻기 판정인
    턴(첫 턴)이 생겼기 때문이다.

    query: 이번 턴 사용자 질문 원문.
    history: [(role, text), ...] — conversation.recent_messages() 결과(과거→최근 순).
             **비어 있어도 호출한다**(첫 턴). 첫 턴은 펼 맥락이 없어 재작성이 no-op 이고
             되묻기 판정만 나온다 — 사유는 모듈 docstring "왜 첫 턴에도 부르는가".
    반환: RewriteResult — standalone_question 은 독립 질문(원문이 자립적이면 원문 그대로),
          needs_clarification 은 어느 업무인지 특정 불가 판정(호출부가 되묻기로 전환).
          실패(키 없음·호출 오류·파싱 오류·빈 결과)는 None — 호출부는 원문으로 계속하며,
          그 턴은 되묻기 판정 없이 지나간다(백업 판정기 없음).
    """
    if not query.strip():
        return None
    return _run(query, _format_history(history))
