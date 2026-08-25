"""캐시로 답한 건만 'cache' 로 기록되는지 — 경로를 헷갈리면 로그가 거짓말을 한다.

실제로 한 번 틀렸다(2026-08-20): served_from='cache' 를 가드레일 거절 경로에 붙여서,
금칙어로 막은 답변이 AD-005 상세에 '캐시 응답'으로 떴다. 두 경로 모두 sub_plans 가 비고
log_run 호출 모양이 똑같아 눈으로는 구분이 안 된다.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from api.rag import sse  # noqa: E402


def _resp():
    return SimpleNamespace(answer="답변", latency_ms=900, out_of_scope=False,
                           model_dump=lambda: {"answer": "답변"})


@pytest.fixture
def captured(monkeypatch):
    calls = []
    monkeypatch.setattr(sse.answer, "log_run",
                        lambda *a, **kw: calls.append((kw.get("served_from"), kw.get("served_label"))))
    monkeypatch.setattr(sse.conversation, "recent_messages", lambda _s: [])
    monkeypatch.setattr(sse.conversation, "save_user_message", lambda *a: None)
    monkeypatch.setattr(sse.conversation, "save_assistant_message", lambda *a: None)
    return calls


def test_cache_hit_is_the_only_path_marked_as_cache(captured, monkeypatch):
    monkeypatch.setattr(sse.answer, "guardrail_hit", lambda *a, **kw: None)
    monkeypatch.setattr(sse.answer, "cache_get", lambda _q: {"answer": "저장된 답변"})
    monkeypatch.setattr("api.schemas.chat.ChatResponse.model_validate",
                        staticmethod(lambda _d: _resp()))

    list(sse.chat_event_stream("착오송금 반환까지 얼마나 걸리나요?", "sess", "req"))

    assert captured == [("cache", None)]


def test_a_guardrail_refusal_is_not_a_cache_hit(captured, monkeypatch):
    monkeypatch.setattr(sse.answer, "guardrail_hit", lambda *a, **kw: "금칙어")
    monkeypatch.setattr(sse.answer, "guardrail_refusal", lambda *a: _resp())

    list(sse.chat_event_stream("막히는 질문", "sess", "req"))

    # 검색을 안 탄 건 캐시와 같지만 '저장해 둔 답을 돌려준 것'은 아니다 — 경로를 갈라 적는다
    assert captured == [("guardrail", None)]


def _no_cache(monkeypatch):
    monkeypatch.setattr(sse.answer, "guardrail_hit", lambda *a, **kw: None)
    monkeypatch.setattr(sse.answer, "cache_get", lambda _q: None)
    monkeypatch.setattr(sse.answer, "fixed_gate_response", lambda *a: _resp())
    monkeypatch.setattr("observability.record_trace", lambda *a, **kw: None)


def test_gate1_exit_records_the_rule_label(captured, monkeypatch):
    _no_cache(monkeypatch)
    monkeypatch.setattr("gate1.run_gate1", lambda _q: SimpleNamespace(
        action="EXIT", label="FIXED_GREETING", rule_id="greet_01", reason="matched"))

    list(sse.chat_event_stream("안녕", "sess", "req"))

    # 규칙 이름까지 남겨야 화면이 '왜 분류가 없나'를 말할 수 있다
    assert captured == [("gate1", "FIXED_GREETING")]


def test_gate2_exit_records_the_path_without_the_internal_category(captured, monkeypatch):
    _no_cache(monkeypatch)
    monkeypatch.setattr("gate1.run_gate1", lambda _q: SimpleNamespace(
        action="CONTINUE", label="CONTINUE", rule_id=None, reason="no_rule_matched"))
    monkeypatch.setattr("gate2.run_gate2", lambda _q: SimpleNamespace(
        action="EXIT", s_id=0.1, s_ood=0.8, threshold=0.5,
        nearest_out_cluster_id="c1", nearest_out_category="일상잡담", reason="out_of_domain"))

    list(sse.chat_event_stream("오늘 날씨 어때", "sess", "req"))

    # 카테고리는 내부 로그 전용이다(src/gate2.py:55) — 경로만 남긴다
    assert captured == [("gate2", None)]


# ── 업무 되묻기 — 판정이 게이트 앞 질문 정리 콜 한 곳으로 모인 뒤(2026-08-25) ──────
# 핵심 규약: **판정은 질문 정리(0-2.5) 한 곳**이고, 첫 턴·후속 턴이 같은 경로를 돈다.
# 종전에는 첫 턴만 플래너(Gate 2 뒤)가 판정해, 업무 명사가 빠진 질문은 Gate 2 가 먼저
# EXIT 시켜 되묻기가 아예 안 나갔다 — 그게 이 배치의 이유다.

def _gates_open(monkeypatch):
    _no_cache(monkeypatch)
    monkeypatch.setattr("gate1.run_gate1", lambda _q: SimpleNamespace(
        action="CONTINUE", label="CONTINUE", rule_id=None, reason="no_rule_matched"))
    monkeypatch.setattr("gate2.run_gate2", lambda _q: SimpleNamespace(
        action="CONTINUE", s_id=0.9, s_ood=0.1, threshold=0.5,
        nearest_out_cluster_id=None, nearest_out_category=None, reason="in_domain"))
    monkeypatch.setattr(sse.answer, "clarification_response", lambda *a: _resp())


def _triage(monkeypatch, needs_clarification, standalone=None, rewritten=False):
    seen = []

    def _fake(query, history):
        seen.append((query, list(history)))
        return SimpleNamespace(rewritten=rewritten,
                               standalone_question=standalone or query,
                               needs_clarification=needs_clarification)
    monkeypatch.setattr("query_rewriter.triage_query", _fake)
    return seen


def test_clarification_fires_on_the_first_turn(captured, monkeypatch):
    """첫 턴(이력 없음)에도 질문 정리가 돌고 그 판정으로 되묻는다."""
    _gates_open(monkeypatch)
    seen = _triage(monkeypatch, needs_clarification=True)

    list(sse.chat_event_stream("신청 방법 알려줘", "sess", "req"))

    assert seen == [("신청 방법 알려줘", [])], "무이력이라고 건너뛰면 첫 턴 되묻기가 죽는다"
    assert captured == [("clarify", None)]


def test_clarification_fires_on_a_follow_up_turn(captured, monkeypatch):
    """후속 턴도 같은 판정기·같은 경로 — 첫 턴과 갈리는 분기가 없다."""
    _gates_open(monkeypatch)
    history = [("user", "착오송금 반환 기한은?"), ("assistant", "2개월입니다")]
    monkeypatch.setattr(sse.conversation, "recent_messages", lambda _s: history)
    seen = _triage(monkeypatch, needs_clarification=True)

    list(sse.chat_event_stream("다른 업무는요?", "sess", "req"))

    assert seen == [("다른 업무는요?", history)]
    assert captured == [("clarify", None)]


def test_clarification_runs_before_gate2(captured, monkeypatch):
    """되묻기가 Gate 2 **앞**이라는 것이 이번 배치의 요점이다 — 업무 명사가 빠진 질문은
    Gate 2 가 범위외로 오차단하므로(실측 s_id 0.536 < s_ood 0.668), 뒤에 두면 못 나간다."""
    _no_cache(monkeypatch)
    monkeypatch.setattr("gate1.run_gate1", lambda _q: SimpleNamespace(
        action="CONTINUE", label="CONTINUE", rule_id=None, reason="no_rule_matched"))
    monkeypatch.setattr("gate2.run_gate2", lambda _q: SimpleNamespace(
        action="EXIT", s_id=0.536, s_ood=0.668, threshold=0.66,
        nearest_out_cluster_id="human_agent_proxy_request",
        nearest_out_category="개인정보상담요청", reason="out_of_domain"))
    monkeypatch.setattr(sse.answer, "clarification_response", lambda *a: _resp())
    _triage(monkeypatch, needs_clarification=True)

    list(sse.chat_event_stream("신청 방법 알려줘", "sess", "req"))

    assert captured == [("clarify", None)], "Gate 2 가 먼저 EXIT 시키면 되묻기가 죽는다"


def test_no_clarification_reaches_the_answer_path(captured, monkeypatch):
    """판정이 false 면 평소대로 답변 경로로 내려간다."""
    _gates_open(monkeypatch)
    _triage(monkeypatch, needs_clarification=False)
    monkeypatch.setattr(sse.answer, "plan",
                        lambda _q: sse.answer.Plan([("신청 링크 알려줘", "civil_petition")]))

    reached = []

    def _prepare(*_a):
        reached.append(True)
        raise RuntimeError("답변 경로 도달을 확인하고 멈춘다 — 실제 LLM 을 부르지 않으려고")

    monkeypatch.setattr(sse.answer, "prepare_sub", _prepare)
    monkeypatch.setattr(sse.answer, "log_failed_run", lambda *a, **kw: None)
    monkeypatch.setattr(sse.answer, "error_from_exception",
                        lambda *a: SimpleNamespace(model_dump=lambda: {}))

    list(sse.chat_event_stream("신청 링크 알려줘", "sess", "req"))

    assert reached, "되묻기로 새지 않고 답변 경로(prepare_sub)까지 내려가야 한다"
    assert captured == [], "이 턴은 되묻기가 아니므로 clarify 로 기록되면 안 된다"


def test_triage_failure_passes_through_without_clarifying(captured, monkeypatch):
    """질문 정리 콜이 실패한 턴은 판정 없이 지나간다(fail-open) — 백업 판정기는 없다."""
    _gates_open(monkeypatch)
    monkeypatch.setattr("query_rewriter.triage_query", lambda *a: None)
    monkeypatch.setattr(sse.answer, "plan",
                        lambda _q: sse.answer.Plan([("신청 링크 알려줘", "civil_petition")]))
    monkeypatch.setattr(sse.answer, "prepare_sub",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("여기서 멈춘다")))
    monkeypatch.setattr(sse.answer, "log_failed_run", lambda *a, **kw: None)
    monkeypatch.setattr(sse.answer, "error_from_exception",
                        lambda *a: SimpleNamespace(model_dump=lambda: {}))

    list(sse.chat_event_stream("신청 링크 알려줘", "sess", "req"))

    assert captured == []
