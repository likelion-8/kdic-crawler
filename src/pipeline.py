"""전체 흐름 조립 — 질문 하나를 받아 분해(복합 질문이면)→분류→검색→재정렬→근거조립→
프롬프트→LLM호출까지 이어붙인 최종 진입점. 각 단계는 이미 만들어진 모듈을 그대로 호출만
한다(새 로직 없음).

K_CANDIDATES=20/K_FINAL=5는 candidate_ranking.py의 리랭킹 실측값(Recall@20 99%+, 기존 프로젝트
AnswerRecall@5 기준)을 그대로 재사용한다.
"""
import os

from query_decomposer import decompose_query
from query_classifier import classify_intent, classify_question_type
from retrieval import DEFAULT_DENSE_MODEL, RoutedRetriever, route_search_chunks
from candidate_ranking import rerank, top_k_cut
from citation import format_all_citations
from civil_petition import build_civil_petition_answer
from prompt_builder import (
    assemble_civil_petition_answer, assemble_informational_answer,
    build_civil_petition_prompt, build_informational_prompt,
)
from llm_client import call_hyperclova
from performance import measure_time
from rag_logger import log_rag_run
from source_check import recheck_source_usage

K_CANDIDATES = 20
K_FINAL = 5

# 2026-07-23 팀 결정: 리랭커 기본 Off (project_context 9.7). 현 설정(bge-reranker-v2-m3,
# k=20, max_length=8192, CPU)에서 이득 없이(Recall 개선 0, MRR 소폭↓) 속도만 크게 악화
# (질문당 27~210초). 코드는 남겨두고 여기서만 끈다 — 재도입 시 True로 바꾸면 됨(GPU/경량 설정
# 재검증 후). Off면 1차 검색(route_search_chunks) 상위 K_FINAL을 그대로 사용.
USE_RERANKER = False

# 2026-07-30: query_decomposer.decompose_query()로 복합 질문(예: "신청 방법과 필요한 서류,
# 처리 기간을 알려주세요")을 감지해 하위 질문별로 따로 검색·답변한다(log/0729.md 3항).
# 판단 자체가 매 질문마다 HyperCLOVA 호출 1회를 추가한다(단일 질문이어도 "쪼갤지 말지"를
# 판단해야 하므로 피할 수 없는 비용) — 38문항 hard-tier 검증(eval_query_decomposition.py)
# 기준 오분해 0%대·과소분해 ~5%까지 잡았지만, temperature=0.2(llm_client.py, 전체 파이프라인
# 공유)에 따른 근본적 비결정성 때문에 10~20%대 잔여 흔들림은 프롬프트만으로는 못 없앴다.
# 최악의 경우도 "원래 단일 질문을 비슷한 재질문 2개로 나눠 검색"하는 정도라 답 품질이
# 완전히 틀어지진 않는다고 판단해 기본 On으로 둔다. E2E(Recall/환각률/응답시간) 재검증 후
# 이 판단이 틀렸다면 USE_RERANKER처럼 여기서 끄면 된다.
USE_QUERY_DECOMPOSITION = True

# 2026-08-03: 마커가 [NO_SOURCE]로 판정한 답변만 source_check.recheck_source_usage()로 한 번
# 더 확인한다(근거를 실제로 썼다고 나오면 출처를 붙인다). 자기보고 마커는 근거를 쓴 답변
# 61건 중 33건(54%)에서 출처를 잃었고, 그 오판이 전부 [NO_SOURCE] 쪽에만 몰려 있었다
# ([SOURCE_USED] 28건은 오판 0건 — docs/pipeline_issues.md 이슈 5). 프롬프트로 마커 정확도를
# 올리는 길은 이미 35회 통제 실험으로 막혔으므로, 프롬프트가 아니라 판정 시점을 생성과
# 분리하는 쪽으로 잡았다. 대가는 [NO_SOURCE] 답변당 LLM 호출 1회 추가다(정상 답변엔 없음).
# 끄려면 False — 그러면 마커 판정만 쓰던 이전 동작으로 정확히 돌아간다.
USE_SOURCE_RECHECK = True


def _answer_one(query, timings, collect=None):
    """질문 하나(원본 질문 또는 복합 질문의 하위 질문 하나)에 대해 검색부터 답변 조립까지
    수행한다. 하위 답변끼리는 출처를 포함해 완전히 독립이다 — 하위 답변 간 "중복 출처
    제거"를 하던 누적 집합(seen_pages/seen_urls)은 2026-07-30 제거했다. 출처를 실제로
    붙였는지가 아니라 검색됐는지 기준으로 걸러서, 앞 하위 답변이 [NO_SOURCE]로 거절한
    경우 뒤 하위 답변의 진짜 출처까지 지우는 버그가 있었다(docs/pipeline_issues.md 이슈 4).
    같은 문서가 여러 하위 답변의 근거면 각각에 보이는 게 맞다 — 다시 도입하지 말 것.

    collect가 리스트면 (query, candidates, top)을 append한다 — rag_logger가 검색 후보/
    최종선택을 로깅할 때만 쓰고, 기본(None)이면 기존 동작과 완전히 동일하다."""
    with measure_time(timings, "query_classification", accumulate=True):
        intent = classify_intent(query)

    with measure_time(timings, "retrieval", accumulate=True):
        candidates = route_search_chunks(query, k=K_CANDIDATES)

    with measure_time(timings, "reranking", accumulate=True):
        reranked = rerank(query, candidates) if USE_RERANKER else candidates
        top = top_k_cut(reranked, k=K_FINAL)

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
        recheck = (lambda body: recheck_source_usage(body, evidence)) if USE_SOURCE_RECHECK else None

        if intent == "civil_petition":
            answer = assemble_civil_petition_answer(
                llm_text, civil_petition_answer, recheck=recheck)
        else:
            answer = assemble_informational_answer(llm_text, citations, recheck=recheck)

    if collect is not None:
        collect.append((query, candidates, top))

    return answer


def _rag_answer_traced(query, collect_retrieval=None):
    """rag_answer()와 흐름은 동일하되, 단계별 소요 시간을 timings 딕셔너리에 함께
    기록해 (답변, timings) 튜플로 반환한다. 성능 측정 스크립트 전용 — 서비스
    경로(rag_answer)는 이 함수를 감싸 답변 문자열만 꺼내 쓴다.

    collect_retrieval이 리스트면 하위 질문별 (query, candidates, top)이 쌓인다(로깅용).
    eval_pipeline_generation.py/measure_baseline.py는 이 인자를 안 넘기므로(기본 None)
    기존 호출과 동작이 완전히 같다 — 평가·성능측정 실행은 로깅 대상이 아니다."""
    timings = {}

    if USE_QUERY_DECOMPOSITION:
        with measure_time(timings, "decomposition"):
            sub_queries = decompose_query(query)
    else:
        sub_queries = [query]

    if len(sub_queries) <= 1:
        # 단일 질문(또는 기능 Off) - 분해기가 살짝 바꿔 쓴 표현(예: "이란"->"이라는 게")이
        # 아니라 원본 질문 그대로 검색한다. 분해가 실제로 아무것도 바꾸지 않아야 할 상황에서
        # 굳이 재질문판 문구를 쓸 이유가 없다(안전한 기본 동작 유지).
        answer = _answer_one(query, timings, collect=collect_retrieval)
    else:
        sub_answers = [_answer_one(q, timings, collect=collect_retrieval) for q in sub_queries]
        answer = "\n\n".join(f"**{q}**\n{a}" for q, a in zip(sub_queries, sub_answers))

    timings["total"] = round(sum(timings.values()), 4)
    return answer, timings


def rag_answer(query):
    """질문 하나 -> 답변 문자열. intent(informational/civil_petition)에 따라
    근거 조립·프롬프트 조립 방식만 갈리고, 검색·재정렬·LLM호출은 공통이다.

    Streamlit(app.py)·터미널(본 파일 __main__)이 실제로 부르는 유일한 경로라, 여기서만
    rag_runs/rag_retrieval_results에 실행 결과를 로깅한다 — eval_pipeline_generation.py 등
    평가 스크립트는 _rag_answer_traced()를 직접 불러 이 로깅을 우회한다(의도적).
    로깅은 log_rag_run 내부에서 전부 실패-안전(예외를 삼킴)이라 여기서 답변을 막지 않는다."""
    sub_results = []
    answer, timings = _rag_answer_traced(query, collect_retrieval=sub_results)

    intent = classify_intent(query)
    qtype = classify_question_type(query)
    route = "hybrid" if qtype in RoutedRetriever.HYBRID_ONLY_TYPES else "dense"
    log_rag_run(
        question=query, answer=answer, intent=intent, question_type=qtype,
        retrieval_route=route, total_latency_ms=timings["total"] * 1000,
        sub_results=sub_results, embedding_model=DEFAULT_DENSE_MODEL,
        llm_model=os.environ.get("CLOVA_MODEL"),
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
