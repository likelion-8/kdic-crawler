"""대화 복원 스키마 — GET /api/sessions/{session_id}.

프론트 types.ts 에 이 스키마가 없다(기획서 역기재 대상). 목이 정의한 모양을 프론트가 그대로
옮겨 쓰고 있어서(web/src/routes/chat/ChatPage.tsx:84 RestoredMessage/RestoredSession) 그쪽을
정본으로 삼아 필드를 맞췄다.
"""
from typing import Optional

from pydantic import BaseModel, Field

from api.schemas.chat import Attachment
from api.schemas.common import SourceItem


class RestoredResponse(BaseModel):
    """답변 말풍선에 딸린 것. 프론트는 Pick<ChatResponse,'sources'|'attachments'|'out_of_scope'>
    로 받는다 — sub_answers 자리가 없어서 복합 질문의 하위 묶음 구조는 복원되지 않는다
    (출처는 잃지 않도록 conversation.py 가 하위의 것을 평탄화해 저장한다)."""
    sources: list[SourceItem] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)
    out_of_scope: bool = False


class RestoredMessage(BaseModel):
    role: str = Field(description="'user' 또는 'assistant'.")
    text: str
    # 말풍선에 찍는 시각. 없으면 프론트가 시각을 아예 그리지 않는다 — 복원된 대화에 '지금'을
    # 찍으면 90분 전 대화에 방금 시각이 붙어 거짓이 되므로 저장된 시각을 그대로 준다.
    at: Optional[str] = Field(default=None, description="ISO8601. 이 메시지가 오간 시각.")
    # 피드백 대상 식별자. 답변 말풍선만 갖는다.
    request_id: Optional[str] = None
    # 사용자 메시지는 비운다.
    response: Optional[RestoredResponse] = None


class RestoredSession(BaseModel):
    session_id: str
    # 이 시각이 24시간(CONVERSATION_RESTORE_WINDOW_H)보다 오래되면 서버가 404 를 준다.
    last_activity_at: str
    messages: list[RestoredMessage] = Field(default_factory=list)
