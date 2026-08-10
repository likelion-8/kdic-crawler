"""관리자 지식베이스 페이지 목록(AD-002).

검색어는 제목과 원본 URL에만 적용한다. 업무 분류는 목록에서 사용하는 표준 값과
정확히 일치시켜, 비슷한 이름의 다른 업무가 섞이지 않게 한다.
"""
from collections.abc import Mapping
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Query
from sqlalchemy import case, func, or_, select

from api.deps import CurrentAdmin, DbSession
from api.errors import BadRequestError
from api.schemas.knowledge import KnowledgePage, KnowledgePageList
from schema import document_chunks, documents

router = APIRouter(prefix="/api/admin/knowledge", tags=["admin-knowledge"])

DEFAULT_PAGE_SIZE = 20
INDEX_STATUSES = frozenset({"INDEXED", "PENDING", "REINDEXING", "FAILED", "EXCLUDED"})
LIST_STATES = frozenset({"최신", "변경 감지", "적용 대기"})
COLLECTION_STATUSES = frozenset({"CANDIDATE", "LOADED", "ROBOTS_BLOCKED", "SKIPPED", "FAILED"})


def _escape_like(value: str) -> str:
    """ILIKE의 와일드카드는 검색어가 아니라 일반 문자로 취급한다."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _resolved_index_status():
    """관리자 확장 컬럼이 아직 비어 있는 기존 적재 문서의 표시 기본값."""
    return func.coalesce(
        documents.c.index_status,
        case((documents.c.is_active.is_(True), "INDEXED"), else_="EXCLUDED"),
    )


def _list_state(index_status: str) -> Literal["최신", "변경 감지", "적용 대기"]:
    # 변경 감지는 별도 비교 작업이 채우는 index_status=PENDING으로 표현한다.
    if index_status == "PENDING":
        return "변경 감지"
    if index_status == "REINDEXING":
        return "적용 대기"
    return "최신"


def _filters(*, tab: str, q: str, business: str | None, state: str | None):
    filters = []
    index_status = _resolved_index_status()

    # 수집 대상 탭은 이미 적재된 페이지와 적재 전 후보를 함께 보여 준다. 반대로
    # 적재 페이지 탭에는 수집이 끝난 문서만 둔다.
    if tab == "indexed":
        filters.append(or_(documents.c.collection_status.is_(None), documents.c.collection_status == "LOADED"))

    if q:
        pattern = f"%{_escape_like(q)}%"
        filters.append(
            or_(
                documents.c.page_title.ilike(pattern, escape="\\"),
                documents.c.source_url.ilike(pattern, escape="\\"),
            )
        )

    if business:
        filters.append(documents.c.business_function == business)

    if state:
        if state in INDEX_STATUSES:
            filters.append(index_status == state)
        elif state == "최신":
            filters.append(index_status.notin_(("PENDING", "REINDEXING")))
        elif state == "변경 감지":
            filters.append(index_status == "PENDING")
        elif state == "적용 대기":
            filters.append(index_status == "REINDEXING")
        else:
            raise BadRequestError("지원하지 않는 상태 필터입니다.")

    return filters, index_status


def _sort_column(sort: str | None, chunk_count):
    columns = {
        "page_id": documents.c.page_id,
        "page_title": documents.c.page_title,
        "collected_at": documents.c.collected_at,
        "chunk_count": chunk_count,
    }
    if sort is None:
        return documents.c.page_id.asc()

    field, separator, direction = sort.partition(":")
    if separator != ":" or field not in columns or direction not in {"asc", "desc"}:
        raise BadRequestError("지원하지 않는 정렬 조건입니다.")
    return columns[field].desc() if direction == "desc" else columns[field].asc()


def build_knowledge_page_queries(*, tab: str, q: str, business: str | None, state: str | None, sort: str | None):
    """동일한 조건을 목록과 total 집계에 적용한다.

    이 함수를 분리해 두면 제목·URL·업무 조건이 한 쿼리에만 적용되어 페이지 수와
    실제 목록이 어긋나는 회귀를 단위 테스트로 막을 수 있다.
    """
    filters, index_status = _filters(tab=tab, q=q, business=business, state=state)
    chunk_count = (
        select(func.count(document_chunks.c.id))
        .where(document_chunks.c.document_id == documents.c.id)
        .scalar_subquery()
        .label("chunk_count")
    )
    rows = (
        select(
            documents.c.page_id,
            documents.c.source_url,
            documents.c.business_function,
            documents.c.sub_category,
            documents.c.page_title,
            documents.c.summary,
            documents.c.collected_at,
            documents.c.content_sha256,
            documents.c.metadata.label("source_metadata"),
            documents.c.owner,
            documents.c.collection_status,
            documents.c.index_status,
            documents.c.split_rule,
            documents.c.collection_note,
            documents.c.link_check,
            documents.c.first_indexed_at,
            index_status.label("resolved_index_status"),
            chunk_count,
        )
        .where(*filters)
        .order_by(_sort_column(sort, chunk_count))
    )
    total = select(func.count(documents.c.id)).where(*filters)
    return rows, total


def _as_dict(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _as_text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "true"
    return False


def _iso_date(value: object) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return ""


def _iso_datetime(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _form_links(metadata: Mapping[str, object]) -> list[dict[str, str]]:
    links = []
    for item in _as_list(metadata.get("form_attachments")):
        if not isinstance(item, Mapping):
            continue
        url = _as_text(item.get("page_url")) or _as_text(item.get("resolved_url")) or _as_text(item.get("url"))
        if not url:
            continue
        label = _as_text(item.get("label")) or _as_text(item.get("text")) or "서식 링크"
        links.append({"label": label, "url": url})
    return links


def serialize_knowledge_page(row: Mapping[str, object]) -> KnowledgePage:
    """크롤러의 JSON 메타데이터와 관리자 확장 컬럼을 화면 계약으로 합친다."""
    metadata = _as_dict(row.get("source_metadata"))
    index_status = _as_text(row.get("resolved_index_status")) or "INDEXED"
    collection_status = _as_text(row.get("collection_status"))
    if collection_status not in COLLECTION_STATUSES:
        collection_status = "LOADED"

    return KnowledgePage(
        page_id=_as_text(row.get("page_id")),
        source_url=_as_text(row.get("source_url")),
        business_function=_as_text(row.get("business_function")),
        sub_category=_as_text(row.get("sub_category")),
        page_title=_as_text(row.get("page_title")),
        required=_as_bool(metadata.get("required")),
        note=_as_text(metadata.get("note")) or _as_text(row.get("collection_note")),
        summary=_as_text(row.get("summary")),
        collected_at=_iso_date(row.get("collected_at")),
        content_sha256=_as_text(row.get("content_sha256")),
        chunk_count=int(row.get("chunk_count") or 0),
        list_state=_list_state(index_status),
        index_status=index_status,
        asset_counts={
            "links": len(_as_list(metadata.get("links"))),
            "images": len(_as_list(metadata.get("images"))),
            "videos": len(_as_list(metadata.get("videos"))),
        },
        form_links=_form_links(metadata),
        owner=_as_text(row.get("owner")),
        split_rule=_as_text(row.get("split_rule")),
        collection_status=collection_status,
        collection_note=_as_text(row.get("collection_note")),
        link_check=_as_text(row.get("link_check")),
        first_indexed_at=_iso_datetime(row.get("first_indexed_at")),
    )


@router.get("/pages", response_model=KnowledgePageList)
def list_knowledge_pages(
    admin: CurrentAdmin,
    db: DbSession,
    tab: Literal["indexed", "targets"] = "indexed",
    q: str = "",
    business: str | None = None,
    state: str | None = None,
    sort: str | None = None,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=100),
):
    """제목·URL 검색 및 업무 분류 필터가 적용된 지식베이스 목록."""
    del admin  # 인증은 의존성에서 검증하며, 목록 자체에는 사용자별 데이터가 없다.
    query = q.strip()
    rows_query, total_query = build_knowledge_page_queries(
        tab=tab,
        q=query,
        business=business,
        state=state,
        sort=sort,
    )
    total = db.execute(total_query).scalar_one()
    rows = db.execute(rows_query.offset((page - 1) * size).limit(size)).mappings().all()
    return KnowledgePageList(
        items=[serialize_knowledge_page(row) for row in rows],
        total=total,
        page=page,
        size=size,
    )
