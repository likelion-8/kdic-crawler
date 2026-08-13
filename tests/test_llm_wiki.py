from src.crawler.build_llm_wiki import WIKI_PATH, build_wiki, load_inputs, write_or_check


def test_llm_wiki_covers_six_domains_and_all_official_sources():
    graph, corpus, fact_gap_queue, fact_gap_decisions = load_inputs()
    output = build_wiki(graph, corpus, fact_gap_queue, fact_gap_decisions)

    domain_pages = [path for path in output if path.startswith("업무영역/")]
    assert len(domain_pages) == 6
    assert "00 시작하기.md" in output
    assert "01 LLM 응답 규칙.md" in output
    assert sum(page.count("- 공식 원문: [") for page in output.values()) == graph["source"]["document_count"]


def test_llm_wiki_separates_navigation_from_approved_answer_content():
    graph, corpus, fact_gap_queue, fact_gap_decisions = load_inputs()
    output = build_wiki(graph, corpus, fact_gap_queue, fact_gap_decisions)
    rules = output["01 LLM 응답 규칙.md"]
    deposit_protection = output["업무영역/예금자보호제도.md"]

    assert "승인된 사실 보강 후보" in rules
    assert "도메인 승인 완료" in rules
    assert "## 승인된 핵심 사실" in deposit_protection
    assert "예금자 보호한도 1인·금융회사별 1억원" in deposit_protection
    assert "금융회사별로 1인당 1억원까지 보호됩니다." in deposit_protection
    assert "`page_id`: `dp_protlmts`" in deposit_protection
    assert "원문 해시:" in deposit_protection
    assert "https://www.kdic.or.kr/" in deposit_protection


def test_llm_wiki_exposes_pending_gap_facts_without_marking_them_answer_ready():
    graph, corpus, fact_gap_queue, fact_gap_decisions = load_inputs()
    output = build_wiki(graph, corpus, fact_gap_queue, fact_gap_decisions)
    deposit_insurance = output["업무영역/예금보험금 안내.md"]
    unclaimed = output["업무영역/고객 미수령금 신청.md"]

    assert "## 승인된 업무 구성" in deposit_insurance
    assert "- 승인된 핵심 사실 없음" in deposit_insurance
    assert "예금보험금 청구권 행사기한" in deposit_insurance
    assert "고객 미수령금의 정의" in unclaimed
    assert "## 승인된 사실 보강 후보 · core fact 승격 대기" in deposit_insurance
    assert deposit_insurance.count("- 상태: 도메인 승인 완료 · core fact 미승격") == 3
    assert unclaimed.count("- 상태: 도메인 승인 완료 · core fact 미승격") == 3
    assert deposit_insurance.count("- 검토자·승인일: hjy10 · 2026-08-12") == 3


def test_checked_in_llm_wiki_is_reproducible():
    assert write_or_check(check=True) == 0
    assert (WIKI_PATH / "00 시작하기.md").exists()
