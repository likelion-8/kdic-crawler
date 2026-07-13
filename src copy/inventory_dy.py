# src/inventory_dy.py
"""수집 대상 페이지 목록 — 기능2(예금보험금 안내)·기능3(고객 미수령금 신청) 담당분 (신동엽).

여기 있는 것만 크롤한다(목록에 없는 페이지는 크롤링하지 않음).
분석필요 2건(F2-04, F3-04) 포함 확정 — 2026-07-13 팀 협의.
사전조사: https://psychedelic-uncle-650.notion.site/24-6-39731c089bcd80d0a7bde56c56b56827

필드
  doc_id             페이지 식별자 (파일명·chunk_id에 쓰인다)
  business_function  담당 업무 (검색 범위 1차 필터)
  sub_category       업무 내 하위 분류 (2차 필터)
  page_title         페이지 제목
  url                수집 URL
  required           사전조사 분류 ("필수" / "분석필요")
  reason             왜 수집하나 (근거)
  summary            페이지 요약 — meta에만 남기고 청크로는 내리지 않는다
"""

PAGES = [
    # ---------------- 기능2. 예금보험금 안내 ----------------
    {
        "doc_id": "F2-01",
        "business_function": "예금보험금 안내",
        "sub_category": "예금보험금 안내 > 신청시 구비서류",
        "page_title": "신청시 구비서류",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtAplyPossDcmnt/selectScrn.do",
        "required": "필수",
        "reason": "예솜24 2.1 신청서류 항목과 개념 일치",
        "summary": "본인·대리인·미성년자 등 신청인 유형별 구비서류 안내",
    },
    {
        "doc_id": "F2-02",
        "business_function": "예금보험금 안내",
        "sub_category": "예금보험금 신청 절차 > 예금보험금 신청절차",
        "page_title": "예금보험금 신청절차",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtAplyProc/selectScrn.do",
        "required": "필수",
        "reason": "예솜24 2.2 신청 절차 항목과 개념 일치",
        "summary": "보험사고 발생부터 지급공고·신청·지급까지의 절차 설명",
    },
    {
        "doc_id": "F2-03",
        "business_function": "예금보험금 안내",
        "sub_category": "예금보험금 안내 > 예금보험금이란?",
        "page_title": "예금보험금이란?",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtExpln/selectScrn.do",
        "required": "필수",
        "reason": "예솜24 기능2 대표항목과 개념 일치",
        "summary": "예금보험금(가지급금·개산지급금)의 정의 설명",
    },
    {
        "doc_id": "F2-04",
        "business_function": "예금보험금 안내",
        "sub_category": "예금보험금 안내 > 보험금 지급대상 금융회사",
        "page_title": "보험금 지급대상 금융회사",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/selectProtSystBamtGiveTrgtFnst.do",
        "required": "분석필요",
        "reason": "파산금융회사별 검색 기능은 예솜24에 없던 내용 — 팀 협의로 포함 확정 (2026-07-13)",
        # 검색·조회 기능 페이지라 동적 검색 결과는 스냅샷에 안 담김 — 안내 문구·기본 목록만 수집 (한계 인지)
        "summary": "파산금융회사별 예금보험금 지급대상 여부 검색 가능",
    },
    # ---------------- 기능3. 고객 미수령금 신청 ----------------
    {
        "doc_id": "F3-01",
        "business_function": "고객 미수령금 신청",
        "sub_category": "미수령금 통합조회/신청 > 고객미수령금",
        "page_title": "고객미수령금",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/ProtSystNramtInqAplyNramtGudn/selectScrn.do",
        "required": "필수",
        "reason": "예솜24 기능3 대표항목과 제목·개념 일치",
        "summary": "미수령금의 정의와 인터넷·방문 신청 방법 안내",
    },
    {
        "doc_id": "F3-02",
        "business_function": "고객 미수령금 신청",
        "sub_category": "미수령금통합신청 > 소개와 신청방법 안내 > 예금자 대상 전화문의 안내",
        "page_title": "예금자 대상 전화문의 안내",
        "url": "https://fins.kdic.or.kr/ua/aplygudn/DpstrTrgtTelQustGudn/selectScrn.do",
        "required": "필수",
        "reason": "예솜24 3.2 방문 신청 항목과 유사한 전화 문의 채널",
        "summary": "명의 변경 시 문의 방법과 미수령금 관련 전화상담 안내",
    },
    {
        "doc_id": "F3-03",
        "business_function": "고객 미수령금 신청",
        "sub_category": "미수령금통합신청 > 소개와 신청방법 안내 > 안내",
        "page_title": "안내",
        "url": "https://fins.kdic.or.kr/ua/aplygudn/NramtItgrAplyItrdMthdGudn/selectScrn.do",
        "required": "필수",
        "reason": "예솜24 기능3 대표항목 및 3.1·3.2 신청방법 항목과 개념 일치",
        "summary": "미수령금 종류와 온라인·오프라인 신청 방법 설명",
    },
    {
        "doc_id": "F3-04",
        "business_function": "고객 미수령금 신청",
        "sub_category": "미수령금 통합조회/신청 > 상속인 금융거래조회",
        "page_title": "상속인 금융거래조회",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/ProtSystHrpeHistInq/selectScrn.do",
        "required": "분석필요",
        "reason": "상속인 대상 조회 기능은 예솜24에 없던 내용 — 팀 협의로 포함 확정 (2026-07-13)",
        "summary": "사망자(피상속인) 명의 미수령금을 상속인이 조회하는 서비스",
    },
]
