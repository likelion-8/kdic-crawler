"""clarify — 프리스크린·페이로드 계약 검증. 되묻기 **판정**은 LLM(query_rewriter 의
needs_clarification)이라 여기서 재지 않는다(실측은 평가 스크립트 몫 — test_query_rewriter
와 같은 원칙). 여기서 고정하는 건 결정론 부분이다:

- 프리스크린은 '후보 거르기'다 — 업무 낱말이 보이면 LLM 도 부르지 않는다(첫 턴 0콜 유지).
- 버튼 label 은 클릭 시 그대로 다음 메시지가 되므로, label 자체가 다시 프리스크린 후보가
  되면 되묻기 루프가 생긴다 — label 은 반드시 업무 특정 낱말을 포함해야 한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from clarify import (  # noqa: E402
    CLARIFY_OPTIONS,
    clarification_payload,
    first_turn_candidate,
)


# ── 프리스크린: LLM 판정 후보가 되는 것 ─────────────────────────────────────────

def test_topicless_apply_questions_are_candidates():
    # 1차 시도(키워드 즉시 발동)와 달리 이제 '후보'일 뿐이다 — 최종 판정은 LLM.
    for q in ("신청 링크 알려줘", "접수는 어디서 해요?", "필요한 서류가 뭐예요?",
              "내가 신청한 결과 언제 받을 수 있어?"):
        assert first_turn_candidate(q), q


# ── 프리스크린: LLM 을 부르지 않는 것 (첫 턴 0콜 약속) ──────────────────────────

def test_topic_present_skips_llm():
    for q in ("착오송금 반환지원 신청 링크 알려줘", "예금보험금 신청은 어디서 하나요?",
              "미수령금 찾기 절차 알려줘", "은닉재산 신고 서류가 뭐예요?",
              "채무조정 신청 자격이 궁금해요", "예금자보호 한도가 얼마예요?"):
        assert not first_turn_candidate(q), q


def test_no_intent_hint_skips_llm():
    for q in ("안녕하세요", "너는 누구야?", "예금보험공사는 뭐 하는 곳이야?"):
        assert not first_turn_candidate(q), q


# ── 페이로드·루프 방지 계약 ────────────────────────────────────────────────────

def test_payload_matches_schema_contract():
    p = clarification_payload()
    assert p["question"] and p["options"], "options 가 비면 프론트에 버튼이 안 그려진다(계약)"
    assert all(o["label"] for o in p["options"])


def test_option_labels_never_loop_back_into_prescreen():
    """클릭된 label 이 다음 턴 메시지가 된다 — label 이 다시 후보가 되면 무한 되묻기."""
    for o in CLARIFY_OPTIONS:
        assert not first_turn_candidate(o["label"]), o["label"]


def test_payload_returns_fresh_copies():
    """호출부가 페이로드를 변형해도 원본 상수가 오염되지 않는다."""
    p = clarification_payload()
    p["options"][0]["label"] = "오염"
    assert CLARIFY_OPTIONS[0]["label"] != "오염"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-q"]))
