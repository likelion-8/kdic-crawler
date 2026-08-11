"""관리자 지식베이스 목록의 검색·필터 계약 테스트.

실제 Supabase 접속 없이 Postgres용 SQL과 응답 변환만 검사한다. 검색 조건은 목록 쿼리와
total 쿼리가 같은 빌더를 공유하므로, 여기서 제목·URL·업무 필터 회귀를 잡을 수 있다.
"""
from datetime import datetime, timezone
import sys
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy.dialects import postgresql

# `python tests/test_admin_knowledge.py`로도 실행되도록 저장소 루트를 먼저 넣는다.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.routers.admin_knowledge import (
    CHUNK_HEAD_CHARS,
    CHUNK_PREVIEW_CHARS,
    build_knowledge_chunk_queries,
    build_knowledge_page_queries,
    router,
    serialize_knowledge_chunk,
    serialize_knowledge_page,
)


def _compiled(*, q: str = "", business: str | None = None):
    rows, total = build_knowledge_page_queries(
        tab="indexed",
        q=q,
        business=business,
        state=None,
        sort=None,
    )
    dialect = postgresql.dialect()
    return rows.compile(dialect=dialect), total.compile(dialect=dialect)


def test_title_and_url_search_share_one_safe_filter():
    rows, total = _compiled(q="보호_100%")
    rows_sql = str(rows)
    total_sql = str(total)

    # 요구한 검색 대상은 제목과 URL이다. page_id까지 넓혀 의도와 다른 결과를 만들지 않는다.
    assert "documents.page_title ILIKE" in rows_sql
    assert "documents.source_url ILIKE" in rows_sql
    assert "documents.page_id ILIKE" not in rows_sql
    assert "documents.page_title ILIKE" in total_sql
    assert "documents.source_url ILIKE" in total_sql

    # %와 _는 와일드카드가 아니라 사용자가 입력한 문자 그대로 검색한다.
    assert "%보호\\_100\\%%" in rows.params.values()
    assert "%보호\\_100\\%%" in total.params.values()


def test_business_filter_is_an_exact_match_in_both_queries():
    rows, total = _compiled(business="예금자보호제도")
    rows_sql = str(rows)
    total_sql = str(total)

    assert "documents.business_function =" in rows_sql
    assert "documents.business_function =" in total_sql
    assert "예금자보호제도" in rows.params.values()
    assert "예금자보호제도" in total.params.values()


def test_chunk_count_only_counts_active_chunks():
    rows, _ = _compiled()

    assert "document_chunks.is_active IS true" in str(rows)


def test_page_order_is_stable_across_pages():
    dialect = postgresql.dialect()

    for sort in (None, "chunk_count:desc", "page_title:asc", "collected_at:desc"):
        rows, _ = build_knowledge_page_queries(
            tab="indexed", q="", business=None, state=None, sort=sort
        )
        sql = str(rows.compile(dialect=dialect))

        # 제목·수집일·청크 수는 값이 겹치는 행이 많다(청크 1개짜리 페이지만 수십 건).
        # 유니크한 page_id를 뒤에 붙이지 않으면 LIMIT/OFFSET 페이지 사이에서 같은
        # 행이 두 번 나오거나 빠질 수 있다.
        assert sql.rstrip().endswith("documents.page_id ASC"), sort


def test_response_contains_metadata_needed_by_the_existing_page():
    page = serialize_knowledge_page(
        {
            "page_id": "dp_protect",
            "source_url": "https://www.kdic.or.kr/protect",
            "business_function": "예금자보호제도",
            "sub_category": "보호제도 > 안내",
            "page_title": "예금자보호 안내",
            "summary": "요약",
            "collected_at": datetime(2026, 8, 10, tzinfo=timezone.utc),
            "content_sha256": "hash",
            "source_metadata": {
                "required": True,
                "note": "수집 근거",
                "links": [{}, {}],
                "images": [{}],
                "videos": [],
                "form_attachments": [
                    {"label": "신청서", "page_url": "https://www.kdic.or.kr/form"},
                ],
            },
            "owner": "dy",
            "collection_status": "LOADED",
            "resolved_index_status": "PENDING",
            "split_rule": "본문 구조 기준 분할",
            "collection_note": "",
            "link_check": "OK",
            "first_indexed_at": None,
            "chunk_count": 3,
        }
    )

    assert page.page_title == "예금자보호 안내"
    assert page.required is True
    assert page.chunk_count == 3
    assert page.list_state == "변경 감지"
    assert page.asset_counts == {"links": 2, "images": 1, "videos": 0}
    assert page.form_links[0].url == "https://www.kdic.or.kr/form"


def test_knowledge_list_route_is_exposed():
    assert any(route.path == "/api/admin/knowledge/pages" for route in router.routes)


# ------------------------------------------------------------------ 청크 목록


def _compiled_chunks(*, page_id: str = "dp_faq_page", q: str = ""):
    rows, total = build_knowledge_chunk_queries(page_id=page_id, q=q)
    dialect = postgresql.dialect()
    return rows.compile(dialect=dialect), total.compile(dialect=dialect)


def test_chunk_query_never_selects_the_embedding_or_the_body():
    rows, _ = _compiled_chunks()
    rows_sql = str(rows)

    # embedding은 Vector(1024)라 한 번 새면 응답이 수 MB가 된다.
    assert "embedding" not in rows_sql

    # 본문도 통째로 옮기지 않는다. 길이와 앞부분만 DB에서 계산해 받는다. 즉 select
    # 목록에 나오는 text는 전부 char_length()나 left() 안에 감싸여 있어야 한다.
    select_list = rows_sql[len("SELECT ") : rows_sql.index("\nFROM")]
    assert "char_length(document_chunks.text)" in select_list
    assert "left(document_chunks.text" in select_list
    assert select_list.count("document_chunks.text") == 2


def test_chunk_query_filters_by_page_id_through_the_documents_join():
    rows, total = _compiled_chunks()

    # chunk_id 문자열을 파싱해 거르면 '#0'을 붙이지 않는 단일 청크 페이지가 통째로 빠진다.
    for compiled in (rows, total):
        sql = str(compiled)
        assert "JOIN documents" in sql
        assert "documents.page_id =" in sql
        assert "chunk_id LIKE" not in sql
        assert "dp_faq_page" in compiled.params.values()


def test_chunk_query_excludes_inactive_chunks_in_both_queries():
    rows, total = _compiled_chunks()

    # 목록 화면의 chunk_count가 활성 청크만 세므로 여기서도 빼야 숫자가 맞는다.
    assert "document_chunks.is_active IS true" in str(rows)
    assert "document_chunks.is_active IS true" in str(total)


def test_chunk_search_hits_the_body_and_escapes_wildcards():
    rows, total = _compiled_chunks(q="보호_100%")

    for compiled in (rows, total):
        assert "document_chunks.text ILIKE" in str(compiled)
        assert "%보호\\_100\\%%" in compiled.params.values()


def test_chunk_order_is_stable_across_pages():
    rows, _ = _compiled_chunks(page_id="")

    # seq만으로 정렬하면 page_id 없이 부를 때 여러 문서의 seq가 겹쳐, LIMIT/OFFSET
    # 페이지 사이에서 같은 청크가 두 번 나오거나 빠진다.
    assert "ORDER BY seq ASC, document_chunks.chunk_id ASC" in str(rows)


def test_missing_page_id_is_not_treated_as_a_filter():
    rows, _ = _compiled_chunks(page_id="")

    # 빈 page_id로 documents.page_id = '' 를 걸면 화면이 기대하는 빈 목록 대신
    # 조건이 하나 더 붙은 다른 질의가 된다.
    assert "documents.page_id =" not in str(rows)


def test_chunk_title_and_preview_follow_the_mock_contract():
    # 목 데이터(web/src/mocks/data/chunks.ts) 실측: 잘린 title은 28자+…, preview는 70자+….
    # head는 쿼리가 left(text, CHUNK_HEAD_CHARS)로 잘라 주는 값이다.
    chunk = serialize_knowledge_chunk(
        {
            "chunk_id": "dp_faq_page#3",
            "page_id": "dp_faq_page",
            "seq": 3,
            "chars": 250,
            "head": "가" * CHUNK_HEAD_CHARS,
        }
    )

    assert chunk.title == "가" * 28 + "…"
    assert chunk.preview == "가" * 70 + "…"
    # 표시하는 글자 수는 잘라 온 앞부분이 아니라 본문 전체 길이다.
    assert chunk.chars == 250

    # FAQ 청크는 물음표까지가 질문 한 줄이라 거기서 끊고 …를 붙이지 않는다.
    question = serialize_knowledge_chunk(
        {
            "chunk_id": "dp_faq_page#0",
            "page_id": "dp_faq_page",
            "seq": 0,
            "chars": 119,
            "head": "질문 예금보호한도 1억원은 언제부터 적용되었나요? 열기 답변 2025년 9월 1일부터 예금보호한도 1억원이 적용",
        }
    )

    assert question.title == "질문 예금보호한도 1억원은 언제부터 적용되었나요"

    # 마침표는 문장 끝으로 보지 않는다 — fins.kdic.or.kr 같은 주소에서 엉뚱하게 끊긴다.
    address = serialize_knowledge_chunk(
        {
            "chunk_id": "kmrs_apply_mthd",
            "page_id": "kmrs_apply_mthd",
            "seq": None,
            "chars": 250,
            "head": "신청방법 온라인 신청 사이트 : fins.kdic.or.kr (상단 아이콘 클릭 시 사이트 연결) 접속방법 : PC (모바",
        }
    )

    assert address.title == "신청방법 온라인 신청 사이트 : fins.kdic.…"
    # 단일 청크 페이지는 chunk_index가 비어 있을 수 있고, 화면 표기는 #0이다.
    assert address.seq == 0


def test_line_breaks_in_the_body_become_spaces():
    # 실제 본문은 줄바꿈이 기본이다(활성 청크 494건 중 445건이 앞 70자 안에 포함).
    # 그대로 내보내면 "#0 · 질문\n예금보호한도…"처럼 제목 한 줄에 개행이 섞인다.
    chunk = serialize_knowledge_chunk(
        {
            "chunk_id": "dp_faq_page#0",
            "page_id": "dp_faq_page",
            "seq": 0,
            "chars": 119,
            "head": "질문\n예금보호한도 1억원은 언제부터 적용되었나요?\n열기\n답변\n2025년 9월 1일부터",
        }
    )

    assert chunk.title == "질문 예금보호한도 1억원은 언제부터 적용되었나요"
    assert "\n" not in chunk.preview
    assert chunk.preview.startswith("질문 예금보호한도 1억원은 언제부터 적용되었나요? 열기 답변 ")

    # 연속 공백도 한 칸으로 접는다 — 목 데이터가 그렇게 만들어져 있다.
    spaced = serialize_knowledge_chunk(
        {"chunk_id": "c", "page_id": "p", "seq": 0, "chars": 20, "head": "☞  예금보험공사   홈페이지"}
    )

    assert spaced.title == "☞ 예금보험공사 홈페이지"


def test_head_fetch_is_wide_enough_to_fill_a_preview():
    # 공백을 접으면 길이가 줄기만 하므로, 70자 preview를 채우려면 그보다 넉넉히 받아야 한다.
    assert CHUNK_HEAD_CHARS > CHUNK_PREVIEW_CHARS


def test_short_chunk_keeps_its_whole_body_without_an_ellipsis():
    chunk = serialize_knowledge_chunk(
        {"chunk_id": "dp_short", "page_id": "dp_short", "seq": 0, "chars": 9, "head": "예금자보호제도입니다"[:9]}
    )

    assert chunk.title == "예금자보호제도입니"
    assert chunk.preview == "예금자보호제도입니"


def test_chunk_route_accepts_every_parameter_the_panel_sends():
    app = FastAPI()
    app.include_router(router)
    spec = app.openapi()["paths"]["/api/admin/knowledge/chunks"]["get"]
    params = {param["name"]: param["schema"] for param in spec["parameters"]}

    assert set(params) == {"page_id", "q", "page", "size"}
    # 네 개 모두 선택값이다. page_id 없이 불러도 422가 아니라 목록이 나와야 한다.
    assert all("default" in schema for schema in params.values())
    # 상세 패널이 CHUNK_FETCH_SIZE=300으로 한 번에 받아 간다. 목록의 100 상한이면 422다.
    assert params["size"]["maximum"] >= 300
    assert params["page"]["minimum"] == 1


if __name__ == "__main__":
    test_title_and_url_search_share_one_safe_filter()
    test_business_filter_is_an_exact_match_in_both_queries()
    test_chunk_count_only_counts_active_chunks()
    test_page_order_is_stable_across_pages()
    test_response_contains_metadata_needed_by_the_existing_page()
    test_knowledge_list_route_is_exposed()
    test_chunk_query_never_selects_the_embedding_or_the_body()
    test_chunk_query_filters_by_page_id_through_the_documents_join()
    test_chunk_query_excludes_inactive_chunks_in_both_queries()
    test_chunk_search_hits_the_body_and_escapes_wildcards()
    test_chunk_order_is_stable_across_pages()
    test_missing_page_id_is_not_treated_as_a_filter()
    test_chunk_title_and_preview_follow_the_mock_contract()
    test_line_breaks_in_the_body_become_spaces()
    test_head_fetch_is_wide_enough_to_fill_a_preview()
    test_short_chunk_keeps_its_whole_body_without_an_ellipsis()
    test_chunk_route_accepts_every_parameter_the_panel_sends()
    print("OK - 관리자 지식베이스 목록 및 청크 조회")
