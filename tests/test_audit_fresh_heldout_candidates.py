from pathlib import Path

from src.eval.audit_fresh_heldout_candidates import (
    FROZEN_PATH,
    OUTPUT_PATH,
    REVIEW_PATH,
    build_review_markdown,
    inspect_rows,
)


def test_candidate_inventory_rejects_frozen_overlap_and_missing_provenance():
    output = inspect_rows(
        FROZEN_PATH,
        [{"test_id": "same", "question": "같은 질문", "expected_sources": ["page"]}],
        {"same"}, {"같은질문"},
    )

    assert output["fresh_heldout_eligible"] is False
    assert "currently_used_as_frozen_ontology_assist_heldout" in output["ineligible_reasons"]
    assert "missing_required_fresh_holdout_provenance" in output["ineligible_reasons"]


def test_candidate_inventory_accepts_only_independent_provenanced_metadata():
    candidate_path = FROZEN_PATH.parent / "independent.jsonl"
    output = inspect_rows(
        candidate_path,
        [{
            "test_id": "fresh", "question": "새 질문", "expected_sources": ["page"],
            "query_form": "user_paraphrase", "authored_by": "reviewer", "authored_at": "2026-08-12",
            "business_function": "업무", "question_type": "fact", "intent": "informational",
        }],
        {"old"}, {"기존질문"},
    )

    assert output["fresh_heldout_eligible"] is True
    assert output["frozen_normalized_question_overlap_count"] == 0


def test_checked_in_inventory_is_reproducible():
    from src.eval.audit_fresh_heldout_candidates import generate

    inventory, review = generate()
    assert OUTPUT_PATH.read_text(encoding="utf-8") == inventory
    assert REVIEW_PATH.read_text(encoding="utf-8") == review
