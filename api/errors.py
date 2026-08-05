"""공통 오류 처리 — 어떤 예외가 나든 응답 본문 모양을 하나로 통일한다.

    {
      "code": "rag_timeout",            # 프론트가 분기할 기계용 식별자
      "user_message": "답변 생성이 ...",  # 사용자에게 그대로 보여줄 한국어 문장
      "retryable": true,                # 재시도 버튼을 띄울지
      "fallback_sources": [...],        # 답을 못 줄 때 대신 안내할 공식 페이지
      "request_id": "..."               # 로그 추적용(미들웨어가 부여)
    }

설계 의도 세 가지:

1. 예외 종류마다 다른 모양이 나가면 프론트가 매번 분기해야 한다. 여기서 한 번 통일하면
   프론트는 code 만 보면 된다.
2. 내부 사정(스택 트레이스, DB 오류 메시지, LLM 응답 원문)은 절대 내보내지 않는다.
   서버 로그에는 남기고, 사용자에게는 user_message 만 준다.
3. 챗봇 특성상 "답을 못 준다"는 상황이 정상 동작의 일부다. 그냥 실패로 끝내지 않고
   fallback_sources 로 공식 페이지를 안내한다 — 이 필드가 봉투에 있는 이유다.

request_id 는 여기서 만들지 않는다. api/middleware.py 가 요청마다 발급해
request.state.request_id 에 넣어두고, 핸들러가 그걸 읽어 봉투에 채운다.
"""
import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# data/corpus.jsonl 에서 가져온 실제 페이지다(page_id: faq_top10 / dp_faq_page).
# citation.format_citation() 이 반환하는 {page_id, breadcrumb, title, url} 과 같은
# 모양이라, 프론트는 정상 답변의 출처와 같은 컴포넌트로 렌더링하면 된다.
# 코퍼스에서 해당 페이지가 사라지면 여기도 함께 고칠 것.
DEFAULT_FALLBACK_SOURCES = [
    {
        "page_id": "faq_top10",
        "breadcrumb": "FAQ_TOP10",
        "title": "고객센터 FAQ TOP 10",
        "url": "https://fins.kdic.or.kr/cm/bbs/selectFaqTop10.do",
    },
    {
        "page_id": "dp_faq_page",
        "breadcrumb": "예금자보호제도 > 예금자보호제도 FAQ",
        "title": "예금자보호제도 FAQ",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/ProtSystFaq/selectScrn.do",
    },
]


class ApiError(Exception):
    """API 계층이 의도적으로 던지는 오류의 부모.

    서비스·라우터는 HTTPException 대신 이 계열을 던진다. status_code 뿐 아니라
    code/user_message/retryable/fallback_sources 까지 예외 자체가 들고 다녀서,
    던지는 쪽이 "사용자에게 뭐라고 보일지"를 결정할 수 있게 하기 위함이다.

    ⚠️ code 는 web/src/lib/codes.ts 의 ErrorCode 5종(LLM_TIMEOUT · LLM_RATE_LIMIT · LLM_ERROR ·
    RETRIEVAL_ERROR · INTERNAL)만 쓴다. 프론트는 닫힌 union 이고 ERROR_HAS_FALLBACK 을 Record 로
    조회하므로, 목록에 없는 값을 보내면 조회가 undefined 가 되어 분기가 깨진다. HTTP 계층 오류
    (검증 실패·404·405 등)에 딱 맞는 코드가 5종에 없어 INTERNAL 로 모으고, 사용자에게 보일
    내용은 user_message 로 구분한다.
    """

    code = "INTERNAL"
    status_code = 500
    user_message = "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
    retryable = False
    include_fallback_sources = False

    def __init__(self, user_message=None, *, retryable=None, fallback_sources=None, detail=None):
        # detail 은 서버 로그 전용이다 — 응답 본문에는 절대 들어가지 않는다.
        self.detail = detail
        if user_message is not None:
            self.user_message = user_message
        if retryable is not None:
            self.retryable = retryable
        if fallback_sources is not None:
            self.fallback_sources = fallback_sources
        elif self.include_fallback_sources:
            self.fallback_sources = DEFAULT_FALLBACK_SOURCES
        else:
            self.fallback_sources = []
        super().__init__(detail or self.user_message)


class BadRequestError(ApiError):
    status_code = 400
    user_message = "요청 형식이 올바르지 않습니다."


class UnauthorizedError(ApiError):
    status_code = 401
    user_message = "로그인이 필요합니다."


class ForbiddenError(ApiError):
    status_code = 403
    user_message = "접근 권한이 없습니다."


class NotFoundError(ApiError):
    status_code = 404
    user_message = "요청한 자료를 찾을 수 없습니다."


class RateLimitError(ApiError):
    code = "LLM_RATE_LIMIT"
    status_code = 429
    # 자동 재호출 금지 — 사용자가 직접 다시 보낸다(mocks/README §3-3).
    user_message = "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."
    retryable = False


class RagTimeoutError(ApiError):
    """RAG 실행이 설정된 시간(config.rag_timeout_s)을 넘겼을 때."""

    code = "LLM_TIMEOUT"
    status_code = 504
    user_message = "답변 생성이 예상보다 오래 걸립니다. 잠시 후 다시 시도해 주세요."
    retryable = True
    include_fallback_sources = True


class RagUnavailableError(ApiError):
    """검색 엔진·LLM·DB 등 RAG 의존 요소가 죽어 답변을 만들 수 없을 때."""

    code = "RETRIEVAL_ERROR"
    status_code = 503
    user_message = "답변 서비스를 일시적으로 이용할 수 없습니다. 잠시 후 다시 시도해 주세요."
    retryable = True
    # ERROR_HAS_FALLBACK[RETRIEVAL_ERROR] 가 false 라 폴백 출처를 싣지 않는다.


def build_error_body(*, code, user_message, retryable, fallback_sources, request_id):
    """봉투를 만드는 단 하나의 지점. 필드가 늘거나 바뀌면 여기만 고친다."""
    return {
        "code": code,
        "user_message": user_message,
        "retryable": retryable,
        "fallback_sources": fallback_sources,
        "request_id": request_id,
    }


def error_response(status_code, body):
    return JSONResponse(status_code=status_code, content=body)


def _request_id(request):
    # 미들웨어보다 앞단에서 터진 예외라면 state 가 비어 있을 수 있다.
    return getattr(request.state, "request_id", None)


# HTTPException 의 status_code 를 우리 code 문자열로 옮긴다. 우리가 직접 던지지 않아도
# FastAPI 내부(예: 없는 경로 404, 허용되지 않은 메서드 405)에서 올라오는 게 있어서 필요하다.
_STATUS_CODE_MAP = {
    400: ("INTERNAL", "요청 형식이 올바르지 않습니다."),
    401: ("INTERNAL", "로그인이 필요합니다."),
    403: ("INTERNAL", "접근 권한이 없습니다."),
    404: ("INTERNAL", "요청한 경로를 찾을 수 없습니다."),
    405: ("INTERNAL", "허용되지 않은 요청 방식입니다."),
    429: ("LLM_RATE_LIMIT", "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."),
}


async def api_error_handler(request: Request, exc: ApiError):
    request_id = _request_id(request)
    # 5xx 는 우리 잘못이라 스택까지, 4xx 는 호출자 잘못이라 한 줄만 남긴다.
    log = logger.exception if exc.status_code >= 500 else logger.warning
    log("[%s] %s: %s", request_id, exc.code, exc.detail or exc.user_message)
    return error_response(
        exc.status_code,
        build_error_body(
            code=exc.code,
            user_message=exc.user_message,
            retryable=exc.retryable,
            fallback_sources=exc.fallback_sources,
            request_id=request_id,
        ),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    code, message = _STATUS_CODE_MAP.get(
        exc.status_code, ("INTERNAL", "요청을 처리하지 못했습니다."))
    return error_response(
        exc.status_code,
        build_error_body(
            code=code,
            user_message=message,
            retryable=exc.status_code in (429, 502, 503, 504),
            fallback_sources=[],
            request_id=_request_id(request),
        ),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Pydantic 검증 실패(422). 기본 응답은 필드 경로·타입 등 내부 구조를 그대로 노출하고
    영어라서, 사용자용 문장으로 갈아끼운다. 상세 내용은 로그로만 남긴다."""
    request_id = _request_id(request)
    logger.warning("[%s] validation_error: %s", request_id, exc.errors())
    return error_response(
        422,
        build_error_body(
            code="INTERNAL",
            user_message="입력값을 확인해 주세요.",
            retryable=False,
            fallback_sources=[],
            request_id=request_id,
        ),
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    """우리가 예상하지 못한 모든 예외의 마지막 그물.

    이게 없으면 스택 트레이스가 그대로 나가거나 봉투 없는 500 이 나간다.
    사용자에게는 일반 문장만 주고, 원인은 request_id 와 함께 로그에서 찾는다."""
    request_id = _request_id(request)
    logger.exception("[%s] unhandled_error: %s", request_id, exc)
    return error_response(
        500,
        build_error_body(
            code="INTERNAL",
            user_message="일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
            retryable=True,
            # ERROR_HAS_FALLBACK[INTERNAL] 이 false 라 폴백 출처를 싣지 않는다.
            fallback_sources=[],
            request_id=request_id,
        ),
    )


def register_exception_handlers(app):
    """main.py 에서 한 번 부른다. 등록 순서가 아니라 예외 타입의 구체성으로 매칭된다."""
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
