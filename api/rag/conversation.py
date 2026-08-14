"""대화 저장·복원 — chat_sessions / chat_messages.

api/rag/sse.py 가 답변을 흘리는 도중에 두 번 부른다. 사용자 메시지는 스트리밍 시작 전에,
답변 메시지는 done 직전에 저장한다. 그 이유가 이 파일의 핵심 설계다:

- 질문을 먼저 저장하는 이유: 나중에 저장하면 LLM 이 실패한 턴의 질문이 기록에 안 남는다.
  사용자는 분명 물어봤는데 복원하면 없다. 질문은 받은 시점에 이미 확정된 사실이다.
- 답변을 나중에 저장하는 이유: sources/out_of_scope 는 스트리밍이 끝나고 source_check 판정이
  나야 확정된다.

실패 처리: 저장이 실패해도 답변은 내보낸다(사용자가 답을 못 받는 건 과하다). 다만
rag_logger 처럼 조용히 넘기지 않고 경고 로그를 남긴다 — 대화에 구멍이 생긴 원인을 나중에
찾을 수 있어야 한다.

## 인증 — 2026-08-06 팀 결정: 두지 않는다

session_id 를 아는 사람은 누구나 그 대화를 읽는다. uuid4 hex(128비트)라 추측은 사실상
불가능하지만 주소창 /chat/{id} 에 노출되므로, 링크 공유·브라우저 히스토리로 새어나가면
그 대화는 열린다. 이 위험을 알고 받아들인 결정이다(빠뜨린 것이 아니다).
쿠키로 세션 소유를 확인하려면 프론트도 함께 바뀌어야 하므로, 필요해지면 그때 함께 붙인다.

## 마스킹 — 2026-08-06 팀 결정: 원문 저장, 관리자 조회 경로에서 마스킹

여기서는 사용자 질문·답변을 원문으로 저장한다. 본인에게 자기가 쓴 그대로를 보여줘야 복원이
의미가 있기 때문이다. 관리자 대화 로그(AD-005)는 마스킹된 것만 봐야 한다는 요구(핸드오프
§6 G3)를 이 테이블에 반영하지 않고, **그쪽 조회 API 가 응답을 만들 때 마스킹**한다.
즉 저장본은 하나이고 마스킹은 읽는 쪽 책임이다 — AD-005 를 만드는 사람이 챙겨야 한다.
"""
import logging

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db import get_session
from schema import chat_messages, chat_sessions

logger = logging.getLogger(__name__)


def _touch_session(session, session_id):
    """세션이 없으면 만들고, 있으면 last_activity_at 만 지금으로 올린다(24시간 판정 기준)."""
    session.execute(
        pg_insert(chat_sessions)
        .values(session_id=session_id)
        .on_conflict_do_update(
            index_elements=["session_id"],
            set_={"last_activity_at": func.now()},
        )
    )


def _next_seq(session, session_id):
    """세션 내 다음 순번. created_at 정렬만으로는 같은 순간에 들어간 user/assistant 순서가
    뒤집힐 수 있어 명시적인 순번을 쓴다."""
    current = session.execute(
        select(func.max(chat_messages.c.seq)).where(chat_messages.c.session_id == session_id)
    ).scalar()
    return (current or 0) + 1


def turn_count(session_id: str) -> int:
    """이 세션에 쌓인 메시지 수. 질의 캐시의 '단일 턴' 적격 판정용(sse.py) —
    질문 저장 전에 불러야 0 == 첫 턴이 성립한다. 실패하면 캐시만 포기하면 되므로
    예외를 올리지 않고 -1(부적격)을 돌려준다."""
    try:
        from db import get_session
        from schema import chat_messages
        from sqlalchemy import func, select
        with get_session() as session:
            return session.execute(
                select(func.count()).select_from(chat_messages)
                .where(chat_messages.c.session_id == session_id)).scalar_one()
    except Exception:  # noqa: BLE001
        logger.exception("turn_count 실패 — 캐시 부적격으로 처리")
        return -1


def save_user_message(session_id: str, text: str) -> None:
    """사용자 질문을 저장한다. 스트리밍 시작 전에 부른다."""
    try:
        with get_session() as s:
            _touch_session(s, session_id)
            s.execute(chat_messages.insert().values(
                session_id=session_id, seq=_next_seq(s, session_id),
                role="user", text=text,
            ))
    except Exception:
        logger.warning("대화 저장 실패(user) session=%s — 답변은 계속한다", session_id, exc_info=True)


def save_assistant_message(session_id: str, request_id: str, resp) -> None:
    """답변을 저장한다. done 직전에 부른다.

    resp(ChatResponse) 를 그대로 옮겨 담는다 — done 이벤트가 나가는 모양과 저장 모양을 같게
    두는 것이 이 함수의 규칙이다. 그래서 복합 질문이면 최상위 sources/attachments 는 빈 배열이
    되고 근거는 전부 sub_answers 로 들어간다(to_chat_response 가 이미 그렇게 만든다).

    한때 하위 답변의 출처를 최상위로 평탄화했는데, 그건 프론트 RestoredMessage.response 에
    sub_answers 자리가 없던 시절의 우회였다. 2026-08-06 프론트 계약에 추가됐으므로(types.ts 의
    Pick<ChatResponse,'sources'|'attachments'|'sub_answers'|'out_of_scope'>) 구조를 그대로 남긴다.
    평탄화를 되살리면 최상위와 하위 양쪽에 출처가 있어 화면에 두 배로 보인다.
    """
    try:
        with get_session() as s:
            _touch_session(s, session_id)
            s.execute(chat_messages.insert().values(
                session_id=session_id, seq=_next_seq(s, session_id),
                role="assistant", text=resp.answer, request_id=request_id,
                sources=[x.model_dump() for x in resp.sources],
                attachments=[x.model_dump() for x in resp.attachments],
                sub_answers=[x.model_dump() for x in resp.sub_answers],
                out_of_scope=resp.out_of_scope,
            ))
    except Exception:
        logger.warning("대화 저장 실패(assistant) session=%s — 답변은 계속한다",
                       session_id, exc_info=True)
