"""RAG 워밍업 & 스레드 실행 헬퍼.

무거운 리소스(임베딩 모델·검색 엔진·질문 분류기)를 서버 시작 시 딱 한 번 로드해서 매
요청마다 재로딩하지 않게 하고, 동기(blocking) 파이프라인 함수를 FastAPI 이벤트 루프를
막지 않고 스레드풀에서 돌리는 헬퍼를 제공한다.

무거운 조립 자체는 src/retrieval.py 의 _build_engines() 가 이미 싱글턴으로 갖고 있다
(BM25 색인·임베딩 모델·RoutedRetriever+질문유형 분류기를 한 번에 조립하고 캐시). 여기서는
그걸 부팅 시점에 '미리' 부르고, 완료 여부를 상태값으로 노출할 뿐이다. src/ 코드는 건드리지
않는다 — flat import(`from retrieval import ...`)는 api/__init__.py 가 sys.path 에 src/ 를
넣어줘서 가능하다.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

# 워밍업 완료 여부. /api/health(readiness)가 이 값으로 chat 가용성을 판단한다.
# 단일 프로세스 기준 플래그다 — 워커를 여러 개 띄우면 워커마다 각자 워밍업한다.
_warmed_up = False


def is_warmed_up() -> bool:
    """무거운 리소스 로딩이 끝났는지. 외부(특히 /api/health)에서 조회한다."""
    return _warmed_up


def _warmup_sync() -> None:
    """블로킹 초기화 본체 — 별도 스레드에서 호출된다.

    _build_engines() 하나가 임베딩 모델 로드·검색엔진 조립·질문유형 분류기(Supabase
    evaluation_dataset 참조)까지 전부 처리한다. intent 분류(query_classifier.classify_intent)는
    OpenAI 호출이라 무거운 사전 로딩이 없어 워밍업 대상이 아니다.
    """
    from retrieval import _build_engines
    _build_engines()


async def warmup() -> None:
    """앱 시작(api/main.py 의 lifespan)에서 한 번 호출한다.

    블로킹 초기화를 스레드에서 돌려 시작 지연을 이벤트 루프 밖으로 뺀다(부팅 중이라
    트래픽은 없지만, 다른 시작 코루틴을 막지 않기 위함). 완료되면 is_warmed_up()==True.
    두 번 불려도 안전하다(이미 됐으면 즉시 반환).
    """
    global _warmed_up
    if _warmed_up:
        return
    logger.info("RAG 워밍업 시작 — 임베딩 모델·검색엔진·질문분류기 로드")
    await asyncio.to_thread(_warmup_sync)
    _warmed_up = True
    logger.info("RAG 워밍업 완료")


async def run_in_thread(func, *args, **kwargs):
    """동기(blocking) 파이프라인 함수를 이벤트 루프를 막지 않고 스레드에서 실행한다.

    ⚠️ 현재 아무도 부르지 않는다. 챗 경로는 async 라우터가 아니라 '평범한 def' 라우터 +
    StreamingResponse 조합(routers/chat.py)이라, FastAPI 가 알아서 스레드풀로 돌려 이 헬퍼가
    필요 없다. async 라우터에서 블로킹 함수를 부를 일이 생기면 그때 쓰라고 남겨 둔 것이다.

    RAG 경로(검색·LLM 호출)는 전부 동기 블로킹 코드라, async 라우터에서 그대로 부르면
    이벤트 루프가 멈춰 다른 요청까지 막힌다. 그때 이 헬퍼로 감싸 스레드풀에 넘긴다.
        예)  result = await run_in_thread(some_blocking_fn, arg)
    """
    return await asyncio.to_thread(func, *args, **kwargs)
