"""Safely record one human ontology review decision.

The script never chooses a decision. By default it only previews the change; writing
the human-owned decision file requires an explicit ``--apply`` flag.
"""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

try:
    from .init_ontology_review_decisions import CANONICAL_PATH, FACTS_PATH, OUTPUT_PATH, load_json
    from ..eval.validate_ontology_review_decisions import ALLOWED_DECISIONS, validate_decisions
except ImportError:  # direct script execution
    from init_ontology_review_decisions import CANONICAL_PATH, FACTS_PATH, OUTPUT_PATH, load_json
    from src.eval.validate_ontology_review_decisions import ALLOWED_DECISIONS, validate_decisions


FINAL_DECISIONS = ALLOWED_DECISIONS - {"pending"}
SECTION_BY_KIND = {"entity": "entities", "fact": "facts"}


def record_decision(
    decisions: dict,
    canonical: dict,
    facts: dict,
    *,
    kind: str,
    item_id: str,
    decision: str,
    reviewer: str,
    reviewed_at: str,
    note: str | None,
) -> dict:
    if kind not in {"entity", "fact"}:
        raise ValueError("kind must be entity or fact")
    if decision not in FINAL_DECISIONS:
        raise ValueError(f"decision must be one of: {', '.join(sorted(FINAL_DECISIONS))}")
    if not reviewer.strip() or not reviewed_at.strip():
        raise ValueError("reviewer and reviewed_at are required")
    if decision in {"rejected", "needs_changes"} and not (note and note.strip()):
        raise ValueError(f"{decision} requires a note")
    section = SECTION_BY_KIND[kind]
    entry = next((item for item in decisions[section] if item["id"] == item_id), None)
    if entry is None:
        raise ValueError(f"unknown {kind} ID: {item_id}")
    if entry["decision"] != "pending":
        raise ValueError(f"{item_id} is already {entry['decision']}; do not overwrite a recorded human decision")
    updated = deepcopy(decisions)
    target = next(item for item in updated[section] if item["id"] == item_id)
    target.update({
        "decision": decision,
        "reviewed_by": reviewer.strip(),
        "reviewed_at": reviewed_at.strip(),
        "note": note.strip() if note and note.strip() else None,
    })
    validation = validate_decisions(updated, canonical, facts)
    if not validation["valid"]:
        raise ValueError("refusing to record an invalid decision file: " + "; ".join(validation["errors"]))
    updated["status"] = (
        "all_canonical_entities_and_core_facts_approved" if validation["all_approved"]
        else "domain_review_complete" if validation["review_complete"]
        else "pending_domain_review"
    )
    return updated


def write_decisions(path: Path, decisions: dict) -> None:
    path.write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or record one human ontology review decision.")
    parser.add_argument("--kind", required=True, choices=("entity", "fact"))
    parser.add_argument("--id", required=True, dest="item_id")
    parser.add_argument("--decision", required=True, choices=sorted(FINAL_DECISIONS))
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--date", required=True, dest="reviewed_at", help="ISO date or timestamp")
    parser.add_argument("--note")
    parser.add_argument("--apply", action="store_true", help="write the reviewed decision; default is preview only")
    args = parser.parse_args()
    current = load_json(OUTPUT_PATH)
    updated = record_decision(
        current, load_json(CANONICAL_PATH), load_json(FACTS_PATH),
        kind=args.kind, item_id=args.item_id, decision=args.decision,
        reviewer=args.reviewer, reviewed_at=args.reviewed_at, note=args.note,
    )
    target = next(item for item in updated[SECTION_BY_KIND[args.kind]] if item["id"] == args.item_id)
    if not args.apply:
        print("preview only; add --apply to write the human-owned decision file")
        print(json.dumps(target, ensure_ascii=False, indent=2))
        return 0
    write_decisions(OUTPUT_PATH, updated)
    print(f"recorded {args.kind} decision: {args.item_id} -> {args.decision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
