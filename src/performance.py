"""단계별 실행 시간 측정용 공통 타이머. pipeline.py의 _rag_answer_traced()가 각 단계를
이 컨텍스트매니저로 감싸 timings 딕셔너리에 초 단위로 기록한다.

time()이 아니라 perf_counter()를 쓴다 — 짧은 구간(수 ms)도 시스템 시각 변경(NTP 보정 등)
영향 없이 단조 증가하는 값으로 정확히 잴 수 있다.
"""
from contextlib import contextmanager
from time import perf_counter


@contextmanager
def measure_time(timings, name):
    started_at = perf_counter()
    try:
        yield
    finally:
        timings[name] = round(perf_counter() - started_at, 4)
