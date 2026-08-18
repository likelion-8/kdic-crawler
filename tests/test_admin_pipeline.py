"""관리자 파이프라인 잡 API(AD-004) 계약 테스트 — DB·자격증명 없이 도는 부분만 자동 검증.

기존 test_admin_knowledge.py 와 같은 방식이다: 실제 Supabase 접속 없이 순수 로직(스텝 초기화·
정렬·행 매핑)·SQL 컴파일·라우팅·계약 상수를 검사한다. HTTP 레벨(401/202/409/404)은 서버를
띄워 수동으로 확인한다(작업 지시서 검증 3항) — 로그인 세션이 필요하기 때문이다.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

# `python tests/test_admin_pipeline.py`로도 실행되도록 저장소 루트를 먼저 넣는다.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.errors import ApiError, BadRequestError
from api.deps import get_current_admin, get_db
from api.routers import admin_pipeline
from api.routers.admin_pipeline import (
    PIPELINE_STEPS,
    JobCancelConflictError,
    JobConflictError,
    _initial_steps,
    _order_by,
    _row_to_job,
    router,
)
from api.schemas.pipeline import JobCreate, PipelineJob


def test_initial_steps_are_all_queued():
    """생성 시 6단계를 전부 QUEUED 로 초기화해야 진행바가 빈 채로 안 뜬다."""
    steps = _initial_steps()
    assert [s["name"] for s in steps] == list(PIPELINE_STEPS)
    assert len(steps) == len(PIPELINE_STEPS)
    assert all(s["status"] == "QUEUED" for s in steps)


def test_default_sort_is_created_at_desc():
    """목록 기본 정렬은 created_at 내림차순(진행 중 잡이 1페이지 맨 위라는 프론트 가정)."""
    sql = str(_order_by("created_at:desc").compile(dialect=postgresql.dialect()))
    assert "created_at DESC" in sql


def test_invalid_sort_is_rejected():
    for bad in ["", "created_at", "created_at:sideways", "unknown:desc"]:
        try:
            _order_by(bad)
        except BadRequestError:
            continue
        raise AssertionError(f"{bad!r} 는 BadRequestError 를 내야 한다")


def test_conflict_error_is_409_and_not_retryable():
    """동시 실행 초과는 409 + retryable=false. true 면 프론트가 [다시 시도]로 계속 409 를 맞는다."""
    err = JobConflictError()
    assert isinstance(err, ApiError)
    assert err.status_code == 409
    assert err.retryable is False


def test_cancel_conflict_error_is_409():
    err = JobCancelConflictError()
    assert err.status_code == 409
    assert err.retryable is False


def test_row_to_job_maps_all_fields():
    row = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        type="REINDEX",
        status="QUEUED",
        targets=["p1", "p2"],
        reason="갱신",
        created_by="admin@demo",
        created_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        steps=_initial_steps(),
        error=None,
        rollback_of=None,
        target_summary=None,
        target_count=2,
        index_impact=None,
        metrics=None,
    )
    job = _row_to_job(row)
    assert isinstance(job, PipelineJob)
    assert job.id == "11111111-1111-1111-1111-111111111111"
    assert job.type == "REINDEX"
    assert job.targets == ["p1", "p2"]
    assert len(job.steps) == len(PIPELINE_STEPS) and job.steps[0].status == "QUEUED"


def test_row_to_job_handles_null_json_columns():
    """JSONB 컬럼이 NULL(targets/reason 미지정)이어도 빈 값으로 안전 변환된다."""
    row = SimpleNamespace(
        id="22222222-2222-2222-2222-222222222222",
        type="REINDEX", status="QUEUED",
        targets=None, reason=None, created_by="a@b",
        created_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        steps=[], error=None, rollback_of=None, target_summary=None,
        target_count=None, index_impact=None, metrics=None,
    )
    job = _row_to_job(row)
    assert job.targets == []
    assert job.reason == ""


def test_job_create_ignores_extra_fields():
    """쓰기 요청엔 멱등키 request_id 가 섞여 온다 — extra='forbid' 면 400 이 나므로 무시돼야 한다."""
    body = JobCreate.model_validate(
        {"type": "REINDEX", "targets": ["p1"], "reason": "x", "request_id": "req_1"})
    assert body.type == "REINDEX"
    assert body.targets == ["p1"]
    assert not hasattr(body, "request_id")


def test_create_endpoint_returns_202():
    route = next(
        r for r in router.routes
        if getattr(r, "path", "") == "/api/admin/jobs" and "POST" in getattr(r, "methods", set()))
    assert route.status_code == 202


def test_jobs_routes_are_exposed():
    paths = {r.path for r in router.routes if hasattr(r, "path")}
    assert "/api/admin/jobs" in paths
    assert "/api/admin/jobs/{job_id}" in paths
    assert "/api/admin/jobs/{job_id}/cancel" in paths


def test_cancel_endpoint_changes_queued_job_to_cancelled(monkeypatch):
    """프론트가 보내는 POST 본문으로 실제 라우팅되고 CANCELLED 응답을 돌려준다."""
    job_id = "33333333-3333-3333-3333-333333333333"
    row = SimpleNamespace(
        id=job_id, type="REINDEX", status="CANCELLED", targets=[], reason="실수",
        created_by="admin@demo", created_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        steps=_initial_steps(), error=None, rollback_of=None, target_summary=None,
        target_count=None, index_impact=None, metrics=None,
    )

    class Result:
        def __init__(self, value):
            self.value = value

        def first(self):
            return self.value

    class FakeDb:
        def __init__(self):
            self.results = [Result(SimpleNamespace(id=job_id)), Result(row)]
            self.commits = 0

        def execute(self, _statement):
            return self.results.pop(0)

        def commit(self):
            self.commits += 1

        def rollback(self):
            raise AssertionError("성공 취소에서 rollback 되면 안 된다")

    db = FakeDb()
    me = SimpleNamespace(email="admin@demo", role="ADMIN")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_admin] = lambda: me
    monkeypatch.setattr(admin_pipeline, "write_activity_log", lambda *args, **kwargs: None)

    response = TestClient(app).post(
        f"/api/admin/jobs/{job_id}/cancel",
        json={"reason": "실수", "request_id": "req-cancel"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert db.commits == 1


if __name__ == "__main__":
    test_initial_steps_are_all_queued()
    test_default_sort_is_created_at_desc()
    test_invalid_sort_is_rejected()
    test_conflict_error_is_409_and_not_retryable()
    test_cancel_conflict_error_is_409()
    test_row_to_job_maps_all_fields()
    test_row_to_job_handles_null_json_columns()
    test_job_create_ignores_extra_fields()
    test_create_endpoint_returns_202()
    test_jobs_routes_are_exposed()
    print("OK - 관리자 파이프라인 잡 API 계약")


def test_job_steps_match_the_worker_stage_list_exactly():
    """잡 생성 시 steps 는 워커의 STEPS 와 이름·순서가 같아야 한다 — 어긋나면 워커의
    _set_step 이 매칭할 항목이 없어 그 단계 기록이 조용히 사라진다(2026-08-18 실사고:
    API 가 옛 6단계를 따로 들고 있어 게이트 판정이 화면에 남지 않았다)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from worker import STEPS

    assert tuple(PIPELINE_STEPS) == tuple(STEPS)
    assert "게이트" in PIPELINE_STEPS


def test_job_step_detail_survives_the_response_model():
    """게이트 판정은 단계 detail 에 실려 온다 — response_model 이 잘라내면 화면에 '—'만
    남는다(2026-08-18 실사고). 워커가 남기는 모양 그대로 통과해야 한다."""
    from api.schemas.pipeline import JobStep

    verdict = {"passed": True, "metrics": {"recall@5": 0.94, "mrr": 0.80, "n": 79},
               "targets": {"recall@5": 0.92, "mrr": 0.80}, "failures": [],
               "summary": "홀드아웃 79문항 통과"}
    step = JobStep.model_validate({"name": "게이트", "status": "SUCCESS", "detail": verdict})
    assert step.model_dump()["detail"] == verdict
