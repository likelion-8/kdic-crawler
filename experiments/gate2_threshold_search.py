"""Gate 2 임계값 그리드서치 — data/gate2_cache/ 참조 벡터 + testset_gate2_domain_eval.jsonl.

판정 방식(재확인, build_gate2_reference.py와 동일 전제): 클러스터 centroid 평균이 아니라
in_domain·out_of_domain 각각의 **개별 문장 벡터 전체 중 최댓값**을 쓴다.
    s_id  = max_i cos(q, in_domain_emb[i])   — 질의와 가장 가까운 in_domain 예시 유사도
    s_ood = max_j cos(q, out_domain_emb[j])  — 질의와 가장 가까운 out_of_domain 예시 유사도
클러스터 안에서 문장 길이가 짧든 길든 그 벡터는 자기 위치에 그대로 남고 서로 평균으로
희석되지 않으므로(2026-08-19 팀 확인), 커버리지를 넓히려 섞어 넣은 단어형 항목이 기존
항목의 판정 정확도를 깎지 않는다.

결정 규칙(그리드서치 대상 파라미터는 threshold 하나):
    block = (s_ood >= threshold) AND (s_ood > s_id)
threshold만으로 막지 않고 s_ood > s_id 비교를 같이 요구하는 이유 — 인접도메인 어휘
(신용등급·대출 상담 등)가 out_domain 참조와 표면적으로 가까워 s_ood가 높게 나와도, 그
질문이 실제로는 도메인 코퍼스 내용과 더 가깝다면(s_id가 더 큼) 오차단하지 않기 위한
안전장치다. Gate 1과 같은 정밀도 우선(확실한 경우만 EXIT) 철학을 따른다.

Gate 2는 하드 블록 대상이므로 두 안전 지표가 0에 가까울수록 좋다:
    false_block_clear_in     = clear_in_domain 중 잘못 차단된 비율
    false_block_boundary_in  = boundary_in_domain 중 잘못 차단된 비율 (핵심 안전 지표)
그 위에서 out_of_domain 차단율(재현율)을 최대화하는 threshold를 고른다.

실행: python3 experiments/gate2_threshold_search.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # experiments/ -> 리포 루트
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "crawler"))

import numpy as np  # noqa: E402

from retrieval import DEFAULT_DENSE_MODEL, _get_model  # noqa: E402

CACHE_DIR = ROOT / "data" / "gate2_cache"
TESTSET_PATH = ROOT / "data" / "testset" / "testset_gate2_domain_eval.jsonl"

GROUPS = ["clear_in_domain", "boundary_in_domain", "clear_out_domain", "boundary_out_domain"]
# pass=차단되면 안 됨(오탐), block=차단돼야 함(재현)
GROUP_EXPECTED = {"clear_in_domain": "pass", "boundary_in_domain": "pass",
                  "clear_out_domain": "block", "boundary_out_domain": "block"}

THRESHOLD_GRID = np.round(np.arange(0.30, 0.91, 0.02), 2)


def _load_testset():
    recs = []
    with open(TESTSET_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def main():
    manifest = json.loads((CACHE_DIR / "manifest.json").read_text(encoding="utf-8"))
    in_emb = np.load(CACHE_DIR / "in_domain_emb.npy")
    out_emb = np.load(CACHE_DIR / "out_domain_emb.npy")
    assert manifest["model"] == DEFAULT_DENSE_MODEL, (
        f"gate2_cache가 다른 모델로 만들어짐({manifest['model']}) — "
        f"build_gate2_reference.py를 다시 실행하세요.")
    print(f"참조 벡터: in_domain {in_emb.shape[0]}개, out_of_domain {out_emb.shape[0]}개 "
          f"(개별 문장 벡터, centroid 아님)")

    testset = _load_testset()
    model = _get_model(DEFAULT_DENSE_MODEL)
    questions = [r["question"] for r in testset]
    q_emb = model.encode(questions, normalize_embeddings=True, show_progress_bar=True, batch_size=8)

    s_id = q_emb @ in_emb.T   # (N, N_in)
    s_ood = q_emb @ out_emb.T  # (N, N_out)
    s_id_max = s_id.max(axis=1)
    s_ood_max = s_ood.max(axis=1)

    for r, sid, sood in zip(testset, s_id_max, s_ood_max):
        r["s_id"] = float(sid)
        r["s_ood"] = float(sood)

    by_group = {g: [r for r in testset if r["group"] == g] for g in GROUPS}
    print("그룹별 문항수:", {g: len(v) for g, v in by_group.items()})
    print()

    # ---- 그리드서치 ----
    rows = []
    for T in THRESHOLD_GRID:
        rates = {}
        for g in GROUPS:
            recs = by_group[g]
            blocked = sum(1 for r in recs if r["s_ood"] >= T and r["s_ood"] > r["s_id"])
            rates[g] = blocked / len(recs) if recs else 0.0
        false_pos = rates["clear_in_domain"] + rates["boundary_in_domain"]
        recall = rates["clear_out_domain"] + rates["boundary_out_domain"]
        # 오탐 0을 최우선(큰 페널티)으로, 그다음 out_domain 차단율(재현) 최대화
        score = recall - 100 * false_pos
        rows.append({"threshold": float(T), **rates, "false_pos_sum": false_pos,
                      "recall_sum": recall, "score": score})

    rows.sort(key=lambda r: r["score"], reverse=True)
    print("=== 그리드서치 top-10 (오탐 0 우선 → out_domain 차단율 최대화 순) ===")
    header = f"{'T':>5} {'clear_in':>9} {'bound_in':>9} {'clear_out':>10} {'bound_out':>10}"
    print(header)
    for r in rows[:10]:
        print(f"{r['threshold']:>5.2f} {r['clear_in_domain']:>9.1%} {r['boundary_in_domain']:>9.1%} "
              f"{r['clear_out_domain']:>10.1%} {r['boundary_out_domain']:>10.1%}")
    print()

    # ---- 추천 threshold: 두 in_domain 그룹 오탐률이 모두 0인 후보 중 out_domain 차단율 최대 ----
    zero_fp = [r for r in rows if r["clear_in_domain"] == 0.0 and r["boundary_in_domain"] == 0.0]
    if zero_fp:
        zero_fp.sort(key=lambda r: r["recall_sum"], reverse=True)
        best = zero_fp[0]
        print(f"추천 threshold = {best['threshold']:.2f}  "
              f"(in_domain 오탐 0, out_domain 차단율 clear={best['clear_out_domain']:.1%} "
              f"boundary={best['boundary_out_domain']:.1%})")
    else:
        best = rows[0]
        print(f"⚠ in_domain 오탐률 0을 만족하는 threshold가 그리드 내에 없음. "
              f"최선 후보 threshold={best['threshold']:.2f} "
              f"(clear_in 오탐={best['clear_in_domain']:.1%}, "
              f"boundary_in 오탐={best['boundary_in_domain']:.1%}) — 참조 사전 보강 필요.")
    print()

    # ---- boundary_in_domain 오차단 목록(추천 threshold 기준) ----
    T = best["threshold"]
    fp_boundary = [r for r in by_group["boundary_in_domain"]
                   if r["s_ood"] >= T and r["s_ood"] > r["s_id"]]
    print(f"=== boundary_in_domain 오차단 목록(threshold={T:.2f}) — {len(fp_boundary)}건 ===")
    for r in fp_boundary:
        print(f"  \"{r['question']}\"  (note={r.get('note','')}, s_id={r['s_id']:.3f}, s_ood={r['s_ood']:.3f})")
    if not fp_boundary:
        print("  없음")
    print()

    # ---- clear_in_domain 오차단 목록(추천 threshold 기준) ----
    fp_clear = [r for r in by_group["clear_in_domain"]
                if r["s_ood"] >= T and r["s_ood"] > r["s_id"]]
    print(f"=== clear_in_domain 오차단 목록(threshold={T:.2f}) — {len(fp_clear)}건 ===")
    for r in fp_clear:
        print(f"  \"{r['question']}\"  (s_id={r['s_id']:.3f}, s_ood={r['s_ood']:.3f})")
    if not fp_clear:
        print("  없음")
    print()

    # ---- 인접도메인 어휘 중첩 특별 점검: boundary_in_domain 중 채무조정/신용 관련 항목 ----
    watch_kw = ["채무조정", "신용", "대출", "카드", "연체", "감면", "이자"]
    watch = [r for r in by_group["boundary_in_domain"]
             if any(k in r["question"] or k in r.get("note", "") for k in watch_kw)]
    print(f"=== 인접도메인 어휘 중첩 특별 점검: boundary_in_domain 중 채무조정/신용 계열 {len(watch)}건 "
          f"(threshold={T:.2f}) ===")
    for r in watch:
        blocked = r["s_ood"] >= T and r["s_ood"] > r["s_id"]
        mark = "❌ 오차단" if blocked else "✓ 통과"
        print(f"  {mark}  \"{r['question']}\"  (s_id={r['s_id']:.3f}, s_ood={r['s_ood']:.3f})")
    print()

    # ---- clear_out vs boundary_out 차단율 격차 ----
    gap = best["clear_out_domain"] - best["boundary_out_domain"]
    print(f"=== clear_out_domain vs boundary_out_domain 차단율 격차(threshold={T:.2f}) ===")
    print(f"  clear_out_domain    차단율 = {best['clear_out_domain']:.1%}")
    print(f"  boundary_out_domain 차단율 = {best['boundary_out_domain']:.1%}")
    print(f"  격차 = {gap:+.1%}")

    out_path = ROOT / "data" / "gate2_cache" / "threshold_search_report.json"
    out_path.write_text(json.dumps({
        "grid": rows, "recommended_threshold": T,
        "boundary_in_domain_false_positives": [
            {"question": r["question"], "note": r.get("note", ""),
             "s_id": r["s_id"], "s_ood": r["s_ood"]} for r in fp_boundary],
        "clear_in_domain_false_positives": [
            {"question": r["question"], "s_id": r["s_id"], "s_ood": r["s_ood"]} for r in fp_clear],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n상세 리포트 → {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
