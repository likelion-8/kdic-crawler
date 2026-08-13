"""Build source-linked typed ontology proposals from the P3 triage.

Only P3-high items whose class is more specific than ``Concept`` are considered.
Equivalent procedure pages are grouped explicitly. All output remains proposed and
is prohibited from runtime use until domain approval and held-out evaluation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
MAP_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
TRIAGE_PATH = ROOT / "ontology" / "kdic-p3-concept-triage.json"
OUTPUT_PATH = ROOT / "ontology" / "kdic-p3-typed-concept-proposals.json"
ALLOWED_CLASSES = frozenset({"Procedure", "EligibilityRule", "RequiredDocument", "ContactPoint"})


# Grouping is an explicit review decision, not fuzzy or LLM-based merging.
PROPOSALS = (
    {
        "id": "required_document:mistaken_remittance_recipient_forms",
        "label": "착오송금 수취인 구비서류",
        "ontology_class": "RequiredDocument",
        "page_ids": ("receiver_docs",),
        "note": "Forms and supporting documents for a mistaken-remittance recipient.",
    },
    {
        "id": "procedure:mistaken_remittance_return_support",
        "label": "착오송금 반환지원 절차",
        "ontology_class": "Procedure",
        "page_ids": ("mtrs_gvbk_proc", "kmrs_proc"),
        "note": "Two official pages describe the same five-stage return-support procedure.",
    },
    {
        "id": "contact:mistaken_remittance_visit",
        "label": "착오송금 반환지원 방문접수",
        "ontology_class": "ContactPoint",
        "page_ids": ("mtrs_vst_rcpt",),
        "note": "Official in-person application channel and office information.",
    },
    {
        "id": "contact:concealed_assets_report_center",
        "label": "은닉재산 신고센터",
        "ontology_class": "ContactPoint",
        "page_ids": ("ha_center",),
        "note": "Official reporting center for concealed assets and related rewards.",
    },
    {
        "id": "eligibility:mistaken_remittance_self_check",
        "label": "착오송금 반환지원 대상 자가진단",
        "ontology_class": "EligibilityRule",
        "page_ids": ("sender_qlfc_check",),
        "note": "Interactive eligibility check; distinct from the authoritative eligibility guidance.",
    },
    {
        "id": "required_document:deposit_insurance_application",
        "label": "예금보험금 신청 구비서류",
        "ontology_class": "RequiredDocument",
        "page_ids": ("ms_poss_dcmnt",),
        "note": "Required documents vary by applicant type.",
    },
    {
        "id": "procedure:deposit_insurance_payment_application",
        "label": "예금보험금 신청 절차",
        "ontology_class": "Procedure",
        "page_ids": ("ms_aply_proc",),
        "note": "Procedure from insurance event and notice through application and payment.",
    },
    {
        "id": "contact:unclaimed_funds_phone",
        "label": "미수령금 전화문의",
        "ontology_class": "ContactPoint",
        "page_ids": ("uc_tel_qust",),
        "note": "Official telephone inquiry channel for depositors and unclaimed funds.",
    },
    {
        "id": "eligibility:mistaken_remittance_return_support",
        "label": "착오송금 반환지원 신청대상",
        "ontology_class": "EligibilityRule",
        "page_ids": ("kmrs_aply_trgt",),
        "note": "Authoritative eligibility guidance; values remain separate reviewed facts.",
    },
    {
        "id": "procedure:mistaken_remittance_application",
        "label": "착오송금 반환지원 신청방법",
        "ontology_class": "Procedure",
        "page_ids": ("kmrs_apply_mthd",),
        "note": "Online and in-person application methods.",
    },
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_proposals(mapping: dict, triage: dict) -> dict:
    if mapping["source"] != triage["source"]:
        raise ValueError("P3 triage must be generated from the current ontology map")
    document_map = {document["page_id"]: document for document in mapping["document_mappings"]}
    triage_by_page = {candidate["page_id"]: candidate for candidate in triage["page_candidates"]}
    eligible_pages = {
        candidate["page_id"]
        for candidate in triage["page_candidates"]
        if candidate["review_priority"] == "P3-high"
        and candidate["suggested_ontology_class"] in ALLOWED_CLASSES
    }
    selected_pages = {page_id for proposal in PROPOSALS for page_id in proposal["page_ids"]}
    if selected_pages != eligible_pages:
        raise ValueError("PROPOSALS must cover exactly the current typed P3-high pages")

    output = []
    for proposal in PROPOSALS:
        page_ids = proposal["page_ids"]
        if proposal["ontology_class"] not in ALLOWED_CLASSES:
            raise ValueError(f"unsupported class: {proposal['ontology_class']}")
        for page_id in page_ids:
            if triage_by_page[page_id]["suggested_ontology_class"] != proposal["ontology_class"]:
                raise ValueError(f"class mismatch for {page_id}")
        service_ids = sorted({
            service_id
            for page_id in page_ids
            for service_id in document_map[page_id]["service_ids"]
        })
        output.append({
            "id": proposal["id"],
            "label": proposal["label"],
            "ontology_class": proposal["ontology_class"],
            "status": "proposed",
            "service_ids": service_ids,
            "synonyms": [],
            "evidence": [
                {
                    "page_id": page_id,
                    "source_url": triage_by_page[page_id]["evidence"]["source_url"],
                    "content_sha256": triage_by_page[page_id]["evidence"]["content_sha256"],
                }
                for page_id in page_ids
            ],
            "note": proposal["note"],
        })

    return {
        "schema_version": "1.0.0",
        "status": "agent_reviewed_p3_typed_pending_domain_approval",
        "production_impact": "none",
        "source": mapping["source"],
        "review_policy": {
            "heldout_testset_used": False,
            "automatic_runtime_promotion": False,
            "approval_required_before_evaluation": True,
            "fact_values_included": False,
        },
        "source_page_count": len(selected_pages),
        "proposal_count": len(output),
        "proposals": output,
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
