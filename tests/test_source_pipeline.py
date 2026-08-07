"""출처 부착 경로 빠른 검사 — HCX 호출 없이 판정·조립 로직만 검증한다(수 초).

파이프라인 코드(pipeline.py / prompt_builder.py)를 고치면 커밋 전에 이걸 먼저 돌린다:
python3 tests/test_source_pipeline.py

2026-08-03 롤백: 출처 부착 판정을 source_verifier(생성 후 코드 판정)에서 다시 LLM 자기보고
마커([SOURCE_USED]/[NO_SOURCE], prompt_builder._strip_no_source_marker)로 되돌리고,
source_verifier.py·train_source_verifier.py·data/source_verifier/를 삭제했다. 이슈 5에
기록된 마커의 내용 오표기(라벨 107건 중 근거 사용 답변 61건에서 33건 출처 누락)는 알려진
위험으로 감수하는 것이며 이 스크립트로는 잡히지 않는다 — 여기서 보는 건 마커의 파싱과
조립이 정확한지까지다.

과거 사고 재발 방지 케이스:
- 마커 형식 변형 미인식으로 마커가 본문에 노출 — 띄어쓰기·소문자는 이슈 3,
  괄호 안 공백·볼드·콜론은 이슈 5 후속 2
- 거절·인사에 무관한 출처 부착 (2026-07-24, docs/pipeline_issue_history.md 이슈 3)
- 복합 질문에서 앞 하위 답변이 뒤 답변의 출처를 지움 (이슈 4)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from prompt_builder import (  # noqa: E402  (sys.path 조정 후 import)
    _strip_no_source_marker, assemble_informational_answer,
)


def test_marker_parsing():
    """마커를 떼어낸 본문과 근거 사용 판정이 함께 나오는지. 형식 변형(밑줄/띄어쓰기,
    대소문자)까지 인식해야 마커 텍스트가 사용자에게 노출되지 않는다."""
    text, src = _strip_no_source_marker("[SOURCE_USED]\n신분증과 도장이 필요합니다.")
    assert src is True and text == "신분증과 도장이 필요합니다."

    text, src = _strip_no_source_marker("[NO_SOURCE]\n확인할 수 없습니다.")
    assert src is False and text == "확인할 수 없습니다."

    # 실제 재현된 변형 — 밑줄 대신 띄어쓰기(2026-07-30)
    text, src = _strip_no_source_marker("[SOURCE USED]\n안내드립니다.")
    assert src is True and "[" not in text, "띄어쓰기 변형 미인식 — 마커가 본문에 노출됨"

    text, src = _strip_no_source_marker("[no_source]\n안녕하세요.")
    assert src is False and "[" not in text, "소문자 변형 미인식"

    # 실제 재현된 변형 — 대괄호 안쪽 공백(이슈 5 라벨 수집 중 관측, 2026-08-03 대응).
    # 이 변형은 출처 누락과 마커 노출이 동시에 나던 자리다.
    text, src = _strip_no_source_marker("[ SOURCE USED ]\n안내드립니다.")
    assert src is True and "[" not in text, "괄호 안 공백 변형 미인식 — 출처 누락 + 마커 노출"

    text, src = _strip_no_source_marker("[ NO_SOURCE ]\n확인할 수 없습니다.")
    assert src is False and "[" not in text, "괄호 안 공백 변형에서 마커가 본문에 노출됨"

    # 볼드·콜론 표기 흔들림도 같은 계열
    text, src = _strip_no_source_marker("**[SOURCE_USED]**\n안내드립니다.")
    assert src is True and "[" not in text and "*" not in text, "볼드 변형 미인식"

    text, src = _strip_no_source_marker("[SOURCE_USED]:\n안내드립니다.")
    assert src is True and text == "안내드립니다.", "마커 뒤 콜론이 본문에 남음"

    # 마커가 아예 없으면 안전한 쪽(출처 미첨부)으로. 본문은 원문 그대로 둔다.
    text, src = _strip_no_source_marker("마커 없는 답변입니다.")
    assert src is False and text == "마커 없는 답변입니다."


def test_assemble():
    citations = [{"page_id": "p1", "breadcrumb": "안내", "title": "제목", "url": "https://x/1"}]
    with_src = assemble_informational_answer("[SOURCE_USED]\n답변입니다.", citations)
    assert "참고 출처" in with_src and "https://x/1" in with_src
    assert "[SOURCE_USED]" not in with_src, "마커가 본문에 노출됨"
    without = assemble_informational_answer("[NO_SOURCE]\n확인할 수 없습니다.", citations)
    assert "참고 출처" not in without and "https://x/1" not in without
    assert "[NO_SOURCE]" not in without, "마커가 본문에 노출됨"


def test_recheck_direction():
    """2026-08-03 — [NO_SOURCE] 판정만 재확인하고 [SOURCE_USED]는 절대 건드리지 않는지.

    마커의 오판은 [NO_SOURCE] 쪽에만 있었으므로(이슈 5), 맞고 있는 축까지 다시 물으면
    거절·인사에 무관한 출처가 붙는 문제가 되살아난다. 재확인 콜백이 호출되는 조건 자체를
    고정해 둔다."""
    citations = [{"page_id": "p1", "breadcrumb": "안내", "title": "제목", "url": "https://x/1"}]
    called = []

    def recheck(body):
        called.append(body)
        return True

    # [SOURCE_USED] — 재확인을 부르지 않고 그대로 출처 부착
    out = assemble_informational_answer("[SOURCE_USED]\n답변입니다.", citations, recheck=recheck)
    assert not called, "[SOURCE_USED]인데 재확인을 호출함 — 맞고 있는 축을 건드리면 안 됨"
    assert "참고 출처" in out

    # [NO_SOURCE] + 재확인이 '썼다' → 판정을 뒤집어 출처 부착(오표기 구제)
    out = assemble_informational_answer("[NO_SOURCE]\n반환 신청은 이렇게 합니다.", citations,
                                        recheck=recheck)
    assert called == ["반환 신청은 이렇게 합니다."], "재확인에 마커 뗀 본문이 넘어가야 함"
    assert "참고 출처" in out, "재확인이 '썼다'인데 출처가 안 붙음"

    # [NO_SOURCE] + 재확인도 '안 썼다' → 그대로 미부착(거절·인사 정상 동작 유지)
    out = assemble_informational_answer("[NO_SOURCE]\n확인할 수 없습니다.", citations,
                                        recheck=lambda body: False)
    assert "참고 출처" not in out, "재확인이 '안 썼다'인데 출처가 붙음"

    # 재확인 실패(예외)는 마커 판정 유지 — 이 기능이 죽어도 이전 동작으로 떨어질 뿐
    def boom(body):
        raise RuntimeError("LLM 호출 실패")

    from source_check import recheck_source_usage
    orig_call = sys.modules["source_check"].call_hyperclova
    try:
        sys.modules["source_check"].call_hyperclova = boom
        assert recheck_source_usage("반환 신청은 이렇게 합니다.", "근거 본문") is False, \
            "호출 실패가 True로 떨어짐 — 실패는 항상 안전한 쪽이어야 함"
    finally:
        sys.modules["source_check"].call_hyperclova = orig_call


def test_subanswer_independence():
    """이슈 4 회귀 — 협력자를 전부 가짜로 바꿔, 앞 하위 답변(미사용)이 뒤 하위 답변(사용)의
    출처를 지우지 않는지 확인한다."""
    import pipeline

    page = json.loads(open(ROOT / "data" / "corpus.jsonl", encoding="utf-8").readline())
    chunks = [(f"{page['page_id']}#0", 0.9, "본문")]
    orig = (pipeline.decompose_query, pipeline.classify_intent, pipeline.route_search_chunks,
            pipeline.call_hyperclova, pipeline.recheck_source_usage)
    try:
        pipeline.decompose_query = lambda q: ["질문1", "질문2"]
        pipeline.classify_intent = lambda q: "informational"
        pipeline.route_search_chunks = lambda q, k: chunks
        # ①이 [NO_SOURCE]라 재확인이 실제로 호출된다 — HCX를 타지 않도록 가짜로 막고,
        # '안 썼다'로 답하게 해 이 검사의 원래 시나리오(①은 출처 미부착)를 유지한다.
        pipeline.recheck_source_usage = lambda body, evidence: False
        # ① 근거 미사용(거절) → ② 근거 사용. 판정은 이제 마커가 하므로 답변에 직접 붙인다.
        answers = iter(["[NO_SOURCE]\n확인할 수 없습니다.",
                        "[SOURCE_USED]\n반환지원 제도로 신청하시면 됩니다."])
        pipeline.call_hyperclova = lambda p: next(answers)

        result = pipeline.rag_answer("복합 질문")
        first, _, second = result.partition("**질문2**")
        assert "참고 출처" not in first, "①(미사용)에 출처가 붙음"
        assert page["source_url"] in second, "②(사용)의 출처가 사라짐 — 이슈 4 재발!"
    finally:
        (pipeline.decompose_query, pipeline.classify_intent, pipeline.route_search_chunks,
         pipeline.call_hyperclova, pipeline.recheck_source_usage) = orig


if __name__ == "__main__":
    test_marker_parsing()
    test_assemble()
    test_recheck_direction()
    test_subanswer_independence()
    # em-dash 등 cp949에 없는 문자는 쓰지 않는다 - Windows 콘솔에서 UnicodeEncodeError로
    # 검사가 통과하고도 비정상 종료한다(2026-08-03 실제 발생).
    print("OK - 출처 부착 경로 검사 4종 통과")
