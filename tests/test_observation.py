"""api/rag/observation.py 자가 점검 — 관측 기록의 모양과 '모름' 규칙.

핵심 회귀 대상은 **모르는 것을 false 로 적지 않는다**는 규칙이다. 이게 깨지면 AD-005 화면이
'검증을 안 돌림'과 '검증했는데 근거 미사용'을 같은 것으로 보여줘, 관리자가 원인을 반대로 짚는다.
"""
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

from rag import observation as obs  # noqa: E402


@dataclass
class FakeSubPlan:
    """SubPlan 중 관측이 읽는 필드만. 실물은 api/rag/answer.py 의 dataclass."""
    question: str
    intent: str = "informational"
    top: list = None
    obs_marker: Optional[bool] = None
    obs_used_source: Optional[bool] = None
    obs_kind: Optional[str] = None
    obs_appropriate: Optional[bool] = None
    obs_normalized: Optional[bool] = None


def test_no_subplans_is_none():
    # 캐시 적중·가드레일 차단은 검색을 안 탄다 — '관측 없음'과 '내용 없음'은 다르다
    assert obs.build([]) is None
    assert obs.build(None) is None


def test_top_is_capped_and_carries_page_and_score():
    sp = FakeSubPlan("한도?", top=[(f"pg_{i}#c{i}", 0.9 - i / 100, "본문") for i in range(8)])
    got = obs.build([sp])
    top = got["subs"][0]["top"]
    assert len(top) == obs.TOP_N, "상위 N개로 잘라야 로그가 답변보다 커지지 않는다"
    assert top[0] == {"chunk_id": "pg_0#c0", "page_id": "pg_0", "score": 0.9}


def test_unknown_verdict_stays_none():
    # 검증 스위치가 꺼져 판정이 안 적힌 경우 — false 로 적으면 '근거 미사용'이 되어 거짓이다
    got = obs.build([FakeSubPlan("한도?", top=[("dp_protlmts#c1", 0.8, "t")])])
    s = got["subs"][0]
    assert s["used_source"] is None and s["marker"] is None and s["normalized"] is None
    assert obs.summarize(got)["source_used"] is None


def test_summarize_counts_pages_not_chunks():
    sp = FakeSubPlan("한도?", obs_used_source=True, obs_marker=True, top=[
        ("dp_protlmts#c1", 0.9, "t"), ("dp_protlmts#c2", 0.8, "t"), ("dp_faq#c1", 0.7, "t")])
    got = obs.summarize(obs.build([sp]))
    assert got["source_count"] == 2, "같은 페이지의 청크 2개는 출처 1개다"
    assert got["source_used"] is True
    assert got["marker"] == "[SOURCE_USED]"


def test_expected_pages_skips_ungrounded_subs():
    used = FakeSubPlan("한도?", obs_used_source=True, top=[("dp_protlmts#c1", 0.9, "t")])
    unused = FakeSubPlan("안녕?", obs_used_source=False, top=[("noise_page#c1", 0.2, "t")])
    pages = obs.expected_pages(obs.build([used, unused]))
    assert pages == ["dp_protlmts"], "근거를 안 쓴 답변의 검색결과는 정답 후보가 아니다"


def test_expected_pages_keeps_unverified_subs():
    # 검증을 안 돌렸을 뿐 근거는 실제 프롬프트에 들어갔다 — 후보에서 빼면 정답이 사라진다
    sp = FakeSubPlan("한도?", top=[("dp_protlmts#c1", 0.9, "t")])
    assert obs.expected_pages(obs.build([sp])) == ["dp_protlmts"]


def test_validated_but_unchanged_is_false_not_none():
    # 검증이 돌았고 보정이 없었다면 그건 '모름'이 아니라 '보정 안 함'이다.
    # answer.finalize_sub 가 v is not None 일 때 obs_normalized=False 를 적는 규약과 짝이다.
    sp = FakeSubPlan("한도?", obs_kind="grounded", obs_appropriate=True,
                     obs_used_source=True, obs_normalized=False, top=[("a#c", 0.9, "t")])
    assert obs.summarize(obs.build([sp]))["normalized"] is False


def test_mixed_markers_report_as_mixed():
    a = FakeSubPlan("한도?", obs_marker=True, top=[("a#c", 0.9, "t")])
    b = FakeSubPlan("절차?", obs_marker=False, top=[("b#c", 0.9, "t")])
    assert obs.summarize(obs.build([a, b]))["marker"] == "혼재"


def test_summarize_of_missing_observation_is_all_none():
    for empty in (None, {}, {"subs": []}):
        assert obs.summarize(empty) == {
            "source_count": None, "source_used": None, "marker": None, "normalized": None}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"  ok  {name}")
    print("observation self-check ok")
