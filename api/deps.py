"""라우터가 Depends() 로 받아 쓰는 공통 자원 — 설정, DB 세션, request_id.

## Depends 를 왜 쓰나

라우터 안에서 직접 get_settings() 나 get_session() 을 부르면 동작은 한다. 그런데
Depends 로 받으면 두 가지를 얻는다.

1. 정리(cleanup)를 FastAPI가 책임진다. DB 세션은 yield 뒤 코드가 응답이 끝난 다음
   반드시 실행되므로 commit/rollback/close 를 빠뜨릴 수 없다.
2. 테스트에서 app.dependency_overrides[get_db] = ... 로 통째로 갈아끼울 수 있다.
   라우터 안에서 직접 부르면 이게 불가능하다.

## 타입 별칭(Annotated)

    def handler(db: DbSession): ...

처럼 쓰라고 아래에서 Annotated 별칭을 만들어 둔다. 매번
`db: Session = Depends(get_db)` 라고 쓰는 것보다 짧고, 의존성을 바꿀 때 한 곳만 고친다.
"""
import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import Depends, Request
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from api.config import Settings, get_settings
from api.errors import ForbiddenError, UnauthorizedError

# src/db.py 를 flat import 한다 — api/__init__.py 가 sys.path 에 src/ 를 넣어줘서
# 가능하다. src/ 쪽 import 스타일을 그대로 따르는 것이라 의도된 모양이다.
from db import get_session
from schema_admin import admin_accounts, admin_activity_logs, admin_sessions

logger = logging.getLogger(__name__)


def get_settings_dep() -> Settings:
    """설정 의존성.

    config.get_settings() 를 그대로 쓰지 않고 한 겹 감싸는 이유는 오직 테스트다 —
    dependency_overrides 의 키로 쓸 함수가 필요하다. 값 자체는 lru_cache 된 같은 객체다.
    """
    return get_settings()


def get_db():
    """요청 하나당 DB 세션 하나.

    src/db.py 의 get_session() 은 이미 contextmanager 라, 블록을 빠져나갈 때
    commit(정상) 또는 rollback(예외) 후 close 까지 한다. 여기서는 그 블록을
    "요청 처리 전체"로 늘리기만 한다 — yield 아래 줄은 응답이 끝난 뒤 실행되고,
    핸들러에서 예외가 나면 FastAPI 가 그 예외를 이 제너레이터 안으로 다시 던져줘서
    get_session() 의 rollback 이 정상적으로 걸린다.

    def(async def 아님)로 선언한 것도 의도적이다. SQLAlchemy 동기 세션은 블로킹이라,
    async def 로 두면 이벤트 루프를 막는다. 동기 함수로 두면 FastAPI 가 알아서
    스레드풀에서 돌린다.

    주의: 챗봇 답변 경로는 이 의존성이 필요 없다. src/rag_logger.py 가 자체적으로
    (실패해도 답변을 막지 않는 방식으로) 로깅하기 때문이다. DB 가 실제로 필요한
    관리자용 라우터에서만 쓸 것.
    """
    with get_session() as session:
        yield session


def get_request_id(request: Request) -> Optional[str]:
    """미들웨어가 scope 에 넣어둔 요청 id. 응답 본문에 request_id 를 함께 실어
    보내야 하는 라우터에서 쓴다(오류 응답은 errors.py 가 알아서 채운다)."""
    return getattr(request.state, "request_id", None)


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbSession = Annotated[Session, Depends(get_db)]
RequestId = Annotated[Optional[str], Depends(get_request_id)]


# ---------------------------------------------------------------- 관리자 인증
#
# 세션은 httpOnly 쿠키 하나로 표현한다(프론트 lib/api/client.ts 가 credentials:'include'
# 로 보낸다). 쿠키에 담기는 건 토큰 원문이고, DB(admin_sessions.id)에 남는 건 그 sha256
# 해시다 — 이 비대칭이 핵심이다. 같은 값을 양쪽에 두면 DB 가 새는 순간 모든 세션이 그대로
# 탈취된다.
#
# 3타이머(절대 8h · 유휴 30분 · 재확인 30분)는 admin_sessions 의 3필드에서 계산한다
# (CM-DF-003 §04 가 정한 컬럼 구성 그대로다. src/schema_admin.py 참고).

COOKIE_NAME = "kdic_admin_session"
ABSOLUTE_WINDOW = timedelta(hours=8)
IDLE_WINDOW = timedelta(minutes=30)
REAUTH_WINDOW = timedelta(minutes=30)

# 폴링 표시 헤더. 프론트가 진행 상태·세션 확인처럼 '사람의 활동이 아닌' 요청에 붙인다
# (lib/api/client.ts POLL_HEADER). 서버는 이 요청을 유휴 타이머 갱신에서 뺀다.
POLL_HEADER = "X-Poll"

# 계정 상태 중 로그인·세션 유지가 허용되는 값. schema_admin.py 의 4종(활성/비활성/초대됨/잠김)
# 중 하나다 — 문자열이 한 글자만 달라도 "로그인은 되는데 다음 요청부터 401" 이 되므로 상수로 둔다.
ACTIVE_STATUS = "활성"


def new_session_token() -> str:
    """쿠키에 실어 보낼 세션 토큰 원문. 로그인할 때만 만든다."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """쿠키 원문 -> DB 에 저장할 값. bcrypt 가 아니라 sha256 인 이유는 이 값이 사람이 고른
    비밀번호가 아니라 256비트 난수라서다 — 사전 공격 대상이 아니므로 느린 해시가 필요 없고,
    매 요청 검증에 쓰이니 빨라야 한다."""
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class AdminIdentity:
    """인증된 관리자 1명 + 그 세션. 라우터는 이 값만 보고 응답을 만든다."""
    session_id: str
    account_id: str
    email: str
    name: str
    role: str
    session_started_at: datetime
    last_activity_at: datetime
    last_auth_at: datetime


def get_current_admin(request: Request, db: DbSession) -> AdminIdentity:
    """쿠키 -> 세션 조회 -> 3타이머 검사 -> (폴링이 아니면) 유휴 타이머 갱신.

    /api/admin/* 라우터에 router-level dependency 로 걸면 엔드포인트마다 인증 코드를
    반복하지 않는다. 화면에서 버튼을 숨기는 건 UX 편의일 뿐이고 최종 판정은 여기서 한다.

    401 을 쓰는 게 맞는 유일한 자리다 — 프론트는 401 을 보면 경로를 보지 않고
    expireSession() 해서 로그인 화면으로 보낸다(lib/api/client.ts:107). 인증이 필요한
    관리자 API 에서는 그게 정확히 원하는 동작이다. 반대로 '비밀번호가 틀렸다'는 401 이
    아니라 403 이다(routers/admin_auth.py 참고).
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise UnauthorizedError("로그인이 필요합니다.")

    row = db.execute(
        select(
            admin_sessions.c.id.label("session_id"),
            admin_sessions.c.session_started_at,
            admin_sessions.c.last_activity_at,
            admin_sessions.c.last_auth_at,
            admin_accounts.c.id.label("account_id"),
            admin_accounts.c.email,
            admin_accounts.c.name,
            admin_accounts.c.role,
            admin_accounts.c.status,
        )
        .join_from(admin_sessions, admin_accounts,
                   admin_sessions.c.account_id == admin_accounts.c.id)
        .where(admin_sessions.c.id == hash_token(token),
               # 로그아웃·강제 종료된 세션은 행이 남아 있어도 무효다.
               admin_sessions.c.revoked_at.is_(None))
    ).first()

    # 세션이 없는 경우와 계정이 잠긴 경우를 같은 응답으로 묶는다 — 어느 쪽이든 화면이
    # 할 일은 '로그인 화면으로 되돌리기' 하나뿐이라 구분해 봐야 쓸 데가 없다.
    if row is None or row.status != ACTIVE_STATUS:
        raise UnauthorizedError("세션이 만료되었습니다. 다시 로그인해 주세요.")

    now = datetime.now(timezone.utc)
    if (now >= row.session_started_at + ABSOLUTE_WINDOW
            or now >= row.last_activity_at + IDLE_WINDOW):
        # 만료된 세션은 즉시 무효로 박아 둔다. 안 그러면 같은 쿠키로 계속 조회가 일어나고,
        # 시각 비교에만 의존하면 서버 시계가 흔들릴 때 되살아날 수 있다.
        db.execute(update(admin_sessions)
                   .where(admin_sessions.c.id == row.session_id)
                   .values(revoked_at=now))
        db.commit()
        raise UnauthorizedError("세션이 만료되었습니다. 다시 로그인해 주세요.")

    # 🔴 폴링은 활동이 아니다. 프론트는 GET /api/admin/session 을 항상 X-Poll 로 부르는데
    # (app/session.ts loadSession), 여기서 유휴를 갱신해 버리면 세션을 확인하는 행위가
    # 곧 활동이 되어 유휴 만료가 영원히 오지 않는다.
    last_activity_at = row.last_activity_at
    if request.headers.get(POLL_HEADER) != "1":
        db.execute(update(admin_sessions)
                   .where(admin_sessions.c.id == row.session_id)
                   .values(last_activity_at=now))
        db.commit()
        last_activity_at = now

    return AdminIdentity(
        session_id=row.session_id,
        account_id=str(row.account_id),
        email=row.email,
        name=row.name,
        role=row.role,
        session_started_at=row.session_started_at,
        last_activity_at=last_activity_at,
        last_auth_at=row.last_auth_at,
    )


CurrentAdmin = Annotated[AdminIdentity, Depends(get_current_admin)]


# ---------------------------------------------------------------- 위험 작업 재인증
#
# 재확인이 필요한 쓰기는 3종이다 — 전체 캐시 비우기 · 권한 변경 · 롤백(A14 확정).
# 프롬프트 게시에는 걸지 않는다(롤백으로 되돌릴 수 있고 게시 후 자동 롤백까지 있다).
#
# 🔴 서버가 독립 검증해야 한다(P5). 프론트도 needsReauth 를 보고 POST /reauth 를 먼저
#    부르지만(access/api.ts runRisky), 그 판정은 클라이언트 코드라 우회할 수 있다. 화면을
#    거치지 않고 위험 API 를 직접 때리면 재확인 없이 통과해 버린다.
#
# ## 다른 트랙이 쓰는 법
#
#     from api.deps import ReauthedAdmin
#
#     @router.put("/ops-policy")
#     def update_ops_policy(me: ReauthedAdmin, ...):   # 만료면 여기 닿기 전에 403
#
# 역할 게이트와 같이 걸 때는 둘 다 본다 — 재인증은 '누구인가'가 아니라 '방금 확인했는가'라
# 서로 대체하지 못한다. 역할 검사는 아직 공통 함수가 없어 각 라우터가 자기 방식으로 한다
# (admin_logs._require · admin_activity 인라인):
#
#     @router.post("/jobs/{job_id}/rollback")
#     def rollback(me: ReauthedAdmin, ...):
#         if me.role != "ADMIN":
#             raise ForbiddenError("긴급 롤백에는 ADMIN 권한이 필요합니다.")
#
# 401 이 아니라 403 인 이유: 프론트는 401 을 보면 경로를 보지 않고 expireSession() 한다
# (lib/api/client.ts:107). 세션은 멀쩡한데 재확인만 만료된 상황에서 401 을 주면 위험 작업을
# 누를 때마다 로그아웃되어, 사용자는 재확인을 할 기회조차 없다.


def reauth_remaining_s(me: AdminIdentity, now: Optional[datetime] = None) -> int:
    """재확인이 유효한 남은 초. 0 이면 재확인이 필요하다.

    GET /api/admin/session 의 reauth_valid_until_s 와 **같은 계산**이어야 한다 — 화면이 그
    값으로 비밀번호 슬롯을 띄울지 정하는데, 서버 판정과 어긋나면 '입력칸이 안 떴는데 403'
    또는 '입력칸이 떴는데 안 물어봄'이 된다.
    """
    now = now or datetime.now(timezone.utc)
    return max(0, int((me.last_auth_at + REAUTH_WINDOW - now).total_seconds()))


def require_reauth(me: CurrentAdmin) -> AdminIdentity:
    """위험 작업 의존성. 마지막 재확인이 30분을 넘겼으면 403 으로 막는다.

    통과한 신원을 그대로 돌려주므로 CurrentAdmin 대신 써도 된다(ReauthedAdmin 별칭).
    """
    if reauth_remaining_s(me) <= 0:
        raise ForbiddenError(
            "보안을 위해 비밀번호를 다시 확인해 주세요.",
            detail=f"reauth expired: {me.email} last_auth_at={me.last_auth_at.isoformat()}")
    return me


ReauthedAdmin = Annotated[AdminIdentity, Depends(require_reauth)]


# ---------------------------------------------------------------- 활동 로그(감사 기록)
#
# "누가 · 언제 · 어떤 작업을 · 무엇에 · 어떤 결과로" 한 행에 담는다(CM-DF-003 §04).
# 추가 전용이고 조인하지 않는다 — 화면(AD-011)이 이 한 행만으로 상세를 그리므로 실행자
# email·역할을 그 시점 값으로 박아 둔다. 계정이 나중에 바뀌거나 지워져도 기록이 안 흔들린다.
#
# 왜 CurrentAdmin 이 아니라 actor 문자열을 받나
#   로그인 실패도 기록 대상인데(감사에서 제일 중요한 축이다) 그 시점엔 인증된 세션이 없다.
#   CurrentAdmin 을 요구하는 모양으로 만들면 실패 경로를 아예 못 적는다.
#
# 최소 구현 범위(2026-08-10): 기록만 한다. 멱등키 중복 방지·재인증 검증·개인정보 마스킹은
# 제외했다. 마스킹은 프론트가 이미 하고 있다(EventDetail.tsx maskIp — 서버가 마스킹해 주면
# 그대로 통과시킨다는 주석). 다만 before_value/after_value 에 비밀번호 해시·세션 토큰 같은
# 비밀값을 넣는 것은 최소 구현에서도 금지다 — 90일 남는 표다.

# action 어휘. 자유 텍스트로 두면 안 된다 — 프론트가 이 문자열을 정규식으로 갈라 '관련 화면
# 이동' 링크를 정한다(EventDetail.tsx NO_LINK / LINKS). 예를 들어 "계정 로그인" 이라고 쓰면
# /권한|계정/ 에 걸려 엉뚱하게 계정 관리 화면으로 링크가 붙는다. 새 어휘는 그 표와 함께 정할 것.
ACTION_LOGIN = "로그인"
ACTION_LOGIN_FAILED = "로그인 실패"
ACTION_LOGOUT = "로그아웃"

# 접근 관리(AD-010) 어휘. 위 표(EventDetail.tsx LINKS)에 대조해 정했다:
#   "계정"·"권한" 이 들어간 셋은 /권한|계정/ 에 걸려 전체 계정 목록으로 간다 — 의도한 이동처다.
#   "임시 잠금" 은 NO_LINK 에 이미 그 문자열이 있어 링크가 붙지 않는다(사전 "연결 없음").
#   비밀번호 계열은 어느 규칙에도 안 걸려 링크가 없다 — 이동할 화면이 실제로 없어 맞다.
ACTION_REAUTH = "비밀번호 재확인"
ACTION_ACCOUNT_INVITED = "계정 초대"
ACTION_ROLE_CHANGED = "권한 변경"            # A7 이 이 표기를 지정했다
ACTION_ACCOUNT_DEACTIVATED = "계정 비활성화"
ACTION_ACCOUNT_LOCKED = "임시 잠금"
ACTION_PASSWORD_CHANGED = "비밀번호 변경"
ACTION_PASSWORD_RESET_REQUESTED = "비밀번호 재설정 요청"
ACTION_PASSWORD_RESET_COMPLETED = "비밀번호 재설정"

# '오늘의 위험 작업'(AD-010) 에 뜨는 행위. 되돌리기 어렵거나 권한·보안을 바꾸는 것들이다.
# 재인증이 필요한 3종(전체 캐시 비우기·권한 변경·롤백)이 출발점이고, 계정 수명주기를 바꾸는
# 행위를 더했다. B·C·D 트랙이 새 위험 행위를 만들면 여기에 문자열을 더하면 화면에 잡힌다.
RISKY_ACTIONS = frozenset({
    ACTION_ROLE_CHANGED,
    ACTION_ACCOUNT_INVITED,
    ACTION_ACCOUNT_DEACTIVATED,
    ACTION_PASSWORD_RESET_COMPLETED,
    "전체 캐시 비우기",      # B 트랙(POST /cache/purge?scope=all)
    "긴급 롤백",             # D 트랙(prompt emergency-rollback) · 본 트랙(jobs/{id}/rollback)
})

# 파이프라인 잡 생성. 재수집·재색인은 검색 결과를 실제로 바꾸는 작업이라 "누가 왜 돌렸는지"가
# 남아야 한다. 값을 아무렇게나 정하면 안 된다 — 화면이 이 문자열을 정규식으로 갈라
# '연결 보기' 이동처를 정한다(EventDetail.tsx LINKS). 파이프라인 규칙은
#   /전체 재수집|선택 재수집|재색인|재적재|파이프라인|작업/
# 이라, 앞의 셋은 그대로 걸리고 나머지 셋은 '작업'을 붙여 같은 화면으로 보낸다.
# JobType 정본은 web/src/lib/codes.ts 이고 admin_pipeline.JOB_TYPES 와 키가 같아야 한다.
ACTION_BY_JOB_TYPE = {
    "FULL_RECRAWL": "전체 재수집",
    "SELECTED_RECRAWL": "선택 재수집",
    "REINDEX": "재색인",
    "RECHUNK": "재청킹 작업",
    "REEMBED": "재임베딩 작업",
    "SMOKE_EVAL": "스모크 평가 작업",
    "CHANGE_DETECT": "변경 감지 작업",   # 액션명에 "작업"이 있어야 활동 로그가 파이프라인 화면으로 라우팅한다
}

# 결과 3종 고정(프론트 목 데이터와 같은 값).
RESULT_SUCCESS = "성공"
RESULT_FAILED = "실패"
RESULT_DENIED = "거부됨"


def client_ip(request: Request) -> Optional[str]:
    """접속 IP. 미들웨어의 요청 제한이 쓰는 규칙과 같아야 해서 판단 기준을 맞춰 둔다
    (api/middleware.py _client_key). X-Forwarded-For 는 프록시 뒤에 있을 때만 믿는다 —
    직접 노출된 서버에서 믿으면 헤더를 위조해 남의 IP 로 기록을 남길 수 있다."""
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def write_activity_log(
    db: Session,
    request: Request,
    *,
    actor: str,
    action: str,
    actor_role: Optional[str] = None,
    target: Optional[str] = None,
    result: str = RESULT_SUCCESS,
    reason: Optional[str] = None,
    before_value: Optional[str] = None,
    after_value: Optional[str] = None,
    detail: Optional[dict] = None,
) -> None:
    """활동 로그 한 행. 키워드 인자로만 받는다 — actor/action/target 이 전부 문자열이라
    위치 인자로 두면 순서가 바뀌어도 아무 데서도 안 걸린다.

    ## 스스로 commit 한다

    호출한 쪽이 곧바로 예외를 던지는 경우가 있어서다(로그인 실패 → 403). 그때 커밋을
    호출자에게 맡기면 get_db 의 rollback 이 걸려 **실패 기록만 쏙 사라진다** — 감사 로그로는
    최악의 동작이다. 성공 경로에서는 본 작업을 commit 한 뒤에 부를 것. 그래야 이 함수의
    commit 이 남의 트랜잭션을 대신 확정하지 않는다.

    ## 실패해도 예외를 올리지 않는다

    로깅 때문에 로그인이 막히면 안 된다(src/rag_logger.py 와 같은 판단). 대신 조용히 넘기지
    말고 logger.exception 으로 스택을 남긴다 — 감사 기록이 빠지는 건 그 자체로 사고다.
    실패한 문장은 세션을 오염시키므로 반드시 rollback 해서 호출자의 후속 쿼리를 살려 둔다.
    """
    try:
        db.execute(insert(admin_activity_logs).values(
            occurred_at=datetime.now(timezone.utc),
            actor=actor,
            actor_role=actor_role,
            action=action,
            target=target,
            result=result,
            reason=reason,
            before_value=before_value,
            after_value=after_value,
            request_id=getattr(request.state, "request_id", None),
            ip=client_ip(request),
            detail=detail,
        ))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("활동 로그 기록 실패(무시하고 계속): action=%s actor=%s", action, actor)
