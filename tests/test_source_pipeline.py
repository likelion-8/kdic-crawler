"""출처 부착 경로 빠른 검사 — HCX 호출 없이 판정·조립 로직만 검증한다(수 초).

파이프라인 코드(pipeline.py / prompt_builder.py / source_verifier.py)를 고치면 커밋 전에
이걸 먼저 돌린다: python3 tests/test_source_pipeline.py

과거 사고 재발 방지 케이스:
- 근거로 답했는데 출처 누락 (마커 오표기, docs/pipeline_issues.md 이슈 5 → source_verifier로 대체)
- 거절·인사에 무관한 출처 부착 (2026-07-24, docs/pipeline_issues.md 이슈 3)
- 복합 질문에서 앞 하위 답변이 뒤 답변의 출처를 지움 (이슈 4)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from source_verifier import used_source  # noqa: E402  (sys.path 조정 후 import)
from prompt_builder import assemble_informational_answer  # noqa: E402


def _mtrs_context():
    for line in open(ROOT / "data" / "chunks_all.jsonl", encoding="utf-8"):
        d = json.loads(line)
        if d["chunk_id"].startswith("mtrs_gvbk_proc"):
            return d["text"]
    raise AssertionError("mtrs_gvbk_proc 청크가 코퍼스에 없음")


def test_verifier():
    ctx = _mtrs_context()
    grounded = ("친구에게 잘못 송금한 돈을 돌려받고 싶다면, 먼저 송금한 금융기관에 연락하여 "
                "착오송금 사실을 알리고, 만약 해결되지 않는다면 예금보험공사의 착오송금 반환지원 "
                "제도를 이용할 수 있습니다. 예금보험공사는 수취인에게 자진반환을 권유하고, "
                "미반환 시 법원의 지급명령을 통해 회수를 진행합니다.")
    # 마커 시절 5/5로 오표기되던 착오송금 실질 답변 — 반드시 '근거 사용'으로 판정돼야 한다
    assert used_source(grounded, ctx) is True
    assert used_source("문의하신 내용은 예금보험공사가 제공하는 정보의 범위를 벗어난 질문이라 "
                       "정확한 안내가 어렵습니다. 관련 기관에 문의하시길 권해드립니다.", ctx) is False
    assert used_source("제공된 자료에서 확인할 수 없습니다.", ctx) is False
    assert used_source("안녕하세요! 예금보험공사와 관련해 궁금하신 점이 있으시면 말씀해주세요.", ctx) is False


def test_assemble():
    citations = [{"page_id": "p1", "breadcrumb": "안내", "title": "제목", "url": "https://x/1"}]
    with_src = assemble_informational_answer("답변입니다.", citations, used_source=True)
    assert "참고 출처" in with_src and "https://x/1" in with_src
    without = assemble_informational_answer("확인할 수 없습니다.", citations, used_source=False)
    assert "참고 출처" not in without and "https://x/1" not in without


def test_subanswer_independence():
    """이슈 4 회귀 — 협력자를 전부 가짜로 바꿔, 앞 하위 답변(미사용)이 뒤 하위 답변(사용)의
    출처를 지우지 않는지 확인한다."""
    import pipeline

    page = json.loads(open(ROOT / "data" / "corpus.jsonl", encoding="utf-8").readline())
    chunks = [(f"{page['page_id']}#0", 0.9, "본문")]
    orig = (pipeline.decompose_query, pipeline.classify_intent, pipeline.route_search_chunks,
            pipeline.call_hyperclova, pipeline.used_source)
    try:
        pipeline.decompose_query = lambda q: ["질문1", "질문2"]
        pipeline.classify_intent = lambda q: "informational"
        pipeline.route_search_chunks = lambda q, k: chunks
        answers = iter(["확인할 수 없습니다.", "반환지원 제도로 신청하시면 됩니다."])
        pipeline.call_hyperclova = lambda p: next(answers)
        verdicts = iter([False, True])  # ① 미사용 → ② 사용
        pipeline.used_source = lambda a, c: next(verdicts)

        result = pipeline.rag_answer("복합 질문")
        first, _, second = result.partition("**질문2**")
        assert "참고 출처" not in first, "①(미사용)에 출처가 붙음"
        assert page["source_url"] in second, "②(사용)의 출처가 사라짐 — 이슈 4 재발!"
    finally:
        (pipeline.decompose_query, pipeline.classify_intent, pipeline.route_search_chunks,
         pipeline.call_hyperclova, pipeline.used_source) = orig


if __name__ == "__main__":
    test_verifier()
    test_assemble()
    test_subanswer_independence()
    print("OK — 출처 부착 경로 검사 3종 통과")
