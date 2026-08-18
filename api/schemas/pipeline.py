"""AD-004 데이터 파이프라인 작업(재수집·재적재 잡) 요청/응답 스키마.

계약 정본: web/src/routes/admin/pipeline/api.ts 의 PipelineJob 인터페이스.
enum 값 정본: web/src/lib/codes.ts (JobType/JobStatus/JobErrorCode).
단계 이름 정본: web/src/lib/constants.ts PIPELINE_STEPS.

⚠️ 요청 모델에 extra='forbid' 를 걸지 않는다 — 쓰기 요청엔 공통 규약상 request_id(멱등키)와
reason 이 섞여 오는데, forbid 면 400 으로 죽는다(backend-structure §3, deps 규약). pydantic v2
기본값 extra='ignore' 라 모르는 필드는 조용히 무시된다.
"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class JobStep(BaseModel):
    """7단계(수집·변환·청킹·검증·게이트·색인·반영) 중 한 단계의 진행상황.
    정본은 src/worker.py STEPS."""
    name: str
    status: str  # QUEUED | RUNNING | SUCCESS | FAILED | SKIPPED
    elapsed_ms: Optional[int] = None
    count: Optional[int] = None  # 단계별 처리 건수
    # 단계가 남긴 구조화 정보(2026-08-18). 게이트가 판정(passed·metrics·targets·failures·
    # summary)을 싣는다 — 이 필드가 없으면 response_model 이 잘라내 화면에 '—'만 남는다
    # (전날 prefilled_sources 와 같은 함정). 모양은 src/index_gate.evaluate 결과 + summary.
    detail: Optional[dict] = None


class JobError(BaseModel):
    """작업 실행 실패 정보. status=FAILED 일 때만 채워진다(이번 범위에선 안 씀)."""
    code: str  # codes.ts JobErrorCode (STAGE_TIMEOUT 등)
    stage: str
    detail: str


class PipelineJob(BaseModel):
    """작업 1건 응답 — 프론트 PipelineJob 과 필드 동일."""
    id: str
    type: str
    status: str
    targets: list[str] = Field(default_factory=list)
    reason: str = ""
    created_by: str
    created_at: datetime
    steps: list[JobStep] = Field(default_factory=list)
    error: Optional[JobError] = None
    rollback_of: Optional[str] = None
    target_summary: Optional[str] = None
    target_count: Optional[int] = None
    index_impact: Optional[str] = None
    metrics: Optional[dict[str, Any]] = None
    # 적재 파라미터(2026-08-18) — {"chunk_mode": ...}. 이력 표가 "어느 청킹으로 돌렸나"를 그린다
    params: Optional[dict[str, Any]] = None


class PipelineJobList(BaseModel):
    """목록 봉투 — {items, total, page, size}. page 는 1-base. KnowledgePageList 와 같은 형태."""
    items: list[PipelineJob]
    total: int
    page: int
    size: int


class JobCreate(BaseModel):
    """작업 생성 요청 본문. type 만 필수. targets/reason 은 선택.
    (request_id 등 공통 규약 필드가 섞여 와도 extra=ignore 라 문제없다.)"""
    type: str
    targets: list[str] = Field(default_factory=list)
    reason: str = ""
    # 적재 파라미터(2026-08-18). 재적재 모달의 청킹 모드 — chunking.build_units 의 mode.
    # 종전에는 프론트가 보내도 여기 없어 조용히 버려졌다(extra=ignore 의 함정).
    chunk_mode: Optional[str] = None


class JobCancel(BaseModel):
    """취소 사유. 공통 request_id가 함께 와도 Pydantic 기본 정책으로 무시한다."""
    reason: str = ""


class JobRetry(BaseModel):
    """재시도 사유. 실패한 잡과 같은 type·targets 로 새 잡을 만든다."""
    reason: str = ""


class JobRollback(BaseModel):
    """긴급 롤백 사유. ADMIN + 재인증이 필요하다(P5).

    본문에 password 를 싣지 않는다 — 재확인은 POST /api/admin/reauth 를 **먼저** 따로
    호출해 끝낸다(access/api.ts runRisky). 여기서 또 받으면 비밀번호가 두 요청에 남는다.
    """
    reason: str = ""


class ChangedPage(BaseModel):
    """원본 사이트 본문이 바뀐 것으로 감지된 페이지 한 줄(P3)."""
    page_id: str
    title: str
    # 원본 사이트에서 읽은 제목. 우리 쪽 제목과 다르면 페이지가 통째로 바뀐 신호다.
    # 별도 컬럼이 없어 지금은 저장된 제목을 그대로 쓴다(라우터 주석 참고).
    source_title: str
    detected_at: str


class ChangedPagesResponse(BaseModel):
    """GET /pipeline/changes · POST /pipeline/changes/recheck 공통 응답.

    ⚠️ last_checked_at 은 '마지막으로 재확인을 실행한 시각'이고, 원천은 활동 로그다
    (라우터 주석). 한 번도 실행한 적이 없으면 빈 문자열이다 — 화면의 RefreshBar 가
    빈 값을 '—' 로 그린다.
    """
    last_checked_at: str = ""
    items: list[ChangedPage] = Field(default_factory=list)
    # [지금 확인]이 실제 감지 잡을 만들었는지(2026-08-18). 다른 잡이 진행 중이면 False —
    # 화면이 "지금은 확인할 수 없습니다(다른 작업 진행 중)"를 알린다. GET 은 항상 False.
    job_queued: bool = False


class JobEstimate(BaseModel):
    """확인 모달에 띄우는 대상 건수·예상 소요(P3).

    ⚠️ estimated_minutes 는 **실측이 아니다.** 완료된 잡이 아직 한 건도 없어(워커 미구현)
    평균을 낼 원천이 없다. 라우터의 페이지당 초 상수에서 계산한 어림값이고, 잡이 실제로
    돌기 시작하면 그 기록의 평균으로 갈아야 한다.
    """
    type: str
    target_count: int
    estimated_minutes: int
