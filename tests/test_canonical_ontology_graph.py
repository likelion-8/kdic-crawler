from src.crawler.build_canonical_ontology_graph import OUTPUT_PATH, current_graph, serialize


def test_graph_has_unique_nodes_and_no_dangling_edges():
    graph = current_graph()
    node_ids = [item["id"] for item in graph["nodes"]]
    known = set(node_ids)

    assert len(node_ids) == len(known)
    assert all(edge["source"] in known and edge["target"] in known for edge in graph["edges"])
    assert graph["summary"]["node_type_counts"]["BusinessDomain"] == 6
    assert graph["summary"]["node_type_counts"]["Service"] >= 6
    assert graph["summary"]["node_type_counts"]["Document"] == 58
    assert graph["summary"]["node_type_counts"]["Fact"] == 15
    assert graph["production_impact"] == "none"


def test_every_fact_and_domain_approved_entity_has_evidence_edge():
    graph = current_graph()
    evidenced = {edge["target"] for edge in graph["edges"] if edge["relation"] == "EVIDENCE_FOR"}
    required = {
        node["id"] for node in graph["nodes"]
        if node["node_type"] == "Fact" or node["status"] == "domain_approved"
    }
    assert required.issubset(evidenced)
    assert graph["status"] == "canonical_graph_all_reviewed_items_approved"
    assert graph["approval"]["counts"] == {"approved": 60}
    assert graph["approval"]["core_approval_complete"] is True
    assert graph["approval"]["all_graph_review_items_complete"] is True
    assert graph["approval"]["all_graph_review_items_approved"] is True
    assert graph["approval"]["official_label_counts"] == {
        "source_verified_domain_approved": 47,
    }
    assert graph["approval"]["official_label_decision_counts"] == {"approved": 47}
    assert graph["approval"]["all_reviewed_item_decision_counts"] == {"approved": 107}


def test_fact_nodes_keep_human_label_and_direct_source_evidence():
    graph = current_graph()
    facts = {node["id"]: node for node in graph["nodes"] if node["node_type"] == "Fact"}

    protection_limit = facts["fact:deposit_protection_limit"]
    assert protection_limit["label"] == "예금자 보호한도 1인·금융회사별 1억원"
    assert protection_limit["evidence"]["page_id"] == "dp_protlmts"
    assert "금융회사별로 1인당 1억원" in protection_limit["evidence"]["quote"]


def test_representative_pages_explicitly_evidence_existing_services():
    graph = current_graph()
    evidence_edges = {
        (edge["source"], edge["target"])
        for edge in graph["edges"]
        if edge["relation"] == "EVIDENCE_FOR"
    }

    assert ("document:dp_syst", "service:deposit_protection") in evidence_edges
    assert ("document:kmrs_itrd", "service:mistaken_remittance_return") in evidence_edges
    assert ("document:dr_system", "service:debt_adjustment") in evidence_edges


def test_checked_in_graph_is_reproducible():
    assert OUTPUT_PATH.read_text(encoding="utf-8") == serialize(current_graph())
