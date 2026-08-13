from src.crawler.build_fact_gap_review_queue import (
    OUTPUT_PATH,
    REVIEW_PATH,
    build_queue,
    generate,
    load_corpus,
    load_json,
)
from src.crawler.build_fact_gap_review_queue import CANONICAL_PATH, MAP_PATH


def current_queue():
    return build_queue(load_json(MAP_PATH), load_json(CANONICAL_PATH), load_corpus())


def test_fact_gap_queue_targets_the_two_domains_without_core_facts():
    queue = current_queue()

    assert queue["summary"]["candidate_count"] == 6
    assert queue["summary"]["business_domain_candidate_counts"] == {
        "고객 미수령금 신청": 3,
        "예금보험금 안내": 3,
    }
    assert queue["summary"]["targeted_zero_core_fact_domains"] == ["고객 미수령금 신청", "예금보험금 안내"]
    assert queue["production_impact"] == "none"
    assert all(candidate["review_status"] == "source_verified_candidate_pending_domain_review" for candidate in queue["candidates"])


def test_fact_gap_candidates_keep_literal_quotes_and_review_qualifiers():
    queue = current_queue()
    candidates = {candidate["id"]: candidate for candidate in queue["candidates"]}
    corpus = load_corpus()

    assert candidates["candidate_fact:deposit_insurance_typical_payment_timing"]["object"]["qualifier"] == "typically"
    assert candidates["candidate_fact:unclaimed_funds_unified_application_start"]["object"]["value"] == "2016-10"
    assert all(item["evidence"]["quote"] in corpus[item["evidence"]["page_id"]]["text"] for item in candidates.values())


def test_checked_in_fact_gap_queue_and_review_markdown_are_reproducible():
    queue, review = generate()

    assert OUTPUT_PATH.read_text(encoding="utf-8") == queue
    assert REVIEW_PATH.read_text(encoding="utf-8") == review
