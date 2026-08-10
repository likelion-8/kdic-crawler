"""여러 스키마가 공유하는 공통 모델 — 출처(SourceItem)와 에러 봉투(ApiError).

ApiError 는 api/errors.py 의 build_error_body() 가 내보내는 응답 봉투와 필드가 1:1 로
같아야 한다(프론트가 code 하나로 분기하는 계약). 여기서는 그 '형식'만 선언한다 — 실제로
값을 채우는 건 errors.py 의 핸들러들이며, 그쪽은 이 모델을 거치지 않고 dict 를 직접
만든다. 따라서 이 모델은 OpenAPI 문서·응답 직렬화용 '계약서' 역할이다.

타입 표기: 선택 필드는 `str | None`(3.10+ 문법)이 아니라 typing.Optional 로 통일한다.
api/ 전체가 이미 Optional 로만 쓰고 있어 표기를 섞지 않으려는 것이다(둘은 기능이 같다).
※ 이 저장소의 venv 는 Python 3.11 이라 `str | None` 도 런타임에 문제없이 돈다 —
   "3.9 라서 못 쓴다"는 예전 주석은 사실이 아니었으므로 근거로 삼지 말 것.
"""
from typing import Optional

from pydantic import BaseModel, Field


class SourceItem(BaseModel):
    """답변(또는 에러 폴백)이 인용하는 출처 한 건.

    필드명은 런타임에 출처를 실제로 만들어내는 코드들과 '그대로' 맞췄다(프론트 MSW 계약과도
    동일). 그래서 매핑(이름 변환) 없이 바로 담을 수 있다:
      - citation.format_citation()          -> {page_id, breadcrumb, title, url}
      - civil_petition.build_link_section()  -> {title, url, breadcrumb}
      - errors.DEFAULT_FALLBACK_SOURCES      -> {page_id, breadcrumb, title, url}
    """
    page_id: Optional[str] = Field(default=None, description="출처 페이지 식별자.")
    breadcrumb: Optional[str] = Field(
        default=None, description="사이트 계층 경로(예: '예금자보호제도 > 보호한도').")
    title: Optional[str] = Field(default=None, description="페이지 제목.")
    url: str = Field(description="출처 페이지 URL.")


class ApiError(BaseModel):
    """에러 응답 봉투 — api/errors.py build_error_body() 가 내보내는 5개 필드와 동일.

    프론트는 이 봉투의 code 만 보고 분기하고, 사용자에게는 user_message 만 보여준다.
    내부 사정(스택 트레이스·DB 오류 원문 등)은 절대 담기지 않는다(서버 로그에만 남음).

    code 값 규약(2026-08-05 정렬 완료): web/src/lib/codes.ts 의 ErrorCode 5종만 쓴다 —
    LLM_TIMEOUT / LLM_RATE_LIMIT / LLM_ERROR / RETRIEVAL_ERROR / INTERNAL. 프론트가 닫힌 union 이고
    ERROR_HAS_FALLBACK 을 Record 로 조회하므로 목록 밖 값은 조회가 undefined 가 되어 분기가 깨진다.
    HTTP 계층 오류(검증 실패·404·405)는 대응 코드가 5종에 없어 errors.py 가 INTERNAL 로 모으고
    user_message 로 구분한다. 타입은 str 로 두되 값은 이 5종을 벗어나지 않게 한다.

    fallback_sources 를 실을지도 codes.ts 의 ERROR_HAS_FALLBACK 표를 따른다 — LLM_* 3종만 true,
    RETRIEVAL_ERROR·INTERNAL 은 false 다.
    """
    code: str = Field(description="프론트 분기용 기계 식별자. LLM_TIMEOUT/LLM_RATE_LIMIT/LLM_ERROR/RETRIEVAL_ERROR/INTERNAL 5종만 사용.")
    user_message: str = Field(description="사용자에게 그대로 보여줄 한국어 문장.")
    retryable: bool = Field(description="재시도 버튼을 띄울지 여부.")
    fallback_sources: list[SourceItem] = Field(
        default_factory=list,
        description="답을 못 줄 때 대신 안내할 공식 페이지 목록(errors.py 폴백과 동일한 breadcrumb/url 형태).")
    # errors.py 의 _request_id() 는 미들웨어보다 앞단에서 터진 예외의 경우 None 을 돌려준다.
    request_id: Optional[str] = Field(
        default=None, description="요청 추적 id(미들웨어가 부여). 미들웨어 이전 예외면 null.")
