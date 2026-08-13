"""Curate P3-high general concepts into source-linked ontology proposals.

This pass covers the high-priority P3 pages that the deterministic triage classified
as generic ``Concept``. Decisions are explicit: propose a typed entity, merge into an
existing Service, or reject a content-navigation page. No fact values are promoted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
MAP_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
TRIAGE_PATH = ROOT / "ontology" / "kdic-p3-concept-triage.json"
OUTPUT_PATH = ROOT / "ontology" / "kdic-p3-general-concept-proposals.json"
ALLOWED_CLASSES = frozenset({"Actor", "Concept", "MonetaryRule", "Service"})


REVIEWS = (
    ("dr_psn_rg", "proposed", "concept:individual_rehabilitation", "개인회생", "Concept"),
    ("uc_gudn", "merge_existing", "service:unclaimed_funds", "미수령금 통합조회·신청", "Service"),
    ("mtrs_rel_law", "proposed", "concept:mistaken_remittance_regulations", "착오송금 반환지원 관련 법령·규정", "Concept"),
    ("ms_trgt_fnst", "proposed", "actor:deposit_insurance_payment_target_institution", "보험금 지급대상 금융회사", "Actor"),
    ("dp_protlmts", "proposed", "monetary_rule:deposit_protection_limit", "예금자 보호한도", "MonetaryRule"),
    ("ha_status_agree", "proposed", "service:failure_responsibility_investigation_status", "부실책임조사 진행현황 조회", "Service"),
    ("dr_debt_cert", "proposed", "service:debt_certificate_financial_information_request", "부채증명원·금융거래정보 신청", "Service"),
    ("uc_hrpe_hist", "proposed", "service:heir_financial_transaction_inquiry", "상속인 금융거래조회", "Service"),
    ("dr_credit_sprt", "proposed", "service:credit_recovery_support", "신용회복 지원", "Service"),
    ("uc_bkrp_trst_mng", "proposed", "concept:trust_real_estate_management_system", "신탁부동산 관리체계", "Concept"),
    ("uc_bkrp_trst_psta", "proposed", "concept:trust_real_estate_status", "신탁부동산 현황", "Concept"),
    ("dp_gudn_data", "rejected", None, None, None),
    ("ms_expln", "proposed", "concept:deposit_insurance_payment", "예금보험금", "Concept"),
    ("dp_logo", "proposed", "concept:deposit_protection_logo_use_rules", "예금보호 로고 사용 규정", "Concept"),
    ("dp_syst", "merge_existing", "service:deposit_protection", "예금자보호제도", "Service"),
    ("dp_ovrs", "proposed", "concept:international_deposit_protection_limits", "해외 예금자 보호한도", "Concept"),
    ("dp_svbk_hist", "proposed", "concept:savings_bank_name_change_history", "저축은행 상호 변경이력", "Concept"),
    ("kmrs_itrd", "merge_existing", "service:mistaken_remittance_return", "착오송금 반환지원", "Service"),
    ("receiver_attention", "proposed", "concept:mistaken_remittance_recipient_cautions", "착오송금 수취인 유의사항", "Concept"),
    ("dr_info_aply", "proposed", "service:debt_information_inquiry_consultation", "채무정보 조회·상담신청", "Service"),
    ("dr_kruc", "merge_existing", "service:debt_adjustment", "채무조정", "Service"),
    ("dr_system", "merge_existing", "service:debt_adjustment", "채무조정", "Service"),
    ("uc_bkrp_spcl_mng", "proposed", "concept:special_asset_management_system", "특별자산 관리체계", "Concept"),
    ("uc_bkrp_spcl_ast", "proposed", "concept:special_asset_status", "특별자산 현황", "Concept"),
    ("dr_psn_br", "proposed", "concept:bankruptcy_discharge", "파산·면책", "Concept"),
    ("uc_bkrp_mng", "proposed", "concept:bankruptcy_estate_management", "파산재단 관리", "Concept"),
    ("uc_bkrp_fndt", "proposed", "concept:bankruptcy_estate_status", "파산재단 현황", "Concept"),
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_proposals(mapping: dict, triage: dict) -> dict:
    if mapping["source"] != triage["source"]:
        raise ValueError("P3 triage must be generated from the current ontology map")
    triage_by_page = {candidate["page_id"]: candidate for candidate in triage["page_candidates"]}
    expected_pages = {
        candidate["page_id"]
        for candidate in triage["page_candidates"]
        if candidate["review_priority"] == "P3-high"
        and candidate["suggested_ontology_class"] == "Concept"
    }
    review_pages = {review[0] for review in REVIEWS}
    if review_pages != expected_pages or len(review_pages) != len(REVIEWS):
        raise ValueError("REVIEWS must cover each current P3-high general page exactly once")

    document_map = {document["page_id"]: document for document in mapping["document_mappings"]}
    service_ids = {service["id"] for service in mapping["services"]}
    proposal_ids = {review[2] for review in REVIEWS if review[1] == "proposed"}
    reviews = []
    proposals = []
    for page_id, decision, candidate_id, label, ontology_class in REVIEWS:
        source = triage_by_page[page_id]
        evidence = {
            "page_id": page_id,
            "source_url": source["evidence"]["source_url"],
            "content_sha256": source["evidence"]["content_sha256"],
        }
        if decision == "rejected":
            note = "Content download/search board; retain as Document, not a domain entity."
        elif decision == "merge_existing":
            if candidate_id not in service_ids:
                raise ValueError(f"unknown existing service: {candidate_id}")
            note = "Page documents an existing top-level Service; do not create a duplicate entity."
        else:
            if ontology_class not in ALLOWED_CLASSES or candidate_id not in proposal_ids:
                raise ValueError(f"invalid proposal for {page_id}")
            note = "Source-backed P3 proposal pending domain approval."
            proposals.append({
                "id": candidate_id,
                "label": label,
                "ontology_class": ontology_class,
                "status": "proposed",
                "parent_service_ids": document_map[page_id]["service_ids"],
                "synonyms": [],
                "fact_values": [],
                "evidence": [evidence],
            })
        reviews.append({
            "page_id": page_id,
            "source_label": source["candidate_label"],
            "decision": decision,
            "candidate_id": candidate_id,
            "note": note,
            "evidence": evidence,
        })

    return {
        "schema_version": "1.0.0",
        "status": "agent_reviewed_p3_general_pending_domain_approval",
        "production_impact": "none",
        "source": mapping["source"],
        "review_policy": {
            "heldout_testset_used": False,
            "automatic_runtime_promotion": False,
            "approval_required_before_evaluation": True,
            "fact_values_included": False,
        },
        "review_count": len(reviews),
        "proposal_count": len(proposals),
        "merge_existing_count": sum(review["decision"] == "merge_existing" for review in reviews),
        "rejected_count": sum(review["decision"] == "rejected" for review in reviews),
        "proposals": proposals,
        "reviews": reviews,
    }


def serialize(proposals: dict) -> str:
    return json.dumps(proposals, ensure_ascii=False, indent=2) + "\n"


def write_or_check(check: bool) -> int:
    output = serialize(build_proposals(load_json(MAP_PATH), load_json(TRIAGE_PATH)))
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
    parser.add_argument("--check", action="store_true", help="fail if generated proposals are out of date")
    return write_or_check(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
