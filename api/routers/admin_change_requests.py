"""변경 요청(change_requests) API — AD-002 삭제·제외 / AD-003 신규 적재 요청의 생성·조회·확정.

프론트 실코드가 부르는 건 생성(POST /change-requests)과 확정(POST /{id}/approve)이다
(KnowledgePages.tsx · NewPageForm.tsx). 목록/상세/버리기(reject)도 함께 둔다.

권한(2026-08-04 팀 결정): 생성·approve·reject 는 **EDITOR 이상**(구 계약의 ADMIN 아님 —
web/src/mocks/handlers/admin.ts:295-296). 조회는 로그인만.

존재 검증은 라우터가 한다 — change_requests.target_page_id 에 FK 가 없고(ADD 는 아직 없는
페이지를 가리키므로 FK 를 걸 수 없다) action 마다 전제가 정반대라 애초에 FK 한 줄로 표현이
안 된다(src/schema.py change_requests 주석):
    ADD                      documents 에 page_id 가 **없어야** + PENDING ADD 도 없어야 -> 400
    UPDATE / DELETE / EXCLUDE  documents 에 page_id 가 **있어야**                        -> 404

⚠️ 승인(approve)은 상태만 APPROVED 로 바꾼다. 실제 적재/삭제(REINDEX 워커)는 아직 없다
(pipeline_jobs 주석) — 이 API 는 '요청 레이어'까지다.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from api.deps import CurrentAdmin, DbSession, get_current_admin
from api.errors import ApiError, BadRequestError, ForbiddenError, NotFoundError
from api.schemas.change_request import (
    ChangeRequest, ChangeRequestCreate, ChangeRequestDecision, ChangeRequestList)
from schema import change_requests, documents

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-change-requests"],
    # 라우터 전체 인증(쿠키 없으면 401). 여기 추가되는 엔드포인트는 전부 자동 보호된다.
    dependencies=[Depends(get_current_admin)],
)

# action/status 값 정본: web/src/lib/codes.ts (PendingAction 'NONE' 제외 — 요청이 없다는 뜻).
ACTIONS = frozenset({"ADD", "UPDATE", "DELETE", "EXCLUDE"})
STATUSES = frozenset({"PENDING", "APPROVED", "REJECTED"})
# 역할 계층 정본: web/src/lib/codes.ts ROLE_RANK. 쓰기(생성·확정·버리기)는 EDITOR 이상.
ROLE_RANK = {"VIEWER": 0, "OPERATOR": 1, "EDITOR": 2, "ADMIN": 3}
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class RequestConflictError(ApiError):
    """이미 처리된 요청의 확정/버리기 시도(409). PENDING 이 아니면 상태 전이를 막는다 —
    approve/reject 의 중복은 별도 멱등키 없이 상태 전이로만 막는다(schema.py 주석)."""
    code = "change_request_conflict"
    status_code = 409
    user_message = "이미 처리된 요청입니다."


def _require_editor(me: CurrentAdmin) -> None:
    """EDITOR 이상만 쓰기. admin_activity 의 인라인 role 체크와 같은 방식(공용 의존성 없음)."""
    if ROLE_RANK.get(me.role, -1) < ROLE_RANK["EDITOR"]:
        raise ForbiddenError(
            f"이 작업에는 EDITOR 이상 권한이 필요합니다. 현재 권한은 {me.role}입니다.")


def _row_to_cr(row) -> ChangeRequest:
    """change_requests 한 행 -> ChangeRequest. payload(JSONB)는 psycopg 가 이미 dict 로 준다."""
    return ChangeRequest(
        id=str(row.id), action=row.action, target_page_id=row.target_page_id,
        target_title=row.target_title, business_function=row.business_function,
        payload=row.payload, reason=row.reason,
        requested_by=row.requested_by, requested_at=row.requested_at, status=row.status,
        decided_by=row.decided_by, decided_at=row.decided_at,
        decision_reason=row.decision_reason, request_id=row.request_id)


def _find_by_request_id(db, request_id):
    return db.execute(
        select(change_requests).where(change_requests.c.request_id == request_id)).first()


@router.post("/change-requests", status_code=201, response_model=ChangeRequest)
def create_change_request(body: ChangeRequestCreate, db: DbSession, me: CurrentAdmin):
    """변경 요청 생성 -> 201 + ChangeRequest(PENDING). EDITOR 이상. 존재 검증은 action 별로
    다르다(위 모듈 주석). request_id 멱등: 같은 키 재전송이면 기존 행을 그대로 돌려준다."""
    _require_editor(me)
    if body.action not in ACTIONS:
        raise BadRequestError("지원하지 않는 변경 종류입니다.")

    # 멱등 — 같은 request_id 재전송이면 신규 생성 없이 기존 행 반환.
    dup = _find_by_request_id(db, body.request_id)
    if dup is not None:
        return _row_to_cr(dup)

    # 존재 검증(FK 없음 — 라우터가 한다).
    doc = db.execute(
        select(documents.c.page_title, documents.c.business_function)
        .where(documents.c.page_id == body.target_page_id)
    ).first()
    title, bf = body.target_title, body.business_function

    if body.action == "ADD":
        if doc is not None:
            raise BadRequestError("이미 존재하는 페이지입니다.")
        # documents 만으로 못 잡는 구멍: 같은 page_id 의 PENDING ADD(승인돼도 워커가 없어
        # documents 에 아직 안 생김). request_id 멱등키는 '다른 요청의 같은 id 충돌'은 못 막는다.
        pending_add = db.execute(
            select(func.count()).select_from(change_requests).where(
                change_requests.c.action == "ADD",
                change_requests.c.target_page_id == body.target_page_id,
                change_requests.c.status == "PENDING")
        ).scalar_one()
        if pending_add:
            raise BadRequestError("같은 페이지에 대해 처리 대기 중인 적재 요청이 이미 있습니다.")
    else:  # UPDATE / DELETE / EXCLUDE — 대상 문서가 있어야 한다.
        if doc is None:
            raise NotFoundError("대상 페이지를 찾을 수 없습니다.")
        # 목록 표시용 복사값은 요청 본문에 없으면 documents 에서 채운다.
        title = title or doc.page_title
        bf = bf or doc.business_function

    try:
        row = db.execute(
            insert(change_requests).values(
                action=body.action, target_page_id=body.target_page_id,
                target_title=title, business_function=bf, payload=body.payload,
                reason=body.reason, requested_by=me.email, status="PENDING",
                request_id=body.request_id,
            ).returning(*change_requests.c)
        ).first()
        db.commit()
    except IntegrityError:
        # request_id unique 경합(동시 재전송) — 기존 행 반환으로 멱등 유지.
        db.rollback()
        again = _find_by_request_id(db, body.request_id)
        if again is None:
            raise
        return _row_to_cr(again)
    return _row_to_cr(row)


@router.get("/change-requests", response_model=ChangeRequestList)
def list_change_requests(
        db: DbSession,
        status: Optional[str] = Query(None, description="PENDING/APPROVED/REJECTED 필터"),
        page: int = Query(1, ge=1),
        size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)):
    """목록 -> {items, total, page, size}. ?status= 로 거른다. 기본 최신 신청순."""
    where = []
    if status is not None:
        if status not in STATUSES:
            raise BadRequestError("지원하지 않는 상태 값입니다.")
        where.append(change_requests.c.status == status)

    count_q = select(func.count()).select_from(change_requests)
    rows_q = select(change_requests).order_by(change_requests.c.requested_at.desc())
    if where:
        count_q = count_q.where(*where)
        rows_q = rows_q.where(*where)

    total = db.execute(count_q).scalar_one()
    rows = db.execute(rows_q.limit(size).offset((page - 1) * size)).all()
    return ChangeRequestList(items=[_row_to_cr(r) for r in rows],
                             total=total, page=page, size=size)


@router.get("/change-requests/{cr_id}", response_model=ChangeRequest)
def get_change_request(cr_id: str, db: DbSession):
    """상세 -> ChangeRequest. 없거나 형식이 틀린 id 면 404(UUID 컬럼이라 잘못된 형식은 쿼리가
    500 을 내므로 먼저 걸러낸다)."""
    row = _get_or_404(db, cr_id)
    return _row_to_cr(row)


def _get_or_404(db, cr_id):
    try:
        uuid.UUID(cr_id)
    except ValueError:
        raise NotFoundError("변경 요청을 찾을 수 없습니다.")
    row = db.execute(select(change_requests).where(change_requests.c.id == cr_id)).first()
    if row is None:
        raise NotFoundError("변경 요청을 찾을 수 없습니다.")
    return row


def _decide(cr_id, new_status, body, db, me):
    """approve/reject 공통 — EDITOR 이상, PENDING 만 전이. 전이는 원자적(where status=PENDING)
    으로 걸어 동시 확정 경합에서도 하나만 성공한다."""
    _require_editor(me)
    _get_or_404(db, cr_id)  # 존재 확인(404) — 아래 update 가 0행이면 '이미 처리됨'과 구분하기 위함
    now = datetime.now(timezone.utc)
    updated = db.execute(
        update(change_requests)
        .where(change_requests.c.id == cr_id, change_requests.c.status == "PENDING")
        .values(status=new_status, decided_by=me.email, decided_at=now,
                decision_reason=body.reason)
        .returning(*change_requests.c)
    ).first()
    if updated is None:          # 존재는 하나 PENDING 이 아니었다(이미 처리/경합).
        db.rollback()
        raise RequestConflictError()
    db.commit()
    return _row_to_cr(updated)


@router.post("/change-requests/{cr_id}/approve", response_model=ChangeRequest)
def approve_change_request(cr_id: str, body: ChangeRequestDecision,
                           db: DbSession, me: CurrentAdmin):
    """변경 요청 확정 -> APPROVED. 없으면 404, 이미 처리됐으면 409. ⚠️ 상태만 바꾼다 —
    실제 적재/삭제(REINDEX 워커)는 별개·미구현."""
    return _decide(cr_id, "APPROVED", body, db, me)


@router.post("/change-requests/{cr_id}/reject", response_model=ChangeRequest)
def reject_change_request(cr_id: str, body: ChangeRequestDecision,
                          db: DbSession, me: CurrentAdmin):
    """변경 요청 버리기 -> REJECTED. 없으면 404, 이미 처리됐으면 409."""
    return _decide(cr_id, "REJECTED", body, db, me)
