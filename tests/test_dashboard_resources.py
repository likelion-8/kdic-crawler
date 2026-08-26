"""AD-001 리소스 모니터링 — Langfuse 집계를 화면 계약으로 옮기는 계산.

지키려는 것은 '단가 없는 모델을 0원처럼 보이게 하지 않는다'는 규칙이다. HCX 는 단가가 아직
없는데 토큰은 가장 많이 쓰는 단계라, 0 으로 채우면 화면이 "답변 생성은 공짜"라고 말하게 된다.
Langfuse·DB 는 부르지 않는다 — build_resource_payload 는 순수 함수다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "api", ROOT / "src"):
    sys.path.insert(0, str(p))

from api.routers.admin_dashboard import (  # noqa: E402
    MODEL_PRICE_USD_PER_1M, build_resource_payload)

DAYS = ["2026-08-25", "2026-08-26"]


def _row(name, model, i, o, date="2026-08-26"):
    return {"date": date, "name": name, "model": model, "input": i, "output": o}


def test_priced_model_cost_is_tokens_times_unit_price():
    # gpt-5.6-luna = $0.20/1M 입력 · $1.20/1M 출력 → 1,000,000 in + 1,000,000 out = $1.40
    rows = [_row("plan_query_llm", "gpt-5.6-luna", 1_000_000, 1_000_000)]
    out = build_resource_payload(2, rows, rows, DAYS)
    assert out["cost"][-1]["usd"] == 1.4
    assert out["today"]["cost_text"] == "$1.40"


def test_unpriced_model_is_excluded_from_cost_but_keeps_its_tokens():
    """0 원으로 채우지 않는다 — 토큰은 보여주고 비중은 비운다."""
    rows = [_row("hcx_stream", "HCX-007", 10_000, 500)]
    out = build_resource_payload(2, rows, rows, DAYS)

    assert out["tokens"][-1] == {"date": "2026-08-26", "input": 10_000, "output": 500}
    assert out["cost"][-1]["usd"] == 0            # 비용은 못 매긴다
    assert out["today"]["cost_text"] == "단가 미등록"   # "$0.0000" 이 아니다
    only = out["cost_breakdown"][0]
    assert only["share"] is None
    assert "단가 미등록" in only["amount_text"] and "토큰" in only["amount_text"]
    assert "HCX-007 단가 미등록" in out["cost_caption"]


def test_share_is_computed_over_priced_stages_only():
    rows = [_row("hcx_stream", "HCX-007", 5_000_000, 100_000),
            _row("plan_query_llm", "gpt-5.6-luna", 1_000_000, 0),      # $0.20
            _row("validate_answer_llm", "gpt-5.6-luna", 3_000_000, 0)]  # $0.60
    out = build_resource_payload(2, rows, rows, DAYS)
    shares = {b["label"]: b["share"] for b in out["cost_breakdown"]}
    assert shares["질문 분해·의도 판단"] == 25 and shares["출처 판정"] == 75
    # 토큰이 가장 많은 단계가 맨 위 — 비용이 아니라 토큰으로 정렬한다(단가 미등록이 섞이므로)
    assert out["cost_breakdown"][0]["label"] == "답변 생성 (HyperCLOVA X)"


def test_empty_range_says_so_instead_of_showing_zero_cost():
    out = build_resource_payload(2, [], [], DAYS)
    assert out["cost_caption"] == "최근 2일 · 기록된 LLM 호출 없음"
    assert out["today"]["tokens_text"] == "호출 없음"
    assert [p["usd"] for p in out["cost"]] == [0, 0]   # 축은 유지(빈 그래프가 아니라 0선)


def test_hcx_price_slot_exists_so_filling_it_is_a_one_line_change():
    """단가가 채워지면 이 테스트가 깨진다 — 그때 위 미등록 테스트들도 같이 손보라는 신호."""
    assert MODEL_PRICE_USD_PER_1M["HCX-007"] is None
