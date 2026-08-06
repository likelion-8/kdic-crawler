"""GET /api/sessions/{session_id} — 새로고침·재방문 시 대화 복원.

프론트는 /chat/{session_id} 주소로 들어올 때 이걸 호출하고, 복원이 끝나면 화면의 말풍선
목록을 통째로 교체한다. 실패하면 재시도하지 않고(retry:false) session_id 를 버린 뒤 웰컴
화면에서 새로 시작한다 — 그래서 만료·부재를 애매하게 200 으로 주면 안 되고 404 로 끊어야 한다.

인증을 두지 않는다(2026-08-06 팀 결정). session_id 만 있으면 누구나 조회된다 — 위험과 근거는
api/rag/conversation.py 의 상단 주석에 적어 뒀다. 나중에 인증을 붙이면 여기에 의존성이 하나
추가되는 형태가 된다.

sync def 로 둔다: DB 접근이 블로킹이라 async 로 두면 이벤트 루프를 막는다.
"""
import logging

from fastapi import APIRouter
from sqlalchemy import func, select

from api.deps import DbSession
from api.errors import NotFoundError
from api.schemas.session import RestoredMessage, RestoredResponse, RestoredSession
from schema import chat_messages, chat_sessions  # src/schema.py 의 테이블 정의 (flat import)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

# 복원 가능 기간(시간). 프론트 constants.ts 의 CONVERSATION_RESTORE_WINDOW_H 와 같아야 한다.
RESTORE_WINDOW_H = 24


@router.get("/sessions/{session_id}", response_model=RestoredSession)
def get_session(session_id: str, db: DbSession):
    """24시간 이내 대화를 복원한다. 없는 세션·만료된 세션은 404."""
    row = db.execute(
        select(chat_sessions.c.session_id, chat_sessions.c.last_activity_at)
        .where(chat_sessions.c.session_id == session_id)
    ).first()
    if row is None:
        raise NotFoundError("대화를 찾을 수 없습니다.")

    # 만료 판정은 조회 시점 계산으로 한다 — 행을 지우지 않는다. 삭제는 되돌릴 수 없고
    # 관리자 대화 로그(AD-005)는 24시간보다 오래 봐야 한다.
    age_h = (_now(db) - row.last_activity_at).total_seconds() / 3600
    if age_h > RESTORE_WINDOW_H:
        raise NotFoundError(
            "대화 보관 기간이 지났습니다.",
            detail=f"session={session_id} age={age_h:.1f}h",
        )

    messages = db.execute(
        select(chat_messages)
        .where(chat_messages.c.session_id == session_id)
        .order_by(chat_messages.c.seq)
    ).all()

    return RestoredSession(
        session_id=row.session_id,
        last_activity_at=row.last_activity_at.isoformat(),
        messages=[_to_message(m) for m in messages],
    )


def _now(db):
    """만료 비교에 DB 시각을 쓴다. 앱 서버와 DB 의 시계가 어긋나도 판정이 흔들리지 않게
    양쪽 값을 같은 출처(Postgres)에서 가져온다."""
    return db.execute(select(func.now())).scalar()


def _to_message(m) -> RestoredMessage:
    """사용자 메시지는 response 를 비우고, 답변만 출처·서류를 담는다(프론트가 존재 여부로
    섹션을 그린다)."""
    response = None
    if m.role == "assistant":
        response = RestoredResponse(
            sources=m.sources or [],
            attachments=m.attachments or [],
            out_of_scope=bool(m.out_of_scope),
        )
    return RestoredMessage(
        role=m.role,
        text=m.text,
        at=m.created_at.isoformat() if m.created_at else None,
        request_id=m.request_id,
        response=response,
    )
