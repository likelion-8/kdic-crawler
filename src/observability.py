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


def flush():
    """버퍼에 남은 trace를 즉시 전송. 서버(Streamlit·FastAPI)는 백그라운드 배치라 부를 필요
    없고, 프로세스가 곧 끝나는 CLI·평가 스크립트가 종료 직전에 부른다(유실 방지)."""
    if not _AVAILABLE:
        return
    try:
        get_client().flush()
    except Exception:
        pass
