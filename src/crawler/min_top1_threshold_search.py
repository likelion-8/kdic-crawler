"""MIN_TOP1_SCORE(무관 질문 게이트) 임계값 재탐색 — 2026-08-25 현재 색인 기준.

이 게이트는 질문을 차단하지 않는다. top-1 검색 점수가 임계값 미만이면 **근거를 통째로
비운다**(candidate_ranking.gate_low_relevance). 그래서 이 실험이 답해야 할 질문은
"무관 질문을 얼마나 막나"가 아니라 다음 하나다:

    이 임계값에서 인스코프 질문의 근거가 사라지지 않으면서, 무관 질문에는 근거가 안 붙는가?

기존 0.35 의 근거(candidate_ranking.py 주석, 2026-08-10)는 두 가지 이유로 그대로 못 쓴다.
  1) 08-18 프리픽스 색인 채택으로 점수 분포가 바뀌었다(DB 503/503 청크가 [제목·업무] 프리픽스).
  2) 08-19 Gate 1(룰)·Gate 2(임베딩)가 검색 **앞**에 생겨, 그때 근거로 쓴 잡담 5건은
     이제 이 게이트까지 오지도 않는다.

── 이 스크립트가 지키는 측정 조건 (셋 다 결과를 가른다) ────────────────────────────────
DB 로 잰다        서빙 랭킹은 PgVectorDenseRetriever(Supabase document_chunks.embedding)다.
                  로컬 build_units() + DenseRetriever 로 재면 다른 값이 나온다 — DB 색인은
                  08-18 자라 FAQ B+C 포맷(a90360e, 08-20)이 안 들어가 있다(DB 에 '열기'
                  포함 청크 83개 잔존). 그래서 운영과 같은 route_search_chunks() 를 쓴다.
Gate 1·2 생존분   OOS 제거율의 분모는 Gate 1·2 를 **통과한** 질문이다. 안 그러면 Gate 2 가
                  이미 한 일을 이 게이트 실적으로 중복 계상해 임계값이 과하게 높아진다.
인접도메인 제외   인접 금융 도메인(투자·대출·타기관 등)은 top-1 점수가 높아 점수로 안 갈린다
                  (기존 기록: 중앙값 0.512). 성공 대상이 아니라 **참고 지표**로만 싣는다.
                  그 몫은 Gate 2 와 생성 후 source_check 다.

── 지표 ────────────────────────────────────────────────────────────────────────────────
인스코프 오차단(strict)  정답 근거를 실제로 **들고 있었는데도** 비운 비율. 검색이 이미
                         실패한(정답 청크가 top-k 에 없는) 질문이 비는 것은 게이트의 잘못이
                         아니라 정상 동작이므로 분모에서 뺀다. 정답 라벨이 있는 풀
                         (retrieval_eval_v1 / testset_pipeline 인스코프)에서만 계산한다.
인스코프 근거 비움       정답 라벨이 없는 풀(gate2 clear_in / boundary_in)까지 포함한 총량.
OOS 근거 제거(생존분)    Gate 1·2 를 통과한 무관 질문 중 근거가 빈 비율 — 이 게이트의 실적.

선택 원칙(코드 철학 유지): 인스코프 오차단 0 인 후보만 남기고, 그중 OOS 제거율이 가장 높은
값. 다만 그 규칙은 선택값을 **min(인스코프 top-1) 하나로 완전히 결정**하므로(0.01 격자는
곡선을 그릴 때만 의미가 있다) 최종값은 "최저 인스코프 점수 ~ 최고 OOS 점수" 갭의 중간을
잡아 관리자 슬라이더 격자(0.05, api/routers/admin_rag_params.py)에 스냅한다 — 0.35 도
그렇게 정해진 값이다. 뒤집힌 질문 목록은 사람이 직접 보라고 리포트에 그대로 싣는다.

    python src/crawler/min_top1_threshold_search.py
    python src/crawler/min_top1_threshold_search.py --reuse-scores   # 임베딩 생략, 스윕만

점수 수집은 data/results/min_top1_scores.json 에 캐시된다 — 임계값 스윕은 재수집 없이
몇 번이든 다시 돌릴 수 있다. 색인·청킹·검색 모델이 바뀌면 캐시를 지우고 다시 수집할 것.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

TESTSET_DIR = ROOT / "data" / "testset"
RESULTS_DIR = ROOT / "data" / "results"
SCORES_PATH = RESULTS_DIR / "min_top1_scores.json"
REPORT_PATH = RESULTS_DIR / "min_top1_threshold_search.json"

# 성공 대상에서 제외하는 OOS 범주 — 점수로 안 갈리는 것이 이미 확인된 부류.
ADJACENT = "인접도메인"


# ── 평가셋 적재 ────────────────────────────────────────────────────────────────────────

def _read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _pipeline_oos_category(note: str) -> str:
    """testset_pipeline 의 out_of_scope 10건을 gate2 평가셋과 같은 범주 어휘로 맞춘다.
    '금감원 소관'·'금융이지만 KDIC 업무 아님'은 인접도메인이라 성공 대상에서 빠진다."""
    if "금감원" in note or "금융이지만" in note:
        return ADJACENT
    if "인사말" in note:
        return "인사말"
    if "의미없는" in note or "공백" in note:
        return "무의미입력"
    if "잡담" in note:
        return "일상잡담"
    return "기타범위밖"


def load_pools():
    """(인스코프, 무관) 두 리스트. 각 행: dict(question, pool, group, category,
    answer_pages, answer_chunks). 같은 질문이 여러 셋에 있으면 처음 것만 남긴다."""
    in_scope, oos, seen = [], [], set()

    def add(bucket, row):
        if row["question"] in seen:
            return
        seen.add(row["question"])
        bucket.append(row)

    # 정답 청크 라벨이 있는 홀드아웃 — 진짜 오차단률은 여기서만 계산된다.
    for r in _read_jsonl(TESTSET_DIR / "testset_retrieval_eval_v1.jsonl"):
        add(in_scope, {"question": r["question"], "pool": "retrieval_v1",
                       "group": r.get("question_type", ""), "category": "",
                       "answer_pages": r.get("expected_sources") or [],
                       "answer_chunks": r.get("answer_chunk_ids") or []})

    for r in _read_jsonl(TESTSET_DIR / "testset_pipeline.jsonl"):
        if r.get("expected_sources"):
            add(in_scope, {"question": r["question"], "pool": "pipeline_in",
                           "group": r.get("question_type", ""), "category": "",
                           "answer_pages": r["expected_sources"], "answer_chunks": []})
        else:
            add(oos, {"question": r["question"], "pool": "pipeline_oos", "group": "out_of_scope",
                      "category": _pipeline_oos_category(r.get("note", "")),
                      "answer_pages": [], "answer_chunks": []})

    # Gate 2 held-out — boundary_in_domain 38건이 인스코프 꼬리(짧은 파편·오타·구어체·
    # 단일 키워드)라 min(인스코프 top-1)을 실제로 결정하는 그룹이다.
    for r in _read_jsonl(TESTSET_DIR / "testset_gate2_domain_eval.jsonl"):
        group = r["group"]
        # note 는 "인접도메인/투자 / 금융 어휘, 투자 상담" 또는 "예금자보호제도 / 짧은 파편 질의"
        head = (r.get("note") or "").split("/")[0].strip()
        row = {"question": r["question"], "pool": "gate2_eval", "group": group,
               "category": head, "answer_pages": [], "answer_chunks": []}
        add(oos if group.endswith("out_domain") else in_scope, row)

    return in_scope, oos


# ── 점수 수집 ──────────────────────────────────────────────────────────────────────────

def collect_scores(rows):
    """운영과 동일한 경로로 각 질문의 top-1 점수와 Gate 1·2 판정을 모은다.

    검색은 route_search_chunks(DB) → top_k_cut 로, api/rag/answer.prepare_sub 및
    pipeline._answer_one 이 게이트 직전까지 하는 것과 같다. 리랭커는 현행 운영값 그대로
    끈 상태(USE_RERANKER=False)를 전제한다 — 켜면 게이트가 보는 점수가 코사인이 아니라
    cross-encoder 점수가 되어 이 실험의 임계값이 통째로 무의미해진다."""
    from candidate_ranking import top_k_cut
    from gate1 import run_gate1
    from gate2 import run_gate2
    from pipeline import K_CANDIDATES, K_FINAL
    from retrieval import route_search_chunks

    out = []
    for i, row in enumerate(rows, 1):
        q = row["question"]
        rec = dict(row)

        g1 = run_gate1(q)
        rec["gate1"] = g1.action
        rec["gate1_label"] = g1.label
        if g1.action == "CONTINUE":
            g2 = run_gate2(q)
            rec["gate2"] = g2.action
            rec["gate2_s_id"] = g2.s_id
            rec["gate2_s_ood"] = g2.s_ood
        else:
            rec["gate2"] = "SKIPPED"
            rec["gate2_s_id"] = rec["gate2_s_ood"] = None
        rec["survived_gates"] = rec["gate1"] == "CONTINUE" and rec["gate2"] == "CONTINUE"

        # 게이트에서 끝난 질문도 점수를 같이 남긴다 — "게이트가 없었다면 어땠나"를 보려면
        # 필요하고, 분모에서 빼는 것은 집계 단계에서 한다.
        # ⚠️ 그래서 아래 top1_score/top_pages 는 게이트가 EXIT 한 질문에서는 **실제로 일어난
        # 일이 아니다**(운영은 Gate 1·2 EXIT 시 검색을 아예 안 돈다). 실제 실행 여부는 이
        # 필드로 판단할 것 — 필드명만 보고 실측으로 오해한 사례가 있었다(2026-08-25).
        rec["retrieval_actually_ran"] = rec["survived_gates"]
        try:
            top = top_k_cut(route_search_chunks(q, k=K_CANDIDATES), k=K_FINAL)
        except Exception as e:  # noqa: BLE001 — 빈 입력 등은 점수 없음으로 남기고 계속
            print(f"  ! 검색 실패({q!r}): {type(e).__name__}: {e}", file=sys.stderr)
            top = []
        rec["top1_score"] = float(top[0][1]) if top else None
        rec["top_chunk_ids"] = [cid for cid, _, _ in top]
        rec["top_pages"] = [cid.split("#")[0] for cid, _, _ in top]

        # 정답을 실제로 들고 있었나 — 청크 라벨이 있으면 청크로, 없으면 페이지로 판정.
        if rec["answer_chunks"]:
            rec["answer_present"] = bool(set(rec["answer_chunks"]) & set(rec["top_chunk_ids"]))
        elif rec["answer_pages"]:
            rec["answer_present"] = bool(set(rec["answer_pages"]) & set(rec["top_pages"]))
        else:
            rec["answer_present"] = None      # 라벨 없음 — strict 오차단 분모에서 제외

        out.append(rec)
        if i % 20 == 0:
            print(f"  ... {i}/{len(rows)}")
    return out


# ── 스윕 ───────────────────────────────────────────────────────────────────────────────

def _rate(hits, n):
    return round(hits / n, 4) if n else None


def sweep(in_scope, oos, start, end, step):
    """임계값별 지표. 점수가 None(검색 실패)인 행은 '근거 비움'으로 센다 — 실제로 게이트
    이전에 이미 근거가 없는 상태이므로."""
    def emptied(rec, t):
        return rec["top1_score"] is None or rec["top1_score"] < t

    strict_pool = [r for r in in_scope if r["answer_present"] is True]
    # 경계 인스코프(짧은 파편·오타·구어체·단일 키워드) — 정답 라벨이 없어 strict 분모에
    # 안 들어가지만, 근거가 비면 실제 고객 질문이 답을 못 받는다. strict 만 보면 이 그룹의
    # 손실이 통째로 안 보인다(2026-08-25 실측: 0.47 까지 strict 오차단 0인데 이 그룹은 8건 손실).
    boundary_pool = [r for r in in_scope if r["group"] == "boundary_in_domain"]
    oos_alive = [r for r in oos if r["survived_gates"]]
    oos_target = [r for r in oos_alive if r["category"] != ADJACENT]
    oos_adjacent = [r for r in oos_alive if r["category"] == ADJACENT]

    groups = sorted({r["pool"] for r in in_scope})
    rows, prev_state = [], None
    thresholds = [round(start + i * step, 4)
                  for i in range(int(round((end - start) / step)) + 1)]

    for t in thresholds:
        state = {r["question"]: emptied(r, t) for r in in_scope + oos}
        flipped = ([] if prev_state is None
                   else sorted(q for q, v in state.items() if prev_state.get(q) != v))
        entry = {
            "threshold": t,
            "in_scope_false_block_rate": _rate(sum(emptied(r, t) for r in strict_pool),
                                               len(strict_pool)),
            "in_scope_false_blocks": sum(emptied(r, t) for r in strict_pool),
            "in_scope_emptied": sum(emptied(r, t) for r in in_scope),
            "in_scope_emptied_rate": _rate(sum(emptied(r, t) for r in in_scope), len(in_scope)),
            "boundary_in_emptied": sum(emptied(r, t) for r in boundary_pool),
            "boundary_in_emptied_rate": _rate(sum(emptied(r, t) for r in boundary_pool),
                                              len(boundary_pool)),
            "in_scope_emptied_by_pool": {
                g: _rate(sum(emptied(r, t) for r in in_scope if r["pool"] == g),
                         sum(1 for r in in_scope if r["pool"] == g)) for g in groups},
            "oos_cleared_rate": _rate(sum(emptied(r, t) for r in oos_target), len(oos_target)),
            "oos_cleared": sum(emptied(r, t) for r in oos_target),
            "oos_adjacent_cleared_rate": _rate(sum(emptied(r, t) for r in oos_adjacent),
                                               len(oos_adjacent)),
            "flipped": flipped,
        }
        rows.append(entry)
        prev_state = state

    return rows, {"strict_n": len(strict_pool), "boundary_in_n": len(boundary_pool),
                  "in_scope_n": len(in_scope), "oos_target_n": len(oos_target),
                  "oos_adjacent_n": len(oos_adjacent), "oos_alive_n": len(oos_alive)}


def main():
    ap = argparse.ArgumentParser(description="MIN_TOP1_SCORE 임계값 재탐색")
    ap.add_argument("--start", type=float, default=0.20)
    ap.add_argument("--end", type=float, default=0.50)
    ap.add_argument("--step", type=float, default=0.01)
    ap.add_argument("--reuse-scores", action="store_true",
                    help="이전 수집 결과(min_top1_scores.json)를 그대로 쓰고 스윕만 다시 한다")
    args = ap.parse_args()
    if args.step <= 0 or args.end < args.start:
        ap.error("--step 은 양수, --end 는 --start 이상이어야 합니다.")

    if args.reuse_scores and SCORES_PATH.exists():
        cached = json.loads(SCORES_PATH.read_text(encoding="utf-8"))
        in_scope, oos = cached["in_scope"], cached["oos"]
        print(f"점수 캐시 재사용: {SCORES_PATH.relative_to(ROOT)}")
    else:
        raw_in, raw_oos = load_pools()
        print(f"평가셋: 인스코프 {len(raw_in)}건 / 무관 {len(raw_oos)}건 — 점수 수집 시작")
        print("[인스코프]")
        in_scope = collect_scores(raw_in)
        print("[무관]")
        oos = collect_scores(raw_oos)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        SCORES_PATH.write_text(
            json.dumps({"in_scope": in_scope, "oos": oos}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"점수 저장: {SCORES_PATH.relative_to(ROOT)}")

    grid, sizes = sweep(in_scope, oos, args.start, args.end, args.step)

    # 분리 가능성. ⚠️ 정답 라벨이 있는 풀만 보면 안 된다 — 그 풀은 잘 만들어진 질문이라
    # 점수가 높고, 실제 꼬리(경계 인스코프)는 라벨이 없어 분모에서 빠진다. 라벨 있는 풀로만
    # 재면 "분리 가능"이 나오지만 전 풀 기준으로는 겹친다(2026-08-25 실측).
    strict_scores = [r["top1_score"] for r in in_scope
                     if r["answer_present"] is True and r["top1_score"] is not None]
    all_scores = [r["top1_score"] for r in in_scope if r["top1_score"] is not None]
    alive_target = [r for r in oos if r["survived_gates"] and r["category"] != ADJACENT]
    target_scores = [r["top1_score"] for r in alive_target if r["top1_score"] is not None]
    min_in_strict = min(strict_scores) if strict_scores else None
    min_in_all = min(all_scores) if all_scores else None
    max_oos = max(target_scores) if target_scores else None

    print(f"\n분모: 인스코프 전체 {sizes['in_scope_n']}건"
          f"(정답보유 {sizes['strict_n']} / 경계 {sizes['boundary_in_n']}) · "
          f"게이트 생존 무관 {sizes['oos_alive_n']}건"
          f"(성공대상 {sizes['oos_target_n']} / 인접도메인 {sizes['oos_adjacent_n']})")
    print(f"인스코프 top-1 최솟값: 정답보유 {min_in_strict:.4f} / **전 풀 {min_in_all:.4f}**")
    print(f"무관(생존·성공대상) top-1 최댓값: {max_oos:.4f}")
    if min_in_all is not None and max_oos is not None:
        gap = min_in_all - max_oos
        print(f"전 풀 갭: {gap:+.4f}  → " + ("분리 가능" if gap > 0 else
              "⚠️ 분리 불가 — 인스코프 근거를 하나도 안 잃으면서 무관을 다 비우는 임계값은 없다"))

    print("\n=== 임계값 스윕 ===")
    print(f"{'임계값':>6} {'오차단(라벨)':>12} {'경계 손실':>10} {'인스코프 손실계':>13} "
          f"{'무관 제거(생존)':>15} {'인접(참고)':>10}")
    for e in grid:
        mark = " ←현행" if abs(e["threshold"] - 0.35) < 1e-9 else ""
        print(f"{e['threshold']:>6.2f} {e['in_scope_false_blocks']:>7}건 "
              f"{e['boundary_in_emptied']:>7}/{sizes['boundary_in_n']} "
              f"{e['in_scope_emptied']:>8}건 {(e['in_scope_emptied_rate'] or 0):>5.1%} "
              f"{e['oos_cleared']:>7}/{sizes['oos_target_n']} "
              f"{(e['oos_cleared_rate'] or 0):>6.1%} "
              f"{(e['oos_adjacent_cleared_rate'] or 0):>9.1%}{mark}")

    # 두 선택 규칙을 나란히 낸다 — 둘이 갈리는 것 자체가 이번 실험의 결과다.
    #   strict : 라벨 있는 풀만 본다(= 기존 0.35 를 정할 때 쓴 기준). 꼬리를 못 본다.
    #   전 풀  : 경계 인스코프까지 포함해 근거 손실이 0 인 최대값. 이쪽이 설계 의도에 맞다.
    def _pick(rows, label):
        if not rows:
            print(f"  {label}: 스윕 범위에 없음")
            return None
        best = max(rows, key=lambda e: (e["oos_cleared_rate"] or 0, e["threshold"]))
        snapped = round(round(best["threshold"] / 0.05) * 0.05, 2)
        row = next((e for e in grid if abs(e["threshold"] - snapped) < 1e-9), None)
        print(f"  {label}: 최대 {best['threshold']:.2f} (무관 제거 {best['oos_cleared_rate']:.1%})"
              f" → 0.05 격자 {snapped:.2f}" + (
                  f" [경계 손실 {row['boundary_in_emptied']}건, 무관 제거 "
                  f"{row['oos_cleared_rate']:.1%}]" if row else ""))
        return snapped

    print("\n=== 선택 후보 ===")
    pick_strict = _pick([e for e in grid if e["in_scope_false_blocks"] == 0], "라벨 풀 오차단 0")
    pick_all = _pick([e for e in grid if e["in_scope_emptied"] == 0], "전 풀 근거 손실 0")
    recommended = pick_all if pick_all is not None else pick_strict

    current = next((e for e in grid if abs(e["threshold"] - 0.35) < 1e-9), None)
    payload = {
        "decision_rule": "evidence_cleared = (top1_score < threshold)",
        "selection_policy": "인스코프 근거 손실(경계 포함 전 풀) 0 우선 → 무관(게이트 생존·인접도메인 제외) 제거율 최대 → 0.05 격자 스냅",
        "index_note": "DB(document_chunks) 2026-08-18 색인 · 프리픽스 O · FAQ B+C 미반영 · USE_RERANKER=False",
        "pool_sizes": sizes,
        "in_scope_min_top1_labeled": min_in_strict,
        "in_scope_min_top1_all": min_in_all,
        "oos_target_max_top1": max_oos,
        "separable": (None if min_in_all is None or max_oos is None else min_in_all > max_oos),
        "separable_labeled_only": (None if min_in_strict is None or max_oos is None
                                   else min_in_strict > max_oos),
        "recommended_threshold_labeled_rule": pick_strict,
        "current_threshold": 0.35,
        "current_metrics": current,
        "recommended_threshold": recommended,
        "in_scope_pool_counts": dict(Counter(r["pool"] for r in in_scope)),
        "oos_category_counts": dict(Counter(r["category"] for r in oos)),
        "gate_survival": {
            "oos_gate1_exit": sum(1 for r in oos if r["gate1"] == "EXIT"),
            "oos_gate2_exit": sum(1 for r in oos if r["gate2"] == "EXIT"),
            "in_scope_gate_exit": sum(1 for r in in_scope if not r["survived_gates"]),
        },
        "grid": grid,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n리포트 저장: {REPORT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
