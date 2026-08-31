"""BM25+Dense+BF / Dense+BF "점수 직접결합" 실험 — RRF(순위)가 아니라 점수(코사인 유사도)를
그대로 섞는 방식이 business_function을 활용하는 데 더 정확하다는 판단을 실측으로 검증한다.

배경: RRF는 BM25와 Dense처럼 척도가 다른 점수를 섞을 때 "순위"로 우회하는 도구다. 근데
business_function 분류 점수와 Dense 코사인 유사도는 척도가 같아서(둘 다 코사인 유사도),
순위로 뭉개지 않고 점수 그대로 더하거나 곱해도 된다 — 오히려 "얼마나 확신하는지"(0.95 vs 0.31)
같은 정보가 순위 변환 과정에서 사라지지 않아 더 정확하다.

두 가지 결합 방식을 실험한다:
- dense+bf: 척도가 같으므로 RRF 없이 직접 가중합 (dense_score + λ·bf_score)
- bm25+dense+bf: bm25는 척도가 달라 dense와 RRF로 먼저 결합하고, 그 위에 bf를 가산점(곱)으로 얹음
  (rrf_score · (1 + λ·bf_score))

business_function 점수는 BusinessFunctionClassifier와 같은 1-NN 코사인 유사도 메커니즘을 쓰되,
leave-page-out으로 제외한다. 자기 자신만 빼는 leave-one-out으로는 부족한데, 같은 페이지에서
생성된 형제 질문들(페이지당 최대 14~15개)은 business_function이 100% 동일해서 자기 자신만
빼도 형제 질문이 최근접으로 잡혀 점수가 허위로 높아진다. 같은 gold page(expected_sources)에서
나온 질문 전체를 후보 풀에서 제외해야 진짜 일반화 성능을 잰다.

실행: python3 experiments/bf_score_fusion_eval.py
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent   # experiments/ -> 리포 루트
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "crawler"))

from chunking import build_units, load_records  # noqa: E402
from retrieval import (  # noqa: E402
    BM25Retriever, DEFAULT_DENSE_MODEL, PageRanked, QdrantDenseRetriever,
    _encode_query, _get_model, rrf,
)

TESTSET = ROOT / "data" / "testset" / "testset_all.jsonl"
QDRANT_PATH = str(ROOT / "data" / "qdrant_local")
QDRANT_COLLECTION = "kdic_chunks_all"
KS = [1, 3, 5, 10]
LAMBDAS = [0.1, 0.3, 0.5, 1.0]


def load_rows():
    rows = []
    with open(TESTSET, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d["expected_sources"]:  # out_of_scope 제외 - 분류기 참조셋과 동일 조건
                rows.append(d)
    return rows


def evaluate(per_question_ranked, golds, ks=KS):
    """per_question_ranked: 질문별 [(page_id, score), ...] 리스트(정렬 완료)."""
    recall = {k: 0.0 for k in ks}
    rr_sum = 0.0
    n = len(golds)
    for ranked, gold in zip(per_question_ranked, golds):
        pids = [pid for pid, _ in ranked]
        for k in ks:
            hits = sum(1 for pid in pids[:k] if pid in gold)
            recall[k] += hits / len(gold)
        rr = 0.0
        for rank, pid in enumerate(pids, 1):
            if pid in gold:
                rr = 1.0 / rank
                break
        rr_sum += rr
    return {f"Recall@{k}": round(recall[k] / n, 4) for k in ks} | {"MRR": round(rr_sum / n, 4)}


def mrr_only(per_question_ranked, golds):
    rr_sum = 0.0
    for ranked, gold in zip(per_question_ranked, golds):
        rr = 0.0
        for rank, (pid, _) in enumerate(ranked, 1):
            if pid in gold:
                rr = 1.0 / rank
                break
        rr_sum += rr
    return rr_sum / len(golds)


def evaluate_by_type(per_question_ranked, golds, qtypes):
    from collections import defaultdict
    groups = defaultdict(list)
    for i, t in enumerate(qtypes):
        groups[t].append(i)
    return {t: round(mrr_only([per_question_ranked[i] for i in idxs],
                               [golds[i] for i in idxs]), 4)
            for t, idxs in groups.items()}


def main():
    rows = load_rows()
    questions = [r["question"] for r in rows]
    golds = [set(r["expected_sources"]) for r in rows]
    bf_labels = [r["business_function"] for r in rows]
    qtypes = [r["question_type"] for r in rows]
    print(f"평가 문항 {len(rows)}건")

    uids, texts, u2p = build_units("all")
    page2bf = {r["page_id"]: r["business_function"] for r in load_records()}
    unit2bf = {u: page2bf.get(p) for u, p in u2p.items()}

    print("검색기 구성 중...")
    bm25 = PageRanked(BM25Retriever(uids, texts, unit2bf), u2p)
    dense = PageRanked(QdrantDenseRetriever(QDRANT_PATH, QDRANT_COLLECTION), u2p)
    n = len(bm25.page_ids)

    model = _get_model(DEFAULT_DENSE_MODEL)
    print("질문 임베딩 계산 중(BF leave-page-out용)...")
    q_emb = model.encode(questions, normalize_embeddings=True, show_progress_bar=True, batch_size=8)
    S = q_emb @ q_emb.T

    # leave-page-out: 같은 페이지(gold set)에서 나온 형제 질문은 business_function이
    # 100% 동일하므로, 자기 자신만 빼는 leave-one-out은 형제 질문을 최근접으로 잡아
    # "진짜 일반화"가 아닌 누수된 점수를 준다. 같은 페이지 질문 전체를 제외한다.
    from collections import defaultdict
    page_key = [tuple(sorted(g)) for g in golds]
    key_to_idxs = defaultdict(list)
    for i, k in enumerate(page_key):
        key_to_idxs[k].append(i)
    for i, k in enumerate(page_key):
        S[i, key_to_idxs[k]] = -1e9

    categories = sorted(set(bf_labels))
    cat_idx = {c: np.array([i for i, b in enumerate(bf_labels) if b == c]) for c in categories}

    def bf_scores_for(i):
        return {c: float(S[i, idxs].max()) for c, idxs in cat_idx.items()}

    # ---- 질문당 검색은 한 번만: dense_ranked / bm25_ranked / fused / bf_scores 캐싱 ----
    print("질문별 검색 실행 중(캐싱)...")
    dense_rankeds, fused_rankeds, bf_scores_list = [], [], []
    for i, q in enumerate(questions):
        dr = dense.search(q, n)
        br = bm25.search(q, n)
        dense_rankeds.append(dr)
        fused_rankeds.append(rrf([br, dr]))
        bf_scores_list.append(bf_scores_for(i))
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(questions)}", flush=True)

    def dense_only():
        return [ranked for ranked in dense_rankeds]

    def hybrid_only():
        return [ranked for ranked in fused_rankeds]

    def dense_plus_bf(lam):
        out = []
        for dr, bf in zip(dense_rankeds, bf_scores_list):
            scored = [(pid, sc + lam * bf.get(page2bf.get(pid), 0.0)) for pid, sc in dr]
            out.append(sorted(scored, key=lambda x: x[1], reverse=True))
        return out

    def bm25_dense_plus_bf(lam):
        out = []
        for fr, bf in zip(fused_rankeds, bf_scores_list):
            scored = [(pid, sc * (1 + lam * bf.get(page2bf.get(pid), 0.0))) for pid, sc in fr]
            out.append(sorted(scored, key=lambda x: x[1], reverse=True))
        return out

    # ---- 팀원 제안: 유형별 1차 검색기(table_lookup=Dense, 나머지=Hybrid) 후,
    #      "예측된 business_function(top-1)과 일치하는 문서만" 가산점 부여 (하드 매칭) ----
    pred_bf_list = [max(bf, key=bf.get) for bf in bf_scores_list]
    base_rankeds = [
        dense_rankeds[i] if qtypes[i] == "table_lookup" else fused_rankeds[i]
        for i in range(len(questions))
    ]

    def base_only():
        return [ranked for ranked in base_rankeds]

    def type_aware_matched_bf(lam):
        out = []
        for base, bf, pred in zip(base_rankeds, bf_scores_list, pred_bf_list):
            bonus = lam * bf[pred]
            scored = [(pid, sc + (bonus if page2bf.get(pid) == pred else 0.0)) for pid, sc in base]
            out.append(sorted(scored, key=lambda x: x[1], reverse=True))
        return out

    print("\n=== 기존 baseline ===")
    print("Dense           :", evaluate(dense_only(), golds))
    print("Hybrid(BM25+Dense RRF):", evaluate(hybrid_only(), golds))

    print("\n=== Dense + BF (점수 직접 가중합, RRF 없음) ===")
    for lam in LAMBDAS:
        print(f"λ={lam:<4}:", evaluate(dense_plus_bf(lam), golds))

    print("\n=== BM25+Dense(RRF) + BF(가산점, 곱) ===")
    for lam in LAMBDAS:
        print(f"λ={lam:<4}:", evaluate(bm25_dense_plus_bf(lam), golds))

    print("\n=== 유형별 1차검색(table_lookup=Dense/나머지=Hybrid) + BF top-1 일치 가산점 ===")
    print("base(유형별 검색기, BF 미적용):", evaluate(base_only(), golds))
    for lam in LAMBDAS:
        print(f"λ={lam:<4}:", evaluate(type_aware_matched_bf(lam), golds))

    from collections import Counter
    types_count = Counter(qtypes)
    print("\n=== 유형별 MRR (λ=0.5 대표) ===")
    print("유형".ljust(14), "Dense".rjust(8), "Hybrid".rjust(8), "Dense+BF".rjust(10),
          "BM25+Dense+BF".rjust(14), "유형별+BF매칭".rjust(14))
    by_type = {
        "Dense": evaluate_by_type(dense_only(), golds, qtypes),
        "Hybrid": evaluate_by_type(hybrid_only(), golds, qtypes),
        "Dense+BF": evaluate_by_type(dense_plus_bf(0.5), golds, qtypes),
        "BM25+Dense+BF": evaluate_by_type(bm25_dense_plus_bf(0.5), golds, qtypes),
        "TypeAware+BFMatch": evaluate_by_type(type_aware_matched_bf(0.5), golds, qtypes),
    }
    for t in sorted(types_count, key=lambda t: -types_count[t]):
        print(f"{t}({types_count[t]})".ljust(14),
              f"{by_type['Dense'][t]:>8.3f}", f"{by_type['Hybrid'][t]:>8.3f}",
              f"{by_type['Dense+BF'][t]:>10.3f}", f"{by_type['BM25+Dense+BF'][t]:>14.3f}",
              f"{by_type['TypeAware+BFMatch'][t]:>14.3f}")


if __name__ == "__main__":
    sys.exit(main())
