"""Create a runtime ontology snapshot only after every governance gate passes.

This tool does not connect to Supabase or change RAG behavior. Its sole purpose is
to make an attempted runtime handoff fail closed until human approval and the frozen
quality gate both pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from .build_ontology_map import ROOT
except ImportError:  # direct script execution
    from build_ontology_map import ROOT


CANONICAL_PATH = ROOT / "ontology" / "kdic-canonical-ontology-draft.json"
FACTS_PATH = ROOT / "ontology" / "kdic-core-fact-proposals.json"
DECISIONS_PATH = ROOT / "ontology" / "review" / "canonical-ontology-decisions.json"
OUTPUT_PATH = ROOT / "ontology" / "kdic-runtime-ontology.json"
sys.path.insert(0, str(ROOT))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_snapshot(canonical: dict, facts: dict, decisions: dict) -> dict:
    entity_decisions = {item["id"]: item["decision"] for item in decisions["entities"]}
    fact_decisions = {item["id"]: item["decision"] for item in decisions["facts"]}
    return {
        "schema_version": "1.0.0",
        "status": "runtime_snapshot_approved",
        "production_impact": "candidate_only_no_automatic_rag_integration",
        "source": canonical["source"],
        "approved_entities": [
            entity for entity in canonical["entities"] if entity_decisions.get(entity["id"]) == "approved"
        ],
        "approved_facts": [
            fact for fact in facts["facts"] if fact_decisions.get(fact["id"]) == "approved"
        ],
    }


def _serialize(snapshot: dict) -> str:
    return json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"


def _readiness() -> dict:
    # Import lazily so direct execution works and this module stays independent of the release validator's imports.
    from src.eval.validate_ontology_release import validate

    return validate()


def write_or_check(check: bool) -> int:
    readiness = _readiness()
    if not readiness["runtime_ready"]:
        print("runtime ontology snapshot blocked")
        for blocker in readiness["blockers"]:
            print("  blocker:", blocker)
        if OUTPUT_PATH.exists():
            print(f"  stale snapshot must not be used: {OUTPUT_PATH.relative_to(ROOT)}")
        return 1

    snapshot = _serialize(build_snapshot(load_json(CANONICAL_PATH), load_json(FACTS_PATH), load_json(DECISIONS_PATH)))
    if check:
        if OUTPUT_PATH.exists() and OUTPUT_PATH.read_text(encoding="utf-8") == snapshot:
            print(f"runtime ontology snapshot is current: {OUTPUT_PATH.relative_to(ROOT)}")
            return 0
        print(f"runtime ontology snapshot is missing or stale: {OUTPUT_PATH.relative_to(ROOT)}")
        return 1
    OUTPUT_PATH.write_text(snapshot, encoding="utf-8", newline="\n")
    print(f"wrote runtime ontology snapshot: {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    return write_or_check(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
