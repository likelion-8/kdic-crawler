"""RAG 파라미터(AD-007) — 검색·생성 파라미터 조정. **엔드포인트는 D 트랙 담당자가 채운다.**

빈 라우터로 자리만 잡아 둔 파일이다(사유는 admin_dashboard.py 상단과 같다).

## 만들 것 (6종)

    GET  /api/admin/rag-params                    params 메타 + current + draft + gate
    POST /api/admin/rag-params/evaluate           응답에 draft_signature 포함(R2)
    POST /api/admin/rag-params/ab-search
    POST /api/admin/rag-params/apply              reason 필수. 게이트 미통과면 409(R3)
    GET  /api/admin/rag-params/history
    POST /api/admin/rag-params/history/{id}/rollback

## 🔴 이 화면의 본체는 API 가 아니라 src/runtime_config.py 다

지금 파라미터는 전부 파이썬 상수다:

    src/pipeline.py           K_CANDIDATES=20 · K_FINAL=5 · USE_RERANKER=False ·
                              USE_QUERY_DECOMPOSITION=True · USE_SOURCE_RECHECK=True
    src/query_planner.py      USE_QUERY_PLANNER=True
    src/candidate_ranking.py  MIN_TOP1_SCORE=0.35
    src/retrieval.py          HYBRID_LINEAR_ALPHA=0.4

**상수를 DB 조회로 그냥 바꾸면 챗봇이 죽는다.** DB 가 느리거나 비면 답변 경로가 통째로
멈춘다. 폴백 로더(get_param(name, default))로 감싸서, **DB 에 값이 없으면 오늘과 완전히
똑같이 동작**하게 만든다. 그러면 롤백은 DB 행 삭제 한 번이다.

⚠️ 각 상수 주석에 적힌 실측 근거(리랭커 CPU 96초 · MIN_TOP1_SCORE 0.35 도출 · 플래너
100문항 벤치마크)를 지우지 마라. DB 로 옮겨도 "왜 이 기본값인가"는 코드에 남아야 한다.

## 쓸 테이블 (2026-08-12 신설, src/schema_admin.py)

    rag_param_versions   status 로 current(1) · draft(1) · history(N) 를 표현한다.
                         각 1개 제약은 부분 유니크 인덱스로 DB 가 강제한다 —
                         애플리케이션 규칙으로만 두면 동시 요청 두 개가 current 를 둘 만든다.

## 확정된 팀 결정

- 🔴 파라미터 메타(현행값·반영 시점·min/max/step·옵션·슬라이더 눈금)를 **서버가 내려주는**
  형태로 만든다(R1). 그래야 값이 바뀌어도 프론트 재배포가 필요 없고, '목업 숫자 하드코딩
  금지'도 지켜진다.
- evaluate 응답에 draft_signature(평가한 초안의 지문)를 담는다(R2). '평가 이후 초안을
  수정하면 평가 무효화'를 판정하려면 서버가 무엇을 평가했는지 알려 줘야 한다.
- apply 는 게이트 미통과 시 **409** 로 막는다(R3). 실패 응답에 현재 적용값 전문을 실어
  주면 화면이 '실패 시 이전 버전 유지'를 그대로 다시 그린다.
- 쓰기 권한은 EDITOR 로 가정한다(R4).

## 검증 의무 (이 트랙만)

상수를 옮길 때마다 챗봇이 그대로 도는지 확인한다.
  1) DB 가 빈 상태에서 기존 테스트 전체 통과
  2) 실제 질문 하나를 E2E 로 태워 답변·출처가 이전과 같은지
  3) DB 에 값을 넣었을 때 그 값이 실제로 반영되는지
회귀 기준선: docs/pipeline_heldout_baseline_89q.md
"""
from fastapi import APIRouter, Depends

from api.deps import get_current_admin

router = APIRouter(
    prefix="/api/admin/rag-params",
    tags=["admin-rag-params"],
    dependencies=[Depends(get_current_admin)],
)
