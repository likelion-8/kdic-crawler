"""AD-001 단계별 평균 응답시간 — rag_runs.observation.timings 를 화면 계약으로 옮기는 계산.

지키려는 것은 '재지 않은 것을 0ms 로 그리지 않는다'는 규칙이다. 종전 구현은 8개 단계를
전부 avg_ms=0 으로 내보내 화면이 "모든 단계가 즉시 끝난다"고 말했다. 값이 없으면 막대를
그리지 않아야 StageBars 가 '측정된 단계 기록이 없습니다'로 떨어진다(Charts.tsx).

DB 는 부르지 않는다 — build_stage_latency 는 순수 함수다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "api", ROOT / "src"):
    sys.path.insert(0, str(p))

from api.routers.admin_dashboard import LATENCY_STAGE_NAMES, build_stage_latency  # noqa: E402


def test_stage_labels_follow_the_web_request_order():
    """CLI 파이프라인(src/pipeline.py)의 8구간이 아니라 웹 경로(api/rag/sse.py)가 도는 순서다."""
    assert LATENCY_STAGE_NAMES == (
        ("rewrite", "질문 정리"), ("gate", "게이트"), ("cache", "캐시 조회"),
        ("plan", "질의 계획"), ("retrieval", "검색"), ("generation", "답변 생성"),
        ("validation", "출처 판정"),
    )


def test_seconds_become_milliseconds_in_execution_order():
    out = build_stage_latency({"generation": 3.2499, "retrieval": 0.9195, "rewrite": 2.0484},
                              avg_total_ms=10267)
    assert out == {
        "avg_total_ms": 10267,
        "stages": [{"name": "질문 정리", "avg_ms": 2048},
                   {"name": "검색", "avg_ms": 920},
                   {"name": "답변 생성", "avg_ms": 3250}],
    }


def test_stages_with_no_measurement_are_absent_not_zero():
    """0 으로 채우면 '즉시 끝났다'로 읽힌다. 안 잰 단계는 막대 자체가 없어야 한다."""
    out = build_stage_latency({"gate": 0.0004}, avg_total_ms=310)
    assert [s["name"] for s in out["stages"]] == ["게이트"]


def test_no_records_yields_an_empty_chart_instead_of_eight_zero_bars():
    out = build_stage_latency({}, avg_total_ms=0)
    assert out == {"avg_total_ms": 0, "stages": []}


def test_unknown_keys_are_dropped():
    """계측 키를 늘렸는데 라벨을 안 붙였으면 화면에 영문 키가 새는 것보다 빠지는 게 낫다."""
    out = build_stage_latency({"retrieval": 0.5, "reranking": 9.9}, avg_total_ms=1000)
    assert [s["name"] for s in out["stages"]] == ["검색"]
