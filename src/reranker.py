"""후보 재정렬(reranking) — cross-encoder로 (질문, 청크) 쌍을 직접 비교해 재정렬.

bi-encoder(retrieval.py의 Dense/BM25)는 질문·문서를 따로 인코딩해 코사인 유사도·단어
통계로 비교하지만, cross-encoder는 질문+문서를 한 쌍으로 모델에 같이 넣어 관련도 점수를
직접 뽑는다 — 더 정교하지만 후보 하나하나 모델을 다시 돌려야 해서(문서 임베딩처럼 미리
계산해둘 수 없음) 전체 색인엔 못 쓰고, retrieval.route_search_chunks로 1차로 좁혀둔
소수 후보만 재정렬하는 2단계 구조로 쓴다.

모델은 bge-reranker-v2-m3(8192토큰 지원) — 이 코퍼스 최대 토큰 길이(청크 5,502·
통짜페이지 1,667)를 커버해 리랭킹 단계에서 잘림이 없다(bge-m3 계열 임베딩 때와 동일 이유).

권장 사용: route_search_chunks(query, k=20)로 1차 후보를 뽑고(Recall@20 실측 99%+),
rerank()로 재정렬한 뒤 top_k_cut(..., k=5)로 최종 5개만 남긴다(기존 프로젝트 전체
평가 기준인 AnswerRecall@5와 동일한 k).
"""
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
_reranker = {}


def _get_reranker():
    if "model" not in _reranker:
        from sentence_transformers import CrossEncoder
        _reranker["model"] = CrossEncoder(RERANK_MODEL, max_length=8192, device="cpu")
    return _reranker["model"]


def rerank(query, candidates):
    """candidates: [(chunk_id, score, text), ...] — retrieval.route_search_chunks() 등
    1차 검색이 내놓은 후보. 각 후보를 (질문, 텍스트) 쌍으로 cross-encoder에 넣어 관련도
    점수를 다시 매기고, 그 점수 기준 내림차순으로 재정렬해 [(chunk_id, score, text), ...]를
    반환한다. score는 1차 검색 점수를 덮어쓴 재정렬 점수다."""
    if not candidates:
        return []
    model = _get_reranker()
    pairs = [(query, text) for _, _, text in candidates]
    scores = model.predict(pairs)
    reranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    return [(cid, float(score), text) for (cid, _old_score, text), score in reranked]


def top_k_cut(reranked, k):
    """재정렬된 후보 리스트에서 상위 k개만 자른다."""
    return reranked[:k]
