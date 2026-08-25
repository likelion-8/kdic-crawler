"""clarify — 페이로드 계약 검증. 되묻기 **판정**은 LLM(플래너/재작성기의
needs_clarification)이라 여기서 재지 않는다(실측은 평가 스크립트 몫 — test_query_rewriter
와 같은 원칙).

2026-08-21: 정규식 프리스크린(first_turn_candidate)이 사라져 그 테스트도 함께 지웠다.
판정이 이미 도는 구조화 출력 콜에 얹혔으므로 "LLM 을 부를지" 자체가 결정할 일이 아니다.
여기 남는 건 결정론 부분 — 페이로드 모양과 루프 방지 계약이다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from clarify import CLARIFY_OPTIONS, clarification_payload  # noqa: E402


def test_payload_matches_schema_contract():
    p = clarification_payload()
    assert p["question"] and p["options"], "options 가 비면 프론트에 버튼이 안 그려진다(계약)"
    assert all(o["label"] for o in p["options"])


def test_option_labels_name_a_business():
    """클릭된 label 이 다음 턴 메시지가 된다 — label 만 보고 업무를 알 수 없으면
    판정기가 다시 '업무 미정'으로 보아 되묻기가 무한 반복된다."""
    businesses = ("착오송금", "예금보험금", "미수령금", "은닉재산", "채무조정", "예금자보호")
    for o in CLARIFY_OPTIONS:
        assert any(b in o["label"] for b in businesses), o["label"]


def test_payload_returns_fresh_copies():
    """호출부가 페이로드를 변형해도 원본 상수가 오염되지 않는다."""
    p = clarification_payload()
    p["options"][0]["label"] = "오염"
    assert CLARIFY_OPTIONS[0]["label"] != "오염"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
