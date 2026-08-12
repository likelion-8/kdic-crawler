"""관리자 대화 로그(AD-005) 통합 테스트.

세 가지를 본다.

    1) 권한 경계 — 목록·상세는 VIEWER 에게 403, 요약은 200. 이 경계가 갈리는 게 핵심이다
    2) KST · 기간 검증 — 날짜 경계가 어긋나면 '오늘'이 9시간 밀린다
    3) 실패·범위외 건이 실제로 집계에 잡히는가 — 실패 기록 작업(rag_logger/sse)의 검증

1·2 는 DB 없이 돈다(가짜 세션·SQL 컴파일 비교 — 기존 테스트 파일들과 같은 방식).
3 은 실 DB 가 필요해서 conftest.py 의 db_session/test_prefix/db_cleanup 을 쓴다.
DATABASE_URL 이 없으면 실패가 아니라 skip 이다.
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.deps import get_current_admin, get_db
from api.errors import BadRequestError
from api.main import create_app
from api.routers.admin_logs import (_kst_day_start, _status_out, _to_kst_iso,
                                    build_log_queries)


# ---------------------------------------------------------------- 가짜 DB · 관리자

class _Result:
    """db.execute(...) 의 반환 흉내. 라우터가 쓰는 세 가지만 있으면 된다."""

    def __init__(self, *, rows=None, scalar=0):
        self._rows = rows or []
        self._scalar = scalar

    def scalar_one(self):
        return self._scalar

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDb:
    """execute() 가 미리 넣어 둔 결과를 순서대로 돌려준다. 결과가 모자라면 빈 것을 준다 —
    권한 테스트는 쿼리까지 못 가고 403 으로 끝나므로 개수를 정확히 맞출 필요가 없다."""

    def __init__(self, *results):
        self.results = list(results)
        self.executed = 0

    def execute(self, _statement):
        self.executed += 1
        return self.results.pop(0) if self.results else _Result()

    def commit(self):
        pass

    def rollback(self):
        pass


def _admin(role: str):
    return lambda: SimpleNamespace(role=role, email=f"{role.lower()}@demo", name=role)


def _client(role: str, db=None):
    app = create_app()
    app.dependency_overrides[get_current_admin] = _admin(role)
    app.dependency_overrides[get_db] = lambda: db or _FakeDb()
    return TestClient(app)


# ------------------------------------------------------- 1) 권한 경계 (G2)
#
# '집계만 보는 VIEWER' 는 화면 숨김이 아니라 서버 계약이다. 목록·상세가 열리면 사용자가
# 실제로 입력한 문장이 그대로 새어 나간다.

@pytest.mark.parametrize("path", ["/api/admin/logs", "/api/admin/logs/req_1"])
def test_viewer_cannot_read_conversations(path):
    with _client("VIEWER") as client:
        assert client.get(path).status_code == 403


@pytest.mark.parametrize("role", ["OPERATOR", "EDITOR", "ADMIN"])
def test_operator_and_above_can_read_the_list(role):
    with _client(role, _FakeDb(_Result(scalar=0), _Result(rows=[]))) as client:
        response = client.get("/api/admin/logs")
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "size": 20}


def test_viewer_can_read_the_summary():
    """요약만 VIEWER 에게 열려 있다 — 숫자에는 대화 내용이 없다."""
    with _client("VIEWER", _FakeDb(_Result(rows=[]), _Result(rows=[]))) as client:
        response = client.get("/api/admin/logs/summary")
    assert response.status_code == 200
    assert response.json() == {
        "total": 0, "normal": 0, "out_of_scope": 0, "failed": 0,
        "feedback_up": 0, "feedback_down": 0,
    }


def test_export_is_admin_only():
    body = {"request_id": str(uuid.uuid4()), "from": "", "to": ""}
    for role in ("VIEWER", "OPERATOR", "EDITOR"):
        with _client(role) as client:
            assert client.post("/api/admin/logs/exports", json=body).status_code == 403
    with _client("ADMIN", _FakeDb(_Result(scalar=7))) as client:
        response = client.post("/api/admin/logs/exports", json=body)
    assert response.status_code == 200
    assert response.json()["estimated_rows"] == 7


def test_summary_is_declared_before_the_detail_route():
    """/summary 가 /{request_id} 뒤에 있으면 'summary' 가 request_id 로 잡혀 404 가 된다."""
    paths = list(create_app().openapi()["paths"])
    assert "/api/admin/logs" in paths
    assert paths.index("/api/admin/logs/summary") < paths.index("/api/admin/logs/{request_id}")


# ------------------------------------------------------- 2) KST · 기간 검증

def test_created_at_goes_out_as_kst():
    # 화면은 받은 문자열을 그대로 지역 시각처럼 읽는다. UTC 로 주면 이 기록이 08-11 이 아니라
    # 08-10 로 보인다.
    utc = datetime(2026, 8, 11, 1, 30, tzinfo=timezone.utc)
    assert _to_kst_iso(utc) == "2026-08-11T10:30:00+09:00"


def test_naive_timestamps_are_read_as_utc():
    assert _to_kst_iso(datetime(2026, 8, 11, 1, 30)) == "2026-08-11T10:30:00+09:00"
    assert _to_kst_iso(None) is None


def test_midnight_boundary_belongs_to_the_new_kst_day():
    """KST 자정 직전·직후가 다른 날로 갈리는지. UTC 로 15:00 이 KST 자정이다."""
    before = datetime(2026, 8, 11, 14, 59, 59, tzinfo=timezone.utc)   # KST 08-11 23:59:59
    after = datetime(2026, 8, 11, 15, 0, 0, tzinfo=timezone.utc)      # KST 08-12 00:00:00
    assert _to_kst_iso(before).startswith("2026-08-11")
    assert _to_kst_iso(after).startswith("2026-08-12")
    # 그 경계가 곧 _kst_day_start 가 만드는 하한이다.
    assert _kst_day_start(after.astimezone(timezone.utc).date()) is not None
    assert _to_kst_iso(after) == "2026-08-12T00:00:00+09:00"


def _compiled(**kwargs):
    defaults = dict(q="", status="", intent="", feedback="",
                    from_raw=None, to_raw=None, sort="occurred_at:desc")
    defaults.update(kwargs)
    rows, total = build_log_queries(**defaults)
    dialect = postgresql.dialect()
    return rows.compile(dialect=dialect), total.compile(dialect=dialect)


def test_the_to_date_includes_the_whole_day():
    """to 를 그 날 00:00 으로 비교하면 '오늘'을 골랐을 때 오늘 것이 한 건도 안 나온다."""
    rows, total = _compiled(from_raw="2026-08-12", to_raw="2026-08-12")
    for sql in (str(rows), str(total)):
        assert "rag_runs.created_at >=" in sql
        assert "rag_runs.created_at <" in sql


def test_filters_apply_to_both_the_list_and_the_count():
    rows, total = _compiled(status="FAILED", intent="informational")
    for sql in (str(rows), str(total)):
        assert "rag_runs.status IN" in sql
        assert "rag_runs.intent =" in sql


def test_a_bad_period_is_rejected_rather_than_trimmed():
    # 90일치만 조용히 돌려주면 화면은 '전체를 봤다'고 착각한다.
    with pytest.raises(BadRequestError, match="최대"):
        _compiled(from_raw="2026-01-01", to_raw="2026-08-12")
    with pytest.raises(BadRequestError, match="늦"):
        _compiled(from_raw="2026-08-12", to_raw="2026-08-01")
    with pytest.raises(BadRequestError, match="기간 형식"):
        _compiled(from_raw="2026/08/12")


def test_exactly_ninety_days_is_allowed():
    """양끝 포함 90일은 통과해야 한다 — 화면 daysBetween 과 같은 셈이다."""
    rows, _ = _compiled(from_raw="2026-05-15", to_raw="2026-08-12")
    assert "rag_runs.created_at >=" in str(rows)


def test_unknown_filter_values_are_rejected():
    # 새 어휘를 조용히 통과시키면 필터가 안 걸린 채 전건이 나온다.
    for kwargs in ({"status": "success"}, {"intent": "smalltalk"}, {"feedback": "maybe"}):
        with pytest.raises(BadRequestError):
            _compiled(**kwargs)


def test_legacy_status_is_mapped_on_read():
    """2026-08-12 이전 행은 전부 "success" 다. 화면 어휘로 옮겨야 상태 칩이 뜬다."""
    assert _status_out("success") == "NORMAL"
    assert _status_out("FAILED") == "FAILED"
    assert _status_out("OUT_OF_SCOPE") == "OUT_OF_SCOPE"


def test_choosing_normal_also_finds_legacy_rows():
    """'정상'을 골랐을 때 옛 "success" 행도 같이 걸려야 한다 — 안 그러면 기존 기록이 통째로
    사라진다. IN 절이라 파라미터 값이 리스트로 들어간다(POSTCOMPILE)."""
    rows, _ = _compiled(status="NORMAL")
    in_values = [v for v in rows.params.values() if isinstance(v, list)]
    assert in_values and "success" in in_values[0]
    assert "NORMAL" in in_values[0]


# ------------------------------- 3) 실패·범위외가 집계에 잡히는가 (실 DB)
#
# 실패 기록 작업(src/rag_logger.py · api/rag/sse.py)의 검증이다. 그 작업 전에는 실패한
# 질의가 rag_runs 에 행 자체가 없어서 아래 failed 는 무엇을 넣든 0 이었다.

def _insert_run(db, prefix, *, status, request_id_suffix, intent="informational",
                failure_stage=None, root_cause=None):
    """행을 직접 넣는다. rag_logger.log_rag_run 을 쓰지 않는 이유는 그 함수가 모든 예외를
    삼켜서(실패-안전) 삽입이 실패해도 테스트가 조용히 통과해 버리기 때문이다."""
    from schema import rag_runs
    db.execute(rag_runs.insert(), {
        "question": f"{prefix}질문",
        "answer": "본문",
        "intent": intent,
        "status": status,
        "failure_stage": failure_stage,
        "root_cause": root_cause,
        "total_latency_ms": 1234,
        "request_id": f"{prefix}{request_id_suffix}",
        "session_id": f"{prefix}sess",
    })


@pytest.mark.parametrize("status", ["NORMAL", "OUT_OF_SCOPE", "FAILED"])
def test_each_status_lands_in_its_own_summary_bucket(db_session, test_prefix, db_cleanup, status):
    """세 상태가 각자의 칸에 들어가는지. 어휘가 어긋나면 어느 칸에도 안 들어간다."""
    from schema import rag_runs
    db_cleanup(rag_runs, rag_runs.c.request_id)

    before = _summary(db_session)
    _insert_run(db_session, test_prefix, status=status, request_id_suffix="r1")
    db_session.commit()
    after = _summary(db_session)

    bucket = {"NORMAL": "normal", "OUT_OF_SCOPE": "out_of_scope", "FAILED": "failed"}[status]
    assert after[bucket] == before[bucket] + 1, f"{status} 가 {bucket} 집계에 안 잡힌다"
    assert after["total"] == before["total"] + 1


def test_the_list_renders_a_real_row_end_to_end(db_session, test_prefix, db_cleanup):
    """넣은 행이 목록에 그대로 나오는지 — 조인·KST·필드 매핑을 실 DB 로 한 번에 본다.

    가짜 세션으로는 못 보는 것들이 여기서 걸린다: feedback LEFT JOIN 이 피드백 없는 행을
    떨어뜨리지 않는지, created_at 이 +09:00 으로 나가는지, total_latency_ms 가 초로 바뀌는지.
    """
    from schema import rag_runs
    db_cleanup(rag_runs, rag_runs.c.request_id)

    _insert_run(db_session, test_prefix, status="OUT_OF_SCOPE", request_id_suffix="oos")
    db_session.commit()

    with _client("OPERATOR", db_session) as client:
        response = client.get(f"/api/admin/logs?q={test_prefix}")
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    row = body["items"][0]
    assert row["request_id"] == f"{test_prefix}oos"
    assert row["status"] == "OUT_OF_SCOPE"
    assert row["question_masked"] == f"{test_prefix}질문"
    assert row["latency_s"] == 1.23                  # total_latency_ms 1234 -> 초(소수 2자리)
    assert row["feedback"] is None                   # 피드백 없는 행도 목록에 남는다
    assert row["occurred_at"].endswith("+09:00")     # UTC 로 나가면 화면의 '오늘'이 밀린다
    # 원천이 없는 두 필드는 지어내지 않는다(0 을 넣으면 '출처가 없었다'는 사실처럼 읽힌다).
    assert row["source_count"] is None
    assert row["triage"] == "NONE"


def test_a_failed_run_keeps_its_stage_and_cause_in_the_detail(db_session, test_prefix, db_cleanup):
    """실패 건 상세가 failure_stage/root_cause 를 그대로 보여주는지 — 이 두 값이 없으면
    운영자는 '실패했다'는 사실만 알고 왜인지는 모른다."""
    from schema import rag_runs
    db_cleanup(rag_runs, rag_runs.c.request_id)

    _insert_run(db_session, test_prefix, status="FAILED", request_id_suffix="fail",
                failure_stage="llm", root_cause="TimeoutError: 30초 동안 토큰 없음")
    db_session.commit()

    with _client("OPERATOR", db_session) as client:
        response = client.get(f"/api/admin/logs/{test_prefix}fail")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FAILED"
    assert body["error"]["failure_stage"] == "llm"
    assert body["error"]["root_cause"].startswith("TimeoutError")


@pytest.mark.xfail(
    reason="api/schemas/logs.py 의 ConversationLogRow.intent 가 non-Optional 이라 "
           "intent=NULL 행에서 ResponseValidationError(500) 가 난다. 같은 파일이 "
           "question_type 을 Optional 로 연 것과 같은 처리가 intent 에도 필요하다 — "
           "스키마는 2번 담당이라 여기서 고치지 않고 재현만 남긴다.",
    strict=False, raises=Exception)
def test_a_failed_run_without_an_intent_still_renders(db_session, test_prefix, db_cleanup):
    """플래너 자체가 죽은 실패(sse.py 의 첫 번째 에러 경로)는 intent 를 모른다.

    그 행은 intent 가 NULL 로 남는데, 목록이 그걸 못 그리면 실패 한 건이 화면 전체를
    500 으로 만든다 — 실패를 기록한 대가로 목록을 잃는 셈이 된다.

    지어낸 intent 를 넣어 피하지 않는다. 그건 logs/api.ts:39-49 가 경고한 바로 그 사고다
    (원천 없는 값을 그럴듯하게 채워 화면이 거짓을 말하게 하는 것).
    """
    from schema import rag_runs
    db_cleanup(rag_runs, rag_runs.c.request_id)

    _insert_run(db_session, test_prefix, status="FAILED", request_id_suffix="noplan",
                intent=None, failure_stage="retrieval", root_cause="RuntimeError: planner down")
    db_session.commit()

    with _client("OPERATOR", db_session) as client:
        response = client.get(f"/api/admin/logs?q={test_prefix}")
    assert response.status_code == 200, response.text
    assert response.json()["total"] >= 1


def _summary(db):
    """라우터의 집계 함수를 그대로 부른다 — HTTP 를 태우지 않고 숫자만 본다."""
    from api.routers.admin_logs import logs_summary
    return logs_summary(SimpleNamespace(role="ADMIN", email="t@demo", name="t"), db)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
