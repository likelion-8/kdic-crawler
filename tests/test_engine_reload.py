"""retrieval._build_engines — ACTIVE 색인 버전이 바뀌면 엔진을 다시 조립한다(미구현 ⑤).

무거운 조립(임베딩·BM25)은 대역으로 바꾸고 재조립 트리거만 본다. 회귀 대상 : (1) 버전이
같으면 재조립하지 않는다(질의마다 수 초 멈추면 안 됨), (2) 바뀌면 재조립한다, (3) 버전 확인이
실패(None)하면 '바뀜'으로 치지 않는다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import retrieval  # noqa: E402


def _reset(monkeypatch):
    retrieval._engines.clear()
    monkeypatch.setattr(retrieval, "_engines_version", None)
    monkeypatch.setattr(retrieval, "_version_checked_at", 0.0)
    monkeypatch.setattr(retrieval, "_VERSION_CHECK_INTERVAL_S", 0.0)   # 매 호출 확인


def test_same_version_does_not_rebuild(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(retrieval, "_active_index_version", lambda: "v1")
    retrieval._engines.update(marker=1)
    monkeypatch.setattr(retrieval, "_engines_version", "v1")
    assert retrieval._index_changed() is False


def test_new_version_triggers_rebuild(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(retrieval, "_engines_version", "v1")
    monkeypatch.setattr(retrieval, "_active_index_version", lambda: "v2")
    assert retrieval._index_changed() is True


def test_unknown_version_is_not_a_change(monkeypatch):
    # DB 를 못 읽었으면 재조립하지 않는다 — 헛된 재조립은 질의를 수 초 멈춘다
    _reset(monkeypatch)
    monkeypatch.setattr(retrieval, "_engines_version", "v1")
    monkeypatch.setattr(retrieval, "_active_index_version", lambda: None)
    assert retrieval._index_changed() is False


def test_check_is_rate_limited(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.setattr(retrieval, "_VERSION_CHECK_INTERVAL_S", 3600.0)
    calls = {"n": 0}
    def probe():
        calls["n"] += 1
        return "v2"
    monkeypatch.setattr(retrieval, "_active_index_version", probe)
    monkeypatch.setattr(retrieval, "_engines_version", "v1")
    retrieval._index_changed(); retrieval._index_changed(); retrieval._index_changed()
    assert calls["n"] == 1, "간격 안에서는 DB 를 한 번만 본다"
