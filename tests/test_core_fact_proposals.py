from src.crawler.build_core_fact_proposals import (
    CANONICAL_PATH, CORPUS_PATH, MAP_PATH, OUTPUT_PATH, build_facts, load_corpus, load_json, serialize,
)


def current_facts():
    return build_facts(load_json(MAP_PATH), load_json(CANONICAL_PATH), load_corpus(CORPUS_PATH))


def test_core_facts_are_literal_source_verified_and_not_runtime_approved():
    output = current_facts()

    assert output["fact_count"] == 15
    assert output["production_impact"] == "none"
    assert output["policies"]["heldout_testset_used"] is False
    assert all(item["review_status"] == "source_verified_pending_domain_approval" for item in output["facts"])
    assert all(len(item["evidence"]["content_sha256"]) == 64 for item in output["facts"])


def test_high_risk_values_keep_scope_and_conditions():
    facts = {item["id"]: item for item in current_facts()["facts"]}

    assert facts["fact:deposit_protection_limit"]["object"] == {
        "type": "MonetaryValue", "value": 100000000, "currency": "KRW",
        "scope": "per_person_per_financial_institution",
    }
    amount = facts["fact:mistaken_remittance_amount_range"]["object"]
    assert (amount["minimum"], amount["maximum"], amount["inclusive"]) == (50000, 100000000, True)
    assert facts["fact:individual_rehabilitation_secured_debt_limit"]["object"]["debt_type"] == "secured"


def test_high_risk_fact_quotes_directly_support_the_claim_scope():
    facts = {item["id"]: item for item in current_facts()["facts"]}

    assert "금융회사별로 1인당 1억원" in facts["fact:deposit_protection_limit"]["evidence"]["quote"]
    prior_action_quote = facts["fact:mistaken_remittance_prior_return_request"]["evidence"]["quote"]
    assert "먼저 반환을 요청해야 합니다" in prior_action_quote
    assert "돌려받지 못한 경우 신청 가능" in prior_action_quote


def test_checked_in_core_facts_are_reproducible():
    assert OUTPUT_PATH.read_text(encoding="utf-8") == serialize(current_facts())
