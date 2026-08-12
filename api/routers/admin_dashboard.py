"""관리자 대시보드(AD-001) — 운영 요약 지표. **엔드포인트는 B 트랙 담당자가 채운다.**

이 파일은 자리만 잡아 둔 빈 라우터다. api/main.py 가 모두가 고치는 자리라, 각자 기능을
만들면서 등록 줄을 한 줄씩 더하면 머지 충돌이 확정적으로 난다(main.py 상단 주석). 미리
등록해 두면 작업이 이 파일 안에서만 끝난다.

## 만들 것 (3종)

    GET /api/admin/dashboard/summary
    GET /api/admin/dashboard/trend?range=7|30|90
    GET /api/admin/dashboard/resources?range=7|30|90

신규 테이블이 없다 — 이미 쌓인 데이터의 집계다. 원천은 rag_runs(질문 수·상태·latency) ·
feedback(좋아요/싫어요) · pipeline_jobs(작업) · admin_activity_logs(활동).

## 참고할 것

- api/routers/admin_logs.py 의 logs_summary() — 오늘(KST) 집계. 같은 KST 처리를 쓴다
- api/routers/admin_activity.py 의 activity_overview() — 현황 + facets 패턴
- docs/frontend-handoff.md "D. 대시보드" 절(D1~D4)
- web/src/mocks/handlers/extra/ad-dash-activity.ts — 응답 모양 정본

## 확정된 팀 결정

- 🔴 상시 지표 5종(indicators)은 **만들지 않는다**(D3, 2026-08-04 P-11). 임계치가 기획서
  어디에도 없고 5종 중 2종은 백엔드에 원천이 아예 없다. 기준 없이 경고를 띄우지 않는다.
- service.cause 를 서버가 정한다(D2) — 'ERROR_RATE'면 화면이 AD-005 실패 필터로,
  'PIPELINE'이면 AD-004 로 간다. 프론트는 이 값으로만 분기한다.
- 단계별 평균 응답시간은 **응답 8구간 고정 배열**이며 서버가 준 순서 그대로 그린다(D4).
- 표시 문자열(₩·M 등)은 서버가 완성해서 준다(D3'). 프론트가 단위를 지어내지 않는다.
- ⚠️ rag_runs.status 에는 옛 값 "success" 가 섞여 있다. admin_logs.py 의 LEGACY_STATUS
  매핑과 **같은 처리**를 할 것 — 안 하면 대시보드 숫자와 대화 로그 숫자가 어긋난다.
"""
from fastapi import APIRouter, Depends

from api.deps import get_current_admin

router = APIRouter(
    prefix="/api/admin/dashboard",
    tags=["admin-dashboard"],
    dependencies=[Depends(get_current_admin)],
)
