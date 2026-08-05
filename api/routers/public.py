"""공개(비인증) 엔드포인트 — readiness 헬스체크.

계층 규칙: 라우터는 얇게 유지한다. 여기서는 상태 소스(DB·워밍업)를 조합해 응답만
만든다. 실제 리소스 로딩/판단은 api/rag/engine.py 와 src/db.py 소관이다.

liveness 와 readiness 를 나눈다:
  - liveness  : api/main.py 의 GET /health — 프로세스가 떠 있는지만(외부 의존성 안 봄).
  - readiness : 이 파일의 GET /api/health — DB·워밍업까지 확인해 chat 가용성을 판단.
"""
import logging

from fastapi import APIRouter

from api.rag.engine import is_warmed_up

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["public"])


def _db_ok() -> bool:
    """Supabase 연결 가능 여부를 가벼운 쿼리(SELECT 1)로 확인한다. 실패는 로그만 남기고
    False 를 돌려준다 — 헬스체크가 예외로 죽으면 안 되기 때문이다."""
    try:
        from sqlalchemy import text

        from db import get_engine
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("health: Supabase 연결 확인 실패", exc_info=True)
        return False


@router.get("/health")
def health():
    """readiness probe — DB·워밍업·채팅 가용성 확인.

    sync def 로 둔다: _db_ok() 의 DB 쿼리는 블로킹이라 async 로 두면 이벤트 루프를 막는다.
    sync 로 두면 FastAPI 가 스레드풀에서 돌린다.

    워밍업이 안 됐거나 DB 연결이 안 되면 chat 을 못 쓰므로 disabled_features 에 "chat" 을
    넣고 status 를 degraded 로 낮춘다.
    """
    warmed = is_warmed_up()
    db_ok = _db_ok()
    chat_available = warmed and db_ok

    body = {
        "status": "ok" if chat_available else "degraded",
        "maintenance": False,
        "disabled_features": [] if chat_available else ["chat"],
    }
    # user_message 는 선택 필드 — 프론트가 점검 안내/입력창 잠금에 쓴다. 정상일 땐 생략한다.
    if not chat_available:
        body["user_message"] = "챗봇을 준비 중입니다. 잠시 후 다시 시도해 주세요."
    return body
