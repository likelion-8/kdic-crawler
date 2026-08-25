"""워커 상주 루프 — 예외로 죽지 않고, stop 이 서면 빠져나온다.

2026-08-25 QA 의 'QUEUED 고착'은 실행 주체가 아예 없어서 났다. 이제 API 프로세스가
poll_forever 를 데몬 스레드로 돌리는데(api/main.py lifespan), 그 루프가 예외 한 번에
조용히 죽으면 증상이 그대로 돌아온다 — 겉으로는 서버가 멀쩡하고 잡만 안 움직인다.
여기서 고정하는 것은 그 두 가지뿐이다: **안 죽는다**, **멈추라면 멈춘다**.
"""
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import worker  # noqa: E402

# 아래 autouse 픽스처가 이름을 가리므로 진짜 함수를 잡아 둔다 — 정리 로직 자체를 보는 테스트용
_REAL_RECLAIM = worker.reclaim_stale_jobs


@pytest.fixture(autouse=True)
def _no_db(monkeypatch):
    """poll_forever 기동 시의 고아 잡 정리는 실 DB(팀 공유 Supabase)를 탄다 — 여기선 끈다."""
    monkeypatch.setattr(worker, "reclaim_stale_jobs", lambda session: 0)
    monkeypatch.setattr(worker, "get_session", lambda: _NullSession())


class _NullSession:
    def __enter__(self):
        return None

    def __exit__(self, *exc):
        return False


def test_poll_forever_survives_exceptions_and_stops(monkeypatch):
    calls = []
    stop = threading.Event()

    def boom():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("DB 끊김")   # 첫 폴링이 터져도 루프는 계속돼야 한다
        if len(calls) >= 3:
            stop.set()
        return False

    monkeypatch.setattr(worker, "poll_once", boom)
    worker.poll_forever(stop=stop, interval=0)

    assert len(calls) >= 3, "예외 뒤에도 폴링이 이어져야 한다"
    assert stop.is_set()


def test_poll_forever_returns_immediately_if_already_stopped(monkeypatch):
    monkeypatch.setattr(worker, "poll_once",
                        lambda: (_ for _ in ()).throw(AssertionError("불려선 안 된다")))
    stop = threading.Event()
    stop.set()
    worker.poll_forever(stop=stop, interval=0)


def test_poll_forever_runs_housekeeping(monkeypatch):
    """보관기간 파기 tick 이 루프에 붙어 있다 — 빠지면 auto_purge 가 다시 장식이 된다."""
    import housekeeping

    ticks, stop = [], threading.Event()
    monkeypatch.setattr(worker, "poll_once", lambda: False)
    monkeypatch.setattr(housekeeping, "tick", lambda: (ticks.append(1), stop.set())[0])
    worker.poll_forever(stop=stop, interval=0)
    assert ticks


def test_reclaim_marks_only_old_running_jobs(monkeypatch):
    """기동 시 고아 잡 정리 — 오래된 RUNNING 만 FAILED 로 마감하고, 실패 단계를 남긴다.

    동시 실행 1개 규칙이 QUEUED·RUNNING 을 같이 보므로, 죽은 워커가 남긴 RUNNING 한 행이
    이후의 모든 작업 생성을 409 로 막는다(2026-08-25 실제 발생: 08-24 CHANGE_DETECT).
    """
    from datetime import datetime, timedelta, timezone

    old_job = SimpleNamespace(
        id="job-old",
        steps=[{"name": "수집", "status": "RUNNING"}, {"name": "변환", "status": "QUEUED"}])

    class _Session:
        def __init__(self):
            self.query = None

        def execute(self, statement):
            self.query = statement
            return SimpleNamespace(all=lambda: [old_job])

    finished = {}
    monkeypatch.setattr(worker, "_finish",
                        lambda session, job_id, status, **kw: finished.update(
                            {"id": job_id, "status": status, **kw}))

    session = _Session()
    assert _REAL_RECLAIM(session) == 1
    assert finished["id"] == "job-old"
    assert finished["status"] == "FAILED"
    assert finished["error"]["stage"] == "수집", "멈춘 단계가 실패 상세에 남아야 한다"
    assert finished["error"]["code"] == "INTERNAL"
    assert finished["skip_remaining"] is True

    # created_at < now - STALE_RUNNING_H 로 거른다 — 방금 시작한 남의 잡을 뺏지 않기 위한 창
    where = str(session.query.compile(compile_kwargs={"literal_binds": True}))
    assert "RUNNING" in where
    cutoff = datetime.now(timezone.utc) - timedelta(hours=worker.STALE_RUNNING_H)
    assert cutoff.strftime("%Y-%m-%d %H") in where, "created_at 컷오프가 지금보다 과거여야 한다"
