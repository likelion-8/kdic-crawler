"""웹 경로 단계별 소요 시간 — AD-001 '단계별 평균 응답시간'의 유일한 원천.

Langfuse 로는 못 낸다. 게이트·캐시 조회는 record_span 점 이벤트라 소요가 남지 않고,
route_search_chunks 는 CLI·평가 실행과 섞여 웹 경로만 골라낼 방법이 없다(2026-09-01 실측:
7일 route_search_chunks 4,445건 중 웹 sub_answer 는 680건). 그래서 서빙 경로에서 직접 잰다.

여기서 지키는 것은 '경로가 실제로 탄 단계만 남는다'다. 안 탄 단계를 0 으로 채우면 평균이
그만큼 낮아져 화면이 "검색은 공짜"라고 말하게 된다.
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
                           error=None, clarification=None,
                           model_dump=lambda **kw: {"answer": "답변"})


@pytest.fixture
def timings(monkeypatch):
    """log_run 이 받은 timings 딕셔너리를 그대로 붙잡는다."""
    seen = []
    monkeypatch.setattr(sse.answer, "log_run",
                        lambda *a, **kw: seen.append(kw.get("timings")))
    monkeypatch.setattr(sse.conversation, "recent_messages", lambda _s: [])
    monkeypatch.setattr(sse.conversation, "save_user_message", lambda *a: None)
    monkeypatch.setattr(sse.conversation, "save_assistant_message", lambda *a: None)
    monkeypatch.setattr(sse.answer, "guardrail_hit", lambda *a, **kw: None)
    return seen


def test_cache_hit_records_only_the_stages_it_actually_ran(timings, monkeypatch):
    monkeypatch.setattr(sse.answer, "cache_get", lambda _q: {"answer": "저장된 답변"})
    monkeypatch.setattr("api.schemas.chat.ChatResponse.model_validate",
                        staticmethod(lambda _d: _resp()))

    list(sse.chat_event_stream("착오송금 반환까지 얼마나 걸리나요?", "sess", "req"))

    assert len(timings) == 1
    recorded = timings[0]
    # 캐시에서 끝난 턴이 탄 것은 셋뿐이다 — 검색·답변 생성 키가 있으면 안 된다.
    assert set(recorded) == {"rewrite", "gate", "cache"}
    assert all(v >= 0 for v in recorded.values())


def _normal_path(monkeypatch):
    """게이트 통과 · 캐시 미스 · 되묻기 없음 — 검색부터 출처 판정까지 다 도는 턴."""
    monkeypatch.setattr(sse.answer, "cache_get", lambda _q: None)
    monkeypatch.setattr("gate1.run_gate1", lambda _q: SimpleNamespace(
        action="CONTINUE", label="CONTINUE", rule_id=None, reason="no_rule_matched",
        canonical_text=_q, rule_text=_q))
    monkeypatch.setattr("gate2.run_gate2", lambda _q: SimpleNamespace(
        action="CONTINUE", s_id=0.9, s_ood=0.1, threshold=0.5,
        nearest_out_cluster_id=None, nearest_out_category=None, reason="in_domain"))
    monkeypatch.setattr("query_rewriter.triage_query", lambda q, h: SimpleNamespace(
        rewritten=False, standalone_question=q, needs_clarification=False))
    monkeypatch.setattr(sse.answer, "plan",
                        lambda q: SimpleNamespace(items=[(q, "informational")], fallback=False))

    def _prepare(q, intent=None):
        return SimpleNamespace(question=q, intent=intent, top=[], prompt="p", civil=None,
                               evidence="", fixed_response=None, exit_at=None,
                               obs_marker=None, obs_used_source=None, obs_kind=None,
                               obs_appropriate=None, obs_normalized=None, obs_precheck=None)
    monkeypatch.setattr(sse.answer, "prepare_sub", _prepare)
    monkeypatch.setattr(sse, "_stream_one", lambda _p: _FakeTokens())
    monkeypatch.setattr(sse.answer, "finalize_sub",
                        lambda sp, body, used: (SimpleNamespace(answer=body, sources=[]), False))
    monkeypatch.setattr(sse.answer, "to_chat_response", lambda *a, **kw: _resp())


class _FakeTokens:
    """HCX 스트림 흉내 — 토큰 하나 흘리고 끝낸다."""
    def __init__(self):
        self._frames = [("tok", "답변 본문"), ("end", None)]

    def get(self, timeout=None):
        return self._frames.pop(0)


def test_full_path_records_all_seven_web_stages(timings, monkeypatch):
    _normal_path(monkeypatch)

    list(sse.chat_event_stream("착오송금 반환 신청은 어떻게 하나요?", "sess", "req"))

    assert len(timings) == 1
    assert set(timings[0]) == {"rewrite", "gate", "cache", "plan",
                               "retrieval", "generation", "validation"}
