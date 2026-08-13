from src.crawler.build_ontology_document_coverage import OUTPUT_PATH, current_coverage, serialize


def test_every_official_document_has_semantic_evidence_or_document_only_decision():
    coverage = current_coverage()
    documents = coverage["documents"]

    assert coverage["summary"] == {
        "official_document_count": 58,
        "semantic_evidence_count": 52,
        "document_only_count": 6,
        "unresolved_count": 0,
    }
    assert len({item["page_id"] for item in documents}) == 58
    assert {item["coverage_status"] for item in documents} == {"semantic_evidence", "document_only"}


def test_content_scope_mismatch_and_navigation_are_explicitly_retained_as_documents():
    coverage = {item["page_id"]: item for item in current_coverage()["documents"]}

    assert coverage["faq_nramt"]["document_role"] == "내용 범위 불일치 FAQ"
    assert coverage["mtrs_stut_chc"]["document_role"] == "상황 분기 화면"
    assert coverage["faq_nramt"]["targets"] == []


def test_checked_in_document_coverage_is_reproducible():
    assert OUTPUT_PATH.read_text(encoding="utf-8") == serialize(current_coverage())
