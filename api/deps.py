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
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import Depends, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from api.config import Settings, get_settings
from api.errors import UnauthorizedError

# src/db.py 를 flat import 한다 — api/__init__.py 가 sys.path 에 src/ 를 넣어줘서
# 가능하다. src/ 쪽 import 스타일을 그대로 따르는 것이라 의도된 모양이다.
from db import get_session
from schema_admin import admin_accounts, admin_sessions


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
