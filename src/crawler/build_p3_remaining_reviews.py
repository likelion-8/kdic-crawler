"""Close the remaining P3-medium and P3-low ontology triage decisions.

FAQ/content-format pages stay Documents rather than becoming entities. Stable
services, procedures, contact points, cautions, and required-document groups become
source-linked proposals. All decisions remain pending domain approval.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
MAP_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
TRIAGE_PATH = ROOT / "ontology" / "kdic-p3-concept-triage.json"
OUTPUT_PATH = ROOT / "ontology" / "kdic-p3-remaining-reviews.json"

REVIEWS = (
    ("faq_msdr_apply", "rejected", None, None, None),
    ("faq_top10", "rejected", None, None, None),
    ("faq_nramt", "rejected", None, None, None),
    ("mtrs_stut_chc", "rejected", None, None, None),
    ("ha_ilgl_intro", "proposed", "contact:financial_misconduct_report_center", "금융부실관련자 불법행위 신고센터", "ContactPoint"),
    ("uc_itgr_aply", "merge_existing", "service:unclaimed_funds", None, None),
    ("dp_faq_page", "rejected", None, None, None),
    ("ha_faq_dclr", "rejected", None, None, None),
    ("dr_faq_inq", "rejected", None, None, None),
    ("dp_gudn_faq", "merge_existing", "concept:display_explanation_confirmation_scheme", None, None),
    ("sender_docs", "proposed", "required_document:mistaken_remitter_application", "착오송금인 신청 구비서류", "RequiredDocument"),
    ("dp_prdct", "merge_existing", "concept:protected_financial_product", None, None),
    ("dp_fnst", "merge_existing", "actor:protected_financial_institution", None, None),
    ("dp_prdct_srch", "proposed", "service:protected_financial_product_search", "보호대상 금융상품 검색", "Service"),
    ("dp_fnst_srch", "proposed", "service:protected_financial_institution_search", "보호대상 금융회사 검색", "Service"),
    ("dp_josa_law", "proposed", "concept:insured_financial_company_survey_legal_basis", "부보금융회사조사 법적근거·관련규정", "Concept"),
    ("dp_josa_objc", "proposed", "procedure:insured_financial_company_survey_objection", "부보금융회사조사 소명·이의제기", "Procedure"),
    ("dp_josa_itrd", "merge_existing", "concept:insured_financial_company_survey", None, None),
    ("sender_attention", "proposed", "concept:mistaken_remitter_cautions", "착오송금인 유의사항", "Concept"),
    ("dp_gudn", "merge_existing", "concept:display_explanation_confirmation_scheme", None, None),
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_reviews(mapping: dict, triage: dict) -> dict:
    if mapping["source"] != triage["source"]:
        raise ValueError("triage must use the current ontology map")
    triage_by_page = {item["page_id"]: item for item in triage["page_candidates"]}
    expected = {item["page_id"] for item in triage["page_candidates"] if item["review_priority"] != "P3-high"}
    reviewed = {item[0] for item in REVIEWS}
    if expected != reviewed or len(reviewed) != len(REVIEWS):
        raise ValueError("REVIEWS must cover every remaining P3 page exactly once")
    document_map = {item["page_id"]: item for item in mapping["document_mappings"]}
    decisions = []
    proposals = []
    for page_id, decision, candidate_id, label, ontology_class in REVIEWS:
        source = triage_by_page[page_id]
        evidence = {
            "page_id": page_id,
            "source_url": source["evidence"]["source_url"],
            "content_sha256": source["evidence"]["content_sha256"],
        }
        if decision == "proposed":
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
        decisions.append({
            "page_id": page_id,
            "triage_priority": source["review_priority"],
            "source_label": source["candidate_label"],
            "decision": decision,
            "candidate_id": candidate_id,
            "evidence": evidence,
        })
    return {
        "schema_version": "1.0.0",
        "status": "agent_reviewed_p3_remaining_pending_domain_approval",
        "production_impact": "none",
        "source": mapping["source"],
        "review_policy": {
            "heldout_testset_used": False,
            "faq_pages_remain_documents": True,
            "faq_facts_may_be_reviewed_separately": True,
            "automatic_runtime_promotion": False,
        },
        "summary": {
            "review_count": len(decisions),
            "proposal_count": len(proposals),
            "merge_existing_count": sum(item["decision"] == "merge_existing" for item in decisions),
            "rejected_count": sum(item["decision"] == "rejected" for item in decisions),
        },
        "proposals": proposals,
        "decisions": decisions,
    }


def serialize(output: dict) -> str:
    return json.dumps(output, ensure_ascii=False, indent=2) + "\n"


def write_or_check(check: bool) -> int:
    output = serialize(build_reviews(load_json(MAP_PATH), load_json(TRIAGE_PATH)))
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
