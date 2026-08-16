"""OOS 라우팅의 결정론적 계약 테스트(네트워크·LLM·검색 DB 없음)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import candidate_ranking  # noqa: E402
import oos_routing  # noqa: E402
import runtime_config  # noqa: E402


@pytest.fixture(autouse=True)
def empty_runtime_params():
    runtime_config.override("params", {})
    yield
    runtime_config.override("params", None)


def test_rule_gate_only_cuts_exact_smalltalk():
    hit = oos_routing.rule_gate("안녕하세요!")
    assert hit is not None
    assert hit.stage == "rule"
    assert hit.decision == "OOS"
    assert "예금보험공사" in hit.response

    # 인사말 뒤에 실제 질문이 붙으면 확실한 패턴이 아니므로 통과시킨다.
    assert oos_routing.rule_gate("안녕하세요 예금자보호 한도는 얼마인가요?") is None


def test_cosine_gate_uses_dynamic_threshold_and_passes_ambiguous_values():
    runtime_config.override("params", {"min_route_cosine_score": 0.35})
    blocked = oos_routing.pre_route("질문", route_signal=("fact", 0.20))
    passed = oos_routing.pre_route("질문", route_signal=("fact", 0.36))
    assert blocked.stage == "cosine" and blocked.is_terminal
    assert passed.stage == "pre_route" and not passed.is_terminal


def test_rerank_gate_does_not_reuse_embedding_threshold():
    low = [("c1", -2.0, "text")]
    assert candidate_ranking.gate_low_rerank_relevance(low, threshold=-1.0) == []
    assert candidate_ranking.gate_low_rerank_relevance(low, threshold=-3.0) == low


def test_supervisor_fail_open_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = oos_routing.supervise_context("질문", [("c1", 0.9, "근거")])
    assert result.decision == "ANSWERABLE"
    assert result.rationale == "supervisor_api_key_unavailable"
