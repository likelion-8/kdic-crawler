"""세션별 30분 한도(AD-009 session_per_30min)와 429 문구(over_limit_message).

2026-08-25 QA: 두 값 다 화면에서 저장·표시되지만 읽는 코드가 없었다. session_per_30min 은
미들웨어가 세션 id 를 모르고(요청 본문에 있다), over_limit_message 는 429 문구가 코드에
박혀 있어 관리자가 고쳐도 사용자는 옛 문구를 봤다.

DB 없이 돈다 — get_policy 를 갈아 끼워 정책만 흉내 낸다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import ops_policy  # noqa: E402
from api.errors import RateLimitError  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_counters():
    ops_policy._SESSION_HITS.clear()
    ops_policy.reset_cache()
    yield
    ops_policy._SESSION_HITS.clear()
    ops_policy.reset_cache()


def _policy(monkeypatch, **over):
    value = {**ops_policy.DEFAULTS, **over}
    monkeypatch.setattr(ops_policy, "get_policy", lambda now=None: value)
    return value


def test_blocks_after_the_limit(monkeypatch):
    _policy(monkeypatch, session_per_30min=3, over_limit_message="지금은 잠깐 대기 중이에요")

    for i in range(3):
        ops_policy.check_session_quota("sess-a", now=float(i))
    with pytest.raises(RateLimitError) as caught:
        ops_policy.check_session_quota("sess-a", now=3.0)

    assert caught.value.status_code == 429
    # 문구는 관리자가 AD-009 에서 편집한 값이어야 한다
    assert caught.value.user_message == "지금은 잠깐 대기 중이에요"
    assert caught.value.retryable is False, "429 는 자동 재호출 금지(PRD-02 §3-b)"


def test_sessions_are_counted_separately(monkeypatch):
    _policy(monkeypatch, session_per_30min=1)
    ops_policy.check_session_quota("sess-a", now=0.0)
    ops_policy.check_session_quota("sess-b", now=0.0)   # 다른 세션은 영향 없다
    with pytest.raises(RateLimitError):
        ops_policy.check_session_quota("sess-a", now=0.0)


def test_window_slides(monkeypatch):
    _policy(monkeypatch, session_per_30min=1)
    ops_policy.check_session_quota("sess-a", now=0.0)
    with pytest.raises(RateLimitError):
        ops_policy.check_session_quota("sess-a", now=ops_policy.SESSION_WINDOW_S - 1)
    # 30분이 지나면 창 밖으로 밀려나 다시 통과한다
    ops_policy.check_session_quota("sess-a", now=ops_policy.SESSION_WINDOW_S + 1)


def test_rejected_requests_are_not_counted(monkeypatch):
    """거절을 세면 계속 두드리는 쪽이 영원히 안 풀린다(미들웨어와 같은 규칙)."""
    _policy(monkeypatch, session_per_30min=1)
    ops_policy.check_session_quota("sess-a", now=0.0)
    for _ in range(5):
        with pytest.raises(RateLimitError):
            ops_policy.check_session_quota("sess-a", now=10.0)
    assert len(ops_policy._SESSION_HITS["sess-a"]) == 1


def test_zero_means_no_limit(monkeypatch):
    _policy(monkeypatch, session_per_30min=0)
    for i in range(50):
        ops_policy.check_session_quota("sess-a", now=float(i))


def test_defaults_match_the_admin_screen():
    """기본값 정본은 admin_ops.DEFAULT_POLICY 다. 갈리면 DB 가 비었을 때 화면과 집행이 어긋난다."""
    from api.routers.admin_ops import DEFAULT_POLICY
    for key, value in ops_policy.DEFAULTS.items():
        assert DEFAULT_POLICY[key] == value, key
