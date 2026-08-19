"""Langfuse 관측(trace) 연동 — 파이프라인 단계별 span 기록의 유일한 진입점.

다른 모듈은 langfuse를 직접 import하지 않고 반드시 이 파일을 거친다. 이유는 rag_logger와
같은 원칙이다: 관측 실패가 챗봇 응답을 막으면 안 된다. langfuse 미설치·키 미설정 어느
경우에도 아래 observe/current_trace_id/flush는 조용히 no-op으로 동작하고, 파이프라인은
평소처럼 굴러간다. (키가 없으면 langfuse SDK 자체도 경고만 찍고 no-op이지만, 패키지가
아예 없는 PC — requirements 갱신 전에 pull만 받은 팀원 — 까지 보호하려면 이 겹이 필요하다.)

설정은 .env의 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST(=LANGFUSE_BASE_URL,
SDK 버전에 따라 읽는 이름이 달라 둘 다 넣어둔다)를 SDK가 자동으로 읽는다.
평가 스크립트 실행이 trace를 오염시키는 게 싫으면 LANGFUSE_TRACING_ENABLED=false 로 끈다.

trace 계층은 데코레이터가 함수 호출 구조에서 자동으로 만든다:
    rag_answer (trace 루트)
      └─ plan_query / route_search_chunks / rerank / call_hyperclova (span·generation)
trace_id는 rag_runs.trace_id로도 남겨(log_rag_run) 관리자 대화 로그 상세(AD-005)가
API_LANGFUSE_HOST로 완성한 링크를 붙일 수 있게 한다(api/config.py 참고).
"""
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # LANGFUSE_* 키 로드 — SDK가 환경변수에서 자동 인식

try:
    from langfuse import get_client, observe  # noqa: F401  (observe는 재수출이 목적)
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

    def observe(*_args, **_kwargs):
        """langfuse 부재 시의 no-op 데코레이터. @observe / @observe(as_type=...) 둘 다 지원."""
        if len(_args) == 1 and callable(_args[0]) and not _kwargs:
            return _args[0]          # @observe (괄호 없이) 형태
        return lambda fn: fn         # @observe(...) 형태


def current_trace_id():
    """현재 실행 중인 trace의 id. 관측이 꺼져 있거나 trace 밖이면 None — 호출부는 그대로
    log_rag_run(trace_id=...)에 넘기면 된다(컬럼이 nullable이라 None이어도 무해)."""
    if not _AVAILABLE:
        return None
    try:
        return get_client().get_current_trace_id()
    except Exception:
        return None


def update_current_generation(**kwargs):
    """현재 generation span에 메타데이터(model 등)를 덧붙인다. 실패해도 무시."""
    if not _AVAILABLE:
        return
    try:
        get_client().update_current_generation(**kwargs)
    except Exception:
        pass


def update_current_span(**kwargs):
    """현재 span의 input/metadata 등을 수동 기록한다. @observe(capture_input=False)와 짝으로
    쓴다 — 메서드에 데코레이터를 그냥 붙이면 self까지 직렬화하려 드는데(QuestionTypeClassifier
    는 참조 임베딩 행렬을 통째로 들고 있다), 자동 캡처를 끄고 필요한 값만 여기로 남긴다."""
    if not _AVAILABLE:
        return
    try:
        get_client().update_current_span(**kwargs)
    except Exception:
        pass


def record_gate1_span(canonical_text, rule_text, result):
    """Gate 1(결정론적 룰) 판정을 현재 trace 의 자식 span(gate1_rulebase)으로 남긴다.

    CLI·평가 경로(@observe 로 ambient trace 가 열려 있는 pipeline.rag_answer 안)에서 부르면
    start_observation 이 현재 컨텍스트 아래에 이 span 을 끼운다. 웹 SSE 경로는 스레드풀
    소비라 ambient 컨텍스트가 없어 이 방식이 안 되므로 거긴 record_trace 메타데이터로 Gate 1
    결과를 남긴다(그쪽은 이 함수를 부르지 않는다).

    관측 실패·비활성은 조용히 무시한다(다른 관측 함수와 같은 원칙 — 챗봇 응답을 막지 않는다).
    result 는 gate1.Gate1Result(action/label/rule_id/reason 필드)."""
    if not _AVAILABLE:
        return
    try:
        span = get_client().start_observation(
            name="gate1_rulebase", as_type="span",
            input={"canonical_text": canonical_text, "rule_text": rule_text})
        span.update(output={
            "action": result.action, "label": result.label,
            "rule_id": result.rule_id, "reason": result.reason})
        span.end()
    except Exception:
        pass


def record_trace(name, *, input=None, output=None, metadata=None):
    """단일 root trace 를 **사후에 한 번에** 기록하고 trace_id 를 돌려준다 — 웹 SSE 경로용.

    웹 응답은 동기 제너레이터를 스레드풀이 조각 단위로 소비한다(starlette
    iterate_in_threadpool — next() 마다 워커 스레드가 바뀔 수 있다). 그래서 pipeline.py 처럼
    @observe 데코레이터로 ambient 컨텍스트를 여는 방식은 조각 사이에 컨텍스트가 유실돼
    쓸 수 없다(이 경로에 계측이 없던 구조적 이유). 대신 done 시점에 질문·답변·메타를 실어
    root trace 하나를 남기고, 그 trace_id 를 rag_runs 에 연결한다(AD-005 링크용).

    한계(의도된 것): 웹 trace 는 단계별 자식 span 이 없다 — 단계 span 은 pipeline 경로
    (CLI·평가)에서 본다. 실패·비활성 시 None(호출부는 그대로 컬럼에 넣으면 된다)."""
    if not _AVAILABLE:
        return None
    try:
        # SDK v4 는 start_span 이 아니라 start_observation(as_type=...) 이다(4.14 실확인).
        span = get_client().start_observation(
            name=name, as_type="span", input=input, metadata=metadata)
        if output is not None:
            span.update(output=output)
        span.end()
        return span.trace_id
    except Exception:
        return None


def flush():
    """버퍼에 남은 trace를 즉시 전송. 서버(FastAPI)는 백그라운드 배치라 부를 필요
    없고, 프로세스가 곧 끝나는 CLI·평가 스크립트가 종료 직전에 부른다(유실 방지)."""
    if not _AVAILABLE:
        return
    try:
        get_client().flush()
    except Exception:
        pass
