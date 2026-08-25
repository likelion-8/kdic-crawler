"""관리자 활동 로그 조회(AD-011) 계약 테스트.

DB·네트워크 없이 돈다. 검사 대상은 세 가지다.

    1) 목록과 total 이 같은 조건을 쓰는가      — 어긋나면 '3건인데 5페이지'가 된다
    2) KST 변환이 양쪽 끝에서 맞는가          — 틀리면 새벽 기록이 전날로 밀린다
    3) action 어휘가 화면 링크 규칙에 걸리는가 — 틀리면 [연결 보기]가 엉뚱한 화면으로 간다
"""
import csv
import io
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Request
from sqlalchemy.dialects import postgresql

# `python tests/test_admin_activity.py` 로도 실행되도록 저장소 루트를 먼저 넣는다.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.deps import ACTION_BY_JOB_TYPE, RESULT_DENIED, RESULT_SUCCESS
from api.errors import BadRequestError
from api.routers import admin_activity, admin_change_requests
from api.routers.admin_activity import (ACTION_ACTIVITY_EXPORT,
                                        ACTIVITY_CSV_HEADER,
                                        build_activity_event_queries,
                                        build_snapshot, export_activity_events,
                                        parse_snapshot_value, router,
                                        _to_kst_iso)
from api.routers.admin_change_requests import (
    CHANGE_REQUEST_AUDIT_ACTIONS, approve_change_request,
    reject_change_request)
from api.routers.admin_pipeline import JOB_TYPES
from api.schemas.activity import ActivityExportRequest
from api.schemas.change_request import ChangeRequestDecision

# EventDetail.tsx 의 LINKS·NO_LINK 를 그대로 옮긴 것. 화면이 action 문자열을 이 규칙으로
# 갈라 '연결 보기' 이동처를 정하므로, 서버가 만드는 어휘가 여기에 걸려야 한다.
PIPELINE_LINK = r"전체 재수집|선택 재수집|재색인|재적재|파이프라인|작업"
URL_LINK = r"URL 적재"
PAGE_LINK = r"페이지|재수집"
NO_LINK = r"^로그인|^로그아웃|로그인 실패|임시 잠금|^로그 조회|^로그 내보내기|^활동 로그"


def _compiled(**kwargs):
    defaults = dict(q="", action="", actor="", result="", from_date=None, sort="occurred_at:desc")
    defaults.update(kwargs)
    rows, total = build_activity_event_queries(**defaults)
    dialect = postgresql.dialect()
    return rows.compile(dialect=dialect), total.compile(dialect=dialect)


# ------------------------------------------------- 1) 목록과 total 이 같은 조건
def test_filters_apply_to_both_the_list_and_the_count():
    rows, total = _compiled(actor="admin@demo", result="실패")
    for sql in (str(rows), str(total)):
        assert "admin_activity_logs.actor =" in sql
        assert "admin_activity_logs.result =" in sql


def test_keyword_searches_action_and_target_only():
    rows, total = _compiled(q="재색인")
    rows_sql = str(rows)
    assert "admin_activity_logs.action ILIKE" in rows_sql
    assert "admin_activity_logs.target ILIKE" in rows_sql
    # 실행자까지 넓히면 검색칸과 실행자 필터의 결과가 겹쳐 무엇이 걸렸는지 알 수 없다.
    assert "admin_activity_logs.actor ILIKE" not in rows_sql
    assert "admin_activity_logs.action ILIKE" in str(total)


def test_keyword_wildcards_are_treated_as_plain_characters():
    rows, _ = _compiled(q="로그_100%")
    assert "%로그\\_100\\%%" in rows.params.values()


def test_period_filter_is_applied_as_a_lower_bound():
    rows, total = _compiled(from_date="2026-08-04")
    assert "admin_activity_logs.occurred_at >=" in str(rows)
    assert "admin_activity_logs.occurred_at >=" in str(total)


def test_bad_period_and_sort_are_rejected_with_400():
    with pytest.raises(BadRequestError):
        _compiled(from_date="2026/08/04")
    # POST /exports 의 filter 는 JSON 이라 문자열이 아닌 값이 올 수 있다. 그때 500 이 아니라
    # 400 이어야 한다 — 500 이면 화면이 '일시적인 오류' 로 떠서 입력 문제인 줄 모른다.
    with pytest.raises(BadRequestError):
        _compiled(from_date=["2026-08-04"])
    with pytest.raises(BadRequestError):
        _compiled(from_date={"from": "2026-08-04"})
    with pytest.raises(BadRequestError):
        _compiled(from_date=20261340)  # 13월 40일


def test_a_numeric_date_is_read_rather_than_rejected():
    # date.fromisoformat 은 3.11 부터 'YYYYMMDD' 압축 형식도 받는다. 그래서 JSON 숫자
    # 20260804 는 400 이 아니라 2026-08-04 로 읽힌다. 느슨하지만 틀린 값을 통과시키는
    # 것은 아니라 그대로 둔다 — 여기서 막아야 할 것은 500 이지 관대함이 아니다.
    rows, _ = _compiled(from_date=20260804)
    assert "admin_activity_logs.occurred_at >=" in str(rows)
    with pytest.raises(BadRequestError):
        _compiled(sort="occurred_at:down")
    # 인덱스 없는 컬럼으로 정렬을 열어 주면 풀스캔이 걸린다.
    with pytest.raises(BadRequestError):
        _compiled(sort="ip:desc")


def test_default_sort_is_newest_first():
    rows, _ = _compiled()
    assert "ORDER BY admin_activity_logs.occurred_at DESC" in str(rows)


# ------------------------------------------------------------- 2) KST 변환
def test_occurred_at_goes_out_as_kst():
    # 화면의 formatKst 는 받은 문자열을 그대로 지역 시각처럼 읽는다. UTC 로 주면
    # 이 기록이 08-11 이 아니라 08-10 로 보인다.
    utc = datetime(2026, 8, 11, 1, 30, tzinfo=timezone.utc)
    assert _to_kst_iso(utc) == "2026-08-11T10:30:00+09:00"


def test_naive_timestamps_are_read_as_utc():
    # 드라이버·컬럼 설정에 따라 tz 없는 값이 올라오는 경우가 있다. 그때 지역시로 읽으면
    # 9시간이 더 밀린다.
    naive = datetime(2026, 8, 11, 1, 30)
    assert _to_kst_iso(naive) == "2026-08-11T10:30:00+09:00"


def test_missing_timestamp_stays_none():
    assert _to_kst_iso(None) is None


# --------------------------------------------------------------- 스냅샷
def test_snapshot_is_omitted_when_there_is_nothing_to_show():
    # 로그인 기록에는 전후값이 없다. 빈 dict 를 실어 보내면 상세 패널에 '변경 내용' 블록이
    # 빈 채로 뜬다 — 화면은 데이터가 있는 블록만 렌더하기로 돼 있다.
    assert build_snapshot(None, None) is None
    assert build_snapshot("", "") is None


def test_snapshot_parses_json_and_keeps_plain_text_usable():
    snapshot = build_snapshot('{"list_state": "최신"}', '{"list_state": "적용 대기"}')
    assert snapshot.before == {"list_state": "최신"}
    assert snapshot.after == {"list_state": "적용 대기"}

    # 자유 텍스트 컬럼이라 JSON 이 아닐 수 있다. 통째로 버리는 것보다 감싸서 보여 준다.
    assert parse_snapshot_value("그냥 문자열") == {"value": "그냥 문자열"}
    assert parse_snapshot_value("[1, 2]") == {"value": [1, 2]}


def test_snapshot_survives_a_one_sided_change():
    snapshot = build_snapshot(None, '{"status": "QUEUED"}')
    assert snapshot.before == {}
    assert snapshot.after == {"status": "QUEUED"}


# --------------------------------------------------- 3) action 어휘와 화면 링크
def test_every_job_type_has_an_action_word():
    # 어휘가 빠진 잡 종류는 action 에 영문 코드가 그대로 찍혀 화면에서 링크가 안 붙는다.
    assert set(ACTION_BY_JOB_TYPE) == set(JOB_TYPES)


def test_job_actions_route_to_the_pipeline_screen():
    import re
    for job_type, action in ACTION_BY_JOB_TYPE.items():
        assert not re.search(NO_LINK, action), f"{job_type} 이 '연결 없음'으로 분류된다"
        # LINKS 는 위에서부터 처음 맞는 것 하나를 쓴다. URL 규칙이 먼저라 거기 걸리면 안 된다.
        assert not re.search(URL_LINK, action), f"{job_type} 이 AD-003 으로 잘못 간다"
        assert re.search(PIPELINE_LINK, action), f"{job_type} 이 파이프라인 화면으로 못 간다"


def test_login_actions_stay_unlinked():
    import re
    from api.deps import ACTION_LOGIN, ACTION_LOGIN_FAILED, ACTION_LOGOUT
    for action in (ACTION_LOGIN, ACTION_LOGIN_FAILED, ACTION_LOGOUT):
        assert re.search(NO_LINK, action)


def test_change_request_actions_route_to_the_expected_screen():
    """EventDetail.tsx 의 첫 일치 규칙 기준으로 ADD 는 AD-003, DELETE 는 AD-002다."""
    import re

    assert CHANGE_REQUEST_AUDIT_ACTIONS == {
        ("ADD", "APPROVED"): "URL 적재 승인",
        ("ADD", "REJECTED"): "URL 적재 반려",
        ("DELETE", "APPROVED"): "페이지 삭제 승인",
        ("DELETE", "REJECTED"): "페이지 삭제 반려",
    }
    for (request_action, _), audit_action in CHANGE_REQUEST_AUDIT_ACTIONS.items():
        assert not re.search(NO_LINK, audit_action)
        if request_action == "ADD":
            assert re.search(URL_LINK, audit_action), f"{audit_action} 이 AD-003으로 못 간다"
        else:
            assert not re.search(URL_LINK, audit_action), f"{audit_action} 이 AD-003으로 잘못 간다"
            assert re.search(PAGE_LINK, audit_action), f"{audit_action} 이 AD-002로 못 간다"


class _FirstResult:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class _DecisionDb:
    def __init__(self, row):
        self.results = [_FirstResult(row), _FirstResult(row)]
        self.commits = 0

    def execute(self, _statement):
        return self.results.pop(0)

    def commit(self):
        self.commits += 1

    def rollback(self):
        raise AssertionError("성공한 결정에서 rollback 되면 안 된다")


def _decision_row(*, action: str, status: str):
    decided_at = datetime(2026, 8, 12, tzinfo=timezone.utc)
    return SimpleNamespace(
        id="44444444-4444-4444-4444-444444444444",
        action=action,
        target_page_id="test_page_001",
        target_title="테스트 페이지",
        business_function="테스트",
        payload=None,
        reason="테스트 요청 사유",
        requested_by="test_editor@example.com",
        requested_at=decided_at,
        status=status,
        decided_by="test_admin@example.com",
        decided_at=decided_at,
        decision_reason="테스트 결정 사유",
        request_id="test_req_change_request",
    )


@pytest.mark.parametrize(
    ("handler", "request_action", "status", "expected_action", "expected_result", "expected_reason"),
    [
        (approve_change_request, "ADD", "APPROVED", "URL 적재 승인", RESULT_SUCCESS, None),
        (reject_change_request, "ADD", "REJECTED", "URL 적재 반려", RESULT_DENIED, "테스트 반려 사유"),
        (approve_change_request, "DELETE", "APPROVED", "페이지 삭제 승인", RESULT_SUCCESS, None),
        (reject_change_request, "DELETE", "REJECTED", "페이지 삭제 반려", RESULT_DENIED, "테스트 반려 사유"),
    ],
)
def test_change_request_decision_writes_audit_log_after_commit(
        monkeypatch, handler, request_action, status, expected_action,
        expected_result, expected_reason):
    row = _decision_row(action=request_action, status=status)
    db = _DecisionDb(row)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    me = SimpleNamespace(email="test_admin@example.com", role="ADMIN")
    captured = {}

    def capture_log(log_db, log_request, **values):
        # write_activity_log 는 스스로 commit 한다. 호출 시점에 상태 전이가 이미 확정돼야 한다.
        assert log_db is db
        assert log_request is request
        assert db.commits == 1
        captured.update(values)

    monkeypatch.setattr(admin_change_requests, "write_activity_log", capture_log)

    response = handler(
        str(row.id), ChangeRequestDecision(reason="테스트 반려 사유"),
        request, db, me,
    )

    assert response.status == status
    assert captured == {
        "actor": "test_admin@example.com",
        "actor_role": "ADMIN",
        "action": expected_action,
        "target": "테스트 페이지 (test_page_001)",
        "result": expected_result,
        "reason": expected_reason,
        "detail": {"change_request_id": str(row.id)},
    }


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value


class _ExportRowsResult:
    """rows_query 결과 — _row_to_event 가 읽는 컬럼만 가진 행 2개."""

    def all(self):
        return [
            SimpleNamespace(id="11111111-1111-1111-1111-111111111111",
                            occurred_at=datetime(2026, 8, 1, 0, 30, tzinfo=timezone.utc),
                            actor="admin@demo", actor_role="ADMIN", action="로그인",
                            target="관리자 콘솔", result="성공", reason=None,
                            request_id="req-1", ip="10.0.0.1"),
            SimpleNamespace(id="22222222-2222-2222-2222-222222222222",
                            occurred_at=datetime(2026, 8, 1, 1, 0, tzinfo=timezone.utc),
                            actor="ops@demo", actor_role="OPERATOR", action="재적재 실행",
                            # 따옴표·줄바꿈이 들어간 값이 CSV 를 깨지 않는지 함께 본다
                            target='재적재 "전체"\n대상', result="성공", reason="정기 점검",
                            request_id="req-2", ip="10.0.0.2"),
        ]


class _ExportDb:
    """첫 execute 는 total(count), 두 번째는 행 목록 — 라우터가 부르는 순서 그대로다."""

    def __init__(self):
        self.calls = 0

    def execute(self, _statement):
        self.calls += 1
        return _ScalarResult(2) if self.calls == 1 else _ExportRowsResult()


def test_activity_export_writes_an_audit_log(monkeypatch):
    db = _ExportDb()
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    admin = SimpleNamespace(email="test_admin@example.com", role="ADMIN")
    body = ActivityExportRequest(
        request_id="test_req_activity_export",
        reason="테스트 감사 자료 확인",
        filter={"action": "로그인", "from": "2026-08-01"},
    )
    captured = {}

    def capture_log(log_db, log_request, **values):
        assert log_db is db
        assert log_request is request
        captured.update(values)

    monkeypatch.setattr(admin_activity, "write_activity_log", capture_log)

    response = export_activity_events(body, request, admin, db)

    # 접수증이 아니라 CSV 파일을 돌려준다(2026-08-25 QA — 종전에는 QUEUED 만 주고 파일이 없었다)
    assert response.headers["content-type"].startswith("text/csv")
    export_id = response.headers["x-export-id"]
    assert response.headers["content-disposition"] == f'attachment; filename="activity-log-{export_id}.csv"'
    assert response.headers["x-export-rows"] == "2"

    csv_text = response.body.decode("utf-8")
    assert csv_text.startswith("\ufeff"), "엑셀이 UTF-8 로 읽게 하는 BOM"
    parsed = list(csv.reader(io.StringIO(csv_text[1:])))
    assert parsed[0] == list(ACTIVITY_CSV_HEADER)
    assert len(parsed) == 3, "머리글 1 + 데이터 2"
    assert parsed[1][1] == "admin@demo"
    # 시각은 목록과 같은 KST ISO 다 — UTC 로 나가면 표를 여는 사람이 9시간 어긋나게 읽는다
    assert parsed[1][0] == "2026-08-01T09:30:00+09:00"
    # 따옴표·줄바꿈이 든 값도 한 칸으로 살아 있어야 한다
    assert parsed[2][4] == '재적재 "전체"\n대상'

    assert captured == {
        "actor": "test_admin@example.com",
        "actor_role": "ADMIN",
        "action": ACTION_ACTIVITY_EXPORT,
        # CM-DF-002 07절: 대상은 '이름 + (ID)' — ID 단독 노출 금지(2026-08-13 정합)
        "target": f"활동 로그 · 현재 필터 ({export_id})",
        "result": RESULT_SUCCESS,
        "reason": "테스트 감사 자료 확인",
        "detail": {
            "export_id": export_id,
            "rows": 2,
            "filter": {"action": "로그인", "from": "2026-08-01"},
            "export_request_id": "test_req_activity_export",
        },
    }
    assert ACTION_ACTIVITY_EXPORT == "활동 로그 내보내기"
    assert __import__("re").search(NO_LINK, ACTION_ACTIVITY_EXPORT)


def test_activity_routes_are_exposed():
    paths = {route.path for route in router.routes}
    assert paths == {
        "/api/admin/activity/overview",
        "/api/admin/activity/events",
        "/api/admin/activity/events/{event_id}",
        "/api/admin/activity/exports",
        # AD-010 '오늘의 위험 작업'. 접근 관리 화면이 쓰지만 prefix 가 여기라 이 라우터에 산다
        # (id 가 AD-011 event_id 와 같은 값이어야 딥링크가 해석된다 — L7).
        "/api/admin/activity/risky-today",
    }


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
