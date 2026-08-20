"""finalize_sub 의 재생성 구제 대칭성 — 나쁜 판정 한 롤로 정답 후보를 버리지 않는다.

2026-08-14 실측(같은 질문 5연속, rag_runs.observation): 검색은 5회 동일했는데 4회는
거절→재생성 구제로 정상 답변, 1회는 used_source=false + ungrounded_claims 경로로 빠져
재시도 없이 범위외로 교체됐다 — 동일 질문에 답변이 뒤집힌 원인. 이 테스트는 그 비대칭이
되돌아오지 않게 지킨다. LLM·DB 없이 validate_answer / _regenerate_once 를 대역으로 바꾼다.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "api", ROOT / "src"):
    sys.path.insert(0, str(p))

from api.rag import answer as answer_mod  # noqa: E402
from api.rag.answer import OUT_OF_SCOPE_MESSAGE, SubPlan, finalize_sub  # noqa: E402

TOP = [("faq_msdr_apply#1", 0.6765, "본문")]   # 실측 사례와 같은 '근거는 강함' 상황


def _sp(top=None):
    return SubPlan(question="반환지원 대상이 아닌 경우는?", intent="informational",
                   top=TOP if top is None else top, prompt=[("user", "질문: ...")],
                   evidence="근거 텍스트")


def _verdict(used_source, kind, appropriate):
    return SimpleNamespace(used_source=used_source, kind=kind, appropriate=appropriate)


@pytest.fixture
def wire(monkeypatch):
    """검증·재생성·출처 조립을 대역으로. calls 로 재생성 시도 여부를 관찰한다."""
    state = {"verdict": None, "regen": ("재생성 본문", False), "calls": 0}
    monkeypatch.setattr(answer_mod, "get_param", lambda _k, _d: True)
    monkeypatch.setattr(answer_mod, "validate_answer", lambda *_a: state["verdict"])

    def fake_regen(_sp):
        state["calls"] += 1
        return state["regen"]

    monkeypatch.setattr(answer_mod, "_regenerate_once", fake_regen)
    monkeypatch.setattr(answer_mod, "_build_sources", lambda top: [])
    return state


def test_ungrounded_verdict_gets_one_rescue_attempt(wire):
    """실측에서 뒤집혔던 바로 그 경로 — 마커는 근거사용인데 검증이 근거이탈 판정.
    재생성이 판정을 통과하면 정답이 산다(종전에는 시도조차 없이 범위외로 교체)."""
    wire["verdict"] = _verdict(used_source=False, kind="ungrounded_claims", appropriate=False)
    wire["regen"] = ("구제된 정답", True)

    sub, used = finalize_sub(_sp(), "원래 본문", marker_used_source=True)

    assert wire["calls"] == 1
    assert used is True
    assert sub.answer == "구제된 정답"


def test_two_consecutive_bad_verdicts_confirm_out_of_scope(wire):
    """재생성본도 판정을 통과하지 못하면 그때 확정한다 — 2연속 실패 확정 철학."""
    wire["verdict"] = _verdict(used_source=False, kind="ungrounded_claims", appropriate=False)
    wire["regen"] = ("여전히 나쁜 본문", False)

    sub, used = finalize_sub(_sp(), "원래 본문", marker_used_source=True)

    assert wire["calls"] == 1
    assert used is False
    assert sub.answer == OUT_OF_SCOPE_MESSAGE


def test_no_evidence_means_no_rescue(wire):
    """근거가 게이트로 비었으면 재생성할 재료가 없다 — 곧장 범위외 처리(억지 답변 방지)."""
    wire["verdict"] = _verdict(used_source=False, kind="ungrounded_claims", appropriate=False)

    sub, used = finalize_sub(_sp(top=[]), "원래 본문", marker_used_source=True)

    assert wire["calls"] == 0
    assert sub.answer == OUT_OF_SCOPE_MESSAGE


def test_failed_refusal_rescue_keeps_the_refusal_text(wire):
    """거절 구제 실패는 범위외 문구가 아니라 원래 거절문 유지 — 정당한 거절이 더 정보가 많다."""
    wire["verdict"] = _verdict(used_source=False, kind="refusal", appropriate=True)
    wire["regen"] = ("여전히 거절", False)

    sub, used = finalize_sub(_sp(), "원래 거절문", marker_used_source=False)

    assert wire["calls"] == 1
    assert used is False
    assert sub.answer == "원래 거절문"


def test_grounded_and_appropriate_touches_nothing(wire):
    """정상 판정이면 재생성을 부르지 않는다 — 콜 수가 늘면 지연·비용이 배가 된다."""
    wire["verdict"] = _verdict(used_source=True, kind="grounded", appropriate=True)

    sub, used = finalize_sub(_sp(), "정상 답변", marker_used_source=True)

    assert wire["calls"] == 0
    assert used is True
    assert sub.answer == "정상 답변"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ─────────────── 마커 없는 응답의 관측 (2026-08-20) ───────────────
#
# PR #174 가 마커 지시를 프롬프트에서 뺐다. 그런데 파싱이 "마커 없음"을 True 로 돌려주는
# 바람에 관측에 있지도 않은 마커가 박혔고, AD-005 상세가 `마커 [[SOURCE_USED]]` 를
# 그렸다 — 심지어 출처 판정이 '미사용'인 줄에서. 모르는 것을 기본값으로 적지 않는다.

def test_absent_marker_is_recorded_as_unknown(wire):
    """마커가 없으면 관측에 None 이 남아야 한다 — True 로 적으면 화면이 없는 값을 그린다."""
    wire["verdict"] = _verdict(used_source=True, kind="grounded", appropriate=True)
    sp = _sp()
    finalize_sub(sp, "본문", marker_used_source=None)
    assert sp.obs_marker is None, "마커가 없었는데 관측에 값이 박혔다"


def test_present_marker_is_recorded_as_is(wire):
    """옛 게시본(AD-008)이 마커를 요구하면 그 값은 그대로 남는다 — 하위호환."""
    wire["verdict"] = _verdict(used_source=True, kind="grounded", appropriate=True)
    for marker in (True, False):
        sp = _sp()
        finalize_sub(sp, "본문", marker_used_source=marker)
        assert sp.obs_marker is marker


def test_absent_marker_does_not_poison_the_precheck_shadow(wire):
    """None 을 그대로 precheck 에 넘기면 falsy 라 전 건이 marker_no_source 로 세어진다.
    근거가 있으면 그 분기로 가지 않아야 섀도 통계가 살아난다."""
    wire["verdict"] = _verdict(used_source=True, kind="grounded", appropriate=True)
    sp = _sp()
    finalize_sub(sp, "본문에 숫자 없음", marker_used_source=None)
    assert sp.obs_precheck != "marker_no_source"
