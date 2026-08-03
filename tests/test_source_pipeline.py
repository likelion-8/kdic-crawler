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
- 마커 형식 변형([SOURCE USED] 등) 미인식으로 마커가 본문에 노출 (이슈 3 후속)
- 거절·인사에 무관한 출처 부착 (2026-07-24, docs/pipeline_issues.md 이슈 3)
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


def test_subanswer_independence():
    """이슈 4 회귀 — 협력자를 전부 가짜로 바꿔, 앞 하위 답변(미사용)이 뒤 하위 답변(사용)의
    출처를 지우지 않는지 확인한다."""
    import pipeline

    page = json.loads(open(ROOT / "data" / "corpus.jsonl", encoding="utf-8").readline())
    chunks = [(f"{page['page_id']}#0", 0.9, "본문")]
    orig = (pipeline.decompose_query, pipeline.classify_intent, pipeline.route_search_chunks,
            pipeline.call_hyperclova)
    try:
        pipeline.decompose_query = lambda q: ["질문1", "질문2"]
        pipeline.classify_intent = lambda q: "informational"
        pipeline.route_search_chunks = lambda q, k: chunks
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
         pipeline.call_hyperclova) = orig


if __name__ == "__main__":
    test_marker_parsing()
    test_assemble()
    test_subanswer_independence()
    # em-dash 등 cp949에 없는 문자는 쓰지 않는다 - Windows 콘솔에서 UnicodeEncodeError로
    # 검사가 통과하고도 비정상 종료한다(2026-08-03 실제 발생).
    print("OK - 출처 부착 경로 검사 3종 통과")
