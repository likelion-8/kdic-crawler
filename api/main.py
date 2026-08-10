"""FastAPI 앱 조립 — 설정·미들웨어·예외처리·라우터·워밍업을 한 곳에서 붙인다.

실행:
    uvicorn api.main:app --reload        (저장소 루트에서)

이 파일에는 업무 로직을 두지 않는다. "무엇을 어떤 순서로 끼우는가"만 있고, 실제 일은
routers/ 와 rag/ 가 한다.

## 미들웨어 중첩 순서 (중요)

app.add_middleware() 는 나중에 추가한 것이 바깥쪽이다. 아래 등록 순서가 만드는 실제 모양:

    요청 --> RequestID --> CORS --> RateLimit --> 라우터
    응답 <-- RequestID <-- CORS <-- RateLimit <-- 라우터

- RequestID 가 가장 바깥: 요청 제한에 걸려 거절된 응답에도 id 가 찍혀야 추적이 된다.
- CORS 가 RateLimit 보다 바깥: 429 응답에도 CORS 헤더가 붙어야 브라우저가 본문을 읽고
  "잠시 후 다시 시도" 문구를 띄울 수 있다. 또 preflight(OPTIONS)가 요청 수에
  잡아먹히지 않는다.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.config import get_settings
from api.errors import register_exception_handlers
from api.middleware import REQUEST_ID_HEADER, RateLimitMiddleware, RequestIDMiddleware

logger = logging.getLogger(__name__)

# 요청 제한에서 빼는 경로. 헬스체크는 오케스트레이터/로드밸런서가 수초마다 호출하므로
# 여기에 걸리면 안 된다. /api/health(readiness)는 프론트도 점검 배너 판정에 주기적으로 부르므로,
# 같은 IP 의 실사용자 채팅 요청과 분당 한도를 나눠 쓰면 안 된다.
RATE_LIMIT_EXEMPT_PATHS = ("/health", "/api/health")


def _configure_logging(settings):
    """uvicorn 이 자기 로거를 이미 설정하므로 포맷을 새로 강제하지 않고 레벨만 맞춘다."""
    logging.basicConfig(
        level=logging.DEBUG if settings.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 한 번씩 실행되는 구간. yield 위는 시작, 아래는 종료."""
    settings = get_settings()
    _configure_logging(settings)
    logger.info("%s 시작 (environment=%s)", settings.app_name, settings.environment)

    if settings.warmup_on_startup:
        # src/retrieval.py 의 _build_engines() 는 BM25 색인·임베딩 모델·질문유형
        # 분류기를 처음 검색할 때 조립한다(수십 초). 이걸 첫 사용자가 물지 않도록
        # 여기서 미리 돌린다.
        #
        # 실패해도 서버는 뜬다. 여기서 예외를 올리면 프로세스가 죽어서 프론트는 그냥
        # "연결할 수 없음"만 보게 되고, /api/health 의 degraded 분기(=준비 중 안내 + 입력창
        # 잠금)가 도달 불가능한 죽은 코드가 된다. 뜨게 두면 health 가 chat 불가를 알려
        # 화면이 이유 있는 안내를 띄운다(원인은 아래 로그에 남는다).
        from api.rag.engine import warmup
        try:
            await warmup()
        except Exception:
            logger.exception("RAG 워밍업 실패 — chat 불가 상태로 기동한다(/api/health 가 degraded 를 알린다)")

    yield

    logger.info("%s 종료", settings.app_name)


def create_app() -> FastAPI:
    """앱 팩토리. 모듈 최상단에서 바로 만들지 않고 함수로 감싸면, 테스트가 설정을
    바꿔가며 앱을 여러 번 새로 만들 수 있다."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        # 운영에서는 자동 문서를 닫는다. 내부 스키마·엔드포인트 목록이 그대로 공개된다.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    # --- 미들웨어 (등록 역순으로 감싸진다: 아래로 갈수록 바깥) ------------------
    if settings.rate_limit_enabled:
        app.add_middleware(
            RateLimitMiddleware,
            limit_per_minute=settings.rate_limit_per_minute,
            exempt_paths=RATE_LIMIT_EXEMPT_PATHS,
            trust_proxy_headers=settings.trust_proxy_headers,
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
        # 이게 없으면 브라우저 JS 가 응답 헤더의 request_id 를 못 읽는다.
        # 사용자가 오류 화면의 id 를 알려줄 수 있게 하려면 필요하다.
        expose_headers=[REQUEST_ID_HEADER],
    )

    app.add_middleware(RequestIDMiddleware)

    # --- 예외 처리 ------------------------------------------------------------
    # 모든 오류를 {code, user_message, retryable, fallback_sources, request_id} 로 통일.
    register_exception_handlers(app)

    # --- 라우터 ---------------------------------------------------------------
    # 라우터를 만들면 여기서 붙인다. 이 파일에는 엔드포인트를 정의하지 않는다
    # (main.py = 조립, routers/ = 엔드포인트).
    #
    from api.routers import admin_auth, admin_knowledge, chat, feedback, public, session
    app.include_router(public.router)
    app.include_router(chat.router)
    app.include_router(feedback.router)
    app.include_router(session.router)
    app.include_router(admin_auth.router)
    app.include_router(admin_knowledge.router)

    # liveness 만 여기 남긴다. readiness(DB·워밍업까지 확인)는 routers/public.py 의
    # GET /api/health 다 — 둘은 판정 대상이 달라 일부러 나눠 뒀고, 둘 다
    # RATE_LIMIT_EXEMPT_PATHS 에 들어 있다.
    #
    # 엔드포인트는 routers/ 소관이라는 계층 규칙의 유일한 예외다. 옮기려면 옮겨도 되지만,
    # 그때 RATE_LIMIT_EXEMPT_PATHS 의 "/health" 도 같이 확인할 것.
    @app.get("/health", tags=["ops"])
    async def health():
        """살아있는지만 보는 liveness probe. DB·LLM 등 외부 의존성은 확인하지 않는다."""
        return {"status": "ok", "environment": settings.environment}

    return app


app = create_app()
