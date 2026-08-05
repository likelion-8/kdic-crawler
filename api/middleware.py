"""요청 단위 공통 처리 — request_id 부여, 접근 로그, 요청 제한(rate limit).

## 왜 BaseHTTPMiddleware 를 안 쓰는가

Starlette 문서에 나오는 `BaseHTTPMiddleware`(@app.middleware("http")) 는 쓰기 편하지만,
응답을 anyio 메모리 스트림으로 한 번 감싸서 통과시킨다. 일반 JSON 응답은 문제없지만
SSE 처럼 "연결을 오래 열어두고 조금씩 흘려보내는" 응답에서는 클라이언트가 창을 닫아도
그 사실이 제때 전달되지 않아, 이미 떠난 사용자를 위해 LLM 호출이 계속되는 일이 생긴다.

api/rag/sse.py 가 바로 그 SSE 를 쓸 예정이라, 처음부터 순수 ASGI 미들웨어로 짰다.
ASGI 미들웨어는 scope/receive/send 를 그대로 넘겨주므로 스트리밍에 개입하지 않는다.

## ASGI 미들웨어를 읽는 법

    async def __call__(self, scope, receive, send)

- scope: 이 요청에 대한 정보 딕셔너리(경로, 메서드, 헤더, 클라이언트 주소...)
- receive: 클라이언트가 보낸 것을 읽는 함수
- send: 클라이언트로 내보내는 함수

우리는 send 를 한 겹 감싸서(send_wrapper) "응답 헤더가 나가는 순간"에만 끼어들어
X-Request-ID 를 붙이고 로그를 남긴다. 나머지는 손대지 않고 그대로 통과시킨다.

## 미들웨어 순서

app.add_middleware() 는 나중에 추가한 것이 바깥쪽(먼저 실행)이다. main.py 에서는

    add_middleware(RateLimitMiddleware)   # 안쪽 - 나중 실행
    add_middleware(RequestIDMiddleware)   # 바깥쪽 - 먼저 실행

순으로 등록한다. 요청 제한에 걸려 거절되는 응답에도 request_id 가 찍혀야 하므로
RequestIDMiddleware 가 반드시 바깥에 있어야 한다.
"""
import logging
import time
import uuid
from collections import defaultdict, deque

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse

from api.errors import build_error_body

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


def _get_request_id(scope):
    """앞단 게이트웨이가 이미 붙여준 값이 있으면 이어받고, 없으면 새로 만든다.
    이어받아야 게이트웨이 로그와 우리 로그를 같은 id 로 맞춰볼 수 있다."""
    for key, value in scope.get("headers", []):
        if key == b"x-request-id":
            incoming = value.decode("latin-1").strip()
            # 남이 보낸 값이 로그에 그대로 들어가므로 길이를 제한한다.
            if incoming and len(incoming) <= 128:
                return incoming
    return uuid.uuid4().hex


class RequestIDMiddleware:
    """요청마다 고유 id 를 붙이고, 처리 시간을 접근 로그로 남긴다.

    id 는 scope["state"] 에 넣는다 — 라우터에서는 request.state.request_id 로,
    errors.py 의 예외 핸들러에서도 같은 값으로 읽힌다. 사용자가 "답변이 이상해요"
    라며 화면의 request_id 를 알려주면 서버 로그에서 그 요청만 바로 뽑을 수 있다.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        # lifespan(앱 시작/종료)과 websocket 은 이 미들웨어의 대상이 아니다.
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _get_request_id(scope)
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
                elapsed_ms = (time.perf_counter() - started) * 1000
                logger.info(
                    "[%s] %s %s -> %s (%.0fms)",
                    request_id, scope["method"], scope["path"],
                    message["status"], elapsed_ms,
                )
            await send(message)

        await self.app(scope, receive, send_wrapper)


class RateLimitMiddleware:
    """클라이언트별 분당 요청 수 제한 — 슬라이딩 윈도우.

    한계를 분명히 해둔다:
    - 프로세스 메모리에 카운트를 둔다. uvicorn 워커를 N개 띄우면 실질 한도가 N배가 된다.
    - 서버를 재시작하면 카운트가 초기화된다.
    즉 남용을 늦추는 최소 장치이지 정확한 쿼터가 아니다. 정확한 제한이 필요해지면
    Redis 등 공유 저장소 기반으로 이 클래스만 갈아끼우면 된다.

    거절할 때 ApiError 를 던지지 않고 JSONResponse 를 직접 만들어 보내는 이유:
    errors.py 의 예외 핸들러는 앱 안쪽(ExceptionMiddleware)에서 동작하므로, 그보다
    바깥인 미들웨어에서 던진 예외는 잡지 못한다. 그래서 봉투 모양만 build_error_body 로
    맞춰 직접 응답한다.
    """

    def __init__(self, app, *, limit_per_minute, exempt_paths=(), trust_proxy_headers=False):
        self.app = app
        self.limit = limit_per_minute
        self.exempt_paths = set(exempt_paths)
        self.trust_proxy_headers = trust_proxy_headers
        self.window_s = 60.0
        self._hits = defaultdict(deque)  # client key -> 최근 요청 시각들
        self._last_sweep = 0.0

    def _client_key(self, scope):
        if self.trust_proxy_headers:
            # 프록시/로드밸런서 뒤에 있을 때만 켠다. 직접 노출된 서버에서 켜면
            # 헤더를 위조해 제한을 우회할 수 있다(그래서 기본값 False).
            for key, value in scope.get("headers", []):
                if key == b"x-forwarded-for":
                    return value.decode("latin-1").split(",")[0].strip()
        client = scope.get("client")
        return client[0] if client else "unknown"

    def _sweep(self, now):
        """오래 조용한 클라이언트 항목을 정리한다.

        요청이 올 때마다 새 key 가 생기므로 그냥 두면 딕셔너리가 접속한 IP 수만큼
        계속 커진다. 매 요청 전체를 훑으면 비싸니 창 길이(60초)에 한 번만 훑는다."""
        if now - self._last_sweep < self.window_s:
            return
        self._last_sweep = now
        cutoff = now - self.window_s
        stale = [k for k, hits in self._hits.items() if not hits or hits[-1] < cutoff]
        for k in stale:
            del self._hits[k]

    def _is_allowed(self, key, now):
        self._sweep(now)
        hits = self._hits[key]
        cutoff = now - self.window_s
        # 창 밖으로 밀려난 기록부터 버린다(슬라이딩 윈도우).
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= self.limit:
            # 거절된 요청은 기록하지 않는다 — 기록하면 계속 두드리는 클라이언트가
            # 영원히 풀리지 않는다(고정 윈도우처럼 굳어버림).
            return False
        hits.append(now)
        return True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        key = self._client_key(scope)
        if not self._is_allowed(key, time.monotonic()):
            request_id = scope.get("state", {}).get("request_id")
            logger.warning("[%s] rate_limited: %s %s", request_id, key, scope["path"])
            # code 는 프론트 codes.ts ErrorCode 5종 중 하나여야 한다. retryable 은 false —
            # 자동 재호출을 금지하고 사용자가 직접 다시 보내게 한다(mocks/README §3-3).
            response = JSONResponse(
                status_code=429,
                content=build_error_body(
                    code="LLM_RATE_LIMIT",
                    user_message="요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                    retryable=False,
                    fallback_sources=[],
                    request_id=request_id,
                ),
                headers={"Retry-After": "60"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
