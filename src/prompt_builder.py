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
SYSTEM_INSTRUCTION = """당신은 예금보험공사(KDIC)에서 국민의 민원과 문의를 응대하는 담당 공무원입니다. 정확하고 신뢰할 수 있는 답변으로 국민을 돕는 것이 당신의 역할입니다.

다음 원칙을 반드시 지키세요:
1. 아래 제공된 "근거 자료"에 있는 내용만으로 답변하세요. 근거 자료에 없는 내용은 절대 추측하거나 만들어내지 말고, "제공된 자료에서 확인할 수 없습니다"라고 솔직하게 답하세요.
2. 금액·날짜·비율·연락처·법령 조항 등 구체적인 사실은 근거 자료에 적힌 그대로만 인용하세요. 일반 상식으로 채우거나 짐작하지 마세요.
3. URL·웹사이트 주소·전화번호를 답변에 직접 쓰지 마세요. 서류 안내와 신청 페이지, 출처 링크는 시스템이 답변 뒤에 별도로 붙여줍니다 — 당신은 그 부분을 언급하거나 대신 채우지 않아도 됩니다.
4. 친절하고 정중한 어투를 쓰되, 확실하지 않은 내용을 단정적으로 말하지 마세요.
5. 아래 예시(few-shot)는 답변의 형식과 어투를 보여주기 위한 것일 뿐입니다. 예시 속 구체적인 사실은 지금 질문의 "근거 자료"에 실제로 없다면 절대 가져오지 마세요."""

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
        # out_of_scope — testset_all.jsonl ha_ilgl_intro_q3
        "question": "불법 대부업체나 사채업자의 살인적인 고금리 피해를 금융감독원에 정식으로 신고하고 구제받는 절차를 상세히 설명해 주세요.",
        "answer": "문의하신 내용은 예금보험공사가 제공하는 정보의 범위를 벗어난 질문이라 정확한 안내가 어렵습니다. 금융감독원 등 관련 기관에 문의하시길 권해드립니다.",
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
        "답변(절차만 자연스럽게 설명하세요 - 서류·URL 언급은 하지 마세요):"
    )
    return [("system", SYSTEM_INSTRUCTION), ("human", human)]


def _render_list(heading, items, line):
    if not items:
        return ""
    body = "\n".join(line(item) for item in items)
    return f"\n\n**{heading}**\n{body}"


def assemble_informational_answer(llm_text, citations):
    """LLM이 쓴 답변 본문 뒤에 citation.py가 조회한 실제 출처를 결정론적으로 붙인다.
    citations: citation.format_all_citations() 결과."""
    return llm_text + _render_list("참고 출처", citations, lambda c: f"- {c['title']} ({c['url']})")


def assemble_civil_petition_answer(llm_text, civil_petition_answer):
    """LLM이 쓴 절차 설명 뒤에 civil_petition.py가 조립한 서류·페이지 정보를 결정론적으로
    붙인다. civil_petition_answer: civil_petition.build_civil_petition_answer() 결과."""
    answer = llm_text
    answer += _render_list(
        "필요 서류", civil_petition_answer["documents"], lambda d: f"- {d['label']}: {d['url']}")
    answer += _render_list(
        "신청 페이지", civil_petition_answer["links"], lambda l: f"- {l['title']}: {l['url']}")
    return answer
