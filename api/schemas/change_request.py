"""변경 요청(change_requests) 요청/응답 스키마 — AD-002 삭제·제외 / AD-003 신규 적재.

계약 정본: web/src/routes/admin/knowledge (KnowledgePages.tsx · NewPageForm.tsx · types.ts),
web/src/mocks/handlers/admin.ts, web/src/lib/codes.ts(PendingAction/Status). 컬럼 정본은
src/schema.py change_requests.

⚠️ 요청 모델에 extra='forbid' 를 걸지 않는다 — 쓰기 요청엔 공통 규약상 request_id(멱등키)와
reason 이 섞여 오고, forbid 면 400 으로 죽는다(pipeline.py 와 같은 판단, backend-structure §3).
pydantic v2 기본 extra='ignore' 라 모르는 필드는 조용히 무시된다.
"""
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ChangeRequestCreate(BaseModel):
    """생성 요청 본문. action/target_page_id/reason/request_id 는 필수(위험 작업 사유·멱등키).
    action 값 검증과 존재 검증은 라우터가 한다(FK 없음). ADD 는 payload 에 새 페이지 객체를
    싣고, target_title/business_function 은 목록 표시용 복사값(없으면 서버가 documents 에서 채움)."""
    action: str                                    # ADD / UPDATE / DELETE / EXCLUDE
    target_page_id: str
    reason: str
    request_id: str                                # 멱등키(같은 요청 재전송 방지)
    target_title: Optional[str] = None
    business_function: Optional[str] = None
    payload: Optional[dict[str, Any]] = None       # action='ADD' 의 새 페이지 객체(K8)


class ChangeRequestDecision(BaseModel):
    """확정(approve)·버리기(reject) 본문. 결정 사유는 감사 기록으로 남긴다."""
    reason: str


class ChangeRequest(BaseModel):
    """변경 요청 1건 응답 — 프론트 ChangeRequest 와 필드 동일(14컬럼)."""
    id: str
    action: str
    target_page_id: str
    target_title: Optional[str] = None
    business_function: Optional[str] = None
    payload: Optional[dict[str, Any]] = None
    reason: str
    requested_by: str
    requested_at: datetime
    status: str                                    # PENDING / APPROVED / REJECTED
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    decision_reason: Optional[str] = None
    request_id: Optional[str] = None


class ChangeRequestList(BaseModel):
    """목록 봉투 — {items, total, page, size}. page 는 1-base(PipelineJobList 와 동일 형태)."""
    items: list[ChangeRequest] = Field(default_factory=list)
    total: int
    page: int
    size: int
