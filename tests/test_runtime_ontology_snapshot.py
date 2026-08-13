from src.crawler.build_runtime_ontology_snapshot import build_snapshot


def test_snapshot_only_contains_items_with_explicit_approval():
    canonical = {"source": {"document_count": 1}, "entities": [{"id": "entity:a"}, {"id": "entity:b"}]}
    facts = {"facts": [{"id": "fact:a"}, {"id": "fact:b"}]}
    decisions = {
        "entities": [{"id": "entity:a", "decision": "approved"}, {"id": "entity:b", "decision": "rejected"}],
        "facts": [{"id": "fact:a", "decision": "approved"}, {"id": "fact:b", "decision": "pending"}],
    }

    snapshot = build_snapshot(canonical, facts, decisions)

    assert [item["id"] for item in snapshot["approved_entities"]] == ["entity:a"]
    assert [item["id"] for item in snapshot["approved_facts"]] == ["fact:a"]
    assert snapshot["production_impact"] == "candidate_only_no_automatic_rag_integration"
