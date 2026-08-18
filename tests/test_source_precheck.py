"""source_precheck 단위 테스트 — 정규화기가 흔들리면 소급 실험 숫자가 전부 무의미해지므로
실험(eval_source_precheck_retro.py) 전에 여기부터 통과해야 한다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from source_precheck import classify, extract_numbers  # noqa: E402


# ── 수치 추출·정규화 ──────────────────────────────────────────────────────────

def test_korean_multiplier_equals_arabic():
    # 같은 금액의 세 표기가 같은 토큰이 돼야 답변↔근거 대조가 성립한다
    assert extract_numbers("5천만원") == {"num:50000000"}
    assert extract_numbers("50,000,000원") == {"num:50000000"}
    assert extract_numbers("5,000만 원") == {"num:50000000"}


def test_eok_and_jo():
    assert extract_numbers("1억원까지 보호") == {"num:100000000"}
    assert extract_numbers("100,000,000원") == {"num:100000000"}
    assert extract_numbers("2조 규모") == {"num:2000000000000"}


def test_cheonman_not_split_into_cheon_and_man():
    # alternation 순서가 깨지면 "천만"이 천(1e3)으로 잡힌다 — 회귀 방지
    assert extract_numbers("3천만원") == {"num:30000000"}


def test_phone_number_kept_literal():
    # 1588-0037 이 1588 과 0037 로 쪼개지면 안 된다
    assert extract_numbers("콜센터 1588-0037로 문의") == {"tel:1588-0037"}


def test_dates():
    assert extract_numbers("2026년 8월 19일 시행") == {"date:2026-8-19"}
    assert extract_numbers("2026.8.19 시행") == {"date:2026-8-19"}
    # 연도 없는 월일은 md: 로 별도 표기 — 연도 있는 날짜와 오매칭되지 않게
    assert extract_numbers("8월 19일까지") == {"md:8-19"}


def test_percent():
    assert extract_numbers("연 0.1% 이자") == {"pct:0.1"}
    assert extract_numbers("50퍼센트") == {"pct:50"}


def test_decimal_and_comma():
    assert extract_numbers("1,234건") == {"num:1234"}


# ── classify 판정 ─────────────────────────────────────────────────────────────

EVIDENCE = "예금자 1인당 금융회사별로 5천만원까지 보호됩니다. 신청은 1년 이내."


def test_clean_when_numbers_match_and_marker_used():
    r = classify("보호한도는 50,000,000원입니다. 1인당 기준입니다.", EVIDENCE, True)
    assert r.clean and r.reason == "clean"


def test_mismatch_caught():
    # 근거에 없는 1억 — LLM 검증(의미 판정)은 이런 자릿수 오류에 관대할 수 있지만
    # 여기서는 결정론으로 잡힌다. 프리체크의 존재 이유.
    r = classify("보호한도는 1억원입니다.", EVIDENCE, True)
    assert not r.clean and r.reason == "number_mismatch"
    assert "num:100000000" in r.missing


def test_marker_no_source_always_suspicious():
    # [NO_SOURCE] 는 42% 오판(source_check.py) — 재생성 구제 경로 보존을 위해 항상 검증행
    r = classify("보호한도는 5천만원입니다.", EVIDENCE, False)
    assert not r.clean and r.reason == "marker_no_source"


def test_no_numbers_is_suspicious_design_b():
    # 설계 B: 대조한 것이 하나도 없으면 통과 아님
    r = classify("예금자보호제도는 예금을 보호하는 제도입니다.", EVIDENCE, True)
    assert not r.clean and r.reason == "no_numbers"


def test_empty_evidence_suspicious():
    r = classify("보호한도는 5천만원입니다.", "", True)
    assert not r.clean and r.reason == "no_evidence"


def test_url_in_body_suspicious():
    # URL 은 citation 이 결정론 부착 — 본문에 있으면 그 자체가 이상 신호
    r = classify("자세한 내용은 https://www.kdic.or.kr 에서 5천만원 한도를 확인하세요.",
                 EVIDENCE, True)
    assert not r.clean and r.reason == "url_in_body"


def test_unparseable_notation_falls_safe():
    # 순한글 수사는 v1 미지원 — 매칭 실패로 의심에 떨어져야 한다(안전한 방향).
    # 답변의 "오천만원"에서 수치가 안 뽑히므로 no_numbers 로 검증행이 된다.
    r = classify("보호한도는 오천만원입니다.", EVIDENCE, True)
    assert not r.clean
