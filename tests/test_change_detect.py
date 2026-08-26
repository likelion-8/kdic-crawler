"""src/change_detect.detect — 원문 변경 감지 판정 로직. fetch·saved 를 주입해 네트워크·DB 없이.

핵심 회귀 대상 : (1) 못 읽은 페이지를 '변경'으로 치지 않는다(관리자 헛걸음 방지),
(2) 옛 판본(expect 불일치)은 채택하지 않는다, (3) 워커 변환 체인과 같은 해시를 쓴다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "src", ROOT / "src" / "crawler"):
    sys.path.insert(0, str(p))

import change_detect  # noqa: E402
from hashing import content_sha256  # noqa: E402

PAGE = {"id": "dp_protlmts", "url": "https://x/dp", "expect": "1억원"}
HTML_A = "<html><body><p>보호한도는 1억원입니다.</p></body></html>"
HTML_B = "<html><body><p>보호한도는 2억원입니다. 1억원 아님</p></body></html>"


def _hash_of(html):
    return content_sha256(change_detect._text_of("dp_protlmts", html))


def _detect(pages, fetch, saved):
    return change_detect.detect(pages, fetch=fetch, saved=saved, sleep=None)


def test_same_text_is_unchanged():
    r = _detect([PAGE], lambda u: HTML_A, {"dp_protlmts": _hash_of(HTML_A)})
    assert r["unchanged"] == ["dp_protlmts"] and r["changed"] == []


def test_different_text_is_changed():
    r = _detect([PAGE], lambda u: HTML_B, {"dp_protlmts": _hash_of(HTML_A)})
    assert r["changed"] == ["dp_protlmts"]


def test_fetch_failure_is_not_a_change():
    def boom(u): raise RuntimeError("timeout")
    r = _detect([PAGE], boom, {"dp_protlmts": _hash_of(HTML_A)})
    assert r["changed"] == [] and r["failed"][0]["page_id"] == "dp_protlmts"


def test_old_edition_is_rejected_not_counted():
    # expect 문자열이 없는 판본만 오면 채택하지 않는다 — 옛 판본을 '변경'으로 오판하지 않는다
    r = _detect([PAGE], lambda u: "<p>5천만원 판본</p>", {"dp_protlmts": _hash_of(HTML_A)})
    assert r["changed"] == [] and "판본" in r["failed"][0]["reason"]


def test_dyn_table_and_unknown_pages_are_skipped():
    dyn = {"id": "uc_bkrp_fndt", "url": "https://x/t", "dyn_table": True}
    new = {"id": "brand_new", "url": "https://x/n"}
    r = _detect([dyn, new], lambda u: HTML_A, {})
    assert set(r["skipped"]) == {"uc_bkrp_fndt", "brand_new"}
    assert r["changed"] == []


def test_html_noise_does_not_trigger_change():
    """HTML 은 튀어도(세션토큰·공백) 본문 텍스트가 같으면 변경이 아니다 — 갱신 감지 기준은
    content_sha256(본문 텍스트)이다(CLAUDE.md 불변식)."""
    noisy = HTML_A.replace("<body>", "<body data-token='abc'>  \n\n")
    r = _detect([PAGE], lambda u: noisy, {"dp_protlmts": _hash_of(HTML_A)})
    assert r["unchanged"] == ["dp_protlmts"]


def test_progress_reports_every_page_once():
    """진행률(%)의 근거 — 건너뛴 페이지·실패한 페이지도 한 번씩 세야 done 이 total 에 닿는다.
    한 갈래라도 빠지면 화면 진행률이 100%에 못 미친 채 끝난다."""
    dyn = {"id": "uc_bkrp_fndt", "url": "https://x/t", "dyn_table": True}
    bad = {"id": "broken", "url": "https://x/b"}

    def fetch(url):
        if url.endswith("/b"):
            raise RuntimeError("timeout")
        return HTML_A

    seen = []
    change_detect.detect([PAGE, dyn, bad], fetch=fetch, saved={"dp_protlmts": _hash_of(HTML_A)},
                         sleep=None, on_progress=lambda done, total: seen.append((done, total)))
    assert seen == [(1, 3), (2, 3), (3, 3)]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
