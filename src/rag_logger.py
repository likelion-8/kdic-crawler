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

## status 어휘 (2026-08-12 팀 결정)

정본은 web/src/routes/admin/logs/api.ts 의 LogStatus 타입이고 아래 3값이 전부다.
관리자 대화 로그(AD-005)의 상태 칩·필터·집계가 전부 이 문자열로 갈린다.

    NORMAL          정상 종료
    OUT_OF_SCOPE    근거를 하나도 쓰지 않은 답변(인사·정체성·범위 밖)
    FAILED          에러로 종료 — failure_stage/root_cause가 함께 채워진다

⚠️ 2026-08-12 이전 행에는 옛 기본값 "success" 가 그대로 들어 있다. 새 어휘 3값 어디에도
안 걸리므로 AD-005 집계에서 total 과 (normal+out_of_scope+failed) 가 어긋난다. 과거 행을
NORMAL 로 한 번 정정하는 것은 이 파일 밖의 일이다(팀 확인 대기).
"""
from db import get_session
from schema import rag_runs

# 상태 3값. 문자열을 각 호출부에 흩어 놓으면 오타 하나가 조용히 집계에서 빠지므로 여기 모은다.
STATUS_NORMAL = "NORMAL"
STATUS_OUT_OF_SCOPE = "OUT_OF_SCOPE"
STATUS_FAILED = "FAILED"

# 실패 단계. api/rag/answer.py 의 error_from_exception(phase=...) 가 쓰는 값과 같아야 한다 —
# 같은 실패가 사용자 오류코드와 로그에서 다른 이름으로 불리면 대조가 안 된다.
STAGE_RETRIEVAL = "retrieval"
STAGE_LLM = "llm"


def log_rag_run(question, answer, intent, question_type, retrieval_route,
                 total_latency_ms, llm_model=None, embedding_model=None,
                 request_id=None, session_id=None, status=STATUS_NORMAL,
                 failure_stage=None, root_cause=None, trace_id=None):
    """질의 1건을 rag_runs 에 남긴다.

    status/failure_stage/root_cause 는 전부 기본값이 있다. src/pipeline.py(CLI·Streamlit)가
    이 함수를 위치·키워드 혼용으로 부르는데 그 파일은 이 변경의 소유가 아니므로, 기본값이
    없으면 머지는 깨끗하게 되고 실행 시점에 TypeError 로 죽는다.

    failure_stage/root_cause 는 status=FAILED 일 때만 의미가 있다. root_cause 는 예외 타입과
    메시지 원문이다 — 사용자에게 보여준 문구가 아니라 조사에 쓸 내부 원문을 넣는다.

    trace_id 는 Langfuse trace 식별자(observability.current_trace_id())다. 관리자 대화 로그
    상세(AD-005)가 API_LANGFUSE_HOST 로 링크를 완성한다. 관측이 꺼져 있으면 None(무해).
    """
    try:
        with get_session() as session:
            session.execute(
                rag_runs.insert(),
                {
                    "question": question, "intent": intent, "question_type": question_type,
                    "retrieval_route": retrieval_route, "answer": answer, "status": status,
                    "failure_stage": failure_stage, "root_cause": root_cause,
                    "total_latency_ms": round(total_latency_ms),
                    "llm_model": llm_model, "embedding_model": embedding_model,
                    "request_id": request_id, "session_id": session_id,
                    "trace_id": trace_id,
                },
            )
    except Exception as e:
        print(f"[rag_logger] 로깅 실패(무시하고 계속): {e}")
