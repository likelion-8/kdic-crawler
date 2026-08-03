"""RAG 서비스 본 스키마(documents/document_chunks/evaluation_dataset/test_set/rag_runs/
rag_retrieval_results) — Supabase PostgreSQL(pgvector)에 생성.

기획서(Supabase PostgreSQL 저장 데이터 정리.pdf) "최소 구축안" 6개 중 rag_trace_steps는
제외했다(팀 결정 — trace는 나중 단계). crawl_runs/crawl_results/document_versions/
evaluation_runs/evaluation_results도 운영 단계 착수 전이라 아직 안 만든다.

기획서는 evaluation_questions 하나에 split 컬럼으로 골든셋/테스트셋을 구분하는
안이었으나, 실제로는 골든셋(testset_all.jsonl)과 테스트셋(testset_pipeline.jsonl)이
용도가 뚜렷이 갈려(팀 결정) evaluation_dataset/test_set 두 테이블로 분리했다.
("golden_set"이라는 이름이 애매하다는 팀 결정으로 2026-08-03 evaluation_dataset로 개명.)

기획서 대비 반영한 수정 3건:
1. evaluation_dataset/test_set에 expected_links, business_function 추가 — 실제 testset
   jsonl(data/testset/*.jsonl)에 이미 두 필드가 있는데 기획서 표엔 빠져 있었음. 없으면
   생성 평가(expected_links 기준)와 업무별 성능 비교(business_function 필터)를 못 돌림.
2. documents.breadcrumb 제거 — sub_category와 값이 같아 중복.
3. documents.is_active → document_chunks.is_active 동기화 트리거 추가 — 문서가
   비활성화됐는데 그 청크가 검색에 계속 걸리는 조용한 버그를 막는다.

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

def _eval_question_columns():
    # evaluation_dataset/test_set이 컬럼 구성이 완전히 같아(testset_all.jsonl과
    # testset_pipeline.jsonl 필드 동일) 공유. Column은 테이블 하나에만 바인딩되므로
    # 호출할 때마다 새로 만들어야 한다.
    return [
        Column("question_id", String, unique=True, nullable=False),
        Column("question", Text, nullable=False),
        Column("question_type", String),
        Column("intent", String),
        Column("business_function", String),  # 업무별 성능 비교 필터
        Column("reference_answer", Text),
        Column("expected_sources", ARRAY(String)),
        Column("expected_links", ARRAY(String)),  # 생성 평가 기준
        Column("must_include", ARRAY(String)),
        Column("must_not_include", ARRAY(String)),
        Column("is_active", Boolean, nullable=False, server_default=text("true")),
    ]


# testset_all.jsonl(851문항, 전체 골든셋) 적재 대상. embedding은 query_classifier.py의
# QuestionTypeClassifier가 로컬 JSONL+npy 캐시 대신 여기서 1-NN 참조 예시를 읽도록
# 쓴다(팀 결정 — 매 질문마다 Supabase에 쿼리하는 게 아니라 프로세스 시작 시 한 번만
# 통째로 읽어 메모리에 올려두고 비교하므로 분류 속도엔 영향 없음).
evaluation_dataset = Table("evaluation_dataset", metadata, _uuid_pk(), *_eval_question_columns(),
                            Column("embedding", Vector(1024)))

# testset_pipeline.jsonl(89문항, held-out 평가셋 — evaluation_dataset과 test_id 겹치지 않음) 적재 대상.
test_set = Table("test_set", metadata, _uuid_pk(), *_eval_question_columns())

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
        # evaluation_dataset이 embedding 컬럼 추가 전에 이미 만들어졌을 수 있어 create_all이
        # 건너뛴다(테이블 존재 여부만 봄, 컬럼 diff는 안 함) — 별도로 멱등하게 추가.
        conn.execute(text("ALTER TABLE evaluation_dataset ADD COLUMN IF NOT EXISTS embedding vector(1024)"))
    print("생성 완료:", ", ".join(t.name for t in metadata.sorted_tables))
    print("트리거 생성 완료: trg_sync_document_chunks_is_active (documents.is_active → document_chunks.is_active)")


if __name__ == "__main__":
    sys.exit(main())
