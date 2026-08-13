from src.eval.validate_ontology_release import OUTPUT_PATH, validate


def test_release_verdict_keeps_runtime_blocked_after_domain_approval():
    output = validate()

    assert output["artifact_integrity_passed"] is True
    assert output["offline_ontology_ready"] is True
    assert output["runtime_ready"] is False
    assert output["domain_approval_complete"] is True
    assert output["official_label_approval_complete"] is True
    assert output["fact_gap_approval_complete"] is True
    assert output["all_human_reviews_complete"] is True
    assert output["all_graph_review_items_complete"] is True
    assert output["retrieval_quality_gate_passed"] is False
    assert output["production_changes_applied"] is False
    assert output["llm_calls_for_validation"] == output["database_calls_for_validation"] == 0
    assert output["checks"]["ontology_schema_aligned"] is True
    assert output["checks"]["llm_wiki_fact_grounding_complete"] is True
    assert output["checks"]["official_label_decision_file_valid"] is True
    assert output["remaining_reviews"] == []
    assert output["summary"]["total_human_review_decisions"] == {"approved": 113}


def test_checked_in_release_verdict_matches_current_artifacts():
    import json

    assert json.loads(OUTPUT_PATH.read_text(encoding="utf-8")) == validate()
