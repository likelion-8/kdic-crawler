"""관리자 세션 4종 — POST login · GET session · POST session/extend · POST logout (AD-000).

세션은 httpOnly 쿠키 하나다. 발급(login)과 폐기(logout)만 여기서 하고, 매 요청의 검증은
api/deps.py 의 get_current_admin 이 한다.

## 상태코드 — 401 과 403 을 반드시 나눈다

| 상황 | 코드 | 근거 |
|---|---|---|
| 쿠키 없이/만료된 세션으로 관리자 API 호출 | 401 | 프론트가 expireSession() 하고 로그인으로 보낸다. 원하는 동작 |
| 로그인 폼에서 이메일·비밀번호 불일치 | **403** | 401 로 주면 세션 만료로 해석돼, 오타 한 번에 로그아웃된 것처럼 보인다 |

프론트는 상태코드 401 을 보면 **경로를 보지 않고** expireSession() 한다
(web/src/lib/api/client.ts:107). 목(web/src/mocks/handlers/admin.ts:162)이 로그인 실패에
401 을 주고 있는데 **목이 틀렸다** — 여기를 목에 맞추지 말 것
(docs/backend-structure.md §3 함정 #1).

## sync def 인 이유

DB 접근(SQLAlchemy 동기 세션)이 블로킹이라 async def 로 두면 이벤트 루프를 막는다.
평범한 def 로 두면 FastAPI 가 스레드풀에서 돌린다(api/deps.py get_db 주석과 같은 이유).
"""
import hashlib
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import APIRouter, Query, Request, Response
from sqlalchemy import func, insert, select, update

from api.deps import (ABSOLUTE_WINDOW, ACTION_ACCOUNT_DEACTIVATED,
                      ACTION_ACCOUNT_INVITED, ACTION_ACCOUNT_LOCKED,
                      ACTION_LOGIN, ACTION_LOGIN_FAILED, ACTION_LOGOUT,
                      ACTION_PASSWORD_CHANGED, ACTION_PASSWORD_RESET_COMPLETED,
                      ACTION_PASSWORD_RESET_REQUESTED, ACTION_REAUTH,
                      ACTION_ROLE_CHANGED, ACTIVE_STATUS, COOKIE_NAME,
                      IDLE_WINDOW, REAUTH_WINDOW, RESULT_FAILED, CurrentAdmin,
                      DbSession, SettingsDep, client_ip, hash_token,
                      new_session_token, write_activity_log)
from api.errors import BadRequestError, ForbiddenError, GoneError, LockedError, NotFoundError
from api.schemas.admin import (AccountCreateRequest, AccountList,
                               AccountPatchRequest, AccountRow, ExtendResponse,
                               LockedAccount, LoginFailureList, LoginFailureRow,
                               LoginRequest, LoginResponse, MyPermissions,
                               PasswordChangeRequest,
                               PasswordResetConfirmRequest, PasswordResetRequest,
                               ReauthRequest, ReauthResponse, RoleDefinition,
                               SecuritySummary, SessionResponse)
# src/schema_admin.py (flat import — api/__init__.py 가 sys.path 에 src/ 를 넣어준다)
from schema_admin import (admin_accounts, admin_login_failures, admin_sessions,
                          password_reset_tokens)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin-auth"])


KST = timezone(timedelta(hours=9))

# 임시 잠금(A2·A12). 최근 LOCKOUT_WINDOW 안에 LOCKOUT_THRESHOLD 번 실패하면 LOCKOUT_MINUTES 동안
# 막는다. 창과 잠금 길이를 같게 둔 이유: 잠금이 풀리는 시점이면 그 실패들도 창 밖으로 나가
# 있어서, 한 번 더 틀렸다고 즉시 다시 잠기지 않는다(사용자가 한 번은 다시 시도할 수 있다).
LOCKOUT_THRESHOLD = 5
LOCKOUT_MINUTES = 10
LOCKOUT_WINDOW = timedelta(minutes=LOCKOUT_MINUTES)

# 비밀번호 정책. 문구 정본은 화면이다 — PasswordChangeModal.tsx:24 / PasswordResetPanel.tsx:242
# ('10자 이상 · 영문/숫자/특수문자 조합 · 아이디 포함 불가'). 프론트는 길이만 막고 나머지는
# 서버 판정에 맡기므로(그 파일들 주석) 여기가 유일한 실제 게이트다.
#
# ⚠️ '최근 사용한 비밀번호 재사용 불가'는 **직전 1개만** 본다. 이력 표가 없어서다
# (admin_accounts 에 password_hash 한 칸뿐이고 이력 테이블 신설은 이번 범위 밖).
# 화면 문구는 '최근 사용한'이라 N개를 기대하게 하므로, 이력이 필요해지면 그때 표를 만든다.
PASSWORD_MIN_LENGTH = 10
PASSWORD_RULE_MESSAGE = ("비밀번호는 10자 이상이며 영문·숫자·특수문자를 모두 포함해야 합니다. "
                         "아이디를 포함할 수 없습니다.")

# 재설정 링크 유효 시간. 메일이 늦게 도착하는 경우까지 감안하되, 링크가 메일함에 오래
# 살아 있을수록 위험하다.
RESET_TOKEN_TTL = timedelta(hours=1)

ROLE_RANK = {"VIEWER": 0, "OPERATOR": 1, "EDITOR": 2, "ADMIN": 3}   # codes.ts ROLE_RANK 와 동일

# 역할 설명 문구(A14). 셀렉트가 `${role} (${label})` 로 조립하므로 label 은 짧아야 한다.
ROLE_DEFINITIONS = [
    {"role": "VIEWER", "label": "조회",
     "description": "대시보드와 설정을 볼 수 있습니다. 대화 로그 본문과 쓰기는 할 수 없습니다."},
    {"role": "OPERATOR", "label": "운영",
     "description": "대화 로그를 보고 파이프라인 작업을 실행할 수 있습니다."},
    {"role": "EDITOR", "label": "편집",
     "description": "지식베이스·평가 문항·RAG 파라미터를 바꿀 수 있습니다."},
    {"role": "ADMIN", "label": "관리",
     "description": "계정과 권한을 포함해 모든 작업을 할 수 있습니다."},
]

# 역할별 권한 키(GET /me/permissions). 화면이 버튼을 숨기는 데 쓰는 편의값이고, 최종 판정은
# 각 엔드포인트가 한다 — 이 목록을 위조해도 실제 권한은 늘지 않는다.
PERMISSIONS_BY_ROLE = {
    "VIEWER": ["dashboard.read", "activity.read", "logs.summary"],
    "OPERATOR": ["dashboard.read", "activity.read", "logs.summary", "logs.read",
                 "pipeline.run", "knowledge.read"],
    "EDITOR": ["dashboard.read", "activity.read", "logs.summary", "logs.read",
               "pipeline.run", "knowledge.read", "knowledge.write", "evaluation.write",
               "rag_params.write", "prompt.write"],
    "ADMIN": ["dashboard.read", "activity.read", "logs.summary", "logs.read",
              "logs.export", "pipeline.run", "pipeline.rollback", "knowledge.read",
              "knowledge.write", "evaluation.write", "rag_params.write", "prompt.write",
              "accounts.manage", "ops.write", "cache.purge"],
}

ADMIN_ROLE = "ADMIN"
STATUS_INVITED = "초대됨"
STATUS_INACTIVE = "비활성"
STATUS_LOCKED = "잠김"
ACCOUNT_STATUSES = frozenset({ACTIVE_STATUS, STATUS_INACTIVE, STATUS_INVITED, STATUS_LOCKED})


def _remaining_s(deadline: datetime, now: datetime) -> int:
    """만료까지 남은 초. 음수는 0 으로 자른다 — 프론트가 이 값을 그대로 카운트다운에 쓰므로
    음수가 나가면 화면에 '-3초' 같은 값이 찍힌다."""
    return max(0, int((deadline - now).total_seconds()))


def _kst_iso(value: Optional[datetime]) -> Optional[str]:
    """timestamptz -> +09:00 ISO. UTC 로 내보내면 화면의 시각이 9시간 어긋난다
    (admin_activity._to_kst_iso · admin_logs._to_kst_iso 와 같은 처리)."""
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return aware.astimezone(KST).isoformat()


def _require_admin(me, what: str) -> None:
    """계정·권한을 다루는 엔드포인트의 공통 게이트. 화면에서 버튼을 숨기는 건 편의일 뿐이다."""
    if me.role != ADMIN_ROLE:
        raise ForbiddenError(f"{what}에는 ADMIN 권한이 필요합니다. 현재 권한은 {me.role}입니다.")


def _active_lock(db, email: str, now: datetime) -> Optional[datetime]:
    """이 email 이 지금 잠겨 있으면 해제 시각을, 아니면 None.

    "이 email 의 가장 최근 행"만 본다(schema_admin.py admin_login_failures 주석) — 복합
    인덱스(email, attempted_at)가 그 질의를 받친다.
    """
    locked_until = db.execute(
        select(func.max(admin_login_failures.c.locked_until))
        .where(admin_login_failures.c.email == email)
    ).scalar_one_or_none()
    if locked_until is None:
        return None
    aware = locked_until if locked_until.tzinfo else locked_until.replace(tzinfo=timezone.utc)
    return aware if aware > now else None


def _record_login_failure(db, request, email: str, now: datetime) -> Optional[datetime]:
    """실패를 남기고, 이 시도로 잠금이 걸렸으면 해제 시각을 돌려준다.

    실패 사유를 인자로 받지 않는다 — 이 표에 남는 것은 '비밀번호가 틀린 시도'뿐이라 사유가
    하나뿐이고, 표에도 그 컬럼이 없다. 계정 상태로 막힌 로그인은 여기가 아니라 활동 로그에
    남긴다(잠금을 걸 이유가 없는 실패다).

    자기 자신을 포함해 창 안의 실패 수를 세므로 THRESHOLD 번째 시도에서 잠긴다.
    스스로 commit 한다 — 호출부가 곧바로 403/423 을 던지는데, 커밋을 미루면 get_db 의
    rollback 에 실패 기록이 딸려 사라진다(write_activity_log 와 같은 판단).
    """
    recent = db.execute(
        select(func.count()).select_from(admin_login_failures)
        .where(admin_login_failures.c.email == email,
               admin_login_failures.c.attempted_at >= now - LOCKOUT_WINDOW)
    ).scalar_one()

    locked_until = now + timedelta(minutes=LOCKOUT_MINUTES) if recent + 1 >= LOCKOUT_THRESHOLD else None
    db.execute(insert(admin_login_failures).values(
        email=email, attempted_at=now, ip=client_ip(request),
        user_agent=request.headers.get("user-agent"), locked_until=locked_until,
    ))
    db.commit()
    return locked_until


def _password_policy_error(password: str, email: str) -> Optional[str]:
    """정책 위반 사유. 통과면 None. 문구는 화면 안내와 같은 기준이다."""
    if len(password) < PASSWORD_MIN_LENGTH:
        return PASSWORD_RULE_MESSAGE
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_symbol = any(not c.isalnum() for c in password)
    if not (has_letter and has_digit and has_symbol):
        return PASSWORD_RULE_MESSAGE
    local = (email or "").split("@")[0]
    if local and local.lower() in password.lower():
        return PASSWORD_RULE_MESSAGE
    return None


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, response: Response,
          db: DbSession, settings: SettingsDep):
    """로그인 — 계정 대조 후 세션 행을 만들고 쿠키를 굽는다.

    잠금 검사가 비밀번호 대조보다 **먼저**다. 뒤에 두면 잠긴 동안에도 비밀번호를 계속 대조해
    줘서, 공격자가 423 응답을 받으면서도 '맞았는지'를 타이밍으로 떠볼 여지가 생긴다.
    """
    now = datetime.now(timezone.utc)

    locked_until = _active_lock(db, req.email, now)
    if locked_until is not None:
        # 🔴 423 이어야 한다. 403 으로 주면 화면이 '권한 없음'으로 읽어 잔여 카운트다운도
        #    제출 잠금도 안 걸린다(LoginPage.tsx:58, 302-333).
        raise LockedError(
            f"로그인 시도가 많아 계정이 일시적으로 잠겼습니다. "
            f"{_kst_iso(locked_until)} 이후 다시 시도해 주세요.",
            extra={"locked_until": _kst_iso(locked_until)})

    row = db.execute(
        select(admin_accounts.c.id, admin_accounts.c.email, admin_accounts.c.name,
               admin_accounts.c.role, admin_accounts.c.status,
               admin_accounts.c.password_hash)
        .where(admin_accounts.c.email == req.email)
    ).first()

    # 계정 없음과 비밀번호 불일치를 같은 문구로 돌려준다 — 응답이 갈리면 그 차이만으로
    # "이 이메일은 등록돼 있다"를 알아낼 수 있다(계정 탐색).
    #
    # bcrypt.checkpw 는 해시가 bcrypt 형식이 아니면 False 가 아니라 ValueError 를 던진다.
    # 계정을 손으로 INSERT 하다 평문을 넣으면 403 이 아니라 500 이 나 원인을 엉뚱한 데서
    # 찾게 되므로, 여기서 잡아 '비밀번호 불일치'와 같은 취급을 한다(서버 로그에는 남긴다).
    if row is None:
        password_ok = False
    else:
        try:
            password_ok = bcrypt.checkpw(req.password.encode(), row.password_hash.encode())
        except ValueError:
            logger.error("admin_accounts.password_hash 가 bcrypt 형식이 아니다: %s", req.email)
            password_ok = False

    if not password_ok:
        logger.warning("admin login failed: %s", req.email)
        # 🔴 던지기 전에 기록한다. 두 기록 함수 모두 스스로 commit 하므로 뒤따르는 4xx 에
        #    딸려 rollback 되지 않는다 — 실패 기록이 사라지면 감사가 무의미하다.
        #    actor 는 '시도한 이메일'이고 actor_role 은 없다(아직 누구인지 확정되지 않았다).
        locked_until = _record_login_failure(db, request, req.email, now)
        write_activity_log(db, request, actor=req.email, action=ACTION_LOGIN_FAILED,
                           target=req.email, result=RESULT_FAILED)
        if locked_until is not None:
            write_activity_log(db, request, actor=req.email, action=ACTION_ACCOUNT_LOCKED,
                               target=req.email, result=RESULT_FAILED,
                               reason=f"{LOCKOUT_WINDOW.total_seconds() // 60:.0f}분 내 "
                                      f"{LOCKOUT_THRESHOLD}회 실패")
            raise LockedError(
                f"로그인 시도가 많아 계정이 일시적으로 잠겼습니다. "
                f"{_kst_iso(locked_until)} 이후 다시 시도해 주세요.",
                extra={"locked_until": _kst_iso(locked_until)})
        # 🔴 남은 시도 횟수를 붙이지 마라(A1). 계정이 있는지 없는지를 알려주는 셈이 된다 —
        #    없는 이메일에는 카운트가 안 쌓이므로 문구 차이만으로 존재 여부가 드러난다.
        raise ForbiddenError("아이디 또는 비밀번호가 올바르지 않습니다.")

    if row.status != ACTIVE_STATUS:
        # 비밀번호는 맞았으므로 실패 표에는 남기지 않는다 — 그 표는 '틀린 시도'를 세어 잠금을
        # 거는 곳이고, 상태 때문에 막힌 것은 몇 번을 반복해도 잠글 이유가 없다.
        write_activity_log(db, request, actor=row.email, actor_role=row.role,
                           action=ACTION_LOGIN_FAILED, target=row.email,
                           result=RESULT_FAILED, reason=f"계정 상태: {row.status}")
        raise ForbiddenError("사용할 수 없는 계정입니다. 관리자에게 문의해 주세요.")

    token = new_session_token()
    db.execute(insert(admin_sessions).values(
        # 🔴 DB 에는 해시가 들어간다. 원문 토큰은 쿠키로만 나간다(api/deps.py hash_token).
        id=hash_token(token),
        account_id=row.id,
        session_started_at=now,
        last_activity_at=now,
        # 재인증(POST /reauth)은 아직 만들지 않았다. 로그인 시각으로 채워 두면 로그인 직후
        # 30분은 재확인이 면제된 상태가 되고, 재인증을 붙일 때 이 컬럼만 갱신하면 된다.
        last_auth_at=now,
    ))
    db.execute(update(admin_accounts)
               .where(admin_accounts.c.id == row.id)
               .values(last_login_at=now))
    db.commit()

    response.set_cookie(
        COOKIE_NAME, token,
        # JS 가 못 읽는다 — XSS 가 나도 세션을 훔쳐 갈 수 없다.
        httponly=True,
        # 5173(프론트) -> 8000(API) 은 오리진은 달라도 포트만 다른 same-site 라 lax 로 간다.
        # "none" 으로 두면 브라우저가 secure=True 를 강제해 http 로컬에서 쿠키가 아예 안 실린다.
        samesite="lax",
        # 로컬은 http 라 False, 배포(https)에서는 True 여야 한다.
        secure=settings.is_production,
        path="/",
        # 절대 만료와 같은 창. 쿠키가 먼저 사라져도 서버 판정과 어긋나지 않는다.
        max_age=int(ABSOLUTE_WINDOW.total_seconds()),
    )
    # 세션 발급을 commit 한 다음에 기록한다 — 먼저 부르면 이 함수의 commit 이 위의 INSERT 까지
    # 같이 확정해 버려서, 뒤에서 문제가 생겨도 되돌릴 수 없는 상태가 된다.
    write_activity_log(db, request, actor=row.email, actor_role=row.role,
                       action=ACTION_LOGIN, target=row.email)
    logger.info("admin login: %s (%s)", row.email, row.role)
    return LoginResponse(email=row.email, name=row.name, role=row.role)


@router.get("/session", response_model=SessionResponse)
def read_session(me: CurrentAdmin):
    """세션 3타이머 조회. 프론트는 부팅·로그인 직후·주기적으로 이걸 부른다.

    이 요청에는 항상 X-Poll 이 붙어 오므로(app/session.ts loadSession) 의존성이 유휴
    타이머를 갱신하지 않는다 — 세션을 확인하는 행위 자체는 활동이 아니다.
    """
    now = datetime.now(timezone.utc)
    return SessionResponse(
        email=me.email,
        role=me.role,
        absolute_expires_in_s=_remaining_s(me.session_started_at + ABSOLUTE_WINDOW, now),
        idle_expires_in_s=_remaining_s(me.last_activity_at + IDLE_WINDOW, now),
        reauth_valid_until_s=_remaining_s(me.last_auth_at + REAUTH_WINDOW, now),
    )


@router.post("/session/extend", response_model=ExtendResponse)
def extend_session(me: CurrentAdmin):
    """[연장] — 유휴 타이머만 되돌린다. 절대 8시간과 재확인 30분은 갱신되지 않는다.

    갱신 자체는 의존성이 이미 했다(X-Poll 이 없는 요청이라 last_activity_at 이 now 로
    올라갔다). 여기서는 그 결과를 초로 알려주기만 한다 — 두 번 쓰면 값이 어긋난다.
    """
    return ExtendResponse(idle_expires_in_s=int(IDLE_WINDOW.total_seconds()))


@router.post("/reauth", response_model=ReauthResponse)
def reauth(req: ReauthRequest, me: CurrentAdmin, request: Request, db: DbSession):
    """위험 작업 직전 비밀번호 재확인(A8). 성공하면 재확인 창 30분이 다시 열린다.

    ## 왜 403 이고 401 이 아닌가

    비밀번호를 틀렸다고 401 을 주면 프론트가 경로를 보지 않고 expireSession() 해서
    **재확인 모달에서 오타 한 번에 로그아웃된다**(docs/backend-structure.md §3 함정 1).
    목(handlers/admin.ts:162)이 401 을 주고 있는데 목이 틀렸다 — 로그인과 같은 판단이다.

    ## last_activity_at 도 함께 갱신한다

    A8 이 둘을 함께 갱신하라고 못 박은 이유는, 비밀번호를 다시 입력하는 것이야말로 가장
    확실한 '사람이 지금 여기 있다'는 증거라서다. 재확인만 갱신하면 유휴 30분이 그대로 흘러
    재확인 직후에 유휴 만료로 튕기는 일이 생긴다.

    실제로는 이 요청이 X-Poll 없이 오므로 get_current_admin 이 이미 last_activity_at 을
    올렸지만, 그 동작에 기대지 않고 여기서 명시적으로 함께 쓴다 — 의존성 쪽 규칙이 바뀌어도
    A8 계약이 깨지지 않게.
    """
    row = db.execute(
        select(admin_accounts.c.password_hash)
        .where(admin_accounts.c.id == me.account_id)
    ).first()

    # 세션은 유효한데 계정 행이 없는 경우(삭제·정리). 로그인과 같은 문구로 막는다.
    if row is None:
        raise ForbiddenError("비밀번호가 올바르지 않습니다.")

    try:
        ok = bcrypt.checkpw(req.password.encode(), row.password_hash.encode())
    except ValueError:
        logger.error("admin_accounts.password_hash 가 bcrypt 형식이 아니다: %s", me.email)
        ok = False

    if not ok:
        # 재확인 실패는 활동 로그에만 남긴다. admin_login_failures 에 넣지 않는 이유는 그
        # 표가 '로그인 시도'의 기록이고 임시 잠금 판정의 입력이라서다 — 이미 인증된 세션의
        # 오타가 그 계정의 로그인을 잠그면, 화면에서 실수 몇 번에 로그인까지 막힌다.
        write_activity_log(db, request, actor=me.email, actor_role=me.role,
                           action=ACTION_REAUTH, target=me.email, result=RESULT_FAILED)
        raise ForbiddenError("비밀번호가 올바르지 않습니다.")

    now = datetime.now(timezone.utc)
    db.execute(update(admin_sessions)
               .where(admin_sessions.c.id == me.session_id)
               .values(last_auth_at=now, last_activity_at=now))
    db.commit()
    write_activity_log(db, request, actor=me.email, actor_role=me.role,
                       action=ACTION_REAUTH, target=me.email)
    logger.info("admin reauth: %s", me.email)
    return ReauthResponse(reauth_valid_until_s=int(REAUTH_WINDOW.total_seconds()))


@router.post("/logout", status_code=204)
def logout(me: CurrentAdmin, request: Request, response: Response, db: DbSession):
    """로그아웃 — 세션 행을 무효로 박고 쿠키를 지운다. 204 + 빈 본문.

    행을 지우지 않고 revoked_at 을 채우는 이유: 세션 이력이 남아야 '언제 로그인해서 언제
    끊었는가'를 활동 로그와 대조할 수 있고, 삭제는 되돌릴 수 없다.
    """
    db.execute(update(admin_sessions)
               .where(admin_sessions.c.id == me.session_id)
               .values(revoked_at=datetime.now(timezone.utc)))
    db.commit()
    write_activity_log(db, request, actor=me.email, actor_role=me.role,
                       action=ACTION_LOGOUT, target=me.email)
    # 쿠키를 굽던 때와 path 가 같아야 브라우저가 지운다.
    response.delete_cookie(COOKIE_NAME, path="/")
    logger.info("admin logout: %s", me.email)


# ═══════════════════════════════════════════════════════════════════════════
# 접근 관리 (AD-010) — 역할·권한·계정·로그인 실패·비밀번호
#
# 계약 정본은 web/src/routes/admin/settings/access/api.ts 다. 필드 이름을 바꾸면 화면이
# 조용히 빈 칸으로 뜬다.
# ═══════════════════════════════════════════════════════════════════════════

@router.get("/roles", response_model=list[RoleDefinition])
def list_roles(me: CurrentAdmin):
    """역할 목록(A14). 셀렉트가 `${role} (${label})` 로 조립한다.

    Page 봉투가 아니라 배열 그대로다 — fetchRoles 의 반환 타입이 RoleDefinition[] 이다.
    권한 순서(VIEWER→ADMIN)를 유지한다. 화면이 이 순서대로 셀렉트를 그린다.
    """
    del me  # 인증만 하면 누구나 볼 수 있다. 역할 정의 자체는 비밀이 아니다.
    return [RoleDefinition(**r) for r in ROLE_DEFINITIONS]


@router.get("/me/permissions", response_model=MyPermissions)
def my_permissions(me: CurrentAdmin):
    """현재 계정의 권한. 화면이 버튼을 숨기는 데 쓰는 편의값이다.

    이 응답을 위조해도 실제 권한은 늘지 않는다 — 각 엔드포인트가 스스로 판정한다.
    """
    return MyPermissions(
        role=me.role,
        rank=ROLE_RANK.get(me.role, 0),
        permissions=PERMISSIONS_BY_ROLE.get(me.role, []),
    )


@router.get("/security/summary", response_model=SecuritySummary)
def security_summary(me: CurrentAdmin, db: DbSession):
    """접근 관리 화면 상단 현황 4값. 목록은 접혀 있어서 집계는 서버가 준다."""
    _require_admin(me, "보안 현황 조회")
    now = datetime.now(timezone.utc)

    # 유효한 세션만 센다 — revoked 는 물론이고 절대·유휴 창을 넘긴 것도 이미 죽은 세션이다.
    # get_current_admin 이 다음 요청에서 무효로 박겠지만, 그때까지 행이 남아 있다고 해서
    # '접속 중'으로 보이면 안 된다.
    active_sessions = db.execute(
        select(func.count()).select_from(admin_sessions)
        .where(admin_sessions.c.revoked_at.is_(None),
               admin_sessions.c.session_started_at > now - ABSOLUTE_WINDOW,
               admin_sessions.c.last_activity_at > now - IDLE_WINDOW)
    ).scalar_one()

    # 🔴 '초대됨·비활성 포함 전체'다(A13). 활성만 세면 아래 계정 목록의 total 과 어긋나
    # 운영자가 사라진 계정을 찾게 된다.
    account_count = db.execute(
        select(func.count()).select_from(admin_accounts)).scalar_one()

    today_start = datetime(*now.astimezone(KST).timetuple()[:3], tzinfo=KST)
    failures_today = db.execute(
        select(func.count()).select_from(admin_login_failures)
        .where(admin_login_failures.c.attempted_at >= today_start)
    ).scalar_one()

    locked_rows = db.execute(
        select(admin_login_failures.c.email,
               func.max(admin_login_failures.c.locked_until).label("unlock_at"))
        .where(admin_login_failures.c.locked_until > now)
        .group_by(admin_login_failures.c.email)
        .order_by(func.max(admin_login_failures.c.locked_until))
    ).all()

    return SecuritySummary(
        active_sessions=active_sessions,
        account_count=account_count,
        failures_today=failures_today,
        locked=[LockedAccount(email=r.email, unlock_at=_kst_iso(r.unlock_at),
                              lock_minutes=LOCKOUT_MINUTES) for r in locked_rows],
    )


def _session_state(db, account_ids: list, current_session_id: str, now: datetime) -> dict:
    """계정 id -> (session, last_activity_at).

    🔴 계정 상태와 **분리**된 값이다(A5). 한 컬럼에 섞으면 '비활성인데 접속 중'을 표현하지
    못하는데, 그 조합이야말로 운영자가 제일 먼저 봐야 하는 상태다(방금 비활성화했는데 아직
    세션이 살아 있다).

    한 계정에 창이 여러 개면 가장 최근 활동을 대표로 삼되, 그중 지금 이 요청의 세션이 있으면
    CURRENT 가 이긴다 — 화면이 '나 자신'을 다른 창과 구분해 표시한다.
    """
    if not account_ids:
        return {}
    rows = db.execute(
        select(admin_sessions.c.id, admin_sessions.c.account_id,
               admin_sessions.c.last_activity_at)
        .where(admin_sessions.c.account_id.in_(account_ids),
               admin_sessions.c.revoked_at.is_(None),
               admin_sessions.c.session_started_at > now - ABSOLUTE_WINDOW,
               admin_sessions.c.last_activity_at > now - IDLE_WINDOW)
    ).all()

    state: dict = {}
    for row in rows:
        key = str(row.account_id)
        is_current = row.id == current_session_id
        previous = state.get(key)
        if previous is not None and previous[0] == "CURRENT" and not is_current:
            continue
        if previous is None or is_current or row.last_activity_at > previous[1]:
            state[key] = ("CURRENT" if is_current else "ACTIVE", row.last_activity_at)
    return state


def _last_admin_ids(db) -> set:
    """지금 '마지막 남은 활성 ADMIN'인 계정 id 집합(0개 또는 1개).

    🔴 서버가 판정해야 한다(A6). 프론트는 목록 한 페이지만 보므로 다음 페이지에 다른 ADMIN 이
    있는지 알 수 없다 — 프론트에 맡기면 마지막 관리자를 강등해 아무도 계정을 못 고치는
    상태를 만들 수 있다.
    """
    rows = db.execute(
        select(admin_accounts.c.id)
        .where(admin_accounts.c.role == ADMIN_ROLE, admin_accounts.c.status == ACTIVE_STATUS)
    ).scalars().all()
    return {str(rows[0])} if len(rows) == 1 else set()


def _snapshot(role: str, status: str) -> str:
    """활동 로그의 before/after 값. 화면이 JSON 이면 키·값 표로 그린다
    (admin_activity.parse_snapshot_value)."""
    return json.dumps({"role": role, "status": status}, ensure_ascii=False)


def _to_account_row(row, *, me, session_state: dict, last_admin_ids: set,
                    now: datetime) -> AccountRow:
    account_id = str(row.id)
    session, last_activity = session_state.get(account_id, ("NONE", None))
    return AccountRow(
        id=account_id,
        email=row.email,
        name=row.name,
        role=row.role,
        status=row.status,
        last_login_at=_kst_iso(row.last_login_at),
        last_activity_at=_kst_iso(last_activity),
        session=session,
        session_idle_expires_in_s=(
            _remaining_s(last_activity + IDLE_WINDOW, now) if last_activity else None),
        is_self=account_id == str(me.account_id),
        is_last_admin=account_id in last_admin_ids,
    )


@router.get("/accounts", response_model=AccountList)
def list_accounts(
    me: CurrentAdmin,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
):
    """전체 계정 목록. 초대됨·비활성도 포함한다(security/summary.account_count 와 같은 모집단)."""
    _require_admin(me, "계정 목록 조회")
    now = datetime.now(timezone.utc)

    total = db.execute(select(func.count()).select_from(admin_accounts)).scalar_one()
    rows = db.execute(
        # 화면이 정렬을 안 보내므로 서버가 정한다. 이메일 오름차순이면 페이지를 넘겨도
        # 순서가 흔들리지 않는다(unique 컬럼이라 tie-break 가 필요 없다).
        select(admin_accounts).order_by(admin_accounts.c.email)
        .offset((page - 1) * size).limit(size)
    ).all()

    session_state = _session_state(db, [r.id for r in rows], me.session_id, now)
    last_admin_ids = _last_admin_ids(db)
    return AccountList(
        items=[_to_account_row(r, me=me, session_state=session_state,
                               last_admin_ids=last_admin_ids, now=now) for r in rows],
        total=total, page=page, size=size,
    )


@router.post("/accounts", response_model=AccountRow)
def create_account(body: AccountCreateRequest, me: CurrentAdmin, request: Request, db: DbSession):
    """계정 초대(A10). 상태 '초대됨'으로 만들고 비밀번호는 본인이 링크로 정한다.

    비밀번호를 여기서 받지 않는 이유: 초대자가 정해 알려주면 그 값이 메신저·메일에 남고,
    바꾸라고 강제할 방법도 없다. 대신 재설정 토큰을 하나 발급해 둔다 — 초대 링크가 곧
    '비밀번호 설정' 링크이고, 본인이 reset-confirm 으로 정하면 상태가 활성이 된다.
    """
    _require_admin(me, "계정 초대")
    email = (body.email or "").strip().lower()
    if not email or "@" not in email:
        raise BadRequestError("올바른 이메일을 입력해 주세요.")
    if body.role not in ROLE_RANK:
        raise BadRequestError(f"알 수 없는 역할입니다: {body.role}")
    if not (body.name or "").strip():
        raise BadRequestError("이름을 입력해 주세요.")
    if not (body.reason or "").strip():
        raise BadRequestError("사유를 입력해 주세요.")

    exists = db.execute(
        select(admin_accounts.c.id).where(admin_accounts.c.email == email)).first()
    if exists is not None:
        raise BadRequestError("이미 등록된 이메일입니다.")

    now = datetime.now(timezone.utc)
    # 로그인할 수 없는 자리표시 해시. 컬럼이 NOT NULL 이고, 빈 문자열을 넣으면 login 의
    # bcrypt.checkpw 가 ValueError 를 던져 서버 로그에 형식 오류가 매번 찍힌다(동작은 맞지만
    # 진짜 문제를 가린다). 난수를 해싱해 두면 아무도 이 값으로 로그인할 수 없다.
    placeholder = _hash_password(secrets.token_urlsafe(32))
    inserted = db.execute(
        insert(admin_accounts)
        .values(email=email, name=body.name.strip(), role=body.role,
                status=STATUS_INVITED, password_hash=placeholder)
        .returning(admin_accounts)
    ).first()
    _issue_reset_token(db, inserted.id, email, request, now, purpose="초대")
    db.commit()

    write_activity_log(db, request, actor=me.email, actor_role=me.role,
                       action=ACTION_ACCOUNT_INVITED,
                       target=f"{body.name.strip()} ({email})", reason=body.reason,
                       after_value=_snapshot(body.role, STATUS_INVITED))
    logger.info("admin account invited: %s (%s) by %s", email, body.role, me.email)
    return _to_account_row(inserted, me=me, session_state={},
                           last_admin_ids=_last_admin_ids(db), now=now)


@router.patch("/accounts/{account_id}", response_model=AccountRow)
def patch_account(account_id: str, body: AccountPatchRequest, me: CurrentAdmin,
                  request: Request, db: DbSession):
    """역할 변경 또는 비활성화(A7). 둘 다 이 엔드포인트 하나로 온다.

    ## 서버가 책임지는 것

    1. 안전 규칙 — 자기 자신과 마지막 남은 ADMIN 은 강등·비활성화할 수 없다(A6). 프론트도
       버튼을 잠그지만 그건 UX 이고, 목록 밖 계정까지 보는 판정은 서버에서만 된다.
    2. 반영 즉시 **대상 계정의 세션 종료**. 권한을 낮췄는데 열려 있던 창이 살아 있으면
       그 창은 옛 권한으로 계속 움직인다.
    3. '권한 변경'(또는 '계정 비활성화') 이벤트 기록.
    """
    _require_admin(me, "계정 변경")
    if body.role is None and body.status is None:
        raise BadRequestError("변경할 역할 또는 상태를 지정해 주세요.")
    if not (body.reason or "").strip():
        raise BadRequestError("사유를 입력해 주세요.")
    if body.role is not None and body.role not in ROLE_RANK:
        raise BadRequestError(f"알 수 없는 역할입니다: {body.role}")
    if body.status is not None and body.status not in ACCOUNT_STATUSES:
        raise BadRequestError(f"알 수 없는 상태입니다: {body.status}")

    target = db.execute(
        select(admin_accounts).where(admin_accounts.c.id == account_id)).first()
    if target is None:
        raise NotFoundError("계정을 찾을 수 없습니다.")

    now = datetime.now(timezone.utc)
    is_self = str(target.id) == str(me.account_id)
    is_last_admin = str(target.id) in _last_admin_ids(db)
    # 강등·비활성화만 막는다. 승격·재활성화는 자기 자신이어도 잠기는 상황을 만들지 않는다.
    demoting = body.role is not None and ROLE_RANK[body.role] < ROLE_RANK[target.role]
    disabling = body.status is not None and body.status != ACTIVE_STATUS

    if (demoting or disabling) and is_self:
        raise BadRequestError("자기 자신의 권한을 낮추거나 계정을 비활성화할 수 없습니다.")
    if (demoting or disabling) and is_last_admin:
        raise BadRequestError(
            "마지막 남은 관리자입니다. 다른 계정에 ADMIN 을 부여한 뒤에 다시 시도해 주세요.")

    changes = {}
    if body.role is not None:
        changes["role"] = body.role
    if body.status is not None:
        changes["status"] = body.status

    updated = db.execute(
        update(admin_accounts).where(admin_accounts.c.id == account_id)
        .values(**changes).returning(admin_accounts)
    ).first()

    # 🔴 반영 즉시 대상 계정의 세션을 끊는다(A7). 지금 이 요청의 세션만 남긴다 — 자기 자신을
    # 승격하는 경우까지 끊으면 방금 성공한 작업의 응답을 받자마자 로그아웃된다.
    db.execute(
        update(admin_sessions)
        .where(admin_sessions.c.account_id == account_id,
               admin_sessions.c.revoked_at.is_(None),
               admin_sessions.c.id != me.session_id)
        .values(revoked_at=now))
    db.commit()

    action = ACTION_ACCOUNT_DEACTIVATED if disabling else ACTION_ROLE_CHANGED
    write_activity_log(
        db, request, actor=me.email, actor_role=me.role, action=action,
        target=f"{target.name} ({target.email})", reason=body.reason,
        before_value=_snapshot(target.role, target.status),
        after_value=_snapshot(updated.role, updated.status))
    logger.info("admin account patched: %s -> %s by %s", target.email, changes, me.email)

    session_state = _session_state(db, [updated.id], me.session_id, now)
    return _to_account_row(updated, me=me, session_state=session_state,
                           last_admin_ids=_last_admin_ids(db), now=now)


@router.get("/login-failures", response_model=LoginFailureList)
def list_login_failures(
    me: CurrentAdmin,
    db: DbSession,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
):
    """로그인 실패 내역(A4). 화면은 최근 4건만 접어서 보여주지만 목록 자체는 페이지로 준다.

    계정이 없는 이메일로 시도한 것도 그대로 나온다 — 그게 계정 탐색 공격의 유일한 흔적이다
    (schema_admin.py 가 FK 를 일부러 안 건 이유).
    """
    _require_admin(me, "로그인 실패 내역 조회")
    now = datetime.now(timezone.utc)

    total = db.execute(
        select(func.count()).select_from(admin_login_failures)).scalar_one()
    rows = db.execute(
        select(admin_login_failures)
        .order_by(admin_login_failures.c.attempted_at.desc())
        .offset((page - 1) * size).limit(size)
    ).all()

    items = []
    for row in rows:
        locked_until = row.locked_until
        if locked_until is not None and locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        # result 는 '이 시도로 잠겼는가'다. 이미 풀린 잠금도 그 시점엔 잠근 게 맞으므로
        # LOCKED 로 남긴다 — 화면은 unlock_at 으로 현재 상태를 따로 그린다.
        items.append(LoginFailureRow(
            id=str(row.id),
            occurred_at=_kst_iso(row.attempted_at) or "",
            email=row.email,
            ip=row.ip or "",
            # 실패 사유를 컬럼으로 두지 않았다(표에 reason 이 없다). 이 표에 남는 것은
            # '비밀번호가 틀린 시도'뿐이라 사유가 하나뿐이다 — 계정 상태로 막힌 로그인은
            # 여기 안 남기고 활동 로그에만 남긴다(login 핸들러 주석).
            reason="비밀번호 불일치",
            result="LOCKED" if locked_until is not None else "NONE",
            unlock_at=_kst_iso(locked_until) if (
                locked_until is not None and locked_until > now) else None,
        ))
    return LoginFailureList(items=items, total=total, page=page, size=size)


# ---------------------------------------------------------------- 비밀번호
#
# ⚠️ 메일 발송 경로가 아직 없다. requirements.txt·.env.example 어디에도 SMTP 설정이 없어서,
# 재설정 토큰을 사용자에게 전달할 방법이 서버에 존재하지 않는다.
#
# 그래서 지금은 **토큰을 서버 로그에만 남긴다**(_issue_reset_token). 응답에는 절대 싣지
# 않는다 — 응답에 실으면 아무나 남의 이메일로 재설정을 요청해 그 계정을 탈취할 수 있고,
# A9 가 막으려는 계정 탐색도 같이 뚫린다.
#
# 운영에 올리기 전에 메일 발송을 붙여야 한다. 붙일 자리는 _issue_reset_token 한 곳뿐이라
# 그 함수만 고치면 된다. 그때까지 초대·재설정은 관리자가 로그에서 링크를 꺼내 전달한다.

def _issue_reset_token(db, account_id, email: str, request, now: datetime,
                       *, purpose: str) -> str:
    """재설정 토큰을 발급하고 원문을 돌려준다. DB 에는 sha256 해시만 남는다.

    admin_sessions 와 같은 비대칭이다 — 메일로 나가는 건 원문이고 여기 남는 건 해시라,
    DB 가 새도 링크를 그대로 쓸 수 없다.

    같은 계정의 아직 안 쓴 이전 토큰은 만료시킨다. 링크를 두 번 요청하면 옛 링크도 계속
    살아 있는 게 자연스럽지 않고, 유효한 링크가 여러 개면 그만큼 표면이 넓어진다.
    """
    db.execute(
        update(password_reset_tokens)
        .where(password_reset_tokens.c.account_id == account_id,
               password_reset_tokens.c.used_at.is_(None),
               password_reset_tokens.c.expires_at > now)
        .values(expires_at=now))

    token = secrets.token_urlsafe(32)
    db.execute(insert(password_reset_tokens).values(
        id=hashlib.sha256(token.encode()).hexdigest(),
        account_id=account_id,
        created_at=now,
        expires_at=now + RESET_TOKEN_TTL,
        requested_ip=client_ip(request),
    ))
    # 🔴 메일 발송이 붙기 전까지의 유일한 전달 경로다. 링크 형식은 A10 이 정한 것 —
    # 기획서가 제안한 /admin/password/reset/confirm 은 프론트 라우터에 없다.
    logger.warning("[%s] 비밀번호 재설정 링크(메일 발송 미구현 — 수동 전달): "
                   "/admin/login?reset_token=%s (%s, %s 유효)",
                   purpose, token, email, RESET_TOKEN_TTL)
    return token


# 경로는 규격(PRD-02 'password(reset-request/…)')과 프론트 실호출(PasswordResetPanel.tsx
# reset-request)에 맞춘다 — 종전 /password/reset 은 프론트가 부르지 않아 재설정 1단계가
# 항상 404 였다(2026-08-13 실측 F-5).
@router.post("/password/reset-request", status_code=202)
def request_password_reset(body: PasswordResetRequest, request: Request, db: DbSession):
    """재설정 요청. 🔴 계정 존재 여부와 무관하게 **항상 202** 다(A9).

    없는 계정에 404 를 주면 그 응답 차이만으로 어떤 이메일이 등록돼 있는지 알아낼 수 있다.
    로그인 문구를 통일해 막아 둔 계정 탐색이 여기서 그대로 뚫린다.

    인증이 필요 없는 엔드포인트다 — 비밀번호를 잊은 사람이 부르는 것이라 세션이 없다.
    """
    email = (body.email or "").strip().lower()
    now = datetime.now(timezone.utc)

    row = db.execute(
        select(admin_accounts.c.id, admin_accounts.c.email, admin_accounts.c.status)
        .where(admin_accounts.c.email == email)
    ).first()

    # 비활성 계정에도 링크를 주지 않는다. 다만 응답은 같다 — 위와 같은 이유다.
    if row is not None and row.status != STATUS_LOCKED:
        _issue_reset_token(db, row.id, row.email, request, now, purpose="재설정")
        db.commit()
        write_activity_log(db, request, actor=row.email,
                           action=ACTION_PASSWORD_RESET_REQUESTED, target=row.email)
    else:
        logger.info("비밀번호 재설정 요청(대상 없음 — 응답은 동일): %s", email)

    return {"status": "accepted"}


@router.post("/password/reset-confirm", status_code=204)
def confirm_password_reset(body: PasswordResetConfirmRequest, request: Request, db: DbSession):
    """링크로 받은 토큰 + 새 비밀번호. 인증 없이 부른다(비밀번호를 아직 모르는 상태다).

    ## 410 과 400 을 반드시 가른다(A11)

        410  만료됐거나 이미 쓴 링크  -> 화면이 '재설정 다시 요청'으로 되돌린다
        400  비밀번호 정책 위반        -> 화면이 그 자리에 머물러 입력을 지킨다

    둘을 404 나 400 으로 뭉치면 사용자가 링크를 다시 받을 생각을 못 하거나(410 을 400 으로),
    다 쓴 입력을 잃는다(400 을 410 으로).
    """
    now = datetime.now(timezone.utc)
    token_hash = hashlib.sha256((body.token or "").encode()).hexdigest()

    row = db.execute(
        select(password_reset_tokens.c.account_id, password_reset_tokens.c.expires_at,
               password_reset_tokens.c.used_at, admin_accounts.c.email)
        .join_from(password_reset_tokens, admin_accounts,
                   password_reset_tokens.c.account_id == admin_accounts.c.id)
        .where(password_reset_tokens.c.id == token_hash)
    ).first()

    # 없는 토큰도 410 이다. 404 로 가르면 '이 토큰은 존재한다'가 드러나고, 화면 분기도
    # 만료와 같으므로(다시 요청) 구분할 실익이 없다.
    if row is None:
        raise GoneError()
    expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if row.used_at is not None or expires_at <= now:
        raise GoneError()

    problem = _password_policy_error(body.new_password, row.email)
    if problem:
        raise BadRequestError(problem)

    db.execute(update(admin_accounts)
               .where(admin_accounts.c.id == row.account_id)
               # 초대됨 상태로 기다리던 계정은 이 시점에 활성이 된다 — 비밀번호를 정한
               # 것이 곧 초대 수락이다.
               .values(password_hash=_hash_password(body.new_password),
                       status=ACTIVE_STATUS))
    # 🔴 행을 지우지 않고 used_at 을 채운다. 지우면 '이미 쓴 링크'와 '없는 링크'를 구분할
    # 수 없어 재사용 시도가 흔적 없이 사라진다(schema_admin.py 주석).
    db.execute(update(password_reset_tokens)
               .where(password_reset_tokens.c.id == token_hash)
               .values(used_at=now))
    # 비밀번호가 바뀌었으므로 그 계정의 기존 세션은 전부 끊는다. 비밀번호를 잊었다는 것은
    # 남이 쓰고 있을 가능성을 포함한다.
    db.execute(update(admin_sessions)
               .where(admin_sessions.c.account_id == row.account_id,
                      admin_sessions.c.revoked_at.is_(None))
               .values(revoked_at=now))
    db.commit()

    write_activity_log(db, request, actor=row.email,
                       action=ACTION_PASSWORD_RESET_COMPLETED, target=row.email)
    logger.info("비밀번호 재설정 완료: %s", row.email)


@router.post("/password/change", status_code=204)
def change_password(body: PasswordChangeRequest, me: CurrentAdmin, request: Request,
                    db: DbSession):
    """로그인 상태에서 스스로 바꾸기(A12). 위험 작업 재확인 대상이 **아니다** —
    현재 비밀번호를 이 요청에서 직접 확인하므로 재확인이 중복이다.

    성공하면 **현재 세션은 유지하고 같은 계정의 다른 세션만** 끊는다. 방금 바꾼 사람을
    로그아웃시키면 바꿨는지 확인할 방법 없이 다시 로그인해야 한다.
    """
    row = db.execute(
        select(admin_accounts.c.password_hash)
        .where(admin_accounts.c.id == me.account_id)
    ).first()
    if row is None:
        raise ForbiddenError("현재 비밀번호가 올바르지 않습니다.")

    try:
        ok = bcrypt.checkpw(body.current_password.encode(), row.password_hash.encode())
    except ValueError:
        logger.error("admin_accounts.password_hash 가 bcrypt 형식이 아니다: %s", me.email)
        ok = False
    if not ok:
        # A12 는 여기에도 5회 실패 10분 잠금을 요구한다. 로그인과 같은 표를 쓰되 email 이
        # 같으므로, 이 실패가 쌓이면 로그인도 함께 잠긴다 — 같은 사람의 같은 비밀번호에
        # 대한 실패라 의도한 동작이다.
        locked_until = _record_login_failure(db, request, me.email, datetime.now(timezone.utc))
        write_activity_log(db, request, actor=me.email, actor_role=me.role,
                           action=ACTION_PASSWORD_CHANGED, target=me.email,
                           result=RESULT_FAILED)
        if locked_until is not None:
            raise LockedError(extra={"locked_until": _kst_iso(locked_until)})
        raise BadRequestError("현재 비밀번호가 올바르지 않습니다.")

    problem = _password_policy_error(body.new_password, me.email)
    if problem:
        raise BadRequestError(problem)
    # 이력 표가 없어 직전 1개만 본다(파일 상단 PASSWORD_MIN_LENGTH 주석).
    if bcrypt.checkpw(body.new_password.encode(), row.password_hash.encode()):
        raise BadRequestError("현재 비밀번호와 다른 값을 사용해 주세요.")

    now = datetime.now(timezone.utc)
    db.execute(update(admin_accounts)
               .where(admin_accounts.c.id == me.account_id)
               .values(password_hash=_hash_password(body.new_password)))
    db.execute(update(admin_sessions)
               .where(admin_sessions.c.account_id == me.account_id,
                      admin_sessions.c.revoked_at.is_(None),
                      admin_sessions.c.id != me.session_id)
               .values(revoked_at=now))
    db.commit()

    write_activity_log(db, request, actor=me.email, actor_role=me.role,
                       action=ACTION_PASSWORD_CHANGED, target=me.email)
    logger.info("비밀번호 변경: %s", me.email)
