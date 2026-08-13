from src.eval.eval_canonical_ontology_assist import assist_ranking, build_label_index, evaluate


def test_assist_uses_only_exact_official_aliases_and_preserves_order():
    canonical = {"entities": [{
        "id": "concept:x", "label": "보호대상 금융회사", "evidence": [{"page_id": "gold"}],
    }]}
    aliases = {"aliases": [
        {"id": "alias:exact", "entity_id": "concept:x", "label": "보호대상금융회사", "alias_type": "official_label_variant", "evidence_page_ids": ["gold"]},
        {"id": "alias:context", "entity_id": "concept:x", "label": "금융회사 개요", "alias_type": "contextual_label", "evidence_page_ids": ["other"]},
    ]}
    decisions = {"labels": [
        {"id": "alias:exact", "decision": "approved"},
        {"id": "alias:context", "decision": "approved"},
    ]}
    index = build_label_index(canonical, aliases, decisions)

    assert {item["label"] for item in index} == {"보호대상 금융회사", "보호대상금융회사"}
    assert assist_ranking(["a", "gold", "b"], ["gold"]) == ["gold", "a", "b"]


def test_assist_excludes_unapproved_exact_official_aliases():
    canonical = {"entities": []}
    aliases = {"aliases": [{
        "id": "alias:pending", "entity_id": "concept:x", "label": "보호대상금융회사",
        "alias_type": "official_label_variant", "evidence_page_ids": ["gold"],
    }]}
    decisions = {"labels": [{"id": "alias:pending", "decision": "pending"}]}

    assert build_label_index(canonical, aliases, decisions) == []


def test_evaluation_is_offline_and_gate_detects_regression():
    rows = {"q": {"test_id": "q", "question": "보호대상 금융회사", "expected_sources": ["gold"]}}
    baseline = {"per_row_retrieval": [{"test_id": "q", "gold": ["gold"], "top5_pages": ["gold", "other"]}]}
    index = [{"label": "보호대상 금융회사", "normalized": "보호대상금융회사", "page_ids": ["wrong"]}]
    output = evaluate(rows, baseline, index)

    assert output["llm_calls"] == output["database_calls"] == 0
    assert output["heldout_tuning"] is False
    assert output["quality_gate"]["passed"] is False
