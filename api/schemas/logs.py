"""관리자 대화 로그(AD-005) 응답 스키마.

계약 정본: web/src/routes/admin/logs/api.ts 의 ConversationLogRow · LogSummary ·
ConversationLogDetail · LogErrorDetail · LangfuseTrace 와 export 요청/응답. 필드 이름을 바꾸면
화면이 조용히 빈 칸으로 뜨므로 그 타입들과 1:1로 맞춰 둔다.

## 원천(源) 표기
각 필드 옆 주석은 그 값이 **어디서 오는가**다. 대부분 rag_runs(src/schema.py) 한 행이고,
피드백 계열은 feedback 테이블을 request_id 로 조인해 온다. 마스킹 필드는 api.masking.mask_text
를 거친다(현재 패스스루 — 원문 그대로).

## ⚠️ 원천 없는 필드는 Optional 로 둔다
아래 필드들은 rag_runs 에 **컬럼이 없다**(답변 생성 시점엔 계산되지만 저장되지 않는다).
프론트 타입은 이 중 일부를 non-null 로 적었지만, 스키마에서 억지로 non-null 로 두면 라우터가
값을 **지어내야** 하고(예: source_used=false → 화면이 '검색 근거 미사용'이라 거짓을 말함), 그건
api.ts:39-49 가 경고한 바로 그 사고다. 그래서 여기서는 Optional 로 열어 두어 라우터가 null 을
낼 수 있게 한다. 각 필드의 처리 결정과 프론트 조율 사항은
docs/conversation_logs_field_sources.md 에 정리했다:
    - source_count               (Row)            원천 없음 → null
    - triage                     (Row)            원천 없음 → 라우터가 'NONE' 고정(미확인=사실)
    - classification.business_function            원천 없음(분류 비활성) → null
    - classification.source_used / marker / normalized   답변시 계산·미저장 → null(⚠️ 프론트 조율)
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

# 코드 값 정본은 web/src/lib/codes.ts · logs/api.ts 다. change_request.py/activity.py 와 같은
# 방침으로 enum 을 Literal 로 복제하지 않고 str 로 받는다(어휘가 늘어도 스키마를 안 고침).
# 관련 폐집합: LogStatus 'NORMAL'|'OUT_OF_SCOPE'|'FAILED' · FeedbackVote 'up'|'down' ·
# Intent · QuestionType · BusinessFunction · TriageStatus 'NONE'|'RESOLVED' · ErrorCode.


class ConversationLogRow(BaseModel):
    """목록 한 행. api.ts 의 ConversationLogRow 와 같은 모양이다."""

    request_id: str                         # rag_runs.request_id
    # 🔴 KST(+09:00) ISO 로 내보낸다(activity.py 와 같은 이유 — UTC 로 주면 화면이 9시간 어긋난
    # 시각을 '오늘'로 읽는다). 원천은 rag_runs.created_at.
    occurred_at: str
    question_masked: str                    # mask_text(rag_runs.question) — 현재 패스스루
    intent: Optional[str] = None            # rag_runs.intent — 플래너 전에 죽은 실패 건은 NULL
    # rag_runs.status/failure_stage 로 매핑. ⚠️ OUT_OF_SCOPE 는 source_used(미저장)에서 갈리므로
    # 지금은 NORMAL 과 구분 불가 — docs 참조. NORMAL/FAILED 만 실제로 판정된다.
    status: str
    feedback: Optional[str] = None          # feedback.vote (request_id 조인, 없으면 null)
    source_count: Optional[int] = None      # ⚠️ 원천 없음 → null (docs). 0 을 지어내면 거짓.
    latency_s: Optional[float] = None       # rag_runs.total_latency_ms / 1000
    triage: str = "NONE"                     # ⚠️ 원천 없음 → 'NONE'(미확인=사실). PATCH triage 범위 밖.


class LogSummary(BaseModel):
    """상단 현황 6값. 각 상태 건수는 status 매핑에 의존한다(out_of_scope 한계는 docs)."""

    total: int
    normal: int
    out_of_scope: int
    failed: int
    feedback_up: int
    feedback_down: int


class LangfuseTrace(BaseModel):
    """실행 추적 링크. 검색 후보·단계별 소요는 Langfuse 전담(api.ts:39-49)."""

    id: str                                 # rag_runs.trace_id
    # 바로 열 수 있는 완성 URL. 서버가 Langfuse 호스트를 붙여 준다(프론트가 호스트를 알 이유 없음).
    # trace_id 는 있으나 호스트 설정이 없으면 null → 화면은 링크 없이 id 만 글로 보여준다.
    url: Optional[str] = None


class LogErrorDetail(BaseModel):
    """오류 상세. code→(meaning·user_message·auto_retry·fallback)은 정적 표에서 채운다
    (api/rag/answer.ERROR_CATALOG · codes.ts ErrorCode 대응). 단계·원인은 rag_runs 에서 온다.

    앞 4행은 **전부 nullable** 이다 — rag_runs.error_code 를 적기 시작한 건 2026-08-19 라
    그 이전 실패에는 분류 기록이 없다. 빈 문자열로 내리면 화면이 '오류 코드 ·' 같은 껍데기를
    그리게 되므로, 모르는 것은 null 로 내려 화면이 '기록 없음'이라 말하게 한다."""

    code: Optional[str] = None
    meaning: Optional[str] = None
    user_message: Optional[str] = None
    auto_retry: Optional[str] = None
    fallback: Optional[str] = None
    failure_stage: Optional[str] = None     # rag_runs.failure_stage — 어느 단계에서 멈췄나
    root_cause: Optional[str] = None        # rag_runs.root_cause


class LogClassification(BaseModel):
    """상세의 분류 블록. intent·question_type 만 rag_runs 에 있고 나머지는 원천이 없다(docs)."""

    intent: Optional[str] = None            # rag_runs.intent — 플래너 전에 죽은 실패 건은 NULL
    business_function: Optional[str] = None  # ⚠️ 원천 없음(분류 비활성, 미저장) → null
    # ⚠️ 컬럼은 있지만 웹 경로가 항상 None 을 넘긴다(api/rag/answer.py:260 — "검색 라우팅
    # 내부에서만 쓰고 응답 경로엔 노출되지 않는다"). 2026-08-12 실측: 목록 대상 91건이 전부
    # NULL 이었다. non-Optional 로 두면 상세 요청이 매번 ValidationError 로 500 이 난다.
    question_type: Optional[str] = None     # rag_runs.question_type
    source_used: Optional[bool] = None      # ⚠️ 답변시 계산·미저장 → null. false 지어내면 거짓(선례)
    marker: Optional[str] = None            # ⚠️ 답변시 계산·미저장 → null
    normalized: Optional[bool] = None       # ⚠️ 답변시 계산·미저장 → null


class FeedbackDetail(BaseModel):
    """피드백 상세 — feedback 테이블(request_id 조인)에서 온다. 없으면 상세에서 이 블록은 null."""

    vote: str                               # feedback.vote 'up'|'down'
    at: str                                 # feedback.created_at → KST ISO
    reason_label: str                       # feedback.reason_codes → 라벨(codes.ts ReasonCode)
    comment: str                            # mask_text(feedback.comment) — 현재 패스스루


class ObservedChunk(BaseModel):
    """관측에 남긴 검색 상위 청크 하나. rag_runs.observation 의 subs[].top[] 원소."""
    chunk_id: str
    page_id: str
    score: float


class ObservedSub(BaseModel):
    """하위 질문 하나의 관측. 판정 필드가 None 이면 '판정하지 않음'이지 '아니오'가 아니다."""
    question: str
    intent: Optional[str] = None
    top: list[ObservedChunk] = []
    marker: Optional[bool] = None          # LLM 자기보고 마커
    used_source: Optional[bool] = None     # 최종 판정(검증이 마커를 오버라이드한 결과)
    kind: Optional[str] = None             # validate_answer 판정 종류
    appropriate: Optional[bool] = None     # 질문-답변 적절성
    normalized: Optional[bool] = None      # 본문이 표준 안내로 교체됐나


class RunObservation(BaseModel):
    """답변 1건의 관측 기록. 모양의 정본은 api/rag/observation.py."""
    subs: list[ObservedSub] = []


class ConversationLogDetail(ConversationLogRow):
    """상세 = 행 + 분류·추적·답변·피드백·오류. api.ts 의 ConversationLogDetail 와 1:1."""

    classification: LogClassification
    langfuse: Optional[LangfuseTrace] = None    # trace_id 없으면 null
    total_latency_ms: Optional[int] = None      # rag_runs.total_latency_ms (단계 분해 없이 총합만)
    answer_masked_preview: str                  # mask_text(rag_runs.answer) 앞부분 — 현재 패스스루
    answer_masked_full: str                     # mask_text(rag_runs.answer) 전체 — 현재 패스스루
    feedback_detail: Optional[FeedbackDetail] = None
    error: Optional[LogErrorDetail] = None       # 실패 건에만
    # 관리자가 '왜 이렇게 답했는지'를 보는 근거. 2026-08-14 신설이라 그 이전 대화는 null 이다.
    observation: Optional[RunObservation] = None
    # 조치 내역(2026-08-19). [처리 완료 표시] 때 받은 사유·처리자·시각. 미처리면 전부 null,
    # 이 컬럼이 생기기 전에 처리한 행은 사유만 null 이다.
    triage_reason: Optional[str] = None
    triaged_by: Optional[str] = None
    triaged_at: Optional[str] = None


class ConversationLogList(BaseModel):
    """목록 봉투 — Page<ConversationLogRow> = {items, total, page, size}. page 는 1-base
    (ChangeRequestList/PipelineJobList 와 동일 형태)."""

    items: list[ConversationLogRow] = Field(default_factory=list)
    total: int
    page: int
    size: int


class LogExportRequest(BaseModel):
    """내보내기 요청. 화면에 보이는 현재 필터를 그대로 실어 온다(api.ts exportLogs body).
    fetchLogs 가 보내는 조건과 같아야 대상이 일치한다. 빈 문자열은 '해당 필터 없음'."""

    # 'from' 은 파이썬 예약어라 alias 로 받는다. populate_by_name 으로 from_ 로도 채워진다.
    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(default="", alias="from")
    to: str = ""
    status: str = ""
    intent: str = ""
    feedback: str = ""
    q: str = ""


class LogExportResponse(BaseModel):
    """내보내기 접수 응답. 내보내기 '사실'은 활동 로그(AD-011)에 남는다(api.ts 주석)."""

    export_id: str
    estimated_rows: int
