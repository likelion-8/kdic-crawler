"""청크(all 모드) + 임베딩(bge-m3-ko)을 Supabase Postgres(pgvector)에 적재.

index_qdrant.py의 pgvector 버전 — 같은 데이터를 같은 필드 구성으로 kdic_chunks_all
테이블에 넣는다. 벡터 컬럼엔 인덱스를 안 건다(exact search, 팀 결정 — 현재 규모
500개 안팎에선 HNSW/IVFFlat 도입 실익이 없고 정확도만 깎임).

실행: python3 src/project1_src/index_pgvector.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from chunking import build_units  # noqa: E402
from db import get_engine  # noqa: E402
from index_qdrant import load_chunk_meta, validate_business_functions  # noqa: E402
from retrieval import DEFAULT_DENSE_MODEL, DenseRetriever  # noqa: E402

from pgvector.sqlalchemy import Vector  # noqa: E402
from sqlalchemy import Column, Integer, MetaData, String, Table, text  # noqa: E402

TABLE_NAME = "kdic_chunks_all"

metadata = MetaData()
chunks_table = Table(
    TABLE_NAME, metadata,
    Column("id", Integer, primary_key=True),
    Column("chunk_id", String, unique=True, nullable=False),
    Column("page_id", String),
    Column("source_url", String),
    Column("page_title", String),
    Column("business_function", String),
    Column("text", String),
    Column("embedding", Vector(1024), nullable=False),
)


def main():
    uids, texts, u2p = build_units("all")
    dense = DenseRetriever(uids, texts)  # 캐시 있으면 그대로 로드, 없으면 인코딩+저장
    meta = load_chunk_meta()
    validate_business_functions(meta)  # index_qdrant.py와 동일하게 색인 전 검증

    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        chunks_table.drop(conn, checkfirst=True)
        chunks_table.create(conn)

        rows = [{
            "chunk_id": uid,
            "page_id": u2p[uid],
            "source_url": meta.get(uid, {}).get("source_url"),
            "page_title": meta.get(uid, {}).get("page_title"),
            "business_function": meta.get(uid, {}).get("business_function"),
            "text": texts[i],
            "embedding": dense.doc_emb[i].tolist(),
        } for i, uid in enumerate(uids)]
        conn.execute(chunks_table.insert(), rows)
        count = conn.execute(text(f"SELECT count(*) FROM {TABLE_NAME}")).scalar()

    print(f"적재 완료: {TABLE_NAME} ({count}행, 차원 {dense.doc_emb.shape[1]}, 모델 {DEFAULT_DENSE_MODEL})")


if __name__ == "__main__":
    sys.exit(main())
