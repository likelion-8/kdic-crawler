"""운영 정책(AD-009) — 요청 제한·캐시·차단·추천 질문. **엔드포인트는 B 트랙 담당자가 채운다.**

빈 라우터로 자리만 잡아 둔 파일이다(사유는 admin_dashboard.py 상단과 같다).

## 만들 것 (8종)

    GET  /api/admin/ops-policy
    PUT  /api/admin/ops-policy                     부분 패치 + 새 version 반환(O5)
    GET  /api/admin/cache/stats
    POST /api/admin/cache/purge?scope=query|all
    GET  /api/admin/blocks
    POST /api/admin/blocks/{id}/release
    PUT  /api/admin/suggested-questions            전체 교체. reason 필수(O2)
    POST /api/admin/suggested-questions/validate   금칙어 검사

경로가 /ops-policy · /cache · /blocks · /suggested-questions 로 갈려서 prefix 를
/api/admin 까지만 잡았다. 각 경로를 데코레이터에 그대로 적을 것.

## 쓸 테이블 (2026-08-12 신설, src/schema_admin.py)

    ops_policy          버전마다 새 행. 가장 큰 version 이 현재 적용본이다.
                        정책 항목이 기획서에 없어 policy JSONB 로 열어 뒀다 —
                        모양 정본은 promptops/api.ts 의 OpsPolicy.
    query_cache         cache_key(정규화 해시) PK. hit_count 로 적중률을 낸다.
    rate_limit_blocks   expires_at 필수(O4). released_at 은 수동 해제 기록.

## 확정된 팀 결정

- PUT /ops-policy 는 **부분 패치**(변경된 필드만)를 받고 응답에 새 version 을 담는다(O5).
  burst_per_10s 는 읽기 전용이다.
- 🔴 PUT /ops-policy 는 위험 작업이라 **서버가 재인증 유효성을 독립 검증**한다(P5).
  프론트 판정은 우회 가능하다. A 트랙이 만드는 재인증 헬퍼를 가져다 쓸 것.
- 차단 목록은 expires_at 이 필수다(O4). 화면이 만료된 행의 [해제]를 비활성화하고 남은
  시간을 확인 모달에 표시한다.
- ⚠️ SuggestedQuestion.click_count 를 화면은 '최근 7일 클릭'으로 렌더한다(O3). 그런데
  추천 칩 클릭 수집 경로 자체가 계약에 없다 — 7일 윈도우 집계를 줄 수 없으면 필드를
  null 로 두고 프론트에 알려라. **0 을 넣으면 '아무도 안 눌렀다'는 거짓이 된다.**
- 모든 쓰기에 api/deps.py 의 write_activity_log 를 남긴다. 본 작업 commit 뒤에 부를 것
  (그 함수가 스스로 commit 한다 — deps.py:279-284).
"""
from fastapi import APIRouter, Depends

from api.deps import get_current_admin

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-ops"],
    dependencies=[Depends(get_current_admin)],
)
