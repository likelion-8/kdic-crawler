"""Preview or record one human decision for an official ontology label."""
from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.crawler.init_official_label_review_decisions import ALIASES_PATH, OUTPUT_PATH, load_json
from src.eval.validate_official_label_review_decisions import ALLOWED_DECISIONS, validate_decisions


FINAL_DECISIONS = ALLOWED_DECISIONS - {"pending"}


def record_decision(
    decisions: dict,
    aliases: dict,
    *,
    item_id: str,
    decision: str,
    reviewer: str,
    reviewed_at: str,
    note: str | None,
) -> dict:
    if decision not in FINAL_DECISIONS:
        raise ValueError(f"decision must be one of: {', '.join(sorted(FINAL_DECISIONS))}")
    if not reviewer.strip() or not reviewed_at.strip():
        raise ValueError("reviewer and reviewed_at are required")
    if decision in {"rejected", "needs_changes"} and not (note and note.strip()):
        raise ValueError(f"{decision} requires a note")
    entry = next((item for item in decisions["labels"] if item["id"] == item_id), None)
    if entry is None:
        raise ValueError(f"unknown official-label ID: {item_id}")
    if entry["decision"] != "pending":
        raise ValueError(f"{item_id} is already {entry['decision']}; do not overwrite a recorded human decision")
    updated = deepcopy(decisions)
    target = next(item for item in updated["labels"] if item["id"] == item_id)
    target.update({
        "decision": decision,
        "reviewed_by": reviewer.strip(),
        "reviewed_at": reviewed_at.strip(),
        "note": note.strip() if note and note.strip() else None,
    })
    validation = validate_decisions(updated, aliases)
    if not validation["valid"]:
        raise ValueError("refusing to record an invalid official-label decision file: " + "; ".join(validation["errors"]))
    updated["status"] = (
        "all_official_labels_approved" if validation["all_approved"]
        else "official_label_review_complete" if validation["review_complete"]
        else "pending_domain_review"
    )
    return updated


def write_decisions(decisions: dict) -> None:
    OUTPUT_PATH.write_text(
        json.dumps(decisions, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", required=True, dest="item_id")
    parser.add_argument("--decision", required=True, choices=sorted(FINAL_DECISIONS))
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--date", required=True, dest="reviewed_at")
    parser.add_argument("--note")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    updated = record_decision(
        load_json(OUTPUT_PATH), load_json(ALIASES_PATH), item_id=args.item_id,
        decision=args.decision, reviewer=args.reviewer, reviewed_at=args.reviewed_at, note=args.note,
    )
    if not args.apply:
        target = next(item for item in updated["labels"] if item["id"] == args.item_id)
        print("preview only; add --apply to write the human-owned decision file")
        print(json.dumps(target, ensure_ascii=False, indent=2))
        return 0
    write_decisions(updated)
    print(f"recorded official-label decision: {args.item_id} -> {args.decision}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
