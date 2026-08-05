"""SSE 스트리밍 — 답변 토큰을 흘리고, 끝에 완성된 ChatResponse 를 done 으로 준다.

이벤트는 모두 `data: {json}\\n\\n` 한 줄 형식이고, JSON 의 type 필드로 구분한다
(프론트 예시가 event: 라인 없이 data 만 쓰는 형태라 그에 맞춤 — 필요하면 named event 로 조정):
  {"type":"answer_delta","text":"..."}      LLM 토큰(내부 마커 제거됨)
  {"type":"done","result":{...ChatResponse...}}  완성 결과(프론트가 최종으로 신뢰)
  {"type":"error","error":{...ApiError...}}      실패/타임아웃

핵심 불변식: answer_delta.text 들을 이어붙인 것 == done.result.answer.
흘려보낸 조각(full_parts)을 그대로 누적해 done.answer 로 쓰므로 구조적으로 보장된다.

동작 구조: chat_event_stream 은 '동기' 제너레이터다. StreamingResponse 가 이를 스레드풀에서
돌리므로 이벤트 루프를 막지 않는다. LLM 토큰은 블로킹 제너레이터(stream_hyperclova)라, 별도
producer 스레드가 queue 에 쌓고 여기서 queue.get(timeout=30) 으로 꺼낸다 — 30초 동안 토큰이
안 오면 Empty 로 잡아 타임아웃 처리한다.
"""
import json
import logging
import queue
import threading

from prompt_builder import _MARKER_RE  # [SOURCE_USED]/[NO_SOURCE] 판정 정규식(운영과 동일 기준)
from llm_client import stream_hyperclova

from api.rag import answer

logger = logging.getLogger(__name__)

# 토큰 간 최대 대기(초). 이 시간 안에 다음 토큰이 안 오면 타임아웃.
TOKEN_TIMEOUT_S = 30
# 마커 판정 전 초기 버퍼 상한(마커는 첫 줄, 최장 "**[ SOURCE_USED ]**:" 도 이보다 짧다).
_MARKER_BUFFER_CAP = 32


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


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
    """POST /api/chat 의 SSE 본체(동기 제너레이터). 분해 → 하위질문마다 (준비→토큰 스트리밍,
    마커 제거) → 완성 ChatResponse 를 done 으로."""
    # 1) 복합 여부 판단(분해). 분해 자체도 LLM 호출이라 실패할 수 있다.
    try:
        sub_qs = answer.decompose(message)
    except Exception as e:  # noqa: BLE001
        logger.exception("[%s] decompose 실패", request_id)
        yield _sse({"type": "error", "error": answer.error_from_exception(e, phase="retrieval").model_dump()})
        return

    composite = len(sub_qs) > 1
    finalized = []
    full_parts = []  # 흘려보낸 모든 조각(구분자 포함) — done.answer 로 쓴다(불변식 보장)

    for i, q in enumerate(sub_qs):
        # 2) 하위질문 준비(검색+프롬프트) — 동기. 여기 실패는 검색/자료 단계로 본다.
        try:
            sp = answer.prepare_sub(q)
        except Exception as e:  # noqa: BLE001
            logger.exception("[%s] prepare_sub 실패: %s", request_id, q)
            yield _sse({"type": "error", "error": answer.error_from_exception(e, phase="retrieval").model_dump()})
            return

        # 복합이면 하위 답변 사이에 구분자를 넣는다(스트림·done.answer 양쪽에 동일 반영).
        if composite and i > 0:
            sep = "\n\n"
            full_parts.append(sep)
            yield _sse({"type": "answer_delta", "text": sep})

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
                    yield _sse({"type": "answer_delta", "text": visible})
            elif kind == "end":
                visible = stripper.finalize()
                if visible:
                    body_parts.append(visible)
                    full_parts.append(visible)
                    yield _sse({"type": "answer_delta", "text": visible})
                break
            else:  # "err"
                err = payload
                break

        if err is not None:
            logger.warning("[%s] 스트리밍 중단: %r", request_id, err)
            yield _sse({"type": "error", "error": answer.error_from_exception(err, phase="llm").model_dump()})
            return

        # 4) 하위 답변 확정(근거 사용 여부 → 출처/서류 구조화)
        finalized.append(answer.finalize_sub(sp, "".join(body_parts), stripper.used_source))

    # 5) 완성 결과
    resp = answer.to_chat_response(finalized, "".join(full_parts), composite, session_id, request_id)
    yield _sse({"type": "done", "result": resp.model_dump()})
