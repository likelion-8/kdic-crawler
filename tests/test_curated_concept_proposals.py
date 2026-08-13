from src.crawler.build_curated_concept_proposals import (
    CORPUS_PATH,
    MAP_PATH,
    OUTPUT_PATH,
    build_proposals,
    load_corpus,
    load_json,
    serialize,
)


def test_p1_p2_review_covers_every_repeated_metadata_concept_without_approving_runtime_use():
    proposals = build_proposals(load_json(MAP_PATH), load_corpus(CORPUS_PATH))

    assert proposals["status"] == "agent_reviewed_p1_p2_pending_domain_approval"
    assert proposals["production_impact"] == "none"
    assert proposals["review_policy"]["heldout_testset_used"] is False
    assert len(proposals["metadata_concept_reviews"]) == 14
    assert {review["decision"] for review in proposals["metadata_concept_reviews"]} == {
        "proposed", "needs_split", "rejected"
    }
    assert all(candidate["status"] == "proposed" for candidate in proposals["candidates"])
    assert all(candidate["evidence"] for candidate in proposals["candidates"])


def test_broad_protection_target_is_split_and_mislabeled_faq_is_not_evidence():
    proposals = build_proposals(load_json(MAP_PATH), load_corpus(CORPUS_PATH))
    by_source = {review["source_concept_id"]: review for review in proposals["metadata_concept_reviews"]}
    by_candidate = {candidate["id"]: candidate for candidate in proposals["candidates"]}

    protection_target = by_source["concept:c_3c48ca055b59c51b"]
    assert protection_target["decision"] == "needs_split"
    assert protection_target["candidate_ids"] == [
        "actor:protected_financial_institution", "concept:protected_financial_product"
    ]
    application = by_source["concept:c_1e0253f62c754140"]
    assert application["excluded_page_ids"] == ["faq_nramt"]
    assert "faq_nramt" not in {item["page_id"] for item in by_candidate[
        "concept:unclaimed_funds_integrated_application"
    ]["evidence"]}


def test_p2_navigation_labels_are_rejected_and_mistaken_remitter_is_an_actor():
    proposals = build_proposals(load_json(MAP_PATH), load_corpus(CORPUS_PATH))
    by_source = {review["source_concept_id"]: review for review in proposals["metadata_concept_reviews"]}
    by_candidate = {candidate["id"]: candidate for candidate in proposals["candidates"]}

    for source_id in {
        "concept:c_dbc468a14b601d5d", "concept:c_dc015df639b9ffb5",
        "concept:c_8497eb60b73b67fd", "concept:c_51f8fbdf3ff9e253",
    }:
        assert by_source[source_id]["decision"] == "rejected"
    assert by_source["concept:c_5b20f0b6b9ebb5f9"]["candidate_ids"] == ["actor:mistaken_remitter"]
    assert by_candidate["actor:mistaken_remitter"]["ontology_class"] == "Actor"


def test_checked_in_proposals_are_reproducible_from_current_corpus():
    assert OUTPUT_PATH.read_text(encoding="utf-8") == serialize(
        build_proposals(load_json(MAP_PATH), load_corpus(CORPUS_PATH))
    )
