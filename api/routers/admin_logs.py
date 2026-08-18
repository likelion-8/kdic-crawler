"""관리자 대화 로그 조회(AD-005) — 실사용 질의 1건씩을 읽는 창구.

`rag_runs` 에 질의 기록이, `feedback` 에 그 답변에 대한 좋아요·싫어요가 쌓여 있는데
읽는 API 가 없어 화면이 목 데이터로만 돌고 있었다. 이 파일이 그 구멍을 메운다.

## 읽기 전용이다

수정·삭제 엔드포인트를 만들지 않는다. 재실행(`/rerun`)·분류(`PATCH {triage}`)는 프론트 계약
(G1)의 7종 중 2종인데 이번 주 범위에서 뺐다(팀 결정) — 화면이 그 버튼을 그리고 있으면 프론트에
숨김을 요청한다(사유·조치: docs/conversation_logs_field_sources.md §8). 나머지 평가 후보 등록은
`POST /api/admin/evaluations/candidates`로 평가 라우터(admin_evaluations.py)에 구현했다.

## 권한이 활동 로그와 반대다

활동 로그(AD-011)는 VIEWER 도 볼 수 있지만, 대화 로그는 **VIEWER 에게 403** 이다.
사용자가 실제로 입력한 문장이 그대로 담기기 때문이다. 요약(`/summary`)만 VIEWER 에게
열어 둔다 — 집계 숫자에는 대화 내용이 없다(G2: 'VIEWER 는 집계만'은 화면 숨김이 아니라
서버 계약이어야 한다).

## KST 를 다루는 방식

화면은 기간을 `from`·`to` **KST 날짜**(YYYY-MM-DD)로 보내고(logs/api.ts periodRange),
받은 시각 문자열을 지역 시각처럼 그대로 읽는다. 그래서 양쪽 끝에서 KST 로 변환한다.

    입력: from/to(KST 날짜) -> [from 00:00 KST, to+1일 00:00 KST)   (_kst_day_start)
    출력: created_at        -> +09:00 ISO 문자열                     (_to_kst_iso)

`to` 를 그 날 00:00 으로 비교하면 '오늘'을 골랐을 때 오늘 것이 한 건도 안 나온다.
끝을 다음 날 00:00 **미만**으로 잡아 to 당일을 통째로 포함시킨다.

## 응답 모델

4종 전부 `api/schemas/logs.py` 의 모델을 `response_model=` 로 단다. 필드 이름·구조의 정본은
`web/src/routes/admin/logs/api.ts` 이고, 스키마가 그것을 1:1로 옮긴 것이다.

## ⚠️ rag_runs 에 원천이 없는 필드가 있다

`ConversationLogDetail` 이 요구하는 것 중 `source_count`·`triage`·`classification` 의
`business_function`·`source_used`·`marker`·`normalized` 는 `rag_runs` 에 컬럼이 없고
(src/schema.py:163-185), `question_type` 은 컬럼은 있지만 웹 경로가 항상 None 을 넘겨
실측 91건이 전부 NULL 이었다. 전부 null 로 내보낸다 — 처리 방침은
docs/conversation_logs_field_sources.md 에 있다.

**빈 값을 '사실'처럼 보이게 만들지 말 것.** logs/api.ts:39-49 에 같은 실수의 선례가 있다
(원천 없는 구획을 목업대로 남겼더니 빈 상태 문구가 운영자에게 거짓을 말했다). 그래서
`source_used=false` 같은 그럴듯한 기본값 대신 null 을 쓴다.
"""
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, func, select, update

from api.deps import (CurrentAdmin, DbSession, SettingsDep, get_current_admin,
                      write_activity_log)
from api.errors import BadRequestError, ForbiddenError, NotFoundError
from api.masking import mask_text
from api.rag import observation
from api.schemas.logs import (ConversationLogDetail, ConversationLogList,
                              ConversationLogRow, LogExportRequest, LogExportResponse,
                              LogSummary)
# src/ 는 flat import 다 — api/__init__.py 가 sys.path 에 넣어 준다(admin_activity.py 와 동일).
from schema import feedback as feedback_table
from schema import rag_runs

logger = logging.getLogger(__name__)

# mask_text 는 4종(주민·전화·카드·이메일) 마스킹을 조회 시점에 적용한다(2026-08-14 구현,
# api/masking.py). question_masked·answer_masked_*·feedback comment 가 전부 이 함수를 거친다.

router = APIRouter(
    prefix="/api/admin/logs",
    tags=["admin-logs"],
    # 라우터 전체에 인증. 역할 구분은 엔드포인트마다 추가로 본다(요약만 VIEWER 허용이라
    # 라우터 레벨에 한 번에 걸 수 없다).
    dependencies=[Depends(get_current_admin)],
)

KST = timezone(timedelta(hours=9))
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

# 직접 지정 기간 상한. 화면도 같은 값으로 막지만(logs/api.ts MAX_CUSTOM_DAYS) 프론트 판정은
# 우회 가능하므로 서버가 최종 판정한다. from·to 양끝을 포함한 일수 기준이다.
MAX_RANGE_DAYS = 90

# 대화 내용을 볼 수 있는 역할. VIEWER 는 빠져 있다 — 목록·상세는 403 이고 요약만 허용된다(G2).
READ_ROLES = frozenset({"ADMIN", "EDITOR", "OPERATOR"})
# 내보내기는 데이터를 파일로 빼가는 행위라 ADMIN 만(activity/exports 와 같은 기준).
EXPORT_ROLES = frozenset({"ADMIN"})

# 어휘는 전부 프론트 타입이 정본이다. 여기서 새 값을 만들면 화면 필터가 조용히 안 걸린다.
STATUSES = frozenset({"NORMAL", "OUT_OF_SCOPE", "FAILED"})   # logs/api.ts LogStatus
INTENTS = frozenset({"informational", "civil_petition"})     # query_planner.PlanItem.intent
FEEDBACKS = frozenset({"up", "down", "none"})                # logs/api.ts LogFilters.feedback
TRIAGES = frozenset({"NONE", "IN_REVIEW", "RESOLVED"})       # codes.ts TriageStatus (CM-DF-002 06절)

# 2026-08-12 실측: 기존 238행이 **전부** status="success" 다. rag_logger 의 기본값이 그 문자열
# 하나뿐이었고 다른 값을 넘기는 호출부가 없었기 때문이다(실패 기록 자체가 없었다).
#
# 화면은 이 값을 모른다 — LOG_STATUS_LABEL[status] 가 undefined 가 되어 상태 칩이 통째로
# 빈 채로 뜬다. 실패 기록 작업이 새 어휘를 쓰기 시작해도 **이미 쌓인 행은 영원히 "success"**
# 라, 읽는 쪽에서 옮겨 준다. UPDATE 마이그레이션 대신 읽기 매핑을 택한 이유는 되돌리기
# 쉽고(이 줄만 지우면 된다) 원본 기록을 건드리지 않아서다.
LEGACY_STATUS = {"success": "NORMAL"}


def _status_out(value: Optional[str]) -> Optional[str]:
    """저장값 -> 화면 어휘. 옛 "success" 를 NORMAL 로 옮긴다."""
    return LEGACY_STATUS.get(value, value)

SORT_COLUMNS = {"occurred_at": rag_runs.c.created_at}

# 상세의 '답변 미리보기' 길이. 전체 펼치기는 추가 호출 없는 클라이언트 토글이라(G4)
# preview 와 full 을 한 응답에 함께 담고, 자르는 기준만 여기서 정한다.
PREVIEW_CHARS = 120


# ---------------------------------------------------------------- KST · 파싱

def _to_kst_iso(value: Optional[datetime]) -> Optional[str]:
    """timestamptz -> +09:00 ISO 문자열. 모듈 주석의 '출력' 쪽이다."""
    if value is None:
        return None
    # 드라이버·컬럼 설정에 따라 naive 로 돌아오는 경우는 UTC 로 본다(컬럼이 timestamptz 라
    # 저장된 값 자체는 UTC 기준이다). admin_activity.py 와 같은 처리.
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(KST).isoformat()


def _kst_day_start(day: date) -> datetime:
    """KST 날짜의 00:00. 비교는 UTC 로 저장된 컬럼과 직접 한다."""
    return datetime(day.year, day.month, day.day, tzinfo=KST)


def _parse_kst_date(raw) -> date:
    """'YYYY-MM-DD' -> date. 형식이 틀리면 400 이다.

    str() 로 눕히는 이유는 내보내기 경로 때문이다 — POST /exports 의 본문은 JSON 이라
    `{"from": 20260804}` 처럼 문자열이 아닌 값이 올 수 있고, 그대로 date.fromisoformat 에
    넣으면 400 이 아니라 TypeError -> 500 이 난다(admin_activity._parse_kst_date 와 같은 사정).
    """
    try:
        return date.fromisoformat(str(raw))
    except (TypeError, ValueError) as exc:
        raise BadRequestError("기간 형식이 올바르지 않습니다. YYYY-MM-DD 로 보내 주세요.") from exc


def _resolve_range(from_raw, to_raw) -> tuple[Optional[date], Optional[date]]:
    """from·to 를 검증해 돌려준다. 어긋난 기간은 400 으로 막는다 — 조용히 잘라내지 않는다.

    90일을 넘겼을 때 90일치만 돌려주면 화면은 그 사실을 알 수 없어 '전체를 봤다'고
    착각한다. 감사 성격의 화면에서는 이게 제일 나쁜 실패 방식이라 거절하는 쪽을 택했다.
    """
    start = _parse_kst_date(from_raw) if from_raw else None
    end = _parse_kst_date(to_raw) if to_raw else None
    if start and end:
        if start > end:
            raise BadRequestError("시작일이 종료일보다 늦습니다.")
        # 화면의 daysBetween 과 같은 셈(양끝 포함).
        if (end - start).days + 1 > MAX_RANGE_DAYS:
            raise BadRequestError(f"조회 기간은 최대 {MAX_RANGE_DAYS}일까지 지정할 수 있습니다.")
    return start, end


def _order_by(sort: str):
    """정렬 파싱. 화면은 항상 최신순만 쓰지만, 임의 컬럼을 허용하면 인덱스 없는 컬럼으로
    풀스캔이 걸리므로 목록을 닫아 둔다(admin_activity._order_by 와 같은 이유)."""
    field, separator, direction = sort.partition(":")
    if separator != ":" or field not in SORT_COLUMNS or direction not in {"asc", "desc"}:
        raise BadRequestError("지원하지 않는 정렬 조건입니다.")
    column = SORT_COLUMNS[field]
    return column.desc() if direction == "desc" else column.asc()


def _escape_like(value: str) -> str:
    """ILIKE 와일드카드를 검색어가 아니라 일반 문자로 취급한다."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _require(admin: CurrentAdmin, roles: frozenset, what: str) -> None:
    """역할 게이트. 화면에서 버튼을 숨기는 건 UX 편의일 뿐이고 최종 판정은 여기서 한다."""
    if admin.role not in roles:
        raise ForbiddenError(
            f"{what}에는 {' 또는 '.join(sorted(roles))} 권한이 필요합니다. "
            f"현재 권한은 {admin.role}입니다.")


# ---------------------------------------------------------------- 쿼리 빌더

def build_log_queries(*, q: str, status: str, intent: str, feedback: str,
                      from_raw, to_raw, sort: str, triage: str = ""):
    """목록·total·내보내기가 **같은 조건**을 쓰도록 한 곳에서 만든다.

    한쪽에만 조건이 붙으면 '3건인데 5페이지'처럼 개수와 목록이 어긋나고, 내보내기에서는
    화면에 보이는 건수와 접수증의 건수가 달라진다. 활동 로그·지식베이스 목록이 같은 이유로
    빌더를 공유하고 있어서(admin_activity.build_activity_event_queries) 같은 모양을 따른다.

    feedback 은 LEFT JOIN 이다 — 피드백이 없는 질의도 목록에 나와야 하고, `feedback=none`
    필터는 그 '없음' 자체를 조건으로 쓴다.
    """
    joined = rag_runs.outerjoin(
        feedback_table, rag_runs.c.request_id == feedback_table.c.request_id)

    # 🔴 request_id 가 없는 행은 목록에 넣지 않는다(2026-08-12 실측 238건 중 147건).
    # CLI(src/pipeline.py)·Streamlit 경로가 request_id 없이 로깅해서 생긴 행들이다. 이 값이
    # 없으면 상세(GET /{request_id})도, 피드백 연결도 불가능해서 화면에서 행을 눌러도 할 수
    # 있는 게 없다. 목록에 두면 '열리지 않는 행'이 절반을 넘는다.
    # 되살리려면 이 한 줄을 지운다 — 그때는 프론트에 '상세 없는 행' 처리를 먼저 정해야 한다.
    filters = [rag_runs.c.request_id.isnot(None), rag_runs.c.request_id != ""]

    start, end = _resolve_range(from_raw, to_raw)
    if start:
        filters.append(rag_runs.c.created_at >= _kst_day_start(start))
    if end:
        # to 당일을 통째로 포함시킨다(모듈 주석 참고).
        filters.append(rag_runs.c.created_at < _kst_day_start(end) + timedelta(days=1))

    if q:
        # 검색 대상은 질문뿐이다. 답변까지 넓히면 근거 문서에 흔한 낱말(예: '예금보험금')로
        # 사실상 전건이 걸려 필터 구실을 못 한다.
        filters.append(rag_runs.c.question.ilike(f"%{_escape_like(q)}%", escape="\\"))
    if status:
        if status not in STATUSES:
            raise BadRequestError("지원하지 않는 상태 값입니다.")
        # 옛 저장값(LEGACY_STATUS)도 같은 필터에 걸려야 한다 — 안 그러면 화면에서
        # '정상'을 골랐을 때 기존 기록이 통째로 사라진다.
        legacy = [old for old, new in LEGACY_STATUS.items() if new == status]
        filters.append(rag_runs.c.status.in_([status, *legacy]))
    if intent:
        if intent not in INTENTS:
            raise BadRequestError("지원하지 않는 intent 값입니다.")
        filters.append(rag_runs.c.intent == intent)
    if triage:
        # 처리 상태(2026-08-18). 'OPEN' 은 RESOLVED 가 아닌 것(NONE·IN_REVIEW) — 화면의
        # '미처리' 선택지이자 대시보드 할 일 카드가 넘기는 값이다. 카드 건수와 같은 조건이라야
        # 눌렀을 때 같은 목록이 열린다.
        if triage == "OPEN":
            filters.append(rag_runs.c.triage != "RESOLVED")
        elif triage in TRIAGES:
            filters.append(rag_runs.c.triage == triage)
        else:
            raise BadRequestError("triage 값이 올바르지 않습니다.")
    if feedback:
        if feedback not in FEEDBACKS:
            raise BadRequestError("지원하지 않는 피드백 값입니다.")
        if feedback == "none":
            filters.append(feedback_table.c.request_id.is_(None))
        else:
            filters.append(feedback_table.c.vote == feedback)

    rows = (
        select(
            rag_runs.c.request_id,
            rag_runs.c.created_at,
            rag_runs.c.question,
            rag_runs.c.intent,
            rag_runs.c.status,
            rag_runs.c.total_latency_ms,
            rag_runs.c.observation,
            rag_runs.c.triage,
            feedback_table.c.vote,
        )
        .select_from(joined)
        .where(*filters)
        .order_by(_order_by(sort))
    )
    total = select(func.count()).select_from(joined).where(*filters)
    return rows, total


def _row_to_log(row) -> dict:
    """한 행 -> 화면 계약(ConversationLogRow).

    source_count 는 rag_runs.observation 에서 온다(2026-08-14 신설). 관측 이전에 쌓인 행은
    observation 이 NULL 이라 그대로 None 이다 — 0 을 넣으면 '출처가 하나도 없었다'는 사실처럼
    읽힌다. triage 는 rag_runs.triage(2026-08-18 신설) — 없던 시절 행은 NONE 이다.
    """
    return {
        "request_id": row.request_id or "",
        # 🔴 KST(+09:00) ISO. UTC 로 주면 화면의 '오늘'이 9시간 어긋난다.
        "occurred_at": _to_kst_iso(row.created_at) or "",
        # 마스킹 4종(주민·전화·카드·이메일)은 api/masking.py 가 조회 시점에 적용한다(2026-08-14 구현).
        # 호출 지점만 남겨 두어, 그 스텁이 채워지면 전 경로가 함께 바뀐다.
        "question_masked": mask_text(row.question) or "",
        "intent": row.intent,
        "status": _status_out(row.status),
        "feedback": row.vote,
        "source_count": observation.summarize(getattr(row, "observation", None))["source_count"],
        "latency_s": round(row.total_latency_ms / 1000, 2) if row.total_latency_ms else None,
        "triage": getattr(row, "triage", None) or "NONE",
    }


# ---------------------------------------------------------------- 엔드포인트
#
# ⚠️ /summary 는 /{request_id} 보다 **먼저** 선언해야 한다. 뒤에 두면 "summary" 가
#    request_id 로 잡혀 상세 핸들러가 먼저 먹고 404 를 돌려준다.

@router.get("", response_model=ConversationLogList)
def list_logs(
    admin: CurrentAdmin,
    db: DbSession,
    q: str = "",
    status: str = "",
    intent: str = "",
    feedback: str = "",
    triage: str = "",
    # 화면은 기간 선택을 KST 날짜로 환산해 보낸다(logs/api.ts periodRange).
    from_: Optional[str] = Query(default=None, alias="from"),
    to: Optional[str] = None,
    sort: str = "occurred_at:desc",
    page: int = Query(default=1, ge=1),
    size: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """대화 로그 목록 -> {items, total, page, size}. page 는 1-base."""
    _require(admin, READ_ROLES, "대화 로그 조회")
    rows_query, total_query = build_log_queries(
        q=q.strip(), status=status.strip(), intent=intent.strip(),
        feedback=feedback.strip(), from_raw=from_, to_raw=to, sort=sort,
        triage=triage.strip(),
    )
    total = db.execute(total_query).scalar_one()
    rows = db.execute(rows_query.offset((page - 1) * size).limit(size)).all()
    return {
        "items": [_row_to_log(row) for row in rows],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/summary", response_model=LogSummary)
def logs_summary(admin: CurrentAdmin, db: DbSession):
    """오늘(KST) 집계. **목록 필터와 무관하게** 항상 오늘 기준이다(G1: '항상 오늘 기준').

    VIEWER 도 볼 수 있는 유일한 대화 로그 엔드포인트다 — 숫자에는 대화 내용이 없다.
    """
    del admin  # 인증은 라우터 의존성이 했고, 집계에는 사용자별 데이터가 없다.

    now = datetime.now(timezone.utc)
    today_start = _kst_day_start(now.astimezone(KST).date())
    # 목록과 **같은 모집단**을 세야 한다 — request_id 없는 행(CLI·Streamlit 기록)을 여기서만
    # 세면 '오늘 3건'인데 목록은 0건이 되어, 운영자가 사라진 3건을 찾게 된다.
    today = and_(rag_runs.c.created_at >= today_start,
                 rag_runs.c.request_id.isnot(None),
                 rag_runs.c.request_id != "")

    # 상태 3종을 한 번에 센다 — 질의 4번을 왕복하는 것보다 낫고, 합계가 부분합과
    # 어긋날 여지도 없앤다.
    counts = db.execute(
        select(rag_runs.c.status, func.count())
        .where(today).group_by(rag_runs.c.status)
    ).all()
    # 옛 저장값을 화면 어휘로 옮겨 합친다(LEGACY_STATUS). 매핑 없이 세면 오늘 기록이
    # 전부 어느 칸에도 안 들어가 '오늘 0건'처럼 보인다.
    by_status: dict = {}
    for status, count in counts:
        by_status[_status_out(status)] = by_status.get(_status_out(status), 0) + count

    votes = db.execute(
        select(feedback_table.c.vote, func.count())
        .select_from(rag_runs.join(
            feedback_table, rag_runs.c.request_id == feedback_table.c.request_id))
        .where(today).group_by(feedback_table.c.vote)
    ).all()
    by_vote = {vote: count for vote, count in votes}

    return {
        "total": sum(by_status.values()),
        "normal": by_status.get("NORMAL", 0),
        "out_of_scope": by_status.get("OUT_OF_SCOPE", 0),
        "failed": by_status.get("FAILED", 0),
        "feedback_up": by_vote.get("up", 0),
        "feedback_down": by_vote.get("down", 0),
    }


def _langfuse(trace_id: Optional[str], host: str) -> Optional[dict]:
    """rag_runs.trace_id + 설정 호스트 -> {id, url}. 프론트가 호스트를 알 이유가 없어 서버가
    완성 URL 을 만든다(G5). trace_id 가 없으면 링크할 대상이 없어 langfuse 자체를 null 로,
    trace_id 는 있으나 호스트 설정이 없으면 url=null(화면은 id 만 글로 보여준다)."""
    if not trace_id:
        return None
    if not host:
        return {"id": trace_id, "url": None}
    return {"id": trace_id, "url": f"{host.rstrip('/')}/trace/{trace_id}"}


@router.get("/{request_id}", response_model=ConversationLogDetail)
def get_log(request_id: str, request: Request, admin: CurrentAdmin, db: DbSession,
            settings: SettingsDep):
    """질의 1건의 상세 = 목록 행 + 분류·피드백·오류.

    request_id 는 UUID 가 아니라 문자열 컬럼이다(rag_runs.request_id). 형식 검사를 하지
    않고 그대로 조회한다 — 활동 로그의 event_id 와 달리 UUID 캐스팅이 없어 500 위험이 없다.
    """
    _require(admin, READ_ROLES, "대화 로그 조회")
    # CM-DF-002 07절 이벤트 사전의 '대화 로그 조회'(대상: 대화 (request_id)) — 상세 열람만
    # 기록한다. 목록 조회까지 적으면 폴링·페이지 이동으로 원장이 뒤덮인다(admin_drafts 와 동일 판단).
    write_activity_log(db, request, actor=admin.email, actor_role=admin.role,
                       action="대화 로그 조회", target=f"대화 ({request_id})")

    row = db.execute(
        select(
            rag_runs.c.request_id,
            rag_runs.c.created_at,
            rag_runs.c.question,
            rag_runs.c.answer,
            rag_runs.c.intent,
            rag_runs.c.question_type,
            rag_runs.c.status,
            rag_runs.c.failure_stage,
            rag_runs.c.root_cause,
            rag_runs.c.total_latency_ms,
            rag_runs.c.trace_id,
            rag_runs.c.observation,
            rag_runs.c.triage,
            feedback_table.c.vote,
            feedback_table.c.reason_codes,
            feedback_table.c.comment,
            feedback_table.c.created_at.label("feedback_at"),
        )
        .select_from(rag_runs.outerjoin(
            feedback_table, rag_runs.c.request_id == feedback_table.c.request_id))
        .where(rag_runs.c.request_id == request_id)
    ).first()
    if row is None:
        raise NotFoundError("대화 기록을 찾을 수 없습니다.")

    answer = mask_text(row.answer) or ""
    preview = answer if len(answer) <= PREVIEW_CHARS else answer[:PREVIEW_CHARS] + "…"

    return {
        **_row_to_log(row),
        "classification": {
            "intent": row.intent,
            # 컬럼은 있지만 웹 경로가 항상 None 을 넘긴다(api/rag/answer.py:260 — "검색 라우팅
            # 내부에서만 쓰고 응답 경로엔 노출되지 않는다"). 2026-08-12 실측 238건 중 91건이 NULL.
            "question_type": row.question_type,
            # ⚠️ business_function 은 업무 분류가 코드에서 비활성이라 여전히 원천이 없다.
            "business_function": None,
            # 아래 3개는 rag_runs.observation 에서 온다(2026-08-14). 관측 이전 행은 None 유지.
            **{k: v for k, v in observation.summarize(row.observation).items()
               if k in ("source_used", "marker", "normalized")},
        },
        # 관리자가 '왜 이렇게 답했는지'를 보는 근거 — 하위 질문별 검색 상위 청크와 판정.
        "observation": row.observation,
        # trace_id + 설정 호스트로 완성 URL 을 만든다(G5). 호스트가 비면 {id, url:null},
        # trace_id 자체가 없으면 langfuse=null. API_LANGFUSE_HOST 로 켠다(api/config.py).
        "langfuse": _langfuse(row.trace_id, settings.langfuse_host),
        "total_latency_ms": row.total_latency_ms,
        "answer_masked_preview": preview,
        "answer_masked_full": answer,
        "feedback_detail": None if row.vote is None else {
            "vote": row.vote,
            "at": _to_kst_iso(row.feedback_at) or "",
            # 화면은 사람이 읽는 한 줄을 기대한다. 코드 배열을 그대로 이어 붙여 두고,
            # 라벨 사전(codes.ts ReasonCode)은 프론트가 갖고 있다.
            "reason_label": ", ".join(row.reason_codes or []),
            # 자유 의견은 개인정보가 가장 잘 섞이는 자유 텍스트다 — 질문·답변과 같은 마스킹을 거친다
            "comment": mask_text(row.comment) or "",
        },
        # 실패 건에만 싣는다. code·meaning·user_message·auto_retry·fallback 은 rag_runs 에
        # 원천이 없어 비워 둔다 — 처리 방침은 별도 조사에서 정한다(모듈 주석).
        "error": None if _status_out(row.status) != "FAILED" else {
            "code": "",
            "meaning": "",
            "user_message": "",
            "auto_retry": "",
            "fallback": "",
            "failure_stage": row.failure_stage,
            "root_cause": row.root_cause,
        },
    }


@router.patch("/{request_id}", response_model=ConversationLogRow)
def patch_log(request_id: str, body: dict, request: Request, admin: CurrentAdmin, db: DbSession):
    """처리 상태 변경(AD-005 [처리 완료 표시]). 프론트 계약(logs/api.ts resolveLog):
    PATCH {triage, reason}. 화면은 오래전부터 이 요청을 보내고 있었고 백엔드가 받는 곳이
    없어 405 였다 — 관리자 유저플로우 설계(2026-08-18) 미구현 6건 중 1순위.

    이 값이 바뀌어야 대시보드 '나쁨 평가' 할 일 건수가 줄고, 목적지 화면의 되돌아가기
    띠에서 [처리 완료]를 눌러도 루프가 닫힌다. 되돌리기(→NONE)도 같은 경로로 허용한다 —
    잘못 누른 완료를 풀 수 없으면 건수가 거짓이 된다.
    """
    _require(admin, READ_ROLES, "대화 로그 처리 상태 변경")
    triage = str(body.get("triage") or "").strip()
    if triage not in TRIAGES:
        raise BadRequestError("triage 값이 올바르지 않습니다(NONE·IN_REVIEW·RESOLVED).")
    reason = str(body.get("reason") or "").strip()
    if triage == "RESOLVED" and not reason:
        raise BadRequestError("처리 완료에는 사유가 필요합니다.")

    row = db.execute(
        select(rag_runs.c.request_id, rag_runs.c.triage)
        .where(rag_runs.c.request_id == request_id)).first()
    if row is None:
        raise NotFoundError("대화 기록을 찾을 수 없습니다.")

    now = datetime.now(timezone.utc)
    db.execute(update(rag_runs).where(rag_runs.c.request_id == request_id).values(
        triage=triage,
        triaged_by=admin.email if triage != "NONE" else None,
        triaged_at=now if triage != "NONE" else None))
    db.commit()
    write_activity_log(db, request, actor=admin.email, actor_role=admin.role,
                       action="대화 로그 처리 상태 변경", target=f"대화 ({request_id})",
                       reason=reason,
                       before_value=row.triage or "NONE", after_value=triage)

    fresh = db.execute(
        select(rag_runs.c.request_id, rag_runs.c.created_at, rag_runs.c.question,
               rag_runs.c.intent, rag_runs.c.status, rag_runs.c.total_latency_ms,
               rag_runs.c.observation, rag_runs.c.triage, feedback_table.c.vote)
        .select_from(rag_runs.outerjoin(
            feedback_table, rag_runs.c.request_id == feedback_table.c.request_id))
        .where(rag_runs.c.request_id == request_id)).first()
    return _row_to_log(fresh)


@router.post("/exports", response_model=LogExportResponse)
def export_logs(body: dict, request: Request, admin: CurrentAdmin, db: DbSession):
    """내보내기 접수. 데이터를 파일로 빼가는 행위라 ADMIN 만 할 수 있다.

    지금은 대상 건수를 세어 접수증만 돌려준다 — 실제 파일 생성·다운로드는 별도 작업이다
    (형식·파일명·건수 상한이 아직 정해지지 않았다, L6). 화면도 접수 후 토스트만 띄우고
    파일을 기다리지 않는다. activity/exports 와 같은 방식이다.

    ⚠️ activity/exports 와 달리 `reason` 을 요구하지 않는다 — 프론트의 exportLogs 가
    reason 을 보내지 않기 때문이다(logs/api.ts). 요구하면 화면이 400 만 받는다.
    request_id(멱등키)는 apiRequest 가 모든 쓰기 요청에 자동으로 넣어 준다(C2).
    """
    _require(admin, EXPORT_ROLES, "대화 로그 내보내기")
    # 본문을 dict 로 받는 이유: LogExportRequest 에 request_id 필드가 없어서(화면 계약에
    # 없다 — apiRequest 가 모든 쓰기 요청에 자동으로 넣는 공통 멱등키다) 모델로 바로 받으면
    # 그 값이 버려진다. 멱등키는 원본에서 꺼내고, 필터만 모델로 검증한다.
    if not str(body.get("request_id") or "").strip():
        raise BadRequestError("request_id가 필요합니다.")
    filters = LogExportRequest.model_validate(body)

    # 화면에 보이는 현재 필터 결과가 대상이다(G6). 목록과 같은 빌더를 써서 두 건수가
    # 어긋나지 않게 한다.
    _, total_query = build_log_queries(
        q=filters.q.strip(),
        status=filters.status.strip(),
        intent=filters.intent.strip(),
        feedback=filters.feedback.strip(),
        from_raw=filters.from_ or None,
        to_raw=filters.to or None,
        sort="occurred_at:desc",
    )
    estimated_rows = db.execute(total_query).scalar_one()

    export_id = f"exp_{uuid.uuid4().hex[:12]}"
    logger.info("대화 로그 내보내기 접수: %s (%s건, 요청자 %s)",
                export_id, estimated_rows, admin.email)
    # PRD-03 AD-005 감사: "조회·검색·내보내기 자체를 활동 로그 이벤트로 기록" — activity/exports
    # 와 동일한 접수 기록. reason 은 화면 계약에 없어 비운다(위 docstring).
    write_activity_log(db, request, actor=admin.email, actor_role=admin.role,
                       action="대화 로그 내보내기",
                       target=f"대화 로그 · 현재 필터 ({export_id})",
                       detail={"export_id": export_id, "estimated_rows": estimated_rows,
                               "filter": {k: v for k, v in body.items() if k != "request_id"}})
    return {"export_id": export_id, "status": "QUEUED", "estimated_rows": estimated_rows}
