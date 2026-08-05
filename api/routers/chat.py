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
from api.schemas.chat import ChatRequest

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
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
