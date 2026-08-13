"""Generate the source-linked P1 curated ontology concept proposals.

This is a deliberately small, offline curation pass over metadata concepts shared by
two or more documents. The output stays ``proposed`` until a domain reviewer
approves it. It does not read the held-out test set or participate in retrieval.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
MAP_PATH = ROOT / "ontology" / "kdic-document-concept-map.json"
CORPUS_PATH = ROOT / "data" / "corpus.jsonl"
OUTPUT_PATH = ROOT / "ontology" / "kdic-curated-concept-proposals.json"
ALLOWED_CLASSES = frozenset({"Actor", "Concept", "Service"})


# These are curation decisions over official page metadata, not extracted facts.
REVIEW_ITEMS = (
    {
        "source_concept_id": "concept:c_0c5aafb82cf87be3",
        "decision": "proposed",
        "candidate_ids": ("service:unclaimed_funds",),
        "evidence_page_ids": (
            "uc_bkrp_fndt", "uc_bkrp_mng", "uc_bkrp_spcl_ast", "uc_bkrp_spcl_mng",
            "uc_bkrp_trst_mng", "uc_bkrp_trst_psta", "uc_gudn", "uc_hrpe_hist",
        ),
        "note": "The repeated breadcrumb is a KDIC service-level concept.",
    },
    {
        "source_concept_id": "concept:c_c5b5a0a24f3477f8",
        "decision": "proposed",
        "candidate_ids": ("concept:bankrupt_financial_company_information_search",),
        "evidence_page_ids": (
            "uc_bkrp_fndt", "uc_bkrp_mng", "uc_bkrp_spcl_ast", "uc_bkrp_spcl_mng",
            "uc_bkrp_trst_mng", "uc_bkrp_trst_psta",
        ),
        "note": "A stable information-search concept spanning six official pages.",
    },
    {
        "source_concept_id": "concept:c_3c48ca055b59c51b",
        "decision": "needs_split",
        "candidate_ids": (
            "actor:protected_financial_institution", "concept:protected_financial_product",
        ),
        "evidence_page_ids": ("dp_fnst", "dp_fnst_srch", "dp_prdct", "dp_prdct_srch", "dp_svbk_hist"),
        "note": "The broad label covers both institutions and products, which are distinct ontology entities.",
    },
    {
        "source_concept_id": "concept:c_21ec591f2025d4c5",
        "decision": "rejected",
        "candidate_ids": (),
        "evidence_page_ids": ("mtrs_gvbk_proc", "mtrs_rel_law", "mtrs_stut_chc", "mtrs_vst_rcpt"),
        "note": "Navigation breadcrumb, not a stable domain concept.",
    },
    {
        "source_concept_id": "concept:c_3f293d28d1e34528",
        "decision": "proposed",
        "candidate_ids": ("concept:display_explanation_confirmation_scheme",),
        "evidence_page_ids": ("dp_gudn", "dp_gudn_data", "dp_gudn_faq", "dp_logo"),
        "note": "Named KDIC scheme with its own guidance, FAQ, material, and logo pages.",
    },
    {
        "source_concept_id": "concept:c_dff04cca052051af",
        "decision": "proposed",
        "candidate_ids": ("actor:protected_financial_institution",),
        "evidence_page_ids": ("dp_fnst", "dp_fnst_srch", "dp_svbk_hist"),
        "note": "Normalizes the generic label to the more specific protected-financial-institution entity.",
    },
    {
        "source_concept_id": "concept:c_1e0253f62c754140",
        "decision": "proposed",
        "candidate_ids": ("concept:unclaimed_funds_integrated_application",),
        "evidence_page_ids": ("uc_itgr_aply", "uc_tel_qust"),
        "excluded_page_ids": ("faq_nramt",),
        "note": "The excluded FAQ title states that its actual content is deposit protection, so it is not evidence for this concept.",
    },
    {
        "source_concept_id": "concept:c_6a91436ac7264d5d",
        "decision": "proposed",
        "candidate_ids": ("concept:insured_financial_company_survey",),
        "evidence_page_ids": ("dp_josa_itrd", "dp_josa_law", "dp_josa_objc"),
        "note": "Named KDIC survey activity with introduction, regulations, and objection process pages.",
    },
    {
        "source_concept_id": "concept:c_dbc468a14b601d5d",
        "decision": "rejected",
        "candidate_ids": (),
        "evidence_page_ids": ("faq_nramt", "ha_faq_dclr"),
        "note": "A content format, not a KDIC domain concept.",
    },
    {
        "source_concept_id": "concept:c_dc015df639b9ffb5",
        "decision": "rejected",
        "candidate_ids": (),
        "evidence_page_ids": ("dp_fnst", "dp_prdct"),
        "note": "Navigation label, not a stable domain concept.",
    },
    {
        "source_concept_id": "concept:c_8497eb60b73b67fd",
        "decision": "rejected",
        "candidate_ids": (),
        "evidence_page_ids": ("faq_nramt", "ha_faq_dclr"),
        "note": "Navigation section, not a stable domain concept.",
    },
    {
        "source_concept_id": "concept:c_7173c92dada04b96",
        "decision": "proposed",
        "candidate_ids": ("concept:protected_financial_product",),
        "evidence_page_ids": ("dp_prdct", "dp_prdct_srch"),
        "note": "Normalizes the generic label to the protected-financial-product entity.",
    },
    {
        "source_concept_id": "concept:c_51f8fbdf3ff9e253",
        "decision": "rejected",
        "candidate_ids": (),
        "evidence_page_ids": ("uc_itgr_aply", "uc_tel_qust"),
        "note": "Navigation breadcrumb, not a stable domain concept.",
    },
    {
        "source_concept_id": "concept:c_5b20f0b6b9ebb5f9",
        "decision": "proposed",
        "candidate_ids": ("actor:mistaken_remitter",),
        "evidence_page_ids": ("sender_attention", "sender_qlfc_check"),
        "note": "A stable actor role in the mistaken-remittance return service.",
    },
)

CANDIDATES = (
    {
        "id": "service:unclaimed_funds",
        "label": "미수령금 통합조회·신청",
        "ontology_class": "Service",
        "evidence_page_ids": (
            "uc_bkrp_fndt", "uc_bkrp_mng", "uc_bkrp_spcl_ast", "uc_bkrp_spcl_mng",
            "uc_bkrp_trst_mng", "uc_bkrp_trst_psta", "uc_gudn", "uc_hrpe_hist",
        ),
    },
    {
        "id": "concept:bankrupt_financial_company_information_search",
        "label": "파산금융회사 정보 검색",
        "ontology_class": "Concept",
        "evidence_page_ids": (
            "uc_bkrp_fndt", "uc_bkrp_mng", "uc_bkrp_spcl_ast", "uc_bkrp_spcl_mng",
            "uc_bkrp_trst_mng", "uc_bkrp_trst_psta",
        ),
    },
    {
        "id": "actor:protected_financial_institution",
        "label": "보호대상 금융회사",
        "ontology_class": "Actor",
        "evidence_page_ids": ("dp_fnst", "dp_fnst_srch", "dp_svbk_hist"),
    },
    {
        "id": "concept:protected_financial_product",
        "label": "보호대상 금융상품",
        "ontology_class": "Concept",
        "evidence_page_ids": ("dp_prdct", "dp_prdct_srch"),
    },
    {
        "id": "concept:display_explanation_confirmation_scheme",
        "label": "표시·설명·확인 제도",
        "ontology_class": "Concept",
        "evidence_page_ids": ("dp_gudn", "dp_gudn_data", "dp_gudn_faq", "dp_logo"),
    },
    {
        "id": "concept:unclaimed_funds_integrated_application",
        "label": "미수령금 통합신청",
        "ontology_class": "Concept",
        "evidence_page_ids": ("uc_itgr_aply", "uc_tel_qust"),
    },
    {
        "id": "concept:insured_financial_company_survey",
        "label": "부보금융회사조사",
        "ontology_class": "Concept",
        "evidence_page_ids": ("dp_josa_itrd", "dp_josa_law", "dp_josa_objc"),
    },
    {
        "id": "actor:mistaken_remitter",
        "label": "착오송금인",
        "ontology_class": "Actor",
        "evidence_page_ids": ("sender_attention", "sender_qlfc_check"),
    },
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_corpus(path: Path) -> dict[str, dict]:
    with path.open(encoding="utf-8") as f:
        return {row["page_id"]: row for line in f if (row := json.loads(line))}


def evidence(page_ids: tuple[str, ...], corpus: dict[str, dict], documents: dict[str, dict]) -> list[dict]:
    return [
        {
            "page_id": page_id,
            "source_url": corpus[page_id]["source_url"],
            "content_sha256": documents[page_id]["content_sha256"],
        }
        for page_id in page_ids
    ]


def build_proposals(mapping: dict, corpus: dict[str, dict]) -> dict:
    metadata_concepts = {concept["id"]: concept for concept in mapping["concepts"]}
    documents = {document["page_id"]: document for document in mapping["document_mappings"]}
    repeated_ids = {concept["id"] for concept in mapping["concepts"] if concept["document_count"] >= 2}
    reviewed_ids = {item["source_concept_id"] for item in REVIEW_ITEMS}
    if repeated_ids != reviewed_ids:
        raise ValueError("REVIEW_ITEMS must cover exactly the current P1/P2 metadata concepts")

    candidate_ids = {candidate["id"] for candidate in CANDIDATES}
    for candidate in CANDIDATES:
        if candidate["ontology_class"] not in ALLOWED_CLASSES:
            raise ValueError(f"unsupported ontology class: {candidate['ontology_class']}")
    for item in REVIEW_ITEMS:
        if item["source_concept_id"] not in metadata_concepts:
            raise ValueError(f"unknown metadata concept: {item['source_concept_id']}")
        if not set(item["candidate_ids"]).issubset(candidate_ids):
            raise ValueError(f"unknown candidate for {item['source_concept_id']}")
        if not set(item["evidence_page_ids"]).issubset(set(metadata_concepts[item["source_concept_id"]]["page_ids"])):
            raise ValueError(f"evidence page is not linked to {item['source_concept_id']}")

    return {
        "schema_version": "1.0.0",
        "status": "agent_reviewed_p1_p2_pending_domain_approval",
        "production_impact": "none",
        "source": mapping["source"],
        "review_policy": {
            "heldout_testset_used": False,
            "automatic_runtime_promotion": False,
            "approval_required_before_evaluation": True,
        },
        "candidates": [
            {
                "id": candidate["id"],
                "label": candidate["label"],
                "ontology_class": candidate["ontology_class"],
                "status": "proposed",
                "synonyms": [],
                "evidence": evidence(candidate["evidence_page_ids"], corpus, documents),
            }
            for candidate in CANDIDATES
        ],
        "metadata_concept_reviews": [
            {
                "source_concept_id": item["source_concept_id"],
                "source_label": metadata_concepts[item["source_concept_id"]]["label"],
                "decision": item["decision"],
                "candidate_ids": list(item["candidate_ids"]),
                "evidence": evidence(item["evidence_page_ids"], corpus, documents),
                "excluded_page_ids": list(item.get("excluded_page_ids", ())),
                "note": item["note"],
            }
            for item in REVIEW_ITEMS
        ],
    }


def serialize(proposals: dict) -> str:
    return json.dumps(proposals, ensure_ascii=False, indent=2) + "\n"


def write_or_check(check: bool) -> int:
    output = serialize(build_proposals(load_json(MAP_PATH), load_corpus(CORPUS_PATH)))
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
    parser.add_argument("--check", action="store_true", help="fail if the generated proposals are out of date")
    return write_or_check(parser.parse_args().check)


if __name__ == "__main__":
    raise SystemExit(main())
