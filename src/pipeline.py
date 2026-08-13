"""전체 흐름 조립 — 질문 하나를 받아 계획(분해+intent)→검색→근거조립→프롬프트→LLM호출까지
이어붙인 진입점. 각 단계는 이미 만들어진 모듈을 그대로 호출만 한다(새 로직 없음).

현재 실행 순서 (2026-08-09 쿼리 플래너 도입 후):
    plan_query(분해+intent 한 콜) → route_search_chunks → top_k_cut → 근거조립 → 프롬프트 → HCX
재정렬(rerank)은 USE_RERANKER=False라 이 흐름에 끼지 않는다. 아래 각 스위치 주석 참고.

rag_answer()를 부르는 곳은 Streamlit(app.py:316)과 이 파일의 CLI 둘뿐이다. 이 파일을
import하는 나머지 셋(src/crawler/measure_baseline.py · src/eval/eval_pipeline_generation.py ·
src/eval/eval_pipeline_retrieval.py)은 rag_answer()를 건너뛰고 _rag_answer_traced()나
상수(K_CANDIDATES 등)만 가져다 쓴다 — rag_runs 로깅을 우회하기 위한 의도된 구조다.

웹 API(api/rag/answer.py)는 여기를 아예 거치지 않고 같은 빌딩블록으로 흐름을 다시 엮는다 —
rag_answer()가 문자열만 돌려주고 토큰 스트리밍을 못 하기 때문이다. 두 경로가 갈리므로,
이 파일의 파라미터·스위치를 바꾸면 api/rag/answer.py 쪽도 같이 맞춰야 한다.

K_CANDIDATES=20/K_FINAL=5는 candidate_ranking.py의 리랭킹 실측값(Recall@20 99%+, 기존 프로젝트
AnswerRecall@5 기준)을 그대로 재사용한다.
"""
import os

from query_decomposer import decompose_query
from query_planner import plan_query, USE_QUERY_PLANNER
from query_classifier import classify_intent, classify_question_type
from retrieval import DEFAULT_DENSE_MODEL, RoutedRetriever, route_search_chunks
from candidate_ranking import gate_low_relevance, rerank, top_k_cut
from citation import format_all_citations
from civil_petition import build_civil_petition_answer
from prompt_builder import (
    assemble_civil_petition_answer, assemble_informational_answer,
    build_civil_petition_prompt, build_informational_prompt,
)
from llm_client import call_hyperclova
from observability import current_trace_id, flush as flush_traces, observe
from performance import measure_time
from rag_logger import log_rag_run
# 아래 상수들은 지우지 않고 '문서화된 기본값'으로 남긴다 — 관리자 화면(AD-007)이 값을 바꿀 수
# 있지만, DB 에 값이 없으면 get_param 이 이 값을 그대로 쓴다. 각 상수 주석의 실측 근거가
# "왜 이 값인가"의 유일한 기록이라 DB 로 옮겼다고 지우면 안 된다(src/runtime_config.py 참고).
from runtime_config import get_param
from source_check import recheck_source_usage

K_CANDIDATES = 20
K_FINAL = 5

# 2026-07-23 팀 결정: 리랭커 기본 Off (project_context 9.7). 끈 직접 사유는 속도다 — 현 설정
# (bge-reranker-v2-m3, k=20, max_length=8192, CPU)에서 질문당 27~210초가 걸려 실서비스에 못 쓴다.
# ⚠️ 품질 효과는 결론난 게 아니다: 2026-07-23 6문항 측정은 Recall 개선 0·MRR 소폭↓였지만
# 2026-07-30 재측정에서는 개선으로 나와 방향이 엇갈렸고, 표본이 작아 어느 쪽도 못 쓴다.
# 판정은 GPU에서 held-out 전체로 다시 한다(조건표: 루트 README.md 2.4절, 상세: candidate_ranking.py).
# 코드는 남겨두고 여기서만 끈다 — 재도입 시 True. Off면 1차 검색 상위 K_FINAL을 그대로 사용.
USE_RERANKER = False

# 2026-08-09: 멀티쿼리 분해와 intent 분류를 gpt-5.6-luna structured output '한 콜'로 함께
# 처리하는 쿼리 플래너(query_planner.plan_query)로 전환했다. 스위치는 query_planner.USE_QUERY_PLANNER
# (여기로 import). True면 plan_query가 {should_split, items:[{question, intent}]}를 한 번에 주고,
# 하위 질문별 intent가 여기서 바로 나오므로 _answer_one이 별도 classify_intent를 안 부른다.
# 채택 근거(docs/query_planner_model_comparison.md, 100문항 joint 벤치마크): gpt-5.6-luna가 joint
# 정확도 89%·intent macroF1 0.946·false split 0%로 최고. 현행(HCX 분해 + luna intent, 질문당
# 2.6콜) 대비 joint 79→89%, 질문당 토큰 2,007→539(-73%), 호출 2.6→1.
# USE_QUERY_PLANNER=False면 아래 기존 분리 방식(decompose_query + classify_intent)으로 폴백한다.
#
# 2026-07-30(폴백 경로): query_decomposer.decompose_query()로 복합 질문(예: "신청 방법과 필요한
# 서류, 처리 기간을 알려주세요")을 감지해 하위 질문별로 따로 검색·답변한다(log/0729.md 3항).
# 판단 자체가 매 질문마다 HyperCLOVA 호출 1회를 추가한다(단일 질문이어도 "쪼갤지 말지"를
# 판단해야 하므로 피할 수 없는 비용). USE_QUERY_PLANNER가 False일 때만 이 경로를 쓰며,
# 그때 USE_QUERY_DECOMPOSITION로 분해 자체를 켜고 끈다(둘 다 off면 원문 그대로 단일 처리).
USE_QUERY_DECOMPOSITION = True

# 2026-08-03: 마커가 [NO_SOURCE]로 판정한 답변만 source_check.recheck_source_usage()로 한 번
# 더 확인한다(근거를 실제로 썼다고 나오면 출처를 붙인다). 자기보고 마커는 근거를 쓴 답변
# 61건 중 33건(54%)에서 출처를 잃었고, 그 오판이 전부 [NO_SOURCE] 쪽에만 몰려 있었다
# ([SOURCE_USED] 28건은 오판 0건 — docs/pipeline_issue_history.md 이슈 5). 프롬프트로 마커 정확도를
# 올리는 길은 이미 35회 통제 실험으로 막혔으므로, 프롬프트가 아니라 판정 시점을 생성과
# 분리하는 쪽으로 잡았다. 대가는 [NO_SOURCE] 답변당 LLM 호출 1회 추가다(정상 답변엔 없음).
# 끄려면 False — 그러면 마커 판정만 쓰던 이전 동작으로 정확히 돌아간다.
USE_SOURCE_RECHECK = True


@observe()
def _answer_one(query, timings, intent=None):
    """질문 하나(원본 질문 또는 복합 질문의 하위 질문 하나)에 대해 검색부터 답변 조립까지
    수행한다. 하위 답변끼리는 출처를 포함해 완전히 독립이다 — 하위 답변 간 "중복 출처
    제거"를 하던 누적 집합(seen_pages/seen_urls)은 2026-07-30 제거했다. 출처를 실제로
    붙였는지가 아니라 검색됐는지 기준으로 걸러서, 앞 하위 답변이 [NO_SOURCE]로 거절한
    경우 뒤 하위 답변의 진짜 출처까지 지우는 버그가 있었다(docs/pipeline_issue_history.md 이슈 4).
    같은 문서가 여러 하위 답변의 근거면 각각에 보이는 게 맞다 — 다시 도입하지 말 것.

    intent: 쿼리 플래너(plan_query)가 이미 판단한 하위 질문 intent를 넘기면 그대로 쓴다.
    None이면(USE_QUERY_PLANNER=False 폴백 경로) 여기서 classify_intent로 분류한다."""
    if intent is None:
        with measure_time(timings, "query_classification", accumulate=True):
            intent = classify_intent(query)

    # 아래 파라미터들은 관리자 화면(AD-007)이 바꿀 수 있다. get_param 은 DB 에 값이 없으면
    # 두 번째 인자(이 모듈의 전역 = 문서화된 기본값)를 그대로 돌려주므로, DB 가 비어 있으면
    # 동작이 오늘과 완전히 같다. 모듈 최상단이 아니라 **쓰는 자리에서** 부르는 것이 중요하다 —
    # 위에서 한 번 읽어 두면 값이 import 시점에 굳어 재시작 전까지 반영되지 않는다.
    with measure_time(timings, "retrieval", accumulate=True):
        candidates = route_search_chunks(query, k=get_param("k_candidates", K_CANDIDATES))

    with measure_time(timings, "reranking", accumulate=True):
        # 전역 USE_RERANKER 를 default 로 넘기는 이유: eval_pipeline_generation.py 가
        # `pipeline.USE_RERANKER = args.rerank` 로 전역을 덮어써 A/B 를 돌린다. DB 에 이
        # 파라미터가 없는 동안은 그 덮어쓰기가 계속 이긴다(runtime_config 모듈 주석 참고).
        reranked = rerank(query, candidates) if get_param("use_reranker", USE_RERANKER) else candidates
        # 무관 질문 게이트(2026-08-10) — api/rag/answer.py 와 동일 동작 유지.
        # 게이트에 걸리면 근거 없이 informational 경로로 통일한다(civil 조립은 근거가 있어야
        # 의미가 있고, 빈 근거 civil 프롬프트는 few-shot leak 이력이 있다).
        top = gate_low_relevance(top_k_cut(reranked, k=get_param("k_final", K_FINAL)))
        if not top:
            intent = "informational"

    with measure_time(timings, "context_building", accumulate=True):
        if intent == "civil_petition":
            civil_petition_answer = build_civil_petition_answer(top)
        else:
            citations = format_all_citations([cid for cid, _, _ in top])

    with measure_time(timings, "prompt_building", accumulate=True):
        if intent == "civil_petition":
            prompt = build_civil_petition_prompt(query, civil_petition_answer)
        else:
            prompt = build_informational_prompt(query, top)

    with measure_time(timings, "llm_call", accumulate=True):
        llm_text = call_hyperclova(prompt)

    # URL은 LLM에게 안 맡긴다 - 실제 서류/페이지/출처 링크는 civil_petition.py/
    # citation.py가 이미 조회해둔 값을 여기서 결정론적으로 그대로 붙인다.
    # 출처를 "붙일지 말지"는 LLM 자기보고 마커([SOURCE_USED]/[NO_SOURCE])로 판단한다 —
    # prompt_builder가 답변 첫 줄에서 마커를 떼며 함께 판정한다. source_verifier(코드 판정)
    # 로 옮겼다가 2026-08-03 이 자기보고 방식으로 되돌렸다.
    # 다만 마커가 [NO_SOURCE]라고 한 경우에만(USE_SOURCE_RECHECK) 생성과 분리된 별도 호출로
    # 한 번 더 확인한다 — 근거를 재확인할 때 생성 때와 "같은 자료"를 넘겨야 판정이 성립하므로,
    # informational은 근거 청크 본문을, civil_petition은 절차 안내 근거를 그대로 넘긴다.
    with measure_time(timings, "answer_assembly", accumulate=True):
        if intent == "civil_petition":
            evidence = civil_petition_answer["procedure"]
        else:
            evidence = "\n\n".join(text for _, _, text in top)
        recheck = ((lambda body: recheck_source_usage(body, evidence))
                   if get_param("use_source_recheck", USE_SOURCE_RECHECK) else None)

        if intent == "civil_petition":
            answer = assemble_civil_petition_answer(
                llm_text, civil_petition_answer, recheck=recheck)
        else:
            answer = assemble_informational_answer(llm_text, citations, recheck=recheck)

    return answer


def _rag_answer_traced(query):
    """rag_answer()와 흐름은 동일하되, 단계별 소요 시간을 timings 딕셔너리에 함께 기록해
    (답변, timings, log_intent) 튜플로 반환한다. 성능 측정 스크립트 전용 — 서비스
    경로(rag_answer)는 이 함수를 감싸 답변 문자열을 꺼내 쓰고, log_intent를 로깅에 재사용한다.

    log_intent: 플래너 경로에선 대표 intent(첫 하위 질문의 것)를 담아 rag_answer가 추가
    호출 없이 그대로 로깅하게 한다. 폴백 경로에선 None을 담고, rag_answer가 필요 시 별도로
    classify_intent를 부른다(= 이 기능 도입 전과 동일 동작)."""
    timings = {}

    if get_param("use_query_planner", USE_QUERY_PLANNER):
        # 멀티쿼리 분해 + intent를 한 콜(structured output)로 함께 판단한다.
        with measure_time(timings, "query_planning"):
            plan = plan_query(query)
        items = plan["items"]
        log_intent = items[0]["intent"] if items else "informational"

        if not (plan["should_split"] and len(items) > 1):
            # 단일 질문 - 플래너가 하위 질문을 살짝 바꿔 썼어도 원본 질문 그대로 검색하고
            # (기존 설계 유지: 재질문판 문구로 검색하지 않는다), intent만 플래너 결과를 쓴다.
            answer = _answer_one(query, timings, intent=(items[0]["intent"] if items else None))
        else:
            sub_answers = [_answer_one(it["question"], timings, intent=it["intent"]) for it in items]
            answer = "\n\n".join(f"**{it['question']}**\n{a}"
                                 for it, a in zip(items, sub_answers))
    else:
        # 폴백: 기존 분리 방식(HCX 분해 + 하위 질문별 classify_intent).
        if get_param("use_query_decomposition", USE_QUERY_DECOMPOSITION):
            with measure_time(timings, "decomposition"):
                sub_queries = decompose_query(query)
        else:
            sub_queries = [query]

        if len(sub_queries) <= 1:
            answer = _answer_one(query, timings)
        else:
            sub_answers = [_answer_one(q, timings) for q in sub_queries]
            answer = "\n\n".join(f"**{q}**\n{a}" for q, a in zip(sub_queries, sub_answers))
        log_intent = None

    timings["total"] = round(sum(timings.values()), 4)
    return answer, timings, log_intent


@observe()
def rag_answer(query):
    """질문 하나 -> 답변 문자열. intent(informational/civil_petition)에 따라
    근거 조립·프롬프트 조립 방식만 갈리고, 검색·재정렬·LLM호출은 공통이다.

    Streamlit(app.py)·터미널(본 파일 __main__)이 실제로 부르는 유일한 경로라, 여기서만
    rag_runs에 실행 결과를 로깅한다 — eval_pipeline_generation.py 등 평가 스크립트는
    _rag_answer_traced()를 직접 불러 이 로깅을 우회한다(의도적). 검색 후보/선택 상세
    (rag_retrieval_results)는 로깅하지 않는다 — 질문당 20행씩 쌓여 부담이고, 추후 Langfuse로
    trace를 붙이면 그쪽이 이 역할을 전담한다(2026-08-04 팀 결정).
    로깅은 log_rag_run 내부에서 전부 실패-안전(예외를 삼킴)이라 여기서 답변을 막지 않는다."""
    answer, timings, log_intent = _rag_answer_traced(query)

    # 로깅용 intent: 플래너 경로는 이미 판단한 대표 intent를 재사용해 추가 호출을 안 한다
    # (쿼리 플래너의 '한 콜' 이점 유지). 폴백 경로(log_intent None)에서만 별도로 분류한다.
    intent = log_intent if log_intent is not None else classify_intent(query)
    qtype = classify_question_type(query)
    route = "hybrid" if qtype in RoutedRetriever.HYBRID_ONLY_TYPES else "dense"
    log_rag_run(
        question=query, answer=answer, intent=intent, question_type=qtype,
        retrieval_route=route, total_latency_ms=timings["total"] * 1000,
        embedding_model=DEFAULT_DENSE_MODEL, llm_model=os.environ.get("CLOVA_MODEL"),
        trace_id=current_trace_id(),
    )

    return answer


if __name__ == "__main__":
    print("KDIC 챗봇 (종료: exit 또는 quit)")
    while True:
        query = input("\n질문: ").strip()
        if query.lower() in ("exit", "quit"):
            break
        if not query:
            continue
        print(f"답변: {rag_answer(query)}")
    flush_traces()  # CLI는 곧 종료되므로 버퍼에 남은 trace를 지금 보낸다(서버 경로는 불필요)
