"""데이터 파이프라인 작업(AD-004) — 재수집·재적재 잡의 생성·조회.

⚠️ 아직 뼈대만 있다. 엔드포인트는 이 파일 안에 추가한다.

이 파일을 미리 만들어 둔 이유는 하나다 — **api/main.py 를 아무도 안 건드리게 하기 위해서다.**
라우터 등록은 이미 끝나 있으므로(main.py create_app), 여기에 @router.post(...) 를 더하면
그대로 서비스에 붙는다. 여러 명이 동시에 관리자 API 를 만드는 동안 main.py 는 모두가 고치는
파일이라 충돌이 확정적으로 나는 자리였다.

## 인증은 이미 걸려 있다

router 에 dependencies=[Depends(get_current_admin)] 가 붙어 있어, 여기 추가하는 모든
엔드포인트가 자동으로 인증을 요구한다(쿠키 없으면 401). 엔드포인트마다 CurrentAdmin 을
받을 필요가 없고, 깜빡해서 인증 없이 열리는 사고도 나지 않는다.

실행자 정보(email·role)가 실제로 필요한 핸들러에서만 `me: CurrentAdmin` 을 추가로 받으면 된다.

## 만들 것 (web/src/routes/admin/pipeline/api.ts 가 계약 정본)

    POST /api/admin/jobs        생성  -> 202 + PipelineJob 본문
    GET  /api/admin/jobs        목록  -> {items, total, page, size} · 기본 created_at:desc
    GET  /api/admin/jobs/{id}   상세

지켜야 할 것 (docs/backend-structure.md §3 함정 #8·#9)

- 생성은 **202 + 본문**. 204 나 빈 본문이면 화면이 방금 만든 잡을 못 찾는다.
- 동시 실행 초과는 **409 + retryable=false**. constants.ts PIPELINE_CONCURRENCY=1 이 근거다.
  QUEUED/RUNNING 인 잡이 있으면 409. retryable 을 true 로 주면 [다시 시도] 버튼이 떠서
  계속 409 를 맞는다.
- 목록 정렬이 기능 계약이다. 프론트는 "진행 중 작업은 항상 1페이지"라고 가정하고 page=1
  에서만 active job 을 찾는다(Pipeline.tsx:120-125). 정렬이 깨지면 폴링이 조용히 오작동한다.
- steps 는 6단계(수집·변환·청킹·검증·색인·반영)를 생성 시 전부 QUEUED 로 초기화한다.
  안 채우면 진행 표시가 빈 채로 뜬다.

## sync def 로 쓸 것

DB 접근(SQLAlchemy 동기 세션)이 블로킹이라 async def 로 두면 이벤트 루프를 막는다.
평범한 def 로 두면 FastAPI 가 스레드풀에서 돌린다(api/deps.py get_db 주석과 같은 이유).
"""
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, insert, select, update

from api.deps import (ACTION_BY_JOB_TYPE, CurrentAdmin, DbSession,
                      get_current_admin, write_activity_log)
from api.errors import ApiError, BadRequestError, ForbiddenError, NotFoundError
from api.schemas.pipeline import JobCancel, JobCreate, PipelineJob, PipelineJobList
from schema import pipeline_jobs

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-pipeline"],
    # 라우터 전체에 인증. 여기 추가되는 엔드포인트는 전부 자동으로 보호된다.
    dependencies=[Depends(get_current_admin)],
)

# JobType/JobStatus 정본: web/src/lib/codes.ts
JOB_TYPES = frozenset(
    {"FULL_RECRAWL", "SELECTED_RECRAWL", "REINDEX", "RECHUNK", "REEMBED", "SMOKE_EVAL"})
ACTIVE_STATUSES = ("QUEUED", "RUNNING")  # 동시 실행 1개 규칙의 판정 대상
# 6단계 이름 정본: web/src/lib/constants.ts PIPELINE_STEPS (수집·변환·청킹·검증·색인·반영)
PIPELINE_STEPS = ("수집", "변환", "청킹", "검증", "색인", "반영")
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100
SORT_COLUMNS = {"created_at": pipeline_jobs.c.created_at}
ROLE_RANK = {"VIEWER": 0, "OPERATOR": 1, "EDITOR": 2, "ADMIN": 3}


class JobConflictError(ApiError):
    """동시 실행 초과(409). constants.ts PIPELINE_CONCURRENCY=1 — QUEUED/RUNNING 잡이 있으면
    새 잡 생성을 막는다. retryable 은 ApiError 기본값 False 그대로 둔다 — True 면 프론트에
    [다시 시도] 버튼이 떠서 계속 409 를 맞는다(backend-structure §3 함정 #9). errors.py 에 409
    클래스가 없어 여기 로컬로 둔다(다른 파일은 안 건드림). ApiError 서브클래스라 공통 예외
    핸들러가 그대로 봉투로 만들어 준다."""
    code = "pipeline_busy"
    status_code = 409
    user_message = "이미 실행 중이거나 대기 중인 작업이 있습니다. 완료 후 다시 시도해 주세요."


class JobCancelConflictError(ApiError):
    """이미 끝난 작업은 취소할 수 없다."""
    code = "pipeline_cancel_conflict"
    status_code = 409
    user_message = "이미 종료된 작업은 취소할 수 없습니다."


def _initial_steps():
    """생성 시 6단계를 전부 QUEUED 로 초기화. 안 채우면 프론트 진행바가 빈 채로 뜬다."""
    return [{"name": name, "status": "QUEUED"} for name in PIPELINE_STEPS]


def _row_to_job(row) -> PipelineJob:
    """pipeline_jobs 한 행 -> PipelineJob. JSONB(targets/steps/error/metrics)는 psycopg 가
    이미 파이썬 list/dict 로 넘겨준다."""
    return PipelineJob(
        id=str(row.id),
        type=row.type,
        status=row.status,
        targets=row.targets or [],
        reason=row.reason or "",
        created_by=row.created_by,
        created_at=row.created_at,
        steps=row.steps or [],
        error=row.error,
        rollback_of=row.rollback_of,
        target_summary=row.target_summary,
        target_count=row.target_count,
        index_impact=row.index_impact,
        metrics=row.metrics,
    )


def _order_by(sort: str):
    """정렬 파싱. 목록 정렬은 기능 계약이다 — 프론트가 '진행 중 잡은 1페이지 맨 위'라고
    가정하므로(Pipeline.tsx) 기본 created_at:desc 를 지킨다."""
    field, sep, direction = sort.partition(":")
    if sep != ":" or field not in SORT_COLUMNS or direction not in {"asc", "desc"}:
        raise BadRequestError("지원하지 않는 정렬 조건입니다.")
    col = SORT_COLUMNS[field]
    return col.desc() if direction == "desc" else col.asc()


@router.post("/jobs", status_code=202, response_model=PipelineJob)
def create_job(body: JobCreate, request: Request, db: DbSession, me: CurrentAdmin):
    """작업 생성 -> 202 + PipelineJob 본문. QUEUED 로만 만들고 실제 실행은 안 한다(워커는 다음
    단계). 동시 실행 1개 규칙: QUEUED/RUNNING 잡이 있으면 409(retryable=false)."""
    if body.type not in JOB_TYPES:
        raise BadRequestError("지원하지 않는 작업 종류입니다.")

    active = db.execute(
        select(func.count()).select_from(pipeline_jobs)
        .where(pipeline_jobs.c.status.in_(ACTIVE_STATUSES))
    ).scalar_one()
    if active:
        raise JobConflictError()

    row = db.execute(
        insert(pipeline_jobs)
        .values(type=body.type, status="QUEUED", targets=body.targets,
                reason=body.reason, created_by=me.email, steps=_initial_steps())
        .returning(*pipeline_jobs.c)
    ).first()
    db.commit()

    # 재수집·재색인은 검색 결과를 바꾸는 작업이라 감사 기록에 남긴다(AD-011).
    # 🔴 잡 생성을 commit 한 뒤에 부른다 — write_activity_log 가 스스로 commit 하므로,
    #    먼저 부르면 이 함수의 commit 이 위의 INSERT 까지 같이 확정해 버린다(deps.py 주석과 동일).
    #    기록이 실패해도 예외를 올리지 않으므로 잡 생성이 막히지는 않는다.
    write_activity_log(
        db, request,
        actor=me.email, actor_role=me.role,
        action=ACTION_BY_JOB_TYPE.get(body.type, body.type),
        # 대상은 잡 id 다 — 화면에서 이 값으로 어느 작업인지 짚을 수 있어야 한다.
        target=str(row.id),
        reason=body.reason or None,
        detail={"job_type": body.type, "targets": body.targets or []},
    )
    return _row_to_job(row)


@router.get("/jobs", response_model=PipelineJobList)
def list_jobs(db: DbSession,
              page: int = Query(1, ge=1),
              size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
              sort: str = Query("created_at:desc")):
    """목록 -> {items, total, page, size}. page 1-base, 기본 정렬 created_at:desc."""
    order = _order_by(sort)
    total = db.execute(select(func.count()).select_from(pipeline_jobs)).scalar_one()
    rows = db.execute(
        select(pipeline_jobs).order_by(order).limit(size).offset((page - 1) * size)
    ).all()
    return PipelineJobList(
        items=[_row_to_job(r) for r in rows], total=total, page=page, size=size)


@router.get("/jobs/{job_id}", response_model=PipelineJob)
def get_job(job_id: str, db: DbSession):
    """상세 -> PipelineJob. 없거나 형식이 틀린 id 면 404(UUID 컬럼이라 잘못된 형식은 쿼리가
    500 을 내므로 먼저 걸러낸다)."""
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise NotFoundError("작업을 찾을 수 없습니다.")
    row = db.execute(select(pipeline_jobs).where(pipeline_jobs.c.id == job_id)).first()
    if row is None:
        raise NotFoundError("작업을 찾을 수 없습니다.")
    return _row_to_job(row)


@router.post("/jobs/{job_id}/cancel", response_model=PipelineJob)
def cancel_job(job_id: str, body: JobCancel, request: Request,
               db: DbSession, me: CurrentAdmin):
    """대기/실행 중 작업을 원자적으로 취소한다."""
    if ROLE_RANK.get(me.role, -1) < ROLE_RANK["OPERATOR"]:
        raise ForbiddenError("작업 취소에는 OPERATOR 이상 권한이 필요합니다.")
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise NotFoundError("작업을 찾을 수 없습니다.")

    existing = db.execute(
        select(pipeline_jobs.c.id).where(pipeline_jobs.c.id == job_id)
    ).first()
    if existing is None:
        raise NotFoundError("작업을 찾을 수 없습니다.")

    row = db.execute(
        update(pipeline_jobs)
        .where(pipeline_jobs.c.id == job_id,
               pipeline_jobs.c.status.in_(ACTIVE_STATUSES))
        .values(status="CANCELLED")
        .returning(*pipeline_jobs.c)
    ).first()
    if row is None:
        db.rollback()
        raise JobCancelConflictError()
    db.commit()

    reason = body.reason.strip() or None
    write_activity_log(
        db, request,
        actor=me.email, actor_role=me.role,
        action="작업 취소", target=job_id, reason=reason,
        detail={"job_type": row.type},
    )
    return _row_to_job(row)
