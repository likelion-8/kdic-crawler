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
    """스트리밍 토큰에서 맨 앞 [SOURCE_USED]/[NO_SOURCE] 마커를 떼어낸다.

    마커는 답변 첫 줄에만 온다(prompt_builder 규칙). 그래서 첫 줄(개행)까지, 혹은 마커보다 긴
    길이까지만 버퍼링해 마커를 판정·제거하고, 그 뒤로는 토큰을 그대로 흘린다. 토큰이 마커를
    쪼개 들어와도(예: "[SOURCE","_USED]\\n") 버퍼링으로 안전하게 합쳐 판정한다.

    하위 답변마다 새 인스턴스를 만들어 상태를 초기화한다(복합 질문 요구사항).
    """

    def __init__(self):
        self._buf = ""
        self._resolved = False
        self.used_source = False  # 마커가 [SOURCE_USED]로 판정되면 True

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
    """POST /api/chat 의 SSE 본체(동기 제너레이터). accepted → 쿼리 플래너(분해+intent) →
    하위질문마다 (준비 → 토큰 스트리밍, 마커 제거) → done.

    sources/attachments 는 별도 이벤트로 보내지 않고 done 에 실린다(사유는 파일 맨 끝 주석).
    실패하면 done 대신 error 가 나가고 스트림이 끝난다."""
    started = time.perf_counter()

    # 0) accepted — 프론트가 이 값으로 URL replaceState·피드백 키를 잡는다. done 의 값과 같아야
    #    한다(핸드오프 §6 B3). 그래서 여기서 새로 만들지 않고 라우터가 준 값을 그대로 쓴다.
    yield _sse("accepted", {"request_id": request_id, "session_id": session_id})

    # 0-1) 질문을 먼저 저장한다(대화 복원용). 답변 뒤에 저장하면 LLM 이 실패한 턴의 질문이
    #      기록에 안 남아, 사용자는 분명 물어봤는데 복원하면 없는 상태가 된다.
    conversation.save_user_message(session_id, message)

    # 1) 쿼리 플래너: 멀티쿼리 분해 + 하위질문별 intent를 한 콜(structured output)로 판단한다.
    #    LLM 호출이라 실패할 수 있다(내부에서 안전 폴백하지만 예외도 방어).
    try:
        plan_items = answer.plan(message)   # [(하위질문, intent|None), ...]
    except Exception as e:  # noqa: BLE001
        logger.exception("[%s] plan 실패", request_id)
        # 기록을 yield 앞에 두는 이유는 아래 세 실패 경로 모두 같다 — yield 뒤에 두면 프론트가
        # 오류 프레임을 받고 연결을 끊었을 때 제너레이터가 재개되지 않아 기록이 통째로 날아간다.
        # log_rag_run 은 내부에서 예외를 삼키므로 이 호출이 오류 전달을 막지는 못한다.
        answer.log_failed_run(message, e, "retrieval", request_id, session_id,
                              sub_plans=[], latency_ms=_elapsed_ms(started))
        yield _sse("error", answer.error_from_exception(e, "retrieval", request_id).model_dump())
        return

    composite = len(plan_items) > 1
    finalized = []
    used_flags = []
    sub_plans = []   # 로깅에 쓸 intent·검색경로 (하위질문마다 다를 수 있다)
    full_parts = []  # 흘려보낸 모든 조각(구분자 포함) — done.answer 로 쓴다(불변식 보장)

    for i, (q, intent) in enumerate(plan_items):
        # 2) 하위질문 준비(검색+프롬프트) — 동기. intent는 플래너 결과를 그대로 넘긴다.
        try:
            sp = answer.prepare_sub(q, intent)
        except Exception as e:  # noqa: BLE001
            logger.exception("[%s] prepare_sub 실패: %s", request_id, q)
            # sub_plans 는 여기까지 성공한 하위질문들이다(이번 것은 아직 안 들어갔다).
            # 복합 질문이 두 번째 하위에서 죽었을 때 어디까지 갔는지가 이 값으로 남는다.
            answer.log_failed_run(message, e, "retrieval", request_id, session_id,
                                  sub_plans=sub_plans, latency_ms=_elapsed_ms(started),
                                  partial_answer="".join(full_parts))
            yield _sse("error", answer.error_from_exception(e, "retrieval", request_id).model_dump())
            return
        sub_plans.append(sp)

        # 복합이면 하위 답변 사이에 구분자를 넣는다(스트림·done.answer 양쪽에 동일 반영).
        if composite and i > 0:
            sep = "\n\n"
            full_parts.append(sep)
            yield _sse("answer_delta", {"text": sep})

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

    # 실사용 로그를 Supabase rag_runs 에 남긴다. 이 행의 request_id 가 곧 사용자가 이 답변에
    # 남길 피드백(POST /api/feedback)의 연결 열쇠다 — 없으면 피드백을 붙일 곳이 사라진다.
    # log_rag_run 은 내부에서 예외를 삼키므로(실패-안전) 답변 전달을 막지 않는다.
    answer.log_run(message, resp, sub_plans, latency_ms)

    # 답변을 저장한다(대화 복원용). 출처·범위외 판정이 확정된 뒤여야 하므로 여기가 맞다.
    conversation.save_assistant_message(session_id, request_id, resp)

    # sources/attachments 이벤트는 보내지 않는다(프론트 합의 2026-08-05).
    # 출처는 근거 사용 여부(source_check)가 확정돼야 정해지는데 그 판정이 스트리밍이 끝난 뒤라,
    # 여기서 보내봐야 done 과 같은 시점이 되어 실익이 없다. 프론트는 done 의 sources/attachments
    # (복합이면 sub_answers 안의 것)로 그린다. 나중에 하위 답변별로 스트리밍을 나누게 되면
    # 그때는 하위가 끝날 때마다 흘려보낼 실익이 생긴다.
    yield _sse("done", resp.model_dump())
