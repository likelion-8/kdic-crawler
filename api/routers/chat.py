"""POST /api/chat — SSE 스트리밍 챗 엔드포인트.

계층 규칙대로 얇게 유지한다: 요청 검증(ChatRequest) → 식별자 발급 → sse.chat_event_stream
호출 → StreamingResponse 반환. RAG 로직은 전부 api/rag/(engine·answer·sse)가 담당한다.

sync def 로 둔다: chat_event_stream 은 블로킹(검색·LLM) 동기 제너레이터라, StreamingResponse
가 이를 스레드풀에서 돌려 이벤트 루프를 막지 않는다.
"""
import uuid

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.rag import sse
from api.schemas.chat import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])


# response_model 은 못 쓴다 — 실제 반환은 SSE 스트림이라 FastAPI 가 검증·직렬화할 본문이 없다.
# 대신 responses 로 문서에만 노출한다. 이게 없으면 OpenAPI 의 200 스키마가 비어(`{}`) ChatResponse
# 계열 모델이 components 에 아예 안 실려서, 프론트가 Swagger 로 계약을 읽을 수 없다.
@router.post(
    "/chat",
    responses={
        200: {
            "description": "SSE 스트림. `event: <이름>\\ndata: <JSON>` 프레임으로 "
                           "accepted → answer_delta* → (sources) → (attachments) → done | error "
                           "순으로 흐른다. 아래 스키마는 done 프레임의 data 다.",
            "content": {"text/event-stream": {"schema": ChatResponse.model_json_schema()}},
        },
    },
)
def chat(req: ChatRequest):
    # session_id: 요청에 있으면 그대로(대화 이어가기), 없으면 새로 발급해 응답 done 에 실어준다.
    session_id = req.session_id or uuid.uuid4().hex
    # request_id: 이 '답변' 하나의 식별자(피드백 대상). 미들웨어의 요청추적 request_id 와 별개.
    request_id = uuid.uuid4().hex
    stream = sse.chat_event_stream(req.message, session_id, request_id)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # nginx 등 프록시가 SSE 를 버퍼링해 실시간성이 죽는 것을 막는다.
            "X-Accel-Buffering": "no",
        },
    )
