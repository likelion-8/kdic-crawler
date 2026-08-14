"""질문 유형 분류의 자기참조 누수 차단 — 평가 정직성.

참조 예시가 골든셋(evaluation_dataset)이고 운영 검색 경로가 그걸 그대로 읽는다. 골든셋 문항으로
평가하면 질문이 자기 자신을 유사도 1.0 으로 끌어와 라우팅이 항상 정답이 되어, 평가 수치가
실서비스(처음 보는 질문)보다 후하게 나온다. 이 테스트가 깨지면 그 착시가 되돌아온다.

DB·모델을 붙이지 않는다 — 분류기 인스턴스의 상태(questions/types/emb)만 직접 채워
argmax 규칙을 시험한다. 여기가 이음매다.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "src"):
    sys.path.insert(0, str(p))

from query_classifier import QuestionTypeClassifier  # noqa: E402


class _FakeModel:
    """질문 문자열 → 미리 정한 벡터. 실제 인코딩 없이 유사도 관계만 재현한다."""

    def __init__(self, vectors):
        self.vectors = vectors

    def encode(self, queries, **_kwargs):
        return np.array([self.vectors[q] for q in queries])


def _classifier(examples, vectors):
    """__init__ 은 DB 를 읽으므로 우회하고 상태만 채운다(이 클래스의 실제 이음매는 classify)."""
    c = QuestionTypeClassifier.__new__(QuestionTypeClassifier)
    c.questions = [q for q, _ in examples]
    c.types = [t for _, t in examples]
    c.emb = np.array([vectors[q] for q, _ in examples])
    c.model = _FakeModel(vectors)
    return c


# '한도?' 는 골든셋에도 있는 문항이다. 자기 자신(fact)이 1.0 으로 가장 가깝고,
# 그 다음으로 가까운 다른 예시는 table_lookup 이다.
VECTORS = {
    "한도?": np.array([1.0, 0.0]),
    "보호 한도 표": np.array([0.95, 0.31]),
    "전혀 다른 질문": np.array([0.0, 1.0]),
}
EXAMPLES = [("한도?", "fact"), ("보호 한도 표", "table_lookup"), ("전혀 다른 질문", "faq")]


def test_default_pulls_itself_in():
    """운영 경로(기본값)는 그대로 — 처음 보는 질문에는 자기 자신이 없으므로 무해하다."""
    c = _classifier(EXAMPLES, VECTORS)
    assert c.classify("한도?") == "fact"


def test_exclude_self_drops_the_identical_example():
    """평가 경로는 자기 자신을 빼고 다음으로 가까운 예시를 쓴다 — 실서비스와 같은 조건."""
    c = _classifier(EXAMPLES, VECTORS)
    assert c.classify("한도?", exclude_self=True) == "table_lookup"


def test_exclude_self_is_noop_for_unseen_questions():
    """홀드아웃처럼 겹침이 없는 평가셋에서는 스위치가 결과를 바꾸지 않아야 한다."""
    vectors = {**VECTORS, "처음 보는 질문": np.array([0.96, 0.28])}
    c = _classifier(EXAMPLES, vectors)
    assert c.classify("처음 보는 질문") == c.classify("처음 보는 질문", exclude_self=True)


def test_exclude_self_matches_on_exact_text_only():
    """원문이 다르면 뜻이 같아도 빼지 않는다 — 실서비스에서도 정당한 예시라 빼면 오히려
    실제와 멀어진다. 임계값 기반으로 바꾸면 이 테스트가 먼저 깨진다."""
    vectors = {**VECTORS, "한도? ": np.array([1.0, 0.0])}   # 뒤에 공백 하나
    c = _classifier(EXAMPLES, vectors)
    assert c.classify("한도? ", exclude_self=True) == "fact", "원문이 다르면 남는다"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
