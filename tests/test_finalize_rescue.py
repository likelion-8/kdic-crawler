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


def test_legitimate_refusal_is_not_regenerated(wire):
    """판정기가 정상 응대라고 본 거절문은 다시 쓰지 않고 그대로 둔다.

    2026-08-29 이전에는 이 조합(kind=refusal · 근거 미사용 · appropriate=true)도 재생성을
    한 번 돌렸다. rag_runs 실측(08-25~08-28)에서 36건 시도에 구제 0건이라 조건에서 뺐다 —
    답변은 종전과 같고(원래 거절문 유지) HCX·검증 콜 두 번만 사라진다."""
    wire["verdict"] = _verdict(used_source=False, kind="refusal", appropriate=True)
    wire["regen"] = ("여전히 거절", False)

    sub, used = finalize_sub(_sp(), "원래 거절문", marker_used_source=False)

    assert wire["calls"] == 0, "정상 거절인데 재생성을 불렀다"
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


def test_url_is_stripped_from_the_final_body(wire):
    """원칙 5(URL 쓰지 말 것)의 백스톱이 웹 경로에도 걸리는지 — 지시만으로는 실측 4.0%가 샜고,
    코퍼스에 없는 주소(https://www.kdic.or.kr/protect/apply.do)가 7회 사용자에게 나갔다.

    판정은 생성 원문을 보고(검증 입력 불변), 사용자가 받는 done.answer 에만 URL 이 없어야 한다."""
    wire["verdict"] = _verdict(used_source=True, kind="grounded", appropriate=True)
    seen = []
    original = "신청은 https://www.kdic.or.kr/protect/apply.do 에서 하시면 됩니다. 문의 1588-0037."

    def spy(_q, body, _e):
        seen.append(body)
        return wire["verdict"]

    import api.rag.answer as m
    m_validate = m.validate_answer
    try:
        m.validate_answer = spy
        sub, used = finalize_sub(_sp(), original, marker_used_source=None)
    finally:
        m.validate_answer = m_validate

    assert seen == [original], "검증이 URL 제거된 본문을 봤다 — 판정 입력은 생성 원문이어야 한다"
    assert "kdic.or.kr" not in sub.answer, "URL 이 그대로 사용자에게 나감"
    assert "1588-0037" in sub.answer, "전화번호까지 지워짐 — 연락처는 정답인 경우가 있다"
    assert used is True


def test_source_recheck_off_skips_validation(monkeypatch):
    """use_source_recheck Off — 검증 1콜을 아예 안 부르고 생성 본문을 그대로 쓴다(2026-08-26 확인).

    AD-007 의 이 토글이 실제로 답변 경로를 바꾸는지가 이 테스트의 대상이다. 켜짐 경로는 위
    테스트들이 이미 지키고 있어, 여기서는 '꺼지면 정말 안 부른다'만 본다 — Off 인데 여전히
    부르면 관리자가 끈 LLM 1콜이 매 답변마다 계속 나간다(비용·지연 그대로)."""
    calls = []
    monkeypatch.setattr(answer_mod, "get_param",
                        lambda k, d: False if k == "use_source_recheck" else d)
    monkeypatch.setattr(answer_mod, "validate_answer",
                        lambda *a: calls.append(a) or _verdict(True, "grounded", True))
    monkeypatch.setattr(answer_mod, "_build_sources", lambda top: [])

    sub, used = finalize_sub(_sp(), "생성된 본문", marker_used_source=None)

    assert calls == [], "Off 인데 검증 1콜이 나갔다"
    assert sub.answer == "생성된 본문", "검증을 안 했는데 본문이 바뀌었다"
    assert used is True, "근거가 있으면 Off 여도 출처를 붙인다(bool(sp.top) 안전망)"


CIVIL = {
    "procedure": "온라인 신청 사이트 접속 후 신청서를 작성합니다.",
    "documents": [],
    # civil_petition.OFFICIAL_APPLY_LINKS['착오송금 반환 신청'] 과 같은 모양
    "links": [{"title": "착오송금 반환지원 온라인 신청",
               "url": "https://fins.kdic.or.kr/ir/aplygudn/MtrsStutChc/selectScrn.do",
               "breadcrumb": "소개와 방법안내 > 상황선택"}],
}


def test_inappropriate_refusal_keeps_official_apply_link(wire):
    """민원 링크 요청에 LLM 이 거절해도 **시스템이 이미 조립한 공식 신청 링크는 살린다.**

    실측(request_id e47d14d0a21a481cbfa812ffe47bb2eb, 2026-08-27): '착오송금 반환지원 신청
    링크를 알려주세요' 에 HCX-DASH-002 가 거절문을 냈다. 검색·게이트는 정상이었고(top1
    0.755) OFFICIAL_APPLY_LINKS 에 정답 URL 이 상수로 있었는데, attachments 가 used 에
    묶여 있어(`used and sp.civil`) 그 링크까지 함께 버려졌다 — 사용자는 링크 하나 달라는
    질문에 범위외 안내를 받았다.

    링크는 LLM 이 만드는 값이 아니라 검색된 업무에서 결정론적으로 나온다. 그러므로 LLM 이
    무엇을 답했든, 근거가 있고 신청 진입점이 있으면 첨부는 사용자에게 가야 한다."""
    wire["verdict"] = _verdict(used_source=False, kind="refusal", appropriate=False)
    wire["regen"] = ("여전히 거절", False)
    sp = _sp()
    sp.intent, sp.civil = "civil_petition", CIVIL

    sub, used = finalize_sub(sp, "문의하신 내용은 …범위를 벗어난 질문이라…", marker_used_source=None)

    urls = [a.url for a in sub.attachments]
    assert "https://fins.kdic.or.kr/ir/aplygudn/MtrsStutChc/selectScrn.do" in urls, \
        "시스템이 들고 있던 공식 신청 링크가 버려졌다"
    assert sub.answer != OUT_OF_SCOPE_MESSAGE, \
        "링크를 붙이면서 본문은 '범위 밖'이라고 하면 서로 모순된다"
    assert used is True, \
        "used=false 면 out_of_scope 로 매겨져 프론트가 첨부 섹션을 접는다 — 링크가 화면에 안 나온다"


def test_inappropriate_refusal_without_links_stays_out_of_scope(wire):
    """신청 진입점이 없는 업무는 종전대로 범위외 처리 — 붙일 링크가 없으면 구제할 것도 없다."""
    wire["verdict"] = _verdict(used_source=False, kind="refusal", appropriate=False)
    wire["regen"] = ("여전히 거절", False)
    sp = _sp()
    sp.intent, sp.civil = "civil_petition", {"procedure": "…", "documents": [], "links": []}

    sub, used = finalize_sub(sp, "원래 본문", marker_used_source=None)

    assert sub.answer == OUT_OF_SCOPE_MESSAGE
    assert sub.attachments == []
    assert used is False


def test_legitimate_refusal_never_gets_the_apply_link(wire):
    """**정말 범위 밖인 질문**에는 링크를 붙이지 않는다 — 링크 구제의 안전 경계.

    민원 intent + 게이트 통과 + 업무 매핑이 되면 civil.links 는 채워진다. 그 자체로는 질문이
    범위 안이라는 뜻이 아니다(게이트 임계 0.35 는 오차단 0 을 목표로 낮게 잡혀 있다). 경계를
    지키는 것은 판정기다 — 정당한 거절은 appropriate=true 라 본문 교체 분기에 들어오지 않고,
    그래서 링크도 붙지 않는다. 이 테스트가 그 성질을 고정한다."""
    wire["verdict"] = _verdict(used_source=False, kind="refusal", appropriate=True)
    sp = _sp()
    sp.intent, sp.civil = "civil_petition", CIVIL

    sub, used = finalize_sub(sp, "그 내용은 저희가 안내드리기 어렵습니다.", marker_used_source=None)

    assert sub.attachments == [], "정당한 거절인데 신청 링크가 붙었다 — 범위 밖 질문에 오안내"
    assert sub.answer == "그 내용은 저희가 안내드리기 어렵습니다.", "정당한 거절문은 그대로 둔다"
    assert used is False


def test_ungrounded_answer_is_masked_not_link_rescued(wire):
    """근거 없는 서술은 링크를 붙일 게 아니라 가려야 할 답변이다 — 종전대로 범위외 교체."""
    wire["verdict"] = _verdict(used_source=False, kind="ungrounded_claims", appropriate=False)
    wire["regen"] = ("여전히 근거 이탈", False)
    sp = _sp()
    sp.intent, sp.civil = "civil_petition", CIVIL

    sub, used = finalize_sub(sp, "지어낸 본문", marker_used_source=None)

    assert sub.answer == OUT_OF_SCOPE_MESSAGE
    assert sub.attachments == []
    assert used is False
