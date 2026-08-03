"""RAG 서비스 본 스키마(documents/document_chunks/evaluation_questions/rag_runs/
rag_retrieval_results) — Supabase PostgreSQL(pgvector)에 생성.

기획서(Supabase PostgreSQL 저장 데이터 정리.pdf) "최소 구축안" 6개 중 rag_trace_steps는
제외했다(팀 결정 — trace는 나중 단계). crawl_runs/crawl_results/document_versions/
evaluation_runs/evaluation_results도 운영 단계 착수 전이라 아직 안 만든다.

기획서 대비 반영한 수정 3건:
1. evaluation_questions에 expected_links, business_function 추가 — 실제 testset
   jsonl(data/testset/*.jsonl)에 이미 두 필드가 있는데 기획서 표엔 빠져 있었음. 없으면
   생성 평가(expected_links 기준)와 업무별 성능 비교(business_function 필터)를 못 돌림.
2. documents.breadcrumb 제거 — sub_category와 값이 같아 중복.
3. documents.is_active → document_chunks.is_active 동기화 트리거 추가 — 문서가
   비활성화됐는데 그 청크가 검색에 계속 걸리는 조용한 버그를 막는다.

기존 kdic_chunks_all(index_pgvector.py)은 그대로 둔다 — 이 파일은 스키마만 만들고
데이터 재적재는 하지 않는다(팀 결정, 별도 작업).

실행: python3 src/schema.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from db import get_engine  # noqa: E402

from pgvector.sqlalchemy import Vector  # noqa: E402
from sqlalchemy import (  # noqa: E402
    Boolean, Column, DateTime, Float, ForeignKey, Integer, MetaData, String,
    Table, Text, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID  # noqa: E402

metadata = MetaData()


def _uuid_pk():
    return Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=text("gen_random_uuid()"))


documents = Table(
    "documents", metadata,
    _uuid_pk(),
    Column("page_id", String, unique=True, nullable=False),
    Column("source_url", String),
    Column("page_title", String),
    Column("business_function", String),
    Column("sub_category", String),
    Column("content", Text),
    Column("summary", Text),
    Column("content_sha256", String),
    Column("collected_at", DateTime(timezone=True)),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("metadata", JSONB),
)

document_chunks = Table(
    "document_chunks", metadata,
    _uuid_pk(),
    Column("document_id", UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False),
    Column("chunk_id", String, unique=True, nullable=False),
    Column("chunk_index", Integer),
    Column("chunk_type", String),
    Column("text", Text, nullable=False),
    Column("embedding", Vector(1024), nullable=False),
    Column("token_count", Integer),
    # 아래 3개는 documents에서 조회 없이 바로 필터링하려고 일부러 중복 저장(비정규화).
    Column("business_function", String),
    Column("page_title", String),
    Column("source_url", String),
    Column("metadata", JSONB),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

evaluation_questions = Table(
    "evaluation_questions", metadata,
    _uuid_pk(),
    Column("question_id", String, unique=True, nullable=False),
    Column("question", Text, nullable=False),
    Column("question_type", String),
    Column("intent", String),
    Column("business_function", String),  # 수정 1: 업무별 성능 비교 필터
    Column("reference_answer", Text),
    Column("expected_sources", ARRAY(String)),
    Column("expected_links", ARRAY(String)),  # 수정 1: 생성 평가 기준
    Column("must_include", ARRAY(String)),
    Column("must_not_include", ARRAY(String)),
    Column("split", String),
    Column("is_active", Boolean, nullable=False, server_default=text("true")),
)

rag_runs = Table(
    "rag_runs", metadata,
    _uuid_pk(),
    Column("trace_id", String),
    Column("question", Text, nullable=False),
    Column("intent", String),
    Column("question_type", String),
    Column("retrieval_route", String),
    Column("answer", Text),
    Column("status", String),
    Column("failure_stage", String),
    Column("root_cause", Text),
    Column("total_latency_ms", Integer),
    Column("llm_model", String),
    Column("embedding_model", String),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

rag_retrieval_results = Table(
    "rag_retrieval_results", metadata,
    _uuid_pk(),
    Column("rag_run_id", UUID(as_uuid=True), ForeignKey("rag_runs.id"), nullable=False),
    Column("sub_query", Text),
    Column("chunk_id", String),
    Column("rank", Integer),
    Column("score", Float),
    Column("stage", String),  # candidate, selected, context
    Column("is_selected", Boolean),
    Column("document_id", UUID(as_uuid=True), ForeignKey("documents.id")),
    Column("source_url", String),
    Column("page_title", String),
)

# 수정 3: documents.is_active가 바뀌면 그 문서의 청크 전부를 같은 값으로 맞춘다.
# 애플리케이션 레이어에서 매번 챙기게 두면 한 곳이라도 빠뜨렸을 때 "비활성 문서의
# 청크가 검색에 걸리는" 조용한 버그가 나므로 DB 트리거로 강제한다.
_SYNC_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION sync_document_chunks_is_active() RETURNS trigger AS $$
BEGIN
    IF NEW.is_active IS DISTINCT FROM OLD.is_active THEN
        UPDATE document_chunks SET is_active = NEW.is_active WHERE document_id = NEW.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sync_document_chunks_is_active ON documents;
CREATE TRIGGER trg_sync_document_chunks_is_active
AFTER UPDATE OF is_active ON documents
FOR EACH ROW
EXECUTE FUNCTION sync_document_chunks_is_active();
"""


def main():
    engine = get_engine()
    with engine.begin() as conn:
        metadata.create_all(conn, checkfirst=True)
        conn.execute(text(_SYNC_TRIGGER_SQL))
    print("생성 완료:", ", ".join(t.name for t in metadata.sorted_tables))
    print("트리거 생성 완료: trg_sync_document_chunks_is_active (documents.is_active → document_chunks.is_active)")


if __name__ == "__main__":
    sys.exit(main())
