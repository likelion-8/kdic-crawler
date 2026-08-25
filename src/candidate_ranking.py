"""검색 후보 순위정리(candidate ranking) — 1차 검색 후보를 최종 상위 k로 좁힌다.

기본 경로는 1차 검색(retrieval.route_search_chunks) 순위 그대로 상위 k를 자르는 것(top_k_cut).
cross-encoder 재정렬(rerank)은 그 앞에 끼울 수 있는 선택 단계로 이 파일에 함께 두되 현재는
비활성이다(아래). 그래서 파일명을 reranker→candidate_ranking으로 바꿔 실제 역할(후보 선별,
재정렬은 옵션)을 반영한다.

── 리랭킹(rerank) 현재 상태: 비활성 (pipeline.py의 USE_RERANKER=False, 2026-07-23) ──
세 가지를 나눠서 읽을 것. 섞으면 "품질까지 결론났다"로 잘못 읽힌다.

  운영값       Off — 확정.
  CPU 실용성   부적합 — 확정. 현 설정(k=20, max_length=8192, CPU)에서 질문당 27~210초가
               걸렸고, 2026-07-30 재측정에서도 문항당 약 96초였다. 실서비스에 못 쓴다.
  품질 효과    판정 보류 — 확정 아님. 2026-07-23 6문항 측정은 Recall@5 개선 0·MRR
               0.71→0.64(하락)였는데, 2026-07-30 재측정에서는 검색 품질이 개선되는 것으로
               나와 방향이 엇갈렸다. 표본이 작아 어느 쪽도 결론으로 쓸 수 없다.

즉 지금 Off인 직접 사유는 "품질에 도움이 안 돼서"가 아니라 "CPU에서 속도를 감당할 수 없어서"다.
품질 효용은 GPU 환경에서 held-out 세트 전체로 다시 판정한다(비교 조건표는 저장소 루트
README.md 2.4절). 그때까지 코드는 보존한다 — 재도입은 USE_RERANKER를 True로 바꾸면 된다.
top_k_cut()은 리랭크 여부와 무관하게 최종 상위 k를 자를 때 계속 쓰인다.
────────────────────────────────────────────────────────────────────────────────

bi-encoder(retrieval.py의 Dense/BM25)는 질문·문서를 따로 인코딩해 코사인 유사도·단어
통계로 비교하지만, cross-encoder는 질문+문서를 한 쌍으로 모델에 같이 넣어 관련도 점수를
직접 뽑는다 — 더 정교하지만 후보 하나하나 모델을 다시 돌려야 해서(문서 임베딩처럼 미리
계산해둘 수 없음) 전체 색인엔 못 쓰고, retrieval.route_search_chunks로 1차로 좁혀둔
소수 후보만 재정렬하는 2단계 구조로 쓴다.

모델은 bge-reranker-v2-m3(8192토큰 지원) — 이 코퍼스 최대 토큰 길이(청크 5,502·
통짜페이지 1,667)를 커버해 리랭킹 단계에서 잘림이 없다(bge-m3 계열 임베딩 때와 동일 이유).

재도입 시 권장 사용: route_search_chunks(query, k=20)로 1차 후보를 뽑고(Recall@20 실측 99%+),
rerank()로 재정렬한 뒤 top_k_cut(..., k=5)로 최종 5개만 남긴다(기존 프로젝트 전체
평가 기준인 AnswerRecall@5와 동일한 k).
현재(USE_RERANKER=False)는 가운데 rerank() 없이 route_search_chunks → top_k_cut 두 단계다.
"""
from observability import observe

RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
_reranker = {}


def _get_reranker():
    if "model" not in _reranker:
        from sentence_transformers import CrossEncoder
        _reranker["model"] = CrossEncoder(RERANK_MODEL, max_length=8192, device="cpu")
    return _reranker["model"]


@observe()
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


# 무관 질문 게이트 임계값. 이 점수는 dense 코사인 **원값**이다(PgVector 1-cosine_distance,
# 임베딩이 L2 정규화라 그대로 코사인). BM25 안 섞이고 재정규화도 없다 — 절대 스케일이라
# 모델·색인이 바뀌면 값 자체가 이동한다.
#
# 2026-08-25 재측정으로 0.35 유지 확정(상세·표 전부: docs/min_top1_threshold_decision.md).
# 최초 결정(2026-08-10)의 근거였던 "인스코프 137 최소 0.378 / 잡담 5 최대 0.362"는 폐기했다 —
# 08-18 프리픽스 색인으로 분포가 +0.09가량 이동했고, 08-19 Gate 1·2가 검색 앞에 생겨 그때
# 근거로 쓴 잡담은 여기까지 오지도 않는다.
#
# 재측정 요약(평가셋 인스코프 223 / 무관 75, DB 색인 08-18, 리랭커·유형라우팅 off):
#   - 전 풀 기준 분리 불가(인스코프 최소 0.332 < 무관 최대 0.443). 어떤 값이든 거래다.
#   - 0.35: 무관 제거 11/13(84.6%), 인스코프 손실 1건. 실트래픽 259건 중 오차단 1건(0.4%).
#   - 0.45↑는 검색이 맞은 인스코프 2건(0.405·0.422)을 잃어 불가. 진짜 첫 손실이 0.405다.
#   - 0.40도 가능하나 그 마진이 0.005뿐이고 얻는 건 "asdf1234" 1건이라 미채택.
#   - 0.30~0.33은 무관 제거가 61.5%로 떨어지고 되찾는 1건은 top-1이 이미 엉뚱한 주제다.
# 도메인 인접 범위외는 점수로 안 갈린다(생존 무관 48건 중 35건이 인접, 0.35에서 2.9%만 제거)
# — 이 게이트가 아니라 Gate 2와 source_check 사후 판정이 맡는다. 올려서 해결하려 하지 말 것.
#
# ⚠️ 리랭커를 켜면(pipeline.USE_RERANKER) 게이트가 보는 점수가 cross-encoder 로짓이 되어 이
#    값이 무의미해진다. 유형 라우팅을 켜면 linear_fuse 의 질의별 min-max 정규화 탓에 top-1 이
#    항상 0.6~1.0 이라 게이트가 아예 발동하지 않는다. 둘 다 재측정 전제 조건이다.
MIN_TOP1_SCORE = 0.35


def gate_low_relevance(top, threshold=None):
    """top-1 점수가 임계값 미만이면 근거를 통째로 비운다(무관 질문이 저점수 청크를 근거로
    받아 환각하는 것을 차단). 빈 근거를 받은 프롬프트는 인사·잡담 응대/범위외 거절로
    유도된다(prompt_builder.NO_EVIDENCE_NOTICE).

    threshold 를 기본 인자에 박지 않고 None 으로 두는 이유: 기본 인자는 **import 시점에 한 번**
    평가된다. MIN_TOP1_SCORE 를 그대로 쓰면 관리자 화면(AD-007)이 값을 바꿔도 프로세스를
    재시작하기 전까지 반영되지 않는다. 호출 시점에 풀어야 한다."""
    if threshold is None:
        from runtime_config import get_param
        threshold = get_param("min_top1_score", MIN_TOP1_SCORE)
    if top and top[0][1] < threshold:
        return []
    return top
