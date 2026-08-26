"""웹 요청 하나가 Langfuse trace **하나**로 남는지(=모든 단계 span 이 루트 밑에 붙는지) 검증.

지키려는 것은 계층이다. 웹 SSE 제너레이터는 스레드풀이 조각 단위로 소비해 contextvar 가
유실되므로, 계측을 `as_child_of(부모)` 밖에서 하면 그 span 은 루트에 안 붙고 **별개의 고아
trace** 가 된다. 2026-08-26 실측에서 전체 trace 14,078건 중 ~70%가 그렇게 쌓인 단발
trace 였고(route_search_chunks 9,993 등), 정작 대화 상세가 링크하는 web_chat trace 는 자식이
하나도 없는 껍데기였다. 계측을 새로 추가할 때 이 테스트가 먼저 깨지도록 둔다.

실제 Langfuse·OpenAI·HCX·Supabase 는 하나도 부르지 않는다 — 전부 monkeypatch 대역이다.
"""
import queue as queue_mod
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "api", ROOT / "src"):
    sys.path.insert(0, str(p))

import query_rewriter  # noqa: E402
from api.rag import answer as answer_mod  # noqa: E402
from api.rag import sse  # noqa: E402

# 이 함수들 안에서 계측된 단계가 돈다 — @observe 가 붙은 것(plan_query·route_search_chunks·
# classify_question_type·call_hyperclova)과 OpenAI generation(plan_query_llm·
# triage_query_llm·validate_answer_llm·classify_intent_llm). 부모 스코프 밖에서 부르면
# 그 span 들이 통째로 고아가 되므로 "부모가 열린 채로 불렸는가"를 따로 확인한다.
#
# triage_query 가 여기 있는 이유는 실제로 그 사고가 났기 때문이다(2026-08-26): span 은
# 열었는데 호출을 as_child_of 밖에 두어 triage_query_llm 이 고아 trace 로 나갔다.
_MUST_RUN_UNDER_PARENT = (
    (answer_mod, "plan"),
    (answer_mod, "prepare_sub"),
    (answer_mod, "finalize_sub"),
    (query_rewriter, "triage_query"),
)


@pytest.fixture
def tree(monkeypatch):
    """sse 가 만드는 span 을 (이름, 부모이름) 으로 수집한다. 부모는 as_child_of 스택의 꼭대기."""
    created = []      # [(span_name, parent_name)]
    called_under = {}  # {함수이름: 부모이름 or None}
    stack = []

    class _Span:
        def __init__(self, name):
            self.name = name

    def _new(name):
        parent = stack[-1] if stack else None
        created.append((name, parent))
        return _Span(name)

    @contextmanager
    def fake_as_child_of(span):
        stack.append(span.name if span is not None else None)
        try:
            yield
        finally:
            stack.pop()

    monkeypatch.setattr(sse, "as_child_of", fake_as_child_of)
    monkeypatch.setattr(sse, "open_span", lambda name, **kw: _new(name))
    monkeypatch.setattr(sse, "record_span", lambda name, **kw: _new(name))
    monkeypatch.setattr(sse, "close_span", lambda span, **kw: None)
    monkeypatch.setattr(sse, "trace_id_of", lambda span: "trace-1")
    monkeypatch.setattr(sse, "record_gate1_span", lambda *a: _new("gate1_rulebase"))
    monkeypatch.setattr(sse, "record_gate2_span", lambda *a: _new("gate2_embedding"))

    def watch():
        """@observe 가 붙은 단계를 품은 호출을 감싸 '부모가 열린 채로 불렸는지' 기록한다.
        대역(_normal_path)을 다 깐 **뒤에** 불러야 한다 — 먼저 감싸면 대역이 덮어써 버린다."""
        for owner, fn in _MUST_RUN_UNDER_PARENT:
            original = getattr(owner, fn)

            def wrapped(*a, _fn=fn, _orig=original, **kw):
                called_under[_fn] = stack[-1] if stack else None
                return _orig(*a, **kw)

            monkeypatch.setattr(owner, fn, wrapped)

    return SimpleNamespace(created=created, called_under=called_under, watch=watch)


def _fake_stream_one(_prompt):
    q = queue_mod.Queue()
    q.put(("tok", "본문입니다."))
    q.put(("end", None))
    return q


def _normal_path(monkeypatch):
    """검색·생성까지 다 도는 정상 경로. 게이트는 전부 CONTINUE, 캐시는 미스."""
    monkeypatch.setattr(sse.answer, "guardrail_hit", lambda *a, **kw: None)
    monkeypatch.setattr(sse.answer, "cache_get", lambda _q: None)
    monkeypatch.setattr(sse.answer, "cache_put", lambda *a: None)
    monkeypatch.setattr(sse.answer, "log_run", lambda *a, **kw: None)
    monkeypatch.setattr(sse.conversation, "recent_messages", lambda _s: [])
    monkeypatch.setattr(sse.conversation, "save_user_message", lambda *a: None)
    monkeypatch.setattr(sse.conversation, "save_assistant_message", lambda *a: None)
    monkeypatch.setattr("gate1.run_gate1", lambda _q: SimpleNamespace(
        action="CONTINUE", label="CONTINUE", rule_id=None, reason="no_rule_matched",
        canonical_text=_q, rule_text=_q))
    monkeypatch.setattr("gate2.run_gate2", lambda _q: SimpleNamespace(
        action="CONTINUE", s_id=0.9, s_ood=0.1, threshold=0.5,
        nearest_out_cluster_id=None, nearest_out_category=None, reason="in_domain"))
    monkeypatch.setattr("query_rewriter.triage_query", lambda q, h: SimpleNamespace(
        rewritten=False, standalone_question=q, needs_clarification=False))
    monkeypatch.setattr(sse.answer, "plan",
                        lambda _q: sse.answer.Plan([("착오송금 신청 방법은?", "informational")]))
    monkeypatch.setattr(sse.answer, "prepare_sub", lambda q, intent: answer_mod.SubPlan(
        question=q, intent=intent, top=[("page_a#1", 0.8, "본문")],
        prompt=[("system", "sys"), ("human", q)], civil=None, evidence="근거"))
    monkeypatch.setattr(sse, "_stream_one", _fake_stream_one)
    monkeypatch.setattr(sse.answer, "finalize_sub", lambda sp, body, marker: (
        answer_mod.SubAnswer(title=sp.question, answer=body, sources=[], attachments=[]), True))


def test_every_step_span_hangs_under_the_request_root(tree, monkeypatch):
    """루트(web_chat)를 뺀 모든 span 에 부모가 있어야 한다. 부모 None 인 span 이 곧 고아 trace."""
    _normal_path(monkeypatch)

    list(sse.chat_event_stream("착오송금 신청 방법은?", "sess", "req"))

    orphans = [name for name, parent in tree.created if parent is None and name != "web_chat"]
    assert orphans == [], f"루트에 안 붙은 span(=고아 trace 가 된다): {orphans}"


def test_the_expected_stages_are_actually_recorded(tree, monkeypatch):
    """계층만 맞고 단계가 비면 의미가 없다 — 정상 경로에서 남아야 할 span 목록."""
    _normal_path(monkeypatch)

    list(sse.chat_event_stream("착오송금 신청 방법은?", "sess", "req"))

    names = [name for name, _ in tree.created]
    for expected in ("web_chat", "gate1_rulebase", "query_rewrite", "cache_lookup",
                     "gate2_embedding", "sub_answer", "hcx_stream", "answer_validation"):
        assert expected in names, f"{expected} span 이 안 남았다: {names}"
    # 하위 질문 밑에 생성·검증이 붙어야 복합 질문에서 어느 하위가 느렸는지 읽을 수 있다
    assert ("hcx_stream", "sub_answer") in tree.created
    assert ("answer_validation", "sub_answer") in tree.created


@pytest.mark.parametrize("fn", [fn for _, fn in _MUST_RUN_UNDER_PARENT])
def test_observed_helpers_run_inside_a_parent_scope(tree, monkeypatch, fn):
    """계측된 단계를 품은 호출은 부모 스코프 안에서 돌아야 한다. 밖에서 부르면
    plan_query·route_search_chunks·call_hyperclova·OpenAI generation 이 별개 trace 로 흩어진다."""
    _normal_path(monkeypatch)
    tree.watch()

    list(sse.chat_event_stream("착오송금 신청 방법은?", "sess", "req"))

    assert tree.called_under.get(fn) is not None, f"{fn} 이 as_child_of 밖에서 불렸다"
