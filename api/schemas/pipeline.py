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
    """6단계(수집·변환·청킹·검증·색인·반영) 중 한 단계의 진행상황."""
    name: str
    status: str  # QUEUED | RUNNING | SUCCESS | FAILED | SKIPPED
    elapsed_ms: Optional[int] = None
    count: Optional[int] = None  # 단계별 처리 건수(아직 서버가 안 채움)


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


class JobCancel(BaseModel):
    """취소 사유. 공통 request_id가 함께 와도 Pydantic 기본 정책으로 무시한다."""
    reason: str = ""
