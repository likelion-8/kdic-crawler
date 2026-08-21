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


# ── 업무 되묻기 — 판정이 플래너 콜에 얹힌 뒤(2026-08-21) ──────────────────────────
# 핵심 규약: **턴당 판정은 한 번**이다. 이력이 있으면 재작성기(0-2.7), 없으면 플래너(1-1).
# 둘 다 보면 재작성기가 "필요 없음"이라 한 것을 플래너가 뒤집어 이중 되묻기가 된다.

def _gates_open(monkeypatch):
    _no_cache(monkeypatch)
    monkeypatch.setattr("gate1.run_gate1", lambda _q: SimpleNamespace(
        action="CONTINUE", label="CONTINUE", rule_id=None, reason="no_rule_matched"))
    monkeypatch.setattr("gate2.run_gate2", lambda _q: SimpleNamespace(
        action="CONTINUE", s_id=0.9, s_ood=0.1, threshold=0.5,
        nearest_out_cluster_id=None, nearest_out_category=None, reason="in_domain"))
    monkeypatch.setattr(sse.answer, "clarification_response", lambda *a: _resp())


def test_planner_clarification_fires_on_first_turn(captured, monkeypatch):
    """첫 턴(이력 없음)은 플래너 판정으로 되묻는다 — 정규식 프리스크린 없이."""
    _gates_open(monkeypatch)
    monkeypatch.setattr(sse.answer, "plan",
                        lambda _q: sse.answer.Plan([("얼마까지 가능해?", "informational")], True))

    list(sse.chat_event_stream("얼마까지 가능해?", "sess", "req"))

    assert captured == [("clarify", None)]


def test_planner_clarification_is_skipped_when_the_rewriter_already_judged(captured, monkeypatch):
    """이력이 있으면 재작성기 판정이 최종 — 플래너가 true 를 줘도 되묻지 않는다(이중 판정 금지)."""
    _gates_open(monkeypatch)
    monkeypatch.setattr(sse.conversation, "recent_messages",
                        lambda _s: [("user", "착오송금 반환 기한은?"), ("assistant", "2개월입니다")])
    monkeypatch.setattr("query_rewriter.rewrite_followup", lambda *a: SimpleNamespace(
        rewritten=False, standalone_question="신청 링크 알려줘", needs_clarification=False))
    monkeypatch.setattr(sse.answer, "plan",
                        lambda _q: sse.answer.Plan([("신청 링크 알려줘", "civil_petition")], True))

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


def test_plan_carries_the_clarification_flag_from_the_planner_call():
    """같은 한 콜에서 나온 값이라 items 와 함께 돌아와야 한다 — 두 번 부르면 LLM 콜이 2배."""
    from api.rag.answer import Plan
    assert Plan([("q", "informational")], True).needs_clarification is True
    assert Plan([("q", "informational")]).needs_clarification is False, "기본값은 되묻지 않음"
