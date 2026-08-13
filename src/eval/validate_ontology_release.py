"""Validate ontology artifact integrity and write the final release-readiness verdict."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.crawler.build_canonical_ontology_draft import CHECKLIST_PATH, OUTPUT_PATH as DRAFT_PATH, generate
from src.crawler.build_canonical_ontology_graph import OUTPUT_PATH as GRAPH_PATH, current_graph, serialize as graph_serialize
from src.crawler.build_core_fact_proposals import (
    CANONICAL_PATH, CORPUS_PATH, MAP_PATH, OUTPUT_PATH as FACTS_PATH,
    build_facts, load_corpus, load_json, serialize as facts_serialize,
)
from src.crawler.build_official_ontology_aliases import (
    OUTPUT_PATH as ALIASES_PATH, build_aliases, serialize as aliases_serialize,
)
from src.crawler.build_llm_wiki import WIKI_PATH, build_wiki, load_inputs as load_wiki_inputs
from src.crawler.build_neo4j_ontology_export import OUTPUT_DIR as NEO4J_DIR, build_export
from src.crawler.build_ontology_document_coverage import (
    OUTPUT_PATH as COVERAGE_PATH,
    P3_REMAINING_PATH as COVERAGE_REMAINING_PATH,
    build_coverage,
    serialize as coverage_serialize,
)
from src.crawler.build_fact_gap_review_queue import (
    OUTPUT_PATH as FACT_GAP_QUEUE_PATH,
    REVIEW_PATH as FACT_GAP_REVIEW_PATH,
    generate as generate_fact_gap_queue,
)
from src.crawler.build_ontology_domain_review_packets import (
    OUTPUT_DIR as DOMAIN_REVIEW_PACKETS_DIR,
    generate as generate_domain_review_packets,
)
from src.crawler.build_obsidian_ontology_vault import VAULT_PATH
from src.crawler.build_runtime_ontology_snapshot import OUTPUT_PATH as RUNTIME_SNAPSHOT_PATH
from src.eval.analyze_canonical_ontology_assist import (
    OUTPUT_PATH as ASSIST_DIAGNOSIS_PATH,
    REVIEW_PATH as ASSIST_DIAGNOSIS_REVIEW_PATH,
    generate as generate_assist_diagnosis,
)
from src.eval.audit_fresh_heldout_candidates import (
    OUTPUT_PATH as FRESH_HELDOUT_INVENTORY_PATH,
    REVIEW_PATH as FRESH_HELDOUT_INVENTORY_REVIEW_PATH,
    generate as generate_fresh_heldout_inventory,
)
from src.eval.validate_fact_gap_review_decisions import current_validation as current_fact_gap_review_validation
from src.eval.eval_canonical_ontology_assist import (
    ALIASES_PATH as EVAL_ALIASES_PATH, ALIAS_DECISIONS_PATH as EVAL_ALIAS_DECISIONS_PATH,
    BASELINE_PATH, CANONICAL_PATH as EVAL_CANONICAL_PATH,
    OUTPUT_PATH as SHADOW_PATH, build_label_index, evaluate, load_rows,
)
from src.eval.validate_ontology_review_decisions import current_validation as current_review_validation
from src.eval.validate_official_label_review_decisions import current_validation as current_official_label_validation
from src.eval.validate_ontology_schema_alignment import current_validation as current_schema_validation


OUTPUT_PATH = ROOT / "results" / "ontology" / "release_readiness.json"


def _equal(path: Path, expected: str) -> bool:
    return path.exists() and path.read_text(encoding="utf-8") == expected


def _directory_markdown_matches(path: Path, expected: dict[str, str]) -> bool:
    existing = {
        item.relative_to(path).as_posix(): item.read_text(encoding="utf-8")
        for item in path.rglob("*.md")
    } if path.exists() else {}
    return existing == expected


def validate() -> dict:
    checks = {}
    draft_json, checklist = generate()
    checks["canonical_draft_reproducible"] = _equal(DRAFT_PATH, draft_json)
    checks["approval_checklist_reproducible"] = _equal(CHECKLIST_PATH, checklist)

    canonical = load_json(CANONICAL_PATH)
    mapping = load_json(MAP_PATH)
    corpus = load_corpus(CORPUS_PATH)
    facts = build_facts(mapping, canonical, corpus)
    checks["core_facts_reproducible"] = _equal(FACTS_PATH, facts_serialize(facts))
    aliases = build_aliases(canonical, corpus)
    checks["official_aliases_reproducible"] = _equal(ALIASES_PATH, aliases_serialize(aliases))
    graph = current_graph()
    checks["canonical_graph_reproducible"] = _equal(GRAPH_PATH, graph_serialize(graph))
    schema_validation = current_schema_validation()
    checks["ontology_schema_aligned"] = schema_validation["valid"]

    neo4j = build_export(graph)
    neo4j_existing = {path.name for path in NEO4J_DIR.iterdir() if path.is_file()} if NEO4J_DIR.exists() else set()
    checks["neo4j_export_reproducible"] = (
        neo4j_existing == set(neo4j)
        and all(_equal(NEO4J_DIR / name, content) for name, content in neo4j.items())
    )
    note_count = len(list((VAULT_PATH / "노드").rglob("*.md"))) if VAULT_PATH.exists() else 0
    checks["obsidian_vault_complete"] = note_count == graph["summary"]["node_count"]
    coverage = build_coverage(mapping, graph, load_json(COVERAGE_REMAINING_PATH))
    checks["document_semantic_coverage_reproducible"] = _equal(COVERAGE_PATH, coverage_serialize(coverage))
    fact_gap_queue, fact_gap_review = generate_fact_gap_queue()
    checks["fact_gap_review_queue_reproducible"] = (
        _equal(FACT_GAP_QUEUE_PATH, fact_gap_queue)
        and _equal(FACT_GAP_REVIEW_PATH, fact_gap_review)
    )
    domain_review_packets = generate_domain_review_packets()
    checks["domain_review_packets_reproducible"] = all(
        _equal(DOMAIN_REVIEW_PACKETS_DIR / name, content)
        for name, content in domain_review_packets.items()
    )
    wiki_graph, wiki_corpus, wiki_fact_gaps, wiki_fact_gap_decisions = load_wiki_inputs()
    wiki = build_wiki(wiki_graph, wiki_corpus, wiki_fact_gaps, wiki_fact_gap_decisions)
    checks["llm_wiki_reproducible"] = _directory_markdown_matches(WIKI_PATH, wiki)
    wiki_text = "\n".join(wiki.values())
    approved_fact_nodes = [node for node in graph["nodes"] if node["node_type"] == "Fact"]
    checks["llm_wiki_fact_grounding_complete"] = all(
        node["label"] in wiki_text
        and node["evidence"]["page_id"] in wiki_text
        and node["evidence"]["content_sha256"] in wiki_text
        and all(
            line in wiki_text
            for line in node["evidence"]["quote"].splitlines()
            if line
        )
        for node in approved_fact_nodes
    )
    review_validation = current_review_validation()
    checks["review_decision_file_valid"] = review_validation["valid"]
    official_label_validation = current_official_label_validation()
    checks["official_label_decision_file_valid"] = official_label_validation["valid"]
    fact_gap_review_validation = current_fact_gap_review_validation()
    checks["fact_gap_review_decision_file_valid"] = fact_gap_review_validation["valid"]

    shadow = evaluate(
        load_rows(), load_json(BASELINE_PATH),
        build_label_index(
            load_json(EVAL_CANONICAL_PATH), load_json(EVAL_ALIASES_PATH),
            load_json(EVAL_ALIAS_DECISIONS_PATH),
        ),
    )
    checks["shadow_evaluation_reproducible"] = _equal(
        SHADOW_PATH, json.dumps(shadow, ensure_ascii=False, indent=2) + "\n"
    )
    assist_diagnosis, assist_diagnosis_review = generate_assist_diagnosis()
    checks["shadow_evaluation_diagnosis_reproducible"] = (
        _equal(ASSIST_DIAGNOSIS_PATH, assist_diagnosis)
        and _equal(ASSIST_DIAGNOSIS_REVIEW_PATH, assist_diagnosis_review)
    )
    fresh_heldout_inventory, fresh_heldout_inventory_review = generate_fresh_heldout_inventory()
    checks["fresh_heldout_candidate_inventory_reproducible"] = (
        _equal(FRESH_HELDOUT_INVENTORY_PATH, fresh_heldout_inventory)
        and _equal(FRESH_HELDOUT_INVENTORY_REVIEW_PATH, fresh_heldout_inventory_review)
    )
    domain_approval_complete = review_validation["all_approved"]
    official_label_approval_complete = official_label_validation["all_approved"]
    fact_gap_approval_complete = fact_gap_review_validation["all_approved"]
    all_human_reviews_complete = (
        domain_approval_complete and official_label_approval_complete and fact_gap_approval_complete
    )
    retrieval_quality_gate_passed = shadow["quality_gate"]["passed"]
    checks["blocked_runtime_snapshot_absent"] = (
        domain_approval_complete and retrieval_quality_gate_passed
    ) or not RUNTIME_SNAPSHOT_PATH.exists()
    artifact_integrity_passed = all(checks.values())
    return {
        "status": (
            "offline_review_complete_runtime_blocked"
            if artifact_integrity_passed and all_human_reviews_complete
            else "offline_core_complete_pending_reviews_runtime_blocked"
            if artifact_integrity_passed
            else "artifact_integrity_failed"
        ),
        "artifact_integrity_passed": artifact_integrity_passed,
        "offline_ontology_ready": artifact_integrity_passed,
        "runtime_ready": artifact_integrity_passed and domain_approval_complete and official_label_approval_complete and retrieval_quality_gate_passed,
        "domain_approval_complete": domain_approval_complete,
        "official_label_approval_complete": official_label_approval_complete,
        "fact_gap_approval_complete": fact_gap_approval_complete,
        "all_human_reviews_complete": all_human_reviews_complete,
        "all_graph_review_items_complete": graph["approval"]["all_graph_review_items_complete"],
        "retrieval_quality_gate_passed": retrieval_quality_gate_passed,
        "production_changes_applied": False,
        "llm_calls_for_validation": 0,
        "database_calls_for_validation": 0,
        "summary": {
            "base_services": canonical["summary"]["base_service_count"],
            "canonical_entities_domain_approved": review_validation["counts"]["entities"].get("approved", 0),
            "core_facts_domain_approved": review_validation["counts"]["facts"].get("approved", 0),
            "official_labels_domain_approved": official_label_validation["counts"].get("approved", 0),
            "graph_nodes": graph["summary"]["node_count"],
            "graph_edges": graph["summary"]["edge_count"],
            "documents_with_semantic_evidence": coverage["summary"]["semantic_evidence_count"],
            "documents_retained_as_document_only": coverage["summary"]["document_only_count"],
            "documents_without_coverage_decision": coverage["summary"]["unresolved_count"],
            "source_verified_fact_gap_candidates": json.loads(fact_gap_queue)["summary"]["candidate_count"],
            "fact_gap_review_decisions": fact_gap_review_validation["counts"],
            "shadow_ranking_changes": json.loads(assist_diagnosis)["summary"]["ranking_changed_count"],
            "shadow_recall_at_1_regressions": json.loads(assist_diagnosis)["summary"]["impact_counts"].get("regressed_first_gold_rank", 0),
            "existing_fresh_heldout_candidates": json.loads(fresh_heldout_inventory)["summary"]["fresh_heldout_eligible_files"],
            "review_decisions": review_validation["counts"]["total"],
            "official_label_review_decisions": official_label_validation["counts"],
            "total_human_review_decisions": {
                "approved": (
                    review_validation["counts"]["total"].get("approved", 0)
                    + official_label_validation["counts"].get("approved", 0)
                    + fact_gap_review_validation["counts"].get("approved", 0)
                )
            },
            "ontology_schema_alignment": {
                "valid": schema_validation["valid"],
                "declared_classes": schema_validation["declared_class_count"],
                "declared_relations": schema_validation["declared_relation_count"],
            },
        },
        "retrieval_shadow": {
            "baseline": shadow["baseline"], "assisted": shadow["assisted"], "delta": shadow["delta"],
        },
        "checks": checks,
        "remaining_reviews": [] if all_human_reviews_complete else [
            item for condition, item in (
                (not official_label_approval_complete, "47 official label variants require domain review."),
                (not fact_gap_approval_complete, "6 source-verified fact-gap candidates require domain review."),
            ) if condition
        ],
        "remaining_actions": [
            "Promote the 6 approved fact-gap candidates through a separate core-fact change before answer use.",
            "Build a fresh independently authored held-out set and recover the Recall@1 regression before runtime integration.",
        ],
        "blockers": [
            blocker for condition, blocker in (
                (not domain_approval_complete, "45 canonical entities and 15 core facts require domain-owner approval."),
                (not review_validation["valid"], "Ontology review decision file is missing or inconsistent with the current draft."),
                (not official_label_approval_complete, "Official label review is incomplete; label-assisted retrieval is prohibited."),
                (not retrieval_quality_gate_passed, "Exact-label ontology assist regressed Recall@1; production integration is prohibited."),
                (json.loads(fresh_heldout_inventory)["summary"]["fresh_heldout_eligible_files"] == 0, "No existing testset qualifies as a fresh ontology-assist held-out set; independently authored questions are required."),
            ) if condition
        ],
    }


def main() -> int:
    output = validate()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("ontology release readiness")
    print("  artifact integrity:", output["artifact_integrity_passed"])
    print("  offline ontology ready:", output["offline_ontology_ready"])
    print("  runtime ready:", output["runtime_ready"])
    print("  blockers:", output["blockers"])
    return 0 if output["artifact_integrity_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
