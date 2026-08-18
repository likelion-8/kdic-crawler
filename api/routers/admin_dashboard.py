"""관리자 대시보드(AD-001) — 운영 요약 지표. **엔드포인트는 B 트랙 담당자가 채운다.**

이 파일은 자리만 잡아 둔 빈 라우터다. api/main.py 가 모두가 고치는 자리라, 각자 기능을
만들면서 등록 줄을 한 줄씩 더하면 머지 충돌이 확정적으로 난다(main.py 상단 주석). 미리
등록해 두면 작업이 이 파일 안에서만 끝난다.

## 만들 것 (3종)

    GET /api/admin/dashboard/summary
    GET /api/admin/dashboard/trend?range=7|30|90
    GET /api/admin/dashboard/resources?range=7|30|90

신규 테이블이 없다 — 이미 쌓인 데이터의 집계다. 원천은 rag_runs(질문 수·상태·latency) ·
feedback(좋아요/싫어요) · pipeline_jobs(작업) · admin_activity_logs(활동).

## 참고할 것

- api/routers/admin_logs.py 의 logs_summary() — 오늘(KST) 집계. 같은 KST 처리를 쓴다
- api/routers/admin_activity.py 의 activity_overview() — 현황 + facets 패턴
- docs/frontend-handoff.md "D. 대시보드" 절(D1~D4)
- web/src/mocks/handlers/extra/ad-dash-activity.ts — 응답 모양 정본

## 확정된 팀 결정

- 🔴 상시 지표 5종(indicators)은 **만들지 않는다**(D3, 2026-08-04 P-11). 임계치가 기획서
  어디에도 없고 5종 중 2종은 백엔드에 원천이 아예 없다. 기준 없이 경고를 띄우지 않는다.
- service.cause 를 서버가 정한다(D2) — 'ERROR_RATE'면 화면이 AD-005 실패 필터로,
  'PIPELINE'이면 AD-004 로 간다. 프론트는 이 값으로만 분기한다.
- 단계별 평균 응답시간은 **응답 8구간 고정 배열**이며 서버가 준 순서 그대로 그린다(D4).
- 표시 문자열(₩·M 등)은 서버가 완성해서 준다(D3'). 프론트가 단위를 지어내지 않는다.
- ⚠️ rag_runs.status 에는 옛 값 "success" 가 섞여 있다. admin_logs.py 의 LEGACY_STATUS
  매핑과 **같은 처리**를 할 것 — 안 하면 대시보드 숫자와 대화 로그 숫자가 어긋난다.
"""
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, cast, func, select

from api.deps import CurrentAdmin, DbSession, get_current_admin
from api.errors import BadRequestError
from api.routers.admin_logs import KST, _kst_day_start, _status_out, _to_kst_iso
from schema import document_chunks, documents, pipeline_jobs, rag_runs
from schema import feedback as feedback_table
from schema_admin import evaluation_runs
from schema_admin import admin_activity_logs

router = APIRouter(
    prefix="/api/admin/dashboard",
    tags=["admin-dashboard"],
    dependencies=[Depends(get_current_admin)],
)

RANGES = frozenset({7, 30, 90})

# D4 정본. rag_runs 에는 total_latency_ms 만 있고 단계별 컬럼은 아직 없다. 배열을 빼거나
# 순서를 바꾸면 화면 레이아웃이 달라지므로 미계측 단계도 0으로 포함한다.
LATENCY_STAGE_NAMES = (
    "질문 분해",
    "분류",
    "검색",
    "후보 컷",
    "근거 조립",
    "프롬프트",
    "답변 생성",
    "출처 판정",
)


def _range_days(value: int) -> int:
    if value not in RANGES:
        raise BadRequestError("조회 기간은 7일, 30일, 90일 중 하나여야 합니다.")
    return value


def _valid_run_filters():
    """대화 로그와 같은 모집단. 상세로 열 수 없는 request_id 없는 기록은 제외한다."""
    return (rag_runs.c.request_id.isnot(None), rag_runs.c.request_id != "")


def _today_window(now: datetime) -> tuple[datetime, datetime]:
    today = now.astimezone(KST).date()
    start = _kst_day_start(today)
    return start, start + timedelta(days=1)


def _range_window(now: datetime, days: int) -> tuple[date, datetime, datetime]:
    end_day = now.astimezone(KST).date()
    start_day = end_day - timedelta(days=days - 1)
    return start_day, _kst_day_start(start_day), _kst_day_start(end_day) + timedelta(days=1)


def _kst_date_column():
    """timestamptz를 KST 날짜로 묶는다. trend와 화면의 날짜 경계를 일치시킨다."""
    return cast(func.timezone("Asia/Seoul", rag_runs.c.created_at), Date)


def build_dashboard_trend_query(*, start: datetime, end: datetime):
    day = _kst_date_column().label("day")
    return (
        select(day, func.count().label("count"))
        .where(*_valid_run_filters(), rag_runs.c.created_at >= start, rag_runs.c.created_at < end)
        .group_by(day)
        .order_by(day)
    )


def _pipeline_status(value: str | None) -> str:
    return {
        "SUCCESS": "정상",
        "FAILED": "실패",
        "RUNNING": "실행 중",
        "QUEUED": "대기 중",
        "CANCELLED": "취소",
    }.get(value or "", "기록 없음")


@router.get("/summary")
def dashboard_summary(admin: CurrentAdmin, db: DbSession):
    """상태·KPI·분포·응답시간 요약. indicators는 팀 결정에 따라 만들지 않는다."""
    del admin
    now = datetime.now(timezone.utc)
    today_start, tomorrow_start = _today_window(now)
    valid_today = (
        *_valid_run_filters(),
        rag_runs.c.created_at >= today_start,
        rag_runs.c.created_at < tomorrow_start,
    )

    pages = db.execute(
        select(func.count()).select_from(documents).where(documents.c.is_active.is_(True))
    ).scalar_one()
    chunks = db.execute(
        select(func.count()).select_from(document_chunks)
        .where(document_chunks.c.is_active.is_(True))
    ).scalar_one()

    # admin_logs.logs_summary와 똑같이 저장 상태를 화면 어휘로 옮긴 뒤 합친다. 옛 success
    # 행이 NORMAL로 합쳐져야 두 화면의 질문 수·오류 수가 어긋나지 않는다.
    status_rows = db.execute(
        select(rag_runs.c.status, func.count())
        .where(*valid_today).group_by(rag_runs.c.status)
    ).all()
    by_status: dict[str | None, int] = {}
    for status, count in status_rows:
        normalized = _status_out(status)
        by_status[normalized] = by_status.get(normalized, 0) + count

    avg_latency = db.execute(
        select(func.avg(rag_runs.c.total_latency_ms)).where(*valid_today)
    ).scalar_one()
    intent_rows = db.execute(
        select(rag_runs.c.intent, func.count())
        .where(*valid_today).group_by(rag_runs.c.intent)
    ).all()
    by_intent = {intent: count for intent, count in intent_rows}
    intent_total = sum(by_intent.get(key, 0) for key in ("informational", "civil_petition"))
    intent_ratio = {
        key: round(by_intent.get(key, 0) * 100 / intent_total) if intent_total else 0
        for key in ("informational", "civil_petition")
    }

    latest_pipeline = db.execute(
        select(pipeline_jobs.c.status, pipeline_jobs.c.created_at)
        .order_by(pipeline_jobs.c.created_at.desc()).limit(1)
    ).first()
    pipeline_failed = db.execute(
        select(func.count()).select_from(pipeline_jobs)
        .where(pipeline_jobs.c.created_at >= today_start,
               pipeline_jobs.c.created_at < tomorrow_start,
               pipeline_jobs.c.status == "FAILED")
    ).scalar_one()
    activity_failed = db.execute(
        select(func.count()).select_from(admin_activity_logs)
        .where(admin_activity_logs.c.occurred_at >= today_start,
               admin_activity_logs.c.occurred_at < tomorrow_start,
               admin_activity_logs.c.result == "실패")
    ).scalar_one()

    rag_failed = by_status.get("FAILED", 0)
    error_count = rag_failed + pipeline_failed + activity_failed
    cause = "PIPELINE" if pipeline_failed else "ERROR_RATE" if error_count else None
    average = round(float(avg_latency or 0))

    # ── 할 일(todos) — 대시보드를 '지표판'이 아니라 '시작점'으로 만드는 값이다.
    # 관리자 화면은 관리 대상별로 나뉘어 있어, 이게 없으면 무엇을 해야 하는지 알려면 화면을
    # 하나씩 열어 봐야 한다(AD-DF-000 관리자 작업 흐름 ①). 각 항목은 건수와 함께 **그 건수를
    # 보여줄 화면의 필터**를 같이 내려, 카드를 눌렀을 때 여기서 센 것과 같은 목록이 열리게 한다.
    # 0 건이어도 항목을 지우지 않는다 — 사라지면 '없는 것'과 '못 센 것'이 구분되지 않는다.
    # 최근 30일로 좁힌다 — 대화 로그 화면의 기간 옵션(오늘·7일·30일·직접≤90일)에 '전체'가
    # 없어서, 전체 기간을 세면 카드 건수와 열리는 목록의 건수가 어긋난다(카드 3건 → 목록 0건).
    # 카드가 넘기는 filter 도 같은 30일이라야 "센 것과 같은 목록"이 열린다.
    since_30d = now - timedelta(days=30)
    feedback_down = db.execute(
        select(func.count()).select_from(feedback_table)
        .where(feedback_table.c.vote == "down",
               feedback_table.c.created_at >= since_30d)
    ).scalar_one()
    jobs_open = db.execute(
        select(func.count()).select_from(pipeline_jobs)
        .where(pipeline_jobs.c.status.in_(("QUEUED", "RUNNING", "FAILED")))
    ).scalar_one()
    latest_run = db.execute(
        select(evaluation_runs.c.gate)
        .where(evaluation_runs.c.status == "DONE")
        .order_by(evaluation_runs.c.finished_at.desc().nulls_last()).limit(1)
    ).first()
    gate = (latest_run.gate if latest_run else None) or {}
    # gate 가 비면 '미통과'가 아니라 '아직 잰 적 없음'이다 — false 로 접으면 거짓 경보가 된다.
    gate_failed = 0 if not gate else (0 if gate.get("passed") else 1)

    todos = [
        {"key": "FEEDBACK_DOWN", "label": "나쁨 평가를 받은 답변", "count": feedback_down,
         "target": {"screen": "logs", "filter": {"feedback": "down", "period": "30d"}}},
        {"key": "PIPELINE_OPEN", "label": "대기·진행·실패한 작업", "count": jobs_open,
         "target": {"screen": "pipeline", "filter": {}}},
        {"key": "GATE_FAILED", "label": "최근 평가 게이트 미통과", "count": gate_failed,
         "target": {"screen": "evaluations", "filter": {}}},
    ]

    return {
        "generated_at": _to_kst_iso(now),
        # ⚠️ '미처리'로 좁히지 못한다 — 대화 로그에 처리 상태를 저장하는 컬럼이 아직 없다
        # (admin_logs 의 triage 가 늘 'NONE'인 것과 같은 사정). 처리 완료를 저장하게 되면
        # FEEDBACK_DOWN 을 미처리 건수로 좁힌다.
        "todos": todos,
        "service": {
            "level": "ERROR" if error_count else "OK",
            "error_count": error_count,
            "cause": cause,
        },
        "kpi": {
            "pages": pages,
            "chunks": chunks,
            "questions_today": sum(by_status.values()),
            "avg_latency_ms": average,
            "pipeline": {
                "status": _pipeline_status(latest_pipeline.status if latest_pipeline else None),
                "last_run_at": _to_kst_iso(latest_pipeline.created_at) if latest_pipeline else "",
            },
        },
        "distribution": {
            "intent": intent_ratio,
            # rag_runs에는 업무분류 컬럼이 없다. 질문 문구로 추측하지 않는다.
            "business": [],
        },
        "latency": {
            "avg_total_ms": average,
            "stages": [{"name": name, "avg_ms": 0} for name in LATENCY_STAGE_NAMES],
        },
    }


@router.get("/trend")
def dashboard_trend(
    admin: CurrentAdmin,
    db: DbSession,
    range_: int = Query(default=7, alias="range"),
):
    """최근 N일의 KST 일별 질문 수. 기록이 없는 날짜도 0으로 채운다."""
    del admin
    days = _range_days(range_)
    now = datetime.now(timezone.utc)
    start_day, start, end = _range_window(now, days)
    rows = db.execute(build_dashboard_trend_query(start=start, end=end)).all()
    counts = {row.day.isoformat(): row.count for row in rows}
    return {
        "range": days,
        "points": [
            {"date": (start_day + timedelta(days=offset)).isoformat(),
             "count": counts.get((start_day + timedelta(days=offset)).isoformat(), 0)}
            for offset in range(days)
        ],
    }


@router.get("/resources")
def dashboard_resources(
    admin: CurrentAdmin,
    db: DbSession,
    range_: int = Query(default=7, alias="range"),
):
    """리소스·비용 표시 계약.

    rag_runs에는 토큰·호출별 비용·동시성 컬럼이 없다. 0을 실측값처럼 채우지 않고 빈
    시계열과 서버 완성 표시문구를 내려 화면의 0건 상태를 사용한다.
    """
    del admin, db
    days = _range_days(range_)
    return {
        "range": days,
        "tokens": [],
        "cost": [],
        "cost_caption": f"최근 {days}일 · 비용 집계 원천 없음",
        "today": {
            "tokens_text": "집계 원천 없음",
            "cost_text": "집계 원천 없음",
            "concurrency_text": "N/A",
            "gpu_text": "N/A",
        },
        "cost_breakdown": [],
    }
