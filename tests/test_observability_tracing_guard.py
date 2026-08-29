"""테스트·평가 실행이 실사용 trace 를 오염시키지 않는지 확인한다.

2026-08-26 실측: `python -m pytest` 는 argv[0] 이 `.../pytest/__main__.py` 라 이름으로 못
잡혔고, 그 구멍으로 테스트 실행 45건이 실사용 trace 사이에 섞여 Langfuse 에 올라갔다
(request_id 가 "req", 질문이 "복합 질문" 인 것들). 관측을 끄는 판단은 observability 를
import 하는 시점에 한 번만 일어나므로, 그 결과를 여기서 확인한다.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "src"):
    sys.path.insert(0, str(p))

import observability  # noqa: E402,F401  (import 자체가 판단을 수행한다)


def test_tracing_is_off_while_tests_run():
    assert os.environ.get("LANGFUSE_TRACING_ENABLED") == "false", (
        "테스트 실행이 Langfuse 에 trace 를 남긴다 — observability 의 pytest 판별을 확인하라")


def test_explicit_opt_in_still_wins():
    """setdefault 라 명시값이 항상 이긴다 — 평가 실행을 굳이 Langfuse 로 보고 싶을 때의 통로."""
    import inspect
    src = inspect.getsource(observability)
    assert 'os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")' in src
    assert 'os.environ["LANGFUSE_TRACING_ENABLED"] = "false"' not in src


# ──────────────── 새 오프라인 진입점이 가드 밖에 생기지 않게 ────────────────

# 계측된 함수를 부르면서도 trace 를 남기는 게 맞는 실행 스크립트. pipeline.py 는 터미널
# 챗봇이라 일부러 남기고, 나머지 둘은 모듈 하단의 수동 확인용 __main__ 블록이다.
ALLOWED_TRACED_ENTRYPOINTS = {"src/pipeline.py", "src/query_decomposer.py", "src/query_planner.py"}

# observability 가 계측해 둔 함수들. 이 중 하나라도 부르는 실행 스크립트는 trace 를 만든다.
_INSTRUMENTED = ("route_search_chunks", "plan_query", "_answer_one",
                 "call_hyperclova", "regenerate_hyperclova", "classify_question_type")


def test_offline_entrypoints_stay_inside_the_guarded_directories():
    """계측 함수를 부르는 실행 스크립트가 crawler/ · eval/ 밖에 새로 생기면 여기서 걸린다.

    그대로 두면 그 실행이 실사용 trace 사이에 섞여 올라간다 — 2026-08-26 실측에서 전체
    trace 의 약 70%가 그렇게 쌓인 오프라인 실행 기록이었다. 새 폴더를 만들었으면
    observability._OFFLINE_DIRS 에 그 이름을 더하고 이 테스트를 통과시켜라."""
    offenders = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if '__name__ == "__main__"' not in text:
            continue
        if not any(name in text for name in _INSTRUMENTED):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED_TRACED_ENTRYPOINTS:
            continue
        if not (observability._OFFLINE_DIRS & set(path.relative_to(ROOT).parts)):
            offenders.append(rel)
    assert offenders == [], f"가드 밖의 오프라인 진입점: {offenders}"
