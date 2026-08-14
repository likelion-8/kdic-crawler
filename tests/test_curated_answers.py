"""답변 매핑(AD-009 curated_answers) — 검증 규칙과 서빙 계약.

핵심 회귀 대상 둘: (1) 출처 없는 답변이 등록되면 안 된다(민원 리스크 불변식),
(2) 같은 질문 키가 두 답변에 걸리면 안 된다(어느 답이 나갈지 순서 좌우 — 조용한 비결정성).
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "api", ROOT / "src"):
    sys.path.insert(0, str(p))

from api.errors import BadRequestError  # noqa: E402
from api.routers.admin_ops import _validate_curated, cache_key_for_question  # noqa: E402


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDb:
    """_validate_curated 는 활성 page_id 목록 조회 한 번만 한다."""

    def __init__(self, page_ids=("dp_protlmts", "faq_msdr_apply")):
        self.page_ids = page_ids

    def execute(self, _stmt):
        return _Result([SimpleNamespace(page_id=p) for p in self.page_ids])


def _item(**over):
    base = {"id": "ca_1", "questions": ["예금자보호 한도가 얼마인가요?"],
            "answer": "1인당 1억원까지 보호됩니다.", "source_page_ids": ["dp_protlmts"],
            "active": True, "order": 1}
    return {**base, **over}


def test_valid_item_gets_keys_and_resolved_sources():
    items = _validate_curated([_item()], _FakeDb())
    it = items[0]
    assert it["question_keys"] == [cache_key_for_question("예금자보호 한도가 얼마인가요?")]
    assert it["sources"], "출처가 저장 시점에 확정돼야 서빙이 코퍼스 재조회 없이 결정적이다"
    assert it["sources"][0]["page_id"] == "dp_protlmts"


def test_sources_are_mandatory():
    with pytest.raises(BadRequestError, match="출처"):
        _validate_curated([_item(source_page_ids=[])], _FakeDb())


def test_unknown_page_id_is_rejected():
    with pytest.raises(BadRequestError, match="page_id"):
        _validate_curated([_item(source_page_ids=["ghost_page"])], _FakeDb())


def test_duplicate_key_across_answers_is_rejected():
    # 정규화가 같아지는 두 문구(공백 차이) — 문자열이 달라도 키가 겹치면 잡아야 한다
    a = _item(id="ca_1", questions=["한도가 얼마인가요?"])
    b = _item(id="ca_2", questions=["한도가  얼마인가요?"], order=2)
    if cache_key_for_question(a["questions"][0]) != cache_key_for_question(b["questions"][0]):
        b = _item(id="ca_2", questions=["한도가 얼마인가요?"], order=2)   # 정규화가 공백을 안 접으면 동일 문구로
    with pytest.raises(BadRequestError, match="겹칩"):
        _validate_curated([a, b], _FakeDb())


def test_duplicate_phrasing_within_one_answer_is_folded():
    items = _validate_curated([_item(questions=["한도?", "한도?"])], _FakeDb())
    assert len(items[0]["question_keys"]) == 1


def test_empty_questions_rejected():
    with pytest.raises(BadRequestError, match="질문 문구"):
        _validate_curated([_item(questions=[])], _FakeDb())


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
