"""신규 URL 문서 Preview API.

Preview는 ``documents``를 URL 중복 확인용으로만 SELECT하고, 결과는 프로세스 메모리에
24시간만 보관한다. ``documents``/``document_chunks`` INSERT·UPDATE·DELETE는 이 경로에
존재하지 않는다.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock

from fastapi import APIRouter
from sqlalchemy import func, select

from api.deps import CurrentAdmin, DbSession
from api.errors import BadRequestError, ForbiddenError, NotFoundError
from api.schemas.previews import (
    PreviewCreateRequest,
    PreviewRejectRequest,
    PreviewRejectResponse,
    PreviewResponse,
)
from crawler.preview import (
    PreviewError,
    build_document_preview,
    normalize_preview_url,
)
from schema import documents


router = APIRouter(prefix="/api/admin", tags=["admin-knowledge"])

PREVIEW_TTL = timedelta(hours=24)
MAX_CACHED_PREVIEWS = 256
EDITOR_ROLES = frozenset({"EDITOR", "ADMIN"})


@dataclass(frozen=True)
class _PreviewEntry:
    request_id: str
    response: PreviewResponse
    expires_at: datetime


class _PreviewStore:
    """작은 프로세스 로컬 TTL 저장소.

    운영 DB에 Preview를 섞지 않으면서 재전송 멱등성과 [버리기]를 지원한다. 프로세스가
    재시작되면 자동으로 사라지는 임시 데이터라는 점도 Preview의 수명과 맞는다.
    """

    def __init__(self) -> None:
        self._entries: OrderedDict[str, _PreviewEntry] = OrderedDict()
        self._request_ids: dict[str, str] = {}
        self._lock = Lock()

    def _purge_expired(self, now: datetime) -> None:
        expired = [preview_id for preview_id, entry in self._entries.items() if entry.expires_at <= now]
        for preview_id in expired:
            entry = self._entries.pop(preview_id)
            self._request_ids.pop(entry.request_id, None)

    def get_by_request_id(self, request_id: str) -> PreviewResponse | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._purge_expired(now)
            preview_id = self._request_ids.get(request_id)
            if preview_id is None:
                return None
            entry = self._entries.get(preview_id)
            return entry.response if entry else None

    def put(self, request_id: str, response: PreviewResponse) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._purge_expired(now)
            previous_id = self._request_ids.get(request_id)
            if previous_id:
                self._entries.pop(previous_id, None)
            entry = _PreviewEntry(
                request_id=request_id,
                response=response,
                expires_at=now + PREVIEW_TTL,
            )
            self._entries[response.preview_id] = entry
            self._request_ids[request_id] = response.preview_id
            while len(self._entries) > MAX_CACHED_PREVIEWS:
                _, removed = self._entries.popitem(last=False)
                self._request_ids.pop(removed.request_id, None)

    def discard(self, preview_id: str) -> datetime | None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._purge_expired(now)
            entry = self._entries.pop(preview_id, None)
            if entry is None:
                return None
            self._request_ids.pop(entry.request_id, None)
            return entry.expires_at


_preview_store = _PreviewStore()


def _require_editor(admin) -> None:
    if admin.role not in EDITOR_ROLES:
        raise ForbiddenError(
            f"이 작업에는 EDITOR 권한이 필요합니다. 현재 권한은 {admin.role}입니다."
        )


def find_existing_document_page_id(db, normalized_url: str) -> str | None:
    """정규화 URL의 기존 page_id를 읽는다. 이 함수가 Preview의 유일한 운영 테이블 접근이다."""
    comparable_url = normalized_url.rstrip("/").lower()
    statement = (
        select(documents.c.page_id)
        .where(func.rtrim(func.lower(documents.c.source_url), "/") == comparable_url)
        .limit(1)
    )
    return db.execute(statement).scalar_one_or_none()


@router.post("/previews", response_model=PreviewResponse)
def create_document_preview(
    payload: PreviewCreateRequest,
    admin: CurrentAdmin,
    db: DbSession,
):
    """크롤링·파싱·업무 분류·청킹 결과를 운영 반영 없이 반환한다."""
    _require_editor(admin)

    try:
        normalized_url = normalize_preview_url(payload.url)
    except PreviewError as exc:
        raise BadRequestError(exc.user_message, retryable=exc.retryable) from exc

    cached = _preview_store.get_by_request_id(payload.request_id)
    if cached is not None:
        return cached

    existing_page_id = find_existing_document_page_id(db, normalized_url)
    if existing_page_id:
        raise BadRequestError(f"이미 등록된 URL입니다. (page_id: {existing_page_id})")

    try:
        result = build_document_preview(
            url=normalized_url,
            business_function=payload.business_function,
            page_title=payload.page_title,
            sub_category=payload.sub_category,
            summary=payload.summary,
        )
    except PreviewError as exc:
        raise BadRequestError(exc.user_message, retryable=exc.retryable) from exc

    final_url = str(result["url"])
    if final_url != normalized_url:
        existing_page_id = find_existing_document_page_id(db, final_url)
        if existing_page_id:
            raise BadRequestError(
                f"이동된 최종 URL이 이미 등록되어 있습니다. (page_id: {existing_page_id})"
            )

    response = PreviewResponse.model_validate(result)
    _preview_store.put(payload.request_id, response)
    return response


@router.post("/previews/{preview_id}/reject", response_model=PreviewRejectResponse)
def reject_document_preview(
    preview_id: str,
    payload: PreviewRejectRequest,
    admin: CurrentAdmin,
):
    """메모리의 Preview를 즉시 버린다. 운영 문서/청크에는 접근하지 않는다."""
    _require_editor(admin)
    if not payload.reason.strip():
        raise BadRequestError("사유를 입력해 주세요.")

    expires_at = _preview_store.discard(preview_id)
    if expires_at is None:
        raise NotFoundError("미리보기가 없거나 보관 시간이 지났습니다. 다시 수집해 주세요.")
    return PreviewRejectResponse(
        preview_id=preview_id,
        purge_at=expires_at.isoformat(),
    )
