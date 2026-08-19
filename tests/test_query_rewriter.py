"""query_rewriter 가드 검증 — 핵심 불변식: **첫 턴(무이력)은 LLM 을 부르지 않는다.**

이게 깨지면 모든 단일 턴 질문에 OpenAI 콜이 하나씩 붙는다 — 멀티턴 기능의 비용 약속
("후속 턴에만 +1콜")이 조용히 무너지는 회귀라 테스트로 고정한다. 재작성 품질 자체는
LLM 판단이라 여기서 재지 않는다(실측은 수동/평가 스크립트 몫).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "src"):
    sys.path.insert(0, str(p))

import query_rewriter  # noqa: E402
from query_rewriter import _format_history, rewrite_followup  # noqa: E402


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """이 테스트 파일에서 LLM 이 불리면 그 자체가 실패다."""
    def _boom():
        raise AssertionError("무이력/빈 질문 경로에서 OpenAI 클라이언트가 생성됐다")
    monkeypatch.setattr(query_rewriter, "_get_client", _boom)


def test_no_history_skips_llm_entirely():
    assert rewrite_followup("착오송금 반환 기한은?", []) is None


def test_blank_query_skips_llm():
    assert rewrite_followup("   ", [("user", "이전 질문")]) is None


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
