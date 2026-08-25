"""서비스명은 한 이름이어야 한다 — 화면은 '예솜24'인데 기본 프롬프트는 '예솜'이었다(2026-08-25 QA).

게시된 프롬프트(prompt_versions)가 없을 때는 이 기본 프롬프트가 그대로 쓰여서, 정체성 질문
("너는 누구야")에 화면 브랜드와 다른 이름을 답한다.

정본은 web/index.html 의 <title> 이다(00-meta 1.3 "AI챗봇 예솜24"). 코드 상수 두 개를
비교하면 둘 다 같이 틀렸을 때 통과해 버리므로, 화면이 실제로 그리는 값에서 읽는다.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

import prompt_builder  # noqa: E402

SERVICE_NAME = re.search(
    r"<title>(.+?)</title>", (ROOT / "web/index.html").read_text(encoding="utf-8")).group(1)


def test_system_prompt_uses_the_service_name():
    assert SERVICE_NAME == "예솜24", "정본이 바뀌었으면 아래 검사도 함께 보라"
    assert f'"{SERVICE_NAME}"' in prompt_builder.SYSTEM_INSTRUCTION


def test_identity_answer_uses_the_service_name():
    """정체성 few-shot 이 옛 이름을 그대로 들고 있으면 모델이 그 이름으로 답한다."""
    identity = next(e for e in prompt_builder.FEW_SHOT_EXAMPLES if "누구야" in e["question"])
    assert SERVICE_NAME in identity["answer"]


def test_no_bare_old_name_remains():
    """'예솜24' 가 아닌 맨 '예솜' 이 남아 있으면 한 답변 안에서 이름이 갈린다."""
    text = prompt_builder.SYSTEM_INSTRUCTION + "".join(
        e["answer"] for e in prompt_builder.FEW_SHOT_EXAMPLES)
    assert not re.search(r"예솜(?!24)", text)
