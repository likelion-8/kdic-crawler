"""전체 흐름 조립 — 질문 하나를 받아 분류→검색→재정렬→근거조립→프롬프트→LLM호출까지
이어붙인 최종 진입점. 각 단계는 이미 만들어진 모듈을 그대로 호출만 한다(새 로직 없음).

K_CANDIDATES=20/K_FINAL=5는 reranker.py에서 실측한 값(Recall@20 99%+, 기존 프로젝트
AnswerRecall@5 기준)을 그대로 재사용한다.
"""
from query_classifier import classify_intent
from retrieval import route_search_chunks
from reranker import rerank, top_k_cut
from citation import format_all_citations
from civil_petition import build_civil_petition_answer
from prompt_builder import build_civil_petition_prompt, build_informational_prompt
from llm_client import call_hyperclova
from performance import measure_time

K_CANDIDATES = 20
K_FINAL = 5


def _rag_answer_traced(query):
    """rag_answer()와 흐름은 동일하되, 단계별 소요 시간을 timings 딕셔너리에 함께
    기록해 (답변, timings) 튜플로 반환한다. 성능 측정 스크립트 전용 — 서비스
    경로(rag_answer)는 이 함수를 감싸 답변 문자열만 꺼내 쓴다."""
    timings = {}

    with measure_time(timings, "query_classification"):
        intent = classify_intent(query)

    with measure_time(timings, "retrieval"):
        candidates = route_search_chunks(query, k=K_CANDIDATES)

    with measure_time(timings, "reranking"):
        reranked = rerank(query, candidates)
        top = top_k_cut(reranked, k=K_FINAL)

    with measure_time(timings, "context_building"):
        if intent == "civil_petition":
            civil_petition_answer = build_civil_petition_answer(top)
        else:
            citations = format_all_citations([cid for cid, _, _ in top])

    with measure_time(timings, "prompt_building"):
        if intent == "civil_petition":
            prompt = build_civil_petition_prompt(query, civil_petition_answer)
        else:
            prompt = build_informational_prompt(query, top, citations)

    with measure_time(timings, "llm_call"):
        answer = call_hyperclova(prompt)

    timings["total"] = round(sum(timings.values()), 4)
    return answer, timings


def rag_answer(query):
    """질문 하나 -> 답변 문자열. intent(informational/civil_petition)에 따라
    근거 조립·프롬프트 조립 방식만 갈리고, 검색·재정렬·LLM호출은 공통이다."""
    answer, _ = _rag_answer_traced(query)
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
