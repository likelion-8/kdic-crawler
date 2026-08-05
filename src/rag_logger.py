"""실사용 질문·답변을 Supabase rag_runs에 기록.

실사용 경로에서만 호출한다 — pipeline.rag_answer()(Streamlit·터미널)와 api/rag/sse.py
(웹 챗봇). eval_pipeline_generation.py/measure_baseline.py 등은 _rag_answer_traced()를
직접 불러 로깅을 우회하므로, 평가·성능측정 실행이 실사용 로그를 오염시키지 않는다.

API 경로는 request_id/session_id를 함께 넘긴다. request_id는 응답으로 나간 답변 식별자와
같은 값이라, 사용자가 그 답변에 남긴 피드백(feedback 테이블)을 이 행에 연결하는 열쇠다.
Streamlit·터미널은 그 개념이 없어 비운다.

검색 후보/선택 상세(rag_retrieval_results)는 일부러 로깅하지 않는다 — 질문 1건당 20행씩
쌓여 부담이 크고, 추후 Langfuse로 trace를 붙이면 그쪽이 이 역할을 전담한다(2026-08-04
팀 결정). 필요해지면 그때 Langfuse 쪽 설계에 맞춰 다시 붙인다.

로깅 실패가 챗봇 응답 자체를 막으면 안 되므로 모든 예외를 여기서 삼키고 print만 한다 —
호출부는 로깅 성공 여부를 신경 쓰지 않는다.
"""
from db import get_session
from schema import rag_runs


def log_rag_run(question, answer, intent, question_type, retrieval_route,
                 total_latency_ms, llm_model=None, embedding_model=None,
                 request_id=None, session_id=None, status="success"):
    try:
        with get_session() as session:
            session.execute(
                rag_runs.insert(),
                {
                    "question": question, "intent": intent, "question_type": question_type,
                    "retrieval_route": retrieval_route, "answer": answer, "status": status,
                    "total_latency_ms": round(total_latency_ms),
                    "llm_model": llm_model, "embedding_model": embedding_model,
                    "request_id": request_id, "session_id": session_id,
                },
            )
    except Exception as e:
        print(f"[rag_logger] 로깅 실패(무시하고 계속): {e}")
