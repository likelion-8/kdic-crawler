"""Diagnose frozen held-out effects of canonical ontology assistance.

This is an audit only. It must not suggest or apply ranking changes based on the
held-out set it analyzes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

try:
    from .eval_canonical_ontology_assist import (
        ALIASES_PATH,
        ALIAS_DECISIONS_PATH,
        BASELINE_PATH,
        CANONICAL_PATH,
        OUTPUT_PATH as SHADOW_PATH,
        TESTSET_PATH,
        build_label_index,
        evaluate,
        load_json,
        load_rows,
    )
except ImportError:  # direct script execution
    from eval_canonical_ontology_assist import (
        ALIASES_PATH,
        ALIAS_DECISIONS_PATH,
        BASELINE_PATH,
        CANONICAL_PATH,
        OUTPUT_PATH as SHADOW_PATH,
        TESTSET_PATH,
        build_label_index,
        evaluate,
        load_json,
        load_rows,
    )


ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_PATH = ROOT / "results" / "ontology" / "canonical_assist_error_analysis.json"
REVIEW_PATH = ROOT / "ontology" / "review" / "CANONICAL_ASSIST_ERROR_ANALYSIS.md"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def first_gold_rank(pages: list[str], gold: set[str]) -> int | None:
    return next((index for index, page_id in enumerate(pages, 1) if page_id in gold), None)


def impact(baseline_rank: int | None, assisted_rank: int | None) -> str:
    baseline_score = baseline_rank if baseline_rank is not None else 6
    assisted_score = assisted_rank if assisted_rank is not None else 6
    if assisted_score < baseline_score:
        return "improved_first_gold_rank"
    if assisted_score > baseline_score:
        return "regressed_first_gold_rank"
    return "first_gold_rank_unchanged"


def evidence_relation(ontology_pages: list[str], gold: set[str]) -> str:
    ontology_set = set(ontology_pages)
    if not ontology_set:
        return "no_ontology_page"
    if not ontology_set & gold:
        return "non_gold_ontology_pages"
    if ontology_set <= gold:
        return "gold_only_ontology_pages"
    return "mixed_gold_and_non_gold_ontology_pages"


def build_analysis(shadow: dict) -> dict:
    changed_cases = []
    for row in shadow["per_question"]:
        if row["baseline_pages"] == row["assisted_pages"]:
            continue
        gold = set(row["gold"])
        baseline_rank = first_gold_rank(row["baseline_pages"], gold)
        assisted_rank = first_gold_rank(row["assisted_pages"], gold)
        changed_cases.append({
            "test_id": row["test_id"],
            "gold": row["gold"],
            "matched_labels": row["matched_labels"],
            "ontology_pages": row["ontology_pages"],
            "baseline_pages": row["baseline_pages"],
            "assisted_pages": row["assisted_pages"],
            "baseline_first_gold_rank": baseline_rank,
            "assisted_first_gold_rank": assisted_rank,
            "impact": impact(baseline_rank, assisted_rank),
            "ontology_evidence_relation": evidence_relation(row["ontology_pages"], gold),
        })
    changed_cases.sort(key=lambda item: item["test_id"])
    impact_counts = Counter(item["impact"] for item in changed_cases)
    relation_counts = Counter(item["ontology_evidence_relation"] for item in changed_cases)
    return {
        "schema_version": "1.0.0",
        "status": "diagnostic_only_frozen_heldout_no_tuning",
        "production_impact": "none",
        "llm_calls": 0,
        "database_calls": 0,
        "heldout_tuning": False,
        "source": {
            "testset": {"path": str(TESTSET_PATH.relative_to(ROOT)), "sha256": sha256(TESTSET_PATH)},
            "baseline": {"path": str(BASELINE_PATH.relative_to(ROOT)), "sha256": sha256(BASELINE_PATH)},
            "canonical_draft": {"path": str(CANONICAL_PATH.relative_to(ROOT)), "sha256": sha256(CANONICAL_PATH)},
            "official_aliases": {"path": str(ALIASES_PATH.relative_to(ROOT)), "sha256": sha256(ALIASES_PATH)},
            "official_alias_decisions": {"path": str(ALIAS_DECISIONS_PATH.relative_to(ROOT)), "sha256": sha256(ALIAS_DECISIONS_PATH)},
            "shadow_evaluation": {"path": str(SHADOW_PATH.relative_to(ROOT)), "sha256": sha256(SHADOW_PATH)},
        },
        "summary": {
            "n_answerable": shadow["n_answerable"],
            "ontology_match_coverage": shadow["ontology_match_coverage"],
            "ranking_changed_count": shadow["ranking_changed_count"],
            "changed_case_count": len(changed_cases),
            "unchanged_case_count": shadow["n_answerable"] - len(changed_cases),
            "impact_counts": dict(sorted(impact_counts.items())),
            "ontology_evidence_relation_counts": dict(sorted(relation_counts.items())),
            "quality_gate": shadow["quality_gate"],
        },
        "policy": {
            "do_not_tune_on_this_heldout_set": True,
            "next_evaluation_requires_fresh_unseen_questions": True,
            "automatic_runtime_promotion": False,
        },
        "changed_cases": changed_cases,
    }


def serialize(analysis: dict) -> str:
    return json.dumps(analysis, ensure_ascii=False, indent=2) + "\n"


def build_review_markdown(analysis: dict) -> str:
    summary = analysis["summary"]
    lines = [
        "# Canonical Ontology Assist Held-out 진단", "",
        "> 고정 held-out 결과를 설명하는 진단 문서입니다. 이 문서의 사례로 검색 규칙을 튜닝하거나 운영에 반영하지 않습니다.",
        "> LLM·DB·Supabase 호출과 운영 검색 변경은 없습니다.", "",
        "## 결과", "",
        f"- 평가 문항: {summary['n_answerable']}개",
        f"- ontology 라벨 일치율: {summary['ontology_match_coverage']}",
        f"- 순위 변경: {summary['ranking_changed_count']}건",
        f"- 첫 정답 순위 개선: {summary['impact_counts'].get('improved_first_gold_rank', 0)}건",
        f"- 첫 정답 순위 하락: {summary['impact_counts'].get('regressed_first_gold_rank', 0)}건",
        f"- 첫 정답 순위 동일: {summary['impact_counts'].get('first_gold_rank_unchanged', 0)}건",
        f"- 품질 게이트 통과: `{summary['quality_gate']['passed']}`", "",
        "## 해석", "",
        "- 정답과 겹치지 않는 ontology 페이지를 앞에 붙인 사례는 Recall@1 하락의 직접 근거다.",
        "- 정답 페이지를 앞에 붙여 개선된 사례가 있어도, 이 held-out 결과로 규칙·가중치를 조정하지 않는다.",
        "- 다음 비교는 새로 수집하고 누구도 결과를 보지 않은 질문 세트에서만 수행한다.", "",
        "## 순위 변경 사례", "",
    ]
    for case in analysis["changed_cases"]:
        lines += [
            f"### `{case['test_id']}` — {case['impact']}", "",
            f"- 정답 페이지: {', '.join(f'`{page}`' for page in case['gold'])}",
            f"- 매칭 label: {', '.join(f'`{label}`' for label in case['matched_labels']) or '(없음)'}",
            f"- ontology 페이지와 정답 관계: `{case['ontology_evidence_relation']}`",
            f"- 첫 정답 순위: baseline `{case['baseline_first_gold_rank']}`, assist `{case['assisted_first_gold_rank']}`",
            f"- baseline: {', '.join(f'`{page}`' for page in case['baseline_pages'])}",
            f"- assist: {', '.join(f'`{page}`' for page in case['assisted_pages'])}",
            "",
        ]
    return "\n".join(lines) + "\n"


def generate() -> tuple[str, str]:
    shadow = evaluate(
        load_rows(), load_json(BASELINE_PATH),
        build_label_index(
            load_json(CANONICAL_PATH), load_json(ALIASES_PATH), load_json(ALIAS_DECISIONS_PATH),
        ),
    )
    if not SHADOW_PATH.exists() or SHADOW_PATH.read_text(encoding="utf-8") != json.dumps(shadow, ensure_ascii=False, indent=2) + "\n":
        raise ValueError("canonical assist shadow evaluation must be generated before its diagnosis")
    analysis = build_analysis(shadow)
    return serialize(analysis), build_review_markdown(analysis)


def write_or_check(check: bool) -> int:
    analysis, review = generate()
    outputs = ((OUTPUT_PATH, analysis), (REVIEW_PATH, review))
    if check:
        stale = [path for path, content in outputs if not path.exists() or path.read_text(encoding="utf-8") != content]
        if stale:
            for path in stale:
                print(f"out of date: {path.relative_to(ROOT)}")
            return 1
        print("up to date: canonical assist held-out diagnosis")
        return 0
    for path, content in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote: {path.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    return write_or_check(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
