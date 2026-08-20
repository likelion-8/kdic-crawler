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
    return SimpleNamespace(answer="답변", latency_ms=900, model_dump=lambda: {"answer": "답변"})


@pytest.fixture
def captured(monkeypatch):
    calls = []
    monkeypatch.setattr(sse.answer, "log_run",
                        lambda *a, **kw: calls.append(kw.get("served_from")))
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

    assert captured == ["cache"]


def test_a_guardrail_refusal_is_not_a_cache_hit(captured, monkeypatch):
    monkeypatch.setattr(sse.answer, "guardrail_hit", lambda *a, **kw: "금칙어")
    monkeypatch.setattr(sse.answer, "guardrail_refusal", lambda *a: _resp())

    list(sse.chat_event_stream("막히는 질문", "sess", "req"))

    # 검색을 안 탄 건 캐시와 같지만 '저장해 둔 답을 돌려준 것'은 아니다
    assert captured == [None]
