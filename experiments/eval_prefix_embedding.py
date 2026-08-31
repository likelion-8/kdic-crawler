"""프리픽스 임베딩 A/B — 청크 텍스트 앞에 [page_title · business_function]을 붙여
색인하면 검색이 좋아지는가 (contextual retrieval의 결정론 버전, 2026-08-19 실험).

배경: 임베딩·BM25가 현재 청크 본문(text)만 색인하고 page_title·business_function은
DB 컬럼에만 있어 검색 신호에서 통째로 빠져 있다(2026-08-18 확인). 특히 300자 미만
청크 161/503개(FAQ 답변·표 블록)는 본문에 주제 신호가 거의 없어 프리픽스 효과가
집중될 것으로 가설을 세웠다.

방법: 운영 인덱스는 건드리지 않는다 — index_gate 와 같은 방식으로 두 변형(베이스라인/
프리픽스)의 메모리 인덱스를 각각 만들어 같은 질문으로 채점한다. 라우팅은 분류기 예측이
아니라 테스트셋의 question_type 라벨로 하는 오라클 라우팅(link_guide→Hybrid, 그 외
Dense) — 인덱스 내용의 효과만 분리해서 재기 위해 분류기 오차라는 변인을 제거한다.

테스트셋: data/testset/testset_retrieval_eval_v1.jsonl (66문항, 골든셋과 원문 중복 0 확인).
채점은 페이지 단위(expected_sources), MRR은 상위 20위까지만(@20 컷오프, 미달 시 0).

판정 기준(실험 전 합의, 2026-08-18):
  ① 효과: FAQ·표 서브셋에서 R@5 순증(새 성공 - 새 실패) > 0
  ② 가드: 일반 서브셋(fact·link_guide·file_download)에서 새 실패 0(있으면 개별 검토)
  ③ 경보: R@20 하락 시 즉시 기각(프리픽스 희석이 심각하다는 뜻)

실행: python experiments/eval_prefix_embedding.py   (bge-m3 로딩 + 프리픽스 503청크 인코딩
     — 첫 실행 수 분, dense_cache 적중 시 수 초. 결과: results/prefix_embedding_eval_v1.json)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # experiments/ -> 리포 루트
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "crawler"))

from chunking import build_units, load_records  # noqa: E402
from retrieval import (BM25Retriever, DenseRetriever, HybridRetriever,  # noqa: E402
                       HYBRID_LINEAR_ALPHA, PageRanked)

TESTSET = ROOT / "data" / "testset" / "testset_retrieval_eval_v1.jsonl"
OUT = ROOT / "results" / "prefix_embedding_eval_v1.json"
EFFECT_TYPES = {"faq", "table_lookup"}   # 효과가 예측되는 서브셋 — 나머지는 가드(비악화)
K_REPORT = 20                            # 랭킹 조회 폭 = R@20·MRR 컷오프


def load_testset():
    rows = [json.loads(l) for l in open(TESTSET, encoding="utf-8")]
    assert all(r.get("expected_sources") for r in rows), "expected_sources 빈 문항 존재"
    return rows


def make_prefix_texts(uids, texts, u2p, meta):
    """[page_title · business_function] 프리픽스 변형. 분할은 안 건드리므로 unit_id 불변."""
    out = []
    for uid, t in zip(uids, texts):
        m = meta[u2p[uid]]
        out.append(f"[{m['page_title']} · {m['business_function']}] {t}")
    return out


def build_retrievers(uids, texts, u2p):
    """변형 하나의 (dense, hybrid) 페이지 단위 검색기. 서비스와 동일 구성 —
    Dense 단독 + link_guide 전용 Hybrid(BM25+Dense linear α=0.4)."""
    dense = PageRanked(DenseRetriever(uids, texts), u2p)
    bm25 = PageRanked(BM25Retriever(uids, texts, None), u2p)
    hybrid = HybridRetriever(bm25, dense, alpha=HYBRID_LINEAR_ALPHA)
    return dense, hybrid


def rank_of(ranking, expected):
    """페이지 랭킹에서 정답(복수 허용) 최고 순위(1-base). 20위 밖이면 None."""
    exp = set(expected)
    for i, (pid, _score) in enumerate(ranking):
        if pid in exp:
            return i + 1
    return None


def evaluate(rows, dense, hybrid):
    """문항별 {rank, top5} — 라우팅은 라벨 기반 오라클(link_guide→Hybrid)."""
    per_q = []
    for r in rows:
        retr = hybrid if r["question_type"] == "link_guide" else dense
        ranking = retr.search(r["question"], K_REPORT)
        per_q.append({
            "rank": rank_of(ranking, r["expected_sources"]),
            "top5": [pid for pid, _ in ranking[:5]],
        })
    return per_q


def metrics(sub):
    """sub: [{rank}, ...] → {n, r5, r20, mrr}. MRR은 @20 컷오프(미달 0)."""
    n = len(sub)
    if n == 0:
        return {"n": 0, "r5": None, "r20": None, "mrr": None}
    r5 = sum(1 for s in sub if s["rank"] is not None and s["rank"] <= 5) / n
    r20 = sum(1 for s in sub if s["rank"] is not None) / n
    mrr = sum(1.0 / s["rank"] for s in sub if s["rank"] is not None) / n
    return {"n": n, "r5": round(r5, 4), "r20": round(r20, 4), "mrr": round(mrr, 4)}


def main():
    rows = load_testset()
    meta = {r["page_id"]: r for r in load_records()}
    uids, texts, u2p = build_units("all")
    print(f"테스트셋 {len(rows)}문항 · 유닛 {len(uids)}개", flush=True)

    print("[1/2] 베이스라인 인덱스 구성(캐시 적중 시 빠름)...", flush=True)
    base_dense, base_hybrid = build_retrievers(uids, texts, u2p)
    print("[2/2] 프리픽스 인덱스 구성(첫 실행은 503청크 인코딩)...", flush=True)
    ptexts = make_prefix_texts(uids, texts, u2p, meta)
    pref_dense, pref_hybrid = build_retrievers(uids, ptexts, u2p)

    base = evaluate(rows, base_dense, base_hybrid)
    pref = evaluate(rows, pref_dense, pref_hybrid)

    # ── 서브셋(효과/일반/전체) × 지표 ──
    def subset(per_q, pred):
        return [s for r, s in zip(rows, per_q) if pred(r)]
    buckets = {
        "faq_표 (효과)": lambda r: r["question_type"] in EFFECT_TYPES,
        "일반 (가드)": lambda r: r["question_type"] not in EFFECT_TYPES,
        "전체": lambda r: True,
    }
    table = {name: {"baseline": metrics(subset(base, p)), "prefix": metrics(subset(pref, p))}
             for name, p in buckets.items()}

    # ── 뒤집힌 문항(R@5 기준) + 업무일치 진단 ──
    flips = []
    for r, b, p in zip(rows, base, pref):
        b5 = b["rank"] is not None and b["rank"] <= 5
        p5 = p["rank"] is not None and p["rank"] <= 5
        if b5 == p5:
            continue
        exp_bf = meta[r["expected_sources"][0]]["business_function"]
        # 업무일치: 프리픽스 쪽 top5에 정답 업무의 페이지가 하나라도 있나 —
        # "업무는 맞는데 페이지가 틀림"(방향은 잡음)과 "업무부터 틀림"(무력)을 가른다.
        bf_match = any(meta[pid]["business_function"] == exp_bf for pid in p["top5"])
        flips.append({
            "direction": "새 성공" if p5 else "새 실패",
            "test_id": r.get("test_id"), "question": r["question"],
            "question_type": r["question_type"], "expected": r["expected_sources"],
            "rank_baseline": b["rank"], "rank_prefix": p["rank"],
            "expected_bf": exp_bf, "prefix_top5": p["top5"], "top5_업무일치": bf_match,
        })

    # ── 판정 ──
    eff_new_ok = sum(1 for f in flips if f["direction"] == "새 성공" and f["question_type"] in EFFECT_TYPES)
    eff_new_ng = sum(1 for f in flips if f["direction"] == "새 실패" and f["question_type"] in EFFECT_TYPES)
    gen_new_ng = sum(1 for f in flips if f["direction"] == "새 실패" and f["question_type"] not in EFFECT_TYPES)
    r20_drop = (table["전체"]["prefix"]["r20"] or 0) < (table["전체"]["baseline"]["r20"] or 0)
    verdict = {
        "효과_순증(faq·표)": eff_new_ok - eff_new_ng,
        "일반_새실패": gen_new_ng, "R@20_하락": r20_drop,
        "판정": ("채택 후보" if (eff_new_ok - eff_new_ng) > 0 and gen_new_ng == 0 and not r20_drop
                 else "기각 또는 개별 검토"),
    }

    result = {"testset": TESTSET.name, "n": len(rows),
              "prefix_format": "[page_title · business_function] ",
              "table": table, "flips": flips, "verdict": verdict}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'서브셋':<14} {'지표':<5} {'베이스라인':>10} {'프리픽스':>10} {'차이':>8}")
    for name, m in table.items():
        for k in ("r5", "r20", "mrr"):
            b, p = m["baseline"][k], m["prefix"][k]
            print(f"{name:<14} {k.upper():<5} {b:>10.4f} {p:>10.4f} {p - b:>+8.4f}")
    print(f"\n뒤집힌 문항 {len(flips)}건:")
    for f in flips:
        print(f"  [{f['direction']}] ({f['question_type']}) {f['question'][:38]}"
              f" | rank {f['rank_baseline']}→{f['rank_prefix']} | 업무일치={f['top5_업무일치']}")
    print(f"\n판정: {verdict}")
    print(f"결과 저장: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
