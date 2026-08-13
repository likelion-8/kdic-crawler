"""Build a small source-verified set of high-value ontology fact proposals.

Facts are manually selected from official corpus text and validated by literal quote
presence plus current content hash. They remain pending domain approval and are not
runtime answer data.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
MAP_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
CANONICAL_PATH = ROOT / "ontology" / "kdic-canonical-ontology-draft.json"
CORPUS_PATH = ROOT / "data" / "corpus.jsonl"
OUTPUT_PATH = ROOT / "ontology" / "kdic-core-fact-proposals.json"


FACTS = (
    ("fact:deposit_protection_limit", "monetary_rule:deposit_protection_limit", "has_limit",
     {"type": "MonetaryValue", "value": 100000000, "currency": "KRW", "scope": "per_person_per_financial_institution"},
     "dp_protlmts", "금융회사별로 1인당 1억원까지 보호됩니다."),
    ("fact:deposit_protection_limit_effective_date", "monetary_rule:deposit_protection_limit", "effective_from",
     {"type": "Date", "value": "2025-09-01"},
     "dp_faq_page", "2025년 9월 1일부터 예금보호한도 1억원이 적용되고 있습니다."),
    ("fact:mistaken_remittance_amount_range", "eligibility:mistaken_remittance_return_support", "has_monetary_range",
     {"type": "MonetaryRange", "minimum": 50000, "maximum": 100000000, "currency": "KRW", "inclusive": True},
     "kmrs_aply_trgt", "신청 가능 한도는 착오송금 건당 5만원 이상 ~ 1억원 이하 입니다."),
    ("fact:mistaken_remittance_application_deadline", "eligibility:mistaken_remittance_return_support", "has_time_rule",
     {"type": "Duration", "value": 1, "unit": "year", "anchor": "mistaken_remittance_date", "inclusive_text": "이내"},
     "kmrs_aply_trgt", "잘못 이체한 날로부터 1년 이내까지 신청 가능합니다"),
    ("fact:mistaken_remittance_prior_return_request", "eligibility:mistaken_remittance_return_support", "requires_prior_action",
     {"type": "Requirement", "action": "request_return_via_transfer_provider", "must_remain_unreturned": True},
     "kmrs_aply_trgt", "이체 시 이용한 금융회사, 간편송금업체 등을 통해 먼저 반환을 요청해야 합니다.\n금융회사, 간편송금업체 등을 통해서도 돌려받지 못한 경우 신청 가능합니다."),
    ("fact:mistaken_remittance_supported_date_threshold", "eligibility:mistaken_remittance_self_check", "has_date_threshold",
     {"type": "DateThreshold", "value": "2021-07-06", "source_operator": "이후"},
     "sender_qlfc_check", "착오송금일이 2021년 7월 6일 이후입니까?"),
    ("fact:recipient_voluntary_return_deadline", "concept:mistaken_remittance_recipient_cautions", "has_time_rule",
     {"type": "Duration", "value": 2, "unit": "week", "anchor": "assignment_notice_delivery"},
     "receiver_attention", "자진반환 기한(양도통지문 송달일로부터 2주) 내에 반환해주시기 바랍니다."),
    ("fact:visit_reception_hours", "contact:mistaken_remittance_visit", "has_operating_hours",
     {"type": "TimeWindow", "days": "weekday", "start": "09:00", "end": "17:00"},
     "mtrs_vst_rcpt", "방문접수는 평일 09:00 ~ 17:00까지 운영됩니다."),
    ("fact:visit_reception_lunch_break", "contact:mistaken_remittance_visit", "has_break_hours",
     {"type": "TimeWindow", "start": "12:00", "end": "13:00"},
     "mtrs_vst_rcpt", "점심시간 12:00 ~ 13:00"),
    ("fact:individual_rehabilitation_unsecured_debt_limit", "concept:individual_rehabilitation", "has_monetary_limit",
     {"type": "MonetaryValue", "value": 1000000000, "currency": "KRW", "debt_type": "unsecured", "operator": "not_exceed"},
     "dr_psn_rg", "무담보 채무의 경우 10억 원, 담보부 채무의 경우 15억 원을 넘지 않아야 합니다."),
    ("fact:individual_rehabilitation_secured_debt_limit", "concept:individual_rehabilitation", "has_monetary_limit",
     {"type": "MonetaryValue", "value": 1500000000, "currency": "KRW", "debt_type": "secured", "operator": "not_exceed"},
     "dr_psn_rg", "무담보 채무의 경우 10억 원, 담보부 채무의 경우 15억 원을 넘지 않아야 합니다."),
    ("fact:individual_rehabilitation_repayment_period", "concept:individual_rehabilitation", "has_time_rule",
     {"type": "Duration", "maximum": 5, "unit": "year"},
     "dr_psn_rg", "변제기간\n5년을 초과할 수 없습니다."),
    ("fact:individual_rehabilitation_income_requirement", "concept:individual_rehabilitation", "has_eligibility",
     {"type": "Requirement", "requirement": "continuing_regular_reliable_income"},
     "dr_psn_rg", "정기적이고, 확실한 수입을 계속하여 얻을 가능성이 있는 사람이어야 합니다."),
    ("fact:concealed_assets_reward_maximum", "contact:concealed_assets_report_center", "has_monetary_limit",
     {"type": "MonetaryValue", "value": 3000000000, "currency": "KRW", "operator": "maximum"},
     "ha_center", "최대 30억원의 포상금을 지급하고 있음"),
    ("fact:concealed_assets_reward_rate", "contact:concealed_assets_report_center", "has_percentage_range",
     {"type": "PercentageRange", "minimum": 5, "maximum": 20, "basis": "recovered_amount_after_costs"},
     "ha_center", "회수금액(소요비용 공제)의 5~20% 수준에서 차등 산정"),
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_corpus(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8") as f:
        return {row["page_id"]: row for line in f if (row := json.loads(line))}


def build_facts(mapping: dict, canonical: dict, corpus: dict[str, dict]) -> dict:
    if mapping["source"] != canonical["source"]:
        raise ValueError("canonical draft must use the current document map")
    document_map = {item["page_id"]: item for item in mapping["document_mappings"]}
    valid_subjects = {item["id"] for item in canonical["entities"]} | {item["id"] for item in canonical["base_services"]}
    facts = []
    seen_ids = set()
    for fact_id, subject_id, predicate, value, page_id, quote in FACTS:
        if fact_id in seen_ids:
            raise ValueError(f"duplicate fact id: {fact_id}")
        seen_ids.add(fact_id)
        if subject_id not in valid_subjects:
            raise ValueError(f"unknown fact subject: {subject_id}")
        if quote not in corpus[page_id]["text"]:
            raise ValueError(f"quote not found in official corpus text: {fact_id}")
        facts.append({
            "id": fact_id,
            "subject_id": subject_id,
            "predicate": predicate,
            "object": value,
            "review_status": "source_verified_pending_domain_approval",
            "evidence": {
                "page_id": page_id,
                "source_url": corpus[page_id]["source_url"],
                "content_sha256": document_map[page_id]["content_sha256"],
                "quote": quote,
            },
        })
    return {
        "schema_version": "1.0.0",
        "status": "core_facts_source_verified_pending_domain_approval",
        "production_impact": "none",
        "source": mapping["source"],
        "policies": {
            "literal_source_quote_required": True,
            "heldout_testset_used": False,
            "runtime_use": "prohibited_until_domain_approval_and_evaluation",
            "review_on_content_hash_change": True,
        },
        "fact_count": len(facts),
        "facts": facts,
    }


def serialize(output: dict) -> str:
    return json.dumps(output, ensure_ascii=False, indent=2) + "\n"


def write_or_check(check: bool) -> int:
    output = serialize(build_facts(load_json(MAP_PATH), load_json(CANONICAL_PATH), load_corpus(CORPUS_PATH)))
    if check:
        if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != output:
            print(f"out of date: {OUTPUT_PATH.relative_to(ROOT)}")
            return 1
        print(f"up to date: {OUTPUT_PATH.relative_to(ROOT)}")
        return 0
    OUTPUT_PATH.write_text(output, encoding="utf-8", newline="\n")
    print(f"wrote: {OUTPUT_PATH.relative_to(ROOT)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    return write_or_check(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
