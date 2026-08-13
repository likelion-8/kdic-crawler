"""Validate the canonical graph against the machine-readable ontology schema."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_PATH = ROOT / "ontology" / "kdic-domain-ontology.yaml"
GRAPH_PATH = ROOT / "ontology" / "kdic-canonical-graph.json"
CORPUS_PATH = ROOT / "data" / "corpus.jsonl"


def load_schema(path: Path = SCHEMA_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_corpus(path: Path = CORPUS_PATH) -> dict[str, dict]:
    return {
        row["page_id"]: row
        for row in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    }


def validate(schema: dict, graph: dict, corpus: dict[str, dict]) -> dict:
    errors: list[str] = []
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    node_by_id = {node.get("id"): node for node in nodes}
    if len(node_by_id) != len(nodes) or None in node_by_id:
        errors.append("graph node IDs must be present and unique")

    declared_classes = {
        item["id"] for item in schema.get("classes", []) if item.get("canonical_graph") is True
    }
    actual_classes = {node.get("node_type") for node in nodes}
    missing_classes = sorted(declared_classes - actual_classes)
    undeclared_classes = sorted(actual_classes - declared_classes)
    if missing_classes:
        errors.append("declared canonical classes missing from graph: " + ", ".join(missing_classes))
    if undeclared_classes:
        errors.append("undeclared graph node types: " + ", ".join(undeclared_classes))

    declared_relations = {item["id"]: item for item in schema.get("relations", [])}
    actual_relations = {edge.get("relation") for edge in edges}
    missing_relations = sorted(set(declared_relations) - actual_relations)
    undeclared_relations = sorted(actual_relations - set(declared_relations))
    if missing_relations:
        errors.append("declared canonical relations missing from graph: " + ", ".join(missing_relations))
    if undeclared_relations:
        errors.append("undeclared graph relations: " + ", ".join(undeclared_relations))

    relation_counts = Counter(edge.get("relation") for edge in edges)
    for relation_id, relation in declared_relations.items():
        expected_count = relation.get("current_edge_count")
        if expected_count is not None and relation_counts[relation_id] != expected_count:
            errors.append(
                f"{relation_id} edge count is {relation_counts[relation_id]}, expected {expected_count}"
            )

    outgoing: dict[tuple[str, str], list[dict]] = defaultdict(list)
    incoming: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for edge in edges:
        source = node_by_id.get(edge.get("source"))
        target = node_by_id.get(edge.get("target"))
        if source is None or target is None:
            errors.append(f"dangling edge: {edge!r}")
            continue
        relation = declared_relations.get(edge.get("relation"))
        if relation is None:
            continue
        if source.get("node_type") not in relation["domain"]:
            errors.append(
                f"{edge['relation']} source type {source.get('node_type')} is invalid for {edge['source']}"
            )
        if target.get("node_type") not in relation["range"]:
            errors.append(
                f"{edge['relation']} target type {target.get('node_type')} is invalid for {edge['target']}"
            )
        outgoing[(edge["source"], edge["relation"])].append(edge)
        incoming[(edge["target"], edge["relation"])].append(edge)

    allowed_statuses = set(schema.get("controlled_vocabularies", {}).get("node_statuses", []))
    unknown_statuses = sorted({node.get("status") for node in nodes} - allowed_statuses)
    if unknown_statuses:
        errors.append("undeclared graph node statuses: " + ", ".join(map(str, unknown_statuses)))

    for node in nodes:
        node_id = node["id"]
        node_type = node["node_type"]
        if node_type == "Document":
            if len(outgoing[(node_id, "DOCUMENTS_SERVICE")]) != 1:
                errors.append(f"Document must have exactly one DOCUMENTS_SERVICE edge: {node_id}")
            page = corpus.get(node.get("page_id"))
            if page is None or node.get("content_sha256") != page.get("content_sha256"):
                errors.append(f"Document source hash is missing or stale: {node_id}")
        if node_type == "Service" and node.get("status") == "base":
            if len(outgoing[(node_id, "BELONGS_TO_DOMAIN")]) != 1:
                errors.append(f"base Service must belong to exactly one domain: {node_id}")
        if node.get("status") == "domain_approved" or node_type in {"Fact", "OfficialLabel"}:
            if not incoming[(node_id, "EVIDENCE_FOR")]:
                errors.append(f"reviewed graph item has no Evidence edge: {node_id}")
        if node_type == "Fact":
            if len(outgoing[(node_id, "ASSERTS_ABOUT")]) != 1:
                errors.append(f"Fact must have exactly one ASSERTS_ABOUT edge: {node_id}")
            evidence = node.get("evidence", {})
            page = corpus.get(evidence.get("page_id"))
            if not page:
                errors.append(f"Fact evidence page is missing: {node_id}")
            else:
                if evidence.get("source_url") != page.get("source_url"):
                    errors.append(f"Fact evidence URL is stale: {node_id}")
                if evidence.get("content_sha256") != page.get("content_sha256"):
                    errors.append(f"Fact evidence hash is stale: {node_id}")
                if evidence.get("quote") not in page.get("text", ""):
                    errors.append(f"Fact evidence quote is not literal corpus text: {node_id}")
                evidence_sources = {
                    edge["source"] for edge in incoming[(node_id, "EVIDENCE_FOR")]
                }
                if evidence_sources != {f"document:{evidence.get('page_id')}"}:
                    errors.append(f"Fact evidence edge does not match embedded evidence: {node_id}")
        if node_type == "OfficialLabel" and len(outgoing[(node_id, "LABEL_FOR")]) != 1:
            errors.append(f"OfficialLabel must have exactly one LABEL_FOR edge: {node_id}")

    expected_node_counts = dict(sorted(Counter(node["node_type"] for node in nodes).items()))
    expected_relation_counts = dict(sorted(relation_counts.items()))
    if graph.get("summary", {}).get("node_count") != len(nodes):
        errors.append("graph summary node_count is stale")
    if graph.get("summary", {}).get("edge_count") != len(edges):
        errors.append("graph summary edge_count is stale")
    if graph.get("summary", {}).get("node_type_counts") != expected_node_counts:
        errors.append("graph summary node_type_counts is stale")
    if graph.get("summary", {}).get("relation_counts") != expected_relation_counts:
        errors.append("graph summary relation_counts is stale")

    approval = graph.get("approval", {})
    pending_aliases = approval.get("official_label_counts", {}).get(
        "source_verified_pending_domain_approval", 0
    )
    approved_aliases = approval.get("official_label_counts", {}).get(
        "source_verified_domain_approved", 0
    )
    if approval.get("core_approval_complete") and pending_aliases:
        expected_status = "canonical_graph_core_approval_complete_alias_review_pending"
        if graph.get("status") != expected_status:
            errors.append(f"graph status must expose pending aliases as {expected_status}")
        if approval.get("all_graph_review_items_complete") is not False:
            errors.append("all_graph_review_items_complete must be false while aliases are pending")
    if approval.get("core_approval_complete") and approved_aliases == 47:
        expected_status = "canonical_graph_all_reviewed_items_approved"
        if graph.get("status") != expected_status:
            errors.append(f"graph status must expose complete approval as {expected_status}")
        if approval.get("all_graph_review_items_complete") is not True:
            errors.append("all_graph_review_items_complete must be true after all label decisions")
        if approval.get("all_graph_review_items_approved") is not True:
            errors.append("all_graph_review_items_approved must be true after unanimous approval")

    return {
        "valid": not errors,
        "schema_version": schema.get("ontology", {}).get("version"),
        "graph_schema_version": graph.get("schema_version"),
        "declared_class_count": len(declared_classes),
        "declared_relation_count": len(declared_relations),
        "errors": errors,
    }


def current_validation() -> dict:
    return validate(load_schema(), load_json(GRAPH_PATH), load_corpus())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    output = current_validation()
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print("ontology schema alignment")
        print("  valid:", output["valid"])
        for error in output["errors"]:
            print("  error:", error)
    return 0 if output["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
