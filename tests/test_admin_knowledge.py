"""관리자 지식베이스 목록의 검색·필터 계약 테스트.

실제 Supabase 접속 없이 Postgres용 SQL과 응답 변환만 검사한다. 검색 조건은 목록 쿼리와
total 쿼리가 같은 빌더를 공유하므로, 여기서 제목·URL·업무 필터 회귀를 잡을 수 있다.
"""
from datetime import datetime, timezone
import sys
from pathlib import Path

from sqlalchemy.dialects import postgresql

# `python tests/test_admin_knowledge.py`로도 실행되도록 저장소 루트를 먼저 넣는다.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.routers.admin_knowledge import (
    build_knowledge_page_queries,
    router,
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


if __name__ == "__main__":
    test_title_and_url_search_share_one_safe_filter()
    test_business_filter_is_an_exact_match_in_both_queries()
    test_chunk_count_only_counts_active_chunks()
    test_response_contains_metadata_needed_by_the_existing_page()
    test_knowledge_list_route_is_exposed()
    print("OK - 관리자 지식베이스 제목·URL 검색 및 업무 분류 필터")
