"""정규화 함수 단위 테스트 — canonical/stripped/rule_text 3종이 설계 프롬프트 2-1 대로 나오는지.

DB·LLM 을 전혀 쓰지 않는 순수 함수 테스트라 수 밀리초면 끝난다:
    python3 -m pytest tests/test_normalizer.py -q
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from normalizer import (  # noqa: E402  (sys.path 조정 후 import)
    normalize, to_canonical,
)


# ── canonical: NFKC · 불가시/제어문자 제거 · 공백 축약 · casefold ──

def test_canonical_collapses_and_trims_whitespace():
    assert to_canonical("  안녕   하세요  ") == "안녕 하세요"


def test_canonical_converts_tab_newline_to_space_boundary():
    # 탭·개행은 삭제가 아니라 공백으로 — 단어가 붙지 않아야 한다
    assert to_canonical("예금\t보호\n한도") == "예금 보호 한도"


def test_canonical_removes_zero_width_and_control_chars():
    # zero-width space/joiner/BOM 이 끼어도 사라져 같은 문자열이 된다
    assert to_canonical("예금​보호﻿한도") == "예금보호한도"


def test_canonical_casefolds_english():
    assert to_canonical("Hello WORLD") == "hello world"


def test_canonical_nfkc_normalizes_fullwidth():
    # 전각 영숫자는 NFKC 로 반각이 된다
    assert to_canonical("ＫＤＩＣ") == "kdic"


def test_canonical_keeps_punctuation():
    # canonical 은 '최소 정규화' — 문장부호는 남긴다(그건 stripped 단계에서 제거)
    assert to_canonical("한도는?!") == "한도는?!"


def test_canonical_empty_and_none():
    assert to_canonical("") == ""
    assert to_canonical("   ") == ""
    assert to_canonical(None) == ""


# ── stripped: canonical + 문장부호 제거(단어 경계 보존, 퍼센트/숫자 유지) ──

def test_stripped_removes_punctuation():
    assert normalize("안녕하세요!!!").stripped == "안녕하세요"


def test_stripped_punctuation_becomes_space_not_glue():
    # "안녕,예금" 이 "안녕예금" 으로 붙지 않고 "안녕 예금" 이 된다
    assert normalize("안녕,예금").stripped == "안녕 예금"


def test_stripped_keeps_numbers_and_percent():
    n = normalize("보호한도 5000만원 3.5% 인가요?")
    # 숫자·퍼센트·통화 의미는 유지, 물음표/마침표만 제거
    assert "5000" in n.stripped and "%" in n.stripped
    assert "?" not in n.stripped


# ── rule_text: stripped + 앞/뒤 정중 표현 wrapper 제거 ──

def test_rule_text_strips_greeting_prefix_and_polite_suffix():
    # 설계 프롬프트 2-1 예시
    n = normalize("안녕하세요 예금자보호 한도를 알려주세요")
    assert n.canonical == "안녕하세요 예금자보호 한도를 알려주세요"  # canonical 은 wrapper 유지
    assert n.rule_text == "예금자보호 한도를"                      # rule_text 는 wrapper 제거


def test_rule_text_only_strips_at_word_boundary():
    # "한도를" 의 앞부분을 prefix 로 오인해 자르지 않는다(경계 없는 부분일치는 무시)
    assert normalize("보호한도를 알려주세요").rule_text == "보호한도를"


def test_rule_text_all_wrapper_becomes_empty():
    assert normalize("안녕하세요 알려주세요").rule_text == ""


def test_rule_text_strips_multiple_stacked_wrappers():
    # 앞뒤로 여러 wrapper 가 겹쳐 붙어도 다 떨어진다
    assert normalize("혹시 예금 보호 궁금합니다").rule_text == "예금 보호"


def test_custom_wrapper_lists_override_defaults():
    # config 에서 넘긴 wrapper 만 적용되는지(기본값과 분리)
    n = normalize("문의합니다 예금 보호 문의합니다",
                  wrapper_prefixes=[], wrapper_suffixes=["문의합니다"])
    assert n.rule_text == "문의합니다 예금 보호"  # prefix 목록이 비어 앞쪽은 안 떼어짐
