"""출처 표시(citation) — 검색된 청크를 사람이 읽을 근거 자료 정보로 변환.

청크(data/chunks_all.jsonl)엔 sub_category가 없다 — 검색 색인에 불필요해 corpus
단계에서 뺀 필드다(docs/metadata_schema.md 참고). 그래서 chunk_id에서 page_id를
뽑아 data/corpus.jsonl로 되짚어(parent 조회) sub_category(브레드크럼)·source_url·
page_title을 가져온다. corpus.jsonl 하나에 세 필드가 다 있으므로 조회는 한 번이면 된다.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_page_meta = {}


def _load_page_meta():
    """page_id -> {sub_category, source_url, page_title}. 프로세스당 한 번만 로드."""
    if not _page_meta:
        with open(ROOT / "data" / "corpus.jsonl", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                _page_meta[d["page_id"]] = {
                    "sub_category": d["sub_category"],
                    "source_url": d["source_url"],
                    "page_title": d["page_title"],
                }
    return _page_meta


def format_citation(chunk_id):
    """청크 하나의 출처를 {page_id, breadcrumb, title, url} 딕셔너리로 반환.
    브레드크럼은 sub_category를 그대로 쓴다(이미 "업무 > 대분류 > ..." 경로 형식).
    최종 문자열 꾸미기(마크다운 링크 등)는 prompt_builder.py 쪽 책임으로 남겨두고,
    여기서는 재료(dict)만 깔끔하게 반환한다."""
    page_id = chunk_id.split("#")[0]
    meta = _load_page_meta().get(page_id, {})
    return {
        "page_id": page_id,
        "breadcrumb": meta.get("sub_category", ""),
        "title": meta.get("page_title", ""),
        "url": meta.get("source_url", ""),
    }


def format_all_citations(chunk_ids):
    """여러 청크 id의 출처를 페이지 기준으로 중복 제거해 목록화한다.

    같은 페이지에서 나온 청크가 top-k 안에 여러 개 있을 수 있으므로(예: faq_msdr_apply#3,
    faq_msdr_apply#4가 둘 다 포함), page_id 기준으로 첫 등장한 순서만 남긴다 — 청크는
    관련도 점수순으로 들어오므로, 첫 등장 순서 = 가장 중요한 출처부터의 순서다."""
    seen_pages = []
    for cid in chunk_ids:
        page_id = cid.split("#")[0]
        if page_id not in seen_pages:
            seen_pages.append(page_id)
    return [format_citation(pid) for pid in seen_pages]
