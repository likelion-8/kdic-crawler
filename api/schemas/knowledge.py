"""관리자 지식베이스 목록(AD-002) 응답 스키마.

프론트는 목록에서 제목·URL·업무를 필터링한 뒤, 같은 레코드로 상세 패널도 렌더링한다.
따라서 목록 응답에 필요한 메타데이터를 별도 조회 없이 모두 담는다.
"""
from typing import Literal

from pydantic import BaseModel


class KnowledgeFormLink(BaseModel):
    label: str
    url: str


class KnowledgePage(BaseModel):
    page_id: str
    source_url: str
    business_function: str
    sub_category: str
    page_title: str
    required: bool
    note: str
    summary: str
    collected_at: str
    content_sha256: str
    chunk_count: int
    list_state: Literal["최신", "변경 감지", "적용 대기"]
    index_status: str
    asset_counts: dict[str, int]
    form_links: list[KnowledgeFormLink]
    owner: str
    split_rule: str
    collection_status: str
    collection_note: str = ""
    link_check: str = ""
    first_indexed_at: str | None = None
    pending_change_request_id: str | None = None
    pending_change_action: str | None = None


class KnowledgePageList(BaseModel):
    items: list[KnowledgePage]
    total: int
    page: int
    size: int


class KbChunk(BaseModel):
    """상세 패널의 청크 목록 한 줄. `#{seq} · {title} ({chars}자)`로 표기된다.

    title은 저장된 값이 아니라 본문에서 만들어 내는 표시용 값이다. document_chunks에는
    청크 제목에 해당하는 컬럼이 없고, 코퍼스(chunks_all.jsonl)에도 없다.
    """

    chunk_id: str
    page_id: str
    seq: int
    title: str
    chars: int
    preview: str


class KbChunkList(BaseModel):
    items: list[KbChunk]
    total: int
    page: int
    size: int
