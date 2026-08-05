"""피드백·추천질문 스키마 — 프론트 lib/api/types.ts 의 FeedbackRequest/FeedbackPatch/
FeedbackResponse/Suggestion 과 필드가 1:1 로 같다.

피드백은 두 번에 나눠 들어온다. 👍/👎 는 누르는 즉시 POST 로 오고, 👎 일 때만 뒤이어 사유
칩·자유 의견이 PATCH 로 온다. 그래서 vote 만 필수고 나머지는 나중에 채워지는 구조다.
"""
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# 자유 의견 길이 상한. 프론트 constants.ts 의 FEEDBACK_FREETEXT_MAX 와 같은 값이어야 한다
# (프론트도 200자에서 입력을 막는다).
FEEDBACK_COMMENT_MAX = 200


class FeedbackRequest(BaseModel):
    """POST /api/feedback — 👍/👎."""
    # 피드백을 붙일 '답변'의 id. ChatResponse.request_id(= rag_runs.request_id)와 같은 값이다.
    # 멱등키로 쓰이는 request_id 와 뜻이 달라 프론트가 이름을 나눠 보낸다.
    answer_request_id: str = Field(min_length=1, description="대상 답변의 식별자.")
    session_id: str = Field(min_length=1, description="그 답변이 속한 세션 식별자.")
    vote: str = Field(description="'up' 또는 'down'.")

    @field_validator("vote")
    @classmethod
    def _vote_allowed(cls, v: str) -> str:
        if v not in ("up", "down"):
            raise ValueError("vote는 'up' 또는 'down'이어야 합니다.")
        return v


class FeedbackPatch(BaseModel):
    """PATCH /api/feedback/{feedback_id} — 👎 사유 보완.

    reason_codes 가 비어도 comment 만 있으면 받아야 한다 — 프론트는 '칩 또는 의견 중 하나라도'
    있으면 등록 버튼을 활성화한다(핸드오프 §6 B21). 둘 다 비었을 때만 거부한다.
    """
    reason_codes: list[str] = Field(default_factory=list, description="codes.ts ReasonCode 목록.")
    comment: Optional[str] = Field(
        default=None, max_length=FEEDBACK_COMMENT_MAX,
        description=f"자유 의견(최대 {FEEDBACK_COMMENT_MAX}자).")


class FeedbackResponse(BaseModel):
    feedback_id: str = Field(description="생성·갱신된 피드백의 id.")


class Suggestion(BaseModel):
    """GET /api/suggestions — 웰컴 화면의 자주 묻는 질문."""
    id: str
    text: str
    business_function: Optional[str] = Field(
        default=None, description="codes.ts BUSINESS_FUNCTIONS 6종 중 하나(한글 문자열).")
