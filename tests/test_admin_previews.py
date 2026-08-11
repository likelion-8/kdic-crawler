"""신규 URL Preview의 전체 흐름과 비영속 경계 테스트."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.deps import get_current_admin, get_db
from api.errors import BadRequestError, ForbiddenError
from api.main import create_app
from api.routers import admin_previews
from api.schemas.previews import PreviewCreateRequest
from crawler.preview import (
    FetchedPage,
    PreviewUrlError,
    build_document_preview,
    chunk_document,
    normalize_preview_url,
)


FAQ_HTML = """
<!doctype html>
<html lang="ko">
  <head>
    <title>예금자보호 FAQ | 예금보험공사</title>
    <meta name="description" content="예금보호한도와 보호대상을 설명합니다.">
  </head>
  <body>
    <div class="breadcrumb"><ul><li>홈</li><li>예금자보호제도</li><li>FAQ</li></ul></div>
    <header>공통 메뉴</header>
    <main id="contents">
      <h1>예금자보호 FAQ</h1>
      <section><strong>질문</strong><p>예금보호한도는 얼마인가요?</p><strong>답변</strong><p>1억원입니다.</p></section>
      <section><strong>질문</strong><p>보호대상 금융회사는 어디인가요?</p><strong>답변</strong><p>부보금융회사입니다.</p></section>
    </main>
    <footer>기관 주소</footer>
  </body>
</html>
"""


def _fetched(html: str = FAQ_HTML, url: str = "https://www.kdic.or.kr/new/faq.do") -> FetchedPage:
    return FetchedPage(url=url, html=html, status_code=200, content_type="text/html; charset=utf-8")


def _raw_preview(url: str) -> dict[str, object]:
    return build_document_preview(
        url=url,
        business_function="예금자보호제도",
        fetcher=lambda _: _fetched(url=url),
    )


def test_url_policy_accepts_only_exact_kdic_https_hosts():
    assert normalize_preview_url(" HTTPS://WWW.KDIC.OR.KR/path#fragment ") == (
        "https://www.kdic.or.kr/path"
    )
    assert normalize_preview_url("https://fins.kdic.or.kr/") == "https://fins.kdic.or.kr/"

    blocked = (
        "http://www.kdic.or.kr/page",
        "https://www.kdic.or.kr.evil.example/page",
        "https://user@www.kdic.or.kr/page",
        "https://www.kdic.or.kr:8443/page",
    )
    for url in blocked:
        with pytest.raises(PreviewUrlError):
            normalize_preview_url(url)


def test_preview_runs_parse_classify_and_existing_faq_chunking_without_files():
    result = _raw_preview("https://www.kdic.or.kr/new/faq.do")
    extracted = result["extracted"]
    chunks = result["chunks"]

    assert extracted["page_title"] == "예금자보호 FAQ"
    assert extracted["business_function"] == "예금자보호제도"
    assert extracted["sub_category"] == "예금자보호제도 > FAQ"
    assert extracted["summary"] == "예금보호한도와 보호대상을 설명합니다."
    assert len(extracted["content_sha256"]) == 64
    assert result["split_rule"] == "FAQ 질문·답변 쌍으로 분할"
    # 기존 split_faq는 첫 질문 앞의 페이지 제목/서문도 별도 청크로 보존한다.
    assert len(chunks) == 3
    assert chunks[0]["chunk_id"].endswith("#0")
    assert "질문" in chunks[1]["preview"]
    assert "공통 메뉴" not in chunks[0]["preview"]
    assert result["sub_category_extraction_failed"] is False


def test_current_kdic_logo_and_location_menu_do_not_replace_document_metadata():
    html = """
    <html><head><title>예금보험공사</title></head><body>
      <h1 class="logo">예금보험공사</h1>
      <div class="location"><ol>
        <li><div class="ulSelectBox"><a>제도·정책</a><ul><li>전체 메뉴 A</li></ul></div></li>
        <li><div class="ulSelectBox"><a>예금자보호제도</a><ul><li>전체 메뉴 B</li></ul></div></li>
        <li><div class="ulSelectBox"><a>보호한도</a><ul><li>전체 메뉴 C</li></ul></div></li>
      </ol></div>
      <div class="pageTit"><h2>보호한도</h2></div>
      <div class="contents"><p>예금자 1인당 원금과 소정의 이자를 합하여 보호합니다. 금융회사별 보호한도와 적용 기준을 함께 설명합니다.</p></div>
    </body></html>
    """
    result = build_document_preview(
        url="https://www.kdic.or.kr/sp/dpstrprot/limit.do",
        business_function="예금자보호제도",
        fetcher=lambda _: _fetched(html, "https://www.kdic.or.kr/sp/dpstrprot/limit.do"),
    )

    assert result["extracted"]["page_title"] == "보호한도"
    assert result["extracted"]["sub_category"] == "예금자보호제도 > 보호한도"
    assert "전체 메뉴" not in result["chunks"][0]["preview"]


def test_human_metadata_wins_and_classifier_warns_on_a_strong_conflict():
    conflict_html = FAQ_HTML.replace("예금자보호 FAQ", "은닉재산 신고 안내").replace(
        "예금보호한도와 보호대상을 설명합니다.",
        "은닉재산과 부실관련자 신고포상 및 포상금을 설명합니다.",
    ).replace(
        "예금보호한도는 얼마인가요?",
        "은닉재산 신고포상은 얼마인가요?",
    ).replace(
        "보호대상 금융회사는 어디인가요?",
        "부실관련자의 재산 신고는 어떻게 하나요?",
    )
    result = build_document_preview(
        url="https://www.kdic.or.kr/report/hidden-property.do",
        business_function="예금자보호제도",
        page_title="관리자 제목",
        summary="관리자 요약",
        fetcher=lambda _: _fetched(
            conflict_html,
            "https://www.kdic.or.kr/report/hidden-property.do",
        ),
    )

    assert result["extracted"]["page_title"] == "관리자 제목"
    assert result["extracted"]["summary"] == "관리자 요약"
    assert result["extracted"]["business_function"] == "예금자보호제도"
    assert any("자동 분류 후보는 '은닉재산 신고'" in warning for warning in result["warnings"])


def test_business_is_automatically_decided_when_request_omits_it():
    result = build_document_preview(
        url="https://fins.kdic.or.kr/remittance/guide.do",
        fetcher=lambda _: _fetched(
            FAQ_HTML.replace("예금자보호", "착오송금 반환지원"),
            "https://fins.kdic.or.kr/remittance/guide.do",
        ),
    )
    assert result["extracted"]["business_function"] == "착오송금 반환 신청"


def test_table_chunking_reuses_header_and_three_row_rule():
    header = "구분 | 기관 | 상태"
    text = "안내\n" + header + "\n" + "\n".join(
        f"{index} | 기관{index} | 정상" for index in range(21)
    )
    chunks, split_rule = chunk_document("dp_table", text)

    assert split_rule == "표 헤더를 포함한 3행 단위로 분할"
    assert len(chunks) == 7
    assert all(header in chunk["preview"] for chunk in chunks)


class _FakeResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _SelectOnlyDb:
    def __init__(self, existing_page_id=None):
        self.existing_page_id = existing_page_id
        self.statements = []

    def execute(self, statement):
        # Preview가 운영 테이블에 내보낼 수 있는 SQL은 URL 중복 확인 SELECT 하나뿐이다.
        assert statement.is_select is True
        sql = str(statement).upper()
        assert "INSERT " not in sql
        assert "UPDATE " not in sql
        assert "DELETE " not in sql
        assert "DOCUMENT_CHUNKS" not in sql
        self.statements.append(statement)
        if isinstance(self.existing_page_id, list):
            value = self.existing_page_id.pop(0)
        else:
            value = self.existing_page_id
        return _FakeResult(value)


def _editor():
    return SimpleNamespace(role="EDITOR")


def _request(url="https://www.kdic.or.kr/new/faq.do"):
    return PreviewCreateRequest(
        request_id=str(uuid.uuid4()),
        url=url,
        business_function="예금자보호제도",
        note="신규 안내 수집",
    )


def test_api_preview_only_selects_documents_and_returns_result(monkeypatch):
    db = _SelectOnlyDb()
    monkeypatch.setattr(admin_previews, "build_document_preview", lambda **kwargs: _raw_preview(kwargs["url"]))

    response = admin_previews.create_document_preview(_request(), _editor(), db)

    assert response.preview_id.startswith("pv_")
    assert response.chunks
    assert len(db.statements) == 1


def test_duplicate_url_stops_before_crawl(monkeypatch):
    db = _SelectOnlyDb(existing_page_id="dp_existing")
    called = False

    def should_not_crawl(**kwargs):
        nonlocal called
        called = True
        raise AssertionError("중복 URL은 크롤링하면 안 됨")

    monkeypatch.setattr(admin_previews, "build_document_preview", should_not_crawl)
    with pytest.raises(BadRequestError, match="이미 등록된 URL"):
        admin_previews.create_document_preview(_request(), _editor(), db)
    assert called is False


def test_redirected_final_url_is_checked_for_duplicates(monkeypatch):
    source_url = "https://www.kdic.or.kr/new/redirect.do"
    final_url = "https://www.kdic.or.kr/existing/page.do"
    db = _SelectOnlyDb(existing_page_id=[None, "dp_existing"])

    def redirected_preview(**kwargs):
        result = _raw_preview(final_url)
        result["url"] = final_url
        return result

    monkeypatch.setattr(admin_previews, "build_document_preview", redirected_preview)
    with pytest.raises(BadRequestError, match="최종 URL이 이미 등록"):
        admin_previews.create_document_preview(_request(source_url), _editor(), db)
    assert len(db.statements) == 2


def test_preview_requires_editor_or_admin_role():
    with pytest.raises(ForbiddenError):
        admin_previews.create_document_preview(
            _request(),
            SimpleNamespace(role="OPERATOR"),
            _SelectOnlyDb(),
        )


def test_preview_routes_are_registered_in_the_app():
    paths = create_app().openapi()["paths"]
    assert "/api/admin/previews" in paths
    assert "/api/admin/previews/{preview_id}/reject" in paths


def test_preview_http_response_matches_the_frontend_contract(monkeypatch):
    db = _SelectOnlyDb()
    app = create_app()
    app.dependency_overrides[get_current_admin] = _editor
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(admin_previews, "build_document_preview", lambda **kwargs: _raw_preview(kwargs["url"]))

    client = TestClient(app)
    try:
        response = client.post(
            "/api/admin/previews",
            json={
                "request_id": str(uuid.uuid4()),
                "url": "https://www.kdic.or.kr/new/faq.do",
                "business_function": "예금자보호제도",
                "note": "신규 안내 수집",
            },
        )
    finally:
        client.close()

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "preview_id",
        "url",
        "extracted",
        "split_rule",
        "chunks",
        "warnings",
        "sub_category_extraction_failed",
    }
    assert body["chunks"][1]["preview"].startswith("질문")
    assert len(db.statements) == 1
