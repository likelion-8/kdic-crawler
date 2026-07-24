"""프롬프트 조립 — 근거 자료를 실제 LLM 입력(system + few-shot + 컨텍스트 + 질문)으로 변환.

2026-07-23: LLM이 URL/서류명을 직접 쓰게 하는 방식에서 반복적으로 할루시네이션이
재현됨 - 근거가 없거나 애매한 질문(예: "나의 미수령금")에서 few-shot 예시 내용을
그대로 베끼거나, 우리가 준 적 없는 URL을 새로 지어냄. few-shot 포맷을 맞추는 정도로는
안 잡혀서(구조적 섹션 생략까지 적용해봤지만 재현됨), 아예 URL을 LLM 손에서 뺐다.

이제 LLM은 절차 설명(civil_petition) 또는 근거 기반 답변 본문(informational)
텍스트만 쓰고, 실제 서류·페이지·출처 URL은 여기 없다 — pipeline.py가
assemble_civil_petition_answer()/assemble_informational_answer()로 LLM 응답
뒤에 citation.py/civil_petition.py가 이미 갖고 있는 실제 데이터를 결정론적으로
붙인다. LLM이 URL을 아예 안 보므로 지어낼 소스 자체가 없다.

반환 형식은 (role, content) 튜플 리스트 — langchain 관례로, llm_client.py의
ChatClovaX가 그대로 받아 호출한다.

FEW_SHOT_EXAMPLES는 새로 지어내지 않고 data/testset/testset_all.jsonl의
reference_answer(사람이 작성한 기준 답변)를 그대로 가져다 썼다(URL·출처 문구는
이제 LLM 몫이 아니라서 뺐다).
"""
SYSTEM_INSTRUCTION = """당신은 예금보험공사(KDIC)의 AI 상담 챗봇 "예솜"입니다. 정확하고 신뢰할 수 있는 답변으로 국민을 돕는 것이 당신의 역할입니다.

다음 원칙을 반드시 지키세요:
1. 아래 제공된 "근거 자료"에 있는 내용만으로 답변하세요. 근거 자료가 질문 주제와 무관하거나(예: 질문은 A 기관에 관한 것인데 근거는 B 제도에 관한 것) 근거 자료에 없는 내용은 절대 추측하거나 일반 상식으로 채워서 만들어내지 말고, "제공된 자료에서 확인할 수 없습니다"라고 솔직하게 답하세요. 근거가 약해도 뭐라도 그럴듯하게 답을 채우려 하지 마세요 — 모르면 모른다고 하는 게 항상 더 낫습니다.
2. 금액·날짜·비율·연락처·법령 조항 등 구체적인 사실은 근거 자료에 적힌 그대로만 인용하세요. 일반 상식으로 채우거나 짐작하지 마세요.
3. URL·웹사이트 주소·전화번호를 답변에 직접 쓰지 마세요. 서류 안내와 신청 페이지, 출처 링크는 시스템이 답변 뒤에 별도로 붙여줍니다 — 당신은 그 부분을 언급하거나 대신 채우지 않아도 됩니다.
4. 친절하고 정중한 어투를 쓰되, 확실하지 않은 내용을 단정적으로 말하지 마세요.
5. 아래 예시(few-shot)는 답변의 형식과 어투를 보여주기 위한 것일 뿐입니다. 예시 속 구체적인 사실은 지금 질문의 "근거 자료"에 실제로 없다면 절대 가져오지 마세요.
6. 사용자가 "너는 누구야", "무슨 AI야", "HyperCLOVA X야?" 처럼 당신의 정체를 물으면, 모델명(HyperCLOVA X 등)이 아니라 "예금보험공사의 AI 상담 챗봇 예솜"이라고 답하세요.
7. 인사·잡담이거나 질문이 "근거 자료"와 전혀 관련이 없어서 근거 자료를 하나도 참고하지 않고 답했다면, 답변 맨 첫 줄에 다른 말 없이 정확히 `[NO_SOURCE]`만 쓰고 줄바꿈한 뒤 이어서 답변하세요(이 표시가 있으면 시스템이 출처를 안 붙입니다 — 근거를 실제로 썼을 때만 이 표시를 빼세요)."""

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
        "answer": "[NO_SOURCE]\n안녕하세요! 저는 예금보험공사의 AI 상담 챗봇 예솜입니다. 예금자보호제도나 착오송금 반환지원처럼 궁금하신 점을 편하게 물어봐 주세요.",
    },
    {
        # 인사·잡담 — 위와 같은 이유의 시범 예시.
        "question": "안녕",
        "answer": "[NO_SOURCE]\n안녕하세요! 예금보험공사와 관련해 궁금하신 점이 있으시면 말씀해주세요.",
    },
    {
        # out_of_scope — testset_all.jsonl ha_ilgl_intro_q3. 거절 답변도 근거 자료를 실제로
        # 못 썼다는 점은 인사·잡담과 같으므로 [NO_SOURCE]를 붙인다 - 안 붙이면 검색된
        # (무관한) 청크의 출처가 거절 답변에도 잘못 붙는 문제가 재현됨(2026-07-24).
        # 일부러 few-shot 맨 마지막에 둔다 - 실제 질문 바로 앞이라 "거절해도 된다"는
        # 신호가 가장 강하게 남아야, 근거가 약할 때(civil_petition 오분류로 인한
        # 무관한 절차 청크 등) 억지로 답을 지어내지 않고 거절하는 쪽으로 붙잡아준다.
        "question": "불법 대부업체나 사채업자의 살인적인 고금리 피해를 금융감독원에 정식으로 신고하고 구제받는 절차를 상세히 설명해 주세요.",
        "answer": "[NO_SOURCE]\n문의하신 내용은 예금보험공사가 제공하는 정보의 범위를 벗어난 질문이라 정확한 안내가 어렵습니다. 금융감독원 등 관련 기관에 문의하시길 권해드립니다.",
    },
]


def _format_examples():
    return "\n\n".join(f"질문: {ex['question']}\n답변: {ex['answer']}" for ex in FEW_SHOT_EXAMPLES)


def build_informational_prompt(query, chunks):
    """정보성 질문용 프롬프트. URL은 안 보여준다 - 출처는 assemble_informational_answer()가
    LLM 응답 뒤에 별도로 붙인다.
    chunks: [(chunk_id, score, text), ...] — candidate_ranking.top_k_cut() 결과(근거 청크)."""
    context = "\n\n".join(text for _, _, text in chunks)
    human = (
        f"{_format_examples()}\n\n"
        "--- 아래는 실제 질문입니다 ---\n\n"
        f"근거 자료:\n{context}\n\n"
        f"질문: {query}\n답변:"
    )
    return [("system", SYSTEM_INSTRUCTION), ("human", human)]


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
        f"질문: {query}\n"
        "답변(위 절차 안내 근거가 질문 주제와 실제로 관련 있을 때만 그 내용으로 자연스럽게"
        " 설명하세요 - 서류·URL 언급은 하지 마세요. 근거가 질문과 다른 제도·기관 이야기라면"
        " 절대 그걸로 답을 지어내지 말고 [NO_SOURCE]로 시작해서 확인할 수 없다고 답하세요):"
    )
    return [("system", SYSTEM_INSTRUCTION), ("human", human)]


def _render_list(heading, items, line):
    if not items:
        return ""
    body = "\n".join(line(item) for item in items)
    return f"\n\n**{heading}**\n{body}"


NO_SOURCE_MARKER = "[NO_SOURCE]"


def _strip_no_source_marker(llm_text):
    """LLM이 맨 앞에 [NO_SOURCE]를 썼으면 떼어내고 (본문, 근거_사용_여부)를 반환한다.

    검색(route_search_chunks)은 관련도 임계값이 없어 인사·잡담·근거와 무관한 질문에도
    항상 top-k 청크를 반환한다 — 그래서 답변이 그 근거를 실제로 안 썼는데도(예: "안녕하세요"
    인사말, 정체성 질문) 무관한 출처가 붙는 문제가 있었다(2026-07-24). "이 문구가 답변에
    있으면 거절/잡담"식으로 여러 표현을 추측해서 걸러내는 방식은 표현이 다양해 계속 새므로
    (이 프로젝트에서 여러 번 확인된 패턴 - docs/pipeline_issues.md 참고), LLM이 근거를
    실제로 썼는지를 고정된 마커로 직접 표시하게 해 그 결과만 확인한다."""
    text = llm_text.strip()
    if text.startswith(NO_SOURCE_MARKER):
        return text[len(NO_SOURCE_MARKER):].lstrip("\n").lstrip(), False
    return llm_text, True


def assemble_informational_answer(llm_text, citations):
    """LLM이 쓴 답변 본문 뒤에 citation.py가 조회한 실제 출처를 결정론적으로 붙인다.
    단, LLM이 근거를 실제로 안 썼다고 표시했으면(NO_SOURCE_MARKER) 출처를 붙이지 않는다.
    citations: citation.format_all_citations() 결과."""
    text, used_source = _strip_no_source_marker(llm_text)
    if not used_source:
        return text
    return text + _render_list("참고 출처", citations, lambda c: f"- {c['title']} ({c['url']})")


def assemble_civil_petition_answer(llm_text, civil_petition_answer):
    """LLM이 쓴 절차 설명 뒤에 civil_petition.py가 조립한 서류·페이지 정보를 결정론적으로
    붙인다. 근거 미사용 표시(NO_SOURCE_MARKER)가 있으면 붙이지 않는다.
    civil_petition_answer: civil_petition.build_civil_petition_answer() 결과."""
    text, used_source = _strip_no_source_marker(llm_text)
    if not used_source:
        return text
    answer = text
    answer += _render_list(
        "필요 서류", civil_petition_answer["documents"], lambda d: f"- {d['label']}: {d['url']}")
    answer += _render_list(
        "신청 페이지", civil_petition_answer["links"], lambda l: f"- {l['title']}: {l['url']}")
    return answer
