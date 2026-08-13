"""관리자 인증(AD-000) 요청·응답 스키마 — 로그인·세션 조회·연장.

계약의 정본은 프론트다. 필드명·타입을 아래 두 곳과 그대로 맞췄다:
  - web/src/routes/admin/LoginPage.tsx:30-34   LoginResponse{email,name,role}
  - web/src/app/session.ts:32-38               SessionResponse(3타이머, '남은 초')

🔴 세션 3필드는 시각(ISO)이 아니라 **남은 초(int)** 다. 프론트가 받은 즉시 만료 시각
(epoch ms)으로 굳혀 카운트다운을 돌리므로(session.ts toSession), ISO 로 바꾸면 헤더
카운트다운·유휴 경고·[연장] 활성 판정 세 개가 한꺼번에 깨진다.

요청 본문에 request_id(멱등키)가 섞여 들어온다 — lib/api/client.ts 가 모든 쓰기 요청에
자동으로 붙인다. 지금은 쓰지 않지만 pydantic 기본값이 '모르는 필드 무시'라 그대로 통과한다
(extra='forbid' 를 켜면 로그인이 400 으로 죽는다. 켜지 말 것).

타입 표기는 api/ 관례대로 typing.Optional 로 통일한다(api/schemas/common.py 주석 참고).
"""
from typing import Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """POST /api/admin/login 본문. 프론트는 아이디 칸의 값을 email 로 보낸다."""
    email: str = Field(description="로그인 ID(이메일).")
    password: str = Field(description="평문 비밀번호. 서버에서 bcrypt 로 대조만 하고 저장하지 않는다.")


class LoginResponse(BaseModel):
    """로그인 성공 응답. 세션 자체는 본문이 아니라 httpOnly 쿠키로 나간다."""
    email: str = Field(description="로그인한 계정.")
    name: str = Field(description="화면 헤더에 표시할 이름.")
    role: str = Field(description="VIEWER | OPERATOR | EDITOR | ADMIN (web/src/lib/codes.ts).")


class SessionResponse(BaseModel):
    """GET /api/admin/session — 세션 3타이머를 '남은 초'로 내려준다.

    | 타이머 | 창 | 갱신 조건 |
    |---|---|---|
    | 절대 | 8시간 | 갱신 불가. 만료 시 강제 로그아웃 |
    | 유휴 | 30분 | 인증된 관리자 API 요청 · [연장] — 🔴 폴링(X-Poll)은 제외 |
    | 재확인 | 30분 | 비밀번호 재확인 성공 시(아직 미구현 — 로그인 시각으로 채운다) |
    """
    email: str = Field(description="로그인한 계정.")
    role: str = Field(description="현재 역할.")
    absolute_expires_in_s: int = Field(description="절대 만료(8h)까지 남은 초.")
    idle_expires_in_s: int = Field(description="유휴 만료(30분)까지 남은 초.")
    reauth_valid_until_s: int = Field(description="위험 작업 재확인이 유효한 남은 초. 0 이면 재확인 필요.")


class ExtendResponse(BaseModel):
    """POST /api/admin/session/extend — [연장] 버튼. 유휴 타이머만 되돌린다."""
    idle_expires_in_s: int = Field(description="되돌린 유휴 만료까지 남은 초(=1800).")


class ReauthRequest(BaseModel):
    """POST /api/admin/reauth 본문 — 위험 작업 직전 비밀번호 재확인.

    프론트는 access/api.ts 의 runRisky 가 이 요청을 먼저 보내고 성공하면 본 작업을 부른다.
    본 작업 요청 본문에 password 를 싣지 않는다 — 별도 호출로 끝낸다.
    """
    password: str = Field(description="평문 비밀번호. 대조만 하고 저장하지 않는다.")


class ReauthResponse(BaseModel):
    """재확인 성공 응답. 필드는 이거 하나다.

    '마지막 인증 시각 조회' GET 을 따로 만들지 않는다 — GET /api/admin/session 이 같은 값을
    이미 준다(docs/backend-structure.md §3 함정 27). 30분 창 계산은 서버가 하고, 화면은
    reauth_valid_until_s <= 0 일 때만 비밀번호 슬롯을 띄운다.
    """
    reauth_valid_until_s: int = Field(description="재확인이 유효한 남은 초(=1800).")


class RoleDefinition(BaseModel):
    """GET /api/admin/roles 한 항목. 셀렉트가 `${role} (${label})` 로 조립한다(A14)."""
    role: str = Field(description="VIEWER | OPERATOR | EDITOR | ADMIN.")
    label: str = Field(description="한글 표기.")
    description: str = Field(description="이 역할이 무엇을 할 수 있는지 한 줄.")


class MyPermissions(BaseModel):
    """GET /api/admin/me/permissions — 현재 계정이 무엇을 할 수 있는가.

    화면이 버튼을 숨기는 데 쓰는 편의값이다. 최종 판정은 언제나 서버가 각 엔드포인트에서
    한다 — 이 응답을 위조해도 실제 권한은 늘어나지 않는다.
    """
    role: str = Field(description="현재 역할.")
    rank: int = Field(description="역할 서열(VIEWER 0 · OPERATOR 1 · EDITOR 2 · ADMIN 3).")
    permissions: list[str] = Field(description="이 역할이 가진 권한 키 목록.")


class LockedAccount(BaseModel):
    """security/summary 의 잠긴 계정 한 줄."""
    email: str
    unlock_at: Optional[str] = Field(default=None, description="해제 시각 KST ISO. null 이면 만료됨.")
    lock_minutes: int = Field(description="잠금 창 길이(분).")


class SecuritySummary(BaseModel):
    """GET /api/admin/security/summary — 화면 상단 현황 4값."""
    active_sessions: int = Field(description="지금 유효한 세션 수(만료·로그아웃 제외).")
    # 🔴 '초대됨·비활성 포함 전체'다(A13). 활성만 세면 화면의 계정 목록 건수와 어긋난다.
    account_count: int = Field(description="전체 계정 수(초대됨·비활성 포함).")
    failures_today: int = Field(description="오늘(KST) 로그인 실패 건수.")
    locked: list[LockedAccount] = Field(default_factory=list)


class AccountRow(BaseModel):
    """계정 목록 한 행. 계정 상태와 세션 상태를 **분리**한다(A5) — 한 컬럼에 섞으면
    '비활성인데 접속 중'을 표현하지 못한다."""
    id: str
    email: str
    name: str
    role: str
    status: str = Field(description="활성 | 비활성 | 초대됨 | 잠김.")
    last_login_at: Optional[str] = None
    last_activity_at: Optional[str] = None
    session: str = Field(description="CURRENT(지금 이 요청) | ACTIVE(다른 창) | NONE.")
    session_idle_expires_in_s: Optional[int] = None
    # 🔴 둘 다 서버 판정이다(A6). 프론트는 한 페이지만 보므로 '마지막 남은 ADMIN'을 알 수 없다.
    is_self: bool = Field(description="자기 자신 — 강등·비활성화 불가.")
    is_last_admin: bool = Field(description="마지막 남은 활성 ADMIN — 강등·비활성화 불가.")


class AccountList(BaseModel):
    """Page<AccountRow> — {items, total, page, size}. page 는 1-base."""
    items: list[AccountRow] = Field(default_factory=list)
    total: int
    page: int
    size: int


class AccountCreateRequest(BaseModel):
    """POST /api/admin/accounts — 초대. 비밀번호를 받지 않는다.

    초대는 '계정을 만들어 두고 본인이 링크로 비밀번호를 정하게 하는' 흐름이다(A10).
    초대자가 비밀번호를 정해 알려주는 방식이면 그 값이 메신저에 남는다.

    reason 은 **본문으로** 온다 — lib/api/client.ts 가 위험 작업의 사유를 body 에 넣는다
    (헤더가 아니다. client.ts:79 참고).
    """
    email: str
    name: str
    role: str
    reason: str = ""


class AccountPatchRequest(BaseModel):
    """PATCH /api/admin/accounts/{id} — 역할 변경 또는 비활성화. 둘 다 이 하나로 온다(A7).

    role 과 status 중 하나만 온다. 둘 다 없으면 400 이다 — 빈 PATCH 를 성공으로 돌려주면
    화면은 반영됐다고 믿고 목록을 다시 그리는데 실제로는 아무것도 안 바뀐 상태가 된다.
    """
    role: Optional[str] = None
    status: Optional[str] = None
    reason: str = ""


class LoginFailureRow(BaseModel):
    """GET /api/admin/login-failures 한 행."""
    id: str
    occurred_at: str = Field(description="KST ISO.")
    email: str
    ip: str
    reason: str
    result: str = Field(description="LOCKED(이 시도로 잠김) | NONE.")
    unlock_at: Optional[str] = None


class LoginFailureList(BaseModel):
    items: list[LoginFailureRow] = Field(default_factory=list)
    total: int
    page: int
    size: int


class PasswordResetRequest(BaseModel):
    """POST /api/admin/password/reset-request — 재설정 요청. 계정 유무와 무관하게 항상 202(A9)."""
    email: str


class PasswordResetConfirmRequest(BaseModel):
    """POST /api/admin/password/reset-confirm — 링크로 받은 토큰 + 새 비밀번호."""
    token: str = Field(description="메일 링크의 reset_token 원문(서버는 sha256 으로 대조).")
    new_password: str


class PasswordChangeRequest(BaseModel):
    """POST /api/admin/password/change — 로그인 상태에서 스스로 바꾸기(A12)."""
    current_password: str
    new_password: str
