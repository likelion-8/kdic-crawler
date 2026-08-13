import copy

from src.crawler.init_ontology_review_decisions import build_initial_decisions, load_json
from src.eval.validate_ontology_review_decisions import validate_decisions


def _inputs():
    from src.crawler.init_ontology_review_decisions import CANONICAL_PATH, FACTS_PATH

    return load_json(CANONICAL_PATH), load_json(FACTS_PATH)


def test_initial_decisions_cover_every_entity_and_fact_without_approval():
    canonical, facts = _inputs()
    output = validate_decisions(build_initial_decisions(canonical, facts), canonical, facts)

    assert output["valid"] is True
    assert output["review_complete"] is False
    assert output["all_approved"] is False
    assert output["counts"]["total"] == {"pending": 60}


def test_non_pending_decision_requires_reviewer_and_timestamp():
    canonical, facts = _inputs()
    decisions = build_initial_decisions(canonical, facts)
    decisions["entities"][0]["decision"] = "approved"
    invalid = validate_decisions(decisions, canonical, facts)

    assert invalid["valid"] is False
    assert any("needs reviewed_by" in error for error in invalid["errors"])

    decisions["entities"][0].update({"reviewed_by": "도메인 담당자", "reviewed_at": "2026-08-12"})
    valid = validate_decisions(decisions, canonical, facts)
    assert valid["valid"] is True


def test_validator_rejects_missing_or_stale_decisions():
    canonical, facts = _inputs()
    decisions = copy.deepcopy(build_initial_decisions(canonical, facts))
    decisions["facts"].pop()
    decisions["source"]["core_facts"]["sha256"] = "0" * 64
    output = validate_decisions(decisions, canonical, facts)

    assert output["valid"] is False
    assert any("missing fact decisions" in error for error in output["errors"])
    assert any("source hashes are stale" in error for error in output["errors"])
