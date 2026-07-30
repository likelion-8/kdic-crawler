"""전체 흐름 조립 — 질문 하나를 받아 분해(복합 질문이면)→분류→검색→재정렬→근거조립→
프롬프트→LLM호출까지 이어붙인 최종 진입점. 각 단계는 이미 만들어진 모듈을 그대로 호출만
한다(새 로직 없음).

K_CANDIDATES=20/K_FINAL=5는 candidate_ranking.py의 리랭킹 실측값(Recall@20 99%+, 기존 프로젝트
AnswerRecall@5 기준)을 그대로 재사용한다.
"""
from query_decomposer import decompose_query
from query_classifier import classify_intent
from retrieval import route_search_chunks
from candidate_ranking import rerank, top_k_cut
from citation import format_all_citations
from civil_petition import build_civil_petition_answer
from prompt_builder import (
    assemble_civil_petition_answer, assemble_informational_answer,
    build_civil_petition_prompt, build_informational_prompt,
)
from source_verifier import used_source
from llm_client import call_hyperclova
from performance import measure_time

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


def _answer_one(query, timings):
    """질문 하나(원본 질문 또는 복합 질문의 하위 질문 하나)에 대해 검색부터 답변 조립까지
    수행한다. 하위 답변끼리는 출처를 포함해 완전히 독립이다 — 하위 답변 간 "중복 출처
    제거"를 하던 누적 집합(seen_pages/seen_urls)은 2026-07-30 제거했다. 출처를 실제로
    붙였는지가 아니라 검색됐는지 기준으로 걸러서, 앞 하위 답변이 [NO_SOURCE]로 거절한
    경우 뒤 하위 답변의 진짜 출처까지 지우는 버그가 있었다(docs/pipeline_issues.md 이슈 4).
    같은 문서가 여러 하위 답변의 근거면 각각에 보이는 게 맞다 — 다시 도입하지 말 것."""
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

    with measure_time(timings, "source_verification", accumulate=True):
        # 출처를 붙일지도 LLM에게 안 묻는다 - 답변이 근거를 실제로 썼는지를
        # source_verifier가 겹침 계산으로 판정한다(자기보고 마커 폐기 경위는 그 파일 주석).
        context = (civil_petition_answer["procedure"] if intent == "civil_petition"
                   else "\n\n".join(text for _, _, text in top))
        src_used = used_source(llm_text, context)

    # URL은 LLM에게 안 맡긴다 - 실제 서류/페이지/출처 링크는 civil_petition.py/
    # citation.py가 이미 조회해둔 값을 여기서 결정론적으로 그대로 붙인다.
    if intent == "civil_petition":
        answer = assemble_civil_petition_answer(llm_text, civil_petition_answer, src_used)
    else:
        answer = assemble_informational_answer(llm_text, citations, src_used)

    return answer


def _rag_answer_traced(query):
    """rag_answer()와 흐름은 동일하되, 단계별 소요 시간을 timings 딕셔너리에 함께
    기록해 (답변, timings) 튜플로 반환한다. 성능 측정 스크립트 전용 — 서비스
    경로(rag_answer)는 이 함수를 감싸 답변 문자열만 꺼내 쓴다."""
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
        answer = _answer_one(query, timings)
    else:
        sub_answers = [_answer_one(q, timings) for q in sub_queries]
        answer = "\n\n".join(f"**{q}**\n{a}" for q, a in zip(sub_queries, sub_answers))

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
