"""검색 후보 순위정리(candidate ranking) — 1차 검색 후보를 최종 상위 k로 좁힌다.

기본 경로는 1차 검색(retrieval.route_search_chunks) 순위 그대로 상위 k를 자르는 것(top_k_cut).
cross-encoder 재정렬(rerank)은 그 앞에 끼울 수 있는 선택 단계로 이 파일에 함께 두되 현재는
비활성이다(아래). 그래서 파일명을 reranker→candidate_ranking으로 바꿔 실제 역할(후보 선별,
재정렬은 옵션)을 반영한다.

── 리랭킹(rerank) 현재 상태: 비활성 (pipeline.py의 USE_RERANKER=False, 2026-08-24 GPU 재측정 후에도 유지) ──

2026-08-24 GPU(L4) 환경에서 held-out 세트(testset_pipeline.jsonl, 79문항)로 Off·BAAI/bge-reranker-v2-m3·
dragonkue/bge-reranker-v2-m3-ko 세 조건 실측(결과: results/pipeline_holdout/retrieval_rerank_*.json).

  Recall@5(=K_FINAL, 운영 최종 컨텍스트 크기와 동일 지표)   Off 0.956 · BAAI 0.945(↓) · dragonkue 0.956(동률)
  Recall@1 / MRR                                          Off 0.650/0.857 · dragonkue 0.793/0.946(↑ 크게 개선)
  속도(79문항 전체)                                        Off 427s · BAAI 1595s · dragonkue 1611s
                                                           (문항당 +8~9초 — CPU 때 27~210초보단 개선됐지만 여전히 부담)

Recall@1·MRR은 dragonkue가 크게 낫지만, 운영이 실제로 쓰는 K_FINAL=5 기준 지표(Recall@5)는 리랭킹을
켜도 그대로거나 더 나쁨 — 즉 리랭커는 top-5 "안에서의 순서"만 바꿀 뿐 top-5에 못 들던 정답을 새로
끌어오지 못한다. 문항당 +8~9초 비용 대비 K_FINAL=5 기준 실질 이득이 없어 Off 유지가 맞다는 결론.

부수 발견(버그): gate_low_relevance의 MIN_TOP1_SCORE=0.35는 bi-encoder 점수 기준 튜닝값인데, 리랭킹을
켜면 이 게이트가 리랭커가 새로 매긴 점수에 그대로 적용된다. dragonkue는 원점수 스케일이 훨씬 낮아서
(예: 질문 "예금자 한 명이 한 금융회사에서 보호받을 수 있는 한도는 얼마인가요?"에서 정답 페이지가 1위인데
점수 0.0985 < 0.35) 정답을 올바르게 찾고도 게이트가 근거를 통째로 삭제하는 경우가 다수 발생(context_hit
실패 22건 중 18건이 이 패턴). 리랭커를 향후 재도입할 경우 MIN_TOP1_SCORE를 그 모델의 점수 분포로
반드시 재보정해야 한다 — 안 그러면 어떤 리랭커를 붙이든 이 문제가 조용히 정답률을 깎는다.

RERANK_MODEL은 재도입 시 후보 우선순위를 위해 dragonkue/bge-reranker-v2-m3-ko로 바꿔뒀다(순수 랭킹
품질은 이쪽이 더 좋음). top_k_cut()은 리랭크 여부와 무관하게 최종 상위 k를 자를 때 계속 쓰인다.
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

RERANK_MODEL = "dragonkue/bge-reranker-v2-m3-ko"
_reranker = {}


def _get_reranker():
    if "model" not in _reranker:
        import torch
        from sentence_transformers import CrossEncoder
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _reranker["model"] = CrossEncoder(RERANK_MODEL, max_length=8192, device=device)
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
    재시작하기 전까지 반영되지 않는다. 호출 시점에 풀어야 한다.

    ⚠️ 2026-08-25(Gate3 도입): 이 함수 자체는 더는 웹·CLI 답변 경로에서 호출되지 않는다
    (아래 gate3_exit 로 대체 — HCX/OpenAI 호출 전에 원본 Dense 점수로 조기 종료한다). 기존
    호출부·테스트가 남아 있을 수 있어 삭제하지 않고 그대로 둔다."""
    if threshold is None:
        from runtime_config import get_param
        threshold = get_param("min_top1_score", MIN_TOP1_SCORE)
    if top and top[0][1] < threshold:
        return []
    return top


def gate3_exit(candidates, threshold=None) -> bool:
    """Gate3 판정 — candidates(route_search_chunks 가 돌려준 **원본** 1차 후보, rerank 전)의
    top-1 점수가 threshold **이하**이거나 candidates 가 비면 True(EXIT).

    ⚠️ 반드시 rerank() 호출 **전**의 candidates 에 대해서만 판정할 것. rerank()는 점수를
    cross-encoder 로짓으로 덮어써 스케일이 달라지므로(MIN_TOP1_SCORE 는 dense 코사인
    원값 기준), 재정렬된 리스트에 이 임계값을 적용하면 의미가 없다.

    ⚠️ use_type_routing(admin 파라미터)이 켜져 있으면 candidates 가 Hybrid/RRF/linear-fusion
    점수일 수 있다(retrieval.route_search_chunks 참고) — 이 경우 호출부가 아예 이 함수를
    부르지 말고 Gate3 를 건너뛰어야 한다(MIN_TOP1_SCORE 는 dense 전용 임계값).

    gate_low_relevance 와 비교연산자가 다르다(`<=` vs `<`) — 요구사항이 "0.35 이하"로 명시돼
    경계값(정확히 threshold)도 EXIT 로 판정한다."""
    if threshold is None:
        from runtime_config import get_param
        threshold = get_param("min_top1_score", MIN_TOP1_SCORE)
    if not candidates:
        return True
    return candidates[0][1] <= threshold
