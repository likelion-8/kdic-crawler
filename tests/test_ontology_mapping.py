from src.crawler.build_ontology_map import (
    CORPUS_PATH,
    OUTPUT_PATH,
    SERVICES,
    build_mapping,
    load_corpus,
    serialize,
)


def test_current_corpus_maps_all_documents_to_services_and_concepts():
    mapping = build_mapping(load_corpus(CORPUS_PATH))

    assert mapping["source"]["document_count"] == 58
    assert len(mapping["services"]) == 6
    assert {s["business_domain"] for s in mapping["services"]} == set(SERVICES)
    assert len(mapping["document_mappings"]) == 58
    assert all(d["service_ids"] and d["concept_ids"] for d in mapping["document_mappings"])
    assert all(d["mapping"]["review_status"] == "unreviewed"
               for d in mapping["document_mappings"])


def test_protection_limit_page_keeps_exact_metadata_concepts_and_evidence_hash():
    mapping = build_mapping(load_corpus(CORPUS_PATH))
    concepts = {c["id"]: c["label"] for c in mapping["concepts"]}
    document = next(d for d in mapping["document_mappings"] if d["page_id"] == "dp_protlmts")

    assert document["service_ids"] == ["service:deposit_protection"]
    assert "보호한도" in {concepts[cid] for cid in document["concept_ids"]}
    assert len(document["content_sha256"]) == 64


def test_checked_in_mapping_is_reproducible_from_current_corpus():
    assert OUTPUT_PATH.read_text(encoding="utf-8") == serialize(build_mapping(load_corpus(CORPUS_PATH)))
