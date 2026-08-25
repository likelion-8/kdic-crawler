"""query_rewriter 가드·계약 검증. 재작성 품질 자체는 LLM 판단이라 여기서 재지 않는다
(실측은 수동/평가 스크립트 몫).

2026-08-25 로 불변식이 뒤집혔다. 종전 핵심 불변식은 "첫 턴(무이력)은 LLM 을 부르지 않는다"
였는데, 되묻기 판정을 Gate 2 앞으로 옮기면서 **첫 턴에도 부르는 것이 요구사항이 됐다**
(모듈 docstring "왜 첫 턴에도 부르는가"). 그래서 여기서 고정하는 것은 반대 방향이다 —
무이력에서도 콜이 나가는가, 그리고 빈 이력이 프롬프트에 표식으로 들어가는가.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "src"):
    sys.path.insert(0, str(p))

import query_rewriter  # noqa: E402
from query_rewriter import (NO_HISTORY, _format_history, _unwrap_quotes,  # noqa: E402
                            triage_query)


@pytest.fixture
def no_llm(monkeypatch):
    """LLM 이 불리면 그 자체가 실패 — 빈 질문 조기반환 경로 검증용."""
    def _boom():
        raise AssertionError("빈 질문 경로에서 OpenAI 클라이언트가 생성됐다")
    monkeypatch.setattr(query_rewriter, "_get_client", _boom)


@pytest.fixture
def spy_llm(monkeypatch):
    """실제 호출 없이 프롬프트에 실린 [이전 대화] 를 들여다본다."""
    seen = {}

    def _fake_run(query, history_text):
        seen["query"], seen["history_text"] = query, history_text
        return "SENTINEL"
    monkeypatch.setattr(query_rewriter, "_run", _fake_run)
    return seen


def test_first_turn_still_calls_the_llm(spy_llm):
    """2026-08-25 로 뒤집힌 불변식 — 무이력이라고 건너뛰면 첫 턴 되묻기가 통째로 죽는다.
    (Gate 2 가 업무 미정 질문을 먼저 EXIT 시키므로 뒤에 받아줄 판정기가 없다.)"""
    assert triage_query("신청 방법 알려줘", []) == "SENTINEL"
    assert spy_llm["query"] == "신청 방법 알려줘"


def test_first_turn_marks_the_absent_history(spy_llm):
    """빈 문자열로 넘기면 LLM 이 '이력이 잘린 것'과 '원래 없는 것'을 구분 못 한다 —
    프롬프트의 첫 턴 규칙이 이 표식을 보고 rewritten=false 를 고정한다."""
    triage_query("신청 방법 알려줘", [])
    assert spy_llm["history_text"] == NO_HISTORY


def test_blank_query_skips_llm(no_llm):
    assert triage_query("   ", [("user", "이전 질문")]) is None



def test_format_history_labels_and_truncates():
    history = [("user", "질문1"), ("assistant", "답" * 1000)]
    out = _format_history(history)
    assert out.startswith("사용자: 질문1")
    assert "챗봇: " in out
    # 턴당 길이 제한 — 답변 전문이 통째로 들어가면 토큰만 는다
    assert len(out) < 1000 + 50


def test_format_history_keeps_only_recent_turns():
    history = [("user", f"질문{i}") for i in range(20)]
    out = _format_history(history)
    assert "질문0" not in out and f"질문{19}" in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── 감싼 따옴표 벗기기 ────────────────────────────────────────────────────────────
# standalone_question 은 그대로 검색 질의이자 캐시 키다. LLM 이 출력을 따옴표로 감싸면
# 같은 질문이 캐시에 두 행으로 쌓이고 검색 질의도 오염된다(2026-08-21 실측).

def test_unwrap_strips_curly_quotes():
    """실제로 query_cache 에 쌓였던 모양."""
    assert _unwrap_quotes('“반환지원 대상이 아닌 경우는 어떤 경우인가요?”') ==         "반환지원 대상이 아닌 경우는 어떤 경우인가요?"


def test_unwrap_strips_straight_quotes():
    assert _unwrap_quotes('"착오송금이 뭐야?"') == "착오송금이 뭐야?"
    assert _unwrap_quotes("'착오송금이 뭐야?'") == "착오송금이 뭐야?"


def test_unwrap_strips_nested_quotes():
    assert _unwrap_quotes('"“착오송금이 뭐야?”"') == "착오송금이 뭐야?"


def test_unwrap_leaves_unmatched_quote_alone():
    """한쪽에만 있는 따옴표는 원문 인용의 일부일 수 있어 건드리지 않는다."""
    assert _unwrap_quotes('"착오송금이 뭐야?') == '"착오송금이 뭐야?'
    assert _unwrap_quotes('착오송금이 뭐야?”') == '착오송금이 뭐야?”'


def test_unwrap_leaves_inner_quotes_alone():
    """가운데 따옴표는 의미가 있는 인용이라 남긴다."""
    q = '“착오송금”이 무슨 뜻인가요?'
    assert _unwrap_quotes(q) == q


def test_unwrap_leaves_plain_question_alone():
    assert _unwrap_quotes("착오송금 반환 기한은 언제인가요?") == "착오송금 반환 기한은 언제인가요?"
