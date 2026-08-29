"""AD-001 리소스 모니터링 — Langfuse 집계를 화면 계약으로 옮기는 계산.

지키려는 것은 '요금표에 없는 모델을 0원처럼 보이게 하지 않는다'는 규칙이다. 표에 없는
모델이 토큰을 가장 많이 쓰는 단계일 수 있고(HCX 가 실제로 그렇다), 그걸 0 으로 채우면
화면이 "답변 생성은 공짜"라고 말하게 된다.
Langfuse·DB 는 부르지 않는다 — build_resource_payload 는 순수 함수다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "api", ROOT / "src"):
    sys.path.insert(0, str(p))

from api.routers.admin_dashboard import (  # noqa: E402
    KRW_TO_USD, MODEL_PRICE_USD_PER_1M, build_resource_payload)

DAYS = ["2026-08-25", "2026-08-26"]

# 요금표에 없는 모델. Langfuse 에 실제로 찍혀 있으나(팀원이 한 번 써 본 흔적) 우리가 쓰는
# 모델이 아니라 표에 안 넣었다 — '표에 없으면 어떻게 되나'를 재는 데 딱 맞는 표본이다.
UNPRICED = "HCX-DASH-007"


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
    rows = [_row("hcx_stream", UNPRICED, 10_000, 500)]
    out = build_resource_payload(2, rows, rows, DAYS)

    assert out["tokens"][-1] == {"date": "2026-08-26", "input": 10_000, "output": 500}
    assert out["cost"][-1]["usd"] == 0            # 비용은 못 매긴다
    assert out["today"]["cost_text"] == "단가 미등록"   # "$0.0000" 이 아니다
    only = out["cost_breakdown"][0]
    assert only["share"] is None
    assert "단가 미등록" in only["amount_text"] and "토큰" in only["amount_text"]
    assert f"{UNPRICED} 단가 미등록" in out["cost_caption"]


def test_share_is_computed_over_priced_stages_only():
    rows = [_row("hcx_stream", UNPRICED, 5_000_000, 100_000),
            _row("plan_query_llm", "gpt-5.6-luna", 1_000_000, 0),      # $0.20
            _row("validate_answer_llm", "gpt-5.6-luna", 3_000_000, 0)]  # $0.60
    out = build_resource_payload(2, rows, rows, DAYS)
    shares = {b["label"]: b["share"] for b in out["cost_breakdown"]}
    assert shares["질문 분해·의도 판단"] == 25 and shares["출처 판정"] == 75
    # 비용 큰 순이라 금액을 못 매긴 단계는 맨 뒤다 — 토큰을 제일 많이 써도 그렇다.
    # 대신 목록에서 사라지지는 않는다(사라지면 '안 썼다'로 읽힌다).
    assert out["cost_breakdown"][0]["label"] == "출처 판정"
    assert out["cost_breakdown"][-1]["label"] == "답변 생성 (HyperCLOVA X)"
    assert out["cost_breakdown"][-1]["share"] is None


def test_empty_range_says_so_instead_of_showing_zero_cost():
    out = build_resource_payload(2, [], [], DAYS)
    assert out["cost_caption"] == "최근 2일 · 기록된 LLM 호출 없음"
    assert out["today"]["tokens_text"] == "호출 없음"
    assert [p["usd"] for p in out["cost"]] == [0, 0]   # 축은 유지(빈 그래프가 아니라 0선)


def test_hcx_price_matches_the_published_krw_table():
    """공시가는 원화다(ncloud 요금표, 한국 리전·기본·실시간, 1,000 토큰 기준):
    HCX-007 입력 1.25원 · 출력 5원. USD 표는 NCP 가 같은 페이지에 적어 둔 당월 환율로 옮긴
    값이어야 한다 — 우리가 임의 환율을 쓰면 청구서와 대시보드가 갈린다."""
    win, wout = 1.25, 5.0                       # 원 / 1,000 토큰
    usd_in, usd_out = MODEL_PRICE_USD_PER_1M["HCX-007"]
    assert usd_in == pytest.approx(win * 1_000 * KRW_TO_USD)
    assert usd_out == pytest.approx(wout * 1_000 * KRW_TO_USD)
    # NCP 가 같은 표에서 USD 로도 보여주는 값(반올림 4자리)과 맞는지 — 옮기다 자릿수가
    # 틀리면 여기서 걸린다. USD 0.0009 / 0.0035 per 1,000 토큰.
    assert round(usd_in / 1_000, 4) == 0.0009
    assert round(usd_out / 1_000, 4) == 0.0035


def test_answer_generation_now_has_a_price_so_it_shows_money_not_tokens():
    """HCX 단가가 채워졌으므로 '답변 생성' 도 금액·비중을 갖는다(2026-08-26 이전엔 미등록)."""
    rows = [_row("hcx_stream", "HCX-007", 1_000_000, 1_000_000)]
    out = build_resource_payload(2, rows, rows, DAYS)
    assert out["cost_breakdown"][0]["share"] == 100
    assert out["today"]["cost_text"] == "$4.34"      # $0.867375 + $3.4695 = $4.336875
    assert "단가 미등록" not in out["cost_caption"]


def test_every_serving_generation_name_has_a_screen_label():
    """집계 목록과 화면 라벨이 함께 움직이는지 고정한다.

    비용 집계는 span **이름**으로 거른다. 그래서 서빙에 새 LLM 호출을 붙일 때 이름을 한쪽에만
    더하면 조용히 누락된다 — 2026-08-14 에 재생성이 call_hyperclova 를 부르기 시작한 뒤로
    그 몫이 대시보드에서 통째로 빠져 있었고(실측 08-25~08-28: HCX 생성 콜 583건 중 131건),
    아무 테스트도 깨지지 않아 08-29 까지 드러나지 않았다. 이 테스트가 그 침묵을 막는다."""
    from observability import SERVING_GENERATION_NAMES
    from api.routers.admin_dashboard import STAGE_LABELS

    assert set(SERVING_GENERATION_NAMES) == set(STAGE_LABELS), (
        "집계 목록과 화면 라벨이 어긋났다 — 한쪽에만 더하면 그 단계의 비용이 조용히 사라진다")


def test_regeneration_is_wired_to_the_counted_entry_point():
    """재생성은 call_hyperclova 가 아니라 별도 진입점으로 나가야 집계에 잡힌다.

    call_hyperclova 는 평가·CLI 도 쓰는 이름이라 서빙 목록에 넣을 수 없다. 그래서 재생성만
    hcx_regenerate 로 계측한다 — 호출부가 되돌아가거나 목록에서 이름이 빠지면 비용 누락이
    그대로 재발한다."""
    import llm_client
    from observability import SERVING_GENERATION_NAMES
    from api.rag import answer

    assert answer.regenerate_hyperclova is llm_client.regenerate_hyperclova, (
        "재생성 경로가 전용 진입점을 안 쓴다")
    assert "hcx_regenerate" in SERVING_GENERATION_NAMES, (
        "hcx_regenerate 가 서빙 집계 목록에 없다 — 재생성 비용이 집계에서 빠진다")
