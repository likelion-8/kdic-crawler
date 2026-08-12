"""평가(AD-006) 요청/응답 스키마 — 실행 이력·게이트 판정·문항 편집.

계약 정본: web/src/routes/admin/evaluation/api.ts (EvaluationRun · GateDetail · EvalItem ·
EvalItemInput · EvalItemValidation · EvalApplyRequest/Result). 컬럼 정본은
src/schema_admin.py(evaluation_runs · evaluation_results · testset_items)와
src/schema.py(evaluation_dataset · documents).

## 확정된 팀 결정이 스키마에 박힌 지점
- metrics 는 숫자 4필드가 아니라 [{label, value}] 배열이다(E1). value 는 반올림까지 끝낸
  **문자열**(점수 3자리·퍼센트 1자리·초 1자리) — 서버가 표기를 확정한다.
- gate 는 passed 와 기준별 판정을 함께 담는다(E10). 목표값도 서버가 내려준다(E4).
- 코드 값(target·source·status·intent·question_type·business_function)은 폐집합으로 못 박지
  않고 str 로 둔다(change_request.py/activity.py 와 같은 방침 — 어휘가 늘어도 스키마 불변).

## ⚠️ testset_items 에 없는 필드
EvalItem 은 question_type·intent 를 요구하지만 testset_items(편집용 사본)에는 두 컬럼이
없다(원본 evaluation_dataset 에만 있다). 지어내지 않고 Optional 로 열어 null 을 낸다 —
처리 방침은 docs/evaluation_api_notes.md 에 정리했다(로그 화면의 원천 없는 필드와 같은 원칙).
"""
from typing import Any, Optional

from pydantic import BaseModel, Field


# ──────────────────────────────── 실행 이력 (GET /runs) ──────────────────────

class RunMetric(BaseModel):
    """이력 표 '핵심 결과' 한 칸. 대상별로 축이 다르다(RAG=정확도/MRR/생성)."""
    label: str
    value: str                              # 반올림까지 끝낸 표시 문자열(서버가 확정)


class RunGate(BaseModel):
    """목록 행의 게이트 요약. 상세(GateDetail)와 같은 값을 읽도록 evaluation_runs.gate 에서 온다."""
    passed: bool
    smoke_passed: int = 0
    smoke_total: int = 0
    blocked_reason: Optional[str] = None


class EvaluationRun(BaseModel):
    """평가 실행 1건. api.ts EvaluationRun 과 1:1."""
    run_id: str
    target: str                             # '운영 설정' | 'RAG 초안' | '프롬프트 초안'
    source: str                             # RUN_SOURCES(수동 실행 등)
    started_at: str                         # KST ISO
    finished_at: Optional[str] = None       # 실행 중이면 null
    status: str                             # JobStatus (RUNNING/DONE/FAILED)
    item_count: int = 0
    metrics: list[RunMetric] = Field(default_factory=list)
    gate: RunGate
    follow_up: Optional[str] = None
    testset_version: int
    improved_by_composition: Optional[bool] = None


class EvaluationRunList(BaseModel):
    """목록 봉투 — Page<EvaluationRun> = {items, total, page, size}."""
    items: list[EvaluationRun] = Field(default_factory=list)
    total: int
    page: int
    size: int


# ──────────────────────────── 게이트 판정 상세 (GET /runs/{id}/gate) ─────────

class GateCriterion(BaseModel):
    """게이트 상세 표 1행. target/result 는 화면 표기 문자열 그대로(수정 불가, E4)."""
    label: str                              # '검색 정확도@5' · 'Smoke 30문항'
    target: str                             # '0.92 이상' · '30/30' — 서버가 내려준다
    result: str
    passed: bool


class GateFailedItem(BaseModel):
    """미달 실행에서만(H8). evaluation_results 의 passed=false 행에서 온다."""
    item_id: str
    question: str
    expected_source: str
    actual_top1: str
    score: float


class GateDetail(BaseModel):
    """게이트 판정 상세. api.ts GateDetail 과 1:1."""
    run_id: str
    target: str
    source: str
    started_at: str
    criteria: list[GateCriterion] = Field(default_factory=list)
    latest_smoke: str = ""
    failed_items: list[GateFailedItem] = Field(default_factory=list)


# ──────────────────────────────── 문항 (GET /items) ─────────────────────────

class ExpectedSource(BaseModel):
    """기대 출처 — 표시 포맷 '{doc_id} · {제목}'. 원천은 documents(page_id·page_title)."""
    doc_id: str
    title: str


class EvalItem(BaseModel):
    """평가셋 문항 1건. api.ts EvalItem 과 1:1.

    ⚠️ question_type·intent 는 testset_items 에 컬럼이 없어 Optional 이다(모듈 주석 참고).
    프론트 타입은 non-null 이므로 값이 채워지려면 컬럼 추가(제안) 또는 프론트 조율이 필요하다.
    """
    item_id: str
    question: str
    business_function: Optional[str] = None
    question_type: Optional[str] = None     # ⚠️ 원천 없음(testset_items 컬럼 없음) → null
    intent: Optional[str] = None            # ⚠️ 원천 없음(testset_items 컬럼 없음) → null
    expected_source: Optional[ExpectedSource] = None


class EvalItemList(BaseModel):
    """목록 봉투 — Page<EvalItem>."""
    items: list[EvalItem] = Field(default_factory=list)
    total: int
    page: int
    size: int


# ────────────────────────── 문항 검증·반영 (POST /items/validate · /apply) ──

class EvalItemInput(BaseModel):
    """인라인 입력 행이 보내는 값. api.ts EvalItemInput.

    extra 를 막지 않는다 — validate 는 ignore_id 를, apply 항목은 공통 규약상 request_id/reason
    이 섞여 올 수 있다(change_request.py 와 같은 판단). pydantic v2 기본 extra='ignore'.
    """
    item_id: str = ""
    question: str
    business_function: Optional[str] = None
    question_type: Optional[str] = None
    intent: Optional[str] = None
    expected_source_id: str = ""
    ignore_id: Optional[str] = None         # 중복 질문 검사에서 자기 자신 제외(기존 행 편집)


class EvalFieldError(BaseModel):
    """검증에 걸린 '필드'. 걸린 필드만 붉게 칠하려면 field 가 필수다(E6)."""
    field: str                              # 'item_id' | 'question' | 'expected_source'
    message: str


class EvalItemValidation(BaseModel):
    """저장 시 자동 검증 결과. ok 일 때만 확정된 문항(item)을 함께 준다."""
    ok: bool
    errors: list[EvalFieldError] = Field(default_factory=list)
    item: Optional[EvalItem] = None


class ExcludeInput(BaseModel):
    """제외 1건 — item_id + 사유(필수). 행을 지우지 않고 표시만 한다(E6)."""
    item_id: str
    reason: str


class EvalApplyRequest(BaseModel):
    """편집 묶음 반영 요청. adds/edits/excludes + reason(위험 작업 사유, 공통 규약).

    extra 를 막지 않는다(request_id 멱등키가 함께 온다). reason 은 apiRequest 가 본문에 넣는다.
    """
    adds: list[EvalItemInput] = Field(default_factory=list)
    edits: list[EvalItemInput] = Field(default_factory=list)
    excludes: list[ExcludeInput] = Field(default_factory=list)
    reason: Optional[str] = None
    request_id: Optional[str] = None


class EvalApplyResult(BaseModel):
    """반영 결과 — 버전 증가 1회 + 재측정 1회(E7)."""
    testset_version: int
    rerun_id: str


# ──────────────────────────── 코퍼스·후보 (GET /corpus · POST /candidates) ──

class CorpusSearchResult(BaseModel):
    """기대 출처 자동완성 결과 — {items:[ExpectedSource]}."""
    items: list[ExpectedSource] = Field(default_factory=list)


class CandidateResult(BaseModel):
    """대화 로그 → 문항 후보 등록 결과(AD-005 연동). api.ts addEvalCandidate 응답."""
    candidate_id: str
    status: str
