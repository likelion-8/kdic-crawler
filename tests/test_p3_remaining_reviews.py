from src.crawler.build_p3_remaining_reviews import (
    MAP_PATH, OUTPUT_PATH, TRIAGE_PATH, build_reviews, load_json, serialize,
)


def test_all_remaining_p3_pages_receive_exactly_one_decision():
    output = build_reviews(load_json(MAP_PATH), load_json(TRIAGE_PATH))
    pages = [item["page_id"] for item in output["decisions"]]

    assert output["summary"] == {
        "review_count": 20, "proposal_count": 7, "merge_existing_count": 6, "rejected_count": 7
    }
    assert len(pages) == len(set(pages)) == 20
    assert output["production_impact"] == "none"
    assert output["review_policy"]["heldout_testset_used"] is False


def test_faqs_are_documents_and_stable_services_are_proposals():
    output = build_reviews(load_json(MAP_PATH), load_json(TRIAGE_PATH))
    decisions = {item["page_id"]: item for item in output["decisions"]}
    proposals = {item["id"]: item for item in output["proposals"]}

    assert decisions["dp_faq_page"]["decision"] == "rejected"
    assert decisions["dp_faq_page"]["candidate_id"] is None
    assert proposals["service:protected_financial_product_search"]["ontology_class"] == "Service"
    assert proposals["procedure:insured_financial_company_survey_objection"]["ontology_class"] == "Procedure"
    assert all(item["status"] == "proposed" for item in proposals.values())


def test_checked_in_remaining_reviews_are_reproducible():
    assert OUTPUT_PATH.read_text(encoding="utf-8") == serialize(
        build_reviews(load_json(MAP_PATH), load_json(TRIAGE_PATH))
    )
