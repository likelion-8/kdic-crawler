"""답변 경로 재구성 + pipeline 산출물을 ChatResponse(구조화)로 매핑.

왜 rag_answer()를 안 부르고 재구성하나: rag_answer()는 (1) 문자열만 반환하고 (2) 모놀리식·
비스트리밍이라 토큰을 흘릴 수 없다. 그래서 src/pipeline.py 는 건드리지 않고, 그 안이 쓰는
'빌딩블록'(분해·분류·검색·근거조립·프롬프트)을 그대로 재사용해 SSE 가 토큰을 흘릴 수 있는
형태로 다시 엮는다. 파라미터(K_CANDIDATES/K_FINAL·리랭커 off·분해 on)는 pipeline 과 동일하게 맞춘다.

여기서 LLM 생성 자체는 하지 않는다 — prepare_sub()가 '프롬프트까지'만 준비하고, 실제 토큰
스트리밍은 api/rag/sse.py 가 llm_client.stream_hyperclova(prompt)로 돌린다. 스트리밍이 끝난
뒤 finalize_sub()가 근거 사용 여부를 확정해 출처/서류를 구조화한다.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional

# src/ 빌딩블록 (flat import — api/__init__.py 가 sys.path 에 src/ 를 넣어줌). pipeline.py 와
# 완전히 같은 함수들을 쓴다. src/ 는 읽기만 하고 수정하지 않는다.
from query_decomposer import decompose_query
from query_classifier import classify_intent
from retrieval import route_search_chunks
from candidate_ranking import top_k_cut
from citation import format_all_citations
from civil_petition import build_civil_petition_answer
from prompt_builder import build_civil_petition_prompt, build_informational_prompt
from source_check import recheck_source_usage

from api.errors import DEFAULT_FALLBACK_SOURCES
from api.schemas.chat import Attachment, ChatResponse, SourceItem, SubAnswer
from api.schemas.common import ApiError

logger = logging.getLogger(__name__)

# pipeline.py 와 동일 값 — 리랭커 off 이므로 route_search_chunks 상위 K_FINAL 을 그대로 쓴다.
K_CANDIDATES = 20
K_FINAL = 5

# 에러 응답에 실을 폴백 출처(공식 페이지). errors.py 것을 그대로 SourceItem 으로.
_FALLBACK_SOURCES = [SourceItem(**s) for s in DEFAULT_FALLBACK_SOURCES]


@dataclass
class SubPlan:
    """하위 질문 하나의 'LLM 직전까지' 준비물. sse.py 가 prompt 로 토큰을 스트리밍하고,
    끝난 뒤 top/civil/evidence 로 출처·서류·근거재확인을 처리한다."""
    question: str
    intent: str
    top: list                      # [(chunk_id, score, text), ...]
    prompt: list                   # [(role, content), ...]
    civil: Optional[dict] = None   # build_civil_petition_answer 결과({procedure,documents,links}) 또는 None
    evidence: str = ""             # 근거 재확인(recheck)용 텍스트


def decompose(query: str) -> list[str]:
    """복합 질문이면 하위 질문 리스트로, 아니면 원본 1개짜리 리스트로. pipeline 과 동일하게
    query_decomposer.decompose_query()를 쓴다(단일이면 원본 그대로 검색)."""
    subs = decompose_query(query)
    return subs if subs and len(subs) > 1 else [query]


def prepare_sub(q: str) -> SubPlan:
    """하위 질문 하나에 대해 intent 분류·검색·근거조립·프롬프트까지 준비(동기, LLM 생성 전).
    pipeline._answer_one 의 검색~프롬프트 단계와 동일하다(리랭커 off)."""
    intent = classify_intent(q)
    candidates = route_search_chunks(q, k=K_CANDIDATES)
    top = top_k_cut(candidates, k=K_FINAL)
    if intent == "civil_petition":
        civil = build_civil_petition_answer(top)
        prompt = build_civil_petition_prompt(q, civil)
        evidence = civil["procedure"]
    else:
        civil = None
        prompt = build_informational_prompt(q, top)
        evidence = "\n\n".join(text for _, _, text in top)
    return SubPlan(question=q, intent=intent, top=top, prompt=prompt, civil=civil, evidence=evidence)


def _build_sources(top: list) -> list[SourceItem]:
    """검색 상위 청크 → 페이지 단위 출처. citation.format_all_citations 가 이미
    {page_id, breadcrumb, title, url} 로 주므로 SourceItem 필드와 1:1 이라 그대로 싣는다."""
    return [SourceItem(**c) for c in format_all_citations([cid for cid, _, _ in top])]


def _build_attachments(civil: dict) -> list[Attachment]:
    """민원 결과의 서류(documents)/신청링크(links)를 kind 로 구분해 Attachment 로.
    documents: {page_id,label,url}, links: {title,url,breadcrumb}."""
    out = [
        Attachment(kind="document", label=d.get("label"), url=d.get("url"), page_id=d.get("page_id"))
        for d in civil.get("documents", [])
    ]
    out += [
        Attachment(kind="link", label=l.get("title"), url=l.get("url"))
        for l in civil.get("links", [])
    ]
    return out


def finalize_sub(sp: SubPlan, body: str, marker_used_source: bool) -> SubAnswer:
    """스트리밍이 끝난 하위 답변을 구조화한다. 근거 사용 여부는 pipeline 과 동일하게 판정한다:
    마커가 [SOURCE_USED]면 그대로 첨부, [NO_SOURCE]면 source_check.recheck_source_usage 로 한 번
    더 확인해 실제로 근거를 썼으면 뒤집는다(인사·거절엔 출처가 안 붙게 하기 위함). 근거 미사용이면
    sources/attachments 를 비운다."""
    used = marker_used_source
    if not used:
        try:
            used = recheck_source_usage(body, sp.evidence)
        except Exception:
            logger.warning("recheck_source_usage 실패 — 출처 미첨부로 처리", exc_info=True)
            used = False
    sources = _build_sources(sp.top) if used else []
    attachments = _build_attachments(sp.civil) if (used and sp.civil) else []
    return SubAnswer(title=sp.question, answer=body, sources=sources, attachments=attachments)


def to_chat_response(finalized: list[SubAnswer], full_answer: str, composite: bool,
                     session_id: str, request_id: str) -> ChatResponse:
    """확정된 하위 답변들을 최종 ChatResponse 로. full_answer 는 sse.py 가 실제로 흘린
    answer_delta 들을 그대로 이어붙인 문자열이라, done.answer == 스트림 합계가 보장된다.

    - 단일: 상위 answer/sources/attachments 채우고 sub_answers 는 비운다.
    - 복합: sub_answers 에 하위별로 담고, 상위 answer 는 스트림 합계(구분자 포함) 그대로 둔다
      (상위 sources/attachments 는 하위에 있으므로 비운다).
    out_of_scope/clarification 은 파이프라인에 구조화된 신호가 없어 기본값(False/None).
    """
    if composite:
        return ChatResponse(
            answer=full_answer, sources=[], attachments=[],
            sub_answers=finalized, session_id=session_id, request_id=request_id,
        )
    s = finalized[0]
    return ChatResponse(
        answer=full_answer, sources=s.sources, attachments=s.attachments,
        sub_answers=[], session_id=session_id, request_id=request_id,
    )


def error_from_exception(exc: Exception, phase: str = "llm") -> ApiError:
    """예외를 프론트가 분기하는 대문자 5종 code 로 매핑한다(errors.py 는 안 건드리고 chat
    경로에서만 매핑 — 팀 결정 A). timeout/rate 는 어느 단계든 우선 감지하고, 그 외에는 단계
    (retrieval/llm)로 가른다. 사용자 문구는 담되 내부 원문은 로그로만 남긴다."""
    msg = f"{type(exc).__name__} {exc}".lower()
    fb = _FALLBACK_SOURCES
    if isinstance(exc, TimeoutError) or "timeout" in msg or "timed out" in msg:
        return ApiError(code="LLM_TIMEOUT", retryable=True, fallback_sources=fb,
                        user_message="답변 생성이 지연되고 있어요. 잠시 후 다시 시도해 주세요.")
    if "rate" in msg or "429" in msg or "too many" in msg or "quota" in msg:
        return ApiError(code="LLM_RATE_LIMIT", retryable=True, fallback_sources=fb,
                        user_message="요청이 많아 잠시 지연되고 있어요. 잠시 후 다시 시도해 주세요.")
    if phase == "retrieval":
        return ApiError(code="RETRIEVAL_ERROR", retryable=True, fallback_sources=fb,
                        user_message="관련 자료를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.")
    if phase == "llm":
        return ApiError(code="LLM_ERROR", retryable=True, fallback_sources=fb,
                        user_message="답변 생성 중 문제가 발생했어요. 잠시 후 다시 시도해 주세요.")
    return ApiError(code="INTERNAL", retryable=False, fallback_sources=fb,
                    user_message="일시적인 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")
