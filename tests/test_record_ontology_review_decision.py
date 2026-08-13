import pytest

from src.crawler.init_ontology_review_decisions import build_initial_decisions, load_json
from src.crawler.record_ontology_review_decision import record_decision
from src.eval.validate_ontology_review_decisions import validate_decisions


def inputs():
    from src.crawler.init_ontology_review_decisions import CANONICAL_PATH, FACTS_PATH

    canonical = load_json(CANONICAL_PATH)
    facts = load_json(FACTS_PATH)
    return build_initial_decisions(canonical, facts), canonical, facts


def test_record_decision_updates_exactly_one_pending_item_after_validation():
    decisions, canonical, facts = inputs()
    item_id = decisions["entities"][0]["id"]

    updated = record_decision(
        decisions, canonical, facts, kind="entity", item_id=item_id, decision="approved",
        reviewer="업무 담당자", reviewed_at="2026-08-12", note=None,
    )

    target = next(item for item in updated["entities"] if item["id"] == item_id)
    assert target["decision"] == "approved"
    assert target["reviewed_by"] == "업무 담당자"
    assert decisions["entities"][0]["decision"] == "pending"
    assert validate_decisions(updated, canonical, facts)["valid"] is True


def test_record_decision_refuses_missing_reason_and_overwrite():
    decisions, canonical, facts = inputs()
    item_id = decisions["facts"][0]["id"]
    with pytest.raises(ValueError, match="requires a note"):
        record_decision(
            decisions, canonical, facts, kind="fact", item_id=item_id, decision="rejected",
            reviewer="업무 담당자", reviewed_at="2026-08-12", note=None,
        )
    approved = record_decision(
        decisions, canonical, facts, kind="fact", item_id=item_id, decision="approved",
        reviewer="업무 담당자", reviewed_at="2026-08-12", note=None,
    )
    with pytest.raises(ValueError, match="already approved"):
        record_decision(
            approved, canonical, facts, kind="fact", item_id=item_id, decision="approved",
            reviewer="다른 담당자", reviewed_at="2026-08-12", note=None,
        )
