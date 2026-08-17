"""답변 경로 재구성 + 그 결과를 ChatResponse(구조화)로 매핑.

⚠️ 이 파일은 src/pipeline.py 를 호출하지 않는다. rag_answer()가 (1) 문자열만 반환하고
(2) 모놀리식·비스트리밍이라 토큰을 흘릴 수 없어서다. 대신 pipeline 이 쓰는 것과 '같은
빌딩블록'(쿼리 플래너·검색·근거조립·프롬프트)을 그대로 재사용해 SSE 가 토큰을 흘릴 수 있는
형태로 다시 엮는다. src/ 는 읽기만 하고 수정하지 않는다.

두 경로가 갈려 있으므로 파라미터(K_CANDIDATES/K_FINAL·리랭커 off·플래너 on)를 pipeline 과
같게 유지하는 것은 수동 책임이다 — 한쪽만 바꾸면 CLI(평가 경로)와 웹 답변이 달라진다.

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
from query_planner import plan_query, USE_QUERY_PLANNER
from query_classifier import classify_intent
from retrieval import route_search_chunks
from candidate_ranking import gate_low_relevance, top_k_cut
from citation import format_all_citations
from civil_petition import build_civil_petition_answer
from llm_client import call_hyperclova
from prompt_builder import (_strip_no_source_marker, build_civil_petition_prompt,
                            build_informational_prompt)
from runtime_config import get_param
from source_check import validate_answer

from api.errors import DEFAULT_FALLBACK_SOURCES
from api.schemas.chat import Attachment, ChatResponse, SourceItem, SubAnswer
from api.schemas.common import ApiError

logger = logging.getLogger(__name__)

# pipeline.py 와 동일 값 — 리랭커 off 이므로 route_search_chunks 상위 K_FINAL 을 그대로 쓴다.
#
# 🔴 실사용자가 타는 경로는 pipeline.py 가 아니라 여기다(파일 상단 참고). 그래서 관리자
# 화면(AD-007)이 바꾼 값이 실제로 먹으려면 **이 두 값도** runtime_config 를 거쳐야 한다.
# 상수는 지우지 않고 문서화된 기본값으로 남긴다 — DB 가 비면 여기로 떨어진다.
K_CANDIDATES = 20
K_FINAL = 5

# pipeline.USE_SOURCE_RECHECK 와 동일 기본값(상수 중복도 위 K_* 와 같은 사정 — pipeline 을
# import 하지 않는다). use_source_recheck 는 사후 검증(validate_answer) 전체의 on/off
# 스위치다: Off 면 마커만 신뢰하고 검증·본문 교체·재생성을 전부 생략한다(2026-08-14 팀 결정).
USE_SOURCE_RECHECK = True

# 에러 응답에 실을 폴백 출처(공식 페이지). errors.py 것을 그대로 SourceItem 으로.
_FALLBACK_SOURCES = [SourceItem(**s) for s in DEFAULT_FALLBACK_SOURCES]

# 사후 판정이 "근거 없는 내용을 사실처럼 서술"(ungrounded_claims)로 분류한 답변의 대체 문구.
# 환각 본문이 정상 답변처럼 노출되는 것을 막는다(2026-08-10 "스파이더맨" 마블 설명 실측).
# 스트리밍으로 이미 흘러간 델타는 못 무르지만, 프론트는 done 의 answer 를 최종으로 신뢰하므로
# 완성 화면·대화 복원·rag_runs 로그에는 이 문구가 남는다. 인사·정체성·정상 거절문은 교체하지 않는다.
OUT_OF_SCOPE_MESSAGE = (
    "문의하신 내용은 예금보험공사가 제공하는 정보의 범위를 벗어난 질문이라 정확한 안내가 "
    "어렵습니다. 예금자보호제도나 착오송금 반환지원 등 공사 업무에 대해 궁금하신 점을 물어봐 주세요."
)

# 재생성 가드의 점수 하한 변천(2026-08-10): 0.60 → 0.45 → 폐지. 처음엔 도메인 인접 범위외의
# 재생성 채택을 점수로 막았지만, 그 역할은 다수결 판정 + 판정 입력에 질문 포함으로 대체됐다
# ("보이스피싱" 0/6 채택 실측). 반면 하한은 정의형 질문(top-1 0.41~0.49)의 정당한 복구를
# 계속 가로막았다. 이제 게이트(MIN_TOP1_SCORE)를 통과한 근거가 있으면 재생성 대상이다 —
# 채택은 어차피 다수결 판정을 통과해야 한다.


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


def plan(query: str) -> list:
    """(하위 질문, intent) 목록. pipeline._rag_answer_traced 와 동일 로직으로, 웹 SSE 경로도
    같은 쿼리 플래너를 쓰게 한다(두 경로 동작 일치).

    USE_QUERY_PLANNER면 query_planner.plan_query() 한 콜(structured output)로 분해+intent를
    함께 얻는다. 단일이면 원본 질문으로 검색하고(pipeline 과 동일: 재질문판 문구로 검색 안 함)
    intent만 플래너 결과를 쓴다. False면 기존 decompose_query 로 나누고 intent 는 prepare_sub 에서
    분류하도록 None 을 넘긴다."""
    if get_param("use_query_planner", USE_QUERY_PLANNER):
        p = plan_query(query)
        items = p["items"] or [{"question": query, "intent": "informational"}]
        if p["should_split"] and len(items) > 1:
            return [(it["question"], it["intent"]) for it in items]
        return [(query, items[0]["intent"])]
    subs = decompose_query(query)
    subs = subs if subs and len(subs) > 1 else [query]
    return [(q, None) for q in subs]


def prepare_sub(q: str, intent: Optional[str] = None) -> SubPlan:
    """하위 질문 하나에 대해 intent 분류·검색·근거조립·프롬프트까지 준비(동기, LLM 생성 전).
    pipeline._answer_one 의 검색~프롬프트 단계와 동일하다(리랭커 off).

    intent: 쿼리 플래너(plan)가 이미 판단한 값을 넘기면 그대로 쓴다. None이면(플래너 Off 폴백)
    여기서 classify_intent 로 분류한다."""
    if intent is None:
        intent = classify_intent(q)
    # 관리자 화면(AD-007)이 바꾼 값을 쓰되, DB 가 비면 위 상수로 떨어진다. 모듈 최상단이
    # 아니라 여기서 부르는 것이 중요하다 — 위에서 읽어 두면 import 시점에 값이 굳는다.
    candidates = route_search_chunks(q, k=get_param("k_candidates", K_CANDIDATES))
    top = gate_low_relevance(top_k_cut(candidates, k=get_param("k_final", K_FINAL)))
    if not top:
        # 무관 질문 게이트에 걸림 — 저점수 청크를 근거로 주면 환각 소재가 되므로 근거 없이
        # 인사 응대/범위외 거절 프롬프트로 보낸다(NO_EVIDENCE_NOTICE). civil_petition 조립은
        # 근거가 있어야 의미가 있으므로 informational 경로로 통일한다.
        return SubPlan(question=q, intent=intent, top=[],
                       prompt=build_informational_prompt(q, []), civil=None, evidence="")
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


RETRY_NOTICE = (
    "(직전 응답이 '근거에 답이 있는데도 거절'로 판정되었습니다. 근거 자료를 다시 읽고, "
    "질문과 관련된 내용이 있으면 반드시 그 내용으로 답하세요. 정말로 관련 내용이 없을 때만 "
    "안내가 어렵다고 하세요.)\n"
)


def _regenerate_once(sp: SubPlan) -> tuple[str, bool]:
    """확률적 거절 복구용 1회 재생성(비스트리밍). (본문, 근거사용) 을 돌려준다 —
    마커가 [SOURCE_USED]거나 판정이 근거 사용으로 보면 채택, 아니면 (원문 무관) 미채택.
    실패는 미채택으로 떨어져 원래 거절문이 유지된다.

    같은 프롬프트를 그대로 다시 돌리면 거절이 그대로 재현되기 쉬워(실측: 복구 1/4)
    질문 직전에 RETRY_NOTICE 를 끼워 근거 재확인을 강제한다. 억지 답변 위험은 채택
    조건(판정 통과)이 막는다 — 근거에 정말 없으면 판정이 거절을 유지시킨다."""
    try:
        role, human = sp.prompt[-1]
        # few-shot 예시에도 "질문: "이 있으므로 마지막(실제 질문) 위치에 끼운다
        idx = human.rfind("질문: ")
        pushed = sp.prompt[:-1] + [(role, human[:idx] + RETRY_NOTICE + human[idx:] if idx >= 0 else human)]
        raw = call_hyperclova(pushed)
        body, marker_used = _strip_no_source_marker(raw)
        if marker_used:
            return body, True
        # 단일 검증 1콜(2026-08-14 팀 결정으로 다수결 폐지). 재생성본은 근거를 썼고
        # 질문에도 적절해야 채택한다 — 실패(None)는 미채택으로 원래 거절문 유지.
        v = validate_answer(sp.question, body, sp.evidence)
        return body, bool(v) and v.used_source and v.appropriate
    except Exception:
        logger.warning("재생성 실패 — 원래 답변 유지", exc_info=True)
        return "", False


def finalize_sub(sp: SubPlan, body: str, marker_used_source: bool) -> tuple[SubAnswer, bool]:
    """스트리밍이 끝난 하위 답변을 구조화한다. 판정(2026-08-14 팀 결정):
    use_source_recheck 가 켜져 있으면 **모든 답변**을 source_check.validate_answer 1콜로
    검증한다 — used_source 가 마커([SOURCE_USED]/[NO_SOURCE])를 양방향 오버라이드하고,
    appropriate=False(동문서답·근거와 모순)면 본문을 OUT_OF_SCOPE_MESSAGE 로 교체해
    범위외 처리한다. "근거 없는 내용을 사실처럼 서술"(ungrounded_claims)의 본문 교체도
    유지한다 — 인사·정체성·정상 거절문은 appropriate=true·kind 상이라 교체되지 않는다.
    검증 실패(None)는 fail-open: 마커 판정 유지 + 적절성 통과(검증이 답변을 막지 않는다).
    스위치 Off 면 마커만 신뢰하고 검증을 통째로 생략한다.

    (SubAnswer, used) 를 돌려준다 — used 는 호출부가 out_of_scope 판정과 sources 이벤트 전송
    여부에 쓴다(근거를 안 쓴 답변 = 인사·범위 밖이므로 출처 섹션을 아예 그리지 않는다)."""
    used = marker_used_source
    if get_param("use_source_recheck", USE_SOURCE_RECHECK):
        # 단일 검증 1콜 — 3표 다수결은 2026-08-14 팀 결정으로 폐지(모든 경로 1콜 통일).
        v = validate_answer(sp.question, body, sp.evidence)
        if v is not None:
            used = v.used_source and bool(sp.top)  # 근거가 게이트로 비었으면 출처 붙일 대상이 없다
            inappropriate = not v.appropriate
            if inappropriate and used:
                # 근거를 쓴 답변이 '부적절' — 단일 판정 1콜은 경계 문항에서 롤마다 흔들린다
                # (다수결이 있던 이유). 정답을 한 롤 판정으로 버리지 않도록 1회 재생성 후
                # 재검증해 2연속 부적절일 때만 확정한다(게이트의 '2연속 실패 확정'과 같은 철학).
                body2, used2 = _regenerate_once(sp)
                if used2:
                    body, used, inappropriate = body2, True, False
            if inappropriate or (not used and v.kind == "ungrounded_claims"):
                # 질문에 답하지 못했거나(동문서답·근거 모순) 근거 없는 내용을 사실처럼
                # 서술 — 본문을 표준 안내로 교체하고 범위외 처리(환각·오답 노출 차단)
                body = OUT_OF_SCOPE_MESSAGE
                used = False
            elif not used and v.kind == "refusal" and sp.top:
                # 근거가 강하게 검색돼 있는데 거절 — HCX 확률적 거절(같은 프롬프트로 정답·거절이
                # 반반 갈리는 것이 실측됨)일 수 있어 딱 한 번 재생성한다. 재생성본도 판정을
                # 통과해야만 채택하므로 정당한 거절(근거에 답이 정말 없는 경우)은 그대로 유지된다.
                # 스트리밍엔 이미 거절문이 나갔지만 프론트는 done.answer 를 최종으로 신뢰한다.
                body2, used2 = _regenerate_once(sp)
                if used2:
                    body, used = body2, True
    sources = _build_sources(sp.top) if used else []
    attachments = _build_attachments(sp.civil) if (used and sp.civil) else []
    return SubAnswer(title=sp.question, answer=body, sources=sources, attachments=attachments), used


def to_chat_response(finalized: list[SubAnswer], used_flags: list[bool], full_answer: str,
                     composite: bool, session_id: str, request_id: str,
                     latency_ms: int) -> ChatResponse:
    """확정된 하위 답변들을 최종 ChatResponse 로. full_answer 는 sse.py 가 실제로 흘린
    answer_delta 들을 그대로 이어붙인 문자열이라, done.answer == 스트림 합계가 보장된다.

    - 단일: 상위 answer/sources/attachments 채우고 sub_answers 는 비운다.
    - 복합: sub_answers 에 하위별로 담고, 상위 answer 는 스트림 합계(구분자 포함) 그대로 둔다.
      상위 sources/attachments 는 비운다 — 프론트 계약(types.ts SubAnswer 주석)이 "sub_answers 가
      비어 있지 않으면 최상위는 빈 배열"로 확정돼 있다.

    out_of_scope: 근거를 하나도 안 쓴 답변(인사·정체성·범위 밖)을 뜻한다. 프론트는 이 값이 true 면
    출처·서류 섹션을 통째로 그리지 않는다(mocks/README §3-2). 파이프라인에 별도 OOS 판정기가 없어
    "모든 하위가 근거 미사용"으로 대신한다.
    clarification 은 되묻기 로직 자체가 아직 없어 None.
    """
    out_of_scope = not any(used_flags)
    # answer 는 스트림 원문(full_answer)이 아니라 확정된 하위 본문으로 조립한다 — finalize_sub 가
    # ungrounded 본문을 교체했을 때 done.answer 에도 반영되게 하기 위함. 교체가 없으면 스트림
    # 합계와 동일하다(구분자 "\n\n" 포함). full_answer 는 하위 호환용 파라미터로 남긴다.
    final_answer = "\n\n".join(s.answer for s in finalized) if finalized else full_answer
    if composite:
        return ChatResponse(
            answer=final_answer, sources=[], attachments=[], sub_answers=finalized,
            out_of_scope=out_of_scope, session_id=session_id, request_id=request_id,
            latency_ms=latency_ms,
        )
    s = finalized[0]
    return ChatResponse(
        answer=final_answer, sources=s.sources, attachments=s.attachments, sub_answers=[],
        out_of_scope=out_of_scope, session_id=session_id, request_id=request_id,
        latency_ms=latency_ms,
    )


def _plan_labels(sub_plans: list) -> tuple[Optional[str], Optional[str]]:
    """하위 계획들 -> (intent, retrieval_route) 로그 문자열.

    복합 질문은 하위마다 intent·검색경로가 다를 수 있어 쉼표로 잇는다(단일이면 값 하나).
    실패 경로는 sub_plans 가 비었거나(플래너 실패) 도중까지만 채워져 있을 수 있어 빈 목록도
    받는다 — 그때는 둘 다 None 이다.
    """
    intents = ",".join(dict.fromkeys(sp.intent for sp in sub_plans)) or None
    routes = ",".join(dict.fromkeys(
        getattr(sp, "route", None) or "" for sp in sub_plans)).strip(",") or None
    return intents, routes


def log_run(question: str, resp: ChatResponse, sub_plans: list, latency_ms: int,
            trace_id=None) -> None:
    """실사용 질의 1건을 Supabase rag_runs 에 남긴다.

    pipeline.rag_answer() 는 자기 안에서 이걸 부르지만 API 는 그 함수를 우회해 흐름을
    재조립하므로(파일 상단 참고), 여기서 따로 불러야 한다. 이 호출이 없으면 웹 챗봇 대화가
    DB에 한 줄도 남지 않고, request_id 가 저장되지 않아 피드백을 붙일 답변도 사라진다.

    status 는 resp.out_of_scope 에서 그대로 끌어온다 — to_chat_response 가 이미 "모든 하위가
    근거 미사용" 으로 판정해 둔 값이라 여기서 다시 계산하지 않는다. 이 값이 안 실리면
    AD-005 요약의 '범위 외' 집계가 영원히 0 이다.

    log_rag_run 은 내부에서 모든 예외를 삼키므로 호출부가 실패를 신경 쓰지 않아도 된다.
    """
    from rag_logger import STATUS_NORMAL, STATUS_OUT_OF_SCOPE, log_rag_run
    intents, routes = _plan_labels(sub_plans)
    log_rag_run(
        question=question,
        answer=resp.answer,
        intent=intents,
        question_type=None,      # 검색 라우팅 내부에서만 쓰고 응답 경로엔 노출되지 않는다
        retrieval_route=routes,
        total_latency_ms=latency_ms,
        request_id=resp.request_id,
        session_id=resp.session_id,
        status=STATUS_OUT_OF_SCOPE if resp.out_of_scope else STATUS_NORMAL,
        trace_id=trace_id,   # observability.record_trace 결과 — AD-005 상세의 Langfuse 링크 원천
    )


def log_failed_run(question: str, exc: Exception, phase: str, request_id: str, session_id: str,
                   sub_plans: list, latency_ms: int, partial_answer: str = "") -> None:
    """에러로 끝난 질의 1건을 rag_runs 에 FAILED 로 남긴다.

    log_run 을 못 쓰는 이유는 그 시점에 ChatResponse 가 없어서다 — 실패 경로는 응답을 완성하지
    못하고 끝난다. 그래서 같은 테이블에 같은 방식으로 쓰되 진입점만 따로 둔다.

    이걸 안 부르면 실패한 질의는 rag_runs 에 **행 자체가 없다.** 그러면 AD-005 요약의 실패
    집계가 언제나 0 이라, 화면상으로는 한 번도 실패한 적 없는 서비스가 된다.

    phase 는 error_from_exception 에 넘긴 값과 같은 것을 그대로 넘긴다("retrieval"/"llm").
    사용자에게 나간 오류코드와 로그의 단계가 갈리면 대조가 안 된다.

    partial_answer: 스트리밍이 끊기기 전까지 사용자에게 실제로 흘러간 본문. 어디까지 답하다
    끊겼는지가 조사에 쓰이므로 남긴다. status 가 FAILED 라 완성된 답변으로 오독될 여지는 없다.
    """
    from rag_logger import STATUS_FAILED, log_rag_run
    intents, routes = _plan_labels(sub_plans)
    log_rag_run(
        question=question,
        answer=partial_answer or None,
        intent=intents,
        question_type=None,
        retrieval_route=routes,
        total_latency_ms=latency_ms,
        request_id=request_id,
        session_id=session_id,
        status=STATUS_FAILED,
        failure_stage=phase,
        # 사용자 문구(ApiError.user_message)가 아니라 내부 원문이다. 사용자 문구는 5종뿐이라
        # 원인 구분이 안 되고, 조사에 필요한 것은 어떤 예외가 어디서 났는지다.
        root_cause=f"{type(exc).__name__}: {exc}",
    )


# ──────────────────────── 가드레일 · 질의 캐시 (2026-08-13 배선) ────────────────────────
# 종전에는 AD-008 이 게시한 금칙어가 챗 경로 어디에도 적용되지 않았고(F-3), query_cache 는
# 테이블·통계·비우기 API 만 있고 /api/chat 이 읽지도 쓰지도 않았다(F-4). 둘 다 sse.py 가
# 이 헬퍼들을 통해 쓴다. 캐시·가드레일 실패는 답변을 막지 않는다(전부 실패-안전).

GUARDRAIL_BLOCK_MESSAGE = (
    "문의하신 내용에는 안내가 제한되는 표현이 포함되어 있어 답변을 드리기 어렵습니다. "
    "예금보험공사 업무에 대한 질문으로 다시 작성해 주세요.")
CACHE_TTL_H = 24   # PRD-03 AD-009: 적격 질문만 24시간 캐시


def guardrail_hit(text: str) -> Optional[str]:
    """게시본 금칙어(blocklist) 첫 적중 단어 -> str | None. 질문·답변 양방향에서 부른다."""
    try:
        from runtime_config import get_prompt
        block = (get_prompt("guardrails", None) or {}).get("blocklist") or {}
        if not block.get("active", True):
            return None
        folded = str(text or "").casefold()
        for item in block.get("items") or []:
            w = item if isinstance(item, str) else (item.get("pattern") or "")
            w = str(w).strip()
            if w and w.casefold() in folded:
                return w
    except Exception:  # noqa: BLE001
        logger.exception("guardrail_hit 실패 — 미적용으로 통과")
    return None


def guardrail_refusal(session_id: str, request_id: str, latency_ms: int) -> ChatResponse:
    """금칙어 적중 시의 고정 거절 응답 — 근거·출처 없이 범위 외로 처리한다."""
    return ChatResponse(
        answer=GUARDRAIL_BLOCK_MESSAGE, sources=[], attachments=[], out_of_scope=True,
        sub_answers=[], clarification=None, error=None,
        latency_ms=latency_ms, session_id=session_id, request_id=request_id)


def gate1_response(g1, session_id: str, request_id: str, latency_ms: int) -> ChatResponse:
    """Gate 1(결정론적 룰)이 EXIT 로 판정한 질문의 고정 응답을 ChatResponse 로 감싼다.

    Gate 1 은 검색·LLM 을 타지 않으므로 근거·출처가 없다 — out_of_scope=True 로 두어 프론트가
    출처·서류 섹션을 그리지 않게 한다(인사·정체성·범위 밖 응답과 동일 취급). g1 은
    gate1.Gate1Result; response_text 가 없으면(설정 누락) 표준 범위외 문구로 폴백한다."""
    return ChatResponse(
        answer=(getattr(g1, "response_text", None) or OUT_OF_SCOPE_MESSAGE),
        sources=[], attachments=[], out_of_scope=True, sub_answers=[],
        clarification=None, error=None,
        latency_ms=latency_ms, session_id=session_id, request_id=request_id)


def _cache_versions() -> dict:
    """캐시 유효성 스냅샷 — PRD-03: 키 = 정규화 질문 + (인덱스·RAG·프롬프트·모델 버전).
    질의별 비우기(admin_ops purge)가 질문 해시로 지우므로 버전은 키가 아니라 **저장값**에
    넣고 조회 시 대조한다 — 버전이 바뀌면 미스로 취급하고 행을 지운다(자동 무효화)."""
    import os
    from db import get_session
    from schema import search_index_versions
    from schema_admin import rag_param_versions
    from sqlalchemy import select
    from runtime_config import current_versions
    snap = {"prompt": current_versions().get("prompt"),
            "model": os.environ.get("CLOVA_MODEL", "")}
    with get_session() as session:
        snap["params"] = session.execute(
            select(rag_param_versions.c.version)
            .where(rag_param_versions.c.status == "current")).scalar()
        snap["index"] = str(session.execute(
            select(search_index_versions.c.id)
            .where(search_index_versions.c.status == "ACTIVE")
            .order_by(search_index_versions.c.created_at.desc()).limit(1)).scalar())
    return snap


def cache_get(question: str) -> Optional[dict]:
    """적중 시 저장된 ChatResponse dict(식별자 제외)를 돌려주고 hit_count 를 올린다."""
    try:
        from datetime import datetime, timezone
        from api.routers.admin_ops import cache_key_for_question
        from db import get_session
        from schema_admin import query_cache
        from sqlalchemy import delete, select, update
        key = cache_key_for_question(question)
        now = datetime.now(timezone.utc)
        with get_session() as session:
            row = session.execute(select(query_cache).where(query_cache.c.cache_key == key)).first()
            if row is None:
                return None
            if row.expires_at is not None and row.expires_at <= now:
                session.execute(delete(query_cache).where(query_cache.c.cache_key == key))
                session.commit()
                return None
            stored = row.response or {}
            if stored.get("_versions") != _cache_versions():
                # 인덱스·설정·프롬프트·모델 중 하나라도 바뀌었다 — 자동 무효화(PRD-03)
                session.execute(delete(query_cache).where(query_cache.c.cache_key == key))
                session.commit()
                return None
            session.execute(update(query_cache).where(query_cache.c.cache_key == key)
                            .values(hit_count=query_cache.c.hit_count + 1, last_hit_at=now))
            session.commit()
            return stored.get("chat")
    except Exception:  # noqa: BLE001
        logger.exception("cache_get 실패 — 미스로 처리")
        return None


def cache_put(question: str, resp: ChatResponse) -> None:
    """적격 응답을 24h TTL 로 저장한다(upsert). 적격 판정은 호출부(sse.py)가 한다."""
    try:
        from datetime import datetime, timedelta, timezone
        from api.routers.admin_ops import cache_key_for_question
        from db import get_session
        from schema_admin import query_cache
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        key = cache_key_for_question(question)
        now = datetime.now(timezone.utc)
        payload = {
            "chat": resp.model_dump(exclude={"session_id", "request_id", "latency_ms"}),
            "_versions": _cache_versions(),
        }
        stmt = pg_insert(query_cache).values(
            cache_key=key, question=question, response=payload,
            created_at=now, expires_at=now + timedelta(hours=CACHE_TTL_H))
        stmt = stmt.on_conflict_do_update(
            index_elements=[query_cache.c.cache_key],
            set_={"question": question, "response": payload,
                  "created_at": now, "expires_at": now + timedelta(hours=CACHE_TTL_H)})
        with get_session() as session:
            session.execute(stmt)
            session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("cache_put 실패 — 저장만 포기")


def error_from_exception(exc: Exception, phase: str = "llm", request_id: str = "") -> ApiError:
    """예외를 프론트가 분기하는 대문자 5종 code 로 매핑한다(codes.ts ErrorCode). timeout/rate 는
    어느 단계든 우선 감지하고, 그 외에는 단계(retrieval/llm)로 가른다. 사용자 문구는 담되 내부
    원문은 로그로만 남긴다.

    fallback_sources 는 codes.ts 의 ERROR_HAS_FALLBACK 표를 그대로 따른다 — LLM_* 3종만 폴백
    출처를 싣고 RETRIEVAL_ERROR·INTERNAL 은 싣지 않는다(프론트가 그 표로 렌더를 가른다).
    request_id 는 항상 채운다 — 비면 화면의 문의용 요청 ID 줄이 사라진다(핸드오프 §6 B11).
    """
    msg = f"{type(exc).__name__} {exc}".lower()
    if isinstance(exc, TimeoutError) or "timeout" in msg or "timed out" in msg:
        return ApiError(code="LLM_TIMEOUT", retryable=True, fallback_sources=_FALLBACK_SOURCES,
                        request_id=request_id,
                        user_message="답변 생성이 지연되고 있어요. 잠시 후 다시 시도해 주세요.")
    if "rate" in msg or "429" in msg or "too many" in msg or "quota" in msg:
        return ApiError(code="LLM_RATE_LIMIT", retryable=True, fallback_sources=_FALLBACK_SOURCES,
                        request_id=request_id,
                        user_message="요청이 많아 잠시 지연되고 있어요. 잠시 후 다시 시도해 주세요.")
    if phase == "retrieval":
        return ApiError(code="RETRIEVAL_ERROR", retryable=True, fallback_sources=[],
                        request_id=request_id,
                        user_message="관련 자료를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.")
    if phase == "llm":
        return ApiError(code="LLM_ERROR", retryable=True, fallback_sources=_FALLBACK_SOURCES,
                        request_id=request_id,
                        user_message="답변 생성 중 문제가 발생했어요. 잠시 후 다시 시도해 주세요.")
    return ApiError(code="INTERNAL", retryable=False, fallback_sources=[],
                    request_id=request_id,
                    user_message="일시적인 오류가 발생했어요. 잠시 후 다시 시도해 주세요.")
