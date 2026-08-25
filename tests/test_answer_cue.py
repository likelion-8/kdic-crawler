"""되뱉은 "답변:" 큐 제거 — 생성 프롬프트가 "질문/답변" 쌍으로 끝나서 HCX 가 자기 턴에
그 큐를 한 번 더 찍는 롤이 있다(2026-08-25 웹 화면에 "답변: 예금자보호제도 신청은…" 노출).

롤마다 갈리는 확률적 현상이라 프롬프트로는 못 잡는다 — 결정론적으로 벗기고, 그 규칙을
여기 고정한다. 특히 **웹(스트리밍)과 CLI(일괄)가 같은 기준**이어야 한다: 두 경로가 갈리면
같은 질문의 답변이 화면마다 달라진다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "src"):
    sys.path.insert(0, str(p))

from api.rag.sse import _MarkerStripper  # noqa: E402
from prompt_builder import parse_marker, strip_answer_cue  # noqa: E402


def _stream(tokens):
    """스트리밍 경로를 토큰 단위로 재현 -> (보인 본문, used_source)."""
    st = _MarkerStripper()
    return "".join(st.feed(t) for t in tokens) + st.finalize(), st.used_source


# ── 무엇을 벗기나 ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "답변: 본문",
    "답변 : 본문",
    "답변：본문",      # 전각 콜론
    "**답변**: 본문",  # 마크다운 굵게
    "답변:\n본문",
])
def test_strips_the_echoed_cue(raw):
    assert strip_answer_cue(raw) == "본문"


# ── 무엇을 남기나 — 여기가 이 규칙의 안전선이다 ──────────────────────────────────

@pytest.mark.parametrize("raw", [
    "답변 드리겠습니다. 착오송금은 이렇게 처리됩니다.",   # 콜론이 없으면 정상 본문이다
    "답변드립니다: 착오송금은 이렇게 처리됩니다.",        # '답변' 바로 뒤가 콜론이 아니다
    "착오송금 반환지원 신청은 총 4단계입니다.",
    "질문: 이건 본문의 일부다",                          # 인식 대상은 '답변' 하나뿐
])
def test_leaves_normal_bodies_alone(raw):
    assert strip_answer_cue(raw) == raw


def test_strips_only_one_cue():
    """한 번만 벗긴다 — 본문이 우연히 같은 모양으로 이어질 때 두 번째까지 먹지 않는다."""
    assert strip_answer_cue("답변: 답변: 본문") == "답변: 본문"


# ── 마커와 섞인 순서 ─────────────────────────────────────────────────────────────
# 큐와 마커는 둘 다 앞머리 장식이라 순서가 정해져 있지 않다. 어느 쪽이 먼저 와도 벗겨야 한다.

@pytest.mark.parametrize("raw,body,used", [
    ("답변: [SOURCE_USED]\n본문", "본문", True),
    ("[SOURCE_USED]\n답변: 본문", "본문", True),
    ("[NO_SOURCE] 답변: 본문", "본문", False),
    ("마커도 큐도 없는 본문입니다.", "마커도 큐도 없는 본문입니다.", None),
])
def test_parse_marker_handles_both_orders(raw, body, used):
    assert parse_marker(raw) == (body, used)


# ── 스트리밍도 같은 결과여야 한다 ────────────────────────────────────────────────

def test_streaming_strips_a_cue_split_across_tokens():
    """토큰 경계가 큐 한가운데를 갈라도(첫 줄 버퍼링) 벗겨야 한다."""
    seen, used = _stream(["답변", ": ", "예금자보호제도 신청은", " 자동입니다.\n", "다음 줄"])
    assert seen == "예금자보호제도 신청은 자동입니다.\n다음 줄"
    assert used is None


def test_streaming_strips_a_cue_on_the_line_after_the_marker():
    """마커가 첫 줄을 다 차지하면 큐는 둘째 줄에 온다 — 여기서 멈추면 웹만 큐를 흘려보내
    비스트리밍 parse_marker 와 결과가 갈린다."""
    seen, used = _stream(["[SOURCE_USED]\n", "답변: 본문\n", "둘째 줄"])
    assert seen == "본문\n둘째 줄"
    assert used is True


def test_streaming_keeps_a_marker_only_answer_empty():
    """마커만 오고 끝나도 멈춰야 한다(버퍼링이 영원히 늘어지면 안 된다)."""
    assert _stream(["[SOURCE_USED]\n"]) == ("", True)


@pytest.mark.parametrize("tokens", [
    ["답변 드리겠습니다.", " 착오송금은…\n"],
    ["착오송금 반환지원 신청은", " 총 4단계입니다.\n"],
])
def test_streaming_leaves_normal_bodies_alone(tokens):
    assert _stream(tokens)[0] == "".join(tokens)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
