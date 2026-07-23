"""프롬프트 조립 — 근거 자료를 실제 LLM 입력(system + few-shot + 컨텍스트 + 질문)으로 변환.

SYSTEM_INSTRUCTION/FEW_SHOT_EXAMPLES는 두 빌더가 공유한다. informational은 근거
청크를 그대로 컨텍스트로 쓰고, civil_petition은 civil_petition.build_civil_petition_answer()의
절차·서류·페이지 3단계 구조를 그대로 컨텍스트에 넣어 그 순서를 지켜 답하도록 지시한다.

반환 형식은 (role, content) 튜플 리스트 — langchain 관례로, llm_client.py의
ChatClovaX가 그대로 받아 호출한다.

FEW_SHOT_EXAMPLES는 새로 지어내지 않고 data/testset/testset_all.jsonl의
reference_answer(사람이 작성한 기준 답변)를 그대로 가져다 썼다.
"""
SYSTEM_INSTRUCTION = """당신은 예금보험공사(KDIC)에서 국민의 민원과 문의를 응대하는 담당 공무원입니다. 정확하고 신뢰할 수 있는 답변으로 국민을 돕는 것이 당신의 역할입니다.

다음 원칙을 반드시 지키세요:
1. 아래 제공된 "근거 자료"에 있는 내용만으로 답변하세요. 근거 자료에 없는 내용은 절대 추측하거나 만들어내지 말고, "제공된 자료에서 확인할 수 없습니다"라고 솔직하게 답하세요.
2. 금액·날짜·비율·연락처·법령 조항 등 구체적인 사실은 근거 자료에 적힌 그대로만 인용하세요. 일반 상식으로 채우거나 짐작하지 마세요.
3. 답변 끝에 참고한 출처(페이지 제목과 링크)를 안내하세요.
4. 사용자가 신청·접수·제출 등 절차를 원하는 질문이면, 절차 안내 → 필요 서류 안내 → 신청 페이지 안내 순서로 답변을 구성하세요.
5. 친절하고 정중한 어투를 쓰되, 확실하지 않은 내용을 단정적으로 말하지 마세요."""

FEW_SHOT_EXAMPLES = [
    {
        # informational — testset_all.jsonl ms_poss_dcmnt_q4
        "question": "예금자 본인이 직접 예금보험금을 찾으러 갈 때 필요한 서류는 무엇인가요?",
        "answer": "주민등록증·운전면허증·여권 등 공공기관 발행 신분증과 본인의 도장(서명 가능)만 있으면 됩니다.\n\n(출처: 신청시 구비서류 안내)",
    },
    {
        # civil_petition — testset_all.jsonl ms_poss_dcmnt_q3
        "question": "예금보험금 위임장 양식은 어디서 다운로드 받나요?",
        "answer": (
            "절차 안내: 대리인이 위임장을 지참해 신청하시면 됩니다.\n"
            "서류 안내: '신청시 구비서류' 페이지의 양식 다운로드 섹션에서 위임장 양식을 내려받을 수 있습니다.\n"
            "페이지 연결: 신청시 구비서류 안내 페이지에서 확인하실 수 있습니다.\n\n"
            "(출처: 신청시 구비서류 안내)"
        ),
    },
    {
        # out_of_scope — testset_all.jsonl ha_ilgl_intro_q3
        "question": "불법 대부업체나 사채업자의 살인적인 고금리 피해를 금융감독원에 정식으로 신고하고 구제받는 절차를 상세히 설명해 주세요.",
        "answer": "문의하신 내용은 예금보험공사가 제공하는 정보의 범위를 벗어난 질문이라 정확한 안내가 어렵습니다. 금융감독원 등 관련 기관에 문의하시길 권해드립니다.",
    },
]


def _format_examples():
    return "\n\n".join(f"질문: {ex['question']}\n답변: {ex['answer']}" for ex in FEW_SHOT_EXAMPLES)


def build_informational_prompt(query, chunks, citations):
    """정보성 질문용 프롬프트.
    chunks: [(chunk_id, score, text), ...] — candidate_ranking.top_k_cut() 결과(근거 청크).
    citations: citation.format_all_citations() 결과."""
    context = "\n\n".join(text for _, _, text in chunks)
    sources = "\n".join(f"- {c['title']} ({c['url']})" for c in citations) or "(해당 없음)"
    human = (
        f"{_format_examples()}\n\n"
        "--- 아래는 실제 질문입니다 ---\n\n"
        f"근거 자료:\n{context}\n\n"
        f"참고 출처:\n{sources}\n\n"
        f"질문: {query}\n답변:"
    )
    return [("system", SYSTEM_INSTRUCTION), ("human", human)]


def build_civil_petition_prompt(query, civil_petition_answer):
    """민원성 질문용 프롬프트.
    civil_petition_answer: civil_petition.build_civil_petition_answer() 결과
    ({"procedure": str, "documents": [...], "links": [...]})."""
    documents = "\n".join(
        f"- {d['label']}: {d['url']}" for d in civil_petition_answer["documents"]
    ) or "(해당 없음)"
    links = "\n".join(
        f"- {l['title']}: {l['url']}" for l in civil_petition_answer["links"]
    ) or "(해당 없음)"
    human = (
        f"{_format_examples()}\n\n"
        "--- 아래는 실제 질문입니다 ---\n\n"
        f"[절차 안내 근거]\n{civil_petition_answer['procedure']}\n\n"
        f"[서류 안내 근거]\n{documents}\n\n"
        f"[페이지 연결 근거]\n{links}\n\n"
        f"질문: {query}\n"
        "답변(절차 → 서류 → 페이지 순서로 구성하고, 위 URL은 새로 만들지 말고 그대로 인용하세요):"
    )
    return [("system", SYSTEM_INSTRUCTION), ("human", human)]
