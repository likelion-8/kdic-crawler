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
import logging
from datetime import datetime, timezone

import bcrypt
from fastapi import APIRouter, Request, Response
from sqlalchemy import insert, select, update

from api.deps import (ABSOLUTE_WINDOW, ACTION_LOGIN, ACTION_LOGIN_FAILED,
                      ACTION_LOGOUT, ACTIVE_STATUS, COOKIE_NAME, IDLE_WINDOW,
                      REAUTH_WINDOW, RESULT_FAILED, CurrentAdmin, DbSession,
                      SettingsDep, hash_token, new_session_token,
                      write_activity_log)
from api.errors import ForbiddenError
from api.schemas.admin import ExtendResponse, LoginRequest, LoginResponse, SessionResponse
from schema_admin import admin_accounts, admin_sessions  # src/schema_admin.py (flat import)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin-auth"])


def _remaining_s(deadline: datetime, now: datetime) -> int:
    """만료까지 남은 초. 음수는 0 으로 자른다 — 프론트가 이 값을 그대로 카운트다운에 쓰므로
    음수가 나가면 화면에 '-3초' 같은 값이 찍힌다."""
    return max(0, int((deadline - now).total_seconds()))


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, request: Request, response: Response,
          db: DbSession, settings: SettingsDep):
    """로그인 — 계정 대조 후 세션 행을 만들고 쿠키를 굽는다."""
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
        # 🔴 던지기 전에 기록한다. write_activity_log 가 스스로 commit 하므로 뒤따르는
        #    403 에 딸려 rollback 되지 않는다 — 실패 기록이 사라지면 감사가 무의미하다.
        #    actor 는 '시도한 이메일'이고 actor_role 은 없다(아직 누구인지 확정되지 않았다).
        write_activity_log(db, request, actor=req.email, action=ACTION_LOGIN_FAILED,
                           target=req.email, result=RESULT_FAILED)
        raise ForbiddenError("아이디 또는 비밀번호가 올바르지 않습니다.")

    if row.status != ACTIVE_STATUS:
        write_activity_log(db, request, actor=row.email, actor_role=row.role,
                           action=ACTION_LOGIN_FAILED, target=row.email,
                           result=RESULT_FAILED, reason=f"계정 상태: {row.status}")
        raise ForbiddenError("사용할 수 없는 계정입니다. 관리자에게 문의해 주세요.")

    now = datetime.now(timezone.utc)
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
