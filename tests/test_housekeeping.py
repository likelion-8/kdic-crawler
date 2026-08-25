"""보관기간 파기 — 정책이 꺼져 있으면 아무것도 지우지 않고, tick 은 하루 한 번만 돈다.

되돌릴 수 없는 DELETE 라 두 가지만 못 박는다: **꺼져 있으면 안 지운다**, **연달아 불러도
두 번 지우지 않는다**. 실제 DB 를 쓰지 않는다(팀 공유 Supabase 라 테스트가 행을 지우면 안 된다).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import housekeeping  # noqa: E402


class _FakeSession:
    """정책 행만 돌려주는 최소 세션. 삭제 경로로 넘어가면 execute 가 기록된다."""

    def __init__(self, policy):
        self._policy = policy
        self.calls = []

    def execute(self, statement):
        self.calls.append(statement)
        return _FakeResult(self._policy)

    def commit(self):
        self.calls.append("commit")


class _FakeResult:
    def __init__(self, policy):
        self._policy = policy

    def first(self):
        return type("Row", (), {"policy": self._policy})()

    def scalar_one(self):
        return 0   # 지울 행이 없다 — auto_purge 가 켜져 있어도 조기 반환된다


def test_auto_purge_off_deletes_nothing():
    session = _FakeSession({"auto_purge": False})
    assert housekeeping.purge_expired_activity_logs(session) == 0
    assert len(session.calls) == 1, "정책 조회 한 번 말고는 아무것도 하지 않아야 한다"


def test_auto_purge_on_but_nothing_expired():
    session = _FakeSession({"auto_purge": True})
    assert housekeeping.purge_expired_activity_logs(session) == 0
    assert "commit" not in session.calls, "지운 게 없으면 감사 기록도 남기지 않는다"


class _FakeSessionCtx:
    """with 문에 넣을 수 있는 가짜 세션 — 실 DB(팀 공유 Supabase)에 붙지 않는다."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


def test_tick_runs_at_most_once_a_day(monkeypatch):
    runs = []
    monkeypatch.setattr(housekeeping, "_last_run", {"at": None})
    monkeypatch.setattr(housekeeping, "purge_expired_activity_logs", lambda s: runs.append(1))
    monkeypatch.setattr(housekeeping, "_open_session",
                        lambda: _FakeSessionCtx(_FakeSession({"auto_purge": True})))

    housekeeping.tick(now=0.0)
    housekeeping.tick(now=60.0)
    housekeeping.tick(now=3600.0)
    assert len(runs) == 1, "하루가 안 지났으면 다시 돌지 않는다"

    housekeeping.tick(now=24 * 60 * 60 + 1)
    assert len(runs) == 2, "하루가 지나면 다시 돈다"


def test_retention_days_matches_the_api_constant():
    """정본은 api/routers/admin_activity.RETENTION_DAYS. 두 값이 갈리면 화면의 '삭제 예정'과
    실제 삭제 시점이 어긋난다."""
    import re
    text = (ROOT / "api/routers/admin_activity.py").read_text(encoding="utf-8")
    api_days = int(re.search(r"^RETENTION_DAYS = (\d+)", text, re.M).group(1))
    assert housekeeping.RETENTION_DAYS == api_days
