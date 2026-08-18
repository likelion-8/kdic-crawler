"""src/ingest — 승인된 신규 페이지를 코퍼스·수집 대상에 넣는다(미구현 ①). fetcher 주입, 임시 파일.

회귀 대상 : (1) 미리보기와 같은 파서로 본문을 만든다(검수한 청크와 다르면 안 됨), (2) 같은
page_id 는 교체(중복 행 금지 — REINDEX 가 두 번 색인함), (3) 빈 본문은 거절, (4) 실제
corpus.jsonl 은 건드리지 않는다(경로 주입).
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "src", ROOT / "src" / "crawler"):
    sys.path.insert(0, str(p))

import ingest  # noqa: E402

HTML = """<html><head><title>새 페이지 | 예금보험공사</title>
<meta name="description" content="테스트 요약"></head>
<body><div id="contents"><h2>새 제도 안내</h2>
<p>예금자보호제도에 따라 금융회사가 영업정지나 파산 등으로 예금을 지급할 수 없게 되면 예금보험공사가 예금자에게 보험금을 지급합니다.</p>
<p>보호한도는 1인당 원금과 소정이자를 합하여 1억원입니다. 초과 금액은 파산 배당으로 일부 회수될 수 있습니다.</p>
<p>보호 대상 금융회사는 은행, 보험회사, 투자매매업자, 종합금융회사, 상호저축은행입니다. 자세한 사항은 고객센터로 문의해 주세요.</p>
</div></body></html>"""


def _fetch(url):
    return SimpleNamespace(html=HTML, url=url)


def _record(**over):
    base = {"page_id": "test_new_page", "source_url": "https://www.kdic.or.kr/x/new.do",
            "business_function": "예금자보호제도", "sub_category": "", "page_title": "",
            "required": True, "note": "검증", "summary": "", "owner": "verify"}
    return {**base, **over}


def _read(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def test_ingest_appends_corpus_and_inventory(tmp_path):
    corpus, inv = tmp_path / "corpus.jsonl", tmp_path / "inv.jsonl"
    r = ingest.ingest_page(_record(), fetcher=_fetch, corpus_path=corpus, inventory_path=inv)
    assert r["replaced"] is False and r["text_chars"] > 0
    rows = _read(corpus)
    assert len(rows) == 1 and rows[0]["page_id"] == "test_new_page"
    assert "1억원" in rows[0]["text"]
    assert rows[0]["content_sha256"]                      # 갱신 감지 기준값
    assert rows[0]["page_title"] == "새 페이지"   # 비운 제목은 파서 값으로(사이트명 접미 제거됨)
    assert _read(inv)[0]["id"] == "test_new_page" and _read(inv)[0]["added_by_admin"] is True


def test_same_page_id_is_replaced_not_duplicated(tmp_path):
    corpus, inv = tmp_path / "corpus.jsonl", tmp_path / "inv.jsonl"
    ingest.ingest_page(_record(), fetcher=_fetch, corpus_path=corpus, inventory_path=inv)
    r = ingest.ingest_page(_record(note="다시"), fetcher=_fetch, corpus_path=corpus, inventory_path=inv)
    assert r["replaced"] is True
    assert len(_read(corpus)) == 1 and _read(corpus)[0]["note"] == "다시"


def test_empty_body_is_rejected(tmp_path):
    # 파서(preview.parse_document)가 짧은 본문을 먼저 거절한다 — 미리보기와 같은 기준이라 검수한
    # 것과 다른 것이 적재될 수 없다. 어느 예외든 '적재되지 않는다'가 계약이다
    def empty(url): return SimpleNamespace(html="<html><body></body></html>", url=url)
    with pytest.raises(Exception, match="본문"):
        ingest.ingest_page(_record(), fetcher=empty,
                           corpus_path=tmp_path / "c.jsonl", inventory_path=tmp_path / "i.jsonl")


def test_missing_required_fields_rejected(tmp_path):
    with pytest.raises(ValueError, match="필수"):
        ingest.ingest_page(_record(business_function=""), fetcher=_fetch,
                           corpus_path=tmp_path / "c.jsonl", inventory_path=tmp_path / "i.jsonl")


def test_remove_page_drops_from_both(tmp_path):
    corpus, inv = tmp_path / "corpus.jsonl", tmp_path / "inv.jsonl"
    ingest.ingest_page(_record(), fetcher=_fetch, corpus_path=corpus, inventory_path=inv)
    assert ingest.remove_page("test_new_page", corpus_path=corpus, inventory_path=inv) is True
    assert _read(corpus) == [] and _read(inv) == []


def test_output_is_lf_utf8(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    ingest.ingest_page(_record(), fetcher=_fetch, corpus_path=corpus, inventory_path=tmp_path / "i.jsonl")
    raw = corpus.read_bytes()
    assert b"\r\n" not in raw, "CRLF 면 공유 임베딩 캐시 해시가 틀어진다(CLAUDE.md 불변식)"


def test_collected_at_matches_indexer_date_format(tmp_path):
    """색인기는 date.fromisoformat 으로 읽는다 — 시각이 붙으면 색인 단계가 죽는다(E2E 실측)."""
    from datetime import date
    corpus = tmp_path / "corpus.jsonl"
    ingest.ingest_page(_record(), fetcher=_fetch, corpus_path=corpus, inventory_path=tmp_path / "i.jsonl")
    date.fromisoformat(_read(corpus)[0]["collected_at"])   # 예외 없이 파싱돼야 한다


@pytest.mark.parametrize("bad", [
    "http://www.kdic.or.kr/x.do",             # HTTPS 아님
    "https://169.254.169.254/latest/meta-data", # 클라우드 메타데이터
    "https://localhost:8000/api/health",        # 로컬
    "https://10.0.0.5/admin",                   # 사설 IP
    "https://evil.example.com/kdic.or.kr",      # 허용 목록 밖
    "https://user:pw@www.kdic.or.kr/x.do",      # userinfo
])
def test_ingest_rejects_urls_outside_the_allowlist(tmp_path, bad):
    """SSRF 방어 — 승인 URL 도 미리보기와 같은 허용 목록·스킴 검증을 통과해야 한다. 여기서
    fetcher 는 절대 호출되면 안 된다(호출되면 서버가 임의 주소를 대신 요청한 것)."""
    called = {"n": 0}
    def spy(url):
        called["n"] += 1
        return SimpleNamespace(html=HTML, url=url)
    with pytest.raises(Exception):
        ingest.ingest_page(_record(source_url=bad), fetcher=spy,
                           corpus_path=tmp_path / "c.jsonl", inventory_path=tmp_path / "i.jsonl")
    assert called["n"] == 0, f"허용 목록 밖 URL 을 fetch 했다: {bad}"
