"""복합 질문 분해(query_decomposer.decompose_query) 품질 평가.

기존 eval_intent_*.py와 달리 "정답 라벨과 비교"가 아니라 "요구사항이 안 빠지고 보존됐는가"를
본다 — LLM이 매번 표현을 조금씩 바꿔 써도(예: "예금보험금은 어떻게 신청하나요?" vs "예금보험금
신청 방법은 어떻게 되나요?") 정답으로 쳐야 하므로, 문장 전체를 정확히 맞히는 대신 각
expected_items[i].must_include 키워드가 출력 어딘가에 다 들어있는지만 확인한다.

측정 항목(테스트셋 case_type별로도 나눠서):
- false_split_rate: 안 쪼개야 할 질문(should_split=false)을 쪼갠 비율 — 지난 실패 케이스(dq_004)
  같은 과잉분해를 잡는 지표
- under_split_rate: 쪼개야 할 질문(should_split=true)을 안 쪼갠 비율
- count_match_rate: 출력 개수가 expected_items 개수와 일치한 비율
- item_missing_rate: expected_items 중 어느 출력 줄에서도 커버 안 된 항목의 비율
- split_decision_stability: 같은 질문을 REPEATS번 반복했을 때 쪼갤지 말지 판단이 매번
  동일했던 케이스의 비율(LLM이 결정론적이지 않아서 — temperature=0.2) 흔들리는 정도.

테스트셋은 difficulty(easy/hard) 축도 갖는다 - easy는 few-shot과 비슷한 정형 문장,
hard는 오타·반말·서사형 조건문·동의어 함정·부정 함정·스코프 밖 절 포함 등 실사용자 말투에
가까운 케이스라 easy만 볼 때보다 훨씬 엄격하게 잡힌다(전체 평균만 보면 쉬운 케이스에 묻혀
실제 약점을 놓치므로 by_difficulty로 반드시 hard만 따로 확인할 것).

REPEATS번 실제 HyperCLOVA 호출을 케이스마다 반복하므로 38문항 × 3회 = 114회 호출, 수십 분 걸림.
결과는 data/query_decomposition_eval_result.json.
실행: python3 experiments/eval_query_decomposition.py
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # experiments/ -> 리포 루트
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "src" / "crawler"))

from query_decomposer import decompose_query  # noqa: E402
TESTSET = ROOT / "data" / "testset" / "testset_query_decomposition.jsonl"
OUT_RESULT = ROOT / "data" / "query_decomposition_eval_result.json"
REPEATS = 3


def load_testset():
    with open(TESTSET, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def match_items(output_lines, expected_items):
    """expected_items 각각을 아직 안 쓴 output_lines 중 must_include 키워드를 전부 포함하는
    줄에 그리디로 매칭한다. 반환: (matched_count, missing_items)."""
    used = set()
    missing = []
    for item in expected_items:
        kws = item["must_include"]
        hit = None
        for i, line in enumerate(output_lines):
            if i in used:
                continue
            if all(kw in line for kw in kws):
                hit = i
                break
        if hit is not None:
            used.add(hit)
        else:
            missing.append(kws)
    return len(expected_items) - len(missing), missing


def evaluate_case(row):
    runs = [decompose_query(row["question"]) for _ in range(REPEATS)]
    expected_n = len(row["expected_items"])
    per_run = []
    for output_lines in runs:
        matched, missing = match_items(output_lines, row["expected_items"])
        per_run.append({
            "output": output_lines,
            "n_out": len(output_lines),
            "split_flag": len(output_lines) > 1,
            "count_match": len(output_lines) == expected_n,
            "matched": matched,
            "missing": missing,
        })
    split_flags = [r["split_flag"] for r in per_run]
    return {
        "test_id": row["test_id"],
        "case_type": row["case_type"],
        "difficulty": row["difficulty"],
        "should_split": row["should_split"],
        "runs": per_run,
        "split_stable": len(set(split_flags)) == 1,
        "majority_split_flag": sum(split_flags) > REPEATS / 2,
    }


def _group_metrics(cases, key_fn):
    """group_key(easy/hard 또는 case_type)별로 같은 지표를 계산하는 공통 로직.
    그룹 안에서 should_split이 섞여 있을 수 있으므로(예: difficulty='hard'는 단일·복합이
    다 있음) false_split/under_split 분모를 그룹 내에서 각각 따로 센다 — case_type처럼
    그룹이 should_split 하나로만 균일하다는 가정을 두지 않는다."""
    groups = defaultdict(lambda: {
        "n_cases": 0, "n_runs": 0,
        "should_not_split_runs": 0, "should_split_runs": 0,
        "false_split": 0, "under_split": 0, "count_match": 0,
        "total_items": 0, "matched_items": 0, "stable": 0,
    })
    for c in cases:
        g = groups[key_fn(c)]
        g["n_cases"] += 1
        g["n_runs"] += REPEATS
        if c["split_stable"]:
            g["stable"] += 1
        if not c["should_split"]:
            g["should_not_split_runs"] += REPEATS
        else:
            g["should_split_runs"] += REPEATS
        for r in c["runs"]:
            if not c["should_split"] and r["split_flag"]:
                g["false_split"] += 1
            if c["should_split"] and not r["split_flag"]:
                g["under_split"] += 1
            if r["count_match"]:
                g["count_match"] += 1
            g["total_items"] += r["matched"] + len(r["missing"])
            g["matched_items"] += r["matched"]

    return {
        k: {
            "n_cases": g["n_cases"],
            "n_runs": g["n_runs"],
            "false_split_rate": round(g["false_split"] / g["should_not_split_runs"], 4) if g["should_not_split_runs"] else None,
            "under_split_rate": round(g["under_split"] / g["should_split_runs"], 4) if g["should_split_runs"] else None,
            "count_match_rate": round(g["count_match"] / g["n_runs"], 4),
            "item_missing_rate": round(1 - g["matched_items"] / g["total_items"], 4) if g["total_items"] else None,
            "split_decision_stability": round(g["stable"] / g["n_cases"], 4),
        }
        for k, g in groups.items()
    }


def aggregate(cases):
    overall = _group_metrics(cases, lambda c: "overall")["overall"]
    overall["n_cases"] = len(cases)
    overall["total_runs"] = len(cases) * REPEATS
    return {
        **overall,
        "by_difficulty": _group_metrics(cases, lambda c: c["difficulty"]),
        "by_case_type": _group_metrics(cases, lambda c: c["case_type"]),
    }


def main():
    testset = load_testset()
    print(f"{len(testset)}문항 × {REPEATS}회 반복 = {len(testset) * REPEATS}회 HyperCLOVA 호출 시작…")

    cases = []
    for i, row in enumerate(testset, 1):
        print(f"  [{i}/{len(testset)}] {row['test_id']} ({row['case_type']}) 평가 중…")
        cases.append(evaluate_case(row))

    summary = aggregate(cases)

    print("\n=== 전체 요약 ===")
    print(f"오분해(false split)율: {summary['false_split_rate']*100:.1f}%  (안 쪼개야 할 질문을 쪼갠 비율)")
    print(f"과소분해(under split)율: {summary['under_split_rate']*100:.1f}%  (쪼개야 할 질문을 안 쪼갠 비율)")
    print(f"개수 일치율: {summary['count_match_rate']*100:.1f}%")
    print(f"요구사항 누락율: {summary['item_missing_rate']*100:.1f}%")
    print(f"분해 여부 판단 안정성({REPEATS}회 반복 일치): {summary['split_decision_stability']*100:.1f}%")

    print("\n=== difficulty별 (easy=few-shot과 비슷한 정형 문장 / hard=오타·반말·서사형·함정) ===")
    for d, m in summary["by_difficulty"].items():
        print(f"  {d:6} n={m['n_cases']:3} false_split={m['false_split_rate']}  under_split={m['under_split_rate']}  "
              f"count_match={m['count_match_rate']}  item_missing={m['item_missing_rate']}  "
              f"stability={m['split_decision_stability']}")

    print("\n=== case_type별 ===")
    for ct, m in summary["by_case_type"].items():
        print(f"  {ct:24} false_split={m['false_split_rate']}  under_split={m['under_split_rate']}  "
              f"count_match={m['count_match_rate']}  item_missing={m['item_missing_rate']}")

    unstable = [c["test_id"] for c in cases if not c["split_stable"]]
    if unstable:
        print(f"\n분해 여부가 반복마다 흔들린 케이스: {unstable}")

    OUT_RESULT.write_text(json.dumps({
        "summary": summary,
        "cases": cases,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n결과 저장: {OUT_RESULT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
