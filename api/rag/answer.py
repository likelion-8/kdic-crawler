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
from typing import NamedTuple, Optional

# src/ 빌딩블록 (flat import — api/__init__.py 가 sys.path 에 src/ 를 넣어줌). pipeline.py 와
# 완전히 같은 함수들을 쓴다. src/ 는 읽기만 하고 수정하지 않는다.
from query_decomposer import decompose_query
from query_planner import plan_query, USE_QUERY_PLANNER
from query_classifier import classify_intent
from retrieval import USE_TYPE_ROUTING, route_search_chunks
from candidate_ranking import MIN_TOP1_SCORE, gate3_exit, top_k_cut
from citation import format_all_citations
from civil_petition import build_civil_petition_answer
from llm_client import call_hyperclova
from prompt_builder import (NO_RELEVANT_EVIDENCE_MESSAGE, OUT_OF_SCOPE_MESSAGE,
                            _strip_no_source_marker, build_civil_petition_prompt,
                            build_informational_prompt, strip_urls, with_retry_notice)
from runtime_config import get_param
from source_check import validate_answer
from source_precheck import classify as precheck_classify
from observability import record_gate3_span

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

# 사후 판정이 "근거 없는 내용을 사실처럼 서술"(ungrounded_claims)로 분류한 답변의 대체 문구는
# prompt_builder.OUT_OF_SCOPE_MESSAGE 다(위에서 import). 환각 본문이 정상 답변처럼 노출되는 것을
# 막는다(2026-08-10 "스파이더맨" 마블 설명 실측). 스트리밍으로 이미 흘러간 델타는 못 무르지만,
# 프론트는 done 의 answer 를 최종으로 신뢰하므로 완성 화면·대화 복원·rag_runs 로그에는 이 문구가
# 남는다. 인사·정체성·정상 거절문은 교체하지 않는다.
#
# 2026-08-25: 정의를 prompt_builder 로 옮겼다 — 생성 단계의 거절 지시(원칙 1·few-shot·
# NO_EVIDENCE_NOTICE)와 이 교체문이 서로 다른 문구였고, 사용자에겐 같은 상황이 세 얼굴로 보였다.

# 사후 판정이 나빴는데 **민원 경로에 공식 신청 진입점(civil.links)이 있을 때** 쓰는 본문.
# 그 링크는 LLM 이 만든 값이 아니라 검색된 업무에서 결정론적으로 나오므로(civil_petition.
# OFFICIAL_APPLY_LINKS) LLM 이 무엇을 답했든 정답이다. 링크를 붙이면서 본문만 "범위 밖"이라고
# 하면 서로 모순되므로 문구도 함께 바꾼다. 사실을 새로 말하지 않는다 — 안내는 첨부가 한다.
APPLY_LINK_FALLBACK_MESSAGE = (
    "요청하신 신청 페이지를 아래에 안내드립니다. 자세한 절차와 준비물은 링크에서 확인하실 수 있습니다."
)

# 재생성 가드의 점수 하한 변천(2026-08-10): 0.60 → 0.45 → 폐지. 처음엔 도메인 인접 범위외의
# 재생성 채택을 점수로 막았지만, 그 역할은 다수결 판정 + 판정 입력에 질문 포함으로 대체됐다
# ("보이스피싱" 0/6 채택 실측). 반면 하한은 정의형 질문(top-1 0.41~0.49)의 정당한 복구를
# 계속 가로막았다. 이제 게이트(MIN_TOP1_SCORE)를 통과한 근거가 있으면 재생성 대상이다 —
# 채택은 어차피 다수결 판정을 통과해야 한다.


@dataclass
class SubPlan:
    """하위 질문 하나의 'LLM 직전까지' 준비물. sse.py 가 prompt 로 토큰을 스트리밍하고,
    끝난 뒤 top/civil/evidence 로 출처·서류·근거재확인을 처리한다.

    Gate3(검색 관련도 게이트)가 EXIT 로 판정하면 prompt 는 None 이다 — LLM 을 아예 안 부르므로
    준비할 필요가 없다. 그 경우 fixed_response 가 채워지고, 호출부(sse.py)는 finalize_sub 를
    타지 않고 fixed_response 를 그대로 확정 답변으로 쓴다."""
    question: str
    intent: str
    top: list                      # [(chunk_id, score, text), ...] — Gate3 EXIT 면 []
    prompt: Optional[list]         # [(role, content), ...] — Gate3 EXIT 면 None(LLM 미호출)
    civil: Optional[dict] = None   # build_civil_petition_answer 결과({procedure,documents,links}) 또는 None
    evidence: str = ""             # 근거 재확인(recheck)용 텍스트
    # Gate3(검색 관련도) EXIT 전용 필드. None 이면 Gate3 를 통과(또는 건너뜀)한 정상 경로다.
    fixed_response: Optional[str] = None   # 확정 답변(HCX 미호출) — NO_RELEVANT_EVIDENCE_MESSAGE
    exit_at: Optional[str] = None          # "gate3" | None
    gate3_reason: Optional[str] = None     # "no_candidates" | "low_retrieval_relevance"
    retrieval_top1_score: Optional[float] = None   # Gate3 판정에 쓴 원본 dense top-1(없으면 None)
    retrieval_threshold: Optional[float] = None    # 판정 당시 threshold(관측용 — 나중에 바뀌어도 고정)
    # 아래 obs_* 는 finalize_sub 가 적고 observation.build 가 읽는 관측용 판정이다. 여기 둔 이유는
    # log_run 이 이미 sub_plans 를 받고 있어 이음매를 넓히지 않아도 값이 건너가기 때문이다.
    # 판정을 안 한 경우 None 을 유지한다 — false 로 적으면 '근거 미사용'이라는 거짓이 된다.
    obs_marker: Optional[bool] = None        # LLM 자기보고 마커([SOURCE_USED]/[NO_SOURCE])
    obs_used_source: Optional[bool] = None   # 최종 판정(검증이 마커를 오버라이드한 결과)
    obs_kind: Optional[str] = None           # validate_answer 의 판정 종류
    obs_appropriate: Optional[bool] = None   # 질문-답변 적절성
    obs_normalized: Optional[bool] = None    # 본문이 표준 안내로 교체됐나
    # 프리체크 섀도 판정(exp/source-precheck-v1, 2026-08-19). 기록만 하고 동작엔 안 쓴다 —
    # 소급 실험(eval_source_precheck_retro.py)의 표본이 여기서 쌓인다. 채택 결정 전까지
    # 이 값으로 분기하면 안 된다.
    obs_precheck: Optional[str] = None            # source_precheck.classify 사유(clean/의심 사유)
    obs_precheck_missing: Optional[list] = None   # number_mismatch 일 때 근거에 없던 수치 토큰


class Plan(NamedTuple):
    """플래너 1콜의 결과. items 는 [(하위질문, intent|None), ...].

    2026-08-25 에 needs_clarification 필드를 뺐다 — 업무 되묻기 판정이 게이트 앞
    (query_rewriter.triage_query)으로 옮겨가 이 콜에서 나오지 않는다(query_planner.QueryPlan
    docstring).

    fallback: True면 플래너 API 호출이 실패해 items 가 실제 판단이 아니라 안전 기본값(단일+
    informational)이라는 뜻(query_planner.plan_query docstring). 기본 False — decompose_query
    폴백 경로(USE_QUERY_PLANNER=False)와 기존 호출부(테스트 등)가 이 필드 없이 Plan([...])만
    만들어도 그대로 "장애 아님"으로 해석되게 하기 위함."""
    items: list
    fallback: bool = False


def plan(query: str) -> Plan:
    """분해·intent 를 한 콜로. pipeline._rag_answer_traced 와 동일 로직으로, 웹 SSE 경로도
    같은 쿼리 플래너를 쓰게 한다(두 경로 동작 일치).

    USE_QUERY_PLANNER면 query_planner.plan_query() 한 콜(structured output)로 둘을 함께
    얻는다. 단일이면 원본 질문으로 검색하고(pipeline 과 동일: 재질문판 문구로 검색 안 함)
    intent만 플래너 결과를 쓴다. False면 기존 decompose_query 로 나누고 intent 는 prepare_sub 에서
    분류하도록 None 을 넘긴다(이 경로는 plan_query 를 아예 안 타므로 fallback 개념이 없다 —
    항상 False)."""
    if get_param("use_query_planner", USE_QUERY_PLANNER):
        p = plan_query(query)
        items = p["items"] or [{"question": query, "intent": "informational"}]
        fallback = bool(p.get("fallback")) or not p["items"]
        if p["should_split"] and len(items) > 1:
            return Plan([(it["question"], it["intent"]) for it in items], fallback)
        return Plan([(query, items[0]["intent"])], fallback)
    subs = decompose_query(query)
    subs = subs if subs and len(subs) > 1 else [query]
    return Plan([(q, None) for q in subs], False)


def prepare_sub(q: str, intent: Optional[str] = None) -> SubPlan:
    """하위 질문 하나에 대해 intent 분류·검색·근거조립·프롬프트까지 준비(동기, LLM 생성 전).
    pipeline._answer_one 의 검색~프롬프트 단계와 동일하다(리랭커 off).

    intent: 쿼리 플래너(plan)가 이미 판단한 값을 넘기면 그대로 쓴다. None이면(플래너 Off 폴백)
    여기서 classify_intent 로 분류한다.

    실행 순서(Gate3, 2026-08-25): route_search_chunks → **원본** 후보 top-1로 Gate3 판정 →
    통과 시에만 top_k_cut → 프롬프트 조립. 이 순서를 지켜야 하는 이유는 gate3_exit 판정이
    반드시 재정렬 전 원본 dense 점수를 봐야 하기 때문이다(candidate_ranking.gate3_exit
    docstring). 이 함수는 리랭커를 쓰지 않으므로(웹 경로는 애초에 rerank 를 안 부른다) 순서
    위반 위험은 크지 않지만, CLI 경로(pipeline._answer_one)와 같은 패턴을 유지한다."""
    if intent is None:
        intent = classify_intent(q)
    # 관리자 화면(AD-007)이 바꾼 값을 쓰되, DB 가 비면 위 상수로 떨어진다. 모듈 최상단이
    # 아니라 여기서 부르는 것이 중요하다 — 위에서 읽어 두면 import 시점에 값이 굳는다.
    candidates = route_search_chunks(q, k=get_param("k_candidates", K_CANDIDATES))

    # Gate3 — 원본 dense 후보의 top-1이 임계값 이하(또는 후보 없음)면 HCX·OpenAI 를 아예
    # 타지 않고 즉시 고정응답으로 끝낸다(기존엔 여기서 근거만 비우고 LLM 에게 "거절문을
    # 그대로 답하라"고 한 번 더 시켰다 — 판정이 이미 난 걸 다시 물어보는 비용 낭비였다).
    # use_type_routing 이 켜져 있으면(admin 파라미터, 기본 Off) candidates 가 Hybrid/RRF
    # 점수일 수 있어 dense 전용 임계값을 적용하지 않고 Gate3 자체를 건너뛴다 — 그 경로는
    # 기존 gate_low_relevance 도 taken 하지 않으므로(리랭커·유형라우팅 on이면 게이트가 사실상
    # 무력화된다는 candidate_ranking.MIN_TOP1_SCORE 경고와 동일 전제) 통과로 취급하고 아래
    # 기존 흐름을 그대로 탄다.
    hybrid_routing = get_param("use_type_routing", USE_TYPE_ROUTING)
    if not hybrid_routing:
        threshold = get_param("min_top1_score", MIN_TOP1_SCORE)
        top1 = candidates[0][1] if candidates else None
        if gate3_exit(candidates, threshold):
            reason = "no_candidates" if not candidates else "low_retrieval_relevance"
            logger.info("Gate3 EXIT(%s): %r top1=%s threshold=%s", reason, q,
                       candidates[0][1] if candidates else None, threshold)
            record_gate3_span(q, exited=True, top1_score=top1, threshold=threshold, reason=reason)
            return SubPlan(
                question=q, intent=intent, top=[], prompt=None, civil=None, evidence="",
                fixed_response=NO_RELEVANT_EVIDENCE_MESSAGE, exit_at="gate3",
                gate3_reason=reason,
                retrieval_top1_score=(candidates[0][1] if candidates else None),
                retrieval_threshold=threshold, obs_used_source=False)
        # 통과도 남긴다 — 임계값 조정의 핵심 표본은 아슬아슬하게 통과한 질문이다. SubPlan 에는
        # EXIT 일 때만 점수가 실리므로(위 필드) 통과 쪽 점수는 이 span 에만 남는다.
        record_gate3_span(q, exited=False, top1_score=top1, threshold=threshold)

    top = top_k_cut(candidates, k=get_param("k_final", K_FINAL))
    if intent == "civil_petition":
        civil = build_civil_petition_answer(top)
        prompt = build_civil_petition_prompt(q, civil)
        evidence = civil["procedure"]
    else:
        civil = None
        prompt = build_informational_prompt(q, top)
        evidence = "\n\n".join(text for _, _, text in top)
    return SubPlan(question=q, intent=intent, top=top, prompt=prompt, civil=civil, evidence=evidence)


def finalize_gate3_exit(sp: SubPlan) -> tuple[SubAnswer, bool]:
    """Gate3 EXIT SubPlan을 SubAnswer로 감싼다. finalize_sub 와 짝을 이루는 함수지만 HCX·
    OpenAI 어느 쪽도 부르지 않는다 — prepare_sub 가 이미 만들어 둔 고정응답을 그대로
    확정한다. used=False 고정(근거를 안 썼으므로 sources/attachments 는 항상 빈 배열)."""
    return SubAnswer(title=sp.question, answer=sp.fixed_response, sources=[], attachments=[]), False


def _build_sources(top: list) -> list[SourceItem]:
    """검색 상위 청크 → 페이지 단위 출처. citation.format_all_citations 가 이미
    {page_id, breadcrumb, title, url} 로 주므로 SourceItem 필드와 1:1 이라 그대로 싣는다."""
    return [SourceItem(**c) for c in format_all_citations([cid for cid, _, _ in top])]


def _build_attachments(civil: dict) -> list[Attachment]:
    """민원 결과의 서류(documents)/신청링크(links)를 kind 로 구분해 Attachment 로.
    documents: {page_id,label,url,labels?}, links: {title,url,breadcrumb}.
    labels 는 같은 다운로드 페이지로 묶인 개별 서류명 목록이다(2건 이상일 때만 있다)."""
    out = [
        Attachment(kind="document", label=d.get("label"), url=d.get("url"),
                   page_id=d.get("page_id"), labels=d.get("labels"))
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
    판정이 근거 사용으로 보면 채택, 아니면 (원문 무관) 미채택. 실패는 미채택으로 떨어져
    원래 거절문이 유지된다.

    같은 프롬프트를 그대로 다시 돌리면 거절이 그대로 재현되기 쉬워(실측: 복구 1/4)
    질문 직전에 RETRY_NOTICE 를 끼워 근거 재확인을 강제한다. 억지 답변 위험은 채택
    조건(판정 통과)이 막는다 — 근거에 정말 없으면 판정이 거절을 유지시킨다.

    ⚠️ 2026-08-20 실험(exp/hcx007-no-marker-v1): 예전엔 재생성본의 마커가 [SOURCE_USED]면
    검증 없이 바로 채택하는 지름길이 있었다. 마커 지시를 프롬프트에서 뺀 지금은
    `_strip_no_source_marker`가 사실상 항상 True를 돌려주므로, 그 지름길을 그대로 두면
    재생성본을 사실상 무조건 채택(재검증 없음)하게 되어 버린다 — 그래서 지름길을 없애고
    재생성본도 항상 사후검증을 거치게 한다(호출 1회 추가, 안전이 우선)."""
    try:
        # 삽입 위치는 prompt_builder 가 정한다 — "질문: " 만 뒤에서 찾으면 사용자가 질문에
        # 그 문자열을 적었을 때 문구가 질문 한가운데 박힌다(with_retry_notice 주석 참고).
        pushed = with_retry_notice(sp.prompt, sp.question, RETRY_NOTICE)
        raw = call_hyperclova(pushed)
        body, _ = _strip_no_source_marker(raw)
        # 단일 검증 1콜(2026-08-14 팀 결정으로 다수결 폐지). 재생성본은 근거를 썼고
        # 질문에도 적절해야 채택한다 — 실패(None)는 미채택으로 원래 거절문 유지.
        v = validate_answer(sp.question, body, sp.evidence)
        return body, bool(v) and v.used_source and v.appropriate and bool(sp.top)
    except Exception:
        logger.warning("재생성 실패 — 원래 답변 유지", exc_info=True)
        return "", False


def finalize_sub(sp: SubPlan, body: str, marker_used_source: Optional[bool]) -> tuple[SubAnswer, bool]:
    """스트리밍이 끝난 하위 답변을 구조화한다. 판정(2026-08-14 팀 결정):
    use_source_recheck 가 켜져 있으면 **모든 답변**을 source_check.validate_answer 1콜로
    검증한다 — used_source 가 마커([SOURCE_USED]/[NO_SOURCE])를 양방향 오버라이드하고,
    appropriate=False(동문서답·근거와 모순)면 본문을 OUT_OF_SCOPE_MESSAGE 로 교체해
    범위외 처리한다. "근거 없는 내용을 사실처럼 서술"(ungrounded_claims)의 본문 교체도
    유지한다 — 인사·정체성·정상 거절문은 appropriate=true·kind 상이라 교체되지 않는다.

    ⚠️ 2026-08-20 실험(exp/hcx007-no-marker-v1): 마커 지시를 프롬프트에서 뺐으므로
    marker_used_source 파라미터는 이제 신뢰할 자기보고가 아니다(대부분 기본값 True로
    들어옴, prompt_builder._strip_no_source_marker 참고). 그래서 기본값을
    `bool(sp.top)`(검색 관련성 게이트를 통과해 근거가 실제로 있는지)로 바꿨다 — 마커를
    믿던 자리를 "근거 존재 여부"로 대체한 것. use_source_recheck Off거나 검증 실패(None)
    같은 fail-open 상황에서도 이 기본값이 안전망 역할을 한다(근거 자체가 없으면 항상
    False). 검증이 성공하면 그 판정(v.used_source and bool(sp.top))이 그대로 최종 판정이다.

    (SubAnswer, used) 를 돌려준다 — used 는 호출부가 out_of_scope 판정과 sources 이벤트 전송
    여부에 쓴다(근거를 안 쓴 답변 = 인사·범위 밖이므로 출처 섹션을 아예 그리지 않는다)."""
    used = bool(sp.top)
    # 나쁜 판정인데 공식 신청 링크가 있어 첨부만 살린 경우. used(=LLM 이 근거를 썼나)와는
    # 별개다 — 출처 청크는 안 붙이고 신청 링크만 붙인다.
    link_rescue = False
    # 관측에는 **원값**을 적는다 — 마커가 없으면 None(모름)이지 True 가 아니다.
    # 이 값이 AD-005 상세의 '마커 [...]' 표기 원천이라, True 로 채우면 화면이 있지도 않은
    # 마커를 사실처럼 보여준다(2026-08-20 수정).
    sp.obs_marker = marker_used_source
    # 프리체크 섀도 기록(exp/source-precheck-v1): 판정만 남기고 동작은 바꾸지 않는다.
    # luna 와 같은 입력(생성 원문 body + 같은 evidence)으로 판정해야 교차표가 성립하므로
    # 재생성·본문 교체보다 앞에서 적는다. 다중 하위질문·civil 도 여기서는 실제 evidence 로
    # 판정돼, 소급 분석이 못 재던 로그의 69%가 표본이 된다. 실패해도 답변을 막지 않는다.
    try:
        # 마커가 없으면(None) marker_no_source 분기는 성립하지 않는다 — 근거 유무(used)를
        # 넘겨 '근거가 있었는데 안 썼다'만 그 분기로 잡히게 한다. None 을 그대로 넘기면
        # falsy 라 전 건이 marker_no_source 로 세어져 섀도 통계가 무너진다.
        pc = precheck_classify(body, sp.evidence, used)
        sp.obs_precheck, sp.obs_precheck_missing = pc.reason, (pc.missing or None)
    except Exception:
        logger.warning("프리체크 섀도 판정 실패 — 기록 없이 계속", exc_info=True)
    if get_param("use_source_recheck", USE_SOURCE_RECHECK):
        # 단일 검증 1콜 — 3표 다수결은 2026-08-14 팀 결정으로 폐지(모든 경로 1콜 통일).
        v = validate_answer(sp.question, body, sp.evidence)
        if v is not None:
            # 검증이 돌았으면 '보정 없음'도 사실이다 — False 로 적는다. None 은 '판정 안 함'
            # 전용이라 여기서 남겨두면 화면이 검증 여부를 구분하지 못한다.
            sp.obs_kind, sp.obs_appropriate = v.kind, v.appropriate
            sp.obs_normalized = False
            used = v.used_source and bool(sp.top)  # 근거가 게이트로 비었으면 출처 붙일 대상이 없다
            inappropriate = not v.appropriate
            # 나쁜 판정(부적절·근거이탈·거절)인데 근거가 강하게 검색돼 있으면 딱 한 번
            # 재생성한다. 단일 판정 1콜은 경계 문항에서 롤마다 흔들리므로(다수결이 있던 이유)
            # 한 롤 판정만으로 정답 후보를 버리지 않는다 — 재생성본도 판정을 통과해야만
            # 채택되니(2연속 실패 확정) 정당한 거절·미달은 그대로 유지된다.
            # ⚠️ 종전에는 '부적절+근거사용'과 '거절'만 구제하고 used_source=false +
            # ungrounded_claims 는 재시도 없이 즉시 범위외로 교체하는 비대칭이 있었다.
            # 2026-08-14 실측(같은 질문 5연속): 4회는 거절→재생성 구제로 정상 답변,
            # 1회가 이 빠진 경로로 떨어져 동일 질문에 답변이 뒤집혔다(관측 기록으로 확인).
            #
            # 2026-08-29: refusal 을 이 조건에서 뺐다. 검증 프롬프트가 "정상 거절도
            # appropriate=true"라고 못 박아 두므로(source_check.VALIDATE_INSTRUCTION), 제대로
            # 거절한 답변이 kind=refusal + 근거 미사용으로 떨어져 전부 재생성 대상이 됐다.
            # rag_runs 실측(08-25~08-28, 하위답변 433건): 그 조합으로 36건을 다시 썼고 구제는
            # 0건이다. 판정기가 이미 정상 응대라고 본 답변이라 재생성본도 같은 거절을 낸다.
            # 값이 있는 쪽은 남긴다 — ungrounded 분기는 같은 창에서 35건 중 17건(49%)이 실제로
            # 구제됐다. inappropriate 로 잡히는 거절(판정기가 "근거에 답이 있는데 거절했다"고
            # 본 건)도 앞 절이 그대로 받는다.
            # ⚠️ 08-14~08-24 창에서는 이 조합도 62건 중 12건(19%)이 구제됐다. 발동률이 다시
            # 오르면 되돌리거나, 검증에 "근거에 답이 있나" 축을 더해 그때만 재생성한다.
            bad = inappropriate or (not used and v.kind == "ungrounded_claims")
            if bad and sp.top:
                # 스트리밍엔 이미 원래 본문이 나갔지만 프론트는 done.answer 를 최종으로 신뢰한다.
                body2, used2 = _regenerate_once(sp)
                if used2:
                    body, used, inappropriate = body2, True, False
            if inappropriate or (not used and v.kind == "ungrounded_claims"):
                # 재생성으로도 구제되지 않았다(또는 근거 자체가 비어 시도조차 못 했다) —
                # 질문에 답하지 못했거나 근거 없는 내용을 사실처럼 서술한 건이므로 본문을
                # 표준 안내로 교체하고 범위외 처리한다(환각·오답 노출 차단).
                # kind=refusal 이 구제에 실패한 경우는 여기 걸리지 않고 원래 거절문을
                # 유지한다 — 정당한 거절문이 범위외 문구보다 정보량이 많다(종전 동작 보존).
                #
                # 예외: 민원 경로에 공식 신청 진입점이 있으면 범위외로 덮지 않는다. 종전에는
                # attachments 가 used 에 묶여 있어(아래 `used and sp.civil`) 시스템이 이미
                # 조립해 둔 신청 URL 까지 함께 버렸다 — '착오송금 반환지원 신청 링크를
                # 알려주세요' 에 링크 없이 범위외 안내만 나갔다(2026-08-27 실측,
                # request_id e47d14d0a21a481cbfa812ffe47bb2eb). 링크는 LLM 의 답변 품질과
                # 무관하게 맞으므로, LLM 이 거절해도 사용자에게 간다.
                # kind=refusal 로 좁힌다 — 여기까지 온 refusal 은 판정기가 "근거에 답이 있는데
                # 거절했다"고 본 건이다(정당한 거절은 appropriate=true 라 이 분기에 들어오지도
                # 않는다). 동문서답·ungrounded 는 링크를 붙일 게 아니라 가려야 할 답변이므로
                # 종전대로 범위외로 덮는다.
                if v.kind == "refusal" and (sp.civil or {}).get("links"):
                    body = APPLY_LINK_FALLBACK_MESSAGE
                    link_rescue = True
                else:
                    body = OUT_OF_SCOPE_MESSAGE
                used = False
                sp.obs_normalized = True
    sp.obs_used_source = used
    # 링크 구제 건은 **관측상** 근거 미사용이 맞다(LLM 이 실제로 안 썼다). 다만 호출부 판정에는
    # '답을 줬다'로 넘긴다 — used 가 false 면 to_chat_response 가 out_of_scope=true 로 매기고,
    # 프론트가 그 값으로 첨부 섹션을 통째로 접는다(AnswerMessage.showSections). 살려 둔 신청
    # 링크가 응답에는 있는데 화면에는 안 나오는 상태가 된다(2026-08-27 브라우저 확인).
    if link_rescue:
        used = True
    # 원칙 5(URL 쓰지 말 것)의 결정론적 백스톱 — 지시만으로는 4.0%가 샜고 존재하지 않는 주소도
    # 있었다(prompt_builder.strip_urls 주석). 판정이 전부 끝난 뒤에 지운다: 검증은 생성 원문을
    # 보고, 사용자·로그·대화복원에 남는 done.answer 에는 URL 이 없다. 스트리밍 델타는 이미
    # 나갔지만 프론트가 done.answer 를 최종으로 신뢰하는 것은 본문 교체와 같은 전제다.
    body = strip_urls(body)
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
    clarification 은 여기서 항상 None 이다 — 되묻기 턴은 이 함수까지 오지 않는다.
    sse 가 판정 즉시 clarification_response() 로 빠져나간다(0-2.7 후속 턴 / 1-1 첫 턴).
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
            trace_id=None, served_from: Optional[str] = None,
            served_label: Optional[str] = None) -> None:
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

    from . import observation
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
        trace_id=trace_id,   # web_chat 루트 span 의 trace_id — AD-005 상세의 Langfuse 링크 원천
        # 검색 상위 청크·검증 판정. 이게 없으면 AD-005 상세의 source_count·source_used·marker·
        # normalized 가 영원히 null 이라 관리자가 원인을 못 가린다(api/rag/observation.py).
        # 플래너 앞에서 끝난 경로(캐시·가드레일·Gate 1·2)는 sub_plans 가 비어 관측이 NULL 이
        # 된다 — 경로를 적어 두지 않으면 AD-005 가 '왜 분류가 없나'를 말할 수 없다.
        observation=observation.with_served_from(observation.build(sub_plans), served_from,
                                                 served_label),
    )


def log_failed_run(question: str, exc: Exception, phase: str, request_id: str, session_id: str,
                   sub_plans: list, latency_ms: int, partial_answer: str = "",
                   trace_id=None) -> None:
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
        trace_id=trace_id,   # 실패 건이야말로 Langfuse 로 어디서 멈췄는지 봐야 한다
        failure_stage=phase,
        # 사용자 문구(ApiError.user_message)가 아니라 내부 원문이다. 사용자 문구는 5종뿐이라
        # 원인 구분이 안 되고, 조사에 필요한 것은 어떤 예외가 어디서 났는지다.
        root_cause=f"{type(exc).__name__}: {exc}",
        # 사용자에게 실제로 나간 코드. 응답 조립(error_from_exception)과 같은 판정을 쓰므로
        # 화면의 오류 코드와 로그의 오류 코드가 갈리지 않는다.
        error_code=classify_error(exc, phase),
    )


# ──────────────────────── 가드레일 · 질의 캐시 (2026-08-13 배선) ────────────────────────
# 종전에는 AD-008 이 게시한 금칙어가 챗 경로 어디에도 적용되지 않았고(F-3), query_cache 는
# 테이블·통계·비우기 API 만 있고 /api/chat 이 읽지도 쓰지도 않았다(F-4). 둘 다 sse.py 가
# 이 헬퍼들을 통해 쓴다. 캐시·가드레일 실패는 답변을 막지 않는다(전부 실패-안전).

GUARDRAIL_BLOCK_MESSAGE = (
    "문의하신 내용에는 안내가 제한되는 표현이 포함되어 있어 답변을 드리기 어렵습니다. "
    "예금보험공사 업무에 대한 질문으로 다시 작성해 주세요.")
CACHE_TTL_H = 24   # PRD-03 AD-009: 적격 질문만 24시간 캐시


def guardrail_hit(text: str, side: str = "질문") -> Optional[str]:
    """게시본 금칙어(blocklist) 첫 적중 단어 -> str | None. side 는 '질문' 또는 '답변'.

    규칙의 필드를 전부 존중한다(2026-08-14 정정 — 종전에는 pattern 만 읽고 유형·적용 범위·
    행별 활성을 무시해서, 관리자가 AD-008 에서 무엇을 고르든 항상 '전 규칙·양방향·문자
    그대로'로 동작했다. 편집 UI 가 받는 값이 실제 동작에 반영되지 않는 거짓 입력칸이었다):
      - active(행별)  꺼진 규칙은 건너뛴다 — 목록 전체 스위치와 별개다
      - scope         '질문'/'답변' 규칙은 해당 방향에서만, '질문 + 답변'은 양방향
      - type          '정규식'은 re 매칭(IGNORECASE), '단어'는 부분 문자열,
                      '사전'은 내장 비속어 사전(api/rag/blocklist_ko.py)을 켠다
      - disabled      '사전' 행에서 관리자가 끈 표제어 — 그 낱말만 빼고 사전을 쓴다
    잘못된 정규식은 그 규칙만 건너뛴다(전체 실패-안전 원칙 유지). 문자열 항목(옛 형식)은
    종전과 같이 '단어·양방향·활성'으로 취급한다.

    ⚠️ '사전' 행의 pattern 은 사람이 읽는 이름일 뿐 매칭에 쓰지 않는다(2026-08-24). 종전에는
    그 이름을 문자열로 찾아서, 기본값 '비속어 기본 사전 (외부 사전)' 을 사용자가 통째로
    입력하지 않는 한 영원히 걸리지 않는 이름뿐인 유형이었다."""
    try:
        from runtime_config import get_prompt
        return blocklist_match((get_prompt("guardrails", None) or {}).get("blocklist"), text, side)
    except Exception:  # noqa: BLE001
        logger.exception("guardrail_hit 실패 — 미적용으로 통과")
    return None


def blocklist_match(block: Optional[dict], text: str, side: str = "질문") -> Optional[str]:
    """금칙어 목록 한 벌을 텍스트에 적용해 첫 적중 표현을 돌려준다.

    게시본(guardrail_hit)과 초안 평가(AD-008 [초안 평가])가 **같은 함수**를 쓴다 — 종전에는
    평가 쪽이 pattern 문자열을 그대로 `in` 으로 찾아, 정규식 규칙은 그 정규식 원문이 답변에
    나올 때만 걸리고 '사전' 규칙은 아예 걸리지 않았다. 평가가 통과시킨 초안이 운영에서
    막히는(또는 그 반대) 어긋남이 거기서 났다(2026-08-24).
    """
    import re as _re

    block = block or {}
    if not block.get("active", True):
        return None
    folded = str(text or "").casefold()
    for item in block.get("items") or []:
        if isinstance(item, str):
            item = {"pattern": item}
        if not item.get("active", True):
            continue
        scope = item.get("scope") or "질문 + 답변"
        if scope != "질문 + 답변" and scope != side:
            continue
        if item.get("type") == "사전":
            from api.rag import blocklist_ko
            # disabled = 관리자가 화면(「사전 보기」)에서 끈 표제어. 없으면 사전 전체를 쓴다
            found = blocklist_ko.find(text, item.get("disabled") or ())
            if found:
                return found
            continue
        w = str(item.get("pattern") or "").strip()
        if not w:
            continue
        if item.get("type") == "정규식":
            try:
                if _re.search(w, str(text or ""), _re.IGNORECASE):
                    return w
            except _re.error:
                logger.warning("금칙어 정규식 오류 — 규칙 건너뜀: %r", w)
            continue
        if w.casefold() in folded:
            return w
    return None


def guardrail_refusal(session_id: str, request_id: str, latency_ms: int) -> ChatResponse:
    """금칙어 적중 시의 고정 거절 응답 — 근거·출처 없이 범위 외로 처리한다."""
    return ChatResponse(
        answer=GUARDRAIL_BLOCK_MESSAGE, sources=[], attachments=[], out_of_scope=True,
        sub_answers=[], clarification=None, error=None,
        latency_ms=latency_ms, session_id=session_id, request_id=request_id)


def clarification_response(clar: dict, session_id: str, request_id: str,
                           latency_ms: int) -> ChatResponse:
    """업무 되묻기 응답 — 검색 전에 끝나므로 출처·서류가 없다(src/clarify.py 참고).

    answer 에는 되묻기 문구를 넣는다: 프론트는 clarification 이 있으면 answer 를 버리지만
    (스키마 계약), 대화 복원·rag_runs 로그·멀티턴 이력은 answer 텍스트를 읽는다 — 특히
    이 문구가 이력에 남아야 다음 턴(버튼 클릭 = 업무명 전송)에서 재작성기가 "직전 챗봇
    턴이 업무를 묻는 질문"임을 보고 원래 질문과 합성할 수 있다.

    out_of_scope=False — 범위 밖이 아니라 범위 안에서 업무를 좁히는 중이다(True 면
    프론트가 범위외 추천 칩을 붙여 되묻기 버튼과 섞인다)."""
    from api.schemas.chat import Clarification
    return ChatResponse(
        answer=clar["question"], sources=[], attachments=[], out_of_scope=False,
        sub_answers=[], clarification=Clarification.model_validate(clar), error=None,
        latency_ms=latency_ms, session_id=session_id, request_id=request_id)


def fixed_gate_response(gate_result, session_id: str, request_id: str, latency_ms: int) -> ChatResponse:
    """Gate 1(결정론적 룰)·Gate 2(임베딩 유사도) 중 하나가 EXIT 로 판정한 질문의 고정 응답을
    ChatResponse 로 감싼다. 두 게이트 모두 gate_result.response_text 속성(gate1.Gate1Result /
    gate2.Gate2Result)을 갖는 결과 객체를 받는다 — 둘 다 검색·LLM 을 타지 않고 즉시 종료하므로
    래핑 로직이 동일해 이 함수 하나를 공유한다.

    근거·출처가 없으므로 out_of_scope=True 로 두어 프론트가 출처·서류 섹션을 그리지 않게 한다
    (인사·정체성·범위 밖 응답과 동일 취급). response_text 가 없으면(설정 누락) 표준 범위외
    문구로 폴백한다."""
    return ChatResponse(
        answer=(getattr(gate_result, "response_text", None) or OUT_OF_SCOPE_MESSAGE),
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
        # id + activated_at — 재적재는 같은 ACTIVE 행을 갱신하므로 id 만으론 색인 교체를 못 본다
        # (2026-08-18 실측: 색인이 바뀌었는데 캐시가 적중함). 교체 시각까지 스냅샷에 넣는다.
        row = session.execute(
            select(search_index_versions.c.id, search_index_versions.c.activated_at)
            .where(search_index_versions.c.status == "ACTIVE")
            .order_by(search_index_versions.c.created_at.desc()).limit(1)).first()
        snap["index"] = f"{row.id}@{row.activated_at}" if row else "none"
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


# 오류 코드 5종의 정적 표(CM-DF-002 04절 · codes.ts ErrorCode). **한 곳에서만 정의한다** —
# 사용자에게 나가는 문구와 관리자 화면(AD-005 오류 정보 4행)이 같은 표를 읽어야 둘이 갈리지
# 않는다. 종전에는 문구가 error_from_exception 안에만 있어서, 관리자 화면은 채울 원천이 없어
# 4행을 통째로 빈 문자열로 내보내고 있었다(2026-08-19 해소).
#
# ⚠️ retryable 과 auto_retry 는 다른 값이다. retryable 은 **사용자가 다시 물어봐도 되는가**(응답
# 봉투에 실려 챗봇 화면의 [다시 시도] 노출을 가른다). auto_retry 는 **서버가 스스로 재시도했는가**
# 로, AD-005 관리자 화면의 '서버 자동 재시도' 행이다. 하나로 묶으면 화면이 하지도 않은 재시도를
# 했다고 말한다.
#
# auto_retry 는 전부 '없음'이다 — 기획서 04절은 LLM_TIMEOUT·LLM_ERROR 에 'BE 재시도 1회'로
# 적혀 있었으나 코드 어디에도 재시도가 없었고, 재시도는 하지 않기로 확정했다(2026-08-19 결정).
# 기획서 04절도 '없음'으로 맞췄다. 나중에 재시도를 넣으면 이 값과 실제 구현을 함께 바꾼다.
ERROR_CATALOG = {
    "LLM_TIMEOUT": {
        "meaning": "답변 생성 시간 초과",
        "user_message": "답변 생성이 지연되고 있어요. 잠시 후 다시 시도해 주세요.",
        "retryable": True, "has_fallback": True, "auto_retry": "없음",
    },
    "LLM_RATE_LIMIT": {
        "meaning": "요청 한도 초과(429)",
        "user_message": "요청이 많아 잠시 지연되고 있어요. 잠시 후 다시 시도해 주세요.",
        "retryable": True, "has_fallback": True, "auto_retry": "없음",
    },
    "LLM_ERROR": {
        "meaning": "답변 생성 실패(5xx·응답 파싱)",
        "user_message": "답변 생성 중 문제가 발생했어요. 잠시 후 다시 시도해 주세요.",
        "retryable": True, "has_fallback": True, "auto_retry": "없음",
    },
    "RETRIEVAL_ERROR": {
        "meaning": "검색 실패 — 근거 자체가 없음",
        "user_message": "관련 자료를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.",
        "retryable": True, "has_fallback": False, "auto_retry": "없음",
    },
    "INTERNAL": {
        "meaning": "그 외 내부 오류",
        "user_message": "일시적인 오류가 발생했어요. 잠시 후 다시 시도해 주세요.",
        "retryable": False, "has_fallback": False, "auto_retry": "없음",
    },
}


def classify_error(exc: Exception, phase: str = "llm") -> str:
    """예외 -> 대문자 5종 code(codes.ts ErrorCode). timeout/rate 는 어느 단계든 우선 감지하고,
    그 외에는 단계(retrieval/llm)로 가른다. 코드만 돌려주므로 응답 조립(error_from_exception)과
    실패 로깅(log_failure)이 같은 판정을 공유한다."""
    msg = f"{type(exc).__name__} {exc}".lower()
    if isinstance(exc, TimeoutError) or "timeout" in msg or "timed out" in msg:
        return "LLM_TIMEOUT"
    if "rate" in msg or "429" in msg or "too many" in msg or "quota" in msg:
        return "LLM_RATE_LIMIT"
    if phase == "retrieval":
        return "RETRIEVAL_ERROR"
    if phase == "llm":
        return "LLM_ERROR"
    return "INTERNAL"


def error_from_exception(exc: Exception, phase: str = "llm", request_id: str = "") -> ApiError:
    """예외를 프론트가 분기하는 ApiError 로 감싼다. 판정은 classify_error, 문구·폴백 여부는
    ERROR_CATALOG 가 정본이다. 사용자 문구는 담되 내부 원문은 로그로만 남긴다.

    fallback_sources 는 codes.ts 의 ERROR_HAS_FALLBACK 표와 같다 — LLM_* 3종만 폴백 출처를
    싣고 RETRIEVAL_ERROR·INTERNAL 은 싣지 않는다(프론트가 그 표로 렌더를 가른다).
    request_id 는 항상 채운다 — 비면 화면의 문의용 요청 ID 줄이 사라진다(핸드오프 §6 B11).
    """
    code = classify_error(exc, phase)
    spec = ERROR_CATALOG[code]
    return ApiError(code=code, retryable=spec["retryable"],
                    fallback_sources=_FALLBACK_SOURCES if spec["has_fallback"] else [],
                    request_id=request_id, user_message=spec["user_message"])
