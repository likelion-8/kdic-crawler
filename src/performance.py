"""단계별 실행 시간 측정용 공통 타이머. pipeline.py의 _rag_answer_traced()가 각 단계를
이 컨텍스트매니저로 감싸 timings 딕셔너리에 초 단위로 기록한다.

time()이 아니라 perf_counter()를 쓴다 — 짧은 구간(수 ms)도 시스템 시각 변경(NTP 보정 등)
영향 없이 단조 증가하는 값으로 정확히 잴 수 있다.
"""
from contextlib import contextmanager
from time import perf_counter


@contextmanager
def measure_time(timings, name, accumulate=False):
    """accumulate=True면 같은 name의 기존 값에 더한다 — 복합 질문에서 하위 질문마다
    검색·LLM호출 등 같은 단계를 여러 번 도는데, pipeline.py의 timings 키 구조(예:
    "retrieval", "llm_call")를 단일 질문 때와 동일하게 유지해 성능 측정 스크립트가
    복합/단일 질문을 구분할 필요 없이 그대로 쓸 수 있게 하기 위함."""
    started_at = perf_counter()
    try:
        yield
    finally:
        elapsed = perf_counter() - started_at
        timings[name] = round(timings.get(name, 0) + elapsed, 4) if accumulate else round(elapsed, 4)
