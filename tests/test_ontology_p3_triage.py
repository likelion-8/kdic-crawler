from src.crawler.build_ontology_p3_triage import (
    CORPUS_PATH,
    CURATED_PROPOSALS_PATH,
    MAP_PATH,
    OUTPUT_PATH,
    build_triage,
    load_corpus,
    load_json,
    serialize,
)


def test_triage_retains_every_p3_metadata_concept_once_at_its_source_page():
    mapping = load_json(MAP_PATH)
    triage = build_triage(mapping, load_corpus(CORPUS_PATH), load_json(CURATED_PROPOSALS_PATH))
    expected_ids = {concept["id"] for concept in mapping["concepts"] if concept["document_count"] == 1}
    actual_ids = [
        concept["id"]
        for candidate in triage["page_candidates"]
        for concept in candidate["source_metadata_concepts"]
    ]

    assert set(actual_ids) == expected_ids
    assert len(actual_ids) == len(set(actual_ids))
    assert triage["summary"]["source_metadata_concept_count"] == len(expected_ids)
    assert triage["production_impact"] == "none"
    assert triage["review_policy"]["heldout_testset_used"] is False


def test_triage_prefers_specific_page_title_variant_and_only_suggests_a_class():
    triage = build_triage(
        load_json(MAP_PATH), load_corpus(CORPUS_PATH), load_json(CURATED_PROPOSALS_PATH)
    )
    by_page = {candidate["page_id"]: candidate for candidate in triage["page_candidates"]}

    procedure = by_page["kmrs_proc"]
    assert procedure["candidate_label"] == "착오송금반환지원 절차"
    assert procedure["suggested_ontology_class"] == "Procedure"
    assert procedure["status"] == "triage_only_pending_domain_review"
    generic = by_page["uc_itgr_aply"]
    assert generic["candidate_label"] == "안내"
    assert generic["review_priority"] == "P3-low"
    assert generic["review_action"] == "verify_or_reject_navigation_label"
    parent = by_page["dp_prdct"]
    assert parent["review_priority"] == "P3-medium"
    assert parent["potential_parent_candidate_ids"] == ["concept:protected_financial_product"]


def test_checked_in_p3_triage_is_reproducible_from_current_corpus():
    assert OUTPUT_PATH.read_text(encoding="utf-8") == serialize(
        build_triage(
            load_json(MAP_PATH), load_corpus(CORPUS_PATH), load_json(CURATED_PROPOSALS_PATH)
        )
    )
