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

K_CANDIDATES = 20
K_FINAL = 5


def rag_answer(query):
    """질문 하나 -> 답변 문자열. intent(informational/civil_petition)에 따라
    근거 조립·프롬프트 조립 방식만 갈리고, 검색·재정렬·LLM호출은 공통이다."""
    intent = classify_intent(query)

    candidates = route_search_chunks(query, k=K_CANDIDATES)
    reranked = rerank(query, candidates)
    top = top_k_cut(reranked, k=K_FINAL)

    if intent == "civil_petition":
        civil_petition_answer = build_civil_petition_answer(top)
        prompt = build_civil_petition_prompt(query, civil_petition_answer)
    else:
        citations = format_all_citations([cid for cid, _, _ in top])
        prompt = build_informational_prompt(query, top, citations)

    return call_hyperclova(prompt)


if __name__ == "__main__":
    print("KDIC 챗봇 (종료: exit 또는 quit)")
    while True:
        query = input("\n질문: ").strip()
        if query.lower() in ("exit", "quit"):
            break
        if not query:
            continue
        print(f"답변: {rag_answer(query)}")
