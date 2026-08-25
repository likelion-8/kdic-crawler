"""워커 상주 루프 — 예외로 죽지 않고, stop 이 서면 빠져나온다.

2026-08-25 QA 의 'QUEUED 고착'은 실행 주체가 아예 없어서 났다. 이제 API 프로세스가
poll_forever 를 데몬 스레드로 돌리는데(api/main.py lifespan), 그 루프가 예외 한 번에
조용히 죽으면 증상이 그대로 돌아온다 — 겉으로는 서버가 멀쩡하고 잡만 안 움직인다.
여기서 고정하는 것은 그 두 가지뿐이다: **안 죽는다**, **멈추라면 멈춘다**.
"""
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import worker  # noqa: E402


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
