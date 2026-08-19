"""라우팅 가치 재측정 — "link_guide 만 Hybrid" 규칙이 현재 코퍼스에서도 유효한가.

**왜 필요한가.** retrieval.py:266-275 의 유형별 Dense/Hybrid MRR 표는 2026-07-28 실측이고,
그 뒤에 코퍼스 재수집(2026-08-18)·[제목·업무] 프리픽스 임베딩 채택(b123c64)·청킹 변경
(503청크)이 있었다. 골든셋 검증(validate_goldenset.py)의 비용 가중 손익이 전부 이 표에
얹혀 있어서, 표가 뒤집히면 "어느 오분류가 비싼가"의 결론도 뒤집힌다. 심하면 라우팅 규칙
자체가 무효가 되어 골든셋의 link_guide 라벨을 고치는 일이 의미를 잃는다.

**분류기를 태우지 않는다.** 각 문항의 정답 question_type 을 알고 있으므로 유형별로 Dense·
Hybrid 를 직접 돌려 비교한다. 분류기가 개입하지 않으니 자기참조 누수가 없고, 따라서
골든셋 819문항을 그대로 표본으로 쓸 수 있다(link_guide 59 · table_lookup 114 — 외부
검증셋 3개를 합친 것보다 크다). 여기서 재는 것은 '분류기가 얼마나 맞히나'가 아니라
'맞혔을 때/틀렸을 때 검색이 얼마나 달라지나'다.

**모델을 안 올린다.** 청크 임베딩·질문 임베딩 모두 dense_cache 의 .npy 를 직접 읽는다.
BM25 축만 Kiwi 토크나이저를 쓴다(질문 819개 토큰화는 수십 초). 캐시가 없으면 중단한다 —
bge-m3 를 CPU 로 올리는 비용을 조용히 치르지 않기 위해서다.

**pgvector 대신 로컬 청크 임베딩을 쓰는 이유.** 운영 Dense 축은 PgVectorDenseRetriever 이고
DB 는 현재 503청크로 로컬과 일치한다(2026-08-19 확인). 같은 벡터이므로 결과가 같고,
질의마다 DB 왕복을 하지 않아 819문항이 몇 초에 끝난다.

읽기 전용. 결과는 results/routing_value/ 에 쓴다.
실행: python3 src/eval/eval_routing_value.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from retrieval import (BM25Retriever, DEFAULT_DENSE_MODEL, DenseRetriever,  # noqa: E402
                       HYBRID_LINEAR_ALPHA, PageRanked, linear_fuse)

CHUNKS = ROOT / "data" / "chunks_all.jsonl"
GOLDEN = ROOT / "data" / "testset" / "testset_all.jsonl"
OUTDIR = ROOT / "results" / "routing_value"
RECALL_K = 5
HYBRID_ONLY = "link_guide"


def _jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _cached(texts, what):
    path = DenseRetriever._cache_path(texts, DEFAULT_DENSE_MODEL)
    if not path.exists():
        sys.exit(f"{what} 임베딩 캐시가 없습니다({path.name}). "
                 f"모델 로딩을 피하려고 여기서 멈춥니다 — 캐시를 만든 뒤 다시 실행하세요.")
    return np.load(path)


class _PrecomputedDense:
    """질문 임베딩을 미리 가진 Dense 검색기 — DenseRetriever 와 같은 search() 계약.

    DenseRetriever 를 그냥 쓰면 캐시가 있어도 생성자가 모델을 먼저 올린다. 여기서는
    (질문 -> 벡터) 맵을 받아 내적만 한다."""

    def __init__(self, unit_ids, doc_emb, qvec):
        self.unit_ids = unit_ids
        self.doc_emb = doc_emb
        self.qvec = qvec

    def search(self, query, k, business_function=None):
        del business_function          # 업무 필터는 현재 비활성(retrieval._build_engines)
        scores = self.doc_emb @ self.qvec[query]
        ranked = sorted(zip(self.unit_ids, scores.tolist()), key=lambda x: x[1], reverse=True)
        return ranked[:k]


def _recall_mrr(ranked_pages, gold):
    """index_gate._recall_mrr · eval_pipeline_retrieval 과 같은 규약."""
    recall = len(gold & set(ranked_pages[:RECALL_K])) / len(gold)
    for i, p in enumerate(ranked_pages, 1):
        if p in gold:
            return recall, 1.0 / i
    return recall, 0.0


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    chunks = _jsonl(CHUNKS)
    uids = [c["chunk_id"] for c in chunks]
    texts = [c["text"] for c in chunks]
    unit2page = {c["chunk_id"]: c["page_id"] for c in chunks}

    golden = _jsonl(GOLDEN)
    qemb = _cached([g["question"] for g in golden], "골든셋 질문")
    qvec = {g["question"]: qemb[i] for i, g in enumerate(golden)}
    scored = [g for g in golden if g.get("expected_sources")]

    print(f"청크 {len(chunks)} · 채점 문항 {len(scored)} — 인덱스 조립 중")
    dense = PageRanked(_PrecomputedDense(uids, _cached(texts, "청크"), qvec), unit2page)
    bm25 = PageRanked(BM25Retriever(uids, texts), unit2page)
    n_pages = len(dense.page_ids)

    per_type = defaultdict(lambda: {"n": 0, "dense_mrr": 0.0, "hybrid_mrr": 0.0,
                                    "dense_r5": 0.0, "hybrid_r5": 0.0})
    # 문항별 (유형, Dense MRR, Hybrid MRR) — 부트스트랩 신뢰구간과 사후 분석에 쓴다.
    # 유형별 차이가 작을 때(±0.02 수준) 평균만으로는 부호를 믿을 수 없다.
    detail = []
    for i, g in enumerate(scored):
        if i and i % 200 == 0:
            print(f"  {i}/{len(scored)}")
        q, gold = g["question"], set(g["expected_sources"])
        d = dense.search(q, n_pages)
        b = bm25.search(q, n_pages)
        h = linear_fuse(b, d, HYBRID_LINEAR_ALPHA)
        acc = per_type[g["question_type"]]
        acc["n"] += 1
        rrs = {}
        for name, ranked in (("dense", d), ("hybrid", h)):
            recall, rr = _recall_mrr([p for p, _ in ranked], gold)
            acc[f"{name}_mrr"] += rr
            acc[f"{name}_r5"] += recall
            rrs[name] = rr
        detail.append({"test_id": g["test_id"], "question_type": g["question_type"],
                       "page": (g["expected_sources"] or [""])[0],
                       "dense_mrr": rrs["dense"], "hybrid_mrr": rrs["hybrid"]})

    # 유형별 쌍대 부트스트랩 — 같은 문항에 두 방식을 다 돌렸으므로 문항 단위로 재표집한다.
    # 95% 구간이 0을 포함하면 그 유형의 Dense/Hybrid 우열은 이 표본으로 판정할 수 없다.
    rng = np.random.default_rng(20260819)
    by_t = defaultdict(list)
    for row in detail:
        by_t[row["question_type"]].append(row["hybrid_mrr"] - row["dense_mrr"])

    table = {}
    for t, a in per_type.items():
        table[t] = {k: round(a[k] / a["n"], 4) for k in
                    ("dense_mrr", "hybrid_mrr", "dense_r5", "hybrid_r5")}
        table[t]["n"] = a["n"]
        diffs = np.array(by_t[t])
        table[t]["hybrid_minus_dense_mrr"] = round(float(diffs.mean()), 4)
        boot = rng.choice(diffs, size=(2000, len(diffs)), replace=True).mean(axis=1)
        lo, hi = np.percentile(boot, [2.5, 97.5])
        table[t]["ci95"] = [round(float(lo), 4), round(float(hi), 4)]
        table[t]["유의"] = bool(lo > 0 or hi < 0)

    total = sum(a["n"] for a in per_type.values())
    all_dense = sum(per_type[t]["dense_mrr"] for t in per_type) / total
    oracle = sum(per_type[t]["hybrid_mrr" if t == HYBRID_ONLY else "dense_mrr"]
                 for t in per_type) / total
    gain_per_lg = table[HYBRID_ONLY]["hybrid_minus_dense_mrr"]
    breakeven = {t: round(table[HYBRID_ONLY]["n"] * gain_per_lg / -v["hybrid_minus_dense_mrr"], 1)
                 for t, v in table.items()
                 if t != HYBRID_ONLY and v["hybrid_minus_dense_mrr"] < 0}

    # 유형별 최적 라우팅(차이가 유의하게 +인 유형만 Hybrid)의 상한 — 현행 규칙과 비교한다.
    best_hybrid = sorted(t for t, v in table.items() if v["유의"] and v["ci95"][0] > 0)
    best = sum(per_type[t]["hybrid_mrr" if t in best_hybrid else "dense_mrr"]
               for t in per_type) / total

    result = {"청크수": len(chunks), "채점문항": total, "유형별": table,
              "전부_Dense_MRR": round(all_dense, 4), "오라클_MRR": round(oracle, 4),
              "라우팅_이론상_최대이득": round(oracle - all_dense, 4),
              "link_guide_1건_이득": gain_per_lg,
              "손익분기_오판건수": breakeven,
              "규칙_유효": gain_per_lg > 0,
              "유형별최적_Hybrid대상": best_hybrid,
              "유형별최적_MRR": round(best, 4),
              "유형별최적_대비_현행규칙_손실": round(best - oracle, 4)}
    with open(OUTDIR / "routing_value.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    with open(OUTDIR / "per_question.json", "w", encoding="utf-8") as f:
        json.dump(detail, f, ensure_ascii=False)

    print()
    print(f"{'유형':16}{'n':>5}{'Dense':>9}{'Hybrid':>9}{'차이':>9}   {'95% CI':>18}  유의")
    for t, v in sorted(table.items(), key=lambda x: -x[1]["n"]):
        ci = f"[{v['ci95'][0]:+.3f}, {v['ci95'][1]:+.3f}]"
        print(f"{t:16}{v['n']:>5}{v['dense_mrr']:>9.3f}{v['hybrid_mrr']:>9.3f}"
              f"{v['hybrid_minus_dense_mrr']:>+9.3f}   {ci:>18}  {'★' if v['유의'] else ''}")
    print()
    print(f"유형별 최적 Hybrid 대상: {best_hybrid or '없음'}  -> MRR {best:.4f} "
          f"(현행 규칙 오라클 {oracle:.4f} 대비 {best - oracle:+.4f})")
    print()
    print(f"전부 Dense MRR {all_dense:.4f}  ->  오라클 MRR {oracle:.4f}  "
          f"(이론상 최대이득 {oracle - all_dense:+.4f})")
    print(f"link_guide 규칙 {'유효 (Hybrid 가 낫다)' if gain_per_lg > 0 else '★ 무효 (Dense 가 낫다)'}"
          f" — 1건당 {gain_per_lg:+.3f}")
    print(f"손익분기 오판건수: {breakeven}")
    print(f"결과: {OUTDIR}")


if __name__ == "__main__":
    sys.exit(main())
