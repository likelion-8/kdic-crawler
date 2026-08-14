"""요청 단위 공통 처리 — request_id 부여, 접근 로그, 요청 제한(rate limit).

## 왜 BaseHTTPMiddleware 를 안 쓰는가

Starlette 문서에 나오는 `BaseHTTPMiddleware`(@app.middleware("http")) 는 쓰기 편하지만,
응답을 anyio 메모리 스트림으로 한 번 감싸서 통과시킨다. 일반 JSON 응답은 문제없지만
SSE 처럼 "연결을 오래 열어두고 조금씩 흘려보내는" 응답에서는 클라이언트가 창을 닫아도
그 사실이 제때 전달되지 않아, 이미 떠난 사용자를 위해 LLM 호출이 계속되는 일이 생긴다.

api/rag/sse.py 가 바로 그 SSE 이므로(POST /api/chat), 처음부터 순수 ASGI 미들웨어로 짰다.
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
    """클라이언트별 요청 수 제한 — 슬라이딩 윈도우 + AD-009 운영 정책 연동(2026-08-13).

    사용자(챗봇) 경로에는 ops_policy 최신 행(분당·일일·burst)을 30초 TTL 로 읽어 적용하고,
    10분 내 위반 3회면 rate_limit_blocks 에 10분 임시 차단을 적는다 — 종전에는 AD-009 에서
    저장한 정책을 읽는 코드가 어디에도 없어 화면이 장식이었다(F-2). 관리자 경로(/api/admin)는
    운영 정책의 대상이 아니므로(사용자 요청 제한 정책) 종전 settings 한도를 그대로 쓴다 —
    분당 10회를 관리자 화면에 적용하면 대시보드 진입만으로 잠긴다.

    한계를 분명히 해둔다:
    - 프로세스 메모리에 카운트를 둔다. uvicorn 워커를 N개 띄우면 실질 한도가 N배가 된다.
    - 서버를 재시작하면 카운트가 초기화된다(차단 목록은 DB 라 유지된다).
    - 세션별 30분 한도(session_per_30min)는 미들웨어가 세션 id 를 모른다(요청 본문에 있다)
      — 정책 값은 저장·표시되지만 집행은 후속 과제다.
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
        # AD-009 운영 정책 연동 상태 (전부 실패-안전 — DB 가 죽어도 기본값으로 동작)
        self._policy = {"at": 0.0, "value": None}         # ops_policy 30초 TTL 캐시
        self._blocks = {"at": 0.0, "value": {}}           # 활성 차단 {key: expires_ts} 10초 TTL
        self._day = None                                  # 일일 카운터 리셋 기준일(KST)
        self._day_hits = defaultdict(int)                 # key -> 오늘 요청 수
        self._violations = defaultdict(deque)             # key -> 최근 위반 시각(10분 창)

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
        # 위반 기록도 같이 청소한다 — 스캔·NAT 로 IP 가 다양하면 이 dict 만 무한히 큰다
        v_cutoff = now - self._VIOLATION_WINDOW_S
        v_stale = [k for k, v in self._violations.items() if not v or v[-1] < v_cutoff]
        for k in v_stale:
            del self._violations[k]

    _POLICY_TTL_S = 30.0
    _BLOCKS_TTL_S = 10.0
    _BURST_WINDOW_S = 10.0
    _VIOLATION_WINDOW_S = 600.0   # PRD-03: 10분 내 위반 3회 → 10분 차단
    _VIOLATION_THRESHOLD = 3
    _BLOCK_MINUTES = 10

    def _get_policy(self, now):
        """ops_policy 최신 행 -> {ip_per_min, ip_per_day, burst_per_10s}. 30초 TTL."""
        if now - self._policy["at"] < self._POLICY_TTL_S and self._policy["value"]:
            return self._policy["value"]
        value = {"ip_per_min": 10, "ip_per_day": 300, "burst_per_10s": 3}  # AD-009 기본값
        try:
            from sqlalchemy import select
            from db import get_session
            from schema_admin import ops_policy
            with get_session() as session:
                row = session.execute(
                    select(ops_policy).order_by(ops_policy.c.version.desc()).limit(1)).first()
            if row is not None and row.policy:
                for k in ("ip_per_min", "ip_per_day"):
                    if row.policy.get(k) is not None:
                        value[k] = row.policy[k]
                # burst_per_10s 는 읽기 전용 상수(admin_ops READ_ONLY_POLICY_FIELDS)라 기본값 유지
        except Exception:  # noqa: BLE001 — 정책을 못 읽으면 기본값으로 제한한다
            logger.exception("ops_policy 조회 실패 — 기본 한도로 동작")
        self._policy = {"at": now, "value": value}
        return value

    def _active_block_until(self, key, now):
        """rate_limit_blocks 활성 차단 만료 monotonic 시각 | None. 10초 TTL 캐시."""
        if now - self._blocks["at"] >= self._BLOCKS_TTL_S:
            blocks = {}
            try:
                from datetime import datetime, timezone
                from sqlalchemy import select
                from db import get_session
                from schema_admin import rate_limit_blocks
                wall_now = datetime.now(timezone.utc)
                with get_session() as session:
                    rows = session.execute(
                        select(rate_limit_blocks.c.target, rate_limit_blocks.c.expires_at)
                        .where(rate_limit_blocks.c.released_at.is_(None),
                               rate_limit_blocks.c.expires_at > wall_now)).all()
                for r in rows:
                    remain = (r.expires_at - wall_now).total_seconds()
                    blocks[r.target] = now + max(remain, 0.0)
            except Exception:  # noqa: BLE001
                logger.exception("rate_limit_blocks 조회 실패 — 차단 미적용")
            self._blocks = {"at": now, "value": blocks}
        return self._blocks["value"].get(key)

    def _record_violation(self, key, now):
        """한도 위반 기록 — 10분 내 3회면 rate_limit_blocks 에 10분 임시 차단을 적는다."""
        v = self._violations[key]
        cutoff = now - self._VIOLATION_WINDOW_S
        while v and v[0] < cutoff:
            v.popleft()
        v.append(now)
        if len(v) < self._VIOLATION_THRESHOLD:
            return
        v.clear()
        try:
            from datetime import datetime, timedelta, timezone
            from sqlalchemy import insert
            from db import get_session
            from schema_admin import rate_limit_blocks
            wall_now = datetime.now(timezone.utc)
            with get_session() as session:
                session.execute(insert(rate_limit_blocks).values(
                    target=key, target_kind="ip",
                    reason=f"자동 차단 — 10분 내 요청 제한 {self._VIOLATION_THRESHOLD}회 초과",
                    blocked_at=wall_now,
                    expires_at=wall_now + timedelta(minutes=self._BLOCK_MINUTES)))
                session.commit()
            self._blocks["value"][key] = now + self._BLOCK_MINUTES * 60
            logger.warning("임시 차단 등록: %s (%s분)", key, self._BLOCK_MINUTES)
        except Exception:  # noqa: BLE001
            logger.exception("임시 차단 기록 실패 — 이번 위반은 메모리로만 제한")

    def _check_public(self, key, now, policy):
        """사용자 경로 판정 — (허용 여부, 위반 사유). 분당·burst·일일 순서로 본다."""
        hits = self._hits[key]
        cutoff = now - self.window_s
        while hits and hits[0] < cutoff:
            hits.popleft()
        if len(hits) >= int(policy["ip_per_min"]):
            return False, "ip_per_min"
        burst_cutoff = now - self._BURST_WINDOW_S
        if sum(1 for t in hits if t >= burst_cutoff) >= int(policy["burst_per_10s"]):
            return False, "burst_per_10s"
        # 일일 한도 리셋은 KST 자정 기준(AD-009) — 서버 로컬 날짜가 아니다
        from datetime import datetime, timedelta, timezone
        today = (datetime.now(timezone(timedelta(hours=9)))).date()
        if self._day != today:
            self._day = today
            self._day_hits.clear()
        if self._day_hits[key] >= int(policy["ip_per_day"]):
            return False, "ip_per_day"
        hits.append(now)
        self._day_hits[key] += 1
        return True, None

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
        now = time.monotonic()

        is_admin_path = scope["path"].startswith("/api/admin")
        # AD-009 정책의 대상은 '질문 요청'이다(분당 10·burst 3/10초·일 300 — 화면 라벨도
        # "IP별 분당 요청"이 질문 기준). 세션 복원·추천 질문·피드백까지 같은 한도로 재면
        # 첫 방문의 정상 흐름(진입 3콜 + 질문)이 burst 를 넘겨 429·자동 차단까지 간다
        # (2026-08-14 리뷰 지적). 질문 외 공개 경로는 아래 완만한 공용 한도로 간다.
        is_question = scope["path"] == "/api/chat"
        if is_question:
            # 사용자(챗봇) 질문 — AD-009 운영 정책 집행 + 임시 차단
            block_until = self._active_block_until(key, now)
            if block_until is not None and block_until > now:
                request_id = scope.get("state", {}).get("request_id")
                retry_after = max(int(block_until - now), 1)
                logger.warning("[%s] blocked: %s %s", request_id, key, scope["path"])
                response = JSONResponse(
                    status_code=429,
                    content=build_error_body(
                        code="LLM_RATE_LIMIT",
                        user_message="요청이 반복되어 잠시 차단되었습니다. 잠시 후 이용해 주세요.",
                        retryable=False, fallback_sources=[], request_id=request_id),
                    headers={"Retry-After": str(retry_after)})
                await response(scope, receive, send)
                return
            policy = self._get_policy(now)
            self._sweep(now)
            # 카운터 버킷을 경로 계층별로 분리한다 — 관리자·공용 트래픽이 질문 쿼터를
            # 잠식해 챗봇이 차단되던 공유 deque 버그 수정(2026-08-14 리뷰 #1).
            allowed, why = self._check_public(f"chat:{key}", now, policy)
            if not allowed:
                self._record_violation(key, now)
                request_id = scope.get("state", {}).get("request_id")
                logger.warning("[%s] rate_limited(%s): %s %s", request_id, why, key, scope["path"])
                response = JSONResponse(
                    status_code=429,
                    content=build_error_body(
                        code="LLM_RATE_LIMIT",
                        user_message="요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                        retryable=False, fallback_sources=[], request_id=request_id),
                    headers={"Retry-After": "60"})
                await response(scope, receive, send)
                return
            await self.app(scope, receive, send)
            return

        bucket = ("admin:" if is_admin_path else "pub:") + key
        if not self._is_allowed(bucket, now):
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
