"""Run the fixed ontology-assist shadow evaluation on a validated fresh held-out set.

The command accepts only a human-authored fresh testset and a baseline ranking result
for exactly the same questions. It does not retrieve documents, tune rules, call an
LLM, access Supabase, or change production behavior.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.eval.eval_canonical_ontology_assist import (
    ALIASES_PATH,
    ALIAS_DECISIONS_PATH,
    CANONICAL_PATH,
    build_label_index,
    evaluate,
    load_json,
)
from src.eval.validate_fresh_ontology_assist_heldout import load_jsonl, validate_file


def _relative_or_absolute(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def validate_baseline_alignment(rows: list[dict], baseline: dict) -> dict:
    errors: list[str] = []
    expected = {row["test_id"]: set(row["expected_sources"]) for row in rows}
    entries = baseline.get("per_row_retrieval")
    if not isinstance(entries, list):
        return {"valid": False, "errors": ["baseline per_row_retrieval must be a list"], "counts": {}}
    ids = [entry.get("test_id") for entry in entries if isinstance(entry, dict)]
    if len(ids) != len(entries):
        errors.append("baseline per_row_retrieval entries must be objects")
    duplicate_ids = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicate_ids:
        errors.append(f"baseline has duplicate test_id values: {', '.join(duplicate_ids)}")
    missing_ids = sorted(set(expected) - set(ids))
    unexpected_ids = sorted(set(ids) - set(expected))
    if missing_ids:
        errors.append(f"baseline is missing fresh test IDs: {', '.join(missing_ids)}")
    if unexpected_ids:
        errors.append(f"baseline has unexpected test IDs: {', '.join(unexpected_ids)}")
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("test_id") not in expected:
            continue
        item_id = entry["test_id"]
        if set(entry.get("gold", [])) != expected[item_id]:
            errors.append(f"baseline gold does not match fresh expected_sources: {item_id}")
        top5 = entry.get("top5_pages")
        if not isinstance(top5, list) or len(top5) != 5 or not all(isinstance(page_id, str) and page_id for page_id in top5):
            errors.append(f"baseline top5_pages must contain exactly five non-empty page IDs: {item_id}")
    return {
        "valid": not errors,
        "counts": {"fresh_test_ids": len(expected), "baseline_rows": len(entries)},
        "errors": errors,
    }


def evaluate_fresh(rows: list[dict], baseline: dict, testset_path: Path, baseline_path: Path) -> dict:
    alignment = validate_baseline_alignment(rows, baseline)
    if not alignment["valid"]:
        raise ValueError("baseline does not align with the fresh held-out set: " + "; ".join(alignment["errors"]))
    output = evaluate(
        {row["test_id"]: row for row in rows}, baseline,
        build_label_index(
            load_json(CANONICAL_PATH), load_json(ALIASES_PATH), load_json(ALIAS_DECISIONS_PATH),
        ),
    )
    output.update({
        "mode": "offline_shadow_exact_official_label_prepend_fresh_heldout",
        "production_impact": "none",
        "heldout_tuning": False,
        "fresh_heldout": {
            "testset": _relative_or_absolute(testset_path),
            "baseline": _relative_or_absolute(baseline_path),
            "baseline_alignment": alignment,
            "automatic_runtime_promotion": False,
        },
    })
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate fixed ontology assistance on a validated fresh held-out set.")
    parser.add_argument("--testset", required=True, type=Path, help="independently authored fresh JSONL")
    parser.add_argument("--baseline", required=True, type=Path, help="baseline ranking JSON for the exact same test IDs")
    parser.add_argument("--output", required=True, type=Path, help="write fresh shadow result JSON here")
    args = parser.parse_args()
    freshness = validate_file(args.testset)
    if not freshness["valid"]:
        print(json.dumps(freshness, ensure_ascii=False, indent=2))
        return 1
    output = evaluate_fresh(load_jsonl(args.testset), load_json(args.baseline), args.testset, args.baseline)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("fresh ontology assist shadow evaluation")
    print("  answerable:", output["n_answerable"])
    print("  delta:", output["delta"])
    print("  quality gate:", output["quality_gate"]["passed"])
    print("  wrote:", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
