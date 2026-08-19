"""FAQ 청크 포맷 4변형 — 패러프레이즈 과잉 거절(false refusal)의 오프라인 판가름 실험.

## 배경 (2026-08-19)

FAQ 청크가 크롤링 흔적 그대로 "질문\\n1. {원문 질문}\\n열기\\n답변\\n{답}" 구조라, 생성 LLM 이
사용자 질문과 청크에 박힌 원문 질문의 **문구를 대조**해서 다르면 거절하는 패턴이 실측됐다
(같은 근거·같은 프롬프트에서 질문 문구만 원문으로 바꾸면 정답 — 팀 문구 대조 실험).
추천 칩 질문이 전부 원문의 패러프레이즈라 이 지름길에 정면으로 걸린다. 프롬프트 지시는
이 판단 습관을 못 고친다는 게 반복 실측됐으므로(35회 실험·구/신 프롬프트 동일 거절),
**모델이 보는 청크 텍스트 쪽**을 바꾸는 4가지 변형을 비교한다:

  A 현행(대조군)
  B 프리펜드 — "[제목 · 업무]" 뒤에 "아래는 이 주제의 FAQ 문답" 프레이밍 한 줄.
    원문 보존 불변식(chunking._selftest 부분문자열 검사)과 충돌하지 않는 최소 침습.
  C 아티팩트 제거 — 아코디언 잔재 "열기" 삭제 (크롤링 쓰레기 — 어차피 지워야 함)
  D 재라벨링 — "질문 N." → "관련 질문 예시:", "열기" 제거, "답변" 한 줄 정리.
    박힌 질문을 '이 자료의 유일한 질문'이 아니라 '예시'로 읽히게. C 를 포함한다.
    본문을 고치므로 채택 시 불변식 갱신 필요.

## 방법

재색인 불필요 — 검색은 질문당 1회만 하고(4변형 모두 같은 근거), 청크 텍스트만 변형해
프롬프트를 조립한 뒤 HCX 를 부른다. 호출은 두 종류:
  - greedy 1회(temperature 0): "최빈 응답이 거절인가"의 결정론 신호(주 지표).
    ⚠️ temp 0 에선 시드를 바꿔도 같은 답이 나온다(2026-08-19 실측) — 반복은 무의미.
  - 운영 샘플링(temperature 0.2) --samples 회: 거절률의 확률 추정(보조 지표).

지표: 거절(마커 [NO_SOURCE]) · 정답 포함(must_include) · 원문 유출(답변에 '열기' 또는
대괄호 프리픽스가 새어 나옴 — 이번에 같이 발견된 부작용).

429(HCX 속도제한)는 대기 후 재시도한다. 문항당 콜 수 = 변형 4 x (1 + samples).
실행: python src/eval/eval_faq_chunk_format.py [--samples 2] [--sleep 3]
"""
import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from candidate_ranking import gate_low_relevance, top_k_cut  # noqa: E402
from llm_client import call_hyperclova  # noqa: E402
from prompt_builder import _strip_no_source_marker, build_informational_prompt  # noqa: E402
from retrieval import route_search_chunks  # noqa: E402

# (질문, 정답 판별 문자열) — 칩 패러프레이즈 2 + 테스트셋 패러프레이즈 1
QUESTIONS = [
    ("착오송금 반환까지 얼마나 걸리나요?", "2개월"),
    ("반환지원 대상이 아닌 경우는 어떤 경우인가요?", None),   # 정답이 목록형이라 거절 여부만 본다
    ("착오송금 신청하고 나서 실제로 돈을 돌려받기까지 보통 얼마나 걸리나요?", "2개월"),
]

# FAQ 청크 구조: "질문\n1. {Q}\n열기\n답변\n{A}" (chunks_all.jsonl 실물 기준).
# 번호 없는 변형("질문\n{Q}\n열기\n답변\n")도 흡수한다.
_FAQ_RE = re.compile(r"질문\n(?:\d+\.\s*)?(.+?)\n열기\n답변\n", re.DOTALL)
_PREFIX_END_RE = re.compile(r"^(\[[^\]]+\]\s*)")   # "[제목 · 업무] " 프리픽스

FRAMING = "아래는 이 주제에 대해 자주 묻는 질문과 그 답변입니다.\n"


def v_current(text):
    return text


def v_prepend(text):
    if not _FAQ_RE.search(text):
        return text
    m = _PREFIX_END_RE.match(text)
    if m:
        return text[:m.end(1)] + FRAMING + text[m.end(1):]
    return FRAMING + text


def v_artifact(text):
    return text.replace("\n열기\n", "\n")


def v_relabel(text):
    return _FAQ_RE.sub(lambda m: f"관련 질문 예시: {m.group(1)}\n답변: ", text)


VARIANTS = [("A.현행", v_current), ("B.프리펜드", v_prepend),
            ("C.열기제거", v_artifact), ("D.재라벨링", v_relabel)]


def call_with_retry(prompt, *, deterministic, sleep):
    for attempt in range(4):
        try:
            return call_hyperclova(prompt, deterministic=deterministic,
                                   seed=(20260819 if deterministic else None))
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                wait = 20 * (attempt + 1)
                print(f"    (속도제한 — {wait}초 대기 후 재시도)")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("속도제한 재시도 소진")


def judge(raw, must_include):
    body, marker_used = _strip_no_source_marker(raw)
    refused = not marker_used
    correct = (must_include in body) if must_include else None
    leaked = ("열기" in body) or body.lstrip().startswith("[") or "] " in body[:80]
    return refused, correct, leaked, body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=2, help="변형당 운영 샘플링(temp 0.2) 횟수")
    ap.add_argument("--sleep", type=float, default=3.0)
    args = ap.parse_args()

    for q, must in QUESTIONS:
        top = gate_low_relevance(top_k_cut(route_search_chunks(q, k=20), k=5))
        print(f"\n{'=' * 70}\n질문: {q}\n근거 top3: {[(c, round(s, 3)) for c, s, _ in top[:3]]}")
        for name, fn in VARIANTS:
            chunks = [(cid, s, fn(t)) for cid, s, t in top]
            prompt = build_informational_prompt(q, chunks)
            time.sleep(args.sleep)
            raw = call_with_retry(prompt, deterministic=True, sleep=args.sleep)
            refused, correct, leaked, body = judge(raw, must)
            line = f"  {name:10s} greedy: {'거절' if refused else '답변'}"
            if correct is not None:
                line += f" · 정답 {'O' if correct else 'X'}"
            line += f" · 유출 {'O' if leaked else 'X'}"
            samp = []
            for _ in range(args.samples):
                time.sleep(args.sleep)
                raw_s = call_with_retry(prompt, deterministic=False, sleep=args.sleep)
                r_s, _, _, _ = judge(raw_s, must)
                samp.append(r_s)
            if samp:
                line += f" | 샘플링 거절 {sum(samp)}/{len(samp)}"
            print(line)
            print(f"      └ {body[:70].replace(chr(10), ' ')}")


if __name__ == "__main__":
    main()
