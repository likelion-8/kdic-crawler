from src.crawler.build_p3_general_concept_proposals import (
    MAP_PATH,
    OUTPUT_PATH,
    TRIAGE_PATH,
    build_proposals,
    load_json,
    serialize,
)


def test_general_p3_review_covers_all_high_general_pages_and_stays_offline():
    output = build_proposals(load_json(MAP_PATH), load_json(TRIAGE_PATH))

    assert output["review_count"] == 27
    assert output["proposal_count"] == 21
    assert output["merge_existing_count"] == 5
    assert output["rejected_count"] == 1
    assert output["production_impact"] == "none"
    assert output["review_policy"]["heldout_testset_used"] is False
    assert output["review_policy"]["fact_values_included"] is False
    assert all(proposal["status"] == "proposed" for proposal in output["proposals"])


def test_general_p3_review_types_limit_and_avoids_duplicate_top_level_services():
    output = build_proposals(load_json(MAP_PATH), load_json(TRIAGE_PATH))
    proposals = {proposal["id"]: proposal for proposal in output["proposals"]}
    reviews = {review["page_id"]: review for review in output["reviews"]}

    limit = proposals["monetary_rule:deposit_protection_limit"]
    assert limit["ontology_class"] == "MonetaryRule"
    assert limit["fact_values"] == []
    assert reviews["dp_syst"]["candidate_id"] == "service:deposit_protection"
    assert reviews["dp_syst"]["decision"] == "merge_existing"
    assert reviews["dp_gudn_data"]["decision"] == "rejected"
    assert "service:deposit_protection" not in proposals


def test_checked_in_general_p3_proposals_are_reproducible():
    assert OUTPUT_PATH.read_text(encoding="utf-8") == serialize(
        build_proposals(load_json(MAP_PATH), load_json(TRIAGE_PATH))
    )
