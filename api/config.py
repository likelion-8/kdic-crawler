"""API 계층 환경설정 — .env 와 환경변수를 한 곳에서 읽어 타입이 붙은 객체로 만든다.

src/ 쪽 모듈들(db.py, llm_client.py 등)은 각자 load_dotenv() 후 os.environ 을 직접
읽는다. 그 방식을 바꾸지 않는다 — 여기서 관리하는 건 "API 계층에만 필요한 설정"
(CORS, 타임아웃, 요청 제한, 워밍업 여부)이다. DATABASE_URL 처럼 src/ 와 공유하는 값은
src/db.py 가 계속 주인이고, 여기서는 존재 여부 확인 용도로만 참조한다.

pydantic-settings 를 쓰는 이유: 환경변수는 전부 문자열이라 os.environ 을 직접 쓰면
int 변환·기본값·오타 처리를 부를 때마다 반복하게 된다. BaseSettings 는 그걸 클래스
정의 한 번으로 끝내고, 값이 잘못되면 요청 중이 아니라 앱이 뜰 때 죽는다(늦게 터지는
것보다 낫다).
"""
from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


# LANGFUSE_BASE_URL 폴백(langfuse_host default_factory)이 os.environ 을 읽으므로, pydantic
# env_file 과 별개로 .env 를 먼저 올려 둔다(API_ 접두사가 아닌 키는 pydantic 이 안 읽는다).
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        env_prefix="API_",
        # .env 에는 CLOVA_STUDIO_API_KEY 등 src/ 전용 키가 함께 들어 있다.
        # extra="ignore" 가 없으면 모르는 키를 만나 앱이 뜨지 않는다.
        extra="ignore",
    )

    # --- 기본 정보 -------------------------------------------------------
    app_name: str = "KDIC RAG API"
    environment: str = "development"  # development | production
    debug: bool = False

    # --- CORS ------------------------------------------------------------
    # 콤마로 구분된 문자열로 받는다(API_CORS_ORIGINS=https://a.com,https://b.com).
    # list[str] 로 선언하면 pydantic-settings 가 환경변수를 JSON 으로 파싱하려 해서
    # '["https://a.com"]' 같은 JSON 을 넣어야 한다 — 사람이 .env 에 쓰기 불편하므로
    # str 로 받고 아래 cors_origins 프로퍼티에서 쪼갠다.
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    cors_allow_credentials: bool = True

    # --- 타임아웃(초) -----------------------------------------------------
    # ⚠️ 아래 두 값은 선언만 돼 있고 지금 아무도 읽지 않는다. 값을 바꿔도 동작이 안 바뀌므로
    #    타임아웃을 조정하려면 실제 상수를 고쳐야 한다(api/rag/sse.py 의 TOKEN_TIMEOUT_S).
    #    계약상 자리를 남겨 둔 것이라 지우지 않았다.
    #
    # RAG 한 번은 LLM 을 여러 번 부른다(쿼리 플래너 1회 + 하위질문마다 답변 생성 1회
    # + [NO_SOURCE] 인 경우 출처 재확인 1회). 복합 질문이면 30초를 넘길 수 있어 넉넉히 잡는다.
    # 지금 실제로 걸리는 것은 sse.py 의 '토큰 간' 30초 타임아웃이고, 요청 전체를 자르는
    # 상한은 없다.
    rag_timeout_s: float = 120.0
    # SSE 연결 유지용 ping 간격 — 미구현이다. 붙일 때 주의: 주석형 하트비트(`: ping`)로는
    # 프론트의 30초 무응답 타이머가 갱신되지 않는다(파서가 data: 있는 프레임만 이벤트로 친다.
    # docs/backend-structure.md §3 함정 3). data 를 실은 프레임이어야 한다.
    sse_ping_interval_s: float = 15.0

    # --- 요청 제한 --------------------------------------------------------
    # 프로세스 메모리 기반이라 워커를 여러 개 띄우면 워커 수만큼 실질 한도가 늘어난다.
    # 남용 방어용 최소 안전장치이지 정확한 쿼터가 아니다 — 정확한 제한이 필요해지면
    # Redis 기반으로 교체할 것.
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 30
    # 프록시/로드밸런서 뒤에 배포할 때만 True. 직접 노출된 서버에서 켜면
    # X-Forwarded-For 를 위조해 요청 제한을 우회할 수 있다.
    trust_proxy_headers: bool = False

    # --- RAG --------------------------------------------------------------
    # 첫 질문에서 BM25 색인·임베딩 모델·분류기를 조립하느라 수십 초가 걸린다
    # (src/retrieval.py 의 _build_engines). 앱 부팅 때 미리 돌려 첫 사용자가
    # 그 비용을 물지 않게 한다. 개발 중 재시작이 잦으면 False 로 끄면 된다.
    warmup_on_startup: bool = True

    # --- 파이프라인 워커 ---------------------------------------------------
    # AD-004 가 만든 잡(재수집·재적재·변경 감지·평가 재측정)을 실제로 돌리는 주체.
    # 코드는 예전부터 src/worker.py 에 있었지만 손으로 띄우는 방법뿐이라, 아무도 안 띄우면
    # 잡이 QUEUED 에 영원히 남았다(2026-08-25 QA). API 프로세스가 스레드 하나로 함께
    # 돌려 기본값만으로 '만들면 돈다'가 되게 한다.
    #
    # ⚠️ 잡은 무겁다(재크롤·임베딩 수 분). 워커를 따로 프로세스로 띄워 분리하고 싶으면
    #    API_WORKER_IN_PROCESS=false 로 끄고 `python src/worker.py` 를 상주시킨다.
    #    claim_next 가 FOR UPDATE SKIP LOCKED 라 둘을 같이 켜도 잡이 중복 실행되지는 않는다.
    worker_in_process: bool = True

    # --- 관측(Langfuse) ---------------------------------------------------
    # rag_runs.trace_id 로 완성 URL 을 만들어 대화 로그 상세에 링크로 내보낸다(AD-005 G5).
    # 프론트가 Langfuse 호스트를 알 이유가 없어 서버가 URL 을 완성한다 — 조각으로 주면 배포
    # 환경이 바뀔 때마다 프론트를 고쳐야 한다. 비어 있으면(기본) trace_id 는 있어도 url=null 로
    # 내보내고, 화면은 링크 없이 id 만 글로 보여준다. 예: API_LANGFUSE_HOST=https://cloud.langfuse.com
    # API_LANGFUSE_HOST 가 없으면 SDK 가 쓰는 LANGFUSE_BASE_URL 로 폴백한다 — 같은 호스트를
    # 두 키에 중복 관리하다 한쪽만 바뀌는 사고 방지(2026-08-14 Langfuse 실연결하며 정리).
    langfuse_host: str = Field(
        default_factory=lambda: os.environ.get("LANGFUSE_BASE_URL", ""))

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """설정 싱글턴. lru_cache 라서 .env 를 매번 다시 읽지 않는다.

    FastAPI 라우터에서는 직접 부르지 말고 api/deps.py 의 SettingsDep 를 쓴다 —
    테스트에서 dependency_overrides 로 갈아끼울 수 있어야 하기 때문이다.
    """
    return Settings()
