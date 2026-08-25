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
  괄호 안 공백·볼드·콜론은 이슈 5-B
- 거절·인사에 무관한 출처 부착 (2026-07-24, docs/pipeline_issue_history.md 이슈 3)
- 복합 질문에서 앞 하위 답변이 뒤 답변의 출처를 지움 (이슈 4)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from prompt_builder import (  # noqa: E402  (sys.path 조정 후 import)
    FEW_SHOT_EXAMPLES, NO_EVIDENCE_NOTICE, OUT_OF_SCOPE_MESSAGE, SYSTEM_INSTRUCTION,
    _strip_no_source_marker, assemble_informational_answer, build_informational_prompt,
    strip_urls, with_retry_notice,
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

    # 2026-08-20(PR #174) 마커 지시를 프롬프트에서 뺐다 — 이제 마커가 없는 게 정상이다.
    # parse_marker 는 '모름'을 None 으로 구분하고, 하위호환 래퍼는 True 로 가정한다.
    # (판정 주체는 마커가 아니라 검색 게이트 + 사후검증이다.)
    text, src = _strip_no_source_marker("마커 없는 답변입니다.")
    assert src is True and text == "마커 없는 답변입니다."

    from prompt_builder import parse_marker
    text, marker = parse_marker("마커 없는 답변입니다.")
    assert marker is None and text == "마커 없는 답변입니다.", "'마커 없음'이 True 로 뭉개졌다"
    assert parse_marker("[NO_SOURCE]\n본문")[1] is False
    assert parse_marker("[SOURCE_USED]\n본문")[1] is True


def test_assemble():
    citations = [{"page_id": "p1", "breadcrumb": "안내", "title": "제목", "url": "https://x/1"}]
    with_src = assemble_informational_answer("[SOURCE_USED]\n답변입니다.", citations)
    assert "참고 출처" in with_src and "https://x/1" in with_src
    assert "[SOURCE_USED]" not in with_src, "마커가 본문에 노출됨"
    without = assemble_informational_answer("[NO_SOURCE]\n확인할 수 없습니다.", citations)
    assert "참고 출처" not in without and "https://x/1" not in without
    assert "[NO_SOURCE]" not in without, "마커가 본문에 노출됨"


def test_recheck_direction():
    """2026-08-14 팀 결정 반영 — 검증 콜백은 **모든 답변**에 대해 호출되고 마커 판정을
    양방향으로 오버라이드한다(source_check.validate_answer 1콜 통일). 종전의 "[NO_SOURCE]일
    때만 재확인, [SOURCE_USED]는 불가침" 규칙(2026-08-03)은 폐지됐다. 여기서는 콜백
    계약(항상 호출 · (본문, 마커_판정) 전달 · 결과가 최종 판정)을 고정한다."""
    citations = [{"page_id": "p1", "breadcrumb": "안내", "title": "제목", "url": "https://x/1"}]
    called = []

    def recheck(body, marker_used):
        called.append((body, marker_used))
        return True

    # [SOURCE_USED] — 이제 이 방향도 검증을 거친다(모든 답변 검증). '썼다' 유지 → 출처 부착
    out = assemble_informational_answer("[SOURCE_USED]\n답변입니다.", citations, recheck=recheck)
    assert called == [("답변입니다.", True)], "검증에 (마커 뗀 본문, 마커 판정)이 넘어가야 함"
    assert "참고 출처" in out

    # [NO_SOURCE] + 검증이 '썼다' → 판정을 뒤집어 출처 부착(오표기 구제)
    called.clear()
    out = assemble_informational_answer("[NO_SOURCE]\n반환 신청은 이렇게 합니다.", citations,
                                        recheck=recheck)
    assert called == [("반환 신청은 이렇게 합니다.", False)], "검증에 마커 뗀 본문이 넘어가야 함"
    assert "참고 출처" in out, "검증이 '썼다'인데 출처가 안 붙음"

    # [SOURCE_USED] + 검증이 '안 썼다' → 마커를 뒤집어 미부착(양방향 오버라이드)
    out = assemble_informational_answer("[SOURCE_USED]\n안녕하세요.", citations,
                                        recheck=lambda body, marker_used: False)
    assert "참고 출처" not in out, "검증이 '안 썼다'인데 마커 판정대로 출처가 붙음"

    # [NO_SOURCE] + 검증도 '안 썼다' → 그대로 미부착(거절·인사 정상 동작 유지)
    out = assemble_informational_answer("[NO_SOURCE]\n확인할 수 없습니다.", citations,
                                        recheck=lambda body, marker_used: False)
    assert "참고 출처" not in out, "검증이 '안 썼다'인데 출처가 붙음"

    # 검증 실패(예외)는 None(fail-open) — 호출부(pipeline._recheck)가 마커 판정을 유지한다.
    # 모킹 지점은 source_check._parse(2026-08-10 OpenAI structured output 교체 이후 동일).
    def boom(client, model, messages, schema=None):
        raise RuntimeError("LLM 호출 실패")

    from source_check import validate_answer
    orig_parse = sys.modules["source_check"]._parse
    try:
        sys.modules["source_check"]._parse = boom
        assert validate_answer("질문", "반환 신청은 이렇게 합니다.", "근거 본문") is None, \
            "호출 실패가 판정값으로 떨어짐 — 실패는 None(마커 유지 fail-open)이어야 함"
    finally:
        sys.modules["source_check"]._parse = orig_parse


def test_subanswer_independence():
    """이슈 4 회귀 — 협력자를 전부 가짜로 바꿔, 앞 하위 답변(미사용)이 뒤 하위 답변(사용)의
    출처를 지우지 않는지 확인한다.

    2026-08-09: 멀티쿼리 분해 + intent를 한 콜로 하는 query_planner.plan_query로 전환하면서,
    decompose_query/classify_intent 대신 plan_query를 가짜로 바꾼다(복합으로 분해 + 하위 intent를
    함께 반환). 하위 답변별 출처 독립 로직 자체는 그대로다."""
    import pipeline

    page = json.loads(open(ROOT / "data" / "corpus.jsonl", encoding="utf-8").readline())
    chunks = [(f"{page['page_id']}#0", 0.9, "본문")]
    orig = (pipeline.plan_query, pipeline.classify_question_type, pipeline.route_search_chunks,
            pipeline.call_hyperclova, pipeline.validate_answer)
    try:
        # 플래너가 복합으로 분해 + 하위 intent를 함께 준다(질문1·질문2, 둘 다 informational).
        pipeline.plan_query = lambda q: {"should_split": True, "items": [
            {"question": "질문1", "intent": "informational"},
            {"question": "질문2", "intent": "informational"}]}
        pipeline.classify_question_type = lambda q: "fact"   # 로깅용 — DB 안 타게 가짜로
        pipeline.route_search_chunks = lambda q, k: chunks
        # 2026-08-14부터 모든 답변이 검증(validate_answer)을 거친다 — LLM을 타지 않도록
        # None(판정 불가 = fail-open, 마커 판정 유지)으로 가짜를 세워 이 검사의 원래
        # 시나리오(①은 마커대로 미부착, ②는 마커대로 부착)를 유지한다.
        pipeline.validate_answer = lambda question, body, evidence: None
        # ① 근거 미사용(거절) → ② 근거 사용. 판정은 이제 마커가 하므로 답변에 직접 붙인다.
        answers = iter(["[NO_SOURCE]\n확인할 수 없습니다.",
                        "[SOURCE_USED]\n반환지원 제도로 신청하시면 됩니다."])
        pipeline.call_hyperclova = lambda p: next(answers)

        result = pipeline.rag_answer("복합 질문")
        first, _, second = result.partition("**질문2**")
        assert "참고 출처" not in first, "①(미사용)에 출처가 붙음"
        assert page["source_url"] in second, "②(사용)의 출처가 사라짐 — 이슈 4 재발!"
    finally:
        (pipeline.plan_query, pipeline.classify_question_type, pipeline.route_search_chunks,
         pipeline.call_hyperclova, pipeline.validate_answer) = orig


def test_url_backstop():
    """원칙 5(URL 쓰지 말 것)의 결정론적 백스톱 — 실측 4.0%(rag_runs 802건 중 32건)가 지시를
    어겼고 코퍼스에 없는 주소(https://www.kdic.or.kr/protect/apply.do)까지 7회 나갔다.

    전화번호·이메일은 반대로 **지우면 안 된다** — 골든셋 849문항 중 29건이 연락처가 곧 정답이고
    시스템이 뒤에 붙여주지도 않는다."""
    assert strip_urls("홈페이지(https://www.kdic.or.kr/protect/apply.do)에서 신청하세요.") \
        == "홈페이지에서 신청하세요.", "괄호 안 URL 제거 후 빈 괄호가 남음"
    assert "www." not in strip_urls("자세한 내용은 www.kdic.or.kr 를 참고하세요.")
    assert strip_urls("온라인 신청은 fins.kdic.or.kr에서 가능합니다.") == "온라인 신청은 가능합니다.", \
        "맨몸 도메인이 안 잡히거나 조사가 덩그러니 남음"

    keep = "신고센터 상담전화는 02-758-0102~04이며, 이메일은 cpreport@kdic.or.kr입니다."
    assert strip_urls(keep) == keep, "연락처가 지워짐 — 골든셋 29건이 이 형태의 정답이다"
    assert strip_urls("대표번호는 1588-0037입니다.") == "대표번호는 1588-0037입니다."

    # 조립 경로(pipeline)도 같은 백스톱을 거친다
    citations = [{"page_id": "p1", "breadcrumb": "안내", "title": "제목", "url": "https://x/1"}]
    out = assemble_informational_answer("자세한 내용은 https://www.kdic.or.kr 참고.", citations)
    body, _, sources = out.partition("**참고 출처**")
    assert "kdic.or.kr" not in body, "본문 URL 이 그대로 나감"
    assert "https://x/1" in sources, "붙여준 출처까지 지워짐"


def test_refusal_wording_is_single():
    """거절 문구가 하나뿐인지 — 생성 지시(원칙 1·few-shot·NO_EVIDENCE_NOTICE)와 사후 교체문
    (api/rag/answer.py)이 서로 다른 문구를 내보내면 사용자에겐 같은 상황이 여러 얼굴로 보인다."""
    from api.rag.answer import OUT_OF_SCOPE_MESSAGE as web_message
    assert web_message == OUT_OF_SCOPE_MESSAGE, "웹 경로가 다른 거절 문구를 쓴다"
    assert OUT_OF_SCOPE_MESSAGE in SYSTEM_INSTRUCTION, "시스템 지시문이 표준 거절 문구를 안 준다"
    assert OUT_OF_SCOPE_MESSAGE in NO_EVIDENCE_NOTICE
    assert FEW_SHOT_EXAMPLES[-1]["answer"] == OUT_OF_SCOPE_MESSAGE
    assert "제공된 자료에서 확인할 수 없습니다" not in SYSTEM_INSTRUCTION, \
        "내부 구현(RAG 근거)을 드러내는 옛 거절 문구가 남아 있다"
    # 평가의 거절 판정이 이 문구를 계속 거절로 세는지(문구를 고치면 같이 깨진다)
    from eval.eval_pipeline_generation import is_refused
    assert is_refused(OUT_OF_SCOPE_MESSAGE), "평가가 표준 거절문을 거절로 못 센다"


def test_retry_notice_anchor():
    """재생성 문구는 **실제 질문 바로 앞**에 들어가야 한다. 사용자가 질문에 "질문: "을 적으면
    rfind("질문: ") 방식은 문구를 질문 한가운데 박아 넣었다."""
    q = "질문: 보호한도 얼마야"          # 사용자가 직접 적은 "질문: "
    prompt = build_informational_prompt(q, [("c1", 0.9, "근거 본문")])
    pushed = with_retry_notice(prompt, q, "(재확인)\n")
    human = pushed[-1][1]
    assert f"(재확인)\n질문: {q}" in human, "문구가 실제 질문 앞이 아닌 곳에 들어갔다"
    assert human.count("(재확인)") == 1
    # 앵커를 못 찾으면 원본 그대로 — 재생성이 죽지 않는다
    assert with_retry_notice(prompt, "없는 질문", "(재확인)\n") == prompt


if __name__ == "__main__":
    test_marker_parsing()
    test_assemble()
    test_recheck_direction()
    test_subanswer_independence()
    test_url_backstop()
    test_refusal_wording_is_single()
    test_retry_notice_anchor()
    # em-dash 등 cp949에 없는 문자는 쓰지 않는다 - Windows 콘솔에서 UnicodeEncodeError로
    # 검사가 통과하고도 비정상 종료한다(2026-08-03 실제 발생).
    print("OK - 출처 부착 경로 검사 7종 통과")
