"""착오송금(Mistaken Remittance) 크롤 대상 페이지 인벤토리.

raw_html/*.html과 함께 관리되는 데이터 산출물이라, 페이지를 추가/제외할 때
crawl_mistaken_remittance_jh.py 코드를 건드리지 않고 이 파일만 편집하면 된다.
각 항목: id(영문 식별자), title(한글 제목), url(페이지 URL),
business_function(업무 카테고리), sub_category(하위 분류)
"""

PAGES = [
    {
        "id": "kmrs_itrd",
        "title": "착오송금반환지원 제도란",
        "url": "https://www.kdic.or.kr/sp/kmrs/kmrsItrd/selectScrn.do",
        "business_function": "착오송금",
        "sub_category": "제도란",
    },
    {
        "id": "kmrs_proc",
        "title": "착오송금반환지원 절차",
        "url": "https://www.kdic.or.kr/sp/kmrs/kmrsItrdProc/selectScrn.do",
        "business_function": "착오송금",
        "sub_category": "절차",
    },
    {
        "id": "kmrs_apply_mthd",
        "title": "착오송금반환지원 신청방법",
        "url": "https://www.kdic.or.kr/sp/kmrs/kmrsItrdAplyMthd/selectScrn.do",
        "business_function": "착오송금",
        "sub_category": "신청방법",
    },
    {
        "id": "faq_msdr_apply",
        "title": "FAQ - 착오송금반환지원신청",
        "url": "https://fins.kdic.or.kr/cm/bbs/selectFaqMsdrGvbkAply.do",
        "business_function": "착오송금",
        "sub_category": "FAQ_반환지원신청",
    },
    {
        "id": "faq_top10",
        "title": "고객센터 FAQ TOP 10",
        "url": "https://fins.kdic.or.kr/cm/bbs/selectFaqTop10.do",
        "business_function": "착오송금",
        "sub_category": "FAQ_TOP10",
    },
    {
        "id": "receiver_attention",
        "title": "착오송금수취인 유의사항",
        "url": "https://fins.kdic.or.kr/ir/addrse/AddrseAttnMttr/selectScrn.do",
        "business_function": "착오송금",
        "sub_category": "수취인_유의사항",
    },
    {
        "id": "receiver_docs",
        "title": "구비서류안내 - 착오송금수취인",
        "url": "https://fins.kdic.or.kr/ir/aplygudn/MsdrAddrsePossDcmntGudn/selectScrn.do",
        "business_function": "착오송금",
        "sub_category": "구비서류_수취인",
    },
]
