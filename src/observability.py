"""Langfuse 관측(trace) 연동 — 파이프라인 단계별 span 기록의 유일한 진입점.

다른 모듈은 langfuse를 직접 import하지 않고 반드시 이 파일을 거친다. 이유는 rag_logger와
같은 원칙이다: 관측 실패가 챗봇 응답을 막으면 안 된다. langfuse 미설치·키 미설정 어느
경우에도 아래 함수들은 조용히 no-op으로 동작하고, 파이프라인은 평소처럼 굴러간다.
(키가 없으면 langfuse SDK 자체도 경고만 찍고 no-op이지만, 패키지가 아예 없는 PC —
requirements 갱신 전에 pull만 받은 팀원 — 까지 보호하려면 이 겹이 필요하다.)

설정은 .env의 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST(=LANGFUSE_BASE_URL,
SDK 버전에 따라 읽는 이름이 달라 둘 다 넣어둔다)를 SDK가 자동으로 읽는다.

trace 계층은 경로에 따라 두 가지 방식으로 만든다.

1. **CLI·평가 경로** — @observe 데코레이터가 함수 호출 구조에서 자동으로 만든다.
       rag_answer (trace 루트)
         └─ plan_query / route_search_chunks / rerank / call_hyperclova
   contextvar 기반이라 같은 스레드에서 이어 부르면 알아서 중첩된다.

2. **웹 SSE 경로** — 동기 제너레이터를 스레드풀이 조각 단위로 소비하므로(starlette
   iterate_in_threadpool — next() 마다 워커 스레드가 바뀔 수 있다) contextvar 가 조각
   사이에 유실된다. 그래서 루트 span 을 open_span() 으로 직접 열어 두고 각 계산 블록을
   as_child_of(부모) 로 감싼다 — 그 블록 안에서 만들어지는 span 은 스레드가 무엇이든
   지정한 부모의 자식이 된다(OTel SpanContext 를 명시적으로 attach 한다).

   ⚠️ 이 배선이 없던 때(~2026-08-26)에는 웹 trace 가 자식 없는 껍데기 하나였고, 실제 단계
   span(plan_query·route_search_chunks·classify_question_type)은 전부 **별개의 고아 trace**
   로 흩어져 한 요청을 쭉 훑을 수가 없었다. 새 코드도 같은 함정을 밟지 않으려면 웹 경로에서
   무언가를 계측할 때 반드시 as_child_of 안에서 해야 한다.

trace_id는 rag_runs.trace_id로도 남겨(log_rag_run) 관리자 대화 로그 상세(AD-005)가
API_LANGFUSE_HOST로 완성한 링크를 붙일 수 있게 한다(api/config.py 참고).
"""
import os
import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # LANGFUSE_* 키 로드 — SDK가 환경변수에서 자동 인식

# 평가·색인 스크립트(src/crawler/*.py)와 pytest 는 기본적으로 trace 를 남기지 않는다.
# 실측 근거(2026-08-26): 전체 trace 14,078건 중 ~70%가 평가 스크립트가 계측된 함수를 직접
# 불러 만든 단발 root trace 였고(route_search_chunks 9,993 · classify_question_type 3,365 ·
# call_hyperclova 1,063 · plan_query 989 · rerank 641), rag_answer trace 114건은 전부
# tests/test_source_pipeline.py 의 모의 실행이었다. 정작 실사용 trace(web_chat 238건)가 그
# 사이에 묻혀 목록으로는 찾을 수가 없었다. 평가 실행도 Langfuse 로 보고 싶으면 그 실행에서만
# LANGFUSE_TRACING_ENABLED=true 를 준다(setdefault 라 명시값이 항상 이긴다).
# ⚠ pytest 판별을 argv[0] 이름으로만 하면 안 된다. `python -m pytest` 로 돌리면 argv[0] 이
# `.../site-packages/pytest/__main__.py` 라 이름이 "__main__.py" 다(2026-08-26 실측). 그 구멍
# 때문에 테스트 실행 45건이 실사용 trace 사이에 섞여 올라갔다 — request_id 가 "req", 질문이
# "복합 질문" 인 trace 들이 그것이다. 모듈 적재 여부로 보는 쪽이 확실하다: 이 파일은 테스트
# 수집 단계에서 import 되므로 그 시점에 pytest 는 이미 sys.modules 에 있다.
# 오프라인 실행으로 보는 디렉터리. 계측된 함수를 직접 부르는 진입점 스크립트는 이 둘뿐이고
# (src/crawler/*, src/eval/*), 나머지는 라이브러리 모듈이거나 서빙 코드다. src/pipeline.py 를
# 터미널로 돌리는 CLI 는 일부러 뺐다 — 그건 실제로 보고 싶은 경로다.
_OFFLINE_DIRS = {"crawler", "eval"}
_ARGV0 = Path(sys.argv[0] or "")
_UNDER_PYTEST = "pytest" in sys.modules or _ARGV0.name in ("pytest", "py.test")
if _OFFLINE_DIRS & set(_ARGV0.parts) or _UNDER_PYTEST:
    os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")

try:
    from langfuse import get_client, observe, propagate_attributes  # noqa: F401  (observe는 재수출이 목적)
    from opentelemetry import context as _otel_context
    from opentelemetry import trace as _otel_trace
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


# ──────────────────────── span 열고·닫기 (웹 SSE 경로의 기본 도구) ────────────────────────

def open_span(name, *, as_type="span", input=None, metadata=None, session_id=None, **kwargs):
    """span 을 열고 **끝내지 않은 채** 돌려준다. 반드시 close_span 으로 닫는다.

    현재 컨텍스트에 부모가 있으면 그 자식이 되고, 없으면 새 trace 의 루트가 된다. 웹 SSE
    경로는 루트를 이걸로 하나 열어 두고(요청 시작) 나머지를 as_child_of 로 붙인다.

    스트리밍 LLM 처럼 시작과 끝이 여러 next() 조각에 걸쳐 있는 구간에도 쓴다 — 컨텍스트가
    아니라 span 객체를 들고 다니므로 스레드가 바뀌어도 소요 시간이 실제 값으로 남는다.
    관측이 꺼져 있거나 실패하면 None(close_span·as_child_of 모두 None 을 무해하게 받는다).

    session_id 를 주면 이 span 이 속한 **trace** 에 세션이 붙어 Langfuse Sessions 에서 대화
    단위로 묶인다. metadata 에 같은 값을 실어도 세션으로는 안 잡힌다 — Langfuse 가 보는 것은
    trace 의 session.id 필드다(2026-08-27 실측: web_chat trace 전량 sessionId 없음). SDK v4 는
    propagate_attributes 컨텍스트 안에서 만들어진 span 에만 이 값을 심으므로 생성 시점을 감싼다.
    루트에만 붙고 자식 span 에는 안 붙는다 — 웹 SSE 는 조각마다 스레드가 바뀌어 컨텍스트가
    유실되기 때문이다(모듈 docstring 2번). trace 를 대화로 묶는 데는 루트 하나로 충분하다."""
    if not _AVAILABLE:
        return None
    try:
        # SDK v4 는 start_span 이 아니라 start_observation(as_type=...) 이다(4.14 실확인).
        with (propagate_attributes(session_id=session_id) if session_id else nullcontext()):
            return get_client().start_observation(
                name=name, as_type=as_type, input=input, metadata=metadata, **kwargs)
    except Exception:
        return None


def close_span(span, *, output=None, metadata=None, **kwargs):
    """open_span 으로 연 span 에 결과를 적고 닫는다. span 이 None 이면 아무 일도 안 한다."""
    if span is None:
        return
    try:
        updates = {k: v for k, v in
                   {"output": output, "metadata": metadata, **kwargs}.items() if v is not None}
        if updates:
            span.update(**updates)
        span.end()
    except Exception:
        pass


def record_span(name, *, as_type="span", input=None, output=None, metadata=None, **kwargs):
    """이미 끝난 단계를 span 하나로 즉시 남긴다(open+close). 판정 결과처럼 '값만 있고 구간이
    없는' 단계용이다 — 소요 시간이 필요하면 open_span/close_span 을 쓴다."""
    span = open_span(name, as_type=as_type, input=input, metadata=metadata, **kwargs)
    close_span(span, output=output)
    return span


@contextmanager
def as_child_of(span):
    """이 블록 안에서 만들어지는 모든 span(@observe 데코레이터 포함)을 span 의 자식으로 붙인다.

    span 을 하나 더 만들지 않는다 — 부모만 명시적으로 갈아끼운다. contextvar 를 신뢰할 수
    없는 곳(스레드풀이 조각 단위로 소비하는 SSE 제너레이터)에서 계층을 유지하는 유일한
    방법이다. span 이 None 이거나 관측이 꺼져 있으면 그냥 통과한다."""
    if not _AVAILABLE or span is None:
        yield
        return
    try:
        ctx = _otel_trace.SpanContext(
            trace_id=int(span.trace_id, 16), span_id=int(span.id, 16),
            trace_flags=_otel_trace.TraceFlags(0x01),  # sampled 로 표시하지 않으면 자식이 버려진다
            is_remote=False)
        token = _otel_context.attach(
            _otel_trace.set_span_in_context(_otel_trace.NonRecordingSpan(ctx)))
    except Exception:
        yield
        return
    try:
        yield
    finally:
        try:
            _otel_context.detach(token)
        except Exception:
            pass


def record_openai_generation(name, completion, *, input=None):
    """OpenAI 구조화 출력 호출 하나를 generation span 으로 남긴다 — 모델·토큰까지.

    langfuse.openai 의 전역 자동계측을 안 쓰는 이유가 둘이다.
    (1) 그 패치는 openai SDK 의 chat.completions 를 통째로 감싸는데, HCX(langchain-naver
        ChatClovaX)도 같은 SDK 를 쓴다 — hcx_stream span 과 토큰이 이중 계상된다.
    (2) HCX 스트리밍은 producer 스레드에서 돌아 자동 span 이 다시 고아가 된다(모듈 docstring 2번).
    호출 지점이 넷뿐이라 명시 계측이 더 싸고 정확하다.

    completion 은 client.beta.chat.completions.parse 의 반환값. 실패한 호출은 completion 이
    없으므로 기록되지 않는다 — 그쪽은 어차피 토큰도 안 쓴다."""
    u = getattr(completion, "usage", None)
    record_span(
        name, as_type="generation", input=input,
        output=getattr(getattr(completion.choices[0], "message", None), "content", None)
        if getattr(completion, "choices", None) else None,
        model=getattr(completion, "model", None),
        usage_details=None if u is None else {
            "input": u.prompt_tokens, "output": u.completion_tokens, "total": u.total_tokens})


def usage_details(usage_metadata):
    """langchain 의 usage_metadata({input_tokens, output_tokens, total_tokens})를 Langfuse
    usage_details({input, output, total})로 옮긴다. 값이 없으면 None — 토큰 정보 없는
    generation 은 그냥 비워 두는 게 맞다(0 으로 채우면 '0 토큰 썼다'는 거짓이 된다)."""
    if not usage_metadata:
        return None
    pairs = (("input", "input_tokens"), ("output", "output_tokens"), ("total", "total_tokens"))
    out = {k: usage_metadata[src] for k, src in pairs if usage_metadata.get(src) is not None}
    return out or None


_ZERO_TRACE_ID = "0" * 32


def trace_id_of(span):
    """span 의 trace_id(없으면 None). rag_runs.trace_id 로 넘겨 AD-005 링크를 만든다.

    관측이 꺼져 있으면(LANGFUSE_TRACING_ENABLED=false) SDK 가 0으로 채운 id 를 돌려준다 —
    그대로 저장하면 AD-005 상세가 존재하지 않는 trace 로 가는 링크를 그린다. None 으로 바꿔
    링크 자체가 안 생기게 한다(api/routers/admin_logs.py._langfuse)."""
    tid = getattr(span, "trace_id", None)
    return None if tid in (None, _ZERO_TRACE_ID) else tid


# ──────────────────────── 게이트 판정 span ────────────────────────

def record_gate1_span(canonical_text, rule_text, result):
    """Gate 1(결정론적 룰) 판정을 현재 컨텍스트의 자식 span(gate1_rulebase)으로 남긴다.
    result 는 gate1.Gate1Result(action/label/rule_id/reason 필드)."""
    record_span("gate1_rulebase",
                input={"canonical_text": canonical_text, "rule_text": rule_text},
                output={"action": result.action, "label": result.label,
                        "rule_id": result.rule_id, "reason": result.reason})


def record_gate2_span(query, result):
    """Gate 2(임베딩 유사도 도메인 판정) 결과를 자식 span(gate2_embedding)으로 남긴다.

    nearest_out_category(내부 판정 카테고리, 예: 프롬프트인젝션)는 trace에는 남기지만 이
    값이 사용자에게 노출되는 것은 아니다 — 사용자 응답은 fixed_gate_response의 고정 문구뿐.
    result 는 gate2.Gate2Result(action/s_id/s_ood/threshold/reason 등 필드)."""
    record_span("gate2_embedding", input={"query": query},
                output={"action": result.action, "s_id": result.s_id, "s_ood": result.s_ood,
                        "threshold": result.threshold,
                        "nearest_out_cluster_id": result.nearest_out_cluster_id,
                        "nearest_out_category": result.nearest_out_category,
                        "reason": result.reason})


def record_gate3_span(query, *, exited, top1_score=None, threshold=None, reason=None):
    """Gate 3(검색 관련도 게이트) 판정을 자식 span(gate3_relevance)으로 남긴다.

    Gate 1·2 와 달리 판정 값이 trace 어디에도 없어서, 임계값(MIN_TOP1_SCORE)을 조정하려면
    rag_runs.observation JSONB 를 SQL 로 뒤져야 했다(2026-08-26). 통과(exited=False)도
    남긴다 — 임계값 근처에서 아슬아슬하게 통과한 질문이 조정의 핵심 표본이다."""
    record_span("gate3_relevance", input={"query": query},
                output={"action": "EXIT" if exited else "CONTINUE",
                        "retrieval_top1_score": top1_score,
                        "threshold": threshold, "reason": reason})


# 서빙 경로가 만드는 generation span 이름 전부. 대시보드 리소스 집계(AD-001)가 이 목록으로
# **실사용 LLM 호출만** 골라낸다 — 평가·CLI 가 만드는 call_hyperclova·rerank 는 빠진다.
# 새 LLM 호출을 계측하면 여기 이름을 더해야 대시보드 비용에 잡힌다.
SERVING_GENERATION_NAMES = ("hcx_stream", "plan_query_llm", "triage_query_llm",
                            "validate_answer_llm", "classify_intent_llm")


def llm_usage(from_dt, to_dt, *, daily=False):
    """서빙 LLM 호출의 토큰 합계를 Langfuse 에서 읽는다(단계×모델별).

    반환: [{"date": "YYYY-MM-DD"|None, "name": 단계, "model": 모델명|None,
            "input": int, "output": int}, ...]
    관측이 꺼져 있거나 조회가 실패하면 **None** — 빈 리스트([])와 구분해야 호출부가
    '집계 원천 없음'과 '이 기간에 호출이 없음'을 다르게 말할 수 있다.

    ⚠️ daily=True 의 날짜 경계는 Langfuse 가 UTC 로 자른다(2026-08-26 실측: 08-25T20:00Z 가
    08-25 버킷). KST 로 다시 자르려면 hour 단위로 받아야 하는데 90일이면 row_limit(1000)을
    넘겨 요청을 쪼개야 한다 — 추이 그래프의 하루 경계가 9시간 밀리는 대가로 호출 1번을
    택했다. 화면의 '오늘' 값은 KST 자정~현재로 따로 물어(daily=False) 정확하게 낸다.
    """
    if not _AVAILABLE:
        return None
    query = {
        "view": "observations",
        "dimensions": [{"field": "name"}, {"field": "providedModelName"}],
        "metrics": [{"measure": "inputTokens", "aggregation": "sum"},
                    {"measure": "outputTokens", "aggregation": "sum"}],
        "filters": [{"column": "name", "operator": "any of",
                     "value": list(SERVING_GENERATION_NAMES), "type": "stringOptions"}],
        "fromTimestamp": from_dt.isoformat(),
        "toTimestamp": to_dt.isoformat(),
        "config": {"row_limit": 1000},
    }
    if daily:
        query["timeDimension"] = {"granularity": "day"}
    try:
        import json as _json
        rows = get_client().api.metrics.metrics(query=_json.dumps(query)).data
    except Exception:
        return None
    return [{"date": r.get("time_dimension"), "name": r.get("name"),
             "model": r.get("providedModelName"),
             "input": int(r.get("sum_inputTokens") or 0),
             "output": int(r.get("sum_outputTokens") or 0)}
            for r in rows]


def flush():
    """버퍼에 남은 trace를 즉시 전송. 서버(FastAPI)는 백그라운드 배치라 부를 필요
    없고, 프로세스가 곧 끝나는 CLI·평가 스크립트가 종료 직전에 부른다(유실 방지)."""
    if not _AVAILABLE:
        return
    try:
        get_client().flush()
    except Exception:
        pass
