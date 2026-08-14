"""관리자 활동 로그 조회(AD-011) — 누가·언제·무엇을 했는지 읽는 창구.

`admin_activity_logs` 는 이미 쌓이고 있었지만 읽는 API 가 없어 화면이 404 를 받고 있었다.
이 파일이 그 구멍을 메운다. 감사 기록 쓰기는 api/deps.py 의 write_activity_log 가 맡는다.

## 추가 전용이다

수정·삭제 엔드포인트를 만들지 않는다. 감사 기록을 지울 수 있으면 감사 기록이 아니다.
내보내기(POST /exports)는 원장 행을 수정하지 않지만, ADMIN 전용 데이터 반출 행위 자체는
새 감사 기록으로 남긴다.

## 권한이 다른 로그와 반대다

대화 로그(AD-005)는 VIEWER 에게 403 이지만, 활동 로그 조회는 **VIEWER 도 허용**이다
(mocks/README.md 의 권한 표). 내보내기만 ADMIN 이다 — 기록을 파일로 빼가는 행위라서다.

## KST 를 다루는 방식

화면은 기간 필터를 `from=YYYY-MM-DD` **KST 날짜**로 보내고, 받은 시각 문자열을 formatKst 로
그대로 지역 시각처럼 읽는다. 그래서 이 파일은 양쪽 끝에서 KST 로 변환한다.

    입력: from(KST 날짜) -> 그 날 00:00 KST 이후    (_kst_day_start)
    출력: occurred_at    -> +09:00 ISO 문자열       (_to_kst_iso)

UTC 문자열을 그대로 내보내면 화면의 '오늘'이 9시간 어긋난다. 새벽 0~9시 사이 기록이
전날로 밀려 보이는 형태라, 눈에 잘 안 띄고 원인 찾기도 어렵다.
"""
import json
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select

from api.deps import (CurrentAdmin, DbSession, RESULT_SUCCESS, RISKY_ACTIONS,
                      get_current_admin, write_activity_log)
from api.errors import BadRequestError, ForbiddenError, NotFoundError
from api.schemas.activity import (ActivityEventDetail, ActivityEventList,
                                  ActivityEventRow, ActivityExportRequest,
                                  ActivityExportResponse, ActivityOverview,
                                  ActivitySnapshot, RiskyOpList, RiskyOpRow)
from schema_admin import admin_activity_logs

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin/activity",
    tags=["admin-activity"],
    # 라우터 전체에 인증. 역할 구분은 내보내기에서만 추가로 본다.
    dependencies=[Depends(get_current_admin)],
)

KST = timezone(timedelta(hours=9))
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# 보관 기간. 이 값이 지난 행은 별도 정리 작업이 지운다(아직 없다 — 현황 숫자만 미리 보여 준다).
RETENTION_DAYS = 90
# '이번 주 삭제 예정'의 창. 화면 문구가 주 단위라 7일로 둔다.
PURGE_WINDOW_DAYS = 7

# 필터 선택지가 너무 길어지면 화면 드롭다운이 못 쓰게 된다. 어휘는 수십 개 규모라 넉넉하다.
MAX_FILTER_CHOICES = 100

SORT_COLUMNS = {"occurred_at": admin_activity_logs.c.occurred_at}
EXPORT_ROLES = frozenset({"ADMIN"})
ACTION_ACTIVITY_EXPORT = "활동 로그 내보내기"


def _to_kst_iso(value: Optional[datetime]) -> Optional[str]:
    """timestamptz -> +09:00 ISO 문자열. 위 모듈 주석의 '출력' 쪽이다."""
    if value is None:
        return None
    # DB 가 naive 로 돌려주는 경우(드라이버·컬럼 설정에 따라)는 UTC 로 본다. 컬럼이
    # timestamptz 라 저장된 값 자체는 UTC 기준이다.
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(KST).isoformat()


def _kst_day_start(day: date) -> datetime:
    """KST 날짜의 00:00 을 가리키는 시각. 비교는 UTC 로 저장된 컬럼과 직접 한다."""
    return datetime(day.year, day.month, day.day, tzinfo=KST)


def _parse_kst_date(raw) -> date:
    """'YYYY-MM-DD' -> date. 형식이 틀리면 400 이다.

    타입을 못 박고 str() 로 눕히는 이유는 내보내기 경로 때문이다. POST /exports 의
    filter 는 JSON dict 라 `{"from": 20260804}` 처럼 문자열이 아닌 값이 올 수 있고,
    그대로 date.fromisoformat 에 넣으면 400 이 아니라 TypeError -> 500 이 난다.
    """
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError) as exc:
        raise BadRequestError("기간 형식이 올바르지 않습니다. YYYY-MM-DD 로 보내 주세요.") from exc


def _escape_like(value: str) -> str:
    """ILIKE 와일드카드를 검색어가 아니라 일반 문자로 취급한다."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _order_by(sort: str):
    """정렬 파싱. 화면은 항상 occurred_at:desc 를 보내지만, 임의 컬럼을 허용하면
    인덱스 없는 컬럼으로 풀스캔이 걸리므로 목록을 닫아 둔다."""
    field, separator, direction = sort.partition(":")
    if separator != ":" or field not in SORT_COLUMNS or direction not in {"asc", "desc"}:
        raise BadRequestError("지원하지 않는 정렬 조건입니다.")
    column = SORT_COLUMNS[field]
    return column.desc() if direction == "desc" else column.asc()


def build_activity_event_queries(*, q: str, action: str, actor: str, result: str,
                                 from_date: Optional[str], sort: str):
    """목록과 total 이 같은 조건을 쓰도록 한 곳에서 만든다.

    한쪽에만 조건이 붙으면 '3건인데 5페이지'처럼 개수와 목록이 어긋난다. 지식베이스 목록이
    같은 이유로 빌더를 공유하고 있어서(admin_knowledge.build_knowledge_page_queries) 같은
    모양을 따른다.
    """
    filters = []

    if from_date:
        filters.append(admin_activity_logs.c.occurred_at >= _kst_day_start(_parse_kst_date(from_date)))
    if q:
        # 목 핸들러와 같은 대상 — 행위와 대상만 본다. 실행자까지 넓히면 검색칸에 이메일을
        # 넣었을 때 actor 필터와 결과가 겹쳐 무엇이 걸렸는지 알 수 없게 된다.
        pattern = f"%{_escape_like(q)}%"
        filters.append(or_(
            admin_activity_logs.c.action.ilike(pattern, escape="\\"),
            admin_activity_logs.c.target.ilike(pattern, escape="\\"),
        ))
    if action:
        filters.append(admin_activity_logs.c.action == action)
    if actor:
        filters.append(admin_activity_logs.c.actor == actor)
    if result:
        filters.append(admin_activity_logs.c.result == result)

    rows = select(admin_activity_logs).where(*filters).order_by(_order_by(sort))
    total = select(func.count()).select_from(admin_activity_logs).where(*filters)
    return rows, total


def _row_to_event(row) -> ActivityEventRow:
    """한 행 -> 화면 계약. NULL 허용 컬럼이 많아 빈 문자열로 눕힌다 — 화면이 값을 그대로
    렌더하므로 None 이 'None' 으로 찍히면 안 된다."""
    return ActivityEventRow(
        id=str(row.id),
        occurred_at=_to_kst_iso(row.occurred_at) or "",
        actor=row.actor or "",
        actor_role=row.actor_role or "",
        action=row.action or "",
        target=row.target or "",
        result=row.result or "",
        reason=row.reason or None,
        request_id=row.request_id or "",
        # 마스킹은 화면이 한다(EventDetail.tsx maskIp — '서버가 이미 마스킹해 주면 그대로
        # 통과시킨다'). 여기서 미리 가리면 되돌릴 수 없어 조사에 못 쓴다.
        ip=row.ip or "",
    )


def parse_snapshot_value(raw) -> Optional[dict]:
    """before_value/after_value(Text) -> 화면이 기대하는 dict.

    이 두 컬럼은 자유 텍스트라 무엇이 들어올지 컬럼만 봐서는 모른다. JSON 객체면 그대로,
    아니면 통짜 문자열을 하나의 항목으로 감싼다. 감싸 두면 상세 패널이 최소한 '무엇이
    바뀌었는지'를 보여줄 수 있다(파싱 실패로 통째로 버리는 것보다 낫다).
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {"value": str(raw)}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def build_snapshot(before_value, after_value) -> Optional[ActivitySnapshot]:
    """전후값이 하나라도 있을 때만 스냅샷을 만든다.

    빈 dict 를 늘 실어 보내면 상세 패널의 '변경 내용' 블록이 로그인 기록에도 빈 채로 뜬다.
    화면은 '데이터가 있는 블록만 렌더'하기로 돼 있다(AD-011 ❹).
    """
    before = parse_snapshot_value(before_value)
    after = parse_snapshot_value(after_value)
    if before is None and after is None:
        return None
    return ActivitySnapshot(before=before or {}, after=after or {})


@router.get("/overview", response_model=ActivityOverview)
def activity_overview(admin: CurrentAdmin, db: DbSession):
    """화면 상단 현황 3값 + 필터 선택지. VIEWER 도 볼 수 있다."""
    del admin  # 인증은 의존성이 처리하고, 현황에는 사용자별 데이터가 없다.

    now = datetime.now(timezone.utc)
    today_start = _kst_day_start(now.astimezone(KST).date())

    today_count = db.execute(
        select(func.count()).select_from(admin_activity_logs)
        .where(admin_activity_logs.c.occurred_at >= today_start)
    ).scalar_one()

    last_recorded_at = db.execute(
        select(func.max(admin_activity_logs.c.occurred_at))
    ).scalar_one()

    # 앞으로 7일 안에 보관 90일을 넘기는 행. 즉 기록된 지 83~90일 사이인 행이다.
    purge_due = db.execute(
        select(func.count()).select_from(admin_activity_logs)
        .where(admin_activity_logs.c.occurred_at > now - timedelta(days=RETENTION_DAYS))
        .where(admin_activity_logs.c.occurred_at
               <= now - timedelta(days=RETENTION_DAYS - PURGE_WINDOW_DAYS))
    ).scalar_one()

    actions = db.execute(
        select(admin_activity_logs.c.action).distinct()
        .where(admin_activity_logs.c.action.isnot(None))
        .order_by(admin_activity_logs.c.action).limit(MAX_FILTER_CHOICES)
    ).scalars().all()
    actors = db.execute(
        select(admin_activity_logs.c.actor).distinct()
        .where(admin_activity_logs.c.actor.isnot(None))
        .order_by(admin_activity_logs.c.actor).limit(MAX_FILTER_CHOICES)
    ).scalars().all()

    return ActivityOverview(
        today_count=today_count,
        last_recorded_at=_to_kst_iso(last_recorded_at),
        purge_due_this_week=purge_due,
        actions=list(actions),
        actors=list(actors),
    )


@router.get("/events", response_model=ActivityEventList)
def list_activity_events(
    admin: CurrentAdmin,
    db: DbSession,
    q: str = "",
    action: str = "",
    actor: str = "",
    result: str = "",
    # 화면은 '최근 N일'을 KST 날짜로 환산해 보낸다(ActivityLog.tsx params).
    from_: Optional[str] = Query(default=None, alias="from"),
    sort: str = "occurred_at:desc",
    page: int = Query(default=1, ge=1),
    size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """이벤트 목록 -> {items, total, page, size}. page 는 1-base."""
    del admin
    rows_query, total_query = build_activity_event_queries(
        q=q.strip(), action=action.strip(), actor=actor.strip(),
        result=result.strip(), from_date=from_, sort=sort,
    )
    total = db.execute(total_query).scalar_one()
    rows = db.execute(rows_query.offset((page - 1) * size).limit(size)).all()
    return ActivityEventList(
        items=[_row_to_event(row) for row in rows],
        total=total,
        page=page,
        size=size,
    )


@router.get("/events/{event_id}", response_model=ActivityEventDetail)
def get_activity_event(event_id: str, admin: CurrentAdmin, db: DbSession):
    """이벤트 상세 = 행 + 기록 시점 스냅샷."""
    del admin
    try:
        uuid.UUID(event_id)
    except ValueError:
        # UUID 컬럼이라 형식이 틀린 값을 그대로 조회하면 500 이 난다. 먼저 404 로 돌린다
        # (admin_pipeline.get_job 과 같은 처리).
        raise NotFoundError("이벤트를 찾을 수 없습니다.")

    row = db.execute(
        select(admin_activity_logs).where(admin_activity_logs.c.id == event_id)
    ).first()
    if row is None:
        raise NotFoundError("이벤트를 찾을 수 없습니다.")

    return ActivityEventDetail(
        **_row_to_event(row).model_dump(),
        snapshot=build_snapshot(row.before_value, row.after_value),
    )


@router.post("/exports", response_model=ActivityExportResponse)
def export_activity_events(body: ActivityExportRequest, request: Request,
                           admin: CurrentAdmin, db: DbSession):
    """내보내기 접수. 기록을 파일로 빼가는 행위라 ADMIN 만 할 수 있다.

    지금은 대상 건수를 세어 접수증만 돌려준다 — 실제 파일 생성·다운로드는 별도 작업이다.
    화면도 접수 후 토스트만 띄우고 파일을 기다리지 않는다(ActivityLog.tsx exporting).
    """
    if admin.role not in EXPORT_ROLES:
        raise ForbiddenError(
            f"이 작업에는 ADMIN 권한이 필요합니다. 현재 권한은 {admin.role}입니다.")
    if not (body.request_id or "").strip():
        raise BadRequestError("request_id가 필요합니다.")
    if not (body.reason or "").strip():
        raise BadRequestError("사유를 입력해 주세요.")

    # 현재 필터 결과가 대상이다(AD-011 Description 2). 같은 빌더를 써서 화면에 보이는
    # 건수와 접수증의 건수가 어긋나지 않게 한다.
    _, total_query = build_activity_event_queries(
        q=str(body.filter.get("q", "")).strip(),
        action=str(body.filter.get("action", "")).strip(),
        actor=str(body.filter.get("actor", "")).strip(),
        result=str(body.filter.get("result", "")).strip(),
        from_date=body.filter.get("from"),
        sort="occurred_at:desc",
    )
    estimated_rows = db.execute(total_query).scalar_one()

    export_id = f"exp_{uuid.uuid4().hex[:12]}"
    logger.info("활동 로그 내보내기 접수: %s (%s건, 요청자 %s)", export_id, estimated_rows, admin.email)
    write_activity_log(
        db, request,
        actor=admin.email,
        actor_role=admin.role,
        action=ACTION_ACTIVITY_EXPORT,
        target=f"활동 로그 · 현재 필터 ({export_id})",
        result=RESULT_SUCCESS,
        reason=body.reason.strip(),
        detail={
            "export_id": export_id,
            "estimated_rows": estimated_rows,
            "filter": dict(body.filter),
            "export_request_id": body.request_id.strip(),
        },
    )
    return ActivityExportResponse(
        export_id=export_id, status="QUEUED", estimated_rows=estimated_rows)


# "제목 (page_id)" 형태로 저장된 target 을 되돌리는 규칙. 쓰는 쪽이 그 형식을 쓴다
# (admin_change_requests.py:221 · admin_auth.patch_account). 컬럼을 target_name/target_id 로
# 쪼개는 것은 마이그레이션이라 이번 범위 밖이고, 화면(RiskyOp)은 둘을 나눠 요구한다.
_TARGET_WITH_ID = re.compile(r"^(?P<name>.+?)\s*\((?P<id>[^()]+)\)$")


def split_target(target: Optional[str]) -> tuple[str, Optional[str]]:
    """`"페이지 제목 (dp_003)"` -> `("페이지 제목", "dp_003")`.

    형식이 안 맞으면 통째로 이름으로 본다. 억지로 쪼개면 이름의 일부가 id 로 둔갑해
    화면의 딥링크가 없는 대상을 가리킨다 — 그때는 id 없이 이름만 보여주는 편이 정직하다.
    """
    if not target:
        return "", None
    match = _TARGET_WITH_ID.match(target.strip())
    if match is None:
        return target, None
    return match.group("name").strip(), match.group("id").strip()


@router.get("/risky-today", response_model=RiskyOpList)
def risky_today(
    admin: CurrentAdmin,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """오늘(KST) 실행된 위험 작업(A4). 접근 관리 화면 하단에 뜬다.

    '위험'의 정의는 api/deps.py 의 RISKY_ACTIONS 다 — 되돌리기 어렵거나 권한·보안을 바꾸는
    행위. 다른 트랙이 새 위험 행위를 만들면 그 집합에 문자열을 더하면 여기 잡힌다.

    성공한 것만 보여준다. 거부되거나 실패한 시도는 '실행된 위험 작업'이 아니고, 그건
    활동 로그 목록에서 result 필터로 본다.
    """
    del admin  # 인증은 라우터 의존성이 했다. 활동 로그는 VIEWER 도 볼 수 있다.

    now = datetime.now(timezone.utc)
    today_start = _kst_day_start(now.astimezone(KST).date())
    conditions = (
        admin_activity_logs.c.occurred_at >= today_start,
        admin_activity_logs.c.action.in_(sorted(RISKY_ACTIONS)),
        admin_activity_logs.c.result == RESULT_SUCCESS,
    )

    total = db.execute(
        select(func.count()).select_from(admin_activity_logs).where(*conditions)
    ).scalar_one()
    rows = db.execute(
        select(admin_activity_logs).where(*conditions)
        .order_by(admin_activity_logs.c.occurred_at.desc())
        .offset((page - 1) * size).limit(size)
    ).all()

    items = []
    for row in rows:
        target_name, target_id = split_target(row.target)
        items.append(RiskyOpRow(
            # 🔴 AD-011 의 event_id 와 같은 값이다(L7). 화면이 이 id 로 상세를 연다.
            id=str(row.id),
            occurred_at=_to_kst_iso(row.occurred_at) or "",
            action=row.action or "",
            target_name=target_name,
            target_id=target_id,
            actor=row.actor or "",
            reason=row.reason or "",
        ))
    return RiskyOpList(items=items, total=total, page=page, size=size)
