from src.crawler.build_canonical_ontology_draft import (
    CHECKLIST_PATH,
    MAP_PATH,
    OUTPUT_PATH,
    P1_P2_PATH,
    P3_GENERAL_PATH,
    P3_REMAINING_PATH,
    P3_TYPED_PATH,
    build_checklist,
    build_draft,
    load_json,
    serialize,
)


def current_draft():
    return build_draft(
        load_json(MAP_PATH), load_json(P1_P2_PATH), load_json(P3_TYPED_PATH), load_json(P3_GENERAL_PATH),
        load_json(P3_REMAINING_PATH)
    )


def test_canonical_draft_has_unique_pending_entities_and_valid_service_refs():
    draft = current_draft()
    ids = [entity["id"] for entity in draft["entities"]]
    service_ids = {service["id"] for service in draft["base_services"]}

    assert draft["summary"]["entity_count"] == 45
    assert draft["summary"]["pending_approval_count"] == 45
    assert draft["summary"]["base_service_count"] == 6
    assert draft["summary"]["merged_base_service_proposal_count"] == 1
    assert len(ids) == len(set(ids))
    assert all(entity["review_status"] == "pending_domain_approval" for entity in draft["entities"])
    assert all(set(entity["parent_service_ids"]).issubset(service_ids) for entity in draft["entities"])
    assert all(not entity["synonyms"] and not entity["fact_values"] for entity in draft["entities"])
    assert draft["production_impact"] == "none"


def test_approval_checklist_has_one_decision_block_per_entity():
    draft = current_draft()
    checklist = build_checklist(draft)

    assert checklist.count("- [ ] Approve") == 45
    assert checklist.count("- [ ] Reject") == 45
    assert checklist.count("- [ ] Needs changes") == 45
    assert "does not change machine-readable status or production behavior" in checklist


def test_checked_in_canonical_artifacts_are_reproducible():
    draft = current_draft()
    assert OUTPUT_PATH.read_text(encoding="utf-8") == serialize(draft)
    assert CHECKLIST_PATH.read_text(encoding="utf-8") == build_checklist(draft)
