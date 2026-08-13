from src.eval.validate_fresh_ontology_assist_heldout import validate_rows


DOMAINS = {"가", "나", "다", "라", "마", "바"}
PAGES = {"page_a", "page_b"}


def row(index: int, domain: str, query_form: str = "user_paraphrase") -> dict:
    return {
        "test_id": f"fresh_{index}", "question": f"새로운 질문 {index}", "business_function": domain,
        "expected_sources": ["page_a"], "question_type": "fact", "intent": "informational",
        "query_form": query_form, "authored_by": "domain-reviewer", "authored_at": "2026-08-12",
    }


def test_fresh_heldout_validator_accepts_stratified_independent_rows():
    rows = [row(index, domain, "official_label_explicit" if index % 3 == 0 else "user_paraphrase")
            for index, domain in enumerate(sorted(DOMAINS) * 12)]

    report = validate_rows(rows, [], DOMAINS, PAGES)

    assert report["valid"] is True
    assert report["counts"]["rows"] == 72


def test_fresh_heldout_validator_rejects_legacy_overlap_and_insufficient_strata():
    report = validate_rows([row(1, "가")], [{"test_id": "old", "question": "새로운 질문 1"}], DOMAINS, PAGES)

    assert report["valid"] is False
    assert any("duplicates frozen" in error for error in report["errors"])
    assert any("at least 72" in error for error in report["errors"])
