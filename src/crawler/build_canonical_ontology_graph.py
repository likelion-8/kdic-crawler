"""Build the canonical offline knowledge graph from reviewed ontology artifacts."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
MAP_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
CANONICAL_PATH = ROOT / "ontology" / "kdic-canonical-ontology-draft.json"
FACTS_PATH = ROOT / "ontology" / "kdic-core-fact-proposals.json"
ALIASES_PATH = ROOT / "ontology" / "kdic-official-label-aliases.json"
ALIAS_DECISIONS_PATH = ROOT / "ontology" / "review" / "official-label-decisions.json"
P3_GENERAL_PATH = ROOT / "ontology" / "kdic-p3-general-concept-proposals.json"
P3_REMAINING_PATH = ROOT / "ontology" / "kdic-p3-remaining-reviews.json"
DECISIONS_PATH = ROOT / "ontology" / "review" / "canonical-ontology-decisions.json"
OUTPUT_PATH = ROOT / "ontology" / "kdic-canonical-graph.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _effective_status(source_status: str, decision: str | None, *, fact: bool) -> str:
    if decision in {None, "pending"}:
        return source_status
    statuses = {
        "approved": "source_verified_domain_approved" if fact else "domain_approved",
        "rejected": "source_verified_domain_rejected" if fact else "domain_rejected",
        "needs_changes": "source_verified_domain_needs_changes" if fact else "domain_needs_changes",
    }
    return statuses[decision]


def build_graph(
    mapping: dict,
    canonical: dict,
    facts: dict,
    aliases: dict,
    review_catalogs: tuple[dict, ...] = (),
    decisions: dict | None = None,
    alias_decisions: dict | None = None,
) -> dict:
    source = mapping["source"]
    if any(item["source"] != source for item in (canonical, facts, aliases, *review_catalogs)):
        raise ValueError("all canonical graph inputs must use the current corpus map")
    nodes = []
    edges = []
    node_ids = set()
    edge_keys = set()
    entity_reviews = {
        item["id"]: item for item in decisions.get("entities", [])
    } if decisions else {}
    fact_reviews = {
        item["id"]: item for item in decisions.get("facts", [])
    } if decisions else {}
    decision_by_entity_id = {item_id: item["decision"] for item_id, item in entity_reviews.items()}
    decision_by_fact_id = {item_id: item["decision"] for item_id, item in fact_reviews.items()}
    alias_reviews = {
        item["id"]: item for item in alias_decisions.get("labels", [])
    } if alias_decisions else {}
    decision_by_alias_id = {item_id: item["decision"] for item_id, item in alias_reviews.items()}

    def add_node(node: dict) -> None:
        if node["id"] in node_ids:
            raise ValueError(f"duplicate graph node: {node['id']}")
        node_ids.add(node["id"])
        nodes.append(node)

    def add_edge(source_id: str, relation: str, target_id: str, evidence: str | None = None) -> None:
        edge = {"source": source_id, "relation": relation, "target": target_id}
        if evidence:
            edge["evidence_page_id"] = evidence
        edge_key = (source_id, relation, target_id, evidence)
        if edge_key in edge_keys:
            return
        edge_keys.add(edge_key)
        edges.append(edge)

    services = {item["id"]: item for item in mapping["services"]}
    for service in sorted(services.values(), key=lambda item: item["id"]):
        domain_id = service["id"].replace("service:", "domain:")
        add_node({"id": domain_id, "node_type": "BusinessDomain", "label": service["business_domain"], "status": "base"})
        add_node({"id": service["id"], "node_type": "Service", "label": service["label"], "status": "base"})
        add_edge(service["id"], "BELONGS_TO_DOMAIN", domain_id)

    document_map = {item["page_id"]: item for item in mapping["document_mappings"]}
    for document in sorted(document_map.values(), key=lambda item: item["page_id"]):
        document_id = document["document_id"]
        add_node({
            "id": document_id, "node_type": "Document", "label": document["page_id"],
            "page_id": document["page_id"], "content_sha256": document["content_sha256"], "status": "official_source",
        })
        for service_id in document["service_ids"]:
            add_edge(document_id, "DOCUMENTS_SERVICE", service_id)

    for entity in canonical["entities"]:
        add_node({
            "id": entity["id"], "node_type": entity["ontology_class"], "label": entity["label"],
            "status": _effective_status(
                entity["review_status"], decision_by_entity_id.get(entity["id"]), fact=False,
            ),
        })
        for service_id in entity["parent_service_ids"]:
            add_edge(entity["id"], "BELONGS_TO_SERVICE", service_id)
        for evidence in entity["evidence"]:
            add_edge(f"document:{evidence['page_id']}", "EVIDENCE_FOR", entity["id"], evidence["page_id"])

    for fact in facts["facts"]:
        add_node({
            "id": fact["id"], "node_type": "Fact",
            "label": fact_reviews.get(fact["id"], {}).get("label", fact["predicate"]),
            "predicate": fact["predicate"], "object": fact["object"],
            "evidence": fact["evidence"],
            "status": _effective_status(
                fact["review_status"], decision_by_fact_id.get(fact["id"]), fact=True,
            ),
        })
        add_edge(fact["id"], "ASSERTS_ABOUT", fact["subject_id"])
        page_id = fact["evidence"]["page_id"]
        add_edge(f"document:{page_id}", "EVIDENCE_FOR", fact["id"], page_id)

    for alias in aliases["aliases"]:
        node_id = alias["id"]
        add_node({
            "id": node_id, "node_type": "OfficialLabel", "label": alias["label"],
            "alias_type": alias["alias_type"],
            "status": _effective_status(
                alias["review_status"], decision_by_alias_id.get(node_id), fact=True,
            ),
        })
        add_edge(node_id, "LABEL_FOR", alias["entity_id"])
        for page_id in alias["evidence_page_ids"]:
            add_edge(f"document:{page_id}", "EVIDENCE_FOR", node_id, page_id)

    # A reviewed "merge_existing" page does not create a duplicate entity, but it is
    # still official evidence for the existing Service or Concept. Keep that evidence
    # explicit in the graph so representative pages are not mistaken for unmapped ones.
    for catalog in review_catalogs:
        reviews = catalog.get("reviews", catalog.get("decisions", []))
        for review in reviews:
            if review["decision"] != "merge_existing":
                continue
            page_id = review["evidence"]["page_id"]
            target_id = review["candidate_id"]
            if target_id not in node_ids:
                raise ValueError(f"merge target is not a graph node: {target_id}")
            add_edge(f"document:{page_id}", "EVIDENCE_FOR", target_id, page_id)

    for edge in edges:
        if edge["source"] not in node_ids or edge["target"] not in node_ids:
            raise ValueError(f"dangling graph edge: {edge}")
    nodes.sort(key=lambda item: (item["node_type"], item["id"]))
    edges.sort(key=lambda item: (item["relation"], item["source"], item["target"], item.get("evidence_page_id", "")))
    node_counts = Counter(item["node_type"] for item in nodes)
    edge_counts = Counter(item["relation"] for item in edges)
    entity_decision_counts = Counter(decision_by_entity_id.values())
    fact_decision_counts = Counter(decision_by_fact_id.values())
    alias_status_counts = Counter(
        _effective_status(item["review_status"], decision_by_alias_id.get(item["id"]), fact=True)
        for item in aliases["aliases"]
    )
    alias_decision_counts = Counter(decision_by_alias_id.values())
    decision_counts = entity_decision_counts + fact_decision_counts
    review_item_count = len(decision_by_entity_id) + len(decision_by_fact_id)
    core_approval_complete = bool(review_item_count) and decision_counts["approved"] == review_item_count
    alias_review_complete = (
        len(decision_by_alias_id) == len(aliases["aliases"])
        and alias_decision_counts["pending"] == 0
        and alias_decision_counts["needs_changes"] == 0
    )
    all_aliases_approved = alias_review_complete and alias_decision_counts["approved"] == len(aliases["aliases"])
    graph_status = "canonical_graph_pending_domain_approval"
    if core_approval_complete and all_aliases_approved:
        graph_status = "canonical_graph_all_reviewed_items_approved"
    elif core_approval_complete and alias_review_complete:
        graph_status = "canonical_graph_all_reviews_complete"
    elif core_approval_complete:
        graph_status = "canonical_graph_core_approval_complete_alias_review_pending"
    elif review_item_count and decision_counts["pending"] == 0:
        graph_status = "canonical_graph_domain_review_complete"
    elif review_item_count and decision_counts["pending"] < review_item_count:
        graph_status = "canonical_graph_partial_domain_approval"
    return {
        "schema_version": "1.0.0",
        "status": graph_status,
        "production_impact": "none",
        "source": source,
        "approval": {
            "decision_file": DECISIONS_PATH.relative_to(ROOT).as_posix(),
            "scope": "canonical_entities_core_facts_and_official_labels",
            "core_approval_complete": core_approval_complete,
            "official_label_decision_file": ALIAS_DECISIONS_PATH.relative_to(ROOT).as_posix(),
            "official_label_review_complete": alias_review_complete,
            "all_graph_review_items_complete": core_approval_complete and alias_review_complete,
            "all_graph_review_items_approved": core_approval_complete and all_aliases_approved,
            "counts": dict(sorted(decision_counts.items())),
            "entity_counts": dict(sorted(entity_decision_counts.items())),
            "fact_counts": dict(sorted(fact_decision_counts.items())),
            "official_label_counts": dict(sorted(alias_status_counts.items())),
            "official_label_decision_counts": dict(sorted(alias_decision_counts.items())),
            "all_reviewed_item_decision_counts": dict(sorted((decision_counts + alias_decision_counts).items())),
        },
        "summary": {
            "node_count": len(nodes), "edge_count": len(edges),
            "node_type_counts": dict(sorted(node_counts.items())),
            "relation_counts": dict(sorted(edge_counts.items())),
        },
        "nodes": nodes,
        "edges": edges,
    }


def serialize(output: dict) -> str:
    return json.dumps(output, ensure_ascii=False, indent=2) + "\n"


def current_graph() -> dict:
    return build_graph(
        load_json(MAP_PATH), load_json(CANONICAL_PATH), load_json(FACTS_PATH), load_json(ALIASES_PATH),
        (load_json(P3_GENERAL_PATH), load_json(P3_REMAINING_PATH)), load_json(DECISIONS_PATH),
        load_json(ALIAS_DECISIONS_PATH),
    )


def write_or_check(check: bool) -> int:
    output = serialize(current_graph())
    if check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != output:
            print(f"out of date: {OUTPUT_PATH.relative_to(ROOT)}")
            return 1
        print(f"up to date: {OUTPUT_PATH.relative_to(ROOT)}")
        return 0
    OUTPUT_PATH.write_text(output, encoding="utf-8", newline="\n")
    print(f"wrote: {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    return write_or_check(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
