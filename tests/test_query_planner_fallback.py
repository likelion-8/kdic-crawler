"""플래너(query_planner.plan_query) API 호출 실패 시 안전 기본값(단일+informational)으로
빠지는 경로 — 2026-08-28. 이 폴백은 civil_petition 질문을 informational로 잘못 강등시킬 수
있는데, 그 결과가 질의 캐시에 24시간 적재돼 다른 사용자에게 퍼지는 걸 막는 게 이 수정의 목적.

세 계층으로 나눠 검사한다:
  1) query_planner.plan_query()   — 성공/실패 각각 fallback 필드가 맞게 서는지
  2) api.rag.answer.plan()        — 위 값을 Plan.fallback 으로 그대로 옮기는지
  3) api.rag.sse.chat_event_stream() — fallback=True 면 cache_put 을 건너뛰는지(정상 시엔 호출)
"""
import queue as queue_mod
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "api", ROOT / "src"):
    sys.path.insert(0, str(p))

import query_planner  # noqa: E402
from api.rag import answer as answer_mod  # noqa: E402
from api.rag import sse  # noqa: E402


# ════════════════════════ 1) query_planner.plan_query — fallback 필드 ════════════════════════

def test_plan_query_success_has_fallback_false(monkeypatch):
    plan = query_planner.QueryPlan(
        should_split=False,
        items=[query_planner.PlanItem(question="예금보호한도가 얼마인가요?", intent="informational")])
    fake_completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=plan, content=None))],
        usage=None, model="gpt-5.6-luna")
    monkeypatch.setattr(query_planner, "_parse", lambda *a, **kw: fake_completion)
    monkeypatch.setattr(query_planner, "record_openai_generation", lambda *a, **kw: None)

    result = query_planner.plan_query("예금보호한도가 얼마인가요?")

    assert result["fallback"] is False
    assert result["items"][0]["intent"] == "informational"


def test_plan_query_api_failure_has_fallback_true(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("simulated OpenAI outage")
    monkeypatch.setattr(query_planner, "_get_client", boom)

    result = query_planner.plan_query("착오송금 신청 링크를 알려주세요.")

    assert result["fallback"] is True
    assert result["should_split"] is False
    assert result["items"] == [{"question": "착오송금 신청 링크를 알려주세요.", "intent": "informational"}]


def test_plan_query_empty_response_has_fallback_true(monkeypatch):
    """파싱은 됐지만 items 가 빈 경우도 안전 기본값(_fallback)으로 떨어진다 — 이것도 fallback=True."""
    plan = query_planner.QueryPlan(should_split=False, items=[])
    fake_completion = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=plan, content=None))],
        usage=None, model="gpt-5.6-luna")
    monkeypatch.setattr(query_planner, "_parse", lambda *a, **kw: fake_completion)
    monkeypatch.setattr(query_planner, "record_openai_generation", lambda *a, **kw: None)

    result = query_planner.plan_query("아무 질문")

    assert result["fallback"] is True


# ════════════════════════ 2) api.rag.answer.plan — Plan.fallback 전달 ════════════════════════

def test_answer_plan_propagates_fallback_true(monkeypatch):
    monkeypatch.setattr(answer_mod, "get_param", lambda name, default: default)
    monkeypatch.setattr(answer_mod, "plan_query", lambda q: {
        "should_split": False, "items": [{"question": q, "intent": "informational"}],
        "fallback": True})

    p = answer_mod.plan("착오송금 신청 링크를 알려주세요.")

    assert p.fallback is True
    assert p.items == [("착오송금 신청 링크를 알려주세요.", "informational")]


def test_answer_plan_propagates_fallback_false(monkeypatch):
    monkeypatch.setattr(answer_mod, "get_param", lambda name, default: default)
    monkeypatch.setattr(answer_mod, "plan_query", lambda q: {
        "should_split": False, "items": [{"question": q, "intent": "informational"}],
        "fallback": False})

    p = answer_mod.plan("예금보호한도가 얼마인가요?")

    assert p.fallback is False


def test_plan_default_fallback_is_false_for_existing_callers():
    """기존 호출부(테스트 포함)가 Plan([...]) 처럼 fallback 없이 만들어도 '장애 아님'으로
    해석돼야 한다 — 새 필드가 하위 호환을 깨면 안 된다."""
    p = answer_mod.Plan([("질문", "informational")])
    assert p.fallback is False


# ════════════════════════ 3) sse.chat_event_stream — fallback 이면 캐시 적재 스킵 ═════════════════

def _fake_stream_one(prompt):
    q = queue_mod.Queue()
    q.put(("tok", "정상 생성된 답변입니다."))
    q.put(("end", None))
    return q


def _passthrough_finalize_sub(sp, body, marker_used_source):
    from api.schemas.chat import SubAnswer
    return SubAnswer(title=sp.question, answer=body, sources=[], attachments=[]), True


def _sp_pass(question):
    return answer_mod.SubPlan(
        question=question, intent="informational",
        top=[("page_a#1", 0.80, "실제로 관련된 본문")],
        prompt=[("system", "sys"), ("human", "질문: " + question + "\n답변:")],
        civil=None, evidence="근거 텍스트")


def _open_gates_and_spy_cache(monkeypatch):
    """게이트·대화저장·로깅을 전부 통과시키고, cache_put 호출 여부만 기록한다."""
    calls = []
    monkeypatch.setattr(sse.answer, "guardrail_hit", lambda *a, **kw: None)
    monkeypatch.setattr(sse.answer, "cache_get", lambda _q: None)
    monkeypatch.setattr(sse.answer, "cache_put", lambda *a: calls.append(a))
    monkeypatch.setattr(sse.conversation, "recent_messages", lambda _s: [])
    monkeypatch.setattr(sse.conversation, "save_user_message", lambda *a: None)
    monkeypatch.setattr(sse.conversation, "save_assistant_message", lambda *a: None)
    monkeypatch.setattr(sse.answer, "log_run", lambda *a, **kw: None)
    monkeypatch.setattr("gate1.run_gate1", lambda _q: SimpleNamespace(
        action="CONTINUE", label="CONTINUE", rule_id=None, reason="no_rule_matched",
        canonical_text=_q, rule_text=_q))
    monkeypatch.setattr("gate2.run_gate2", lambda _q: SimpleNamespace(
        action="CONTINUE", s_id=0.9, s_ood=0.1, threshold=0.5,
        nearest_out_cluster_id=None, nearest_out_category=None, reason="in_domain"))
    monkeypatch.setattr("query_rewriter.triage_query", lambda q, h: SimpleNamespace(
        rewritten=False, standalone_question=q, needs_clarification=False))
    monkeypatch.setattr(sse, "_stream_one", _fake_stream_one)
    monkeypatch.setattr(sse.answer, "finalize_sub", _passthrough_finalize_sub)
    monkeypatch.setattr(sse.answer, "prepare_sub", lambda q, intent: _sp_pass(q))
    return calls


def test_planner_fallback_skips_cache_put(monkeypatch):
    """플래너 API 호출 실패로 informational로 강등된 civil_petition 질문 — 근거만 있으면
    사후검증을 통과해 정상 응답처럼 보이지만, fallback=True 라 캐시에는 적재되지 않아야 한다."""
    calls = _open_gates_and_spy_cache(monkeypatch)
    monkeypatch.setattr(sse.answer, "plan",
                        lambda _q: sse.answer.Plan(
                            [("착오송금 신청 링크를 알려주세요.", "informational")], fallback=True))

    list(sse.chat_event_stream("착오송금 신청 링크를 알려주세요.", "sess", "req"))

    assert calls == [], "플래너가 장애로 폴백한 답은 캐시에 적재되면 안 된다"


def test_planner_success_still_caches_normally(monkeypatch):
    """대조군 — 플래너가 정상 작동(fallback=False)한 informational 단일 질문은 종전대로 캐시된다."""
    calls = _open_gates_and_spy_cache(monkeypatch)
    monkeypatch.setattr(sse.answer, "plan",
                        lambda _q: sse.answer.Plan(
                            [("예금보호한도가 얼마인가요?", "informational")], fallback=False))

    list(sse.chat_event_stream("예금보호한도가 얼마인가요?", "sess", "req"))

    assert len(calls) == 1, "정상 경로의 캐시 적재 자체가 이번 수정으로 막히면 안 된다"
