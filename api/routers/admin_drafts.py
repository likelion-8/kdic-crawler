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

## ⚠️ version 은 지금 1 고정이다
프론트 계약(admin.ts 목)은 응답에 증가하는 version 을 기대하지만, admin_drafts 에는 저장
횟수를 셀 컬럼이 없다(이력을 남기지 않는 임시 보관 테이블이라 그렇다). 컬럼 없이 매 저장마다
정확히 증가시킬 방법이 없어 1 을 돌려준다 — content 저장(자동저장의 본질)은 정확하다.
정확한 카운터가 필요하면 save_count 컬럼을 제안한다(docs/evaluation_api_notes.md 의 '드래프트
version' 항목). 컬럼 추가는 이번 주 범위 밖(제안만).
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert as pg_insert

from api.deps import CurrentAdmin, DbSession, get_current_admin
from api.errors import BadRequestError, ForbiddenError
from schema_admin import admin_drafts

router = APIRouter(
    prefix="/api/admin/drafts",
    tags=["admin-drafts"],
    dependencies=[Depends(get_current_admin)],
)

KST = timezone(timedelta(hours=9))
# 저장은 EDITOR 이상(admin.ts 목 denied(request,'EDITOR')와 같은 기준).
ROLE_RANK = {"VIEWER": 0, "OPERATOR": 1, "EDITOR": 2, "ADMIN": 3}


class DraftSaved(BaseModel):
    """자동저장 응답 — admin.ts 목의 {screen, saved_at, version}."""
    screen: str
    saved_at: str
    version: int


@router.put("/{screen}", response_model=DraftSaved)
def save_draft(screen: str, body: dict, db: DbSession, me: CurrentAdmin):
    """화면별 입력 자동저장(10초 주기). (screen, account_id) 한 벌을 덮어쓴다.

    🔴 write_activity_log 를 남기지 않는다 — 10초마다 오는 호출이라 감사 기록이 자동저장으로
    뒤덮여 정작 봐야 할 행위가 묻힌다(모듈 주석). 유휴 타이머는 프론트가 X-Poll 헤더를 붙이면
    api/deps.py 가 알아서 뺀다 — 이 라우터가 따로 할 일은 없다.
    """
    if ROLE_RANK.get(me.role, -1) < ROLE_RANK["EDITOR"]:
        raise ForbiddenError(
            f"자동저장에는 EDITOR 이상 권한이 필요합니다. 현재 권한은 {me.role}입니다.")
    # 위험 작업이 아니라 사유는 안 받는다. 멱등키만 확인한다(apiRequest 가 넣어 준다).
    if not str(body.get("request_id") or "").strip():
        raise BadRequestError("request_id가 필요합니다.")

    # request_id(멱등키)는 초안 내용이 아니므로 빼고 저장한다 — 복원 시 그대로 돌려줄 값만 남긴다.
    content = {k: v for k, v in body.items() if k != "request_id"}
    now = datetime.now(timezone.utc)

    # (screen, account_id) 복합 PK 충돌 시 덮어쓴다 — 같은 화면을 두 탭에서 열면 나중 저장이 이긴다.
    stmt = pg_insert(admin_drafts).values(
        screen=screen, account_id=me.account_id, content=content, updated_at=now)
    stmt = stmt.on_conflict_do_update(
        index_elements=[admin_drafts.c.screen, admin_drafts.c.account_id],
        set_={"content": content, "updated_at": now})
    db.execute(stmt)
    db.commit()

    # version 은 1 고정(모듈 주석 — 카운터 컬럼이 없다). saved_at 은 KST ISO 로 내보낸다.
    return {"screen": screen, "saved_at": now.astimezone(KST).isoformat(), "version": 1}
