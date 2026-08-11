"""신규 URL 문서 Preview 요청·응답 계약."""

from typing import Literal

from pydantic import BaseModel, Field


BusinessFunction = Literal[
    "예금자보호제도",
    "예금보험금 안내",
    "고객 미수령금 신청",
    "착오송금 반환 신청",
    "채무조정 안내",
    "은닉재산 신고",
]


class PreviewCreateRequest(BaseModel):
    """POST /api/admin/previews.

    ``request_id``는 관리자 쓰기 요청의 공통 멱등 키다. Preview 자체는 운영
    테이블에 저장하지 않지만 프론트 공통 계약을 유지하기 위해 받는다.
    """

    request_id: str = Field(min_length=1, max_length=128)
    url: str = Field(min_length=1, max_length=2048)
    business_function: BusinessFunction | None = None
    required: bool = True
    page_title: str = Field(default="", max_length=500)
    sub_category: str = Field(default="", max_length=1000)
    note: str = Field(default="", max_length=4000)
    summary: str = Field(default="", max_length=4000)


class PreviewExtracted(BaseModel):
    page_id: str
    page_title: str
    business_function: BusinessFunction
    sub_category: str
    summary: str
    content_sha256: str


class PreviewChunk(BaseModel):
    chunk_id: str
    page_id: str
    seq: int
    title: str
    chars: int
    preview: str


class PreviewResponse(BaseModel):
    preview_id: str
    url: str
    extracted: PreviewExtracted
    split_rule: str
    chunks: list[PreviewChunk]
    warnings: list[str]
    sub_category_extraction_failed: bool


class PreviewRejectRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=4000)


class PreviewRejectResponse(BaseModel):
    preview_id: str
    status: Literal["REJECTED"] = "REJECTED"
    purge_at: str
