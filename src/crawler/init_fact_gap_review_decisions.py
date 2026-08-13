"""Initialize the human-owned review decisions for source-verified fact-gap candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
QUEUE_PATH = ROOT / "ontology" / "kdic-fact-gap-review-queue.json"
OUTPUT_PATH = ROOT / "ontology" / "review" / "fact-gap-review-decisions.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source_descriptor(path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def build_initial_decisions(queue: dict) -> dict:
    return {
        "schema_version": "1.0.0",
        "status": "pending_domain_review",
        "production_impact": "none",
        "policy": {
            "automatic_approval": False,
            "automatic_core_fact_promotion": False,
            "approved_candidates_require_separate_core_fact_change": True,
            "reviewer_identity_required_for_non_pending_decisions": True,
        },
        "source": {"fact_gap_queue": source_descriptor(QUEUE_PATH)},
        "candidates": [
            {
                "id": item["id"], "label": item["label"], "decision": "pending",
                "reviewed_by": None, "reviewed_at": None, "note": None,
            }
            for item in queue["candidates"]
        ],
    }


def write_initial(output_path: Path = OUTPUT_PATH) -> None:
    if output_path.exists():
        raise FileExistsError(f"fact-gap decision file already exists and is human-owned: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(build_initial_decisions(load_json(QUEUE_PATH)), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify that the human-owned decision file exists")
    args = parser.parse_args()
    if args.check:
        print(f"fact-gap decision file {'exists' if OUTPUT_PATH.exists() else 'is missing'}: {OUTPUT_PATH.relative_to(ROOT)}")
        return 0 if OUTPUT_PATH.exists() else 1
    write_initial()
    print(f"initialized pending fact-gap review decisions: {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
