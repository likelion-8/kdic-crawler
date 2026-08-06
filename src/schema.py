"""RAG 서비스 본 스키마(documents/document_chunks/evaluation_dataset/test_set/rag_runs)
— Supabase PostgreSQL(pgvector)에 생성.

기획서(Supabase PostgreSQL 저장 데이터 정리.pdf) "최소 구축안" 6개 중 rag_trace_steps는
제외했다(팀 결정 — trace는 나중 단계). crawl_runs/crawl_results/document_versions/
evaluation_runs/evaluation_results도 운영 단계 착수 전이라 아직 안 만든다.

rag_retrieval_results(검색 후보/선택 추적)도 한때 만들었다가 제거했다 — 질문 1건당
20행씩 쌓이는 부담 대비 실익이 낮고, 추후 Langfuse로 trace를 붙이면 그쪽이 이 역할을
전담하기로 했다(2026-08-04 팀 결정, rag_logger.py 참고).

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
    Boolean, Column, DateTime, ForeignKey, Integer, MetaData, String,
    Table, Text, UniqueConstraint, func, text,
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
    # 답변 1건의 식별자. API가 응답(ChatResponse.request_id)으로 내보낸 값을 그대로 저장한다.
    # 사용자가 그 답변에 피드백을 남길 때 이 값으로 대상을 찾으므로, 없으면 feedback을 붙일
    # 곳이 사라진다. 미들웨어의 요청추적 request_id(X-Request-ID)와는 다른 값이다.
    Column("request_id", String, unique=True),
    # 대화(세션) 식별자. 한 대화의 여러 질문을 묶어 보거나 복원할 때 쓴다.
    Column("session_id", String),
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

# 답변 1건에 대한 사용자 피드백. 프론트는 👍/👎를 먼저 보내고(POST), 👎일 때만 사유 칩·자유
# 의견을 뒤이어 보낸다(PATCH). 그래서 vote는 필수, reason_codes/comment는 나중에 채워진다.
#
# request_id에 unique를 건 이유: 같은 답변에 대한 피드백은 최종 1건만 남는다(사용자가 👍를
# 눌렀다 👎로 바꾸면 덮어쓴다). 이 제약이 있어야 애플리케이션이 upsert로 그 규칙을 강제할 수 있다.
# rag_runs.request_id를 가리키지만 FK는 걸지 않는다 — 로깅(rag_logger)이 실패-안전이라 답변
# 행이 없을 수 있고, 그때 피드백까지 거부되면 사용자에게 이유 없는 실패가 보인다.
feedback = Table(
    "feedback", metadata,
    _uuid_pk(),
    Column("request_id", String, nullable=False, unique=True),
    Column("session_id", String),
    Column("vote", String, nullable=False),          # 'up' | 'down'
    Column("reason_codes", ARRAY(String)),           # codes.ts ReasonCode (INACCURATE 등)
    Column("comment", Text),                         # 마스킹 후 저장 · 최대 200자
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
)


# 대화 복원(GET /api/sessions/{id})용. 새로고침·재방문 시 24시간 이내 대화를 되살린다.
#
# rag_runs에 컬럼을 더하지 않고 따로 둔 이유는 신뢰성 요구가 다르기 때문이다. rag_logger는
# 모든 예외를 삼킨다(로깅이 답변을 막으면 안 되므로) — 관측 기록으로는 맞지만, 대화 상태에
# 그 방식을 쓰면 한 턴이 조용히 빠져 사용자가 '중간에 구멍 난 대화'를 보게 된다. 또 rag_runs는
# 한 행이 Q&A 한 쌍이라 답변이 실패한 턴(질문만 있는 턴)을 표현할 자리가 없다.
chat_sessions = Table(
    "chat_sessions", metadata,
    Column("session_id", String, primary_key=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    # 24시간 판정 기준. 턴마다 갱신한다. 오래된 세션도 행은 지우지 않고 조회에서 404로 막는다
    # (삭제는 되돌릴 수 없고, 관리자 대화 로그(AD-005)는 더 오래 봐야 한다).
    Column("last_activity_at", DateTime(timezone=True), server_default=func.now()),
)


# 대화의 말풍선 한 개. 프론트 RestoredMessage(web/src/routes/chat/ChatPage.tsx:84)와 1:1이라
# user/assistant를 각각 한 행으로 넣는다.
#
# sources/attachments를 JSONB 스냅샷으로 두는 이유: page_id만 저장하고 조회 때 documents를
# 조인하면 '그때 보여준 것'과 '지금 보여주는 것'이 달라진다(페이지가 비활성되거나 제목이
# 바뀌면 과거 대화의 출처가 변하거나 사라진다). 복원은 그 순간의 화면을 그대로 되살리는
# 것이라 통째로 박아둬야 맞고, 통째로 읽고 쓰는 데이터라 JSONB가 적합하다.
#
# seq가 필요한 이유: created_at으로만 정렬하면 user/assistant가 같은 순간에 들어갈 때 순서가
# 뒤집혀 질문과 답변이 거꾸로 표시될 수 있다. 눈에 잘 안 띄면서 치명적인 종류의 버그다.
chat_messages = Table(
    "chat_messages", metadata,
    _uuid_pk(),
    Column("session_id", String, nullable=False, index=True),
    Column("seq", Integer, nullable=False),           # 세션 내 순번 (1부터)
    Column("role", String, nullable=False),           # 'user' | 'assistant'
    Column("text", Text, nullable=False),
    # 이 답변의 식별자(피드백 대상). assistant 행만 채운다 — rag_runs.request_id와 같은 값이다.
    Column("request_id", String),
    Column("sources", JSONB),                         # citation.format_citation() 결과 배열
    Column("attachments", JSONB),                     # civil_petition 서류·링크 배열
    # 복합 질문의 하위 답변 [{title, answer, sources[], attachments[]}]. 이게 채워지면 위의
    # sources/attachments 는 빈 배열이다(근거가 전부 하위로 내려간다) — done 이벤트와 같은 규칙.
    # 둘 다 채우면 프론트가 최상위와 하위를 모두 그려 출처가 두 배로 보인다.
    Column("sub_answers", JSONB),
    Column("out_of_scope", Boolean),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    # seq는 MAX(seq)+1로 계산하므로, 같은 세션에 동시 요청이 들어오면 같은 값이 나올 수 있다.
    # 프론트가 스트리밍 중 입력을 잠가 현실적으로 겹치지 않지만, 겹쳤을 때 순서가 조용히
    # 어긋나는 것보다 여기서 실패하는 편이 낫다.
    UniqueConstraint("session_id", "seq", name="chat_messages_session_seq_key"),
)


# 웰컴 화면의 자주 묻는 질문(CB-001) + 관리자 추천질문 관리(AD-009)가 함께 쓰는 목록.
# 원천을 하나로 둬야 두 화면이 서로 다른 질문을 보여주는 일이 없다.
#
# 컬럼은 프론트 SuggestedQuestion(web/src/routes/admin/settings/promptops/api.ts:158)과 맞췄다.
# 공개 API(GET /api/suggestions)는 이 중 id/text/business_function만 내보내고, active/order/
# click_count는 관리자 화면 몫이다.
#
# id를 uuid가 아니라 문자열 PK로 둔 이유: 프론트가 'sq_01' 같은 읽히는 값을 쓰고 있고,
# 사람이 Supabase 대시보드에서 직접 행을 편집하는 게 당분간 유일한 관리 수단이라
# 눈으로 알아볼 수 있는 편이 낫다.
suggested_questions = Table(
    "suggested_questions", metadata,
    Column("id", String, primary_key=True),
    Column("text", Text, nullable=False),
    Column("business_function", String),      # codes.ts BUSINESS_FUNCTIONS 6종
    Column("active", Boolean, nullable=False, server_default=text("true")),
    Column("display_order", Integer, nullable=False),   # 'order'는 SQL 예약어라 이름을 바꿨다
    Column("click_count", Integer, nullable=False, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
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


# 추천질문 초기값 — 기획서 CB-001 §2.4 「자주 묻는 질문 TOP 10」 원문 그대로다(순서 포함).
# 착오송금에 편중돼 있는데 오타가 아니라 기획서 그대로이며, AD-009의 '업무 균형 경고'를 그
# 화면에서 실제로 보여주기 위한 예시다(프론트 mocks/data/admin.ts:203 주석과 같은 근거).
# 테이블이 비어 있을 때만 넣는다 — 운영에서 지운 질문이 재실행 때 되살아나면 안 된다.
_SUGGESTED_QUESTIONS_SEED = [
    ("sq_01", "착오송금 반환까지 얼마나 걸리나요?", "착오송금 반환 신청", 1),
    ("sq_02", "반환지원 대상이 아닌 경우는 어떤 경우인가요?", "착오송금 반환 신청", 2),
    ("sq_03", "반환지원 대상 금액은 얼마까지인가요?", "착오송금 반환 신청", 3),
    ("sq_04", "어떤 금융회사·앱이 반환지원 대상인가요?", "착오송금 반환 신청", 4),
    ("sq_05", "방문 신청도 가능한가요?", "착오송금 반환 신청", 5),
    ("sq_06", "상속인 금융거래 조회 기간은 어떻게 되나요?", "고객 미수령금 신청", 6),
    ("sq_07", "보이스피싱 피해도 신청할 수 있나요?", "착오송금 반환 신청", 7),
    ("sq_08", "토스·카카오페이 간편송금도 지원되나요?", "착오송금 반환 신청", 8),
    ("sq_09", "착오송금 후 언제까지 신청해야 하나요?", "착오송금 반환 신청", 9),
    ("sq_10", "은행 반환절차 없이 바로 신청할 수 있나요?", "착오송금 반환 신청", 10),
]


def _seed_suggested_questions(conn):
    if conn.execute(text("SELECT count(*) FROM suggested_questions")).scalar():
        return 0
    conn.execute(
        suggested_questions.insert(),
        [{"id": i, "text": t, "business_function": bf, "display_order": o, "active": True}
         for i, t, bf, o in _SUGGESTED_QUESTIONS_SEED],
    )
    return len(_SUGGESTED_QUESTIONS_SEED)


def main():
    engine = get_engine()
    with engine.begin() as conn:
        metadata.create_all(conn, checkfirst=True)
        conn.execute(text(_SYNC_TRIGGER_SQL))
        # evaluation_dataset이 embedding 컬럼 추가 전에 이미 만들어졌을 수 있어 create_all이
        # 건너뛴다(테이블 존재 여부만 봄, 컬럼 diff는 안 함) — 별도로 멱등하게 추가.
        conn.execute(text("ALTER TABLE evaluation_dataset ADD COLUMN IF NOT EXISTS embedding vector(1024)"))
        # rag_runs도 같은 이유로 뒤늦게 추가한 컬럼이 있다(피드백 연결용 request_id/session_id).
        conn.execute(text("ALTER TABLE rag_runs ADD COLUMN IF NOT EXISTS request_id text"))
        conn.execute(text("ALTER TABLE rag_runs ADD COLUMN IF NOT EXISTS session_id text"))
        # chat_messages.sub_answers 도 테이블을 만든 뒤에 추가했다. create_all 은 컬럼 diff 를
        # 보지 않으니(테이블 존재 여부만 본다) 여기서 멱등하게 더한다 — 팀원들이 각자
        # `python src/schema.py` 만 돌리면 반영되므로 손으로 SQL 을 칠 필요가 없다.
        conn.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS sub_answers jsonb"))
        # 답변 1건당 피드백 1건 규칙을 DB가 강제하려면 unique가 필요하다. ADD CONSTRAINT에는
        # IF NOT EXISTS가 없어 카탈로그를 먼저 확인한다.
        conn.execute(text("""
            DO $$ BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'rag_runs_request_id_key') THEN
                    ALTER TABLE rag_runs ADD CONSTRAINT rag_runs_request_id_key UNIQUE (request_id);
                END IF;
            END $$;
        """))
        seeded = _seed_suggested_questions(conn)
    print("생성 완료:", ", ".join(t.name for t in metadata.sorted_tables))
    print(f"추천질문 시드: {seeded}건 삽입" if seeded else "추천질문 시드: 이미 데이터가 있어 건너뜀")
    print("트리거 생성 완료: trg_sync_document_chunks_is_active (documents.is_active → document_chunks.is_active)")


if __name__ == "__main__":
    sys.exit(main())
