"""AD-008 가드레일의 「사전」 유형이 실제로 쓰는 한국어 비속어 사전.

## 왜 코드에 두나

화면(AD-008)에서 금칙어 규칙의 유형을 「사전」으로 고를 수 있는데, 종전에는 런타임이 그 행의
`pattern` 문자열을 **그대로** 찾았다 — 목의 기본값이 `'비속어 기본 사전 (외부 사전)'` 이라
사용자가 그 문구를 통째로 입력하지 않는 한 영원히 걸리지 않는, 이름만 있는 유형이었다.
사전 본문을 DB(JSONB)에 넣으면 관리자가 화면에서 수백 줄을 편집·삭제할 수 있게 되는데,
그건 오탐이 곧 서비스 장애가 되는 규칙이라 검토 없이 바뀌면 안 된다. 그래서 사전은 코드에
두고 배포로만 바꾸며, 화면의 「사전」 행은 그 사전을 켜고 끄는 스위치로 쓴다.

## 출처

LDNOOBW(List of Dirty, Naughty, Obscene and Otherwise Bad Words)의 한국어 목록 72개가
기반이다 — CC BY 4.0, https://github.com/LDNOOBW/List-of-Dirty-Naughty-Obscene-and-Otherwise-Bad-Words
여러 상용 모더레이션 스택이 그대로 싣고 있어 사실상 표준으로 통한다. 한국어 자료 색인은
https://github.com/Tanat05/korean-profanity-resources 참고.

## 그대로 쓰면 서비스가 깨진다 (2026-08-24 실측)

원본 72개를 부분 문자열로 매칭하면 **우리 코퍼스와 평가셋에서 지금 당장 오탐이 난다**:

    '자지' ← "선불전**자지**급수단을 활용하는 간편송금업자도…"   (착오송금 핵심 용어)
    '보지' ← "국내 소재 부동산은 은닉재산으로 **보지** 않습니다"
    '고자' ← "거래하시**고자** 하는 금융회사", "접수하**고자** 할 때"
    '호로' ← "진양**호로** 532", "전화번**호로** 문의하면"
    '씹'   ← "지급명령도 **씹**으면 최후엔 어떻게 돈을 받아내요?"  (평가셋 실제 문항)

질문 쪽 오탐은 정상 민원 질문이 「안내가 제한되는 표현」으로 거절되는 것이라, 놓치는 욕설
하나보다 훨씬 비싸다. 그래서 세 갈래로 나눈다:

  SUBSTRING — 한국어 정상어에 부분 문자열로 끼어들 일이 없는 항목. 그대로 찾는다.
  BOUNDED   — 뜻은 살리되 앞뒤가 한글이면 흘려보낸다(`(?<![가-힣])W(?![가-힣])`).
              "전자지급"의 '자지'는 앞이 '전'이라 빠지고, 단독으로 쓴 '자지'는 걸린다.
              대신 조사가 붙은 형태("자지가")는 놓친다 — 오탐을 피하려고 택한 쪽이다.
  DROPPED   — 정상어와 겹치는 폭이 넓어 아예 쓰지 않는다. 왜 뺐는지 여기 남겨 두는 이유는
              다음 사람이 "표준 목록에 있는데 왜 없지?" 하고 되돌리는 것을 막기 위해서다.

바꿀 때는 `python3 api/rag/blocklist_ko.py` 를 돌린다 — 코퍼스·평가셋 전문과 대조해
오탐이 0인지, 실제 욕설은 걸리는지 확인한다.
"""

from __future__ import annotations

import re
from typing import Optional

# ── 부분 문자열로 찾아도 되는 항목 ────────────────────────────────────────────
# 3글자 이상은 대부분 여기 온다. 2글자는 "이 두 글자가 다른 낱말 안에 들어가는 한국어 단어가
# 있는가"를 따져 남겼다(예: '변태'는 생물학 용어이기도 하지만 낱말 안에 끼지는 않는다).
SUBSTRING: tuple[str, ...] = (
    # LDNOOBW ko
    "강간", "개좆", "개새끼", "개자식", "개차반", "계집년", "근친상간",
    "니기미", "뒤질래", "딸딸이", "또라이", "때씹", "로리타", "몰카", "미친새끼",
    "바바리맨", "변태", "병신", "불알", "빠구리", "사까시", "쌍놈", "스와핑",
    "씨발", "씨발놈", "씨팔", "씹물", "씹빨", "씹새끼", "씹알", "씹창", "씹팔",
    "암캐", "야동", "야사", "야애니", "엄창", "염병", "옘병", "옘병할", "은꼴",
    "잡년", "종간나", "좆", "죽일년", "직촬", "짱깨", "쪽바리", "창녀", "포르노",
    "하드코어", "화냥년", "후레아들", "희쭈그리", "뙤놈",
    # 원본에 없지만 실사용 빈도가 높아 더한 것들. 정상어 충돌 없음을 아래 자체 점검이 지킨다.
    "지랄", "존나", "존내", "좆같", "개년", "썅년", "썅놈", "호로자식",
    # 초성체 — 정상 문장에는 자모만 이어지는 토막이 없다(Gate 1 이 먼저 잡기도 한다)
    "ㅅㅂ", "ㅆㅂ", "ㅄ", "ㅈㄴ", "ㅗ",
)

# ── 앞뒤가 한글이면 흘려보내는 항목 ───────────────────────────────────────────
# (패턴, 사유). 사유는 화면·로그에 쓰지 않고 이 파일을 읽는 사람을 위한 것이다.
BOUNDED: tuple[tuple[str, str], ...] = (
    ("자지", "선불전'자지'급수단 — 착오송금 안내의 핵심 용어라 부분 문자열은 금지"),
    ("시발", "'시발점'·'시발역'"),
    ("육갑", "'육십갑자'의 준말로도 쓰인다"),
    ("근친", "'근친혼'·'근친교배' 같은 학술 표기"),
)

# ── '미친' 은 결합형만 ────────────────────────────────────────────────────────
# "영향을 미친 사건"이 정상 문장이라 단독으로는 절대 쓸 수 없다. 욕으로 쓰일 때의 뒷말만 잡는다.
COMPOUND: tuple[str, ...] = (
    r"미친\s?(?:놈|년|새끼|자식|것|소리|짓)",
    r"뒈[지져]",
)

# ── 쓰지 않는 항목과 사유 ─────────────────────────────────────────────────────
# 표준 목록에 있지만 한국어 정상 문장과 겹치는 폭이 넓어 뺐다. 되돌리지 말 것.
DROPPED: dict[str, str] = {
    "씹": "'씹으면'(무시하다) — 평가셋 문항에 실재한다",
    "보지": "'…으로 보지 않습니다' — 코퍼스에 실재한다",
    "고자": "'-하고자' — 코퍼스·평가셋 양쪽에 실재한다",
    "호로": "'전화번호로'·'진양호로' — 조사·지명에 그대로 들어간다 (호로자식만 남김)",
    "후장": "증시 '후장(後場)' — 금융 도메인 정상어",
    "자위": "'자위권'·'자위 수단'",
    "유모": "'유모차'",
    "노모": "'노모(老母)'",
    "망가": "'망가지다'",
    "애자": "'장애자'·'애자(碍子)'",
    "에로": "'…에로의' 조사 결합",
    "거유": "'증거유무'·'근거 유무'",
    "미친": "'영향을 미친' — 결합형(COMPOUND)으로만 잡는다",
    "섹스": "성교육·통계 문맥의 정상 질의를 막을 수 있어 뺐다(성인물 표현은 다른 항목이 덮는다)",
    "쥐좆": "'좆'이 이미 부분 문자열로 잡는다",
    "좆만": "'좆'이 이미 부분 문자열로 잡는다",
}


def _bounded_re(word: str) -> re.Pattern:
    return re.compile(rf"(?<![가-힣]){re.escape(word)}(?![가-힣])")


_BOUNDED_RE = tuple((w, _bounded_re(w)) for w, _ in BOUNDED)
_COMPOUND_RE = tuple(re.compile(p) for p in COMPOUND)


def find(text: str) -> Optional[str]:
    """사전에 걸리는 첫 표현 -> str | None. 걸린 표현을 그대로 돌려준다(로그용).

    호출부는 api/rag/answer.py guardrail_hit 하나다. 여기서 예외를 던지지 않는다 —
    사전이 답변을 막는 일은 있어도, 사전 때문에 답변이 실패하지는 않아야 한다.
    """
    if not text:
        return None
    folded = str(text).casefold()
    for word in SUBSTRING:
        if word.casefold() in folded:
            return word
    for word, rx in _BOUNDED_RE:
        if rx.search(str(text)):
            return word
    for rx in _COMPOUND_RE:
        m = rx.search(str(text))
        if m:
            return m.group(0)
    return None


# ──────────────────────────────── 자체 점검 ────────────────────────────────
# `python3 api/rag/blocklist_ko.py` — 코퍼스·평가셋 전문에 오탐이 0인지, 실제 욕설은
# 걸리는지 본다. 사전을 고치면 반드시 다시 돌린다.
if __name__ == "__main__":
    import json
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]

    # ① 정상 텍스트에 단 한 건도 걸리면 안 된다 — 코퍼스 전문 + 평가셋 질문 전부
    corpus = [json.dumps(json.loads(line), ensure_ascii=False)
              for line in (root / "data/corpus.jsonl").open(encoding="utf-8")]
    questions = []
    for name in ("testset_all", "testset_pipeline"):
        path = root / f"data/testset/{name}.jsonl"
        questions += [json.loads(line).get("question", "") for line in path.open(encoding="utf-8")]

    false_positives = []
    for label, chunks in (("코퍼스", corpus), ("평가셋 질문", questions)):
        for chunk in chunks:
            hit = find(chunk)
            if hit:
                at = chunk.find(hit)
                false_positives.append(f"{label}: {hit!r} ← …{chunk[max(0, at - 30):at + 30]}…")

    # ② 일반 한국어에서 자주 문제가 되는 형태 — 사전을 넓힐 때 여기가 먼저 깨진다
    SAFE_SENTENCES = (
        "예금을 인출하고자 합니다", "전화번호로 문의드립니다", "선불전자지급수단도 대상인가요",
        "은닉재산으로 보지 않습니다", "지급명령을 씹으면 어떻게 하나요", "버스 시발점이 어디인가요",
        "코로나가 영향을 미친 기간의 이자는요", "유모차 구입비도 보호되나요", "노모 명의 예금은요",
        "서류가 망가졌어요", "장애자 등록증도 신분증인가요", "증거유무를 어떻게 확인하나요",
        "후장에 주가가 급락한 경우", "자위권 행사와 관련된 예금", "근친혼 관련 상속 예금",
    )
    for sentence in SAFE_SENTENCES:
        hit = find(sentence)
        if hit:
            false_positives.append(f"정상 문장: {hit!r} ← {sentence}")

    # ③ 실제로 잡아야 하는 것들
    misses = [s for s in (
        "씨발 이게 뭐야", "야 병신아 답변 똑바로 해", "지랄하지 말고 돈 내놔",
        "개새끼들아 예금 내놔", "존나 느리네", "미친놈들이 심사를 안 해줘",
        "ㅅㅂ 왜 안돼", "포르노 사이트 알려줘", "자지 사진 보여줘",
    ) if not find(s)]

    print(f"사전 크기 : 부분문자열 {len(SUBSTRING)} · 경계 {len(BOUNDED)} · 결합형 {len(COMPOUND)}"
          f" · 제외 {len(DROPPED)}")
    print(f"대조 대상 : 코퍼스 {len(corpus)}건 · 평가셋 질문 {len(questions)}건 · 정상 문장 {len(SAFE_SENTENCES)}건")
    if false_positives:
        print(f"\n❌ 오탐 {len(false_positives)}건")
        for line in false_positives[:20]:
            print("  ", line)
    if misses:
        print(f"\n❌ 놓친 욕설 {len(misses)}건: {misses}")
    if not false_positives and not misses:
        print("\n✅ 오탐 0 · 놓침 0")
