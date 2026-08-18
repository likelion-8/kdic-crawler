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
from datetime import timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, insert, select, update

from api.deps import (ACTION_BY_JOB_TYPE, CurrentAdmin, DbSession, ReauthedAdmin,
                      get_current_admin, write_activity_log)
from api.errors import ApiError, BadRequestError, ForbiddenError, NotFoundError
from api.schemas.pipeline import (ChangedPage, ChangedPagesResponse, JobCancel,
                                  JobCreate, JobEstimate, JobRetry, JobRollback,
                                  PipelineJob, PipelineJobList)
from schema import documents, pipeline_jobs, test_set
from schema_admin import admin_activity_logs

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
JOB_STATUSES = frozenset({"QUEUED", "RUNNING", "SUCCESS", "FAILED", "CANCELLED"})
# 단계 이름 정본은 src/worker.py STEPS 하나다(2026-08-18 정정). 종전에 여기 6단계를 따로 적어
# 두어 게이트 단계가 신설된 뒤에도 잡의 steps 에 '게이트'가 없었고, 워커의 _set_step("게이트")가
# 매칭할 항목이 없어 판정이 통째로 기록되지 않았다(게이트는 돌았는데 화면엔 흔적 없음).
# 프론트 정본 web/src/lib/constants.ts PIPELINE_STEPS 도 같은 7단계다.
from worker import STEPS as PIPELINE_STEPS  # noqa: E402
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


class JobRetryConflictError(ApiError):
    """실패·취소된 작업만 재시도할 수 있다. 성공한 작업을 '재시도'로 부르면 이력이 헷갈린다."""
    code = "pipeline_retry_conflict"
    status_code = 409
    user_message = "실패하거나 취소된 작업만 다시 시도할 수 있습니다."


class JobRollbackConflictError(ApiError):
    """되돌릴 것이 있으려면 실제로 반영된(성공한) 작업이어야 한다."""
    code = "pipeline_rollback_conflict"
    status_code = 409
    user_message = "성공한 작업만 되돌릴 수 있습니다."


KST = timezone(timedelta(hours=9))


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

    # 대상 요약·건수는 서버가 채운다(P2). 화면의 '대상' 열이 이 문자열을 그대로 쓰는데,
    # 전체 작업은 targets 가 비어 있어 프론트가 건수를 알 방법이 없다.
    summary, count = _resolve_targets(db, body.type, body.targets)
    row = db.execute(
        insert(pipeline_jobs)
        .values(type=body.type, status="QUEUED", targets=body.targets,
                reason=body.reason, created_by=me.email, steps=_initial_steps(),
                target_summary=summary, target_count=count)
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
        # CM-DF-002 07절: 대상은 '사람이 읽는 이름 + (ID)' — ID 단독 노출 금지.
        target=f"{row.target_summary or body.type} ({row.id})",
        reason=body.reason or None,
        detail={"job_type": body.type, "targets": body.targets or []},
    )
    return _row_to_job(row)


@router.get("/jobs", response_model=PipelineJobList)
def list_jobs(db: DbSession,
              page: int = Query(1, ge=1),
              size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
              sort: str = Query("created_at:desc"),
              status: str = Query("")):
    """목록 -> {items, total, page, size}. page 1-base, 기본 정렬 created_at:desc.

    status 는 쉼표로 여러 값을 받는다 — `?status=RUNNING,QUEUED&size=1` 이 '진행 중 작업
    전용 조회'다(P4). 지금까지 프론트는 '동시 실행 1개니까 최신순 1페이지에 있다'는 가정으로
    active job 을 찾고 있었는데(Pipeline.tsx:120-125), 그 가정은 잡이 쌓이면 조용히 깨진다.

    total 은 필터를 적용한 뒤의 건수다 — 목록과 다른 모집단을 세면 '1건인데 3페이지'가 된다.
    """
    order = _order_by(sort)
    filters = []
    if status.strip():
        wanted = [s.strip().upper() for s in status.split(",") if s.strip()]
        unknown = [s for s in wanted if s not in JOB_STATUSES]
        if unknown:
            # 조용히 무시하면 필터가 안 걸린 전체 목록이 나가는데, 화면은 걸렀다고 믿는다.
            raise BadRequestError(f"지원하지 않는 상태 값입니다: {', '.join(unknown)}")
        filters.append(pipeline_jobs.c.status.in_(wanted))

    total = db.execute(
        select(func.count()).select_from(pipeline_jobs).where(*filters)).scalar_one()
    rows = db.execute(
        select(pipeline_jobs).where(*filters).order_by(order)
        .limit(size).offset((page - 1) * size)
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
        action="작업 취소", target=f"{row.target_summary or row.type} ({job_id})", reason=reason,
        detail={"job_type": row.type},
    )
    return _row_to_job(row)


# ─────────────────────────── 대상 건수 · 예상 소요 (P2·P3) ───────────────────────────
#
# target_summary·target_count 는 컬럼이 이미 있다(src/schema.py pipeline_jobs). 화면의 '대상'
# 열이 이 문자열을 그대로 쓰므로(pipeline/api.ts PipelineJob.target_summary) 서버가 완성해서
# 넣는다 — 프론트가 '전체'인지 '선택 3건'인지 판단하려면 targets 배열의 의미까지 알아야 한다.

# ⚠️ 페이지당 예상 초. **실측이 아니다** — 완료된 잡이 아직 없어(워커 미구현) 평균을 낼
# 원천이 자체가 없다. 수집은 네트워크 왕복이 있어 가장 느리고, 재색인은 임베딩 계산이,
# 청킹은 문자열 처리라 가장 빠르다는 상대 순서만 반영한 어림값이다.
# 🔴 잡이 실제로 돌기 시작하면 pipeline_jobs 의 소요 기록 평균으로 갈아야 한다.
_SECONDS_PER_TARGET = {
    "FULL_RECRAWL": 6.0,
    "SELECTED_RECRAWL": 6.0,
    "REINDEX": 3.0,
    "RECHUNK": 0.5,
    "REEMBED": 3.0,
    "SMOKE_EVAL": 8.0,
}


def _active_document_count(db) -> int:
    """전체 작업의 대상이 되는 페이지 수. 제외(EXCLUDED)된 문서는 빼야 화면의 '전체 N페이지'가
    지식베이스 목록 건수와 맞는다."""
    return db.execute(
        select(func.count()).select_from(documents)
        .where(documents.c.is_active.is_(True))
    ).scalar_one()


def _resolve_targets(db, job_type: str, targets: list) -> tuple[str, int]:
    """(target_summary, target_count). 화면의 '대상' 열 문자열을 서버가 완성한다.

    선택 작업은 받은 배열이 곧 대상이고, 전체 작업은 targets 가 비어 있어 서버가 센다.
    SMOKE_EVAL 만 단위가 페이지가 아니라 평가 문항이라 문구가 다르다.
    """
    if job_type == "SMOKE_EVAL":
        count = db.execute(select(func.count()).select_from(test_set)).scalar_one()
        return f"평가 {count}문항", count
    if targets:
        return f"선택 {len(targets)}페이지", len(targets)
    count = _active_document_count(db)
    return f"전체 {count}페이지", count


def _estimated_minutes(job_type: str, target_count: int) -> int:
    """어림 소요(분). 0 분으로 내려보내지 않는다 — 화면이 '예상 0분'을 띄우면 즉시 끝난다는
    뜻으로 읽히는데, 어떤 작업도 그렇지 않다."""
    seconds = _SECONDS_PER_TARGET.get(job_type, 3.0) * max(target_count, 1)
    return max(1, round(seconds / 60))


@router.get("/pipeline/estimate", response_model=JobEstimate)
def estimate_job(db: DbSession, type: str = Query(...)):
    """확인 모달의 '대상 N건 · 예상 M분'(P3). 잡을 만들지 않는다."""
    if type not in JOB_TYPES:
        raise BadRequestError("지원하지 않는 작업 종류입니다.")
    _, target_count = _resolve_targets(db, type, [])
    return JobEstimate(type=type, target_count=target_count,
                       estimated_minutes=_estimated_minutes(type, target_count))


# ─────────────────────────── 변경 감지 (P3) ───────────────────────────
#
# '변경 감지'의 정본은 documents.index_status == 'PENDING' 이다 — 별도 비교 작업이 채우는
# 값이고, admin_knowledge._list_state 가 같은 기준으로 목록 배지를 그린다. 두 화면이 다른
# 기준을 쓰면 '변경 감지 3건'인데 목록에는 5건이 뜬다.
#
# ⚠️ last_checked_at 의 원천이 컬럼에 없다. 마지막 비교 시각을 저장하는 자리가 어디에도
# 없어서(마이그레이션은 이번 범위 밖) **활동 로그에서 읽는다** — recheck 가 자기 실행을
# 기록하므로 그 최신 시각이 곧 '마지막으로 확인한 때'다. 한 번도 안 돌렸으면 빈 문자열이고
# 화면의 RefreshBar 는 그걸 '—' 로 그린다.
ACTION_CHANGES_RECHECK = "변경 감지 재확인"


def _last_checked_at(db) -> str:
    latest = db.execute(
        select(func.max(admin_activity_logs.c.occurred_at))
        .where(admin_activity_logs.c.action == ACTION_CHANGES_RECHECK)
    ).scalar_one_or_none()
    if latest is None:
        return ""
    aware = latest if latest.tzinfo else latest.replace(tzinfo=timezone.utc)
    return aware.astimezone(KST).isoformat()


def _changed_pages(db) -> list:
    rows = db.execute(
        select(documents.c.page_id, documents.c.page_title, documents.c.collected_at)
        .where(documents.c.index_status == "PENDING", documents.c.is_active.is_(True))
        .order_by(documents.c.collected_at.desc().nullslast())
    ).all()
    out = []
    for row in rows:
        collected = row.collected_at
        if collected is not None and collected.tzinfo is None:
            collected = collected.replace(tzinfo=timezone.utc)
        out.append(ChangedPage(
            page_id=row.page_id,
            title=row.page_title or row.page_id,
            # ⚠️ 원본 사이트에서 읽은 제목을 따로 저장하는 컬럼이 없다. 비교 작업이 그 값을
            # 남기게 되면 여기를 그 컬럼으로 바꾼다. 그때까지는 저장된 제목을 그대로 둔다 —
            # 빈 문자열을 주면 화면이 '제목이 사라졌다'로 읽는다.
            source_title=row.page_title or "",
            detected_at=collected.astimezone(KST).isoformat() if collected else "",
        ))
    return out


@router.get("/pipeline/changes", response_model=ChangedPagesResponse)
def list_changes(db: DbSession):
    """원본이 바뀐 것으로 감지된 페이지 목록(P3)."""
    return ChangedPagesResponse(last_checked_at=_last_checked_at(db), items=_changed_pages(db))


@router.post("/pipeline/changes/recheck", response_model=ChangedPagesResponse)
def recheck_changes(request: Request, db: DbSession, me: CurrentAdmin):
    """[지금 확인] — 재확인을 실행했다는 사실을 남기고 현재 목록을 돌려준다(P3).

    🔴 실제 재크롤·본문 비교는 여기서 하지 않는다. 그 일은 워커의 몫인데 워커가 아직 없다
    (POST /jobs 가 잡을 QUEUED 로만 만들고 실행하지 않는 것과 같은 상태다). 그래서 이
    호출은 index_status 를 바꾸지 않으며, 목록도 직전과 같을 수 있다.

    그런데도 기록을 남기는 이유는 last_checked_at 의 유일한 원천이라서다 — 이 행이 없으면
    화면이 '마지막 확인'을 영원히 '—' 로 띄운다. 워커가 붙으면 이 자리에서 비교를 돌리고
    기록은 그대로 두면 된다.
    """
    if ROLE_RANK.get(me.role, -1) < ROLE_RANK["OPERATOR"]:
        raise ForbiddenError("변경 감지 재확인에는 OPERATOR 이상 권한이 필요합니다.")

    write_activity_log(db, request, actor=me.email, actor_role=me.role,
                       action=ACTION_CHANGES_RECHECK, target="지식베이스 전체")
    return ChangedPagesResponse(last_checked_at=_last_checked_at(db), items=_changed_pages(db))


# ─────────────────────────── 재시도 · 긴급 롤백 ───────────────────────────

def _load_job(db, job_id: str):
    """id 형식 검사까지 포함한 조회. UUID 컬럼이라 형식이 틀린 값을 그대로 넣으면 500 이 난다."""
    try:
        uuid.UUID(job_id)
    except ValueError:
        raise NotFoundError("작업을 찾을 수 없습니다.")
    row = db.execute(select(pipeline_jobs).where(pipeline_jobs.c.id == job_id)).first()
    if row is None:
        raise NotFoundError("작업을 찾을 수 없습니다.")
    return row


def _guard_concurrency(db) -> None:
    """동시 실행 1개(constants.ts PIPELINE_CONCURRENCY). 생성·재시도·롤백이 같은 규칙을 쓴다."""
    active = db.execute(
        select(func.count()).select_from(pipeline_jobs)
        .where(pipeline_jobs.c.status.in_(ACTIVE_STATUSES))
    ).scalar_one()
    if active:
        raise JobConflictError()


@router.post("/jobs/{job_id}/retry", status_code=202, response_model=PipelineJob)
def retry_job(job_id: str, body: JobRetry, request: Request, db: DbSession, me: CurrentAdmin):
    """실패한 작업을 같은 조건으로 다시 돌린다 -> 202 + 새 PipelineJob.

    원래 행을 되살리지 않고 **새 잡을 만든다.** 실패한 실행도 기록으로 남아야 '몇 번 만에
    됐는가'를 볼 수 있고, steps 를 덮어쓰면 어느 단계에서 처음 깨졌는지가 사라진다.

    202 + 본문이다(함정 #8). 204 나 빈 본문이면 화면이 방금 만든 잡을 못 찾아 폴링을 못 건다.
    """
    if ROLE_RANK.get(me.role, -1) < ROLE_RANK["OPERATOR"]:
        raise ForbiddenError("작업 재시도에는 OPERATOR 이상 권한이 필요합니다.")

    original = _load_job(db, job_id)
    # 성공한 작업을 '재시도'라고 부르면 이력이 헷갈린다 — 같은 일을 또 하려면 새로 만들면 된다.
    if original.status not in ("FAILED", "CANCELLED"):
        raise JobRetryConflictError()
    _guard_concurrency(db)

    targets = list(original.targets or [])
    summary, count = _resolve_targets(db, original.type, targets)
    row = db.execute(
        insert(pipeline_jobs)
        .values(type=original.type, status="QUEUED", targets=targets,
                reason=body.reason.strip() or original.reason, created_by=me.email,
                steps=_initial_steps(), target_summary=summary, target_count=count)
        .returning(*pipeline_jobs.c)
    ).first()
    db.commit()

    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action="작업 재시도",
        target=f"{row.target_summary or original.type} ({row.id})", reason=body.reason.strip() or None,
        detail={"job_type": original.type, "retry_of": job_id},
    )
    return _row_to_job(row)


@router.post("/jobs/{job_id}/rollback", status_code=202, response_model=PipelineJob)
def rollback_job(job_id: str, body: JobRollback, request: Request, db: DbSession,
                 me: ReauthedAdmin):
    """긴급 롤백 — 성공한 작업의 결과를 직전 상태로 되돌리는 잡을 만든다. ADMIN 전용.

    🔴 재인증을 **서버가 독립 검증**한다(P5). me 의 타입이 ReauthedAdmin 이라 마지막 확인이
    30분을 넘겼으면 이 함수에 닿기 전에 403 이다. 프론트도 runRisky 로 먼저 재확인을
    받지만 그 판정은 클라이언트 코드라 우회할 수 있다 — 화면을 거치지 않고 이 경로를 직접
    때리면 재확인 없이 롤백이 돌아간다.

    rollback_of 에 원본 잡 id 를 남긴다. 이 값이 없으면 목록에서 롤백 잡과 평범한 재수집
    잡을 구분할 수 없다.
    """
    if me.role != "ADMIN":
        raise ForbiddenError("긴급 롤백에는 ADMIN 권한이 필요합니다.")
    if not body.reason.strip():
        raise BadRequestError("롤백 사유를 입력해 주세요.")

    original = _load_job(db, job_id)
    # 되돌릴 것이 있으려면 실제로 반영된 작업이어야 한다.
    if original.status != "SUCCESS":
        raise JobRollbackConflictError()
    _guard_concurrency(db)

    targets = list(original.targets or [])
    summary, count = _resolve_targets(db, original.type, targets)
    row = db.execute(
        insert(pipeline_jobs)
        .values(type=original.type, status="QUEUED", targets=targets,
                reason=body.reason.strip(), created_by=me.email, steps=_initial_steps(),
                rollback_of=job_id, target_summary=summary, target_count=count)
        .returning(*pipeline_jobs.c)
    ).first()
    db.commit()

    # '긴급 롤백'은 RISKY_ACTIONS 에 들어 있어 접근 관리의 '오늘의 위험 작업'에도 뜬다.
    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action="긴급 롤백",
        target=f"{row.target_summary or original.type} ({row.id})", reason=body.reason.strip(),
        detail={"job_type": original.type, "rollback_of": job_id},
    )
    return _row_to_job(row)
