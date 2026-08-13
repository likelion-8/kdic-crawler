"""Validate human decisions for source-verified official ontology labels."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.crawler.init_official_label_review_decisions import (
    ALIASES_PATH,
    OUTPUT_PATH,
    source_descriptor,
)


ALLOWED_DECISIONS = frozenset({"pending", "approved", "rejected", "needs_changes"})


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_timestamp(value: object) -> bool:
    if not _nonempty(value):
        return False
    try:
        text = str(value).strip()
        datetime.fromisoformat(text.replace("Z", "+00:00")) if "T" in text else date.fromisoformat(text)
    except ValueError:
        return False
    return True


def validate_decisions(decisions: dict, aliases: dict) -> dict:
    errors: list[str] = []
    expected = {item["id"]: item for item in aliases["aliases"]}
    if decisions.get("schema_version") != "1.0.0":
        errors.append("unsupported decision schema_version")
    if decisions.get("production_impact") != "none":
        errors.append("official-label review decisions must have production_impact none")
    if decisions.get("source") != {"official_labels": source_descriptor(ALIASES_PATH)}:
        errors.append("official-label decision source hash is stale; preserve prior human decisions before reinitializing")
    entries = decisions.get("labels")
    counts: Counter = Counter()
    if not isinstance(entries, list):
        errors.append("labels must be a list")
        entries = []
    ids = [item.get("id") for item in entries if isinstance(item, dict)]
    if len(ids) != len(entries):
        errors.append("official-label decisions must be objects")
    duplicate_ids = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicate_ids:
        errors.append("duplicate official-label decision IDs: " + ", ".join(duplicate_ids))
    missing_ids = sorted(set(expected) - set(ids))
    unexpected_ids = sorted(set(ids) - set(expected))
    if missing_ids:
        errors.append("missing official-label decisions: " + ", ".join(missing_ids))
    if unexpected_ids:
        errors.append("unexpected official-label decisions: " + ", ".join(unexpected_ids))
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("id") not in expected:
            continue
        source = expected[entry["id"]]
        for key in ("entity_id", "label", "alias_type"):
            if entry.get(key) != source[key]:
                errors.append(f"official-label {key} does not match source for {entry['id']}")
        decision = entry.get("decision")
        if decision not in ALLOWED_DECISIONS:
            errors.append(f"invalid official-label decision for {entry['id']}: {decision!r}")
            continue
        counts[decision] += 1
        if decision != "pending":
            if not _nonempty(entry.get("reviewed_by")):
                errors.append(f"official-label non-pending decision needs reviewed_by: {entry['id']}")
            if not _valid_timestamp(entry.get("reviewed_at")):
                errors.append(f"official-label non-pending decision needs ISO reviewed_at: {entry['id']}")
        if decision in {"rejected", "needs_changes"} and not _nonempty(entry.get("note")):
            errors.append(f"official-label {decision} decision needs note: {entry['id']}")
    review_complete = not errors and counts["pending"] == counts["needs_changes"] == 0
    return {
        "valid": not errors,
        "review_complete": review_complete,
        "all_approved": review_complete and counts["approved"] == len(expected),
        "counts": dict(sorted(counts.items())),
        "errors": errors,
    }


def current_validation() -> dict:
    if not OUTPUT_PATH.exists():
        return {
            "valid": False,
            "review_complete": False,
            "all_approved": False,
            "counts": {},
            "errors": [f"missing official-label decision file: {OUTPUT_PATH.relative_to(ROOT)}"],
        }
    return validate_decisions(load_json(OUTPUT_PATH), load_json(ALIASES_PATH))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    output = current_validation()
    print(json.dumps(output, ensure_ascii=False, indent=2) if args.json else f"official-label review valid: {output['valid']}\ncounts: {output['counts']}\nerrors: {output['errors']}")
    return 0 if output["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
