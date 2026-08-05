"""POST /api/feedback · PATCH /api/feedback/{id} — 답변에 대한 👍/👎 와 사유.

저장은 Supabase feedback 테이블. 답변 1건당 피드백 1건이라(request_id 에 unique),
같은 답변에 다시 투표하면 새 행이 아니라 기존 행을 덮어쓴다 — 사용자가 👍 를 눌렀다 👎 로
바꾸는 흐름이 자연스럽게 처리된다.

sync def 로 둔다: DB 접근이 블로킹이라 async 로 두면 이벤트 루프를 막는다.
"""
import logging

from fastapi import APIRouter
from sqlalchemy.dialects.postgresql import insert as pg_insert

from api.deps import DbSession
from api.errors import BadRequestError, NotFoundError
from api.schemas.feedback import FeedbackPatch, FeedbackRequest, FeedbackResponse
from schema import feedback  # src/schema.py 의 테이블 정의 (flat import)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["feedback"])


@router.post("/feedback", response_model=FeedbackResponse)
def create_feedback(req: FeedbackRequest, db: DbSession):
    """👍/👎 등록. 같은 답변에 대한 재투표는 기존 행을 갱신한다(upsert).

    대상 답변(rag_runs)이 있는지는 확인하지 않는다 — 로깅이 실패-안전이라 답변 행이 없을 수
    있는데, 그때 피드백까지 거부하면 사용자에게 이유 없는 실패가 보인다.
    """
    stmt = (
        pg_insert(feedback)
        .values(request_id=req.answer_request_id, session_id=req.session_id, vote=req.vote)
        # 재투표: vote 만 바꾸고 이미 적어둔 사유는 남긴다.
        .on_conflict_do_update(index_elements=["request_id"], set_={"vote": req.vote})
        .returning(feedback.c.id)
    )
    feedback_id = db.execute(stmt).scalar_one()
    db.commit()
    logger.info("feedback %s: %s -> %s", feedback_id, req.answer_request_id, req.vote)
    return FeedbackResponse(feedback_id=str(feedback_id))


@router.patch("/feedback/{feedback_id}", response_model=FeedbackResponse)
def update_feedback(feedback_id: str, patch: FeedbackPatch, db: DbSession):
    """👎 사유 보완. 칩(reason_codes)과 자유 의견(comment) 중 하나라도 있으면 받는다."""
    if not patch.reason_codes and not (patch.comment or "").strip():
        raise BadRequestError("사유를 선택하거나 의견을 입력해 주세요.")

    stmt = (
        feedback.update()
        .where(feedback.c.id == feedback_id)
        .values(reason_codes=patch.reason_codes or None, comment=patch.comment)
        .returning(feedback.c.id)
    )
    try:
        row = db.execute(stmt).first()
    except Exception as exc:  # 잘못된 uuid 형식 등 — 없는 자원과 같은 취급
        db.rollback()
        raise NotFoundError("피드백을 찾을 수 없습니다.", detail=str(exc)) from exc
    if row is None:
        raise NotFoundError("피드백을 찾을 수 없습니다.")
    db.commit()
    return FeedbackResponse(feedback_id=str(row[0]))
