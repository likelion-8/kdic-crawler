"""여러 스키마가 공유하는 공통 모델 — 출처(SourceItem)와 에러 봉투(ApiError).

ApiError 는 api/errors.py 의 build_error_body() 가 내보내는 응답 봉투와 필드가 1:1 로
같아야 한다(프론트가 code 하나로 분기하는 계약). 여기서는 그 '형식'만 선언한다 — 실제로
값을 채우는 건 errors.py 의 핸들러들이며, 그쪽은 이 모델을 거치지 않고 dict 를 직접
만든다. 따라서 이 모델은 OpenAPI 문서·응답 직렬화용 '계약서' 역할이다.

타입 표기: api/ 의 다른 파일들은 `str | None`(3.10+ 문법)을 쓰지만, 이 저장소의 .venv 는
3.9라 그 문법이 런타임에 깨진다. 그래서 기능이 같고 3.9·3.12 모두에서 도는 typing.Optional
을 쓴다.
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

    ⚠️ code 값 규약(미해결): 프론트는 대문자 5종(LLM_TIMEOUT / LLM_RATE_LIMIT / LLM_ERROR /
    RETRIEVAL_ERROR / INTERNAL)으로 분기하는데, errors.py 는 지금 소문자 코드(rag_timeout 등)를
    내보낸다 — 겹치는 값이 없다. 이 모델은 code 를 str 로만 두고(다른 엔드포인트 코드까지
    수용), 값 정렬은 errors.py(1단계 파일) 쪽 결정 사항으로 남긴다.
    """
    code: str = Field(description="프론트 분기용 기계 식별자. 프론트 기대값: LLM_TIMEOUT/LLM_RATE_LIMIT/LLM_ERROR/RETRIEVAL_ERROR/INTERNAL (errors.py 정렬 필요).")
    user_message: str = Field(description="사용자에게 그대로 보여줄 한국어 문장.")
    retryable: bool = Field(description="재시도 버튼을 띄울지 여부.")
    fallback_sources: list[SourceItem] = Field(
        default_factory=list,
        description="답을 못 줄 때 대신 안내할 공식 페이지 목록(errors.py 폴백과 동일한 breadcrumb/url 형태).")
    # errors.py 의 _request_id() 는 미들웨어보다 앞단에서 터진 예외의 경우 None 을 돌려준다.
    request_id: Optional[str] = Field(
        default=None, description="요청 추적 id(미들웨어가 부여). 미들웨어 이전 예외면 null.")
