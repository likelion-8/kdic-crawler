URL_INVENTORY = [
    # ==========================================
    # 5. 채무조정 안내
    # ==========================================
    {
        "id": "da_system",
        "business": "채무조정 안내",
        "sub_category": "채무조정 재기지원",
        "title": "채무조정제도",
        "url": "https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtLbltAjmtSyst/selectScrn.do",
        "required": True,
        "note": "예솜24 기능5 대표항목과 개념 일치 (신청자격, 구비서류 등)"
    },
    {
        "id": "da_info_aply",
        "business": "채무조정 안내",
        "sub_category": "채무조정 재기지원",
        "title": "채무정보 조회 & 상담신청",
        "url": "https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtLbltInfoInqDscsnAply/selectScrn.do",
        "required": True,
        "note": "예솜24 5.2 채무 확인 방법 항목과 동일한 목적의 온라인 채널"
    },
    {
        "id": "da_kruc",
        "business": "채무조정 안내",
        "sub_category": "채무조정",
        "title": "채무조정 (KR&C)",
        "url": "https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtLbltInfoInqDscsnAply/selectScrn.do",
        "required": True,
        "note": "예솜24 5.1-5.3-5.4와 동일 개념을 KR&C 페이지가 더 상세히 제공"
    },
    {
        "id": "da_credit_sprt",
        "business": "채무조정 안내",
        "sub_category": "채무조정 재기지원",
        "title": "신용회복 지원",
        "url": "https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtLbltInfoInqDscsnAply/selectScrn.do",
        "required": False,  # 분석필요
        "note": "신용회복위원회를 통한 지원 제도 안내 (기관 비교표 포함)"
    },
    {
        "id": "da_psn_br",
        "business": "채무조정 안내",
        "sub_category": "채무조정 재기지원",
        "title": "파산면책",
        "url": "https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtPsnBr/selectScrn.do",
        "required": False,  # 분석필요
        "note": "법원을 통한 개인파산 절차 안내 (예솜24 원본 외 범위)"
    },
    {
        "id": "da_psn_rg",
        "business": "채무조정 안내",
        "sub_category": "채무조정 재기지원",
        "title": "개인회생",
        "url": "https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtPsnRg/selectScrn.do",
        "required": False,  # 분석필요
        "note": "법원을 통한 개인회생 절차(3~5년 분할상환) 안내"
    },
    {
        "id": "da_debt_cert",
        "business": "채무조정 안내",
        "sub_category": "지원자금관리",
        "title": "부채증명원/금융거래정보신청",
        "url": "https://www.kdic.or.kr/sp/sprtfund/SprtFndDebtDlngAplyGudn/selectScrn.do",
        "required": False,  # 분석필요
        "note": "파산금융회사 채무자의 부채증명원 공식 발급 절차"
    },
    {
        "id": "da_faq_inq",
        "business": "채무조정 안내",
        "sub_category": "고객센터 > FAQ",
        "title": "채무정보조회 FAQ",
        "url": "https://fins.kdic.or.kr/cm/bbs/selectFaqLbltInfoInq.do",
        "required": False,  # 분석필요
        "note": "온라인 채무정보 조회 방법을 안내하는 FAQ 게시판"
    },

    # ==========================================
    # 6. 은닉재산 신고
    # ==========================================
    {
        "id": "ha_center",
        "business": "은닉재산 신고",
        "sub_category": "금융부실관련자 은닉재산신고",
        "title": "신고센터",
        "url": "https://www.kdic.or.kr/sp/sprtfund/SprtFndCncmDclrGudn/selectScrn.do",
        "required": True,
        "note": "예솜24 기능6 대표항목과 완전 일치 (포상금 산정기준 최대 30억원 등)"
    },
    {
        "id": "ha_faq_dclr",
        "business": "은닉재산 신고",
        "sub_category": "고객센터 > FAQ",
        "title": "은닉재산신고 FAQ",
        "url": "https://fins.kdic.or.kr/cm/bbs/selectFaqCncmPrptDclr.do",
        "required": True,
        "note": "포상금 지급기준표, 신고 절차, 비밀보장 원칙 FAQ"
    },
    {
        "id": "ha_ilgl_intro",
        "business": "은닉재산 신고",
        "sub_category": "금융부실관련자 불법행위신고",
        "title": "신고센터 소개",
        "url": "https://www.kdic.or.kr/sp/sprtfund/SprtFndIvsfalUnrlIlglDclrGudn/selectScrn.do",
        "required": False,  # 분석필요
        "note": "횡령·배임 등 별도 신고대상을 다루는 인접 제도 안내"
    },
    {
        "id": "ha_status_agree",
        "business": "은닉재산 신고",
        "sub_category": "부실책임조사",
        "title": "부실책임조사 진행현황 조회 (개인정보 동의)",
        "url": "https://www.kdic.or.kr/voc/userDataUsingAgree",
        "required": False,  # 분석필요
        "note": "조사 진행현황 조회를 위한 동의 화면 (동적/로그인 여부 실측 필요)"
    }
]

def is_blocked(url):
    # robots.txt 준수 여부를 판정하는 로직 구현 공간
    pass