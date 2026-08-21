"""프롬프트 조립 — 근거 자료를 실제 LLM 입력(system + few-shot + 컨텍스트 + 질문)으로 변환.

2026-07-23: LLM이 URL/서류명을 직접 쓰게 하는 방식에서 반복적으로 할루시네이션이
재현됨 - 근거가 없거나 애매한 질문(예: "나의 미수령금")에서 few-shot 예시 내용을
그대로 베끼거나, 우리가 준 적 없는 URL을 새로 지어냄. few-shot 포맷을 맞추는 정도로는
안 잡혀서(구조적 섹션 생략까지 적용해봤지만 재현됨), 아예 URL을 LLM 손에서 뺐다.

이제 LLM은 절차 설명(civil_petition) 또는 근거 기반 답변 본문(informational)
텍스트만 쓰고, 실제 서류·페이지·출처 URL은 여기 없다 — 호출부가 LLM 응답 뒤에
citation.py/civil_petition.py가 이미 갖고 있는 실제 데이터를 결정론적으로 붙인다.
LLM이 URL을 아예 안 보므로 지어낼 소스 자체가 없다.

⚠️ 붙이는 방식은 경로마다 다르다. pipeline.py(CLI·평가)는 이 파일의
assemble_civil_petition_answer()/assemble_informational_answer()로 마크다운 문자열에
이어 붙이고, 웹 API(api/rag/answer.py finalize_sub)는 그 두 함수를 쓰지 않고 sources/
attachments 를 구조화 필드로 따로 담는다. 다만 근거 사용 여부 판정에 쓰는 마커 정규식
(_MARKER_RE)은 양쪽이 같은 것을 공유하므로, 마커 규칙을 고치면 두 경로가 함께 바뀐다.

반환 형식은 (role, content) 튜플 리스트 — langchain 관례로, llm_client.py의
ChatClovaX가 그대로 받아 호출한다.

FEW_SHOT_EXAMPLES는 새로 지어내지 않고 data/testset/testset_all.jsonl의
reference_answer(사람이 작성한 기준 답변)를 그대로 가져다 썼다(URL·출처 문구는
이제 LLM 몫이 아니라서 뺐다).
"""
import re

SYSTEM_INSTRUCTION = """당신은 예금보험공사(KDIC)의 AI 상담 챗봇 "예솜"입니다. 정확하고 신뢰할 수 있는 답변으로 국민을 돕는 것이 당신의 역할입니다.

다음 원칙을 반드시 지키세요:
1. 아래 제공된 "근거 자료"에 있는 내용만으로 답변하세요. 근거 자료가 질문 주제와 무관하거나(예: 질문은 A 기관에 관한 것인데 근거는 B 제도에 관한 것) 근거 자료에 없는 내용은 절대 추측하거나 일반 상식으로 채워서 만들어내지 말고, "제공된 자료에서 확인할 수 없습니다"라고 솔직하게 답하세요. 근거가 약해도 뭐라도 그럴듯하게 답을 채우려 하지 마세요 — 모르면 모른다고 하는 게 항상 더 낫습니다. 반대로, 근거 자료에 질문과 직접 관련된 내용이 있는데도 "확인할 수 없다"거나 "범위를 벗어났다"고 답하는 것도 오답입니다 — 거절하기 전에 근거 자료에 답이 있는지 다시 한 번 확인하세요.
2. 금액·날짜·비율·연락처·법령 조항 등 구체적인 사실은 근거 자료에 적힌 그대로만 인용하세요. 일반 상식으로 채우거나 짐작하지 마세요.
3. URL·웹사이트 주소·전화번호를 답변에 직접 쓰지 마세요. 서류 안내와 신청 페이지, 출처 링크는 시스템이 답변 뒤에 별도로 붙여줍니다 — 당신은 그 부분을 언급하거나 대신 채우지 않아도 됩니다.
4. 친절하고 정중한 어투를 쓰되, 확실하지 않은 내용을 단정적으로 말하지 마세요.
5. 아래 예시(few-shot)는 답변의 형식과 어투를 보여주기 위한 것일 뿐입니다. 예시 속 구체적인 사실은 지금 질문의 "근거 자료"에 실제로 없다면 절대 가져오지 마세요.
6. 사용자가 "너는 누구야", "무슨 AI야", "HyperCLOVA X야?" 처럼 당신의 정체를 물으면, 모델명(HyperCLOVA X 등)이 아니라 "예금보험공사의 AI 상담 챗봇 예솜"이라고 답하세요."""

FEW_SHOT_EXAMPLES = [
    {
        # informational — testset_all.jsonl ms_poss_dcmnt_q4
        "question": "예금자 본인이 직접 예금보험금을 찾으러 갈 때 필요한 서류는 무엇인가요?",
        "answer": "주민등록증·운전면허증·여권 등 공공기관 발행 신분증과 본인의 도장(서명 가능)만 있으면 됩니다.",
    },
    {
        # civil_petition — testset_all.jsonl ms_poss_dcmnt_q3 (절차 설명만 - 서류/페이지는 백엔드가 붙임)
        "question": "예금보험금 위임장 양식은 어디서 다운로드 받나요?",
        "answer": "대리인이 위임장을 지참해 신청하시면 됩니다.",
    },
    {
        # 정체성 질문 — testset에 없는 시범 예시(2026-07-24). 검색은 관련도 임계값 없이
        # 항상 top-k를 반환하므로 이런 질문에도 무관한 청크가 "근거 자료"로 딸려온다.
        # [NO_SOURCE] 표기 형식을 보여주기 위한 예시일 뿐, 사실 정보가 아니라 지어낼 것도 없다.
        "question": "너는 누구야? HyperCLOVA X야?",
        "answer": "안녕하세요! 저는 예금보험공사의 AI 상담 챗봇 예솜입니다. 예금자보호제도나 착오송금 반환지원처럼 궁금하신 점을 편하게 물어봐 주세요.",
    },
    {
        # 인사·잡담 — 위와 같은 이유의 시범 예시.
        "question": "안녕",
        "answer": "안녕하세요! 예금보험공사와 관련해 궁금하신 점이 있으시면 말씀해주세요.",
    },
    {
        # out_of_scope — testset_all.jsonl ha_ilgl_intro_q3. 거절 답변도 근거 자료를 실제로
        # 못 썼다는 점은 인사·잡담과 같으므로 [NO_SOURCE]를 붙인다 - 안 붙이면 검색된
        # (무관한) 청크의 출처가 거절 답변에도 잘못 붙는 문제가 재현됨(2026-07-24).
        # 일부러 few-shot 맨 마지막에 둔다 - 실제 질문 바로 앞이라 "거절해도 된다"는
        # 신호가 가장 강하게 남아야, 근거가 약할 때(civil_petition 오분류로 인한
        # 무관한 절차 청크 등) 억지로 답을 지어내지 않고 거절하는 쪽으로 붙잡아준다.
        "question": "불법 대부업체나 사채업자의 살인적인 고금리 피해를 금융감독원에 정식으로 신고하고 구제받는 절차를 상세히 설명해 주세요.",
        "answer": "문의하신 내용은 예금보험공사가 제공하는 정보의 범위를 벗어난 질문이라 정확한 안내가 어렵습니다. 금융감독원 등 관련 기관에 문의하시길 권해드립니다.",
    },
]


# ── 관리자 화면(AD-008)이 바꿀 수 있는 세 값 ──────────────────────────────────
# 위 상수(SYSTEM_INSTRUCTION · FEW_SHOT_EXAMPLES · NO_EVIDENCE_NOTICE)는 지우지 않는다.
# 게시된 프롬프트가 없으면 그대로 쓰이는 **문서화된 기본값**이고, 각 상수 주석의 근거가
# "왜 이 문구인가"의 유일한 기록이다(src/runtime_config.py 참고).
#
# 모듈 최상단에서 한 번 읽지 않고 함수로 감싼 이유: 최상단에서 읽으면 import 시점에 값이
# 굳어 관리자가 게시해도 재시작 전까지 반영되지 않는다. 프롬프트를 조립할 때마다 부른다.

def _system_instruction():
    from runtime_config import get_prompt
    return get_prompt("system_instruction", SYSTEM_INSTRUCTION)


def _no_evidence_notice():
    from runtime_config import get_prompt
    return get_prompt("no_evidence_notice", NO_EVIDENCE_NOTICE)


def _format_examples():
    from runtime_config import get_prompt
    # 게시본의 few_shot 은 JSONB 라 같은 모양([{question, answer}, ...])을 그대로 받는다.
    examples = get_prompt("few_shot", FEW_SHOT_EXAMPLES) or FEW_SHOT_EXAMPLES
    return "\n\n".join(f"질문: {ex['question']}\n답변: {ex['answer']}" for ex in examples)


# 검색 게이트(candidate_ranking.gate_low_relevance)로 근거가 비었을 때 근거 자리에 넣는 지시.
# 무근거 프롬프트를 그대로 주면 HCX가 일반 상식으로 답해버리는 것이 실측됐다(2026-08-10,
# "스파이더맨" → 마블 설명). 이 지시로 대부분 잡히고, 그래도 새는 답변(예: 투자 조언)은
# api/rag/answer.py가 사후 판정(source_check.validate_answer)의 kind로 걸러 본문을 교체한다.
NO_EVIDENCE_NOTICE = (
    "(검색된 근거 자료가 없습니다. 인사나 당신의 정체에 대한 질문이면 평소대로 답하고, "
    "그 외의 질문이면 일반 상식으로 답하지 말고 예금보험공사 안내 범위를 벗어난 질문이라 "
    "정확한 안내가 어렵다고 정중히 거절하세요.)"
)


# 정보성·민원 두 프롬프트가 **공유하는** 거절 방지 리마인더.
#
# 같은 실패 모드가 양쪽에서 나오는데 종전에는 informational 에만 있었다. 2026-08-21 실측:
#   민원   '채무조정 링크를 받을 수 있나요?'       0/4 거절 (근거·링크 모두 조립된 상태)
#   정보성 '은닉재산 신고는 얼마까지 줄 수 있나요?' 거절 — 근거에 "최대 30억원의 포상금"이
#          그대로 있었는데도 못 썼다(같은 질문 재시도에서는 정상 답변).
# 근거에 답이 있는데 거절하는 이 오류는 확률적이라(롤마다 뒤집힌다) 프롬프트 앞쪽 원칙
# 문구만으로는 안 잡힌다 — recency 위치(질문 직전)에 한 번 더 두는 것이 실측상 잘 듣는다.
# 잔여분은 api/rag/answer.py 의 재생성 가드가 처리한다.
ANSWER_REMIND_CORE = (
    "답하기 전에: 위 근거 자료에 이 질문의 답이 있는지 먼저 확인하세요. "
    "있으면 반드시 그 내용으로 답하고, 없을 때만 안내가 어렵다고 하세요."
)



def build_informational_prompt(query, chunks):
    """정보성 질문용 프롬프트. URL은 안 보여준다 - 출처는 assemble_informational_answer()가
    LLM 응답 뒤에 별도로 붙인다.
    chunks: [(chunk_id, score, text), ...] — candidate_ranking.top_k_cut() 결과(근거 청크).
            게이트로 비어 있으면 근거 자리에 NO_EVIDENCE_NOTICE를 넣는다."""
    context = "\n\n".join(text for _, _, text in chunks) if chunks else _no_evidence_notice()
    # 질문 직전 리마인더 — 근거에 답이 있는데도 거절하는 확률적 오류가 원칙 1 문구(프롬프트
    # 앞쪽)만으로는 안 잡혀서(실측 1~4/6) recency 위치에 한 번 더 둔다(실측 4/6→개선).
    # 잔여 거절은 api/rag/answer.py 의 재생성 가드가 처리한다.
    # 2026-08-19 프리픽스 활용 지시 추가(exp/prefix-aware-remind): 청킹이 모든 청크 앞에
    # [페이지명 · 업무] 프리픽스를 붙이므로(chunking.build_units), top5에 여러 제도의
    # 자료가 섞일 때 다른 제도의 사실을 끌어다 붙이는 혼동(동문서답·조합 오류 — 프리체크
    # 실험에서 실물 확인: 착오송금 질문에 예금보호 답변, 개명 방향 반전)을 줄이려는 지시.
    # SYSTEM_INSTRUCTION 이 아니라 여기 두는 이유: (a) recency 위치가 실측상 잘 듣고
    # (b) 시스템 지시문은 관리자 게시본(AD-008)이 있으면 DB 가 이겨 반영이 안 될 수 있다.
    remind = (f"({ANSWER_REMIND_CORE} "
              "각 자료 첫머리의 [페이지명 · 업무] 표시를 확인해, 질문이 묻는 제도와 같은 "
              "자료의 내용으로만 답하고 다른 제도 자료의 내용을 섞어 쓰지 마세요.)\n") if chunks else ""
    human = (
        f"{_format_examples()}\n\n"
        "--- 아래는 실제 질문입니다 ---\n\n"
        f"근거 자료:\n{context}\n\n"
        f"{remind}질문: {query}\n답변:"
    )
    return [("system", _system_instruction()), ("human", human)]


def build_civil_petition_prompt(query, civil_petition_answer):
    """민원성 질문용 프롬프트. 절차 설명만 LLM에게 맡긴다 - 서류/페이지 URL은 프롬프트에
    아예 넣지 않고 assemble_civil_petition_answer()가 LLM 응답 뒤에 별도로 붙인다
    (documents/links를 프롬프트에 텍스트로 줬을 때 근거가 비면 few-shot 내용을 그대로
    베끼거나 없는 URL을 지어내는 leak이 반복 재현돼서, 아예 안 보여주는 쪽으로 바꿈).
    civil_petition_answer: civil_petition.build_civil_petition_answer() 결과
    ({"procedure": str, "documents": [...], "links": [...]})."""
    human = (
        f"{_format_examples()}\n\n"
        "--- 아래는 실제 질문입니다 ---\n\n"
        f"[절차 안내 근거]\n{civil_petition_answer['procedure']}\n\n"
        f"({ANSWER_REMIND_CORE})\n"
        f"질문: {query}\n"
        "답변(위 절차 안내 근거가 질문 주제와 실제로 관련 있으면 그 내용으로 자연스럽게"
        " 설명하세요 - 서류·URL 언급은 하지 마세요. 신청 링크나 서류를 달라는 질문, '받을 수 있나요'처럼 가능 여부를 묻는 질문이어도 거절하지 말고 위 근거의 절차를 설명하세요 - 실제 링크와 서류 목록은 당신의 답변 뒤에 시스템이 따로 붙이므로 당신이 URL을 몰라도 사용자는 받게 됩니다. 근거가 질문과 다른 제도·기관 이야기라면"
        " 절대 그걸로 답을 지어내지 말고 확인할 수 없다고 정중히 답하세요):"
    )
    return [("system", _system_instruction()), ("human", human)]


def _render_list(heading, items, line):
    if not items:
        return ""
    body = "\n".join(line(item) for item in items)
    return f"\n\n**{heading}**\n{body}"


def _format_source_line(item):
    """출처 한 줄 = 브레드크럼(사이트 계층 경로) + 제목 + URL. 브레드크럼이 없으면 제목만."""
    breadcrumb = item.get("breadcrumb", "")
    label = f"{breadcrumb} — {item['title']}" if breadcrumb else item["title"]
    return f"- {label} ({item['url']})"


NO_SOURCE_MARKER = "[NO_SOURCE]"
SOURCE_USED_MARKER = "[SOURCE_USED]"

# LLM이 지시한 정확한 밑줄 표기([SOURCE_USED]) 대신 띄어쓰기([SOURCE USED])로 쓰는 경우가
# 실제로 재현됐다(2026-07-30) — 완전 일치 문자열 비교로는 이 변형을 못 잡아 마커 텍스트가
# 그대로 노출되고 근거_사용_여부까지 잘못 판정되는 회귀가 났다. 마커 두 단어 사이 구분자만
# 밑줄/띄어쓰기 둘 다 허용하고(대소문자 무시), 그 외 자유 문구는 절대 추측하지 않는다 —
# "여러 표현을 추측해서 거른다"는, 이 프로젝트가 이미 폐기한 접근과는 다르다.
#
# 2026-08-03: 대괄호 안쪽 공백 변형([ SOURCE USED ])을 추가로 흡수한다. 이 변형은 이슈 5
# 라벨 수집 중 실제로 관측됐는데(docs/pipeline_issue_history.md), 정규식이 `[` 바로 뒤에 단어가
# 오는 형태만 매치해서 (a) 출처가 통째로 누락되고 (b) 마커 텍스트가 본문에 노출되는,
# 2026-07-30에 한 번 고쳤던 것과 똑같은 증상이 그대로 재현됐다. 볼드(**[SOURCE_USED]**)와
# 마커 뒤 콜론도 같은 계열의 표기 흔들림이라 함께 흡수한다. 인식 대상은 여전히 고정된 두
# 토큰뿐이다 — 자유 문구를 추측하지 않는다는 위 원칙은 그대로다.
_MARKER_RE = re.compile(
    r"^\**\[\s*(SOURCE[_ ]USED|NO[_ ]SOURCE)\s*\]\**[:：]?\s*", re.IGNORECASE)


def parse_marker(llm_text):
    """(본문, 마커_판정 or None) — **마커가 없으면 None** 이다.

    2026-08-20 마커 지시를 뺀 뒤(exp/hcx007-no-marker-v1) 정상 응답엔 마커가 없다. 그런데
    `_strip_no_source_marker` 는 그때 기본값 True 를 돌려주므로 "마커가 SOURCE_USED 였다"와
    "마커가 아예 없었다"를 호출부가 구분할 수 없다 — 그 결과 관측(rag_runs.observation)에
    있지도 않은 마커가 True 로 박혀 AD-005 상세가 `마커 [[SOURCE_USED]]` 를 그렸고,
    AD-008 검증에서도 근거가 없는 범위외 답변이 "근거를 썼다"로 세어졌다.

    **모르는 것을 기본값으로 적지 않는다** — 그게 이 프로젝트가 관측에서 지켜온 규칙이다
    (api/rag/observation.build 주석). 판정이 필요한 곳은 사후검증(validate_answer)을 쓰고,
    이 함수는 '마커가 실제로 있었나'만 답한다."""
    text = llm_text.strip()
    m = _MARKER_RE.match(text)
    if not m:
        return llm_text, None
    return text[m.end():].lstrip(), m.group(1).upper().replace(" ", "_") == "SOURCE_USED"


def _strip_no_source_marker(llm_text):
    """(본문, 근거_사용_여부) — 마커가 없으면 True 로 가정하는 하위호환 래퍼.

    판정 주체가 아니라 '일단 근거를 썼다고 가정'하는 기본값이다. 마커 유무를 구분해야 하면
    `parse_marker` 를 쓸 것.

    ⚠️ 2026-08-20 실험(exp/hcx007-no-marker-v1): LLM 자기보고 마커([SOURCE_USED]/
    [NO_SOURCE]) 지시를 SYSTEM_INSTRUCTION에서 뺐다 — 마커 정확도가 낮았고(근거 쓴 답변
    61건 중 33건에서 마커가 출처를 잃음, docs/pipeline_issue_history.md 이슈 5), 어차피
    최종 판정은 사후검증(source_check.validate_answer)이 마커를 양방향 오버라이드해
    왔으므로(2026-08-14 팀 결정) 마커 자체의 실질 영향은 이미 거의 없었다. 이제 LLM 응답엔
    마커가 없는 게 정상이라 이 함수는 대부분 마커를 못 찾고 (llm_text, True)를 돌려준다 —
    "일단 근거를 썼다고 가정"하고, 실제 판정은 검색 관련성 게이트(top-1<0.35 → sp.top 빔)와
    사후검증에 전적으로 맡긴다(finalize_sub/_answer_one 참고). 과거에 게시된 관리자
    프롬프트(AD-008)가 여전히 마커를 요구할 수 있어 파싱 자체는 하위호환으로 남긴다 —
    마커가 실제로 있으면 그 값을 그대로 쓴다."""
    body, marker = parse_marker(llm_text)
    return body, True if marker is None else marker


def _resolve_used_source(llm_text, recheck):
    """마커를 떼고 근거 사용 여부를 확정한다 -> (본문, 근거_사용_여부).

    recheck(본문, 마커_판정)->bool을 주면 **모든 답변**에 대해 한 번 호출하고 그 결과가
    최종 판정이 된다 — 2026-08-14 팀 결정으로 "[NO_SOURCE]일 때만 재확인, [SOURCE_USED]는
    불가침" 규칙을 폐지하고 검증(source_check.validate_answer)이 마커를 양방향으로
    오버라이드한다. 콜백은 실패 시 마커_판정을 그대로 돌려줄 책임이 있다(fail-open).
    recheck가 None이면(기본) 마커 판정을 그대로 쓴다 — 검증을 끈 때와 동작이 같다.
    상세: src/source_check.py, docs/pipeline_issue_history.md 이슈 5."""
    text, used_source = _strip_no_source_marker(llm_text)
    if recheck is not None:
        used_source = recheck(text, used_source)
    return text, used_source


def assemble_informational_answer(llm_text, citations, recheck=None):
    """LLM이 쓴 답변 본문 뒤에 citation.py가 조회한 실제 출처를 결정론적으로 붙인다.
    단, LLM이 근거를 실제로 안 썼다고 표시했으면(NO_SOURCE_MARKER) 출처를 붙이지 않는다.
    citations: citation.format_all_citations() 결과.
    recheck: _resolve_used_source() 참고(선택). 없으면 마커 판정을 그대로 따른다."""
    text, used_source = _resolve_used_source(llm_text, recheck)
    if not used_source:
        return text
    return text + _render_list("참고 출처", citations, _format_source_line)


def assemble_civil_petition_answer(llm_text, civil_petition_answer, recheck=None):
    """LLM이 쓴 절차 설명 뒤에 civil_petition.py가 조립한 서류·페이지 정보를 결정론적으로
    붙인다. 근거 미사용 표시(NO_SOURCE_MARKER)가 있으면 붙이지 않는다.
    civil_petition_answer: civil_petition.build_civil_petition_answer() 결과.
    recheck: _resolve_used_source() 참고(선택). 없으면 마커 판정을 그대로 따른다."""
    text, used_source = _resolve_used_source(llm_text, recheck)
    if not used_source:
        return text
    answer = text
    answer += _render_list(
        "필요 서류", civil_petition_answer["documents"], lambda d: f"- {d['label']}: {d['url']}")
    answer += _render_list("신청 페이지", civil_petition_answer["links"], _format_source_line)
    return answer
