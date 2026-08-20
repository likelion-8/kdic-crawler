"""SSE 스트리밍 — 답변 토큰을 흘리고, 끝에 완성된 ChatResponse 를 done 으로 준다.

프레임 형식은 `event: <이름>\\ndata: <JSON>\\n\\n` 이다(web/src/mocks/README.md §3 정본).
프론트 파서(web/src/lib/api/chat.ts parseFrames)가 `event:` 줄로 이벤트 이름을 읽고 그 이름으로
switch 하므로, event 줄이 없으면 이름이 'message' 가 되어 **모든 이벤트가 조용히 버려진다.**

  event: accepted      data: {request_id, session_id}
  event: answer_delta  data: {text}                     ← 여러 번(내부 마커 제거됨)
  event: done          data: ChatResponse 전문           ← 프론트가 최종으로 신뢰
  event: error         data: ApiError                    ← done 대신 온다

프론트 파서는 sources·attachments 이벤트도 알지만 우리는 보내지 않는다(끝의 주석 참고).

data 는 봉투로 한 번 더 감싸지 않는다 — done 의 data 가 곧 ChatResponse, error 의 data 가 곧
ApiError 다(프론트 ChatStreamEvent 타입이 그렇게 선언돼 있다).

핵심 불변식: answer_delta.text 들을 이어붙인 것 == done.answer.
흘려보낸 조각(full_parts)을 그대로 누적해 done.answer 로 쓰므로 구조적으로 보장된다.

성공이든 실패든 질의 1건은 rag_runs 에 정확히 한 행을 남긴다. 성공은 끝에서 answer.log_run,
실패 3경로는 각자 answer.log_failed_run 이 맡는다. 실패 경로가 그냥 return 하던 시절에는
실패한 질의가 DB에 아예 없어서, 관리자 대화 로그(AD-005)의 실패 집계가 늘 0 이었다.

동작 구조: chat_event_stream 은 '동기' 제너레이터다. StreamingResponse 가 이를 스레드풀에서
돌리므로 이벤트 루프를 막지 않는다. LLM 토큰은 블로킹 제너레이터(stream_hyperclova)라, 별도
producer 스레드가 queue 에 쌓고 여기서 queue.get(timeout=30) 으로 꺼낸다 — 30초 동안 토큰이
안 오면 Empty 로 잡아 타임아웃 처리한다.
"""
import json
import logging
import queue
import threading
import time

from prompt_builder import _MARKER_RE  # [SOURCE_USED]/[NO_SOURCE] 판정 정규식(운영과 동일 기준)
from llm_client import stream_hyperclova

from api.rag import answer, conversation

logger = logging.getLogger(__name__)

# 토큰 간 최대 대기(초). 이 시간 안에 다음 토큰이 안 오면 타임아웃.
TOKEN_TIMEOUT_S = 30
# 마커 판정 전 초기 버퍼 상한(마커는 첫 줄, 최장 "**[ SOURCE_USED ]**:" 도 이보다 짧다).
_MARKER_BUFFER_CAP = 32


def _sse(event: str, data) -> str:
    """SSE 프레임 한 개. event 줄이 반드시 있어야 프론트 파서가 이벤트를 알아본다."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _elapsed_ms(started: float) -> int:
    """시작 시점부터 지금까지(ms). 성공·실패 양쪽이 같은 기준으로 재도록 한 곳에 둔다."""
    return int((time.perf_counter() - started) * 1000)


class _MarkerStripper:
    """스트리밍 토큰에서 맨 앞 [SOURCE_USED]/[NO_SOURCE] 마커가 있으면 떼어낸다.

    ⚠️ 2026-08-20 실험(exp/hcx007-no-marker-v1): 마커 지시를 프롬프트에서 뺐으므로
    (prompt_builder.SYSTEM_INSTRUCTION), 정상적인 응답엔 이제 마커가 없다. 그래도 첫 줄
    버퍼링 자체는 그대로 둔다 — 과거 게시된 관리자 프롬프트(AD-008)가 여전히 마커를 요구할
    수 있어 하위호환 파싱은 유지한다. 마커가 없으면 최종 판정은 전적으로 검색 관련성 게이트
    +사후검증(answer.finalize_sub)에 맡긴다 — 그래서 기본값을 True(일단 근거 사용으로
    가정)로 둔다. 토큰이 마커를 쪼개 들어와도(예: "[SOURCE","_USED]\\n") 버퍼링으로 안전하게
    합쳐 판정한다.

    하위 답변마다 새 인스턴스를 만들어 상태를 초기화한다(복합 질문 요구사항).
    """

    def __init__(self):
        self._buf = ""
        self._resolved = False
        self.used_source = True  # 마커 없으면 기본 True — finalize_sub가 최종 판정

    def feed(self, tok: str) -> str:
        """토큰을 넣고, 지금 흘려보낼 수 있는(마커가 제거된) 텍스트를 반환한다. 아직 판정
        전이면 빈 문자열."""
        if self._resolved:
            return tok
        self._buf += tok
        if "\n" in self._buf or len(self._buf) >= _MARKER_BUFFER_CAP:
            return self._resolve()
        return ""

    def finalize(self) -> str:
        """스트림이 끝났을 때 남은 버퍼를 마저 처리해 반환한다(마커만 있고 개행이 없던 짧은
        답변 등)."""
        if self._resolved:
            return ""
        return self._resolve()

    def _resolve(self) -> str:
        self._resolved = True
        text = self._buf.lstrip()  # pipeline._strip_no_source_marker 와 동일하게 앞 공백 제거 후 판정
        self._buf = ""
        m = _MARKER_RE.match(text)
        if m:
            self.used_source = m.group(1).upper().replace(" ", "_") == "SOURCE_USED"
            return text[m.end():]
        return text


def _stream_one(prompt):
    """prompt 로 LLM 토큰을 producer 스레드에서 뽑아 queue 로 넘긴다. 반환한 queue 에서
    ("tok", 조각) / ("end", None) / ("err", 예외) 를 꺼내 쓴다. get(timeout) 으로 토큰 간
    타임아웃을 건다."""
    q: queue.Queue = queue.Queue()

    def _produce():
        try:
            for tok in stream_hyperclova(prompt):
                q.put(("tok", tok))
            q.put(("end", None))
        except Exception as ex:  # noqa: BLE001 — 그대로 소비 측에 전달해 error 이벤트로 변환
            q.put(("err", ex))

    threading.Thread(target=_produce, daemon=True).start()
    return q


def chat_event_stream(message: str, session_id: str, request_id: str):
    """POST /api/chat 의 SSE 본체(동기 제너레이터). accepted → 가드레일 → 질의 캐시 → Gate 1
    → Gate 2 → 쿼리 플래너(분해+intent) → 하위질문마다 (준비 → 토큰 스트리밍, 마커 제거) → done.

    sources/attachments 는 별도 이벤트로 보내지 않고 done 에 실린다(사유는 파일 맨 끝 주석).
    실패하면 done 대신 error 가 나가고 스트림이 끝난다."""
    started = time.perf_counter()

    # 0) accepted — 프론트가 이 값으로 URL replaceState·피드백 키를 잡는다. done 의 값과 같아야
    #    한다(핸드오프 §6 B3). 그래서 여기서 새로 만들지 않고 라우터가 준 값을 그대로 쓴다.
    yield _sse("accepted", {"request_id": request_id, "session_id": session_id})

    # 0-1) 멀티턴 컨텍스트 — 이전 턴 이력을 **이번 질문을 저장하기 전에** 읽는다(저장 후에
    #      읽으면 방금 질문이 이력에 섞여 재작성기가 자기 자신을 맥락으로 본다). 첫 턴이면
    #      빈 리스트라 아래 재작성(0-2.5)이 통째로 건너뛰어진다 — 단일 턴 비용·동작 불변.
    history = conversation.recent_messages(session_id)

    #      질문을 먼저 저장한다(대화 복원용). 답변 뒤에 저장하면 LLM 이 실패한 턴의 질문이
    #      기록에 안 남아, 사용자는 분명 물어봤는데 복원하면 없는 상태가 된다.
    conversation.save_user_message(session_id, message)

    # 0-2) 가드레일 — AD-008 게시본 금칙어를 질문에 적용한다(질문·답변 양방향의 앞쪽 절반).
    #      적중이면 LLM 을 부르지 않고 고정 거절로 답한다(2026-08-13 F-3 배선).
    hit = answer.guardrail_hit(message, side="질문")
    if hit is not None:
        resp = answer.guardrail_refusal(session_id, request_id, _elapsed_ms(started))
        logger.info("[%s] 금칙어 적중(질문): %r", request_id, hit)
        answer.log_run(message, resp, [], resp.latency_ms)
        conversation.save_assistant_message(session_id, request_id, resp)
        yield _sse("answer_delta", {"text": resp.answer})
        yield _sse("done", resp.model_dump())
        return

    # 0-2.5) 멀티턴 재작성(2026-08-19, src/query_rewriter.py) — 이전 턴이 있으면 후속 질문을
    #      독립 질문으로 편다("그거 신청 기한은?" → "착오송금 반환지원 신청 기한은 언제인가요?").
    #      가드레일(원문 금칙어) **뒤**, 캐시·게이트 **앞**이 자리다: 이후 전 단계(캐시 키·
    #      Gate 1/2 판정·분해·검색·캐시 적재)가 독립 질문 기준으로 일관되게 돈다 — 특히
    #      Gate 2 는 도메인 신호 없는 파편 문장("그거는요?")을 범위외로 오차단할 수 있어,
    #      재작성 없이는 멀티턴이 게이트에 막힌다. 실패·무이력은 원문 그대로(fail-open).
    #      저장(위 0-1)·rag_runs 로그는 사용자가 실제 쓴 원문(message)을 유지하고, 재작성문은
    #      검색·판정에만 쓴다 — 하위 질문(sub_plans[].question)으로 관측에 남는다.
    query = message
    if history:
        from query_rewriter import rewrite_followup
        rewritten = rewrite_followup(message, history)
        if rewritten and rewritten != message:
            query = rewritten
            logger.info("[%s] 멀티턴 재작성: %r -> %r", request_id, message, query)

    # 0-3) 질의 캐시 — 2026-08-19 팀 결정: 턴 수 제한 없이 모든 질문에 대해 조회한다(가드레일
    #      → 캐시 → Gate 1 순서로 재편하면서, '단일 턴(첫 턴)' 적격 제한을 없앴다). 예전에는
    #      대화 맥락에 따라 뜻이 달라질 수 있는 후속 질문에 캐시를 잘못 돌려줄 위험 때문에
    #      첫 턴에서만 봤지만, 이제는 그 위험을 감수하고 모든 턴에서 캐시를 먼저 본다.
    #      관리자 답변 매핑(curated_get, AD-009)은 이 개편과 함께 서빙 경로에서 제거했다
    #      (admin_ops.py 상단 주석 참고 — 관리자 CRUD 자체는 그대로 남아 있다).
    #      적중 시 검색·생성을 통째로 건너뛴다. 캐시 실패는 미스로 취급되어 답변을 막지 않는다.
    cached = answer.cache_get(query)
    if cached is not None:
        resp_dict = {**cached, "session_id": session_id, "request_id": request_id,
                     "latency_ms": _elapsed_ms(started)}
        from api.schemas.chat import ChatResponse
        resp = ChatResponse.model_validate(resp_dict)
        logger.info("[%s] 질의 캐시 적중", request_id)
        answer.log_run(message, resp, [], resp.latency_ms)
        conversation.save_assistant_message(session_id, request_id, resp)
        yield _sse("answer_delta", {"text": resp.answer})
        yield _sse("done", resp.model_dump())
        return

    # 0-4) Gate 1 — 파이프라인의 결정론적 룰 필터(정규화 + 고정 규칙, LLM 없음). 2026-08-19
    #      가드레일·캐시 다음 순서로 이식됐다(팀 결정 — 캐시가 먼저 보고, 캐시에도 없는
    #      질문만 Gate 1 이 본다). 인사·감사·노이즈·정체성·보안우회·개인정보 직접조회·명백한
    #      타 분야 단일 질문만 '확실할 때' EXIT 로 즉시 고정 응답한다(precision ≈ 100% 목표 —
    #      애매하면 CONTINUE). EXIT 처리는 가드레일 거절과 같은 골격이다(질문은 위에서 저장
    #      완료 → 고정 응답 저장 → answer_delta·done). 웹 경로는 ambient trace 가 없어
    #      (record_trace docstring) Gate 1 결과를 record_trace 메타데이터로 남긴다.
    from gate1 import run_gate1
    g1 = run_gate1(query)
    if g1.action == "EXIT":
        resp = answer.fixed_gate_response(g1, session_id, request_id, _elapsed_ms(started))
        logger.info("[%s] Gate1 EXIT: %s (%s)", request_id, g1.label, g1.rule_id)
        from observability import record_trace
        record_trace("web_chat", input={"question": message},
                     output={"answer": resp.answer, "out_of_scope": resp.out_of_scope},
                     metadata={"request_id": request_id, "session_id": session_id,
                               "latency_ms": resp.latency_ms, "exit_at": "gate1",
                               "gate1_label": g1.label, "gate1_rule_id": g1.rule_id,
                               "gate1_reason": g1.reason})
        answer.log_run(message, resp, [], resp.latency_ms)
        conversation.save_assistant_message(session_id, request_id, resp)
        yield _sse("answer_delta", {"text": resp.answer})
        yield _sse("done", resp.model_dump())
        return

    # 0-5) Gate 2 V6 — request-unit semantic scope gate.
    # EXIT stops here. MIXED allows only IN_SCOPE units into downstream stages.
    from gate2 import run_gate2
    g2 = run_gate2(query)
    if g2.action == "EXIT":
        resp = answer.fixed_gate_response(g2, session_id, request_id, _elapsed_ms(started))
        logger.info("[%s] Gate2 V6 EXIT: %s", request_id, g2.reason)
        from observability import record_trace
        record_trace(
            "web_chat",
            input={"question": message},
            output={"answer": resp.answer, "out_of_scope": resp.out_of_scope},
            metadata={
                "request_id": request_id, "session_id": session_id,
                "latency_ms": resp.latency_ms, "exit_at": "gate2_v6",
                "gate2_action": g2.action, "gate2_prediction": g2.prediction,
                "gate2_unitizer_mode": g2.unitizer_mode,
                "gate2_in_scope_count": len(g2.in_scope_units),
                "gate2_oos_count": len(g2.oos_units),
            },
        )
        answer.log_run(message, resp, [], resp.latency_ms)
        conversation.save_assistant_message(session_id, request_id, resp)
        yield _sse("answer_delta", {"text": resp.answer})
        yield _sse("done", resp.model_dump())
        return

    try:
        if g2.action == "MIXED":
            plan_items = []
            for unit in g2.units:
                if unit.prediction == "OOS":
                    plan_items.append((unit.request_unit, None, True))
                    continue
                for q, intent in answer.plan(unit.request_unit):
                    plan_items.append((q, intent, False))
        else:
            plan_items = [(q, intent, False) for q, intent in answer.plan(query)]
    except Exception as e:  # noqa: BLE001
        logger.exception("[%s] plan 실패", request_id)
        answer.log_failed_run(
            message, e, "retrieval", request_id, session_id,
            sub_plans=[], latency_ms=_elapsed_ms(started),
        )
        yield _sse("error", answer.error_from_exception(e, "retrieval", request_id).model_dump())
        return

    composite = len(plan_items) > 1
    finalized = []
    used_flags = []
    sub_plans = []   # 로깅에 쓸 intent·검색경로 (하위질문마다 다를 수 있다)
    full_parts = []  # 흘려보낸 모든 조각(구분자 포함) — done.answer 로 쓴다(불변식 보장)

    for i, (q, intent, gate2_oos) in enumerate(plan_items):
        if composite and i > 0:
            sep = "\n\n"
            full_parts.append(sep)
            yield _sse("answer_delta", {"text": sep})

        if gate2_oos:
            # This OOS unit never reaches prepare_sub/retrieval/prompt/HCX.
            sp = answer.SubPlan(
                question=q, intent="informational", top=[], prompt=[], civil=None, evidence=""
            )
            sub_plans.append(sp)
            body = g2.response_text or answer.OUT_OF_SCOPE_MESSAGE
            sub = answer.SubAnswer(title=q, answer=body, sources=[], attachments=[])
            finalized.append(sub)
            used_flags.append(False)
            full_parts.append(body)
            yield _sse("answer_delta", {"text": body})
            continue

        try:
            sp = answer.prepare_sub(q, intent)
        except Exception as e:  # noqa: BLE001
            logger.exception("[%s] prepare_sub 실패: %s", request_id, q)
            answer.log_failed_run(message, e, "retrieval", request_id, session_id,
                                  sub_plans=sub_plans, latency_ms=_elapsed_ms(started),
                                  partial_answer="".join(full_parts))
            yield _sse("error", answer.error_from_exception(e, "retrieval", request_id).model_dump())
            return
        sub_plans.append(sp)

        # 3) 토큰 스트리밍 + 마커 제거 + 토큰 간 타임아웃
        stripper = _MarkerStripper()
        body_parts = []
        tokens = _stream_one(sp.prompt)
        err = None
        while True:
            try:
                kind, payload = tokens.get(timeout=TOKEN_TIMEOUT_S)
            except queue.Empty:
                err = TimeoutError(f"{TOKEN_TIMEOUT_S}초 동안 토큰 없음")
                break
            if kind == "tok":
                visible = stripper.feed(payload)
                if visible:
                    body_parts.append(visible)
                    full_parts.append(visible)
                    yield _sse("answer_delta", {"text": visible})
            elif kind == "end":
                visible = stripper.finalize()
                if visible:
                    body_parts.append(visible)
                    full_parts.append(visible)
                    yield _sse("answer_delta", {"text": visible})
                break
            else:  # "err"
                err = payload
                break

        if err is not None:
            logger.warning("[%s] 스트리밍 중단: %r", request_id, err)
            # 여기까지 흘러간 본문을 함께 남긴다 — 토큰 타임아웃(30초)인지 LLM 이 초장에
            # 터진 것인지가 '어디까지 답했나'로 갈린다.
            answer.log_failed_run(message, err, "llm", request_id, session_id,
                                  sub_plans=sub_plans, latency_ms=_elapsed_ms(started),
                                  partial_answer="".join(full_parts))
            yield _sse("error", answer.error_from_exception(err, "llm", request_id).model_dump())
            return

        # 4) 하위 답변 확정(근거 사용 여부 → 출처/서류 구조화)
        sub, used = answer.finalize_sub(sp, "".join(body_parts), stripper.used_source)
        finalized.append(sub)
        used_flags.append(used)

    # 5) 완성 결과
    latency_ms = _elapsed_ms(started)
    resp = answer.to_chat_response(
        finalized, used_flags, "".join(full_parts), composite, session_id, request_id, latency_ms)

    # 5-1) 가드레일 — 답변 쪽 절반. 스트리밍으로 이미 나간 조각은 되돌릴 수 없지만 프론트는
    #      done 을 확정본으로 그리므로(계약: done 이 최종) 여기서 거절로 바꾼다.
    # 복합 답변의 resp.answer 는 하위 본문을 이어붙인 것(to_chat_response)이라 최상위 검사로 충분
    a_hit = answer.guardrail_hit(resp.answer, side="답변")
    if a_hit is not None:
        logger.info("[%s] 금칙어 적중(답변): %r — 거절로 대체", request_id, a_hit)
        resp = answer.guardrail_refusal(session_id, request_id, latency_ms)

    # Langfuse root trace — 웹 경로는 스레드풀 소비라 데코레이터 계측이 안 붙는다
    # (observability.record_trace docstring). done 직전에 한 번에 남기고 rag_runs 에 잇는다.
    from observability import record_trace
    trace_id = record_trace(
        "web_chat",
        input={"question": message},
        output={"answer": resp.answer, "out_of_scope": resp.out_of_scope},
        metadata={"request_id": request_id, "session_id": session_id,
                  "latency_ms": latency_ms, "composite": composite,
                  "gate1_label": g1.label, "gate1_reason": g1.reason,
                  "gate2_action": g2.action, "gate2_prediction": g2.prediction,
                  "gate2_unitizer_mode": g2.unitizer_mode,
                  "gate2_in_scope_count": len(g2.in_scope_units),
                  "gate2_oos_count": len(g2.oos_units),
                  "sub_questions": [sp.question for sp in sub_plans]})

    # 실사용 로그를 Supabase rag_runs 에 남긴다. 이 행의 request_id 가 곧 사용자가 이 답변에
    # 남길 피드백(POST /api/feedback)의 연결 열쇠다 — 없으면 피드백을 붙일 곳이 사라진다.
    # log_rag_run 은 내부에서 예외를 삼키므로(실패-안전) 답변 전달을 막지 않는다.
    answer.log_run(message, resp, sub_plans, latency_ms, trace_id=trace_id)

    # 답변을 저장한다(대화 복원용). 출처·범위외 판정이 확정된 뒤여야 하므로 여기가 맞다.
    conversation.save_assistant_message(session_id, request_id, resp)

    # 5-2) 질의 캐시 적재 — 적격: 단일 질문(비복합) · 정보성 · 성공 · 범위 내 · 되묻기 아님
    #      (PRD-03 AD-009). 2026-08-19: '단일 턴'(첫 턴만) 조건은 뺐다 — 0-3 에서 캐시를 턴
    #      제한 없이 조회하는 것과 짝을 맞췄다(가드레일 → 캐시 → Gate 1 재편과 함께). 역할·개인
    #      맥락 판정기는 없으므로 intent=informational 로 갈음한다(civil_petition 은 역할축
    #      위험이 있어 캐시하지 않는다).
    if (not composite and resp.error is None and resp.clarification is None
            and not resp.out_of_scope
            and sub_plans and getattr(sub_plans[0], "intent", None) == "informational"):
        # 캐시 키는 조회(0-3)와 같은 재작성문 — 원문(파편 문장)으로 적재하면 적중이 안 된다.
        answer.cache_put(query, resp)

    # sources/attachments 이벤트는 보내지 않는다(프론트 합의 2026-08-05).
    # 출처는 근거 사용 여부(source_check)가 확정돼야 정해지는데 그 판정이 스트리밍이 끝난 뒤라,
    # 여기서 보내봐야 done 과 같은 시점이 되어 실익이 없다. 프론트는 done 의 sources/attachments
    # (복합이면 sub_answers 안의 것)로 그린다. 나중에 하위 답변별로 스트리밍을 나누게 되면
    # 그때는 하위가 끝날 때마다 흘려보낼 실익이 생긴다.
    yield _sse("done", resp.model_dump())
