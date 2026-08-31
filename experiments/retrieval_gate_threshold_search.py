"""검색 관련도 게이트(candidate_ranking.MIN_TOP1_SCORE) 임계값 재측정.

배경: MIN_TOP1_SCORE=0.35는 2026-08-10에 도출됐다(candidate_ranking.py 주석). 그런데
retrieval.USE_TYPE_ROUTING이 2026-08-19부터 기본 False로 바뀌어(라우팅 컬럼이 아니라
retrieval.py:273 주석 참고), link_guide까지 포함해 1차 검색이 전부 Dense로 통일됐다.
0.35 도출 시점엔 라우팅이 살아있어 link_guide 문항은 Hybrid(RRF) 점수를 썼을 수 있는데,
RRF 점수와 Dense 코사인 유사도는 스케일이 다르므로 지금 분포에서 0.35가 여전히 맞는
경계인지 재확인해야 한다. 이 스크립트는 route_search_chunks()를 실서비스(answer.prepare_sub /
pipeline._answer_one)와 완전히 같은 함수로 그대로 호출해 괴리 없이 재측정한다.

2026-08-25 2차 개정: 1차판(positive 119 / negative 45)은 표본이 너무 작고, 게다가 그
표본의 최솟값(0.473)에 threshold를 그대로 붙여(0.47) 안전 마진이 전혀 없었다. 이 파이프라인은
Gate1→Gate2→이 게이트→source_check 사후검증으로 이어지는 '여러 게이트가 나눠서 조금씩
깎는' soft cascade 설계다 — 그런데 이 게이트 혼자 negative recall을 최대화하려 최솟값까지
밀어붙이면 설계 의도와 어긋난다. 더 결정적으로, 이 파이프라인엔 비대칭이 있다:
  - 근거를 잘못 살려둬도(false pass) → source_check 사후검증이 한 번 더 거른다(복구 가능).
  - 근거를 잘못 박탈하면(false block) → gate_low_relevance가 top=[]로 비우는 순간 뒤의
    어떤 게이트도 되살릴 수 없다(복구 불가능, NO_EVIDENCE_NOTICE로 직행).
그래서 이번엔 (a) 표본을 크게 늘리고 (b) 표본의 안전 경계(T_edge, positive 오차단이 0인
최대 threshold)를 구한 뒤 거기서 SAFETY_MARGIN만큼 더 낮춰서 추천한다 — 표본이 못 담은
더 낮은 점수의 정상 질문이 실제로 존재할 위험에 대비한 여유다.

데이터셋(새로 안 만들고 기존 testset 재사용, 1차판보다 positive 7배·negative 1.5배 확대):
  POSITIVE(반드시 통과해야 함, 오차단 0이 하드 제약):
    - testset_all.jsonl 중 question_type != "out_of_scope"(817) — 팀 전원이 만든
      testset_dy/hw/jh/jy/yj + testset_ambiguous를 합친 마스터 테스트셋. 내가 새로
      질문을 지어내지 않고 이미 라벨링된 실데이터를 그대로 쓴다(지난번 testset_pipeline.jsonl의
      out_of_scope 컨트롤 문항을 못 보고 positive에 잘못 섞었던 실수를 반복하지 않으려
      question_type을 반드시 확인한다).
    - testset_gate2_domain_eval.jsonl 의 clear_in_domain(40)
  NEGATIVE(차단돼야 함, 재현율은 참고 지표일 뿐 — positive 안전이 우선):
    - testset_all.jsonl 중 question_type == "out_of_scope"(32)
    - testset_gate2_domain_eval.jsonl 의 clear_out_domain(35)
  boundary_in_domain/boundary_out_domain(68)은 참고용으로만 점수를 찍는다 — 0.35 최초
  도출 주석에 이미 "도메인 인접 범위외는 이 게이트가 아니라 source_check 사후 판정이
  맡는다"고 명시돼 있어, 임계값 결정(그리드서치 제약·점수)에는 넣지 않는다(같은 설계 철학 유지).

결정 규칙(candidate_ranking.gate_low_relevance와 동일): score < threshold 면 근거를 통째로 비운다.

실행: python3 experiments/retrieval_gate_threshold_search.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # experiments/ -> 리포 루트
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "crawler"))

import numpy as np  # noqa: E402

from retrieval import route_search_chunks  # noqa: E402

ALL_TESTSET_PATH = ROOT / "data" / "testset" / "testset_all.jsonl"
GATE2_TESTSET_PATH = ROOT / "data" / "testset" / "testset_gate2_domain_eval.jsonl"
REPORT_PATH = ROOT / "data" / "eval_cache" / "retrieval_gate_threshold_report.json"

# api/rag/answer.py K_CANDIDATES와 동일 — 실서비스가 1차 검색에 넘기는 k
K_CANDIDATES = 20

CURRENT_THRESHOLD = 0.35
THRESHOLD_GRID = np.round(np.arange(0.20, 0.56, 0.01), 2)
# T_edge(positive 오차단 0인 최댓값)에서 이만큼 더 내려서 추천한다 — 표본이 못 담은 더 낮은
# 점수의 정상 질문이 있을 위험에 대비한 안전 마진(1차판이 마진 0으로 T_edge를 그대로 썼던 것에
# 대한 정정). 값 자체에 통계적 근거는 없다 — "이 게이트 혼자 완벽을 노리지 않는다"는 설계
# 판단을 수치로 표현한 것뿐이다.
SAFETY_MARGIN = 0.05


def _load_jsonl(path):
    recs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def _top1_score(question: str) -> float:
    """실서비스와 같은 route_search_chunks() 호출 — 후보가 비면(사실상 없음) -1.0."""
    candidates = route_search_chunks(question, k=K_CANDIDATES)
    return float(candidates[0][1]) if candidates else -1.0


def _build_population():
    """{group_name: [(question, score), ...]} — group_name 은 아래 6종."""
    all_ts = _load_jsonl(ALL_TESTSET_PATH)
    gate2 = _load_jsonl(GATE2_TESTSET_PATH)

    # 중복 질문 제거(테스트셋 여러 개를 합치면 같은 문장이 겹칠 수 있다) — group별로 first-seen만.
    def _dedup(questions):
        seen = set()
        out = []
        for q in questions:
            if q not in seen:
                seen.add(q)
                out.append(q)
        return out

    pop = {
        "all_positive": _dedup([r["question"] for r in all_ts if r["question_type"] != "out_of_scope"]),
        "all_out_of_scope": _dedup([r["question"] for r in all_ts if r["question_type"] == "out_of_scope"]),
        "clear_in_domain": _dedup([r["question"] for r in gate2 if r["group"] == "clear_in_domain"]),
        "clear_out_domain": _dedup([r["question"] for r in gate2 if r["group"] == "clear_out_domain"]),
        "boundary_in_domain": _dedup([r["question"] for r in gate2 if r["group"] == "boundary_in_domain"]),
        "boundary_out_domain": _dedup([r["question"] for r in gate2 if r["group"] == "boundary_out_domain"]),
    }
    scored = {}
    total = sum(len(v) for v in pop.values())
    done = 0
    for group, questions in pop.items():
        rows = []
        for q in questions:
            rows.append({"question": q, "score": _top1_score(q)})
            done += 1
            if done % 20 == 0 or done == total:
                print(f"  [{done}/{total}] 검색 완료...")
        scored[group] = rows
    return scored


def main():
    print("=== 1차 검색 top-1 점수 재측정 (route_search_chunks, 실서비스와 동일 함수) ===")
    scored = _build_population()
    print()

    POSITIVE_GROUPS = ["all_positive", "clear_in_domain"]
    NEGATIVE_GROUPS = ["all_out_of_scope", "clear_out_domain"]
    REFERENCE_ONLY_GROUPS = ["boundary_in_domain", "boundary_out_domain"]

    for g, rows in scored.items():
        vals = [r["score"] for r in rows]
        print(f"{g:20} n={len(vals):3d}  min={min(vals):.3f}  median={float(np.median(vals)):.3f}  "
              f"max={max(vals):.3f}")
    print()

    # 그룹 간 중복(같은 질문이 all_positive와 clear_in_domain 등에 겹칠 수 있음) 제거 후 통계
    def _pooled(group_names):
        seen = {}
        for g in group_names:
            for r in scored[g]:
                seen.setdefault(r["question"], r["score"])  # first-seen 점수 유지
        return [{"question": q, "score": s} for q, s in seen.items()]

    positive_pool = _pooled(POSITIVE_GROUPS)
    negative_pool = _pooled(NEGATIVE_GROUPS)
    pos_scores = sorted(r["score"] for r in positive_pool)
    print(f"POSITIVE 풀(중복 제거) n={len(positive_pool)}  "
          f"min={pos_scores[0]:.3f}  p1={float(np.percentile(pos_scores, 1)):.3f}  "
          f"p5={float(np.percentile(pos_scores, 5)):.3f}  median={float(np.median(pos_scores)):.3f}")
    print(f"NEGATIVE 풀(중복 제거) n={len(negative_pool)}")
    print()

    def _false_block(pool, T):
        return [r for r in pool if r["score"] < T]

    def _blocked_count(pool, T):
        return sum(1 for r in pool if r["score"] < T)

    # ---- 현재 0.35의 실측 성능(재측정이 왜 필요한지 직접 증거) ----
    fb_now = _false_block(positive_pool, CURRENT_THRESHOLD)
    blk_now = _blocked_count(negative_pool, CURRENT_THRESHOLD)
    print(f"=== 현재 threshold={CURRENT_THRESHOLD} 실측 ===")
    print(f"positive 오차단: {len(fb_now)}건 / {len(positive_pool)}건")
    for r in fb_now[:20]:
        print(f"  ❌ \"{r['question']}\"  score={r['score']:.3f}")
    if len(fb_now) > 20:
        print(f"  ... 외 {len(fb_now) - 20}건")
    print(f"negative 차단율: {blk_now}/{len(negative_pool)} ({blk_now/len(negative_pool):.1%})")
    print()

    # ---- 그리드서치: T_edge = positive 오차단 0인 최댓값. 재현율 최대화가 목적이 아니라
    #      "이 이상 올리면 위험해지는 지점"을 찾는 것만이 목적이다(설계 원칙: 이 게이트는
    #      negative를 최대한 잡는 게 아니라 positive를 안전하게 보존하는 게 우선이다).
    rows = []
    for T in THRESHOLD_GRID:
        fb = len(_false_block(positive_pool, T))
        blk = _blocked_count(negative_pool, T)
        rows.append({
            "threshold": float(T),
            "positive_false_block": fb,
            "positive_total": len(positive_pool),
            "negative_blocked": blk,
            "negative_total": len(negative_pool),
            "negative_recall": blk / len(negative_pool) if negative_pool else 0.0,
        })

    zero_fp = [r for r in rows if r["positive_false_block"] == 0]
    if not zero_fp:
        rows.sort(key=lambda r: r["positive_false_block"])
        edge = rows[0]
        print(f"⚠ positive 오차단 0을 만족하는 threshold가 그리드 내에 없음 — "
              f"최소 오차단 threshold={edge['threshold']:.2f} "
              f"({edge['positive_false_block']}건). 코퍼스·청킹 쪽 원인 점검 필요.")
        recommended_T = edge["threshold"]
    else:
        zero_fp.sort(key=lambda r: r["threshold"], reverse=True)
        edge = zero_fp[0]  # T_edge: positive 오차단 0을 유지하는 최댓값
        recommended_T = round(max(0.0, edge["threshold"] - SAFETY_MARGIN), 2)
        rec_row = min(rows, key=lambda r: abs(r["threshold"] - recommended_T))
        print(f"T_edge(positive 오차단 0인 최댓값) = {edge['threshold']:.2f} "
              f"(negative 차단율 {edge['negative_recall']:.1%}) — 1차판은 이 값을 마진 없이 그대로 썼다.")
        print(f"=== 추천 threshold = T_edge - {SAFETY_MARGIN} = {recommended_T:.2f} "
              f"(positive 오차단 {rec_row['positive_false_block']}/{rec_row['positive_total']}, "
              f"negative 차단율 {rec_row['negative_recall']:.1%}) ===")
    print()

    T = recommended_T
    # ---- 추천 threshold에서 positive 오차단 재확인(마진을 뒀어도 혹시 몰라 재검) ----
    fb_rec = _false_block(positive_pool, T)
    print(f"=== 추천 threshold={T:.2f}에서 positive 오차단 재확인 — {len(fb_rec)}건 ===")
    for r in fb_rec:
        print(f"  ❌ \"{r['question']}\"  score={r['score']:.3f}")
    if not fb_rec:
        print("  없음")
    print()

    # ---- 추천 threshold에서 negative 오탐(=차단 실패) 목록 ----
    miss = [r for r in negative_pool if r["score"] >= T]
    print(f"=== negative 중 threshold={T:.2f}에서도 안 걸리는 문항 — {len(miss)}건 ===")
    for r in sorted(miss, key=lambda r: -r["score"])[:20]:
        print(f"  \"{r['question']}\"  score={r['score']:.3f}")
    if len(miss) > 20:
        print(f"  ... 외 {len(miss) - 20}건")
    if not miss:
        print("  없음")
    print()

    # ---- 참고용: boundary 그룹은 결정에 안 쓰지만 분포는 남긴다 ----
    for g in REFERENCE_ONLY_GROUPS:
        blk = _blocked_count(scored[g], T)
        total = len(scored[g])
        print(f"(참고) {g} threshold={T:.2f} 기준 차단율: {blk}/{total} ({blk/total:.1%}) "
              f"— 이 게이트의 결정 대상 아님(설계상 source_check 사후 판정이 담당)")
    print()

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps({
        "current_threshold": CURRENT_THRESHOLD,
        "current_threshold_positive_false_block": [r["question"] for r in fb_now],
        "current_threshold_negative_recall": blk_now / len(negative_pool) if negative_pool else 0.0,
        "threshold_edge_zero_false_block": edge["threshold"],
        "safety_margin": SAFETY_MARGIN,
        "recommended_threshold": recommended_T,
        "recommended_threshold_positive_false_block": len(fb_rec),
        "grid": rows,
        "scored": scored,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"리포트 저장: {REPORT_PATH}")


if __name__ == "__main__":
    main()
