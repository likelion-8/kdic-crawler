"""관리자 지식베이스 페이지 목록(AD-002).

검색어는 제목과 원본 URL에만 적용한다. 업무 분류는 목록에서 사용하는 표준 값과
정확히 일치시켜, 비슷한 이름의 다른 업무가 섞이지 않게 한다.
"""
import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Query
from sqlalchemy import case, func, or_, select

from api.deps import CurrentAdmin, DbSession
from api.errors import BadRequestError
from api.schemas.knowledge import KbChunk, KbChunkList, KnowledgePage, KnowledgePageList
from schema import document_chunks, documents

router = APIRouter(prefix="/api/admin/knowledge", tags=["admin-knowledge"])

DEFAULT_PAGE_SIZE = 20
# 두 값 모두 목 데이터(web/src/mocks/data/chunks.ts)에서 그대로 실측한 것이다.
# 잘린 title은 예외 없이 29자(28+…), 잘린 preview는 71자(70+…)였다.
CHUNK_TITLE_CHARS = 28
CHUNK_PREVIEW_CHARS = 70
# 본문에는 줄바꿈이 흔하다(활성 청크 494건 중 445건이 앞 70자 안에 포함). 공백으로
# 접은 뒤에 자르는데, 접으면 길이가 줄기만 하므로 70자를 채우려면 넉넉히 받아야 한다.
CHUNK_HEAD_CHARS = 200
ELLIPSIS = "…"
_WHITESPACE = re.compile(r"\s+")
# 상세 패널은 페이지의 청크를 한 번에 다 받아 3장만 접어 보여 준다(PageDetailPanel.tsx의
# CHUNK_FETCH_SIZE=300). 목록의 100건 상한을 그대로 쓰면 그 요청이 422로 막힌다.
# 본문도 embedding도 싣지 않아 300건이라도 응답은 수십 KB에 그친다.
CHUNK_MAX_PAGE_SIZE = 500
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


def _sort_order(sort: str | None, chunk_count):
    """정렬 키와 함께 page_id 보조 키를 돌려준다.

    제목·수집일·청크 수는 값이 겹치는 행이 많은데(청크 1개짜리 페이지만 수십 건),
    동률 행의 순서는 보장되지 않아 LIMIT/OFFSET 페이지 사이에서 같은 행이 두 번
    나오거나 아예 빠질 수 있다. 유니크한 page_id를 뒤에 붙여 전순서를 만든다.
    """
    columns = {
        "page_id": documents.c.page_id,
        "page_title": documents.c.page_title,
        "collected_at": documents.c.collected_at,
        "chunk_count": chunk_count,
    }
    tiebreak = documents.c.page_id.asc()
    if sort is None:
        return (tiebreak,)

    field, separator, direction = sort.partition(":")
    if separator != ":" or field not in columns or direction not in {"asc", "desc"}:
        raise BadRequestError("지원하지 않는 정렬 조건입니다.")
    primary = columns[field].desc() if direction == "desc" else columns[field].asc()
    return (primary, tiebreak)


def build_knowledge_page_queries(*, tab: str, q: str, business: str | None, state: str | None, sort: str | None):
    """동일한 조건을 목록과 total 집계에 적용한다.

    이 함수를 분리해 두면 제목·URL·업무 조건이 한 쿼리에만 적용되어 페이지 수와
    실제 목록이 어긋나는 회귀를 단위 테스트로 막을 수 있다.
    """
    filters, index_status = _filters(tab=tab, q=q, business=business, state=state)
    chunk_count = (
        select(func.count(document_chunks.c.id))
        .where(document_chunks.c.document_id == documents.c.id)
        .where(document_chunks.c.is_active.is_(True))
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
        .order_by(*_sort_order(sort, chunk_count))
    )
    total = select(func.count(documents.c.id)).where(*filters)
    return rows, total


def build_knowledge_chunk_queries(*, page_id: str, q: str):
    """청크 목록과 total에 같은 조건을 적용한다.

    documents를 조인하는 이유는 두 가지다. page_id 필터를 chunk_id 문자열 파싱 없이
    걸 수 있고, 응답의 page_id를 파생값이 아니라 실제 컬럼에서 가져올 수 있다.
    (chunk_id는 단일 청크 페이지에 '#0'을 붙이지 않아 page_id와 값이 같다 — 문자열로
    거르면 `LIKE 'page#%'`에 단일 청크 페이지가 통째로 걸리지 않는다.)
    """
    # embedding은 Vector(1024)라 목록 20건만 실어도 응답이 수 MB가 된다. 본문(text)도
    # 1000자를 넘는 청크가 흔해서, 화면에 필요한 앞부분과 길이만 DB에서 계산해 받는다.
    head = func.left(document_chunks.c.text, CHUNK_HEAD_CHARS).label("head")
    chars = func.char_length(document_chunks.c.text).label("chars")
    # 단일 청크 페이지는 chunk_index가 비어 있을 수 있다. 화면 표기는 #0이다.
    seq = func.coalesce(document_chunks.c.chunk_index, 0).label("seq")

    # 비활성 청크를 빼지 않으면 목록 건수가 목록 화면의 chunk_count와 어긋난다.
    filters = [document_chunks.c.is_active.is_(True)]
    if page_id:
        filters.append(documents.c.page_id == page_id)
    if q:
        # 화면이 검색하는 대상은 title과 preview지만 둘 다 본문의 앞부분이라, 본문을
        # 그대로 ILIKE하면 두 값을 모두 포함한다.
        filters.append(document_chunks.c.text.ilike(f"%{_escape_like(q)}%", escape="\\"))

    source = document_chunks.join(documents, document_chunks.c.document_id == documents.c.id)
    rows = (
        select(document_chunks.c.chunk_id, documents.c.page_id, seq, chars, head)
        .select_from(source)
        .where(*filters)
        # page_id를 지정하지 않으면 여러 문서의 청크가 섞여 seq가 대량으로 겹친다.
        # 유니크한 chunk_id를 보조 키로 붙여 페이지 사이 중복·누락을 막는다.
        .order_by(seq.asc(), document_chunks.c.chunk_id.asc())
    )
    total = select(func.count(document_chunks.c.id)).select_from(source).where(*filters)
    return rows, total


def _clip(head: str, limit: int, clipped: bool) -> str:
    """앞 limit자만 남기고, 뒤에 본문이 더 있으면 …를 붙인다.

    clipped는 head 자체가 본문의 일부만 잘라 온 값이라는 뜻이다. head가 limit보다
    짧아도 뒤에 본문이 남아 있으면 …가 필요하다.
    """
    if len(head) > limit:
        return head[:limit] + ELLIPSIS
    return head + ELLIPSIS if clipped else head


def _chunk_title(head: str, clipped: bool) -> str:
    """본문 앞부분을 목록 표시용 제목으로 줄인다.

    FAQ 청크가 "질문 …인가요? 열기 답변 …" 형태라, 물음표까지만 쓰면 질문 한 줄이
    그대로 제목이 된다. 마침표는 문장 끝으로 보지 않는다 — 본문에 fins.kdic.or.kr
    같은 주소나 번호 표기가 흔해서 엉뚱한 자리에서 끊긴다.
    """
    question, mark, _ = head.partition("?")
    if mark and len(question) <= CHUNK_TITLE_CHARS:
        return question
    return _clip(head, CHUNK_TITLE_CHARS, clipped)


def serialize_knowledge_chunk(row: Mapping[str, object]) -> KbChunk:
    chars = int(row.get("chars") or 0)
    # 본문의 줄바꿈을 그대로 두면 "질문\n예금보호한도…"처럼 제목 한 줄에 개행이 섞인다.
    head = _WHITESPACE.sub(" ", _as_text(row.get("head"))).strip()
    clipped = chars > CHUNK_HEAD_CHARS
    return KbChunk(
        chunk_id=_as_text(row.get("chunk_id")),
        page_id=_as_text(row.get("page_id")),
        seq=int(row.get("seq") or 0),
        title=_chunk_title(head, clipped),
        chars=chars,
        preview=_clip(head, CHUNK_PREVIEW_CHARS, clipped),
    )


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


@router.get("/chunks", response_model=KbChunkList)
def list_knowledge_chunks(
    admin: CurrentAdmin,
    db: DbSession,
    page_id: str = "",
    q: str = "",
    page: int = Query(default=1, ge=1),
    size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=CHUNK_MAX_PAGE_SIZE),
):
    """상세 패널이 여는 페이지의 청크 목록.

    없는 page_id는 404가 아니라 빈 목록으로 답한다. 상세 패널은 목록에서 이미 받은
    행을 그리고 있어서, 청크만 없는 상태를 "이 페이지에는 청크가 없습니다"로 표시한다.
    """
    del admin  # 인증은 의존성이 처리하며, 청크 목록에 사용자별 데이터는 없다.
    rows_query, total_query = build_knowledge_chunk_queries(page_id=page_id.strip(), q=q.strip())
    total = db.execute(total_query).scalar_one()
    rows = db.execute(rows_query.offset((page - 1) * size).limit(size)).mappings().all()
    return KbChunkList(
        items=[serialize_knowledge_chunk(row) for row in rows],
        total=total,
        page=page,
        size=size,
    )
