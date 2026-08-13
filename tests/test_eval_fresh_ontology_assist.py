import pytest

from src.eval.eval_fresh_ontology_assist import evaluate_fresh, validate_baseline_alignment


def rows():
    return [{"test_id": "fresh_1", "question": "보호대상 금융회사", "expected_sources": ["gold"]}]


def baseline(**overrides):
    output = {"per_row_retrieval": [{"test_id": "fresh_1", "gold": ["gold"], "top5_pages": ["gold", "a", "b", "c", "d"]}]}
    output.update(overrides)
    return output


def test_baseline_alignment_requires_same_ids_gold_and_five_ranked_pages():
    assert validate_baseline_alignment(rows(), baseline())["valid"] is True

    invalid = validate_baseline_alignment(rows(), {"per_row_retrieval": [{"test_id": "wrong", "gold": [], "top5_pages": []}]})

    assert invalid["valid"] is False
    assert any("missing fresh test IDs" in error for error in invalid["errors"])
    assert any("unexpected test IDs" in error for error in invalid["errors"])


def test_fresh_evaluator_refuses_misaligned_baseline_before_evaluation(tmp_path):
    with pytest.raises(ValueError, match="baseline does not align"):
        evaluate_fresh(rows(), {"per_row_retrieval": []}, tmp_path / "fresh.jsonl", tmp_path / "baseline.json")
