"""Gate 1 — 파이프라인 최앞단의 결정론적 룰 기반 입력 필터(LLM 호출 없음).

역할(설계 프롬프트 1절): **확실한 것만 즉시 처리하고, 조금이라도 애매하면 전부 통과시킨다.**
OOS 를 많이 잡는 것(recall)이 목표가 아니라, 정상 질문을 잘못 차단하지 않는 것(precision ≈ 100%)이
유일한 목표다. 그래서 여기서 EXIT(고정 응답으로 즉시 종료)하는 것은 인사·감사·노이즈·정체성
질문과, 명백한 보안 우회·개인정보 직접조회·타 분야 단일 질문뿐이다. 그 외는 전부 CONTINUE 로
다음 단계(Gate 2 → 기존 Query Planner)로 흘려보낸다.

이 프로젝트의 OOS 판정은 4단계 캐스케이드(Gate 1 룰 → Gate 2 임베딩 → Gate 3 크로스인코더
점수 → Gate 4 Supervisor LLM)로 설계돼 있다. Gate 1·Gate 2는 '확실한 것'에 한해 즉시 종료
(EXIT)할 수 있고(2026-08-19 Gate 2 도입, src/gate2.py), Gate 3·Gate 4(미구현)는 신호만 넘기고
최종 판정을 Gate 4가 종합하는 구조로 설계돼 있다.

무엇을 잡을지는 전부 config/gate1_rules.yaml 이 정한다 — 이 모듈은 '판정 순서'(run_gate1)만
갖는다. 규칙을 켜고 끄거나 단어를 더하는 것은 YAML 수정만으로 된다. langfuse 는 여기서 부르지
않는다(관측은 호출부가 observability 를 거쳐 붙인다) — Gate 1 로직은 순수·테스트 가능해야 한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from normalizer import normalize

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config" / "gate1_rules.yaml"

# 질문 '전체'가 이 문자들로만 이루어지면 노이즈로 본다(ㅋㅎㅠㅜ·자모 파편·문장부호·물결).
# 일반 한글/영문/숫자가 한 글자라도 섞이면 매칭되지 않는다("...얼마야ㅋㅋ" -> CONTINUE).
#
# ⚠️ NFKC 는 호환용 자모(ㅋ U+314B)를 결합용 자모(ᄏ U+110F)로 분해한다 — canonical 은
# NFKC 를 거친 값이라 "ㅋㅋㅋ" 가 결합용 자모로 바뀌어 있다. 그래서 호환 자모 블록만이 아니라
# 결합용 자모 블록까지 함께 넣어야 낱자 반복(ㅋㅋ/ㅠㅠ)이 노이즈로 잡힌다.
NOISE_PATTERN = re.compile(
    "^[\\s"
    "ᄀ-ᇿ"      # 한글 자모(결합용) — NFKC 결과가 여기로 떨어진다
    "㄰-㆏"      # 한글 호환 자모(ㅋㅎㅠㅜ 등 입력 원형, ㆍ U+318D 포함)
    "ꥠ-꥿"      # 한글 자모 확장-A
    "ힰ-퟿"      # 한글 자모 확장-B
    "?!.,~…·]+$"         # 문장부호·물결·가운뎃점
)


@dataclass
class Gate1Result:
    """Gate 1 판정 결과. EXIT 면 response_text 를 그대로 사용자에게 돌려주고 파이프라인을 타지
    않는다. CONTINUE 면 rule_id/response_id/response_text 는 None 이고 기존 흐름이 그대로 이어진다.

    canonical_text/rule_text 를 함께 실어 호출부(관측)가 무엇을 보고 판정했는지 기록하게 한다."""
    action: str                       # "EXIT" | "CONTINUE"
    label: str                        # "FIXED_GREETING" | ... | "CONTINUE"
    rule_id: Optional[str]            # 매칭된 규칙 ID(CONTINUE 면 None)
    response_id: Optional[str]
    response_text: Optional[str]      # 실제로 돌려줄 고정 응답 문구
    raw_text: str
    canonical_text: str
    rule_text: str
    reason: str                       # "protected_word" | "no_rule_matched" | "greeting" | ...


@dataclass
class _Compiled:
    """YAML 을 판정에 바로 쓰기 좋은 형태로 컴파일한 것(전부 casefold 완료)."""
    wrapper_prefixes: list
    wrapper_suffixes: list
    protected_words: list             # casefold 된 부분일치 대상
    responses: dict                   # response_id -> [문구, ...]
    labels: dict                      # label -> 컴파일된 규칙 슬롯


_CONFIG_CACHE: dict = {}


def _cf_list(items) -> list:
    """문자열 목록을 casefold 한다(빈/None 은 빈 목록). 매칭은 canonical(이미 casefold)과 비교."""
    return [str(x).casefold() for x in (items or [])]


def _compile_config(raw: dict) -> _Compiled:
    """원본 YAML dict -> _Compiled. 같은 label 규칙이 여럿이면 단어를 합치고, id 는 첫 규칙 것을
    쓴다. enabled=false 규칙은 통째로 건너뛴다(그 label 검사 자체가 사라진다)."""
    norm = raw.get("normalization") or {}
    prefixes = norm.get("wrapper_prefixes")   # None 이면 normalizer 기본값이 쓰임
    suffixes = norm.get("wrapper_suffixes")
    protected = _cf_list(raw.get("protected_words"))
    responses = raw.get("responses") or {}

    labels: dict = {}
    for rule in raw.get("rules") or []:
        if not rule.get("enabled", True):
            continue
        label = rule.get("label")
        if not label:
            continue
        slot = labels.get(label)
        if slot is None:
            slot = {
                "rule_id": rule.get("rule_id"),
                "response_id": rule.get("response_id"),
                "words": set(), "phrases": set(),
                "protected_targets": set(), "disclosure_actions": set(), "bypass_phrases": set(),
                "personal_refs": set(), "personal_data": set(), "direct_access_actions": set(),
                "categories": [], "max_words": 15,
            }
            labels[label] = slot
        slot["words"].update(_cf_list(rule.get("words")))
        slot["phrases"].update(_cf_list(rule.get("phrases")))
        slot["protected_targets"].update(_cf_list(rule.get("protected_targets")))
        slot["disclosure_actions"].update(_cf_list(rule.get("disclosure_actions")))
        slot["bypass_phrases"].update(_cf_list(rule.get("bypass_phrases")))
        slot["personal_refs"].update(_cf_list(rule.get("personal_refs")))
        slot["personal_data"].update(_cf_list(rule.get("personal_data")))
        slot["direct_access_actions"].update(_cf_list(rule.get("direct_access_actions")))
        cats = rule.get("categories")
        if isinstance(cats, dict):
            for spec in cats.values():
                slot["categories"].append({
                    "topics": set(_cf_list((spec or {}).get("topics"))),
                    "actions": set(_cf_list((spec or {}).get("actions"))),
                })
        if "max_words" in rule:
            slot["max_words"] = rule["max_words"]

    return _Compiled(
        wrapper_prefixes=prefixes, wrapper_suffixes=suffixes,
        protected_words=protected, responses=responses, labels=labels)


def load_config(path=None, force: bool = False) -> _Compiled:
    """규칙 설정을 로드·컴파일하고 캐시한다(경로별 1회). 테스트에서 force=True 로 다시 읽는다."""
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    key = str(path)
    if not force and key in _CONFIG_CACHE:
        return _CONFIG_CACHE[key]
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cfg = _compile_config(raw)
    _CONFIG_CACHE[key] = cfg
    return cfg


def _contains_any(text: str, needles) -> bool:
    """text 에 needle 중 하나라도 부분 문자열로 있으면 True(needle 은 이미 casefold 됨)."""
    return any(n and n in text for n in needles)


def _has_personal_ref(text: str, refs) -> bool:
    """개인 지칭(내/제/본인) 검출 — 한 글자(내·제)는 단어 경계에서만 인정해 오탐을 막는다.

    "내"를 그냥 부분일치로 잡으면 "안내/내역/국내"에, "제"는 "제도/문제/경제"에 걸려 정상
    질문을 개인 지칭으로 오인한다. 그래서 한 글자 지칭은 (문장 시작|공백) 뒤에 오고 뒤에
    (공백|'의'|끝)이 올 때만 인정한다("제 은행"/"내 계좌"는 잡고 "제도"·"내역"은 안 잡는다).
    두 글자 이상(본인)은 부분일치로 충분하다."""
    for r in refs:
        if not r:
            continue
        if len(r) == 1:
            if re.search(r"(?:^|\s)" + re.escape(r) + r"(?:\s|의|$)", text):
                return True
        elif r in text:
            return True
    return False


def run_gate1(raw_text: str, config_path=None) -> Gate1Result:
    """질문 하나를 받아 Gate 1 판정 결과를 돌려준다(설계 프롬프트 2-5의 실행 순서 그대로).

    EXIT 는 '확실한 것'에 한해서만 난다. 판정은 전부 canonical/stripped/rule_text(정규화 3종)
    위에서 결정론적으로 이뤄진다 — 같은 입력은 항상 같은 결과다."""
    cfg = load_config(config_path)
    norm = normalize(raw_text, cfg.wrapper_prefixes, cfg.wrapper_suffixes)
    canonical, stripped, rule_text = norm.canonical, norm.stripped, norm.rule_text

    def _exit(label: str, reason: str) -> Gate1Result:
        slot = cfg.labels.get(label, {})
        response_id = slot.get("response_id")
        variants = cfg.responses.get(response_id) or []
        return Gate1Result(
            action="EXIT", label=label, rule_id=slot.get("rule_id"),
            response_id=response_id, response_text=(variants[0] if variants else None),
            raw_text=raw_text, canonical_text=canonical, rule_text=rule_text, reason=reason)

    def _continue(reason: str) -> Gate1Result:
        return Gate1Result(
            action="CONTINUE", label="CONTINUE", rule_id=None, response_id=None,
            response_text=None, raw_text=raw_text, canonical_text=canonical,
            rule_text=rule_text, reason=reason)

    # 1·2) 빈 입력 -> NOISE(설계상 빈 입력도 노이즈로 응대). NOISE 규칙이 꺼져 있으면 CONTINUE.
    if not canonical:
        return _exit("FIXED_NOISE", "empty_input") if "FIXED_NOISE" in cfg.labels \
            else _continue("empty_input")

    # 3) 노이즈 — 질문 전체가 ㅋㅎㅠㅜ·자모·문장부호로만 구성.
    if "FIXED_NOISE" in cfg.labels and NOISE_PATTERN.fullmatch(canonical):
        return _exit("FIXED_NOISE", "noise_only")

    # 4) 보안 — (보호대상 ∩ 공개행동) ∪ 우회표현. 보호 단어 유무와 무관하게 먼저 차단한다.
    sec = cfg.labels.get("SECURITY_BLOCK")
    if sec:
        has_target = _contains_any(canonical, sec["protected_targets"])
        has_action = _contains_any(canonical, sec["disclosure_actions"])
        has_bypass = _contains_any(canonical, sec["bypass_phrases"])
        if (has_target and has_action) or has_bypass:
            return _exit("SECURITY_BLOCK", "prompt_injection")

    # 5) 인사/감사 — wrapper 제거 '전' 전체 일치(stripped)를 먼저, 그 다음 wrapper 제거 후
    #    rule_text 가 비었거나 목록과 일치하면 매칭. rule_text 에 내용이 남으면 CONTINUE.
    #
    # ⚠️ "rule_text 가 비면 매칭" 을 곧이곧대로 적용하면 "설명해주세요"·"궁금합니다"처럼
    # 인사말 없이 wrapper **suffix 하나만** 온 입력도 전부 지워져 빈 문자열이 되어 인사로
    # 오판정된다(2026-08-14 리뷰 지적) — "설명해주세요" 는 인사가 아니라 내용 없는 불완전한
    # 요청이다. 그래서 "비어 있음"을 받아들이는 건 stripped 안에 인사/감사 단어가 실제로
    # 어절 단위로 존재했을 때뿐이다(예: "안녕하세요 알려주세요" 는 "안녕하세요" 라는 인사
    # 어절이 있었으므로 인정, "설명해주세요" 단독은 인사 어절이 없었으므로 불인정 → CONTINUE).
    for label, reason in (("FIXED_GREETING", "greeting"), ("FIXED_THANKS", "thanks")):
        slot = cfg.labels.get(label)
        if not slot:
            continue
        words = slot["words"]
        if stripped in words or rule_text in words:
            return _exit(label, reason)
        if rule_text == "" and set(stripped.split()) & words:
            return _exit(label, reason)

    # 6) 봇 정체성/도움 — 전체 문장(wrapper 유지)이 정형 표현과 일치. wrapper 를 뗀 rule_text 가
    #    아니라 stripped 로 비교한다("사용 방법 알려줘"의 '알려줘'가 wrapper 로 잘리면 안 되므로).
    for label, reason in (("FIXED_BOT_INTRO", "bot_intro"), ("FIXED_BOT_HELP", "bot_help")):
        slot = cfg.labels.get(label)
        if slot and stripped in slot["phrases"]:
            return _exit(label, reason)

    # 7) 역량 밖 — 개인지칭 ∩ 개인데이터 ∩ 직접접근행동 세 종류가 '전부' 있을 때만.
    #    (보호 단어 검사보다 먼저 — 예: "제 은행 계좌 잔액을 ... 직접 조회"는 '은행'이 보호
    #     단어지만 개인정보 직접조회라 차단해야 한다.)
    cap = cfg.labels.get("CAPABILITY_UNAVAILABLE")
    if cap and _has_personal_ref(canonical, cap["personal_refs"]) \
            and _contains_any(canonical, cap["personal_data"]) \
            and _contains_any(canonical, cap["direct_access_actions"]):
        return _exit("CAPABILITY_UNAVAILABLE", "capability_unavailable")

    # 8) 보호 단어가 하나라도 있으면 Gate 1 은 여기서 손을 뗀다(hard block 포기, 뒤로 미룸).
    if _contains_any(canonical, cfg.protected_words):
        return _continue("protected_word")

    # 9) 타 분야 — 주제어 ∩ 행동어 조합 + (위에서 보호 단어 없음 확인) + 짧은 단일 목적.
    oos = cfg.labels.get("OUT_OF_DOMAIN_RULE")
    if oos and len(canonical.split()) <= oos["max_words"]:
        for cat in oos["categories"]:
            if _contains_any(canonical, cat["topics"]) and _contains_any(canonical, cat["actions"]):
                return _exit("OUT_OF_DOMAIN_RULE", "out_of_domain")

    # 10) 나머지 전부 통과.
    return _continue("no_rule_matched")
