import copy

import pytest

from src.crawler.init_fact_gap_review_decisions import build_initial_decisions, load_json
from src.crawler.record_fact_gap_review_decision import record_decision
from src.eval.validate_fact_gap_review_decisions import validate_decisions


def queue_and_decisions():
    from src.crawler.init_fact_gap_review_decisions import QUEUE_PATH

    queue = load_json(QUEUE_PATH)
    return queue, build_initial_decisions(queue)


def test_initial_fact_gap_decisions_cover_all_candidates_without_promotion():
    queue, decisions = queue_and_decisions()
    output = validate_decisions(decisions, queue)

    assert output["valid"] is True
    assert output["review_complete"] is False
    assert output["all_approved"] is False
    assert output["counts"] == {"pending": 6}
    assert decisions["policy"]["automatic_core_fact_promotion"] is False


def test_fact_gap_recording_requires_reviewer_and_preserves_recorded_decision():
    queue, decisions = queue_and_decisions()
    item_id = decisions["candidates"][0]["id"]
    with pytest.raises(ValueError, match="requires a note"):
        record_decision(
            decisions, queue, item_id=item_id, decision="needs_changes",
            reviewer="업무 담당자", reviewed_at="2026-08-12", note=None,
        )
    updated = record_decision(
        decisions, queue, item_id=item_id, decision="approved",
        reviewer="업무 담당자", reviewed_at="2026-08-12", note=None,
    )
    assert next(item for item in updated["candidates"] if item["id"] == item_id)["decision"] == "approved"
    assert validate_decisions(updated, queue)["valid"] is True
    with pytest.raises(ValueError, match="already approved"):
        record_decision(
            updated, queue, item_id=item_id, decision="approved",
            reviewer="다른 담당자", reviewed_at="2026-08-12", note=None,
        )


def test_fact_gap_validator_rejects_stale_or_missing_decisions():
    queue, decisions = queue_and_decisions()
    invalid = copy.deepcopy(decisions)
    invalid["candidates"].pop()
    invalid["source"]["fact_gap_queue"]["sha256"] = "0" * 64

    output = validate_decisions(invalid, queue)

    assert output["valid"] is False
    assert any("missing candidate decisions" in error for error in output["errors"])
    assert any("source hash is stale" in error for error in output["errors"])
