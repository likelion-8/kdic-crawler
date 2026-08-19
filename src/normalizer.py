"""Gate 1 텍스트 정규화 — 원문 하나에서 세 가지 표현을 만든다.

원문(raw_text)은 절대 건드리지 않고, 검색·판정이 각자 다른 강도의 정규화를 쓰도록 분리한다:

- raw_text      : 사용자 입력 그대로. 로그·재현용(이 모듈은 이 값을 반환만 하고 수정하지 않는다).
- canonical_text: 검색·임베딩이 쓰는 '최소 정규화' 버전(아래 1~6단계). 문장부호를 지우지 않는다.
- stripped      : canonical 에서 문장부호만 더 제거한 것(7단계). '전체 문장 일치'용
                  (인사·감사·정체성 표현은 wrapper 를 남긴 채 비교해야 하므로 이 단계까지만).
- rule_text     : stripped 에서 정중 표현 wrapper 까지 제거한 것(8단계). Gate 1 판정 전용.

핵심 원칙(설계 프롬프트 2-1): 자동 오타 교정·자동 띄어쓰기 교정은 **하지 않는다.** 정규화는
전부 결정론적(유니코드 정규화·불가시 문자 제거·공백/문장부호 정리)이며, 형태소 분석기
(kiwipiepy)도 여기서는 쓰지 않는다 — 정상 질문을 의미 왜곡 없이 통과시키는 것이 목적이라
가역적이고 예측 가능한 변환만 한다.

wrapper 목록은 gate1_rules.yaml(normalization 절)에서 넘겨받는 것이 정본이고, 아래 기본값은
설정이 없을 때의 폴백이자 test_normalizer.py 가 단독 실행될 수 있게 하는 문서화된 기본값이다.
"""
from __future__ import annotations

import re
import unicodedata
from typing import NamedTuple, Optional, Sequence

# 정중 표현 wrapper — 문장 앞/뒤에 붙는 상투어. rule_text 에서만 제거한다(canonical 은 유지).
# gate1_rules.yaml 의 normalization 절이 있으면 그 값이 이기고, 없으면 이 기본값을 쓴다.
DEFAULT_WRAPPER_PREFIXES = [
    "혹시", "저기요", "저기", "실례지만", "죄송하지만", "안녕하세요", "안녕하십니까",
]
DEFAULT_WRAPPER_SUFFIXES = [
    "알려주세요", "설명해주세요", "답변해주세요", "알려줘", "설명해줘",
    "궁금합니다", "문의드립니다", "부탁드립니다",
]

# 탭·개행 등 '공백류 제어문자'는 삭제하지 않고 공백으로 바꾼다 — 삭제하면 단어가 붙어버려
# ("a\tb" -> "ab") 경계가 사라진다. 그 외 제어문자(Cc)·포맷문자(Cf: zero-width 포함)는 삭제.
_WS_CONTROL = {"\t", "\n", "\r", "\v", "\f"}

# 문장부호로 취급해 rule_text 에서 지울(공백으로 바꿀) 추가 문자 — 유니코드 카테고리가 P* 가
# 아니라서(기호/자모로 분류돼) category 검사로는 안 걸리는 것들을 명시한다.
#   ~,∼: TILDE 류(Sm) · …: 줄임표 · ·,ㆍ: 가운뎃점/아래아(중점 표기) · `,^,|: 기타 기호
_EXTRA_PUNCT = set("~∼…·ㆍ`^|")

# rule_text 에서도 남겨야 하는 문장부호성 문자 — 퍼센트는 수량 의미(설계 프롬프트 2-1의
# '퍼센트' 보존 조항)라 지우지 않는다. 숫자·통화기호는 애초에 P* 가 아니라 여기 없어도 남는다.
_PUNCT_KEEP = set("%")


class Normalized(NamedTuple):
    """정규화 3종 세트. raw_text 는 호출부가 이미 갖고 있어 여기 담지 않는다."""
    canonical: str
    stripped: str
    rule_text: str


def _strip_invisibles(text: str) -> str:
    """zero-width·제어·포맷 문자를 없애고, 공백류 제어문자는 공백으로 바꾼다(경계 보존)."""
    out = []
    for ch in text:
        if ch in _WS_CONTROL:
            out.append(" ")
            continue
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf"):  # 제어문자 / 포맷문자(zero-width ​~‍, ﻿ 포함)
            continue
        out.append(ch)
    return "".join(out)


def _collapse_ws(text: str) -> str:
    """연속 공백을 한 칸으로 축약하고 양끝 공백을 제거한다."""
    return re.sub(r"\s+", " ", text).strip()


def to_canonical(raw: str) -> str:
    """최소 정규화(설계 프롬프트 2-1의 1~6단계) — 검색·임베딩이 쓰는 버전.

    1) NFKC 2) 불가시/제어문자 제거 3) 탭·개행->공백 4) 연속공백 축약 5) strip 6) casefold.
    문장부호는 지우지 않는다(그건 stripped/rule_text 단계에서).
    """
    if raw is None:
        return ""
    t = unicodedata.normalize("NFKC", str(raw))
    t = _strip_invisibles(t)      # 2·3단계(공백류 제어문자는 공백으로 치환됨)
    t = _collapse_ws(t)           # 4·5단계
    return t.casefold()           # 6단계 — 영문 대소문자 통일(한글엔 영향 없음)


def _strip_punct(text: str) -> str:
    """문장부호를 공백으로 바꿔 없앤다(단어 경계 보존). 퍼센트·숫자·통화기호는 남긴다.

    설계 프롬프트 2-1 7단계: 부정/조건·범위·수량·의문사·조사 같은 '의미 단어'는 애초에
    문장부호가 아니라 지워지지 않는다 — 여기서는 문장부호(마침표/쉼표/물음표/느낌표/물결 등)만
    골라 없앤다."""
    out = []
    for ch in text:
        if ch in _PUNCT_KEEP:
            out.append(ch)
        elif ch in _EXTRA_PUNCT or unicodedata.category(ch).startswith("P"):
            out.append(" ")      # 삭제가 아니라 공백 치환 — "안녕,예금" -> "안녕 예금"
        else:
            out.append(ch)
    return _collapse_ws("".join(out))


def _strip_wrappers(text: str, prefixes: Sequence[str], suffixes: Sequence[str]) -> str:
    """앞/뒤 정중 표현 wrapper 를 단어 경계에서만 반복 제거한다.

    경계(공백 또는 문자열 끝)에서만 떼므로 단어 중간을 자르지 않는다("한도를"의 앞부분을
    prefix 로 오인해 자르는 일이 없다). 여러 wrapper 가 겹쳐 붙어도(예: "혹시 안녕하세요 ...")
    바뀔 게 없을 때까지 돌며 다 떼어낸다. 전체가 wrapper 면 빈 문자열이 된다."""
    # 긴 것부터 시도해야 "저기요"가 "저기"로 먼저 잘려 "요"가 남는 일이 없다.
    prefixes = sorted(prefixes, key=len, reverse=True)
    suffixes = sorted(suffixes, key=len, reverse=True)
    changed = True
    while changed and text:
        changed = False
        for p in prefixes:
            if text == p:
                return ""
            if text.startswith(p) and text[len(p):len(p) + 1] == " ":
                text = text[len(p):].lstrip()
                changed = True
                break
        if not text:
            break
        for s in suffixes:
            if text == s:
                return ""
            if text.endswith(s) and text[-len(s) - 1:-len(s)] == " ":
                text = text[:-len(s)].rstrip()
                changed = True
                break
    return text


def normalize(raw: str,
              wrapper_prefixes: Optional[Sequence[str]] = None,
              wrapper_suffixes: Optional[Sequence[str]] = None) -> Normalized:
    """원문 -> (canonical, stripped, rule_text). wrapper 목록이 None 이면 기본값을 쓴다."""
    prefixes = wrapper_prefixes if wrapper_prefixes is not None else DEFAULT_WRAPPER_PREFIXES
    suffixes = wrapper_suffixes if wrapper_suffixes is not None else DEFAULT_WRAPPER_SUFFIXES
    canonical = to_canonical(raw)
    stripped = _strip_punct(canonical)
    rule_text = _strip_wrappers(stripped, prefixes, suffixes)
    return Normalized(canonical=canonical, stripped=stripped, rule_text=rule_text)
