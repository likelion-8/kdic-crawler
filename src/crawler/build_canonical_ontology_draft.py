"""Consolidate all reviewed ontology proposals into one approval-ready draft.

The canonical draft normalizes proposal schemas, verifies evidence against the
current document map, and emits a human approval checklist. It does not approve any
entity, include fact values, read held-out data, or change runtime retrieval.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
MAP_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
P1_P2_PATH = ROOT / "ontology" / "kdic-curated-concept-proposals.json"
P3_TYPED_PATH = ROOT / "ontology" / "kdic-p3-typed-concept-proposals.json"
P3_GENERAL_PATH = ROOT / "ontology" / "kdic-p3-general-concept-proposals.json"
P3_REMAINING_PATH = ROOT / "ontology" / "kdic-p3-remaining-reviews.json"
OUTPUT_PATH = ROOT / "ontology" / "kdic-canonical-ontology-draft.json"
CHECKLIST_PATH = ROOT / "ontology" / "review" / "CANONICAL_ONTOLOGY_APPROVAL_CHECKLIST.md"
KNOWN_CLASSES = frozenset({
    "Actor", "Concept", "ContactPoint", "EligibilityRule", "MonetaryRule",
    "Procedure", "RequiredDocument", "Service",
})


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _evidence_key(item: dict) -> tuple[str, str, str]:
    return item["page_id"], item["source_url"], item["content_sha256"]


def _normalize_entity(item: dict, source_catalog: str, document_map: dict[str, dict]) -> dict:
    evidence = sorted(item["evidence"], key=_evidence_key)
    parent_service_ids = item.get("parent_service_ids", item.get("service_ids"))
    if parent_service_ids is None:
        parent_service_ids = sorted({
            service_id
            for source in evidence
            for service_id in document_map[source["page_id"]]["service_ids"]
        })
    # A top-level service must not claim itself as its parent.
    parent_service_ids = sorted(set(parent_service_ids) - {item["id"]})
    return {
        "id": item["id"],
        "label": item["label"],
        "ontology_class": item["ontology_class"],
        "review_status": "pending_domain_approval",
        "parent_service_ids": parent_service_ids,
        "synonyms": list(item.get("synonyms", [])),
        "fact_values": list(item.get("fact_values", [])),
        "evidence": evidence,
        "provenance": {"source_catalog": source_catalog, "source_status": item["status"]},
    }


def build_draft(mapping: dict, p1_p2: dict, p3_typed: dict, p3_general: dict, p3_remaining: dict) -> dict:
    catalogs = (
        (P1_P2_PATH.name, p1_p2, p1_p2["candidates"]),
        (P3_TYPED_PATH.name, p3_typed, p3_typed["proposals"]),
        (P3_GENERAL_PATH.name, p3_general, p3_general["proposals"]),
        (P3_REMAINING_PATH.name, p3_remaining, p3_remaining["proposals"]),
    )
    for _, catalog, _ in catalogs:
        if catalog["source"] != mapping["source"]:
            raise ValueError("every proposal catalog must use the current ontology map")
        if catalog["production_impact"] != "none":
            raise ValueError("proposal catalog must have no production impact")

    document_map = {document["page_id"]: document for document in mapping["document_mappings"]}
    services = {service["id"]: service for service in mapping["services"]}
    entities = []
    base_service_merges = []
    seen_ids = set()
    for source_catalog, _, items in catalogs:
        for item in items:
            if item["id"] in seen_ids:
                raise ValueError(f"duplicate canonical entity id: {item['id']}")
            seen_ids.add(item["id"])
            if item["ontology_class"] not in KNOWN_CLASSES:
                raise ValueError(f"unknown ontology class: {item['ontology_class']}")
            if item["status"] != "proposed":
                raise ValueError(f"non-proposed source entity: {item['id']}")
            entity = _normalize_entity(item, source_catalog, document_map)
            if entity["synonyms"] or entity["fact_values"]:
                raise ValueError("canonical draft cannot contain unapproved synonyms or fact values")
            for evidence in entity["evidence"]:
                page_id = evidence["page_id"]
                if page_id not in document_map:
                    raise ValueError(f"unknown evidence page: {page_id}")
                if evidence["content_sha256"] != document_map[page_id]["content_sha256"]:
                    raise ValueError(f"stale evidence hash: {page_id}")
            if item["id"] in services:
                if item["ontology_class"] != "Service":
                    raise ValueError(f"base service id reused by non-Service: {item['id']}")
                base_service_merges.append({
                    "service_id": item["id"],
                    "proposed_label": item["label"],
                    "evidence": entity["evidence"],
                    "provenance": entity["provenance"],
                })
                continue
            if not set(entity["parent_service_ids"]).issubset(services):
                raise ValueError(f"unknown parent service for {entity['id']}")
            entities.append(entity)

    entities.sort(key=lambda entity: (entity["ontology_class"], entity["label"], entity["id"]))
    class_counts = Counter(entity["ontology_class"] for entity in entities)
    evidence_pages = {evidence["page_id"] for entity in entities for evidence in entity["evidence"]}
    return {
        "schema_version": "1.0.0",
        "ontology_version": "0.2.0-draft",
        "status": "canonical_draft_pending_domain_approval",
        "production_impact": "none",
        "source": mapping["source"],
        "policies": {
            "heldout_testset_used_for_curation": False,
            "runtime_use": "prohibited_until_approval_and_evaluation",
            "automatic_approval": False,
            "unapproved_synonyms_allowed": False,
            "unapproved_fact_values_allowed": False,
        },
        "source_catalogs": [source_catalog for source_catalog, _, _ in catalogs],
        "base_services": [
            {"id": service["id"], "label": service["label"], "document_count": service["document_count"]}
            for service in sorted(services.values(), key=lambda service: service["id"])
        ],
        "merged_base_service_proposals": sorted(base_service_merges, key=lambda item: item["service_id"]),
        "summary": {
            "entity_count": len(entities),
            "class_counts": dict(sorted(class_counts.items())),
            "evidence_page_count": len(evidence_pages),
            "pending_approval_count": len(entities),
            "base_service_count": len(services),
            "merged_base_service_proposal_count": len(base_service_merges),
        },
        "entities": entities,
    }


def serialize(draft: dict) -> str:
    return json.dumps(draft, ensure_ascii=False, indent=2) + "\n"


def build_checklist(draft: dict) -> str:
    lines = [
        "# Canonical Ontology Approval Checklist",
        "",
        "This is a generated review template. Every entity remains `pending_domain_approval`; checking a box here does not change machine-readable status or production behavior.",
        "",
        "## Approval criteria",
        "",
        "- The label is an official, stable KDIC business term rather than a navigation heading.",
        "- The ontology class and parent Service are correct.",
        "- Every evidence page supports the entity and its content hash is current.",
        "- No synonym, monetary value, deadline, or condition is inferred from the label alone.",
        "- Choose exactly one decision: approve, reject, needs changes.",
        "",
        f"Entities pending review: {draft['summary']['entity_count']}",
        "",
    ]
    for entity in draft["entities"]:
        pages = ", ".join(f"`{item['page_id']}`" for item in entity["evidence"])
        parents = ", ".join(f"`{item}`" for item in entity["parent_service_ids"]) or "(top-level)"
        lines.extend([
            f"## `{entity['id']}` — {entity['label']}",
            "",
            f"- Class: `{entity['ontology_class']}`",
            f"- Parent Service: {parents}",
            f"- Evidence pages: {pages}",
            f"- Source catalog: `{entity['provenance']['source_catalog']}`",
            "- [ ] Approve",
            "- [ ] Reject",
            "- [ ] Needs changes",
            "- Reviewer / date: ",
            "- Note: ",
            "",
        ])
    return "\n".join(lines) + "\n"


def generate() -> tuple[str, str]:
    draft = build_draft(
        load_json(MAP_PATH), load_json(P1_P2_PATH), load_json(P3_TYPED_PATH), load_json(P3_GENERAL_PATH),
        load_json(P3_REMAINING_PATH)
    )
    return serialize(draft), build_checklist(draft)


def write_or_check(check: bool) -> int:
    draft_output, checklist_output = generate()
    outputs = ((OUTPUT_PATH, draft_output), (CHECKLIST_PATH, checklist_output))
    if check:
        stale = [path for path, output in outputs if not path.exists() or path.read_text(encoding="utf-8") != output]
        if stale:
            for path in stale:
                print(f"out of date: {path.relative_to(ROOT)}")
            return 1
        print("up to date: canonical ontology draft and approval checklist")
        return 0
    for path, output in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8", newline="\n")
        print(f"wrote: {path.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if generated artifacts are out of date")
    return write_or_check(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
