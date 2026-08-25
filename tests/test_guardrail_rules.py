"""guardrail_hit — 규칙 필드(행별 활성·적용 범위·유형)가 실제 동작에 반영되는지.

2026-08-14 정정 전에는 pattern 만 읽어서, AD-008 편집 UI 의 유형·적용 범위·행별 활성이
전부 무시됐다(관리자가 무엇을 고르든 항상 '전 규칙·양방향·문자 그대로'). 이 테스트가
깨지면 그 거짓 입력칸 상태로 되돌아간 것이다. runtime_config.get_prompt 만 대역으로 바꾼다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "api", ROOT / "src"):
    sys.path.insert(0, str(p))

import runtime_config  # noqa: E402
from api.rag.answer import guardrail_hit  # noqa: E402


@pytest.fixture
def rules(monkeypatch):
    state = {"items": [], "active": True}
    monkeypatch.setattr(
        runtime_config, "get_prompt",
        lambda _k, _d: {"blocklist": {"active": state["active"], "items": state["items"]}})
    return state


def test_scope_question_only_skips_answer_side(rules):
    rules["items"] = [{"pattern": "대출 알선", "scope": "질문", "active": True}]
    assert guardrail_hit("대출 알선 문의", side="질문") == "대출 알선"
    assert guardrail_hit("대출 알선 안내", side="답변") is None


def test_scope_both_hits_both_sides(rules):
    rules["items"] = [{"pattern": "불법 사금융", "scope": "질문 + 답변", "active": True}]
    assert guardrail_hit("불법 사금융?", side="질문") == "불법 사금융"
    assert guardrail_hit("불법 사금융 관련…", side="답변") == "불법 사금융"


def test_per_item_active_off_is_skipped(rules):
    # 목록 전체 스위치와 별개다 — 종전에는 행을 OFF 해도 계속 차단됐다
    rules["items"] = [{"pattern": "수익 보장", "scope": "질문 + 답변", "active": False}]
    assert guardrail_hit("수익 보장 되나요", side="질문") is None


def test_regex_type_actually_matches_as_regex(rules):
    rules["items"] = [{"pattern": r"\d{3}-\d{4}-\d{4}", "type": "정규식",
                       "scope": "질문 + 답변", "active": True}]
    assert guardrail_hit("연락처 010-1234-5678 남겨요", side="질문") is not None
    assert guardrail_hit("연락처 없음", side="질문") is None


def test_broken_regex_skips_only_that_rule(rules):
    # 실패-안전: 정규식 하나가 틀렸다고 나머지 규칙까지 죽으면 안 된다
    rules["items"] = [
        {"pattern": "[미완성", "type": "정규식", "scope": "질문 + 답변", "active": True},
        {"pattern": "원금 보장", "scope": "질문 + 답변", "active": True},
    ]
    assert guardrail_hit("원금 보장 상품?", side="질문") == "원금 보장"


def test_legacy_string_items_keep_working(rules):
    # 옛 형식(문자열 배열) — 게시본 마이그레이션 없이 그대로 동작해야 한다
    rules["items"] = ["몰빵"]
    assert guardrail_hit("몰빵 투자", side="답변") == "몰빵"


def test_dictionary_type_uses_builtin_dictionary(rules):
    # '사전' 행의 pattern 은 이름일 뿐이다 — 매칭은 내장 사전이 한다
    rules["items"] = [{"pattern": "비속어 기본 사전", "type": "사전",
                       "scope": "질문 + 답변", "active": True}]
    assert guardrail_hit("씨발 이게 뭐야", side="질문") == "씨발"
    assert guardrail_hit("보호 한도가 얼마인가요", side="질문") is None


def test_dictionary_scope_answer_only_lets_rude_questions_through(rules):
    # 정상 질문 뒤에 욕을 붙이는 사용자 — 질문은 받고 답변만 검사한다(2026-08-25 관리자 설정)
    rules["items"] = [{"pattern": "비속어 기본 사전", "type": "사전",
                       "scope": "답변", "active": True}]
    assert guardrail_hit("보호 한도가 얼마야 씨발", side="질문") is None
    assert guardrail_hit("씨발 그건 안 됩니다", side="답변") == "씨발"


def test_dictionary_disabled_words_are_skipped(rules):
    # 화면(「사전 보기」)에서 끈 표제어는 그 규칙에서만 빠지고, 나머지 사전은 그대로 산다
    rules["items"] = [{"pattern": "비속어 기본 사전", "type": "사전", "scope": "질문",
                       "active": True, "disabled": ["병신"]}]
    assert guardrail_hit("병신 같은 안내", side="질문") is None
    assert guardrail_hit("씨발 같은 안내", side="질문") == "씨발"


def test_list_level_switch_still_wins(rules):
    rules["active"] = False
    rules["items"] = [{"pattern": "수익 보장", "scope": "질문 + 답변", "active": True}]
    assert guardrail_hit("수익 보장", side="질문") is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
