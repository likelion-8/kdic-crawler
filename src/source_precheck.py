"""답변 사전 검사(프리체크) — 검증 LLM(source_check.validate_answer) 앞의 0콜 결정론 게이트.

## 무엇을 하나

답변 본문에서 수치(금액·기한·날짜·전화번호·비율)를 뽑아 근거 텍스트의 수치와 대조한다.
"깨끗함"(수치 전부 근거에 있음 + 마커 [SOURCE_USED])이면 LLM 검증을 건너뛰어도 되는
후보다 — 마커 [SOURCE_USED]의 정밀도는 실측 오판 0(라벨 107건 중 28건 + 배치 6건,
source_check.py 모듈 주석)이라 이 축은 신뢰하고, 수치는 LLM 판정이 오히려 약한
축(의미 유사성 기반이라 자릿수 오류에 관대)이라 여기서 결정론으로 잡는다.

## 지금은 섀도 전용 (2026-08-19)

이 모듈은 아직 파이프라인 동작을 바꾸지 않는다. 먼저 기존 rag_runs 로그로 소급 실험
(src/eval/eval_source_precheck_retro.py)을 돌려 두 숫자를 확인한 뒤 채택을 결정한다:
  - 절감률: 전체 답변 중 clean 비율 (= 건너뛸 수 있는 LLM 콜 비율)
  - 놓침률: clean 인데 luna 가 문제로 판정한 비율 (사전 합의 기준: 사람 라벨로 실제 문제 0건)
채택되면 api/rag/answer.py finalize_sub 의 validate_answer 호출 직전에 classify()를 끼운다.

## 설계 B(보수적) — 수치가 하나도 없으면 의심으로 떨어뜨린다

"수치 전부 근거에 있음"은 수치 0개일 때 공허참이 된다. v1은 확인한 것이 하나도 없는
답변을 통과시키지 않는다(reason="no_numbers") — 절감은 수치 포함 답변에서만 나오지만,
"clean 판정 = 뭔가를 실제로 대조해서 통과했다"가 보장된다. 운영 후 놓침률이 계속 0이면
설계 A(수치 없음 = 마커만으로 통과)로 넓히는 것을 재검토한다.

## 정규화의 한계는 안전한 방향으로 떨어진다

여기서 못 알아보는 표기("오천만" 같은 순한글 수사, "1억 5천만"의 합산 표기 등)는 매칭
실패 → suspicious → 지금처럼 LLM 검증을 받는다. 즉 정규화기의 빈틈은 절감 기회를
놓칠 뿐 품질을 잃지 않는다. 소급 실험이 reason 분포를 내주므로, number_mismatch 로
떨어진 건 중 "진짜 불일치"가 아니라 "정규화 실패"인 패턴을 보고 여기를 보강한다.
"""
import re
from dataclasses import dataclass, field

# 아라비아 숫자 뒤에 붙는 한국어 곱 단위. "5천만" = 5 x 1천만. 긴 것 먼저 매칭해야
# "천만"이 "천"+"만"으로 쪼개지지 않는다(정규식 alternation 순서로 보장).
_MULTIPLIERS = {
    "조": 10**12,
    "억": 10**8,
    "천만": 10**7,
    "백만": 10**6,
    "십만": 10**5,
    "만": 10**4,
    "천": 10**3,
    "백": 10**2,
    "십": 10,
}
_MULT_ALT = "|".join(_MULTIPLIERS)  # dict 는 삽입 순서 유지 → 긴 단위가 앞에 온다

# 추출 순서가 곧 우선순위다 — 앞 패턴이 소비한 구간은 뒤 패턴이 보지 않는다(스팬 마스킹).
# 전화번호를 먼저 떼지 않으면 1588-0037 이 1588 과 0037 두 숫자로 쪼개져 오탐이 난다.
_PATTERNS = [
    # 전화번호꼴(지역번호·대표번호): 숫자-숫자(-숫자). 자릿수로 느슨히 잡고 리터럴 보존.
    ("tel", re.compile(r"\d{2,4}-\d{3,4}(?:-\d{4})?")),
    # 날짜: 2026년 8월 19일 / 2026.8.19 / 8월 19일 (연도 없는 월일도 잡는다)
    ("date", re.compile(
        r"(?:(\d{4})\s*년\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일"
        r"|(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})")),
    # 비율: 50% / 0.1퍼센트 / 3프로
    ("pct", re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:%|퍼센트|프로)")),
    # 수량: 아라비아 숫자(쉼표·소수점 허용) + 선택적 한국어 곱 단위
    ("num", re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(" + _MULT_ALT + r")?")),
]

_URL_RE = re.compile(r"https?://|www\.")


def _to_float(digits: str) -> float:
    return float(digits.replace(",", ""))


def _fmt(value: float) -> str:
    """5.0e7 → '50000000'. 정수로 떨어지면 지수 표기 없이 — 토큰 비교가 문자열이라서다."""
    return str(int(value)) if value == int(value) else str(value)


def extract_numbers(text: str) -> set:
    """텍스트의 수치를 정규화 토큰 집합으로. 같은 값의 다른 표기가 같은 토큰이 되게 한다:
    '5천만원' == '50,000,000원' == '5,000만 원' → 'num:50000000'."""
    tokens = set()
    consumed = []  # (start, end) — 앞 패턴이 이미 소비한 스팬

    def overlaps(s, e):
        return any(s < ce and cs < e for cs, ce in consumed)

    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            if overlaps(m.start(), m.end()):
                continue
            if kind == "tel":
                tokens.add(f"tel:{m.group(0)}")
            elif kind == "date":
                y1, mo1, d1, y2, mo2, d2 = m.groups()
                year, month, day = (y1, mo1, d1) if mo1 else (y2, mo2, d2)
                # 연도 없는 '8월 19일'은 md: 로 — 연도 있는 표기와 섞어 비교하지 않는다
                tokens.add(f"date:{int(year)}-{int(month)}-{int(day)}" if year
                           else f"md:{int(month)}-{int(day)}")
            elif kind == "pct":
                tokens.add(f"pct:{_fmt(_to_float(m.group(1)))}")
            else:
                value = _to_float(m.group(1))
                if m.group(2):
                    value *= _MULTIPLIERS[m.group(2)]
                tokens.add(f"num:{_fmt(value)}")
            consumed.append((m.start(), m.end()))
    return tokens


@dataclass
class PrecheckResult:
    """clean=True 면 LLM 검증을 건너뛸 수 있는 답변. reason 은 판정 사유(집계·디버깅용):
    clean / marker_no_source / no_evidence / url_in_body / no_numbers / number_mismatch."""
    clean: bool
    reason: str
    missing: list = field(default_factory=list)  # number_mismatch 일 때 근거에 없던 토큰들


def classify(answer_text: str, evidence: str, marker_used_source: bool) -> PrecheckResult:
    """답변 하나를 깨끗함/의심으로 판정한다. 0콜, 수 ms.

    answer_text: 마커를 떼어낸 답변 본문(finalize_sub 가 받는 body 와 동일).
    evidence: 생성 때 프롬프트에 넣은 근거 텍스트(validate_answer 에 넘기는 것과 동일).
    marker_used_source: HCX 자기보고 마커 판정(prompt_builder 가 파싱한 bool).
    """
    if not marker_used_source:
        # [NO_SOURCE] 마커의 42%는 오판(근거를 썼는데 안 썼다고 보고)이라 마커만으로
        # 판정을 확정할 수 없다 — 재생성 구제 경로도 이쪽에 있으므로 반드시 LLM 검증으로.
        return PrecheckResult(False, "marker_no_source")
    if not str(evidence).strip():
        return PrecheckResult(False, "no_evidence")
    if _URL_RE.search(answer_text):
        # URL 은 LLM 에게 안 맡기는 구조(pipeline.py — citation 이 결정론적으로 부착)라,
        # 본문에 URL 이 보이는 것 자체가 이상 신호다.
        return PrecheckResult(False, "url_in_body")
    answer_nums = extract_numbers(answer_text)
    if not answer_nums:
        return PrecheckResult(False, "no_numbers")  # 설계 B — 모듈 docstring 참고
    missing = sorted(answer_nums - extract_numbers(evidence))
    if missing:
        return PrecheckResult(False, "number_mismatch", missing)
    return PrecheckResult(True, "clean")
