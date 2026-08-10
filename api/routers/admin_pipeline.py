"""데이터 파이프라인 작업(AD-004) — 재수집·재적재 잡의 생성·조회.

⚠️ 아직 뼈대만 있다. 엔드포인트는 이 파일 안에 추가한다.

이 파일을 미리 만들어 둔 이유는 하나다 — **api/main.py 를 아무도 안 건드리게 하기 위해서다.**
라우터 등록은 이미 끝나 있으므로(main.py create_app), 여기에 @router.post(...) 를 더하면
그대로 서비스에 붙는다. 여러 명이 동시에 관리자 API 를 만드는 동안 main.py 는 모두가 고치는
파일이라 충돌이 확정적으로 나는 자리였다.

## 인증은 이미 걸려 있다

router 에 dependencies=[Depends(get_current_admin)] 가 붙어 있어, 여기 추가하는 모든
엔드포인트가 자동으로 인증을 요구한다(쿠키 없으면 401). 엔드포인트마다 CurrentAdmin 을
받을 필요가 없고, 깜빡해서 인증 없이 열리는 사고도 나지 않는다.

실행자 정보(email·role)가 실제로 필요한 핸들러에서만 `me: CurrentAdmin` 을 추가로 받으면 된다.

## 만들 것 (web/src/routes/admin/pipeline/api.ts 가 계약 정본)

    POST /api/admin/jobs        생성  -> 202 + PipelineJob 본문
    GET  /api/admin/jobs        목록  -> {items, total, page, size} · 기본 created_at:desc
    GET  /api/admin/jobs/{id}   상세

지켜야 할 것 (docs/backend-structure.md §3 함정 #8·#9)

- 생성은 **202 + 본문**. 204 나 빈 본문이면 화면이 방금 만든 잡을 못 찾는다.
- 동시 실행 초과는 **409 + retryable=false**. constants.ts PIPELINE_CONCURRENCY=1 이 근거다.
  QUEUED/RUNNING 인 잡이 있으면 409. retryable 을 true 로 주면 [다시 시도] 버튼이 떠서
  계속 409 를 맞는다.
- 목록 정렬이 기능 계약이다. 프론트는 "진행 중 작업은 항상 1페이지"라고 가정하고 page=1
  에서만 active job 을 찾는다(Pipeline.tsx:120-125). 정렬이 깨지면 폴링이 조용히 오작동한다.
- steps 는 6단계(수집·변환·청킹·검증·색인·반영)를 생성 시 전부 QUEUED 로 초기화한다.
  안 채우면 진행 표시가 빈 채로 뜬다.

## sync def 로 쓸 것

DB 접근(SQLAlchemy 동기 세션)이 블로킹이라 async def 로 두면 이벤트 루프를 막는다.
평범한 def 로 두면 FastAPI 가 스레드풀에서 돌린다(api/deps.py get_db 주석과 같은 이유).
"""
from fastapi import APIRouter, Depends

from api.deps import get_current_admin

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-pipeline"],
    # 라우터 전체에 인증. 여기 추가되는 엔드포인트는 전부 자동으로 보호된다.
    dependencies=[Depends(get_current_admin)],
)
