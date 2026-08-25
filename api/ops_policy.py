"""AD-009 운영 정책을 읽고 집행하는 한 곳.

종전에는 RateLimitMiddleware 안에만 정책 캐시가 있었고, 미들웨어가 볼 수 없는 값들은
저장만 되고 아무도 읽지 않았다(2026-08-25 QA):

  - `session_per_30min` — 세션 id 가 요청 **본문**에 있어서 미들웨어는 모른다.
    그래서 여기서 함수로 빼고, 세션 id 를 이미 아는 챗 라우터가 부른다.
  - `over_limit_message` — 화면에서 편집·저장되는데 429 문구는 코드에 박혀 있었다.
    관리자가 문구를 바꿔도 사용자는 옛 문구를 봤다.

## 한계 (미들웨어 카운터와 같다)

프로세스 메모리에 센다. uvicorn 워커를 N 개 띄우면 실질 한도가 N 배가 되고, 재시작하면
0 부터 다시 센다. 남용을 늦추는 장치이지 정확한 쿼터가 아니다 — 정확해야 하면 Redis 등
공유 저장소로 _SESSION_HITS 만 갈아끼운다.
"""
import logging
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

# AD-009 기본값 — admin_ops.DEFAULT_POLICY 와 같아야 한다. DB 를 못 읽어도 이 값으로 돈다.
DEFAULTS = {
    "ip_per_min": 10,
    "ip_per_day": 300,
    "session_per_30min": 30,
    "burst_per_10s": 3,
    "over_limit_message": "잠시 후 다시 시도해 주세요. 문의가 많아 잠깐 대기 중이에요.",
}
# 화면에서 못 바꾸는 값(admin_ops.READ_ONLY_POLICY_FIELDS)은 DB 값을 읽지 않는다.
_PATCHABLE = ("ip_per_min", "ip_per_day", "session_per_30min", "over_limit_message")

_TTL_S = 30.0
_cache = {"at": 0.0, "value": None}

SESSION_WINDOW_S = 1800.0        # 30분 — 정책 이름 그대로
_SESSION_HITS = defaultdict(deque)
_last_sweep = 0.0


def get_policy(now=None) -> dict:
    """ops_policy 최신 행 -> 정책 dict. 30초 TTL. DB 가 죽어도 기본값을 돌려준다."""
    now = time.monotonic() if now is None else now
    if now - _cache["at"] < _TTL_S and _cache["value"]:
        return _cache["value"]
    value = dict(DEFAULTS)
    try:
        from sqlalchemy import select
        from db import get_session
        from schema_admin import ops_policy
        with get_session() as session:
            row = session.execute(
                select(ops_policy).order_by(ops_policy.c.version.desc()).limit(1)).first()
        if row is not None and row.policy:
            for k in _PATCHABLE:
                if row.policy.get(k) is not None:
                    value[k] = row.policy[k]
    except Exception:  # noqa: BLE001 — 정책을 못 읽으면 기본값으로 제한한다
        logger.exception("ops_policy 조회 실패 — 기본 한도로 동작")
    _cache.update(at=now, value=value)
    return value


def reset_cache() -> None:
    """정책을 방금 저장했을 때 30초를 기다리지 않게 한다(admin_ops PATCH 직후)."""
    _cache.update(at=0.0, value=None)


def _sweep(now: float) -> None:
    """조용해진 세션 항목을 버린다 — 안 하면 세션 수만큼 dict 가 계속 커진다."""
    global _last_sweep
    if now - _last_sweep < SESSION_WINDOW_S:
        return
    _last_sweep = now
    cutoff = now - SESSION_WINDOW_S
    for key in [k for k, hits in _SESSION_HITS.items() if not hits or hits[-1] < cutoff]:
        del _SESSION_HITS[key]


def check_session_quota(session_id: str, now=None) -> None:
    """세션별 30분 한도를 재고, 넘었으면 RateLimitError(429). 통과하면 이번 요청을 센다.

    IP 한도(미들웨어)와 따로 재는 이유: 한 IP 뒤에 여러 사람이 있을 수 있고(사무실·NAT),
    반대로 한 사람이 IP 를 바꿔 가며 같은 세션을 이어갈 수도 있다. 정책이 두 축을 따로
    두고 있으니 집행도 따로 한다.

    거절된 요청은 세지 않는다 — 세면 계속 두드리는 쪽이 영원히 안 풀린다(미들웨어와 같은 규칙).
    """
    from api.errors import RateLimitError

    now = time.monotonic() if now is None else now
    policy = get_policy(now)
    limit = int(policy.get("session_per_30min") or 0)
    if limit <= 0:          # 0/None 이면 '제한 없음'으로 본다
        return

    _sweep(now)
    hits = _SESSION_HITS[session_id]
    cutoff = now - SESSION_WINDOW_S
    while hits and hits[0] < cutoff:
        hits.popleft()
    if len(hits) >= limit:
        logger.warning("세션 한도 초과: %s (%s/30분)", session_id, limit)
        raise RateLimitError(str(policy.get("over_limit_message") or
                                 DEFAULTS["over_limit_message"]))
    hits.append(now)
