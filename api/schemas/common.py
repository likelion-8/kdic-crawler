"""여러 스키마가 공유하는 공통 모델 — 출처(SourceItem)와 에러 봉투(ApiError).

ApiError 는 api/errors.py 의 build_error_body() 가 내보내는 응답 봉투와 필드가 1:1 로
같아야 한다(프론트가 code 하나로 분기하는 계약). 여기서는 그 '형식'만 선언한다 — 실제로
값을 채우는 건 errors.py 의 핸들러들이며, 그쪽은 이 모델을 거치지 않고 dict 를 직접
만든다. 따라서 이 모델은 OpenAPI 문서·응답 직렬화용 '계약서' 역할이다.

타입 표기 주의: 기존 api/ 파일들은 `str | None`(파이썬 3.10+ 문법)을 쓰지만, 이 저장소의
.venv 는 3.9라 그 문법이 런타임에 깨진다(Pydantic v2 가 3.9에서 `str | None` 평가 실패).
그래서 여기서는 기능이 동일하고 3.9·3.12 모두에서 도는 typing.Optional 을 쓴다.
"""
from typing import Optional

from pydantic import BaseModel, Field


class SourceItem(BaseModel):
    """답변(또는 에러 폴백)이 인용하는 출처 한 건.

    ⚠️ 필드명 주의: 이름은 corpus.jsonl 원본 필드(sub_category / source_url) 기준이다.
    그런데 런타임에 출처를 실제로 만들어내는 코드들은 이미 이름을 바꿔서 내보낸다:
      - citation.format_citation()          -> {page_id, breadcrumb, title, url}
      - civil_petition.build_link_section()  -> {title, url, breadcrumb}
      - errors.DEFAULT_FALLBACK_SOURCES      -> {page_id, breadcrumb, title, url}
    즉 실제 데이터는 breadcrumb / url 이라, 이 스키마로 채우려면 매핑 단계(다음 단계
    answer.py)에서 breadcrumb -> sub_category, url -> source_url 로 옮겨야 한다.
    (이번 단계는 형식 정의만 하므로 변환 로직은 만들지 않는다 — 확인 결과에 별도 명시.)
    """
    page_id: Optional[str] = Field(default=None, description="출처 페이지 식별자.")
    sub_category: Optional[str] = Field(
        default=None, description="브레드크럼(사이트 계층 경로). 런타임 원본명은 breadcrumb.")
    title: Optional[str] = Field(default=None, description="페이지 제목.")
    source_url: str = Field(description="출처 페이지 URL. 런타임 원본명은 url.")


class ApiError(BaseModel):
    """에러 응답 봉투 — api/errors.py build_error_body() 가 내보내는 5개 필드와 동일.

    프론트는 이 봉투의 code 만 보고 분기하고, 사용자에게는 user_message 만 보여준다.
    내부 사정(스택 트레이스·DB 오류 원문 등)은 절대 담기지 않는다(서버 로그에만 남음).
    """
    code: str = Field(description="프론트 분기용 기계 식별자(예: rag_timeout, validation_error).")
    user_message: str = Field(description="사용자에게 그대로 보여줄 한국어 문장.")
    retryable: bool = Field(description="재시도 버튼을 띄울지 여부.")
    fallback_sources: list[SourceItem] = Field(
        default_factory=list,
        description="답을 못 줄 때 대신 안내할 공식 페이지 목록. "
                    "⚠️ errors.py 는 이 항목들을 breadcrumb/url 이름의 dict 로 내보낸다 "
                    "(SourceItem 의 sub_category/source_url 과 이름이 다름 — 확인 결과 참고).")
    # errors.py 의 _request_id() 는 미들웨어보다 앞단에서 터진 예외의 경우 None 을 돌려준다.
    # 그래서 task 의 표기(request_id: str)와 달리 실제로는 null 이 될 수 있어 Optional 로 둔다.
    request_id: Optional[str] = Field(
        default=None, description="요청 추적 id(미들웨어가 부여). 미들웨어 이전 예외면 null.")
