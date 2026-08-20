from pathlib import Path

import gate2
from gptlike_scope_v5 import V5QueryDecision, V5UnitDecision
from gptlike_scope_v6 import V6DiscourseRequestUnitizer


def _u(text, prediction):
    return V5UnitDecision(request_unit=text, prediction=prediction, reason="test")


def test_v6_unitizer_sentence_mixed():
    units, mode = V6DiscourseRequestUnitizer().split(
        "예보 공식 기준을 알려주세요. 추가로 법원 제출 문서를 작성해 주세요."
    )
    assert mode == "discourse_sentence_boundary"
    assert len(units) == 2


def test_v6_unitizer_inline_mixed():
    units, mode = V6DiscourseRequestUnitizer().split(
        "예보 공식 기준을 알려주세요 그리고 법원 제출 문서를 작성해 주세요."
    )
    assert mode == "discourse_additive_boundary"
    assert len(units) == 2


def test_v6_unitizer_preserves_single_full_context():
    q = "예금보험공사 기준으로 예금자보호 대상인지 알려주세요."
    units, mode = V6DiscourseRequestUnitizer().split(q)
    assert units == (q,)
    assert mode == "single_full_context"


def test_adapter_continue(monkeypatch):
    d = V5QueryDecision(
        action="CONTINUE", prediction="IN_SCOPE",
        units=(_u("예보 기준을 알려주세요.", "IN_SCOPE"),),
        unitizer_mode="single_full_context",
    )
    monkeypatch.setattr(gate2, "classify_gptlike_scope_v6", lambda _: d)
    got = gate2.run_gate2("x")
    assert got.action == "CONTINUE"
    assert got.prediction == "IN_SCOPE"
    assert len(got.in_scope_units) == 1
    assert got.response_text is None


def test_adapter_exit(monkeypatch):
    d = V5QueryDecision(
        action="EXIT", prediction="OOS",
        units=(_u("법원 제출 문서를 작성해 주세요.", "OOS"),),
        unitizer_mode="single_full_context",
    )
    monkeypatch.setattr(gate2, "classify_gptlike_scope_v6", lambda _: d)
    monkeypatch.setattr(gate2, "_load_gate1_oos_response_text", lambda: "OOS")
    got = gate2.run_gate2("x")
    assert got.action == "EXIT"
    assert got.prediction == "OOS"
    assert got.response_text == "OOS"


def test_adapter_mixed_exposes_safe_and_oos_units(monkeypatch):
    d = V5QueryDecision(
        action="MIXED", prediction="MIXED",
        units=(
            _u("예보 기준을 알려주세요.", "IN_SCOPE"),
            _u("법원 제출 문서를 작성해 주세요.", "OOS"),
        ),
        unitizer_mode="discourse_sentence_boundary",
    )
    monkeypatch.setattr(gate2, "classify_gptlike_scope_v6", lambda _: d)
    monkeypatch.setattr(gate2, "_load_gate1_oos_response_text", lambda: "OOS")
    got = gate2.run_gate2("x")
    assert got.action == "MIXED"
    assert [u.request_unit for u in got.in_scope_units] == ["예보 기준을 알려주세요."]
    assert [u.request_unit for u in got.oos_units] == ["법원 제출 문서를 작성해 주세요."]
    assert got.response_text == "OOS"


def test_adapter_runtime_failure_is_fail_open(monkeypatch):
    def boom(_):
        raise RuntimeError("boom")
    monkeypatch.setattr(gate2, "classify_gptlike_scope_v6", boom)
    got = gate2.run_gate2("x")
    assert got.action == "CONTINUE"
    assert got.prediction == "IN_SCOPE"
    assert got.units == ()
    assert got.unitizer_mode == "runtime_error_fail_open"


def test_runtime_wiring_contains_mixed_filter():
    pipeline = Path("src/pipeline.py").read_text(encoding="utf-8")
    sse = Path("api/rag/sse.py").read_text(encoding="utf-8")
    assert "_rag_answer_gate2_mixed" in pipeline
    assert 'if gate2.action == "MIXED"' in pipeline
    assert 'if g2.action == "MIXED"' in sse
    assert "gate2_oos" in sse
    assert "answer.plan(unit.request_unit)" in sse


def test_removed_similarity_gate_artifacts_are_absent():
    assert not Path("config/gate2_reference.json").exists()
    assert not Path("data/gate2_cache").exists()
    assert not Path("src/crawler/build_gate2_reference.py").exists()
    assert not Path("src/crawler/gate2_threshold_search.py").exists()
    assert not Path("src/crawler/gate2_ab_comparison.py").exists()
