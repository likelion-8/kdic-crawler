"""대화 로그·피드백 텍스트 마스킹 — 4종 구현(2026-08-13).

대상은 팀 결정 그대로 **주민등록번호 · 전화번호 · 카드번호 · 이메일** 4종뿐이다.
계좌번호는 제외한다(팀 결정) — 한국 계좌번호는 자릿수가 은행마다 달라 정규식으로 잡으면
"5천만원"·"1332"(내선)·"2024-03-15"(날짜) 같은 답변의 핵심 숫자까지 잡아먹는다.

조회 시점 마스킹이다 — rag_runs.question/answer 는 원문으로 저장되고(src/schema.py),
AD-005 조회 API(admin_logs.py)가 응답을 만들 때 이 함수를 거친다. 저장 시점 마스킹으로
바꾸려면 이 함수를 저장 경로에 그대로 옮기면 된다(시그니처 유지).

패턴 원칙: **오탐보다 미탐을 감수한다.** 금액·기한이 답변의 핵심인 서비스라
일반 숫자를 집어삼키는 패턴(느슨한 자릿수 매칭)은 금지. 각 패턴은 구분자·접두 문맥이
뚜렷한 형태만 잡는다.
"""
import re
from typing import Optional

# 주민등록번호: 6자리-7자리, 뒷자리 첫 숫자 1~8 (YYMMDD-#######)
_RRN = re.compile(r"\b\d{2}[01]\d[0-3]\d[-–]\s?[1-8]\d{6}\b")
# 전화번호: 01X-XXXX-XXXX · 0XX-XXX(X)-XXXX · 15XX-XXXX (구분자 필수 — 구분자 없는 11자리는
# 사업자·문서번호 오탐이 있어 잡지 않는다)
_PHONE = re.compile(r"\b(01[016789][-.\s]\d{3,4}[-.\s]\d{4}"
                    r"|0\d{1,2}[-.\s]\d{3,4}[-.\s]\d{4}"
                    r"|1[5-9]\d{2}[-.\s]\d{4})\b")
# 카드번호: 4-4-4-4 구분자 있는 형태만 (구분자 없는 16자리는 금액·식별자 오탐 위험)
_CARD = re.compile(r"\b\d{4}[-\s]\d{4}[-\s]\d{4}[-\s]\d{4}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")

_RULES = (
    (_RRN, "[주민등록번호 마스킹]"),
    (_CARD, "[카드번호 마스킹]"),       # 카드(4-4-4-4)를 전화보다 먼저 — 전화 패턴과 일부 겹친다
    (_PHONE, "[전화번호 마스킹]"),
    (_EMAIL, "[이메일 마스킹]"),
)


def _published_rules() -> list:
    """게시본(prompt.guardrails.masking)의 활성 규칙 → [(compiled, replacement)].
    읽기 실패·정규식 오류는 그 규칙만 건너뛴다 — 마스킹이 예외로 죽어 로그 화면이 통째로
    안 뜨는 것보다, 규칙 하나가 빠지는 쪽이 낫다."""
    try:
        from runtime_config import get_prompt
        block = (get_prompt("guardrails", None) or {}).get("masking") or {}
        if not block.get("active", True):
            return []
        out = []
        for item in block.get("items") or []:
            if not isinstance(item, dict) or not item.get("active", True):
                continue
            pat = str(item.get("pattern") or "").strip()
            if not pat:
                continue
            try:
                out.append((re.compile(pat), str(item.get("replacement") or "[마스킹]")))
            except re.error:
                continue
        return out
    except Exception:  # noqa: BLE001
        return []


def mask_text(value: Optional[str]) -> Optional[str]:
    """개인정보를 대체 문구로 치환한다 — 고정 4종 + 게시된 활성 규칙. None 은 None 그대로.

    호출부(admin_logs.py 등)는 이 함수 하나만 거치면 된다 — 시그니처는 스텁 시절과 동일해
    기존 배선이 그대로 산다."""
    if value is None:
        return None
    masked = value
    for pattern, repl in _RULES:
        masked = pattern.sub(repl, masked)
    for pattern, repl in _published_rules():
        masked = pattern.sub(repl, masked)
    return masked


if __name__ == "__main__":
    # ponytail: 프레임워크 없는 최소 자가 점검 — 이 로직이 깨지면 여기서 먼저 죽는다
    cases = {
        "제 번호는 010-1234-5678 이에요": "제 번호는 [전화번호 마스킹] 이에요",
        "주민번호 900101-1234567 입니다": "주민번호 [주민등록번호 마스킹] 입니다",
        "카드 1234-5678-9012-3456 로 결제": "카드 [카드번호 마스킹] 로 결제",
        "메일 kim.chulsu+kdic@example.co.kr 로 답장": "메일 [이메일 마스킹] 로 답장",
        # 미탐 감수 원칙 — 핵심 숫자는 건드리지 않는다
        "보호한도는 1억원(100,000,000원)이고 신청은 2024-03-15까지": None,
        "안내 전화 1588-0037 로 문의": "안내 전화 [전화번호 마스킹] 로 문의",
    }
    for src, want in cases.items():
        got = mask_text(src)
        assert got == (want or src), f"{src!r} -> {got!r} (want {want or src!r})"
    assert mask_text(None) is None
    print("masking self-check ok")
