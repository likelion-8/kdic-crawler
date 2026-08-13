"""Validate human ontology review decisions without making any decision automatically."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.crawler.init_ontology_review_decisions import CANONICAL_PATH, FACTS_PATH, OUTPUT_PATH, fact_label


ALLOWED_DECISIONS = frozenset({"pending", "approved", "rejected", "needs_changes"})


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_reviewed_at(value: object) -> bool:
    if not _nonempty(value):
        return False
    text = str(value).strip()
    try:
        if "T" in text:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        else:
            date.fromisoformat(text)
    except ValueError:
        return False
    return True


def _validate_entries(entries: object, expected: dict[str, str], kind: str) -> tuple[list[str], Counter]:
    errors: list[str] = []
    counts: Counter = Counter()
    if not isinstance(entries, list):
        return [f"{kind} must be a list"], counts
    ids = [entry.get("id") for entry in entries if isinstance(entry, dict)]
    if len(ids) != len(entries):
        errors.append(f"{kind} entries must be objects")
    duplicate_ids = sorted(item for item, count in Counter(ids).items() if count > 1)
    if duplicate_ids:
        errors.append(f"duplicate {kind} decision IDs: {', '.join(duplicate_ids)}")
    actual_ids = set(ids)
    missing_ids = sorted(set(expected) - actual_ids)
    unexpected_ids = sorted(actual_ids - set(expected))
    if missing_ids:
        errors.append(f"missing {kind} decisions: {', '.join(missing_ids)}")
    if unexpected_ids:
        errors.append(f"unexpected {kind} decisions: {', '.join(unexpected_ids)}")

    for entry in entries:
        if not isinstance(entry, dict) or entry.get("id") not in expected:
            continue
        entry_id = entry["id"]
        if entry.get("label") != expected[entry_id]:
            errors.append(f"{kind} label does not match source for {entry_id}")
        decision = entry.get("decision")
        if decision not in ALLOWED_DECISIONS:
            errors.append(f"invalid {kind} decision for {entry_id}: {decision!r}")
            continue
        counts[decision] += 1
        if decision == "pending":
            continue
        if not _nonempty(entry.get("reviewed_by")):
            errors.append(f"{kind} non-pending decision needs reviewed_by: {entry_id}")
        if not _valid_reviewed_at(entry.get("reviewed_at")):
            errors.append(f"{kind} non-pending decision needs ISO reviewed_at: {entry_id}")
        if decision in {"rejected", "needs_changes"} and not _nonempty(entry.get("note")):
            errors.append(f"{kind} {decision} decision needs note: {entry_id}")
    return errors, counts


def validate_decisions(decisions: dict, canonical: dict, facts: dict) -> dict:
    errors: list[str] = []
    expected_source = {
        "canonical_draft": {"path": CANONICAL_PATH.relative_to(ROOT).as_posix(), "sha256": _sha256(CANONICAL_PATH)},
        "core_facts": {"path": FACTS_PATH.relative_to(ROOT).as_posix(), "sha256": _sha256(FACTS_PATH)},
    }
    if decisions.get("schema_version") != "1.0.0":
        errors.append("unsupported decision schema_version")
    if decisions.get("production_impact") != "none":
        errors.append("review decisions must have production_impact none")
    if decisions.get("source") != expected_source:
        errors.append("decision file source hashes are stale; reinitialize only after preserving prior human decisions")
    for migration in decisions.get("source_migrations", []):
        if migration.get("artifact") != expected_source["core_facts"]["path"]:
            errors.append("source migration must reference the core facts artifact")
        if migration.get("current_sha256") != expected_source["core_facts"]["sha256"]:
            errors.append("source migration current_sha256 must match the current core facts")
        if len(str(migration.get("previous_sha256", ""))) != 64:
            errors.append("source migration previous_sha256 must be a SHA-256 hash")
        if migration.get("semantic_claim_changed") is not False:
            errors.append("approved decisions can only be preserved for a non-semantic evidence migration")
        if not _nonempty(migration.get("authorized_by")):
            errors.append("source migration needs authorized_by")
        if not _valid_reviewed_at(migration.get("applied_at")):
            errors.append("source migration needs ISO applied_at")

    expected_entities = {entity["id"]: entity["label"] for entity in canonical["entities"]}
    expected_facts = {fact["id"]: fact_label(fact) for fact in facts["facts"]}
    entity_errors, entity_counts = _validate_entries(decisions.get("entities"), expected_entities, "entity")
    fact_errors, fact_counts = _validate_entries(decisions.get("facts"), expected_facts, "fact")
    errors.extend(entity_errors)
    errors.extend(fact_errors)
    all_counts = entity_counts + fact_counts
    review_complete = not errors and all_counts["pending"] == 0 and all_counts["needs_changes"] == 0
    all_approved = review_complete and all_counts["approved"] == len(expected_entities) + len(expected_facts)
    return {
        "valid": not errors,
        "review_complete": review_complete,
        "all_approved": all_approved,
        "counts": {
            "entities": dict(sorted(entity_counts.items())),
            "facts": dict(sorted(fact_counts.items())),
            "total": dict(sorted(all_counts.items())),
        },
        "errors": errors,
    }


def current_validation() -> dict:
    if not OUTPUT_PATH.exists():
        return {
            "valid": False,
            "review_complete": False,
            "all_approved": False,
            "counts": {"entities": {}, "facts": {}, "total": {}},
            "errors": [f"missing review decision file: {OUTPUT_PATH.relative_to(ROOT)}"],
        }
    return validate_decisions(load_json(OUTPUT_PATH), load_json(CANONICAL_PATH), load_json(FACTS_PATH))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    output = current_validation()
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print("ontology review decision validation")
        print("  valid:", output["valid"])
        print("  review complete:", output["review_complete"])
        print("  all approved:", output["all_approved"])
        print("  counts:", output["counts"]["total"])
        for error in output["errors"]:
            print("  error:", error)
    return 0 if output["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
