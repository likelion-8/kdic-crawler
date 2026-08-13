from src.eval.eval_ontology_concept_match import evaluate, load_index, rank_documents


def test_exact_protection_limit_concept_ranks_its_document():
    ranked, concepts = rank_documents("예금자 보호한도는 얼마인가요?", load_index())

    assert "보호한도" in concepts
    assert ranked[0] == "dp_protlmts"


def test_unmatched_question_has_no_ontology_result():
    ranked, concepts = rank_documents("오늘 서울 날씨는 어때요?", load_index())

    assert ranked == []
    assert concepts == []


def test_evaluation_never_claims_production_impact():
    index = load_index()
    result = evaluate([
        {"test_id": "one", "question": "보호한도", "expected_sources": ["dp_protlmts"]},
        {"test_id": "two", "question": "오늘 날씨", "expected_sources": ["dp_protlmts"]},
    ], index)

    assert result["production_impact"] == "none"
    assert result["n_answerable"] == 2
    assert result["matched_question_count"] == 1
