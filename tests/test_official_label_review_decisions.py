import copy

import pytest

from src.crawler.init_official_label_review_decisions import build_initial_decisions, load_json
from src.crawler.record_official_label_review_decision import record_decision
from src.eval.validate_official_label_review_decisions import validate_decisions


def aliases_and_decisions():
    from src.crawler.init_official_label_review_decisions import ALIASES_PATH

    aliases = load_json(ALIASES_PATH)
    return aliases, build_initial_decisions(aliases)


def test_initial_decisions_cover_all_official_labels_without_approval():
    aliases, decisions = aliases_and_decisions()
    output = validate_decisions(decisions, aliases)

    assert output["valid"] is True
    assert output["all_approved"] is False
    assert output["counts"] == {"pending": 47}
    assert decisions["policy"]["contextual_labels_are_synonyms"] is False


def test_official_label_recording_requires_reviewer_and_preserves_decision():
    aliases, decisions = aliases_and_decisions()
    item_id = decisions["labels"][0]["id"]
    updated = record_decision(
        decisions, aliases, item_id=item_id, decision="approved",
        reviewer="업무 담당자", reviewed_at="2026-08-12", note=None,
    )
    assert next(item for item in updated["labels"] if item["id"] == item_id)["decision"] == "approved"
    assert validate_decisions(updated, aliases)["valid"] is True
    with pytest.raises(ValueError, match="already approved"):
        record_decision(
            updated, aliases, item_id=item_id, decision="approved",
            reviewer="다른 담당자", reviewed_at="2026-08-12", note=None,
        )


def test_validator_rejects_missing_or_stale_official_label_decisions():
    aliases, decisions = aliases_and_decisions()
    invalid = copy.deepcopy(decisions)
    invalid["labels"].pop()
    invalid["source"]["official_labels"]["sha256"] = "0" * 64

    output = validate_decisions(invalid, aliases)

    assert output["valid"] is False
    assert any("missing official-label decisions" in error for error in output["errors"])
    assert any("source hash is stale" in error for error in output["errors"])
