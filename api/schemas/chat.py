"""채팅 요청/응답 스키마 — /chat 엔드포인트의 입출력 '형식' 정의.

이 파일은 형식(계약)만 선언한다. 실제로 이 필드들에 값을 채우는 로직(RAG 빌딩블록 호출,
civil_petition 결과 매핑, 복합 질문 하위 답변 취합)은 api/rag/answer.py 가 갖고 있고
이미 구현돼 있다. 여기서 파이프라인을 부르거나 변환을 구현하지 않는다.

필드명·구조는 프론트엔드 MSW 목 계약에 맞췄다(2026-08-05 프론트 대조 반영):
sub_answers 항목 키는 title, Attachment.kind 로 서류/링크 구분, clarification 은 선택지까지
담는 구조, 응답 식별자는 request_id, 세션 복원용 session_id 포함.

타입 표기(Optional[...] 사용 이유)는 common.py 상단 주석 참고.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from api.schemas.common import ApiError, SourceItem

# 질문 길이 상한. 예금보험 상담 질문은 현실적으로 한두 문장이라 500자면 정상 질문은 거의
# 걸리지 않으면서, 문서를 통째로 붙여넣는 식의 남용(비용·지연 폭증)은 막는다.
MAX_MESSAGE_LEN = 500


class Attachment(BaseModel):
    """민원(civil_petition) 안내 한 건. kind 로 '필요 서류'와 '신청 페이지 CTA'를 가른다
    (프론트가 이 값으로 두 섹션을 분리해 그린다 — 없으면 두 섹션이 통째로 안 나온다).

    매핑은 answer._build_attachments() 가 한다:
      - civil_petition documents -> kind="document"  ({page_id, label, url})
      - civil_petition links     -> kind="link"      ({title, url, breadcrumb} 중 url/label)

    ⚠️ file_type: corpus 원본 form_attachments 엔 있으나 build_document_section() 이 버려서
    civil_petition 반환값만으로는 못 채운다(Optional). url 은 form 서류의 경우 직접 파일이
    아니라 '다운로드 버튼이 있는 페이지'다.
    """
    kind: Literal["document", "link"] = Field(
        description="document=필요 서류, link=신청 페이지 CTA. 프론트가 이 값으로 섹션을 가른다.")
    label: Optional[str] = Field(default=None, description="서류/링크 이름.")
    file_type: Optional[str] = Field(
        default=None, description="파일 형식(pdf/hwp 등). ⚠️ civil_petition 반환값엔 없음.")
    url: Optional[str] = Field(
        default=None, description="다운로드 버튼이 있는 페이지 URL(직접 파일 링크가 아닐 수 있음).")
    page_id: Optional[str] = Field(default=None, description="속한 페이지 식별자.")


class SubAnswer(BaseModel):
    """복합(멀티쿼리) 질문의 하위 답변 한 건 — 문자열로 합치지 않고 배열 항목으로 유지.

    설계: 하위질문마다 검색·근거·출처가 독립적이라(pipeline._answer_one) 상위 답변과 같은
    필드를 하위에도 둔다. 하위 간 출처 중복 제거는 금지다 — 같은 문서가 여러 하위 답변의
    근거면 각각에 보여야 한다(되살리면 이슈 4 재발).

    채우는 곳: api/rag/answer.py 의 finalize_sub() → to_chat_response(). src/pipeline.py 쪽
    경로(CLI)는 여전히 하위 답변을 문자열로 합쳐 내보내므로 이 구조를 쓰지 않는다 —
    그래서 answer.py 가 pipeline 을 부르지 않고 같은 빌딩블록으로 흐름을 다시 엮는다.
    """
    title: str = Field(description="분해된 하위 질문(프론트 표시용 제목).")
    answer: str = Field(description="그 하위 질문에 대한 답변 본문.")
    sources: list[SourceItem] = Field(default_factory=list, description="이 하위 답변의 출처.")
    attachments: list[Attachment] = Field(default_factory=list, description="이 하위 답변의 서류/링크.")


class ClarificationOption(BaseModel):
    """재질문 선택지 한 개. 프론트는 label 을 버튼으로 그리고, 선택 시 value(없으면 label)를 보낸다."""
    label: str = Field(description="버튼에 표시할 라벨.")
    value: Optional[str] = Field(default=None, description="선택 시 서버로 보낼 값(없으면 label 사용).")


class Clarification(BaseModel):
    """질문이 애매할 때 서버가 되묻는 구조. 선택지까지 서버가 준다 — 역할축이 많아(41개) 버튼
    라벨을 프론트에 박아둘 수 없으므로 서버가 question 과 options 를 함께 내려보낸다.

    ⚠️ 형식만 있고 되묻기 판정 로직은 아직 없다 — answer.to_chat_response() 가 이 필드를
    설정하지 않아 늘 기본값 None 으로 나간다. 붙일 때: options 가 비면 프론트에 버튼이 하나도
    안 그려지고, done.clarification 이 있으면 answer 는 버려지므로 되묻기 턴에는 answer_delta
    를 아예 보내면 안 된다."""
    question: str = Field(description="사용자에게 되물을 문구.")
    options: list[ClarificationOption] = Field(default_factory=list, description="고를 수 있는 선택지.")


class ChatRequest(BaseModel):
    """/chat 요청 본문. 다른 스키마에 의존하지 않는 순수 입력 계약."""
    message: str = Field(
        ...,
        min_length=1,
        max_length=MAX_MESSAGE_LEN,
        description=f"사용자 질문(필수). 공백만 있으면 거부, 최대 {MAX_MESSAGE_LEN}자.",
    )
    session_id: Optional[str] = Field(
        default=None, description="세션 식별자(선택). 없으면 서버가 새로 발급해 응답에 담아준다.")

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("message는 공백만으로 이루어질 수 없습니다.")
        return stripped


class ChatResponse(BaseModel):
    """/chat 응답 본문 — 최종 답변과 그에 딸린 구조화된 부가 정보.

    여기는 '형식'만 정의하고, 값은 answer.py 의 to_chat_response() 가 채운다.
    done 이벤트의 data 가 곧 이 모델이며 프론트는 이걸 확정본으로 삼는다 — 여기 빠진 필드는
    화면에서 사라지고, 흘려보낸 answer_delta 도 done.answer 로 덮인다.

    단일/복합 규칙: 복합이면 근거를 전부 sub_answers 에 담고 최상위 sources/attachments 는
    빈 배열로 둔다(프론트 계약). 단일이면 그 반대로 최상위만 채우고 sub_answers 를 비운다.
    """
    answer: str = Field(description="최종 답변 본문(단일 질문일 때). 복합 질문은 sub_answers 참고.")
    sources: list[SourceItem] = Field(default_factory=list, description="답변 출처 목록.")
    attachments: list[Attachment] = Field(
        default_factory=list, description="민원 서류/신청 링크(civil_petition 의도일 때만 채워짐).")
    out_of_scope: bool = Field(
        default=False,
        description="업무 범위 밖 질문 여부. 별도 OOS 판정기가 없어 '모든 하위 답변이 근거 미사용'"
                    "으로 대신 판정한다(answer.to_chat_response). true 면 프론트가 출처·서류 섹션을 안 그린다.")
    sub_answers: list[SubAnswer] = Field(
        default_factory=list, description="복합 질문(멀티쿼리)의 개별 답변들. 배열로 유지.")
    clarification: Optional[Clarification] = Field(
        default=None, description="질문이 애매해 재질문이 필요할 때의 되묻기 구조(문구+선택지).")
    error: Optional[ApiError] = Field(
        default=None, description="오류 정보(common.ApiError 재사용). 정상 응답이면 null.")
    # 화면은 쓰지 않고 로깅·분석용이다(프론트 types.ts 에서도 선택 필드). accepted~done 전체
    # 소요이며 sse.py 가 측정한다 — src/performance.py 의 초 단위 값과 달리 밀리초다.
    latency_ms: Optional[int] = Field(
        default=None, description="요청 접수부터 done 까지 걸린 시간(ms).")
    # 프론트가 이 값으로 /chat/{id} 주소를 잡고 새로고침 복원을 한다 — 없으면 복원이 안 된다.
    # 요청에 session_id 가 없었으면 서버가 새로 발급해 여기에 담는다.
    session_id: str = Field(description="세션 식별자. 프론트의 /chat/{id} 주소·새로고침 복원에 쓰인다.")
    # 이 '답변' 하나를 가리키는 식별자(피드백 대상). 피드백 요청 본문에서는 이 값을
    # answer_request_id 로 실어 보낸다(멱등키 request_id 와 뜻이 달라 이름을 구분함). 미들웨어가
    # 요청마다 발급하는 추적용 request_id(X-Request-ID 헤더)와도 별개다 — 생성은 answer.py.
    request_id: str = Field(description="이 답변의 식별자(피드백 대상). 미들웨어 추적용 request_id 와 별개.")
