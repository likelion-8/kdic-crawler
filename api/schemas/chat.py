"""채팅 요청/응답 스키마 — /chat 엔드포인트의 입출력 '형식' 정의.

이 파일은 형식(계약)만 선언한다. 실제로 이 필드들에 값을 채우는 로직(RAG 파이프라인
호출, civil_petition 결과 매핑, 복합 질문 분해 결과 취합 등)은 api/rag/answer.py(다음
단계)의 몫이다. 여기서 파이프라인을 부르거나 변환을 구현하지 않는다.

각 필드가 기존 파이프라인의 실제 반환 구조(civil_petition.py / citation.py / pipeline.py)와
매핑 가능한지 대조한 결과는 아래 각 모델의 주석과 확인 결과 메모에 남겨 두었다.

타입 표기(Optional[...] 사용 이유)는 common.py 상단 주석 참고.
"""
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from api.schemas.common import ApiError, SourceItem

# 질문 길이 상한. 예금보험 상담 질문은 현실적으로 한두 문장이라 500자면 정상 질문은 거의
# 걸리지 않으면서, 문서를 통째로 붙여넣는 식의 남용(비용·지연 폭증)은 막는다. RAG 는 이
# 질문을 분해 -> intent(OpenAI) -> 검색 -> HyperCLOVA 생성으로 여러 번 LLM 에 태우므로
# 입력이 길수록 비용이 곧장 커진다. (src/backend 시안에서 정한 값과 동일하게 맞춤.)
MAX_MESSAGE_LEN = 500


class Attachment(BaseModel):
    """민원(civil_petition) '서류 안내' 한 건.

    civil_petition.build_document_section() 의 항목과 매핑한다. 그 함수가 실제로 내보내는
    항목은 {page_id, label, url} 이다(attachments 는 label=text, form_attachments 는
    label=label·url=page_url 로 이미 가공됨).

    ⚠️ file_type 주의: corpus.jsonl 의 form_attachments 원본에는 file_type 이 있으나
    (raw keys: label, file_type, page_url, resolved_url, download_method, download_params),
    build_document_section() 이 이를 버리고 {page_id, label, url} 만 내보낸다. 따라서 지금
    civil_petition 의 '반환값만으로는' file_type 을 채울 수 없다(코퍼스를 다시 읽거나
    civil_petition 을 바꿔야 함 — 둘 다 이번 단계 범위 밖). 그래서 Optional 로 둔다.

    ⚠️ url 주의: form_attachments 의 url 은 실제 파일 링크가 아니라 '다운로드 버튼이 있는
    페이지'(page_url)다. resolved_url 은 POST 전용 서블릿이라 그대로는 안 열려서
    build_document_section() 이 의도적으로 page_url 을 쓴다.
    """
    label: Optional[str] = Field(default=None, description="서류/서식 이름.")
    file_type: Optional[str] = Field(
        default=None, description="파일 형식(pdf/hwp 등). ⚠️ civil_petition 현재 반환값엔 없음.")
    url: Optional[str] = Field(
        default=None, description="다운로드 버튼이 있는 페이지 URL(직접 파일 링크가 아님).")
    page_id: Optional[str] = Field(default=None, description="서류가 속한 페이지 식별자.")


class SubAnswer(BaseModel):
    """복합(멀티쿼리) 질문의 하위 답변 한 건 — 하나의 문자열로 합치지 않고 배열 항목으로 유지.

    설계 판단: 간단한 question+answer 대신 sources/attachments 까지 둔 '재귀적' 형태를
    택했다. pipeline._answer_one() 이 하위 질문마다 검색·근거 조립·출처를 '완전히 독립적으로'
    만들기 때문이다(pipeline.py 주석: 하위 답변 간 출처 누적/중복제거를 일부러 제거함). 즉
    하위 질문마다 고유한 출처/서류가 있으므로, 상위 답변과 같은 필드를 하위에도 두는 게
    실제 데이터 구조와 맞는다.

    ⚠️ 매핑 주의: 현재 pipeline 은 하위 답변을 문자열로 합쳐(_answer_one 반환도 문자열,
    이후 "\\n\\n".join) 내보내므로, 하위별 sub_question/sources 를 구조화해서 얻으려면
    pipeline 반환 구조를 바꿔야 한다(이번 단계 범위 밖 — 형식만 준비해 둠).
    """
    sub_question: str = Field(description="분해된 하위 질문.")
    answer: str = Field(description="그 하위 질문에 대한 답변 본문.")
    sources: list[SourceItem] = Field(default_factory=list, description="이 하위 답변의 출처.")
    attachments: list[Attachment] = Field(default_factory=list, description="이 하위 답변의 서류 안내.")


class ChatRequest(BaseModel):
    """/chat 요청 본문. 다른 스키마에 의존하지 않는 순수 입력 계약."""
    message: str = Field(
        ...,
        min_length=1,
        max_length=MAX_MESSAGE_LEN,
        description=f"사용자 질문(필수). 공백만 있으면 거부, 최대 {MAX_MESSAGE_LEN}자.",
    )
    # 지금은 멀티턴을 구현하지 않지만, 나중에 세션별 대화 구분에 쓸 수 있게 필드만 열어둔다.
    session_id: Optional[str] = Field(
        default=None, description="세션 식별자(선택). 현재 미사용, 향후 멀티턴용.")

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        # min_length=1 은 빈 문자열만 막고 공백만 있는 입력("   ")은 통과시키므로 여기서 잡는다.
        stripped = v.strip()
        if not stripped:
            raise ValueError("message는 공백만으로 이루어질 수 없습니다.")
        return stripped  # 앞뒤 공백을 제거한 질문을 반환한다


class ChatResponse(BaseModel):
    """/chat 응답 본문 — 최종 답변과 그에 딸린 구조화된 부가 정보.

    이번 단계는 '형식'만 정의한다. 각 필드에 값을 채우는 건 answer.py(다음 단계)다.
    """
    answer: str = Field(description="최종 답변 본문(단일 질문일 때). 복합 질문은 sub_answers 참고.")
    sources: list[SourceItem] = Field(default_factory=list, description="답변 출처 목록.")
    attachments: list[Attachment] = Field(
        default_factory=list, description="민원 서류 안내(civil_petition 의도일 때만 채워짐).")
    out_of_scope: bool = Field(
        default=False,
        description="업무 범위 밖 질문 여부. ⚠️ 파이프라인에 구조화된 OOS 판정 로직이 없다"
                    "([NO_SOURCE] 마커/LLM 거절로 암묵 처리) — 지금은 필드만 두고 값 채우기는 보류.")
    sub_answers: list[SubAnswer] = Field(
        default_factory=list, description="복합 질문(멀티쿼리)의 개별 답변들. 배열로 유지.")
    clarification: Optional[str] = Field(
        default=None, description="질문이 애매해 재질문이 필요할 때의 안내 문구.")
    error: Optional[ApiError] = Field(
        default=None, description="오류 정보(common.ApiError 재사용). 정상 응답이면 null.")
    # ⚠️ 미들웨어(api/middleware.py)가 요청마다 발급하는 request_id(X-Request-ID, uuid4().hex,
    # request.state.request_id)와는 '다른' 값이다. answer_request_id 는 '답변' 하나를 가리키는
    # 식별자로, 사용자가 그 답변에 피드백(좋아요/신고 등)을 보낼 때 대상 답변을 특정하는 데
    # 쓴다. 값 생성은 답변 생성 단계(answer.py)에서 한다.
    answer_request_id: str = Field(description="피드백 대상 '답변' 식별자(요청 추적용 request_id 와 별개).")
