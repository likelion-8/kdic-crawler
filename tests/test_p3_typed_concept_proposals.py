from src.crawler.build_p3_typed_concept_proposals import (
    MAP_PATH,
    OUTPUT_PATH,
    TRIAGE_PATH,
    build_proposals,
    load_json,
    serialize,
)


def test_typed_p3_proposals_cover_all_specific_high_priority_pages_once():
    mapping = load_json(MAP_PATH)
    triage = load_json(TRIAGE_PATH)
    output = build_proposals(mapping, triage)
    source_pages = [evidence["page_id"] for proposal in output["proposals"] for evidence in proposal["evidence"]]

    assert output["source_page_count"] == 11
    assert output["proposal_count"] == 10
    assert len(source_pages) == len(set(source_pages)) == 11
    assert output["production_impact"] == "none"
    assert output["review_policy"]["heldout_testset_used"] is False
    assert output["review_policy"]["fact_values_included"] is False
    assert all(proposal["status"] == "proposed" for proposal in output["proposals"])


def test_duplicate_return_procedure_pages_are_one_source_linked_proposal():
    output = build_proposals(load_json(MAP_PATH), load_json(TRIAGE_PATH))
    by_id = {proposal["id"]: proposal for proposal in output["proposals"]}
    procedure = by_id["procedure:mistaken_remittance_return_support"]

    assert {evidence["page_id"] for evidence in procedure["evidence"]} == {"mtrs_gvbk_proc", "kmrs_proc"}
    assert procedure["service_ids"] == ["service:mistaken_remittance_return"]
    assert procedure["ontology_class"] == "Procedure"


def test_checked_in_typed_p3_proposals_are_reproducible():
    assert OUTPUT_PATH.read_text(encoding="utf-8") == serialize(
        build_proposals(load_json(MAP_PATH), load_json(TRIAGE_PATH))
    )
