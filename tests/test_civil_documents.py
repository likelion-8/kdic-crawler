"""민원 서류 섹션 — 같은 다운로드 페이지로 접기 + 신청 진입점 없는 업무는 생략.

원인(2026-08-25): 서식의 진짜 링크가 POST 전용 서블릿이라 못 써서 "다운로드 버튼이 있는
페이지"(page_url)로 대체하는데, 그러면 한 페이지의 서식이 전부 같은 URL 이 된다. 중복 제거
키가 (label, url) 이라 라벨이 다르면 안 걸러져 같은 링크로 가는 카드가 수십 장 쌓였다
(실측: dp_gudn_data 29장, sender_docs 12장).

여기서 고정하는 계약 둘:
  1) 같은 URL 은 한 항목으로 접되 **개별 서류명은 labels 로 남긴다** — 이 섹션의 존재
     이유가 "무엇을 준비해야 하는지"라, 라벨을 페이지 제목으로 갈아치우면 정보가 사라진다.
  2) 신청 진입점(OFFICIAL_APPLY_LINKS)이 없는 업무는 서류 섹션 자체를 비운다 — 신청 절차가
     없는 업무에 구비서류가 붙으면 본문과 모순된다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "src"):
    sys.path.insert(0, str(p))

import civil_petition  # noqa: E402
from civil_petition import (build_civil_petition_answer,  # noqa: E402
                            build_document_section)
from prompt_builder import _format_document_line  # noqa: E402

SAME_URL = "https://kdic.example/docs"


@pytest.fixture
def page(monkeypatch):
    """corpus 대신 가짜 페이지 하나를 물린다 — 실 코퍼스 수치에 테스트를 묶지 않는다."""
    def _set(**doc):
        monkeypatch.setattr(civil_petition, "_page_docs", {"p1": {
            "attachments": [], "form_attachments": [], "business_function": None,
            "page_title": None, **doc}})
    return _set


CHUNKS = [("p1#0", 0.9, "본문")]


def test_same_url_collapses_to_one_item(page):
    page(page_title="구비서류안내",
         form_attachments=[{"label": f"서류{i} 다운로드", "page_url": SAME_URL} for i in range(12)])
    items = build_document_section(CHUNKS)
    assert len(items) == 1, "같은 URL 카드가 12장 쌓이던 것이 이 변경의 이유다"
    assert items[0]["url"] == SAME_URL


def test_collapsing_keeps_every_document_name(page):
    """접되 버리지 않는다 — 사용자는 어떤 서류가 필요한지 알아야 한다."""
    page(page_title="구비서류안내 - 착오송금인", form_attachments=[
        {"label": "신청서양식 다운로드", "page_url": SAME_URL},
        {"label": "위임장 다운로드", "page_url": SAME_URL},
    ])
    item = build_document_section(CHUNKS)[0]
    assert item["label"] == "구비서류안내 - 착오송금인"      # 대표 이름 = 페이지 제목
    assert item["labels"] == ["신청서양식 다운로드", "위임장 다운로드"]


def test_a_single_document_is_unchanged(page):
    """1건이면 종전 그대로 — 라벨 하나, labels 없음(프론트가 기존 부제를 쓴다)."""
    page(page_title="신청시 구비서류",
         form_attachments=[{"label": "다운로드", "page_url": SAME_URL}])
    item = build_document_section(CHUNKS)[0]
    assert item["label"] == "다운로드"
    assert "labels" not in item


def test_different_urls_stay_separate(page):
    page(form_attachments=[{"label": "A", "page_url": SAME_URL},
                           {"label": "B", "page_url": "https://kdic.example/other"}])
    assert len(build_document_section(CHUNKS)) == 2


def test_group_without_a_page_title_still_gets_a_name(page):
    """page_title 이 없어도 묶음이 이름을 잃지는 않는다."""
    page(page_title=None, form_attachments=[{"label": "A", "page_url": SAME_URL},
                                            {"label": "B", "page_url": SAME_URL}])
    item = build_document_section(CHUNKS)[0]
    assert item["label"] == "A" and item["labels"] == ["A", "B"]


# ── 신청 진입점이 없는 업무 ──────────────────────────────────────────────────────

def test_documents_are_dropped_when_the_business_has_no_apply_link(page):
    """예금자보호제도는 신청 절차가 없다(한도 내 자동 보호). 그런 질문에 구비서류가 붙으면
    본문("별도 절차 없이 자동으로 적용됩니다")과 정면으로 모순된다 — 실물로 안내자료
    게시판의 공지 첨부 29건이 '필요 서류'로 붙었다."""
    page(business_function="예금자보호제도", page_title="안내자료 다운로드",
         form_attachments=[{"label": "2019년도 현장조사 실시 통보", "page_url": SAME_URL}])
    out = build_civil_petition_answer(CHUNKS)
    assert out["links"] == []
    assert out["documents"] == []


def test_documents_survive_when_the_business_has_an_apply_link(page):
    page(business_function="착오송금 반환 신청", page_title="구비서류안내 - 착오송금인",
         form_attachments=[{"label": "신청서양식 다운로드", "page_url": SAME_URL}])
    out = build_civil_petition_answer(CHUNKS)
    assert out["links"] and len(out["documents"]) == 1


# ── 렌더 ─────────────────────────────────────────────────────────────────────────

def test_rendered_line_shows_the_names_and_the_link_once():
    line = _format_document_line(
        {"label": "구비서류안내", "labels": ["신청서양식", "위임장"], "url": SAME_URL})
    assert line == f"- 구비서류안내 (신청서양식 · 위임장): {SAME_URL}"
    assert line.count(SAME_URL) == 1


def test_rendered_line_for_a_single_document_is_unchanged():
    assert _format_document_line({"label": "다운로드", "url": SAME_URL}) == f"- 다운로드: {SAME_URL}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
