"""Phase E — A/B 비교: Gate 1 단독 vs Gate 1 + Gate 2 결합.

실서비스 파이프라인 순서는 Gate 1 → Gate 2(파이프라인에서 Gate 1이 CONTINUE일 때만 Gate 2가
평가됨)다. 그래서 Gate 2의 진짜 기여도는 "전체 차단율"이 아니라 **Gate 1이 놓친 질문 중
Gate 2가 추가로 잡아내는 몫**(증분)이다. 이 스크립트는 testset_gate2_domain_eval.jsonl의
모든 문항에 대해 두 구성(A=Gate1만, B=Gate1+Gate2)을 실제 파이프라인 순서 그대로 재현해 비교한다.

안전 확인도 겸한다 — in_domain 두 그룹(clear/boundary)에서 A 또는 B가 오차단하면 0건이어야
한다(Gate 1이 이미 통과시키는 것을 Gate 2가 새로 막으면 안 되고, Gate 1 자체가 이미 오차단하고
있다면 그건 Gate 2와 무관한 기존 버그이므로 별도로 표시한다).

threshold·결정규칙은 config/gate2_reference.json에서 읽는다(하드코딩 금지).

실행: python3 experiments/gate2_ab_comparison.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # experiments/ -> 리포 루트
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "crawler"))

import numpy as np  # noqa: E402

from gate1 import run_gate1  # noqa: E402
from retrieval import DEFAULT_DENSE_MODEL, _get_model  # noqa: E402

CACHE_DIR = ROOT / "data" / "gate2_cache"
CONFIG_PATH = ROOT / "config" / "gate2_reference.json"
TESTSET_PATH = ROOT / "data" / "testset" / "testset_gate2_domain_eval.jsonl"

GROUPS = ["clear_in_domain", "boundary_in_domain", "clear_out_domain", "boundary_out_domain"]


def _load_testset():
    recs = []
    with open(TESTSET_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def main():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    threshold = config["threshold"]
    manifest = json.loads((CACHE_DIR / "manifest.json").read_text(encoding="utf-8"))
    in_emb = np.load(CACHE_DIR / "in_domain_emb.npy")
    out_emb = np.load(CACHE_DIR / "out_domain_emb.npy")
    assert manifest["model"] == DEFAULT_DENSE_MODEL

    testset = _load_testset()
    model = _get_model(DEFAULT_DENSE_MODEL)
    questions = [r["question"] for r in testset]
    q_emb = model.encode(questions, normalize_embeddings=True, show_progress_bar=True, batch_size=8)
    s_id_max = (q_emb @ in_emb.T).max(axis=1)
    s_ood_max = (q_emb @ out_emb.T).max(axis=1)

    for r, sid, sood in zip(testset, s_id_max, s_ood_max):
        g1 = run_gate1(r["question"])
        gate1_exit = g1.action == "EXIT"
        gate2_block = bool(sood >= threshold and sood > sid)
        # 실제 파이프라인 순서: Gate1이 이미 EXIT면 Gate2는 평가되지 않는다(도달 안 함).
        gate2_reached = not gate1_exit
        combined_exit = gate1_exit or (gate2_reached and gate2_block)
        r.update(gate1_exit=gate1_exit, gate1_label=g1.label, gate2_reached=gate2_reached,
                  gate2_block=gate2_block, combined_exit=combined_exit,
                  s_id=float(sid), s_ood=float(sood))

    by_group = {g: [r for r in testset if r["group"] == g] for g in GROUPS}

    print(f"threshold = {threshold} (config/gate2_reference.json)")
    print()
    print("=== A(Gate1만) vs B(Gate1+Gate2) 차단율 ===")
    print(f"{'group':<20} {'A: Gate1만':>12} {'B: Gate1+Gate2':>16} {'Gate2 증분':>12}")
    for g in GROUPS:
        recs = by_group[g]
        n = len(recs)
        a_rate = sum(r["gate1_exit"] for r in recs) / n
        b_rate = sum(r["combined_exit"] for r in recs) / n
        # 증분 = Gate1은 안 막았는데 Gate2가 새로 막은 문항 비율
        incr = sum(1 for r in recs if not r["gate1_exit"] and r["gate2_reached"] and r["gate2_block"]) / n
        print(f"{g:<20} {a_rate:>12.1%} {b_rate:>16.1%} {incr:>12.1%}")
    print()

    # ---- 안전 확인: in_domain 두 그룹에서 A/B 오차단 ----
    for g in ["clear_in_domain", "boundary_in_domain"]:
        recs = by_group[g]
        gate1_fp = [r for r in recs if r["gate1_exit"]]
        combined_fp = [r for r in recs if r["combined_exit"]]
        gate2_new_fp = [r for r in combined_fp if not r["gate1_exit"]]
        print(f"=== {g} 오차단 확인 ===")
        print(f"  Gate1 단독 오차단: {len(gate1_fp)}건"
              + ("" if not gate1_fp else " ⚠ Gate2와 무관한 기존 Gate1 이슈"))
        for r in gate1_fp:
            print(f"    \"{r['question']}\" (gate1_label={r['gate1_label']})")
        print(f"  Gate2가 새로 추가한 오차단: {len(gate2_new_fp)}건")
        for r in gate2_new_fp:
            print(f"    \"{r['question']}\" (s_id={r['s_id']:.3f}, s_ood={r['s_ood']:.3f})")
        print()

    # ---- Gate2가 실제로 도달(Gate1 CONTINUE)한 out_domain 문항 중 증분 기여 상세 ----
    print("=== Gate2 증분 기여 상세: clear_out_domain 중 Gate1은 놓치고 Gate2가 잡은 문항(최대 10건) ===")
    incr_examples = [r for r in by_group["clear_out_domain"]
                      if not r["gate1_exit"] and r["gate2_reached"] and r["gate2_block"]]
    for r in incr_examples[:10]:
        print(f"  \"{r['question']}\"  (s_id={r['s_id']:.3f}, s_ood={r['s_ood']:.3f})")
    print(f"  총 {len(incr_examples)}건")
    print()

    print("=== Gate2 증분 기여 상세: boundary_out_domain 중 Gate1은 놓치고 Gate2가 잡은 문항 ===")
    incr_boundary = [r for r in by_group["boundary_out_domain"]
                      if not r["gate1_exit"] and r["gate2_reached"] and r["gate2_block"]]
    for r in incr_boundary:
        print(f"  \"{r['question']}\"  (s_id={r['s_id']:.3f}, s_ood={r['s_ood']:.3f})")
    print(f"  총 {len(incr_boundary)}건")

    out_path = CACHE_DIR / "ab_comparison_report.json"
    out_path.write_text(json.dumps({
        "threshold": threshold,
        "groups": {g: {
            "n": len(by_group[g]),
            "gate1_only_block_rate": sum(r["gate1_exit"] for r in by_group[g]) / len(by_group[g]),
            "combined_block_rate": sum(r["combined_exit"] for r in by_group[g]) / len(by_group[g]),
        } for g in GROUPS},
        "records": [{k: r[k] for k in
                     ("question", "group", "domain_label", "gate1_exit", "gate1_label",
                      "gate2_block", "combined_exit", "s_id", "s_ood")} for r in testset],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n상세 리포트 → {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
