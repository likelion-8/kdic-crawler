"""관리자 인증(AD-000 · AD-010) 계약 테스트.

DB 없이 돈다 — 가짜 세션·가짜 신원으로 라우터 함수를 직접 부르거나 TestClient 로 태운다.

가장 중요한 축은 **상태코드**다. 이 화면은 코드 하나가 어긋나면 증상이 조용하다.

    401  세션 만료  → 프론트가 경로도 안 보고 로그아웃시킨다
    403  비밀번호 불일치 · 권한 없음 · 재확인 만료
    423  임시 잠금 (+ locked_until)
    410  만료·사용된 재설정 링크
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.deps import (REAUTH_WINDOW, RISKY_ACTIONS, AdminIdentity,
                      get_current_admin, reauth_remaining_s, require_reauth)
from api.errors import ForbiddenError, GoneError, LockedError

UTC = timezone.utc


def _identity(*, last_auth_ago=timedelta(0), role="ADMIN") -> AdminIdentity:
    now = datetime.now(UTC)
    return AdminIdentity(
        session_id="sess-hash", account_id="acc-1", email="admin@demo", name="관리자",
        role=role, session_started_at=now, last_activity_at=now,
        last_auth_at=now - last_auth_ago,
    )


def _fake_request():
    """client_ip · request.state.request_id 만 읽히므로 그 두 개만 흉내 낸다."""
    return SimpleNamespace(
        headers={}, client=SimpleNamespace(host="127.0.0.1"),
        state=SimpleNamespace(request_id="req-test"),
    )


# ---------------------------------------------------------- 재인증 헬퍼 (작업 1)
#
# B(PUT /ops-policy) · D(긴급 롤백) 트랙이 이 두 개를 import 한다. 시그니처가 바뀌면
# 남의 라우터가 같이 깨지므로 여기서 고정해 둔다.

def test_reauth_is_valid_right_after_authenticating():
    # now 를 고정해서 넘긴다 — _identity() 생성과 reauth_remaining_s() 계산 사이에 1초 미만이
    # 흘러도 int() 절삭으로 1799 가 나와 간헐 실패했다(2026-08-12 실측). 함수가 now 파라미터를
    # 받는 이유가 정확히 이 재현성이다.
    me = _identity()
    assert reauth_remaining_s(me, now=me.last_auth_at) == int(REAUTH_WINDOW.total_seconds())


def test_reauth_expires_after_the_window():
    assert reauth_remaining_s(_identity(last_auth_ago=timedelta(minutes=31))) == 0


def test_remaining_never_goes_negative():
    """프론트가 이 값을 그대로 카운트다운에 쓴다 — 음수가 나가면 '-3초'가 찍힌다."""
    assert reauth_remaining_s(_identity(last_auth_ago=timedelta(hours=5))) == 0


def test_require_reauth_passes_a_fresh_identity_through():
    me = _identity(last_auth_ago=timedelta(minutes=29))
    assert require_reauth(me) is me


def test_require_reauth_blocks_with_403_not_401():
    """🔴 401 로 주면 프론트가 경로를 안 보고 expireSession() 한다 — 위험 작업을 누를 때마다
    로그아웃되어 재확인을 할 기회조차 없다."""
    with pytest.raises(ForbiddenError) as caught:
        require_reauth(_identity(last_auth_ago=timedelta(minutes=31)))
    assert caught.value.status_code == 403


def test_the_shared_helper_keeps_its_name_and_shape():
    """다른 트랙이 import 하는 이름이다. 바꾸려면 채널에 먼저 알려야 한다."""
    from api import deps
    assert hasattr(deps, "require_reauth")
    assert hasattr(deps, "ReauthedAdmin")
    assert hasattr(deps, "reauth_remaining_s")


# ------------------------------------------------------ 오류 봉투 · 상태코드

def test_locked_and_gone_carry_the_right_status():
    assert LockedError.status_code == 423
    assert GoneError.status_code == 410


def test_extra_fields_ride_along_in_the_error_body():
    """423 본문에 locked_until 이 실려야 화면이 잔여 카운트다운을 그린다(A2)."""
    from api.errors import build_error_body
    exc = LockedError(extra={"locked_until": "2026-08-12T10:00:00+09:00"})
    body = build_error_body(code=exc.code, user_message=exc.user_message,
                            retryable=exc.retryable, fallback_sources=exc.fallback_sources,
                            request_id="req-1")
    for key, value in exc.extra.items():
        body.setdefault(key, value)
    assert body["locked_until"] == "2026-08-12T10:00:00+09:00"
    assert body["code"] == "INTERNAL"       # 봉투 5필드는 그대로다


def test_extra_cannot_overwrite_the_envelope():
    """extra 가 code·request_id 를 덮으면 프론트 분기가 통째로 깨진다."""
    from api.errors import build_error_body
    exc = LockedError(extra={"code": "HACKED", "request_id": "spoofed"})
    body = build_error_body(code=exc.code, user_message=exc.user_message,
                            retryable=exc.retryable, fallback_sources=exc.fallback_sources,
                            request_id="req-1")
    for key, value in exc.extra.items():
        body.setdefault(key, value)
    assert body["code"] == "INTERNAL"
    assert body["request_id"] == "req-1"


# ---------------------------------------------------------------- 위험 작업 어휘

def test_risky_actions_reach_the_right_screen():
    """활동 로그 상세의 [연결 보기]가 action 문자열 정규식으로 이동처를 정한다.
    계정·권한 계열은 접근 관리로 가야 하고, '임시 잠금'은 연결이 없어야 한다."""
    import re
    account_link = re.compile(r"권한|계정")
    no_link = re.compile(r"^로그인|^로그아웃|로그인 실패|임시 잠금|^로그 조회|^로그 내보내기|^활동 로그")

    from api.deps import (ACTION_ACCOUNT_DEACTIVATED, ACTION_ACCOUNT_INVITED,
                          ACTION_ACCOUNT_LOCKED, ACTION_ROLE_CHANGED)
    for action in (ACTION_ROLE_CHANGED, ACTION_ACCOUNT_INVITED, ACTION_ACCOUNT_DEACTIVATED):
        assert account_link.search(action), f"{action} 이 접근 관리로 못 간다"
        assert not no_link.search(action)
    assert no_link.search(ACTION_ACCOUNT_LOCKED), "'임시 잠금'은 연결 없음이어야 한다"


def test_risky_actions_include_the_three_reauth_targets():
    """재인증이 필요한 3종(전체 캐시 비우기·권한 변경·롤백)은 위험 작업 목록에 있어야 한다."""
    from api.deps import ACTION_ROLE_CHANGED
    assert ACTION_ROLE_CHANGED in RISKY_ACTIONS
    assert "전체 캐시 비우기" in RISKY_ACTIONS
    assert "긴급 롤백" in RISKY_ACTIONS


# ─────────────────────────── 가짜 DB · TestClient ───────────────────────────

class _Result:
    """db.execute(...) 의 반환 흉내. 라우터가 쓰는 네 가지만 있으면 된다."""

    def __init__(self, *, rows=None, scalar=0):
        self._rows = rows if rows is not None else []
        self._scalar = scalar

    def scalar_one(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self


class _FakeDb:
    """미리 넣어 둔 결과를 순서대로 돌려준다. 모자라면 빈 것을 준다 — 권한 테스트는 쿼리까지
    가지 않고 403 으로 끝나므로 개수를 정확히 맞출 필요가 없다."""

    def __init__(self, *results):
        self.results = list(results)
        self.executed = []

    def execute(self, statement, *args):
        self.executed.append(statement)
        return self.results.pop(0) if self.results else _Result()

    def commit(self):
        pass

    def rollback(self):
        pass


def _admin_dep(role: str, *, last_auth_ago=timedelta(0)):
    return lambda: _identity(role=role, last_auth_ago=last_auth_ago)


def _client(role: str, db=None, *, last_auth_ago=timedelta(0)):
    from api.deps import get_db
    from api.main import create_app
    app = create_app()
    app.dependency_overrides[get_current_admin] = _admin_dep(role, last_auth_ago=last_auth_ago)
    app.dependency_overrides[get_db] = lambda: db if db is not None else _FakeDb()
    return TestClient(app)


# ─────────────────────────── 권한 경계 ───────────────────────────
#
# 계정·권한을 다루는 창구는 ADMIN 전용이다. 화면이 버튼을 숨기는 건 UX 이고, 여기가 실제 벽이다.

@pytest.mark.parametrize("path", [
    "/api/admin/security/summary",
    "/api/admin/accounts",
    "/api/admin/login-failures",
])
@pytest.mark.parametrize("role", ["VIEWER", "OPERATOR", "EDITOR"])
def test_account_screens_are_admin_only(path, role):
    with _client(role) as client:
        assert client.get(path).status_code == 403


def test_roles_and_permissions_are_open_to_any_authenticated_admin():
    """역할 정의와 '내 권한'은 비밀이 아니다 — VIEWER 도 자기 화면을 그리려면 필요하다."""
    with _client("VIEWER") as client:
        roles = client.get("/api/admin/roles")
        mine = client.get("/api/admin/me/permissions")
    assert roles.status_code == 200
    assert [r["role"] for r in roles.json()] == ["VIEWER", "OPERATOR", "EDITOR", "ADMIN"]
    assert mine.status_code == 200
    assert mine.json()["role"] == "VIEWER"
    assert mine.json()["rank"] == 0


def test_permissions_grow_with_the_role():
    """상위 역할이 하위 역할의 권한을 모두 포함해야 한다 — 안 그러면 승격이 권한을 뺏는다."""
    from api.routers.admin_auth import PERMISSIONS_BY_ROLE, ROLE_RANK
    ordered = sorted(PERMISSIONS_BY_ROLE, key=lambda r: ROLE_RANK[r])
    for lower, higher in zip(ordered, ordered[1:]):
        assert set(PERMISSIONS_BY_ROLE[lower]) <= set(PERMISSIONS_BY_ROLE[higher]), (
            f"{higher} 가 {lower} 의 권한을 잃는다")


# ─────────────────────────── 임시 잠금 (A2) ───────────────────────────

def test_lockout_triggers_on_the_threshold_attempt():
    """창 안에 이미 THRESHOLD-1 건이 있으면 이번 시도로 잠긴다."""
    from api.routers.admin_auth import LOCKOUT_THRESHOLD, _record_login_failure
    db = _FakeDb(_Result(scalar=LOCKOUT_THRESHOLD - 1))
    locked = _record_login_failure(db, _fake_request(), "a@demo", datetime.now(UTC))
    assert locked is not None


def test_lockout_does_not_trigger_below_the_threshold():
    from api.routers.admin_auth import LOCKOUT_THRESHOLD, _record_login_failure
    db = _FakeDb(_Result(scalar=LOCKOUT_THRESHOLD - 2))
    assert _record_login_failure(db, _fake_request(), "a@demo", datetime.now(UTC)) is None


def test_an_expired_lock_no_longer_blocks():
    """잠금이 지난 행이 남아 있어도 다시 로그인할 수 있어야 한다."""
    from api.routers.admin_auth import _active_lock
    now = datetime.now(UTC)
    assert _active_lock(_FakeDb(_Result(scalar=now - timedelta(minutes=1))), "a@demo", now) is None
    assert _active_lock(_FakeDb(_Result(scalar=now + timedelta(minutes=5))), "a@demo", now) is not None
    assert _active_lock(_FakeDb(_Result(scalar=None)), "a@demo", now) is None


# ─────────────────────────── 비밀번호 정책 ───────────────────────────

@pytest.mark.parametrize("password", [
    "short1!",              # 10자 미만
    "abcdefghijkl",         # 숫자·특수문자 없음
    "abcdefgh1234",         # 특수문자 없음
    "!@#$%^&*()12",         # 영문 없음
    "hong1234!@#$",         # 아이디(hong) 포함
])
def test_weak_passwords_are_rejected(password):
    from api.routers.admin_auth import _password_policy_error
    assert _password_policy_error(password, "hong@demo") is not None


def test_a_compliant_password_passes():
    from api.routers.admin_auth import _password_policy_error
    assert _password_policy_error("Kd1c!secure2026", "hong@demo") is None


# ─────────────────────────── 위험 작업 대상 파싱 (L7) ───────────────────────────

def test_target_splits_back_into_name_and_id():
    """활동 로그는 target 을 한 문자열로 저장한다. 화면(RiskyOp)은 둘로 나눠 요구한다."""
    from api.routers.admin_activity import split_target
    assert split_target("착오송금 안내 (dp_003)") == ("착오송금 안내", "dp_003")
    assert split_target("이름 (a) (b)") == ("이름 (a)", "b")


def test_an_unparsable_target_keeps_its_whole_text():
    """억지로 쪼개면 이름의 일부가 id 로 둔갑해 딥링크가 없는 대상을 가리킨다."""
    from api.routers.admin_activity import split_target
    assert split_target("admin@demo") == ("admin@demo", None)
    assert split_target(None) == ("", None)
    assert split_target("") == ("", None)


# ─────────────────────────── 파이프라인 마감 ───────────────────────────

def test_target_summary_is_built_by_the_server():
    """전체 작업은 targets 가 비어 있어 프론트가 건수를 알 수 없다(P2)."""
    from api.routers.admin_pipeline import _resolve_targets
    assert _resolve_targets(_FakeDb(), "FULL_RECRAWL", ["a", "b"]) == ("선택 2페이지", 2)
    assert _resolve_targets(_FakeDb(_Result(scalar=58)), "FULL_RECRAWL", []) == ("전체 58페이지", 58)
    # 평가는 단위가 페이지가 아니라 문항이다.
    assert _resolve_targets(_FakeDb(_Result(scalar=89)), "SMOKE_EVAL", []) == ("평가 89문항", 89)


def test_estimated_minutes_never_reads_as_instant():
    """'예상 0분'은 즉시 끝난다는 뜻으로 읽히는데 어떤 작업도 그렇지 않다."""
    from api.routers.admin_pipeline import _estimated_minutes
    assert _estimated_minutes("RECHUNK", 1) == 1
    assert _estimated_minutes("FULL_RECRAWL", 0) == 1
    assert _estimated_minutes("FULL_RECRAWL", 58) > 1


def test_job_status_filter_rejects_unknown_values():
    """조용히 무시하면 필터가 안 걸린 전체 목록이 나가는데 화면은 걸렀다고 믿는다."""
    with _client("OPERATOR") as client:
        assert client.get("/api/admin/jobs?status=BOGUS").status_code == 400


def test_job_status_filter_accepts_the_active_pair():
    """진행 중 작업 전용 조회(P4) — 프론트의 '1페이지에 있을 것' 가정을 대체한다."""
    with _client("OPERATOR", _FakeDb(_Result(scalar=0), _Result(rows=[]))) as client:
        response = client.get("/api/admin/jobs?status=RUNNING,QUEUED&size=1")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "size": 1}


def test_rollback_is_blocked_when_the_reauth_window_expired():
    """🔴 P5 — 서버가 독립 검증한다. 프론트의 runRisky 판정은 우회할 수 있다."""
    with _client("ADMIN", last_auth_ago=timedelta(minutes=31)) as client:
        response = client.post("/api/admin/jobs/00000000-0000-0000-0000-000000000001/rollback",
                               json={"reason": "잘못 반영됨"})
    assert response.status_code == 403


def test_rollback_needs_admin_even_with_a_fresh_reauth():
    """재인증은 '방금 확인했는가'이고 역할은 '누구인가'다 — 서로를 대체하지 못한다."""
    with _client("EDITOR") as client:
        response = client.post("/api/admin/jobs/00000000-0000-0000-0000-000000000001/rollback",
                               json={"reason": "잘못 반영됨"})
    assert response.status_code == 403


def test_recheck_requires_operator():
    with _client("VIEWER") as client:
        assert client.post("/api/admin/pipeline/changes/recheck", json={}).status_code == 403


def test_estimate_rejects_an_unknown_job_type():
    with _client("OPERATOR") as client:
        assert client.get("/api/admin/pipeline/estimate?type=BOGUS").status_code == 400


# ─────────────────────────── 라우터 등록 ───────────────────────────

def test_every_track_a_endpoint_reaches_the_app():
    """main.py 를 건드리지 않고도 붙는다는 약속의 확인. 빠지면 그 기능 전체가 404 인데
    서버는 멀쩡히 뜨고 로그도 조용하다."""
    from api.main import create_app
    paths = create_app().openapi()["paths"]
    for path in (
        "/api/admin/reauth",
        "/api/admin/roles",
        "/api/admin/me/permissions",
        "/api/admin/security/summary",
        "/api/admin/accounts",
        "/api/admin/accounts/{account_id}",
        "/api/admin/login-failures",
        "/api/admin/password/reset-request",
        "/api/admin/password/reset-confirm",
        "/api/admin/password/change",
        "/api/admin/activity/risky-today",
        "/api/admin/jobs/{job_id}/retry",
        "/api/admin/jobs/{job_id}/rollback",
        "/api/admin/pipeline/changes",
        "/api/admin/pipeline/changes/recheck",
        "/api/admin/pipeline/estimate",
    ):
        assert path in paths, f"{path} 가 앱에 안 붙었다"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
