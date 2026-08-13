"""Initialize the human-owned review decisions for official ontology labels."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
ALIASES_PATH = ROOT / "ontology" / "kdic-official-label-aliases.json"
OUTPUT_PATH = ROOT / "ontology" / "review" / "official-label-decisions.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def source_descriptor(path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def build_initial_decisions(aliases: dict) -> dict:
    return {
        "schema_version": "1.0.0",
        "status": "pending_domain_review",
        "production_impact": "none",
        "policy": {
            "automatic_approval": False,
            "contextual_labels_are_synonyms": False,
            "approved_labels_require_retrieval_quality_gate": True,
            "reviewer_identity_required_for_non_pending_decisions": True,
        },
        "source": {"official_labels": source_descriptor(ALIASES_PATH)},
        "labels": [
            {
                "id": item["id"],
                "entity_id": item["entity_id"],
                "label": item["label"],
                "alias_type": item["alias_type"],
                "decision": "pending",
                "reviewed_by": None,
                "reviewed_at": None,
                "note": None,
            }
            for item in aliases["aliases"]
        ],
    }


def write_initial(output_path: Path = OUTPUT_PATH) -> None:
    if output_path.exists():
        raise FileExistsError(f"official-label decision file already exists and is human-owned: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(build_initial_decisions(load_json(ALIASES_PATH)), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        print(f"official-label decision file {'exists' if OUTPUT_PATH.exists() else 'is missing'}: {OUTPUT_PATH.relative_to(ROOT)}")
        return 0 if OUTPUT_PATH.exists() else 1
    write_initial()
    print(f"initialized pending official-label decisions: {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
