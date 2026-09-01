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
- 단계별 평균 응답시간은 서버가 준 순서 그대로 그린다(D4). 배열 길이는 고정이 아니다 —
  잰 단계만 실어 보낸다(build_stage_latency 참고).
- 표시 문자열(₩·M 등)은 서버가 완성해서 준다(D3'). 프론트가 단위를 지어내지 않는다.
- ⚠️ rag_runs.status 에는 옛 값 "success" 가 섞여 있다. admin_logs.py 의 LEGACY_STATUS
  매핑과 **같은 처리**를 할 것 — 안 하면 대시보드 숫자와 대화 로그 숫자가 어긋난다.
"""
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Date, cast, func, select, text

from api.deps import CurrentAdmin, DbSession, get_current_admin
from api.errors import BadRequestError
from observability import llm_usage
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

# D4 정본 — (계측 키, 화면 라벨)을 웹 요청이 도는 순서대로. 종전 8구간은 CLI 파이프라인
# (src/pipeline.py 의 timings 키)을 그대로 옮긴 것이라 실제 서빙 경로와 달랐다: 웹은
# api/rag/sse.py 를 돌아 게이트·질문 정리·캐시 조회를 먼저 타고 리랭커는 아예 안 부른다.
# 계측 키는 sse.py 와 answer.prepare_sub 이 rag_runs.observation.timings 에 적는 값이다.
LATENCY_STAGE_NAMES = (
    ("rewrite", "질문 정리"),
    ("gate", "게이트"),
    ("cache", "캐시 조회"),
    ("plan", "질의 계획"),
    ("retrieval", "검색"),
    ("generation", "답변 생성"),
    ("validation", "출처 판정"),
)


# 모수는 **전 구간을 다 돈 실행**뿐이다(generation 키가 있는 행). 캐시 적중·게이트 EXIT 처럼
# 검색·생성을 안 탄 턴을 섞으면 검색 평균이 안 검색한 턴 수만큼 낮아지고, 단계 비중의 분모인
# 총 응답시간도 같은 모수여야 비중이 성립한다.
_FULL_RUN_WHERE = """
       AND rag_runs.created_at >= :start
       AND rag_runs.created_at < :end
       AND rag_runs.request_id IS NOT NULL
       AND rag_runs.request_id <> ''
       AND jsonb_exists(rag_runs.observation -> 'timings', 'generation')
"""

# jsonb_each_text 로 펴서 키별 평균을 낸다. 단계 키를 늘려도 이 쿼리는 그대로다 —
# 화면에 나올지는 LATENCY_STAGE_NAMES 에 라벨이 있느냐로만 갈린다.
STAGE_LATENCY_SQL = text("""
    SELECT t.key, avg(t.value::float)
      FROM rag_runs, jsonb_each_text(rag_runs.observation -> 'timings') AS t
     WHERE true""" + _FULL_RUN_WHERE + """
     GROUP BY t.key
""")

STAGE_TOTAL_SQL = text("""
    SELECT avg(rag_runs.total_latency_ms)
      FROM rag_runs
     WHERE true""" + _FULL_RUN_WHERE)

STAGE_COUNT_SQL = text("""
    SELECT count(*)
      FROM rag_runs
     WHERE true""" + _FULL_RUN_WHERE)

# 업무별 분포 — rag_runs 에 업무 컬럼은 없지만, 그 답변이 **실제로 인용한 문서**는 남아 있다
# (observation.subs[].top[0].page_id). 질문 문구로 추측하는 게 아니라 근거 문서의
# documents.business_function 을 그대로 센다. 문서에 매칭 안 되는 page_id(삭제된 문서 등)는
# JOIN 에서 떨어져 분모에도 안 들어간다 — 못 센 것을 '기타'로 만들지 않는다.
# 세는 단위는 하위 질문이다. 복합 질문 하나가 착오송금과 예금자보호를 함께 물으면 두 업무에
# 각각 한 번씩 잡혀야 비중이 맞는다(질문 단위로 세면 뒤쪽 업무가 통째로 사라진다).
BUSINESS_MIX_SQL = text("""
    SELECT d.business_function, count(*)
      FROM rag_runs
      CROSS JOIN LATERAL jsonb_array_elements(rag_runs.observation -> 'subs') AS sub
      JOIN documents d ON d.page_id = sub -> 'top' -> 0 ->> 'page_id'
     WHERE rag_runs.created_at >= :start
       AND rag_runs.created_at < :end
       AND rag_runs.request_id IS NOT NULL
       AND rag_runs.request_id <> ''
     GROUP BY d.business_function
     ORDER BY count(*) DESC
""")


def build_stage_latency(avg_seconds_by_stage: dict, avg_total_ms: int,
                        sample_count: int) -> dict:
    """단계별 평균 소요(초) → 화면 계약(ms). 안 잰 단계는 **빼고** 내보낸다.

    0 으로 채우지 않는 이유: StageBars 는 avg_ms 를 그대로 막대로 그려서, 0 이 '즉시 끝남'
    으로 읽힌다. 종전 구현이 8단계를 전부 0 으로 내보내 그래프가 통째로 비어 보였다.
    단계가 하나도 없으면 빈 배열이라 화면이 '측정된 단계 기록이 없습니다'로 떨어진다.

    라벨 없는 키는 버린다 — 계측만 늘리고 라벨을 안 붙인 상태에서 영문 키가 화면에 새는 것
    보다 낫다.

    sample_count 는 이 평균을 낸 실행 건수다. 없으면 화면이 3건 평균과 300건 평균을 같은
    무게로 보여준다 — '출처 판정 45%'가 표본 셋에서 나온 값일 수 있다.
    """
    return {
        "avg_total_ms": avg_total_ms,
        "sample_count": sample_count,
        "stages": [{"name": label, "avg_ms": round(avg_seconds_by_stage[key] * 1000)}
                   for key, label in LATENCY_STAGE_NAMES if key in avg_seconds_by_stage],
    }


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

    business_rows = db.execute(
        BUSINESS_MIX_SQL, {"start": today_start, "end": tomorrow_start}
    ).all()
    business_total = sum(count for _label, count in business_rows)
    business_mix = [
        {"label": label, "ratio": round(count * 100 / business_total)}
        for label, count in business_rows
    ]

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
    # '미처리'만 센다(2026-08-18) — rag_runs.triage 가 생겨 처리 완료를 저장할 수 있다.
    # 조치하면 이 숫자가 줄어야 대시보드가 시작점 노릇을 한다.
    feedback_down = db.execute(
        select(func.count()).select_from(
            feedback_table.join(rag_runs, rag_runs.c.request_id == feedback_table.c.request_id))
        .where(feedback_table.c.vote == "down",
               feedback_table.c.created_at >= since_30d,
               rag_runs.c.triage != "RESOLVED")
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
        {"key": "FEEDBACK_DOWN", "label": "미처리 나쁨 평가", "count": feedback_down,
         "target": {"screen": "logs", "filter": {"feedback": "down", "period": "30d", "triage": "OPEN"}}},
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
            "business": business_mix,
        },
    }


@router.get("/latency")
def dashboard_latency(
    admin: CurrentAdmin,
    db: DbSession,
    range_: int = Query(default=7, alias="range"),
):
    """기간 안의 단계별 평균 소요. summary(오늘 고정)에서 떼어낸 이유는 기간 선택 때문이다.

    KPI '평균 응답시간'과 값이 다르다 — 저쪽은 오늘 전체 질문 평균이고 여기는 전 구간을 다 돈
    질문만 모수다(_FULL_RUN_WHERE). 모수를 함께 내보내야 화면이 3건 평균과 300건 평균을
    구분해 보여줄 수 있다.
    """
    del admin
    days = _range_days(range_)
    now = datetime.now(timezone.utc)
    _, start, end = _range_window(now, days)
    window = {"start": start, "end": end}
    stage_seconds = {stage: float(seconds)
                     for stage, seconds in db.execute(STAGE_LATENCY_SQL, window).all()}
    total_ms = round(float(db.execute(STAGE_TOTAL_SQL, window).scalar_one() or 0))
    count = int(db.execute(STAGE_COUNT_SQL, window).scalar_one() or 0)
    return {"range": days, **build_stage_latency(stage_seconds, total_ms, count)}


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


# ──────────────────── 리소스 모니터링(AD-001) — 원천은 Langfuse ────────────────────
# rag_runs 에는 토큰 컬럼이 없다. 2026-08-26 부터 모든 서빙 LLM 호출이 Langfuse generation
# span 으로 남으므로(observability.SERVING_GENERATION_NAMES) 그쪽 집계를 읽는다. Langfuse 를
# 못 읽으면 0 을 실측값처럼 채우지 않고 '집계 원천 없음'을 그대로 내려보낸다.

# NCP 가 요금 페이지에 함께 표기하는 당월 환율(2026-08 확인). CLOVA 공시가는 원화라 이걸로
# 옮긴다 — 우리가 정한 환율이 아니라 청구 주체가 쓰는 환율이라는 점이 중요하다. 달이 바뀌면
# 여기만 고친다(공시가 자체는 안 바뀐다).
KRW_TO_USD = 0.0006939

# LLM 단가 — USD / 1M 토큰, (입력, 출력). 표에 없는 모델은 '단가 미등록'이라 비용에서 빠진다
# (0 으로 채우면 '공짜'로 읽힌다). 새 모델을 쓰기 시작하면 여기 한 줄 더한다.
#
# CLOVA Studio: ncloud.com 요금표 · 한국 리전 · 구분 '기본' · 요금(실시간), 1,000 토큰 기준
#   HCX-007/005  입력 1.25원 · 출력 5원   |  HCX-DASH-002  입력 0.25원 · 출력 1원
#   (2026-08-26 확인. 튜닝·스킬셋·익스플로러 요금은 우리가 안 쓰므로 넣지 않는다.)
# gpt-5.6-luna: Langfuse 가 계산해 준 비용에서 역산했다(2026-08-26). 표본 3건이 소수점까지
#   맞는다 — 1659in/38out=$0.000377 · 3064/22=$0.000639 · 1368/38=$0.000319.
MODEL_PRICE_USD_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-5.6-luna": (0.20, 1.20),
    "HCX-007": (1.25 * 1_000 * KRW_TO_USD, 5 * 1_000 * KRW_TO_USD),
    "HCX-005": (1.25 * 1_000 * KRW_TO_USD, 5 * 1_000 * KRW_TO_USD),
    "HCX-DASH-002": (0.25 * 1_000 * KRW_TO_USD, 1 * 1_000 * KRW_TO_USD),
}

# generation span 이름 → 화면 라벨(비용 분석의 항목별 비중). 이름의 정본은
# observability.SERVING_GENERATION_NAMES 다 — 새 호출을 계측하면 양쪽에 같이 더한다.
STAGE_LABELS = {
    "hcx_stream": "답변 생성 (HyperCLOVA X)",
    "hcx_regenerate": "답변 재생성 (HyperCLOVA X)",
    "plan_query_llm": "질문 분해·의도 판단",
    "triage_query_llm": "질문 정리·되묻기 판정",
    "validate_answer_llm": "출처 판정",
    "classify_intent_llm": "질문 성격 분류",
}


def _tokens_compact(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _usd_text(value: float) -> str:
    """소수 넷째 자리까지 — 질문 1건이 $0.0013 라 두 자리로 자르면 전부 $0.00 이 된다."""
    return f"${value:,.2f}" if value >= 1 else f"${value:.4f}"


def _row_cost_usd(row: dict) -> float | None:
    """토큰 × 단가. 단가 미등록 모델은 None 이다 — 0 을 돌려주면 '안 썼다'와 구분이 안 된다."""
    price = MODEL_PRICE_USD_PER_1M.get(row["model"] or "")
    if price is None:
        return None
    return row["input"] * price[0] / 1_000_000 + row["output"] * price[1] / 1_000_000


def _unpriced_models(rows: list[dict]) -> list[str]:
    return sorted({r["model"] for r in rows
                   if r["model"] and MODEL_PRICE_USD_PER_1M.get(r["model"]) is None})


def _resources_unavailable(days: int) -> dict:
    """Langfuse 를 못 읽는 배포(키 미설정·조회 실패). 종전과 같은 '0건 상태' 응답이다."""
    return {
        "range": days,
        "tokens": [],
        "cost": [],
        "cost_caption": f"최근 {days}일 · 비용 집계 원천 없음(Langfuse 미연결)",
        "today": {"tokens_text": "집계 원천 없음", "cost_text": "집계 원천 없음",
                  "concurrency_text": "N/A", "gpu_text": "N/A"},
        "cost_breakdown": [],
    }


def build_resource_payload(days: int, day_rows: list[dict], today_rows: list[dict],
                           utc_days: list[str]) -> dict:
    """Langfuse 집계 → 화면 계약. 순수 함수라 테스트가 여기만 보면 된다.

    day_rows/today_rows 는 observability.llm_usage() 반환값. utc_days 는 그래프 x축으로 쓸
    날짜 문자열 목록(Langfuse 의 일 경계가 UTC 라 UTC 날짜다 — llm_usage docstring 참고)."""
    day_rows = [r for r in day_rows if r["name"]]
    today_rows = [r for r in today_rows if r["name"]]

    tokens_by_day = {d: {"date": d, "input": 0, "output": 0} for d in utc_days}
    cost_by_day = {d: 0.0 for d in utc_days}
    for r in day_rows:
        bucket = tokens_by_day.get(r["date"])
        if bucket is None:
            continue        # 조회 창 밖의 버킷(경계 반올림) — 축에 없는 날짜는 버린다
        bucket["input"] += r["input"]
        bucket["output"] += r["output"]
        usd = _row_cost_usd(r)
        if usd is not None:
            cost_by_day[r["date"]] += usd

    priced_total = sum(cost_by_day.values())
    unpriced = _unpriced_models(day_rows)
    caption = f"최근 {days}일 · 일 평균 {_usd_text(priced_total / days)}"
    if not day_rows:
        caption = f"최근 {days}일 · 기록된 LLM 호출 없음"
    elif unpriced:
        caption += f" · {', '.join(unpriced)} 단가 미등록(비용에서 제외)"

    # 항목별 비중 — 단가 미등록 단계는 금액 대신 그 사실을 적고 비중을 비운다. 0% 로 적으면
    # 안 썼다는 뜻이 되는데, 실제로는 토큰을 가장 많이 쓰는 단계가 여기 들어온다.
    by_stage: dict[str, dict] = {}
    for r in day_rows:
        st = by_stage.setdefault(r["name"], {"usd": 0.0, "priced": False, "tokens": 0})
        st["tokens"] += r["input"] + r["output"]
        usd = _row_cost_usd(r)
        if usd is not None:
            st["usd"] += usd
            st["priced"] = True
    breakdown = [
        {"label": STAGE_LABELS.get(name, name),
         "amount_text": _usd_text(st["usd"]) if st["priced"]
         else f"{_tokens_compact(st['tokens'])} 토큰 · 단가 미등록",
         "share": round(st["usd"] / priced_total * 100) if st["priced"] and priced_total else None}
        # 비용 큰 순. 금액을 못 매긴 단계(usd=0)는 자연히 맨 뒤로 가고 자기들끼리는 토큰
        # 순으로 선다 — 목록에서 사라지지는 않는다(사라지면 '안 썼다'로 읽힌다).
        for name, st in sorted(by_stage.items(), key=lambda kv: (-kv[1]["usd"], -kv[1]["tokens"]))
    ]

    today_in = sum(r["input"] for r in today_rows)
    today_out = sum(r["output"] for r in today_rows)
    today_costs = [_row_cost_usd(r) for r in today_rows]
    today_priced = [c for c in today_costs if c is not None]
    return {
        "range": days,
        "tokens": [tokens_by_day[d] for d in utc_days],
        "cost": [{"date": d, "usd": round(cost_by_day[d], 6)} for d in utc_days],
        "cost_caption": caption,
        "today": {
            "tokens_text": (f"입력 {_tokens_compact(today_in)} · 출력 {_tokens_compact(today_out)}"
                            if today_rows else "호출 없음"),
            "cost_text": _usd_text(sum(today_priced)) if today_priced else "단가 미등록",
            # 동시 요청·GPU 는 원천이 없다. 0 을 실측처럼 채우지 않는다(AD-001 A-6 과 동일 판단).
            "concurrency_text": "N/A",
            "gpu_text": "N/A",
        },
        "cost_breakdown": breakdown,
    }


@router.get("/resources")
def dashboard_resources(
    admin: CurrentAdmin,
    db: DbSession,
    range_: int = Query(default=7, alias="range"),
):
    """리소스·비용 — 원천은 Langfuse generation span 이다(위 블록 주석).

    질의는 둘뿐이다: 기간 일별(UTC 일 경계) + 오늘(KST 자정~현재). '오늘' 을 따로 묻는
    이유는 Langfuse 의 일 버킷이 UTC 라 KST 오늘과 최대 9시간 어긋나기 때문이다 —
    헤드라인 숫자만이라도 화면의 다른 KST 카드와 같은 날을 가리키게 한다."""
    del admin, db
    days = _range_days(range_)
    now = datetime.now(timezone.utc)
    first_day = now.date() - timedelta(days=days - 1)
    utc_days = [(first_day + timedelta(days=i)).isoformat() for i in range(days)]
    day_rows = llm_usage(datetime.combine(first_day, time.min, tzinfo=timezone.utc), now,
                         daily=True)
    if day_rows is None:
        return _resources_unavailable(days)
    today_rows = llm_usage(*_today_window(now)) or []
    return build_resource_payload(days, day_rows, today_rows, utc_days)
