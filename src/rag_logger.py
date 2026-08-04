"""실사용 질문·답변·검색결과를 Supabase rag_runs/rag_retrieval_results에 기록.

pipeline.rag_answer()(Streamlit·터미널이 실제로 부르는 경로)에서만 호출한다 —
eval_pipeline_generation.py/measure_baseline.py 등은 _rag_answer_traced()를 직접 불러
로깅을 우회하므로, 평가·성능측정 실행이 실사용 로그를 오염시키지 않는다.

로깅 실패가 챗봇 응답 자체를 막으면 안 되므로 모든 예외를 여기서 삼키고 print만 한다 —
호출부는 로깅 성공 여부를 신경 쓰지 않는다.
"""
from sqlalchemy import text

from db import get_session
from schema import document_chunks, rag_retrieval_results, rag_runs


def _chunk_lookup(conn, chunk_ids):
    """chunk_id -> {document_id, page_title, source_url} — rag_retrieval_results에
    제목·URL·문서 FK를 같이 남기려고 document_chunks에서 한 번에 조회한다."""
    if not chunk_ids:
        return {}
    rows = conn.execute(
        text("SELECT chunk_id, document_id, page_title, source_url FROM document_chunks "
             "WHERE chunk_id = ANY(:ids)"),
        {"ids": list(chunk_ids)},
    ).all()
    return {r.chunk_id: r for r in rows}


def log_rag_run(question, answer, intent, question_type, retrieval_route,
                 total_latency_ms, sub_results, llm_model=None, embedding_model=None):
    """sub_results: [(sub_query, candidates, top), ...] — candidates/top은
    route_search_chunks()와 동일한 [(chunk_id, score, text)] 형식(top이 candidates의
    부분집합). candidates 전체는 stage='candidate', top에 속한 것만 stage='selected'로
    남긴다(rag_retrieval_results 설계 목적인 "후보 Top-20 -> 최종 Top-5" 추적)."""
    try:
        all_ids = {cid for _, candidates, _ in sub_results for cid, _, _ in candidates}
        with get_session() as session:
            lookup = _chunk_lookup(session, all_ids)

            run_id = session.execute(
                rag_runs.insert().returning(rag_runs.c.id),
                {
                    "question": question, "intent": intent, "question_type": question_type,
                    "retrieval_route": retrieval_route, "answer": answer, "status": "success",
                    "total_latency_ms": round(total_latency_ms),
                    "llm_model": llm_model, "embedding_model": embedding_model,
                },
            ).scalar_one()

            rows = []
            for sub_query, candidates, top in sub_results:
                selected_ids = {cid for cid, _, _ in top}
                for rank, (cid, score, _text) in enumerate(candidates, start=1):
                    info = lookup.get(cid)
                    rows.append({
                        "rag_run_id": run_id, "sub_query": sub_query, "chunk_id": cid,
                        "rank": rank, "score": score,
                        "stage": "selected" if cid in selected_ids else "candidate",
                        "is_selected": cid in selected_ids,
                        "document_id": info.document_id if info else None,
                        "page_title": info.page_title if info else None,
                        "source_url": info.source_url if info else None,
                    })
            if rows:
                session.execute(rag_retrieval_results.insert(), rows)
    except Exception as e:
        print(f"[rag_logger] 로깅 실패(무시하고 계속): {e}")
