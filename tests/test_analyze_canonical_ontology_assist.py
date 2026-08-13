from src.eval.analyze_canonical_ontology_assist import (
    OUTPUT_PATH,
    REVIEW_PATH,
    build_analysis,
    generate,
)


def shadow_with_rows(rows):
    return {
        "n_answerable": len(rows),
        "ontology_match_coverage": 1.0,
        "ranking_changed_count": len(rows),
        "quality_gate": {"passed": False},
        "per_question": rows,
    }


def test_analysis_classifies_non_gold_prepend_regression_and_gold_improvement():
    analysis = build_analysis(shadow_with_rows([
        {
            "test_id": "regression", "gold": ["gold"], "matched_labels": ["공식 용어"],
            "ontology_pages": ["wrong"], "baseline_pages": ["gold", "wrong"],
            "assisted_pages": ["wrong", "gold"],
        },
        {
            "test_id": "improvement", "gold": ["gold"], "matched_labels": ["공식 용어"],
            "ontology_pages": ["gold"], "baseline_pages": ["wrong"],
            "assisted_pages": ["gold", "wrong"],
        },
    ]))
    cases = {item["test_id"]: item for item in analysis["changed_cases"]}

    assert cases["regression"]["impact"] == "regressed_first_gold_rank"
    assert cases["regression"]["ontology_evidence_relation"] == "non_gold_ontology_pages"
    assert cases["improvement"]["impact"] == "improved_first_gold_rank"
    assert cases["improvement"]["ontology_evidence_relation"] == "gold_only_ontology_pages"
    assert analysis["policy"]["do_not_tune_on_this_heldout_set"] is True


def test_checked_in_assist_diagnosis_is_reproducible():
    analysis, review = generate()

    assert OUTPUT_PATH.read_text(encoding="utf-8") == analysis
    assert REVIEW_PATH.read_text(encoding="utf-8") == review
