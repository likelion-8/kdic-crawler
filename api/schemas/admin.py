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
