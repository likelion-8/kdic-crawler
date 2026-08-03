"""documents/document_chunks(신규 스키마, schema.py)에 실제 문서+청크+임베딩 적재.

kdic_chunks_all(index_pgvector.py, 레거시 flat 테이블)을 대체하는 정식 스키마 적재 —
documents는 data/corpus.jsonl(페이지 단위 원문), document_chunks는 index_qdrant.py와
동일하게 build_units("all")+load_chunk_meta()로 만든 청크에 임베딩을 붙여 넣는다.

매번 documents/document_chunks를 비우고 다시 채운다(멱등 재실행). FK 때문에
document_chunks를 먼저 지운다.

실행: python3 src/project1_src/index_document_chunks.py
"""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chunking import build_units, is_faq, is_table, load_records  # noqa: E402
from db import get_engine  # noqa: E402
from index_qdrant import load_chunk_meta, validate_business_functions  # noqa: E402
from retrieval import DenseRetriever  # noqa: E402
from schema import document_chunks, documents  # noqa: E402

from sqlalchemy import text  # noqa: E402

_EXTRA_META_KEYS = ("required", "note", "links", "attachments", "form_attachments", "videos", "images")


def _chunk_type(page_text):
    if is_faq(page_text):
        return "faq"
    if is_table(page_text):
        return "table"
    return "page"


def main():
    records = load_records()
    page_text = {r["page_id"]: r["text"] for r in records}

    uids, texts, u2p = build_units("all")
    dense = DenseRetriever(uids, texts)  # 캐시 있으면 그대로 로드
    chunk_meta = load_chunk_meta()
    validate_business_functions(chunk_meta)

    doc_rows = [{
        "page_id": r["page_id"],
        "source_url": r.get("source_url"),
        "page_title": r.get("page_title"),
        "business_function": r.get("business_function"),
        "sub_category": r.get("sub_category"),
        "content": r.get("text"),
        "summary": r.get("summary"),
        "content_sha256": r.get("content_sha256"),
        "collected_at": date.fromisoformat(r["collected_at"]) if r.get("collected_at") else None,
        "metadata": {k: r.get(k) for k in _EXTRA_META_KEYS},
    } for r in records]

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM document_chunks"))
        conn.execute(text("DELETE FROM documents"))
        conn.execute(documents.insert(), doc_rows)

        page_id_to_doc_id = dict(conn.execute(text("SELECT page_id, id FROM documents")).all())

        chunk_rows = []
        for i, uid in enumerate(uids):
            pid = u2p[uid]
            m = chunk_meta.get(uid, {})
            suffix = uid.rsplit("#", 1)[1] if "#" in uid else "0"
            chunk_rows.append({
                "document_id": page_id_to_doc_id[pid],
                "chunk_id": uid,
                "chunk_index": int(suffix),
                "chunk_type": _chunk_type(page_text[pid]),
                "text": texts[i],
                "embedding": dense.doc_emb[i].tolist(),
                "business_function": m.get("business_function"),
                "page_title": m.get("page_title"),
                "source_url": m.get("source_url"),
            })
        conn.execute(document_chunks.insert(), chunk_rows)

        doc_count = conn.execute(text("SELECT count(*) FROM documents")).scalar()
        chunk_count = conn.execute(text("SELECT count(*) FROM document_chunks")).scalar()

    print(f"적재 완료: documents {doc_count}행, document_chunks {chunk_count}행")


if __name__ == "__main__":
    sys.exit(main())
