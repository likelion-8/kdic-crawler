"""화면별 입력 자동저장 — PUT /api/admin/drafts/{screen}. **엔드포인트는 C 트랙 담당자가 채운다.**

빈 라우터로 자리만 잡아 둔 파일이다(사유는 admin_dashboard.py 상단과 같다).

## 왜 필요한가

관리자 화면 여러 곳이 긴 폼을 쓰는데 세션은 유휴 30분에 끊긴다(api/deps.py IDLE_WINDOW).
자동저장이 없으면 작성 중인 내용이 통째로 날아간다. 화면은 10초마다 이 엔드포인트를 부른다.

## 만들 것

    PUT /api/admin/drafts/{screen}

## 쓸 테이블 (2026-08-12 신설, src/schema_admin.py)

    admin_drafts   (screen, account_id) 복합 PK. 화면당 사람당 한 벌이면 충분하고,
                   같은 화면을 두 탭에서 열면 나중 저장이 이기는 게 자연스럽다.
                   이력은 남기지 않는다 — 자동저장은 기록이 아니라 임시 보관이다.

## 주의

- 10초마다 오는 호출이다. 활동 로그(write_activity_log)를 남기지 마라 — 감사 기록이
  자동저장으로 뒤덮여 정작 봐야 할 행위가 묻힌다.
- 같은 이유로 유휴 타이머도 갱신하지 않는 편이 맞는지 확인할 것. 프론트가 X-Poll 헤더를
  붙여 보내면 api/deps.py 가 알아서 뺀다(POLL_HEADER) — 안 붙이면 자동저장이 곧 '활동'이
  되어 유휴 만료가 영원히 오지 않는다. 프론트 동작을 확인하고 필요하면 요청할 것.
"""
from fastapi import APIRouter, Depends

from api.deps import get_current_admin

router = APIRouter(
    prefix="/api/admin/drafts",
    tags=["admin-drafts"],
    dependencies=[Depends(get_current_admin)],
)
