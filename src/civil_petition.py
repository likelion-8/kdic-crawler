"""민원 처리(신청) 의도 질문에 대한 3단계 응답 조립 — 절차 안내·서류 안내·페이지 연결.

intent=civil_petition으로 판별된 질문에서만 쓴다(informational은 근거 청크로 바로
답변하면 되고 이 3단계 조립이 필요 없다). 새로 검색하지 않는다 — pipeline.py가
route_search_chunks → rerank → top_k_cut으로 이미 뽑아둔 근거 청크를 그대로 받아
용도별로 재가공만 한다.
"""
import json
from pathlib import Path

from citation import format_all_citations

ROOT = Path(__file__).resolve().parent.parent
_page_docs = {}


def _load_page_docs():
    """page_id -> {attachments, form_attachments}. corpus.jsonl에서 한 번만 로드.

    이 두 필드는 chunks_all.jsonl엔 없다(검색 색인에 불필요해 청크 단계에서 뺀 필드 —
    citation.py의 sub_category와 같은 이유). page_id로 corpus.jsonl을 되짚어 조회한다.
    """
    if not _page_docs:
        with open(ROOT / "data" / "corpus.jsonl", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                _page_docs[d["page_id"]] = {
                    "attachments": d.get("attachments", []),
                    "form_attachments": d.get("form_attachments", []),
                }
    return _page_docs


def _unique_page_ids(chunks):
    """chunks: [(chunk_id, score, text), ...]. page_id를 첫 등장 순서(=관련도 순)로 중복 제거."""
    seen = []
    for cid, _, _ in chunks:
        page_id = cid.split("#")[0]
        if page_id not in seen:
            seen.append(page_id)
    return seen


def build_procedure_section(chunks):
    """절차 안내(신청 대상·기한·단계). 근거 청크 본문을 그대로 이어붙인다 — 절차 정보는
    corpus에 별도 구조화 필드가 아니라 본문 텍스트 안에 이미 서술돼 있고(예: "1. 착오송금인은
    예금보험공사..."), reranking이 이미 절차 관련 청크를 상위로 올려둔 상태이기 때문이다."""
    return "\n\n".join(text for _, _, text in chunks)


def build_document_section(chunks):
    """서류 안내. 근거 청크가 속한 페이지들의 첨부·서식 다운로드 링크를 모은다.

    (label, url) 기준으로 중복을 제거한다 — corpus.jsonl의 form_attachments 자체에
    같은 서식이 중복 추출된 경우가 있어서(크롤러가 같은 JS 다운로드 버튼을 두 번 잡음,
    예: sender_docs 페이지 28건 중 16건 중복), 원본을 그대로 노출하면 같은 다운로드
    링크가 응답에 반복돼 보인다."""
    docs = _load_page_docs()
    items, seen = [], set()
    for page_id in _unique_page_ids(chunks):
        d = docs.get(page_id, {})
        for a in d.get("attachments", []):
            key = (a.get("text"), a.get("url"))
            if key not in seen:
                seen.add(key)
                items.append({"page_id": page_id, "label": a.get("text"), "url": a.get("url")})
        for fa in d.get("form_attachments", []):
            url = fa.get("resolved_url") or fa.get("page_url")
            key = (fa.get("label"), url)
            if key not in seen:
                seen.add(key)
                items.append({"page_id": page_id, "label": fa.get("label"), "url": url})
    return items


def build_link_section(chunks):
    """페이지 연결(신청 페이지 URL). citation.py가 이미 만든 출처 데이터를 그대로 재사용
    한다 — "근거로 삼은 페이지"와 "신청하러 가야 할 페이지"가 같은 데이터이므로 중복
    조회하지 않는다."""
    chunk_ids = [cid for cid, _, _ in chunks]
    return [{"title": c["title"], "url": c["url"]} for c in format_all_citations(chunk_ids)]


def build_civil_petition_answer(chunks):
    """절차 -> 서류 -> 페이지 연결 3단계를 순서대로 조립한다.
    최종 문자열 포맷(마크다운 등)은 prompt_builder.py 책임으로 남긴다."""
    return {
        "procedure": build_procedure_section(chunks),
        "documents": build_document_section(chunks),
        "links": build_link_section(chunks),
    }
