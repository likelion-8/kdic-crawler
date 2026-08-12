"""평가(AD-006) — 실행 이력·게이트 판정·문항 편집. **엔드포인트는 C 트랙 담당자가 채운다.**

빈 라우터로 자리만 잡아 둔 파일이다(사유는 admin_dashboard.py 상단과 같다).

## 만들 것 (7종)

    GET  /api/admin/evaluations/runs                목록
    GET  /api/admin/evaluations/runs/{run_id}/gate  게이트 판정 상세
    GET  /api/admin/evaluations/items               문항 목록(Page 봉투)
    POST /api/admin/evaluations/items/validate      필드별 오류 [{field, message}]
    POST /api/admin/evaluations/apply               {adds, edits, excludes} + reason
    GET  /api/admin/evaluations/corpus?q=           기대 출처 선택용
    POST /api/admin/evaluations/candidates          대화 로그 -> 문항 후보(AD-005 연동)

## 실행 로직을 새로 짜지 마라

    src/eval/eval_pipeline_retrieval.py
    src/eval/eval_pipeline_generation.py

이미 있다. 감싸서 결과를 테이블에 적는 것이 이 라우터의 일이다.
문항 테이블(evaluation_dataset=골든셋, test_set=held-out)도 이미 있다.

## 쓸 테이블 (2026-08-12 신설, src/schema_admin.py)

    evaluation_runs     실행 1회. metrics·gate 는 JSONB — 대상별 지표 축이 달라서다.
    evaluation_results  실행의 문항별 결과. item_id 는 FK 를 안 걸었다(문항이 빠져도
                        지난 실행 결과는 그대로 남아야 한다).
    testset_items       편집 가능한 문항 + testset_version. 제외는 행을 지우지 않고
                        excluded 플래그 + exclude_reason 으로 표시한다.

## 확정된 팀 결정

- metrics 는 숫자 4필드가 아니라 [{label, value}] 배열이다(E1). 대상별 축이 다르다
  (RAG=정확도/MRR/생성, 프롬프트=회귀/인용/중대 위반). 반올림(점수 3자리·퍼센트 1자리)까지
  서버가 끝낸 문자열로 준다.
- metrics 에 생성 성공률(generation_success_rate)을 넣는다(E2). 환각률로 대체하지 마라 —
  의미가 다르다.
- 🔴 게이트 목표값(0.92↑ / 0.80↑ / 99.5%↑ / 10초↓ / 30of30)은 **반드시 서버가 내려준다**(E4).
  프론트 상수로 박으면 '관리자 화면에서 기준을 낮추는 우회'를 막는 설계가 무너진다.
- run.gate.passed 와 기준별 판정을 **서버가 함께 계산**한다(E10). 목록은 '통과'인데 상세는
  '미달'로 갈리면 안 된다. 그래서 두 값을 evaluation_runs.gate 한 곳에 담아 둔다.
- 반영(apply)은 **버전 증가 1회 + 재측정 1회가 한 트랜잭션**이다(E7). 여러 건을 편집해도
  재측정은 한 번이다.
- items/validate 는 필드별 오류를 준다 — 걸린 필드만 붉게 칠하려면 field 가 필수다(E6).

계약 정본: docs/frontend-handoff.md "E. 평가" 절(E1~E10) ·
web/src/routes/admin/evaluation/api.ts
"""
from fastapi import APIRouter, Depends

from api.deps import get_current_admin

router = APIRouter(
    prefix="/api/admin/evaluations",
    tags=["admin-evaluations"],
    dependencies=[Depends(get_current_admin)],
)
