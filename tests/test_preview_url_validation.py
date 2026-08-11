"""신규 URL 검증(AD-003)의 빈 구멍 회귀 테스트.

Preview 파이프라인 본체는 tests/test_admin_previews.py 가 덮는다. 이 파일은 그 검증이
실제 kdic.or.kr 을 상대로 놓쳤던 두 가지만 붙잡아 둔다.

    1) soft-404  — HTTP 200 인데 내용이 오류 안내문인 페이지
    2) 공백류·길이 — 정규화가 통과시키면 중복 검사가 헛도는 입력

둘 다 실측으로 확인한 뒤 막은 것이라, 여기서 회귀하면 실제로 다시 뚫린다.
네트워크·DB 없이 돌아간다.
"""
import sys
from pathlib import Path

import pytest

# `python tests/test_preview_url_validation.py` 로도 실행되도록 저장소 루트를 먼저 넣는다.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import api  # noqa: F401  — sys.path 에 src/ 를 넣는 부트스트랩

from crawler.preview import (
    MAX_URL_LENGTH,
    PreviewUrlError,
    looks_like_error_page,
    normalize_preview_url,
    parse_document,
)

# 실제 https://www.kdic.or.kr/no-such-page-xyz 가 302 뒤에 200 으로 돌려주는 페이지다.
SOFT_404_HTML = """
<html><head><title>오류 | KDIC 예금보험공사</title></head>
<body><div id="contents">
  <h1>연결 오류</h1>
  <p>Page Not Found</p>
  <p>연결하려는 페이지에 문제가 있어서 페이지를 표시할 수 없습니다.</p>
  <p>잠시 후에 다시 이용해 주시기 바랍니다.</p>
</div></body></html>
"""

NORMAL_HTML = """
<html><head><title>예금자보호제도 | KDIC 예금보험공사</title></head>
<body><div id="contents">
  <h1>예금자보호제도</h1>
  <p>예금자보호제도는 다수의 소액예금자를 우선 보호하고 부실 금융회사를 선택한 예금자도
     일정부분 책임을 분담한다는 차원에서 운영됩니다. 보호한도는 1억원입니다.</p>
</div></body></html>
"""

# 가운데에 섞여 들어오는 공백류 3종. 눈으로는 구분되지 않으므로 이스케이프로 적는다.
URLS_WITH_INNER_WHITESPACE = (
    "https://www.kdic.or.kr/sp/a b",  # 일반 공백
    "https://www.kdic.or.kr/sp/a b",  # 줄바꿈 없는 공백 — 웹에서 복사할 때 실제로 붙어 온다
    "https://www.kdic.or.kr/sp/a\tb",      # 탭
)


# --------------------------------------------------------------- soft-404 차단
def test_soft_404_is_rejected_even_though_the_status_was_200():
    # 상태코드 검사만으로는 못 잡는다. 통과시키면 "## 연결 오류 / Page Not Found ..." 가
    # 그대로 청킹되어 검색 색인에 오류 안내문이 들어간다.
    with pytest.raises(PreviewUrlError):
        parse_document(SOFT_404_HTML, "https://www.kdic.or.kr/no-such-page-xyz/main.do")


def test_a_normal_page_still_parses():
    parsed = parse_document(NORMAL_HTML, "https://www.kdic.or.kr/sp/dpstrprot/ProtSyst/selectScrn.do")
    assert parsed.title == "예금자보호제도"
    assert "보호한도는 1억원" in parsed.text


def test_error_markers_look_at_the_title_and_the_start_of_the_body():
    # _extract_title() 이 접미사를 떼어 "오류"만 남기는 경우와 "연결 오류" 두 형태를 모두 본다.
    assert looks_like_error_page("오류", "본문") is True
    assert looks_like_error_page("연결 오류", "본문") is True
    assert looks_like_error_page("", "Page Not Found 입니다") is True
    assert looks_like_error_page("예금자보호제도", "예금자보호제도는 ...") is False


def test_error_markers_do_not_fire_on_the_word_appearing_deep_in_a_normal_body():
    # 본문 앞부분만 보는 이유. 정상 안내문 중간에 '오류'가 나온다고 문서를 버리면 안 된다.
    body = "예금자보호제도 안내입니다. " + "정상 본문. " * 40 + "입력 오류가 있으면 문의해 주세요."
    assert looks_like_error_page("예금자보호제도", body) is False


# ------------------------------------------------------------ 공백류·길이 검증
def test_normalize_rejects_whitespace_hidden_inside_the_url():
    # ord < 32 검사만으로는 U+0020 과 U+00A0 이 통과한다. 살려 두면 인코딩 과정에서 같은
    # 주소가 다른 문자열이 되어 뒤쪽 중복 검사가 헛돈다.
    for bad in URLS_WITH_INNER_WHITESPACE:
        with pytest.raises(PreviewUrlError):
            normalize_preview_url(bad)


def test_normalize_still_trims_the_outer_whitespace():
    # 양끝 공백은 붙여넣기 흔적이라 거절이 아니라 정리 대상이다(팀 기존 계약).
    assert normalize_preview_url("  https://www.kdic.or.kr/sp\n") == "https://www.kdic.or.kr/sp"


def test_normalize_caps_the_url_length():
    with pytest.raises(PreviewUrlError):
        normalize_preview_url("https://www.kdic.or.kr/" + "a" * MAX_URL_LENGTH)


def test_normalize_keeps_accepting_the_existing_contract():
    # 기존 동작을 건드리지 않았다는 확인(tests/test_admin_previews.py 와 같은 기대값).
    assert normalize_preview_url(" HTTPS://WWW.KDIC.OR.KR/path#fragment ") == \
        "https://www.kdic.or.kr/path"
    assert normalize_preview_url("https://fins.kdic.or.kr/") == "https://fins.kdic.or.kr/"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
