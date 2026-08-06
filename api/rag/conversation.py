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

⚠️ 인증이 없다. session_id 를 아는 사람은 누구나 그 대화를 읽는다(uuid4 hex 라 추측은 어렵지만
주소창 /chat/{id} 에 노출된다). 프론트 계약에 인증 절차가 없어 그대로 맞췄고, 쿠키로 세션
소유를 확인하는 건 프론트와 함께 정해야 하는 별도 작업이다.

⚠️ 사용자 질문·답변을 마스킹하지 않고 원문으로 저장한다. 본인에게 자기가 쓴 그대로를 보여줘야
복원이 의미가 있기 때문이다. 관리자 대화 로그(AD-005)는 마스킹된 것만 봐야 한다는 요구가
있으므로(핸드오프 §6 G3), 그쪽 조회 경로에서 마스킹하거나 별도 저장본을 두는 결정이 필요하다.
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

    resp 는 ChatResponse 다. 복합 질문이면 최상위 sources/attachments 가 비고 근거가
    sub_answers 로 내려가므로, 복원 시 출처를 잃지 않도록 하위의 것을 합쳐서 담는다
    (프론트 RestoredMessage.response 에 sub_answers 자리가 없다 — 아래 주석 참고).
    """
    try:
        sources = [s.model_dump() for s in resp.sources]
        attachments = [a.model_dump() for a in resp.attachments]
        # ⚠️ 복합 질문의 한계: 프론트 RestoredMessage.response 는
        # Pick<ChatResponse,'sources'|'attachments'|'out_of_scope'> 라 sub_answers 자리가 없다.
        # 그대로 두면 복원된 복합 답변은 출처가 통째로 사라지므로, 하위의 출처를 평탄화해
        # 최소한 '어떤 문서를 근거로 했는지'는 남긴다. 하위별 묶음 구조는 복원되지 않는다
        # — 되살리려면 프론트 계약에 sub_answers 를 추가해야 한다.
        for sub in resp.sub_answers:
            sources.extend(s.model_dump() for s in sub.sources)
            attachments.extend(a.model_dump() for a in sub.attachments)

        with get_session() as s:
            _touch_session(s, session_id)
            s.execute(chat_messages.insert().values(
                session_id=session_id, seq=_next_seq(s, session_id),
                role="assistant", text=resp.answer, request_id=request_id,
                sources=sources, attachments=attachments,
                out_of_scope=resp.out_of_scope,
            ))
    except Exception:
        logger.warning("대화 저장 실패(assistant) session=%s — 답변은 계속한다",
                       session_id, exc_info=True)
