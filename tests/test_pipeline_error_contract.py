"""파이프라인 실패 코드 계약 — 워커가 내는 코드를 프론트가 모르면 실패 상세가 크래시한다.

2026-08-25 QA 에서 실제로 터졌다. 워커는 `STAGE_FAILED` 를 내는데 프론트 JobErrorCode 는
기획서 CM-DF-002 06절의 5종뿐이라 `JOB_ERROR_MESSAGE[code].replace(...)` 가
`undefined.replace` 로 화면을 통째로 날렸다. api/schemas/pipeline.py 의 JobError.code 가
str 이라 서버도 못 막는다 — 그래서 이 테스트가 두 파일을 직접 대조한다.

프론트는 모르는 코드를 INTERNAL 문구로 떨어뜨리는 폴백도 함께 갖췄지만(jobErrorMessage),
폴백은 '안 죽는다'는 보장일 뿐 '맞는 문구가 나온다'는 보장이 아니다. 코드를 새로 낼 때
codes.ts 를 같이 고치라는 신호가 여기다.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODES_TS = ROOT / "web/src/lib/codes.ts"
WORKER = ROOT / "src/worker.py"


def _frontend_codes() -> set[str]:
    """codes.ts 의 JOB_ERROR_MESSAGE 키 집합."""
    body = re.search(r"JOB_ERROR_MESSAGE: Record<JobErrorCode, string> = \{(.*?)\n\}",
                     CODES_TS.read_text(encoding="utf-8"), re.S)
    assert body, "codes.ts 에서 JOB_ERROR_MESSAGE 를 못 찾았다 — 이름이 바뀌었나?"
    return set(re.findall(r"^\s*([A-Z_]+):", body.group(1), re.M))


def _worker_codes() -> set[str]:
    """worker.py 가 error={"code": ...} 로 싣는 리터럴 집합."""
    found = set(re.findall(r'error=\{"code":\s*"([A-Z_]+)"', WORKER.read_text(encoding="utf-8")))
    assert found, "worker.py 에서 error={'code': ...} 를 못 찾았다 — 실패 경로가 바뀌었나?"
    return found


def test_worker_error_codes_are_known_to_frontend():
    unknown = _worker_codes() - _frontend_codes()
    assert not unknown, (
        f"워커가 내는 코드 {sorted(unknown)} 가 web/src/lib/codes.ts JobErrorCode 에 없다. "
        "추가하지 않으면 실패 상세가 '처리 중 오류가 발생했습니다'로만 뜬다.")


def test_stage_failed_carries_the_stage_placeholder():
    """STAGE_FAILED 문구는 {단계} 자리표시자를 가져야 한다 — 워커가 stage 를 함께 싣기 때문."""
    text = CODES_TS.read_text(encoding="utf-8")
    line = re.search(r"^\s*STAGE_FAILED:\s*'(.*)',\s*$", text, re.M)
    assert line, "codes.ts 에 STAGE_FAILED 문구가 없다"
    assert "{단계}" in line.group(1), "워커가 stage 를 싣는데 문구에 {단계} 자리가 없다"
