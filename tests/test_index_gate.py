"""src/index_gate.py — 색인 교체 게이트의 판정 로직.

build 를 주입해 임베딩 모델 없이 돌린다. 이 게이트가 잘못 판정하면 두 방향 모두 사고다 —
느슨하면 품질이 떨어진 색인이 사용자에게 나가고, 빡빡하면 멀쩡한 재적재가 영영 반영되지 않아
관리자가 다시 개발자를 부른다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "src"):
    sys.path.insert(0, str(p))

import index_gate  # noqa: E402


class FakeRetriever:
    """질문 → 청크 순위를 표로 받아 그대로 돌려준다. search 시그니처만 실물과 맞춘다."""

    def __init__(self, ranking):
        self.ranking = ranking

    def search(self, query, k):
        return [(cid, 1.0 - i / 100) for i, cid in enumerate(self.ranking[query][:k])]


def _build(ranking):
    return lambda _uids, _texts: FakeRetriever(ranking)


ROWS = [
    {"question": "한도?", "expected_sources": ["dp_protlmts"]},
    {"question": "절차?", "expected_sources": ["ms_poss_dcmnt"]},
]


def test_all_gold_at_top_passes():
    ranking = {"한도?": ["dp_protlmts#0", "x#0"], "절차?": ["ms_poss_dcmnt#0", "y#0"]}
    got = index_gate.evaluate([], [], ROWS, build=_build(ranking))
    assert got["passed"] is True
    assert got["metrics"] == {"recall@5": 1.0, "mrr": 1.0, "n": 2}
    assert got["failures"] == []


def test_gold_missing_everywhere_fails_both_metrics():
    ranking = {"한도?": ["noise#0"] * 6, "절차?": ["noise#1"] * 6}
    got = index_gate.evaluate([], [], ROWS, build=_build(ranking))
    assert got["passed"] is False
    assert {f["key"] for f in got["failures"]} == {"recall@5", "mrr"}
    # 화면에 그대로 실릴 문구라 '무엇이 얼마나' 가 들어 있어야 한다
    assert "미달" in index_gate.describe(got) and "recall@5" in index_gate.describe(got)


def test_chunks_fold_to_pages_before_ranking():
    """같은 페이지의 청크가 상위를 채워도 페이지 순위는 하나다 — 이걸 안 접으면 정답 페이지가
    5위 밖으로 밀려 멀쩡한 색인이 미달로 잡힌다."""
    ranking = {
        "한도?": ["a#0", "a#1", "a#2", "a#3", "a#4", "dp_protlmts#0"],
        "절차?": ["ms_poss_dcmnt#0"],
    }
    got = index_gate.evaluate([], [], ROWS, build=_build(ranking))
    assert got["metrics"]["recall@5"] == 1.0, "a 의 청크 5개는 페이지 1개로 접혀야 한다"


def test_out_of_scope_rows_are_not_scored():
    """정답이 없는 범위 외 문항에 Recall 을 매기면 분모가 부풀어 전체 수치가 왜곡된다."""
    rows = ROWS + [{"question": "안녕?", "expected_sources": []}]
    ranking = {"한도?": ["dp_protlmts#0"], "절차?": ["ms_poss_dcmnt#0"], "안녕?": ["noise#0"]}
    got = index_gate.evaluate([], [], rows, build=_build(ranking))
    assert got["metrics"]["n"] == 2


def test_multi_source_row_scores_by_ratio():
    """정답이 2개인데 1개만 맞으면 0.5 — 정기 평가(eval_pipeline_retrieval)와 같은 규약이라야
    게이트를 통과한 색인이 정기 평가에서 미달로 뒤집히지 않는다."""
    rows = [{"question": "한도?", "expected_sources": ["dp_protlmts", "dp_faq_page"]}]
    ranking = {"한도?": ["dp_protlmts#0", "noise#0"]}
    got = index_gate.evaluate([], [], rows, build=_build(ranking))
    assert got["metrics"]["recall@5"] == 0.5


def test_empty_testset_is_an_error_not_a_pass():
    """평가셋이 비었을 때 조용히 통과시키면 게이트가 있으나 마나가 된다 — 가장 위험한 실패다."""
    with pytest.raises(ValueError):
        index_gate.evaluate([], [], [{"question": "안녕?", "expected_sources": []}],
                            build=_build({}))


def test_targets_come_from_the_single_source():
    """목표값을 이 파일에 다시 적지 않았는지 — 화면 기준과 실제 판정이 갈리는 것을 막는다."""
    from api.routers.admin_evaluations import GATE_CRITERIA

    canonical = {k: t for k, _l, _tg, _op, t, _f in GATE_CRITERIA}
    got = index_gate.evaluate([], [], ROWS,
                              build=_build({"한도?": ["dp_protlmts#0"], "절차?": ["ms_poss_dcmnt#0"]}))
    assert got["targets"]["recall@5"] == canonical["retrieval_accuracy@5"]
    assert got["targets"]["mrr"] == canonical["mrr"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
