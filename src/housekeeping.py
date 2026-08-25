"""보관기간 파기 — AD-009 `auto_purge` 정책의 실제 실행 주체.

2026-08-25 QA 전까지 auto_purge 는 화면에서 켜고 끌 수 있고 DB 에 저장도 됐지만, 그 값을
읽어 실제로 뭔가를 지우는 코드가 없었다. 활동 로그 화면의 '이번 주 삭제 예정' 숫자도
계산만 하고 아무 일도 일어나지 않았다(admin_activity.RETENTION_DAYS 주석이 "별도 정리
작업이 지운다(아직 없다)"라고 적고 있었다). 이 파일이 그 정리 작업이다.

## 어디서 도는가

파이프라인 워커 루프가 하루 한 번 tick() 을 부른다(src/worker.poll_forever). 크론·별도
스케줄러를 새로 들이지 않은 이유는 이미 상주하는 프로세스가 있어서다 — 실행 주체를
늘리는 것 자체가 이번에 고친 문제였다.

## 안전장치

- 정책의 auto_purge 가 False 면 아무것도 지우지 않는다.
- 파기 자체를 활동 로그에 남긴다. 감사 기록을 지운 사실이 감사 기록에 남아야 한다.
- 하루 한 번만 돈다(_MIN_INTERVAL_S). 워커가 재시작되면 그 다음 tick 에서 한 번 더 돌 수
  있지만, 같은 조건의 DELETE 라 두 번 돌아도 결과가 같다.

⚠️ **되돌릴 수 없는 삭제**다. 보관기간(admin_activity.RETENTION_DAYS = 90일)을 줄이면
   그만큼이 다음 tick 에서 한꺼번에 사라진다. 기간은 코드 상수라 화면에서 못 바꾼다.

정기 변경 감지(주기적 CHANGE_DETECT 인큐)는 **일부러 넣지 않았다** — 외부 사이트를 실제로
크롤하는 작업이라, API 를 띄운 개발 PC 마다 매일 kdic.or.kr 을 두드리게 된다. 운영 배포
방식이 정해진 뒤에 붙일 것.
"""
import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, insert, select

from schema_admin import admin_activity_logs, ops_policy

logger = logging.getLogger("housekeeping")

# 보관 기간 정본은 api/routers/admin_activity.RETENTION_DAYS 다. src/ 는 api/ 를 import 하지
# 않는 방향이라(의존 방향 유지) 값을 여기 두고, 어긋나면 tests/test_housekeeping.py 가 잡는다.
RETENTION_DAYS = 90

_MIN_INTERVAL_S = 24 * 60 * 60
_last_run = {"at": None}   # monotonic. None 이면 아직 한 번도 안 돌았다

ACTION_RETENTION_PURGE = "보관기간 만료 활동 로그 파기"


def _auto_purge_enabled(session) -> bool:
    row = session.execute(
        select(ops_policy).order_by(ops_policy.c.version.desc()).limit(1)).first()
    if row is None or not row.policy:
        return True     # 정책 행이 없으면 기본값(admin_ops.DEFAULT_POLICY) 그대로 켜짐
    return row.policy.get("auto_purge") is not False


def purge_expired_activity_logs(session) -> int:
    """보관기간이 지난 활동 로그를 지우고 지운 건수를 돌려준다. 정책이 꺼져 있으면 0."""
    if not _auto_purge_enabled(session):
        logger.debug("auto_purge 꺼짐 — 파기 건너뜀")
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
    doomed = admin_activity_logs.c.occurred_at < cutoff
    count = session.execute(
        select(func.count()).select_from(admin_activity_logs).where(doomed)).scalar_one()
    if count == 0:
        return 0

    session.execute(delete(admin_activity_logs).where(doomed))
    # 감사 기록을 지운 사실도 감사 기록이다. write_activity_log(api/deps.py)는 Request 를
    # 요구해서 여기서 못 쓴다 — 컬럼에 직접 적는다.
    session.execute(insert(admin_activity_logs).values(
        occurred_at=datetime.now(timezone.utc),
        actor="system", actor_role="ADMIN",
        action=ACTION_RETENTION_PURGE,
        target=f"{RETENTION_DAYS}일 경과 활동 로그 {count}건",
        result="성공",
        reason=f"운영 정책 auto_purge — 보관기간 {RETENTION_DAYS}일 경과",
    ))
    session.commit()
    logger.info("보관기간 파기: 활동 로그 %s건 삭제(%s일 경과)", count, RETENTION_DAYS)
    return count


def tick(now=None) -> None:
    """하루 한 번만 실제 작업을 한다. 워커 루프가 매 주기 불러도 안전하다."""
    now = time.monotonic() if now is None else now
    if _last_run["at"] is not None and now - _last_run["at"] < _MIN_INTERVAL_S:
        return
    _last_run["at"] = now
    try:
        with _open_session() as session:
            purge_expired_activity_logs(session)
    except Exception:  # noqa: BLE001 — 정리 작업 실패가 워커를 멈추면 안 된다
        logger.exception("보관기간 파기 실패 — 다음 주기에 다시 시도한다")


def _open_session():
    """세션 여는 지점을 함수로 둔다 — 테스트가 실 DB(팀 공유 Supabase)를 건드리지 않게."""
    from db import get_session
    return get_session()
