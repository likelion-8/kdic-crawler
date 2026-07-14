"""수집 대상 페이지 통합 목록 — 팀원 5명의 inventory를 표준 스키마로 병합.

여기 있는 것만 크롤한다. 사이트맵을 통째로 긁지 않는 이유:
6개 업무 페이지만 필요하고, '무엇을 왜 수집했는지' 설명할 수 있어야 한다.

원출처 (병합 전 파일 → owner 값)
  inventory_yj.py                        → "yj"  기능1 예금자보호제도
  inventory_dy.py                        → "dy"  기능2·3 예금보험금·미수령금
  page_inventory_jh.py                   → "jh"  기능4 착오송금
  inventory_hw.py                        → "hw"  기능6 은닉재산
  crawl_debt_adjustment_raw_html_jy.py   → "jy"  기능5 채무조정 (인라인 PAGES)

필드
  id            페이지 식별자 (data/raw_html/<id>.html 파일명과 일치)
                업무별 접두사: dp_(예금자보호) ms_(예금보험금) uc_(미수령금)
                kmrs_/faq_/receiver_(착오송금) dr_(채무조정) ha_(은닉재산)
  business      6개 업무 중 하나 (BUSINESSES — 검색 범위 1차 필터, 문자열 정확 일치)
  sub_category  업무 내 하위 분류 (2차 필터)
  title         페이지 제목
  url           수집 URL
  required      사전조사에서 '필수'였나 (False = '분석필요', None = 원출처에 분류 없음)
  note          왜 수집하나 (근거. None = 원출처에 기록 없음)
  owner         담당자 접미사 (hw/yj/dy/jh/jy)

선택 필드
  summary       페이지 요약 — meta에만 남기고 청크로는 내리지 않는다. 전 항목 보유
                (yj·dy분은 원저자 검수본, 나머지 27건은 2026-07-13 파싱 본문 기반 초안 — 담당자 검수 필요)
  expect        서버가 판본 여러 개를 서빙하는 페이지에만. 맞는 판본에만 있는 문자열.
  body_selector 본문 컨테이너가 div.contents 가 아닌 페이지에만

정리 이력 (2026-07-13): 채무조정 8건은 hw(da_*)와 jy(DEBT-*)가 중복 수집했었다.
      hw본은 2건(da_kruc·da_credit_sprt)의 URL이 da_info_aply와 같게 오기재되어 실제로는
      다른 페이지가 저장돼 있었으므로, 내용이 온전한 jy 수집본을 dr_* 로 개명해 대표로
      채택하고 hw의 큐레이션(required·note)을 병합했다. hw의 da_* 원본은 git 이력 참조.
"""

BUSINESSES = [
    "예금자보호제도",
    "예금보험금 안내",
    "고객 미수령금 신청",
    "착오송금 반환 신청",
    "채무조정 안내",
    "은닉재산 신고",
]

PAGES = [
    # ============================================================
    # 예금자보호제도 (기능1) — inventory_yj.py 출신 16건 + 누락분 1건 추가, 17페이지
    # ============================================================
    {
        "id": "dp_protlmts",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 보호한도",
        "title": "보호한도",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/ProtSystProtLmts/selectScrn.do",
        "required": True,
        "note": "예솜24 1.3 보호한도 항목",
        "summary": "예금자 1인당 보호한도(원금+소정이자 1억원)와 초과금액 비보호 원칙, 대출 상계 규정, 별도한도(DC·IRP·연금저축·사고보험금 각 1억원)를 설명한다.",
        # 서버가 판본 2종을 번갈아 준다(실측 12회 중 3회). 각주 한 줄만 다르다:
        #   옛 판본 "5천만원 이하 예금자는 …"  /  현행 "1억원 이하 예금자는 …"
        # 어느 쪽이 맞는지는 기계가 못 정한다 → 사람이 여기 못박는다.
        # 근거: 같은 페이지 본문이 1억원을 5번 말한다(옛 판본은 자기 안에서 모순).
        #       faq_nramt Q008 "보호한도 이내 예금(원리금 합계 1억원 이하)이 계약이전"
        # 크롤러는 이 문자열이 든 판본만 채택하고, 옛 판본을 받으면 다시 받는다.
        "expect": "1억원 이하 예금자는",
        "owner": "yj",
    },
    {
        "id": "dp_syst",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 예금자보호제도",
        "title": "예금자보호제도",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/ProtSyst/selectScrn.do",
        "required": True,
        "note": "예솜24 기능1 대표항목",
        "summary": "예금보험공사가 보험료를 적립해 두었다가 금융회사 대신 예금을 지급하는 공적보험의 원리와 구조를 설명한다.",
        "owner": "yj",
    },
    {
        "id": "dp_fnst",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 보호대상 > 금융회사 > 개요",
        "title": "보호대상 금융회사 개요",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtSumr.do",
        "required": True,
        "note": "예솜24 1.1 보호 대상 금융회사",
        "summary": "보호대상 금융회사 종류(은행·보험·투자매매중개업자·종금사·상호저축은행)와 부보금융회사 수를 기준일과 함께 표로 제공한다. 농수협 지역조합·신협·새마을금고는 비대상임을 명시한다.",
        "owner": "yj",
    },
    {
        "id": "dp_prdct",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 보호대상 > 금융상품 > 개요",
        "title": "보호대상 금융상품 개요",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtTrgtPrdctSumr.do",
        "required": True,
        "note": "예솜24 1.2 보호 대상 금융상품",
        "summary": "업권별 보호·비보호 금융상품을 표로 구분한다. CD·RP·펀드·ELS·증권사 CMA 등 비보호 상품과 종금사 CMA 등 보호 상품이 갈린다.",
        "owner": "yj",
    },
    {
        "id": "dp_faq_page",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 예금자보호제도 FAQ",
        "title": "예금자보호제도 FAQ",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/ProtSystFaq/selectScrn.do",
        "required": False,
        "note": "2025년 한도 상향 등 최신 FAQ",
        "summary": "예금보호한도 1억원 상향 시행일, 별도 신청 불필요, 예금-대출 상계 계산 사례, 퇴직연금·연금저축 별도한도 등 17개 문답을 담은 아코디언 FAQ.",
        "owner": "yj",
    },
    {
        "id": "dp_ovrs",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 예금자보호한도(해외)",
        "title": "예금자보호한도(해외)",
        "url": "https://www.kdic.or.kr/di/bzpblnt/selectPbcrPblntProtLmtsOvrs.do",
        "required": False,
        "note": "해외 비교 자료",
        "summary": "한국·미국·캐나다·일본·영국·독일의 예금보호한도와 1인당 GDP 대비 배율을 비교한 표. 기준시점과 출처(IMF)가 명시돼 있다.",
        "owner": "yj",
    },
    {
        "id": "dp_prdct_srch",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 보호대상 > 금융상품 > 보호대상금융상품검색",
        "title": "보호대상금융상품검색",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtTrgtPrdctSrchList.do",
        "required": True,
        "note": "'내 상품이 보호되나요' 조회 화면. 개요(dp_prdct)만으론 개별 상품 질의에 못 답한다",
        "summary": "부보금융회사별 보호금융상품 목록을 금융권역(은행·종금·보험·저축은행·신협)·회사명·상품명으로 검색하는 화면이다. 목록은 금융회사가 제출한 보호금융상품등록부를 바탕으로 작성돼 착오·오류가 있을 수 있고 기준일 이후 신규 판매 상품은 검색되지 않을 수 있다. 정부·지자체·한국은행·금융감독원·예금보험공사·부보금융회사가 가입한 상품과 법인 보험계약은 비보호이며, 변액보험은 최저보증 보험금·특약만 보호(사고보험금 별도), 확정급여형(DB) 퇴직연금 편입 상품은 비보호라고 명시한다.",
        "owner": "yj",
    },
    {
        "id": "dp_fnst_srch",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 보호대상 > 금융회사 > 보호대상금융회사검색",
        "title": "보호대상금융회사검색",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/selectProtSystProtSrch.do",
        "required": True,
        "note": "'내 은행이 보호대상인가요' 조회 화면",
        "summary": "보호대상 금융회사를 금융권역(은행·종합금융회사·생명보험회사·손해보험회사·투자매매업자ㆍ투자중개업자·상호저축은행·신용협동조합)과 회사명으로 검색하는 화면이다. 25.12월 기준 회사명·주소·연락처·FAX·대표자명을 표로 제공하며, 상단에 은행·증권 투자매매중개업자·보험회사·종합금융회사·상호저축은행이 예금보험 대상이라는 안내를 싣는다.",
        "owner": "yj",
    },
    {
        "id": "dp_svbk_hist",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 보호대상 > 금융회사 > 저축은행변경이력",
        "title": "저축은행변경이력",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/selectProtSystSvbkChgHstry.do",
        "required": False,
        "note": "상호가 바뀐 저축은행 추적 — 미수령금 조회와 연결된다",
        "summary": "저축은행의 상호 변경이력을 현 회사명·변경일자·구명칭(또는 저축은행명) 표로 제공한다(2022/4/20 기준, 엑셀 다운로드 가능). 상상인←공평(2018-06-04), 애큐온←HK(2017-12-18), 다올←유진(2022-03-21) 등 옛 이름으로 거래하던 저축은행의 현재 상호를 확인할 수 있다.",
        "owner": "yj",
    },
    {
        "id": "dp_gudn",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 표시·설명·확인 제도 > 표시·설명·확인 제도 안내",
        "title": "표시·설명·확인 제도 안내",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/ProtSystProtGudn/selectScrn.do",
        "required": True,
        "note": "금융회사가 예금자에게 보호 여부를 알려야 하는 제도 — 예금자도 알 권리가 있다",
        "summary": "부보금융회사가 금융상품의 예금보험 여부와 보호한도(원금+소정이자 1인당 최고 1억원)를 홍보물 등에 표시하고, 계약 체결 시 직접 설명한 뒤 서명 등으로 확인받아 불완전판매를 방지하는 제도를 설명한다. 표시제도(예금자보호안내문 표시, 보호금융상품등록부 작성·비치, 안내자료 비치, 예금보호 로고, 신상품 보호여부 사전·사후 확인), 설명제도(문서·구두 설명, 만 65세 이상·은퇴자·주부 등 금융정보취약계층 우선설명), 확인제도(서명·기명날인·녹취·전자서명 등)의 주요 업무와, 공사의 현장조사 및 미이행 시 과태료 부과를 담는다.",
        "owner": "yj",
    },
    {
        "id": "dp_gudn_faq",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 표시·설명·확인 제도 > 표시·설명·확인 제도 관련 FAQ",
        "title": "표시·설명·확인 제도 관련 FAQ",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/ProtSystProtSystFaq/selectScrn.do",
        "required": False,
        "note": "아코디언 FAQ",
        "summary": "표시·설명·확인 제도에 관한 문답을 표시제도와 설명·확인제도로 나눠 담는다. 표시 대상(홍보물·통장등·계좌조회화면등), 방카슈랑스 등 위탁판매 상품의 표시 주체, 전자금융거래 시 제1종 안내문 표시, 예금자보호대상 퇴직연금 범위(확정급여형 비보호, 확정기여형·개인퇴직계좌의 금리연동형·이율보증형 보호, 실적배당형 비보호), 신상품 보호여부 사전확인 대상 3가지, 대리인·법인 고객의 설명·확인 이행, TM·전자금융거래에서의 일괄 동의, 상속·양도·명의변경 시 이행 의무 등을 다룬다.",
        "owner": "yj",
    },
    {
        "id": "dp_gudn_data",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 표시·설명·확인 제도 > 안내자료 다운로드",
        "title": "안내자료 다운로드",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/selectProtSystDataDwnldList.do",
        "required": False,
        "note": "예금자보호 안내자료 서식 제공",
        "summary": "예금자보호제도 안내책자·가이드라인 등 자료 31건을 제목·소관부서·내용으로 검색해 내려받는 게시판이다. 예금자보호제도 안내자료(PDF, 2025.9), 예금보험관계 표시·설명·확인제도 가이드라인(2024.2), 예금자보호안내문(제1종·제2종) 영문 번역본, 표시·설명·확인 의무 관련 규정 일체 등이 등록돼 있고 개인·부보금융회사가 다운로드해 영업점에 비치할 수 있다.",
        "owner": "yj",
    },
    {
        "id": "dp_logo",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 표시·설명·확인 제도 > 예금보호 로고 사용 안내",
        "title": "예금보호 로고 사용 안내",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/ProtSystProtLogoUseGudn/selectScrn.do",
        "required": False,
        "note": "예금보호 로고의 의미 — 예금자가 보호 여부를 식별하는 표식이다",
        "summary": "예금보호 로고(보호금융상품 1인당 최고 1억원 / 비보호)의 사용 규정을 설명한다. 정비례 확대·축소는 가능하나 색상변경은 불가하며 전용색상은 KDIC RED(PANTONE 186C)·KDIC BLUE(PANTONE 294C)의 4원색(CMYK) 사용을 원칙으로 한다. 문구 비율 변형·기울기·자간 확대·그림자·테두리 등 12가지 사용금지 규정과 사용 대상(『예금보험관계 표시 및 설명·확인에 관한 규정』 제2조에 따른 통장등·홍보물·계좌조회화면등), 로고 다운로드를 제공한다.",
        "owner": "yj",
    },
    {
        "id": "dp_josa_itrd",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 부보금융회사조사 > 조사업무 소개",
        "title": "부보금융회사조사 업무 소개",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/ProtSystJosaItrd/selectScrn.do",
        "required": False,
        "note": "공사가 부보금융회사를 조사하는 근거와 절차",
        "summary": "예금자보호법 제21조 제2항에 근거해 공사가 부보금융회사 등의 업무·재산상황을 조사하는 업무를 소개한다. 기본가치(절차의 투명성·조사의 전문성·조사원의 청렴성), 시행령 제12조의2에 따라 부실우려가 인정되거나 자료 확인이 이뤄지지 않은 경우 조사할 수 있다는 기본방향, 주요절차 4단계(조사대상 선정→현장조사→조사내용 심의→조사결과 처리), 권익보호담당역·소명 및 이의제기 제도, 조사결과의 예금보험위원회 보고와 금융감독원·금융위원회 통보·조치 요청을 담는다.",
        "owner": "yj",
    },
    {
        "id": "dp_josa_law",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 부보금융회사조사 > 법적근거 및 관련규정",
        "title": "부보금융회사조사 법적근거 및 관련규정",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/ProtSystJosaRgul/selectScrn.do",
        "required": False,
        "note": "예금자보호법상 조사 권한 근거",
        "summary": "부보금융회사 조사의 법적근거인 예금자보호법 제21조제2항과 시행령 제12조의2 조문을 싣는다. 제21조는 자료제출 요구, 부실우려 시 조사, 금융감독원장에 대한 검사·시정조치 요청, 보험사고 위험 시 금융위원회 통보를 규정하고, 시행령 제12조의2는 상호저축은행의 부실우려 인정기준 4가지(금융위 기준 해당, 자기자본비율이 그 기준+2%포인트 미만, 최근 3개 회계연도 연속 당기순손실, 공사가 금감원과 협의해 조사 필요성을 인정)를 정한다. 내규인 '부보금융기관등의 조사 및 공동검사에 관한 규정' 및 시행세칙 링크도 제공한다.",
        "owner": "yj",
    },
    {
        "id": "dp_josa_objc",
        "business": "예금자보호제도",
        "sub_category": "예금자보호제도 > 부보금융회사조사 > 소명 및 이의제기 > 소명및이의제기신청",
        "title": "부보금융회사조사 소명 및 이의제기 신청",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/ProtSystJosaExplPrtsAplyGudn/selectScrn.do",
        "required": False,
        "note": "조사 대상 금융회사의 이의제기 절차",
        "summary": "조사대상 부보금융회사(임직원)가 조사내용에 이견이 있을 때 증빙자료를 첨부해 조사실시 부서장에게 소명·이의제기하는 절차를 안내한다. 처리절차는 신청→접수→수용여부 검토(실무회의 등)→결과통보이며 '진행상황조회'로 단계를 확인할 수 있다. 신청 채널은 인터넷(VOC 고객의 소리), 우편·방문(서울특별시 중구 청계천로 30 예금보험공사 리스크총괄부, 우편번호 04521), 팩스 02-758-0250이다.",
        "owner": "yj",
    },
    {
        # 사전조사 문서 대조로 발견된 누락분 (2026-07-13 추가). dp_protlmts의 expect 근거(Q008)로
        # 인용된 페이지인데 수집이 빠져 있었다. 사이트 분류명은 '미수령금통합신청'이지만 실제 내용은 예금보호 FAQ.
        "id": "faq_nramt",
        "business": "예금자보호제도",
        "sub_category": "고객센터 > FAQ > 미수령금통합신청",
        "title": "미수령금통합신청 FAQ (실제 내용은 예금보호)",
        "url": "https://fins.kdic.or.kr/cm/bbs/selectFaqNramtAply.do",
        "required": True,
        "note": "예솜24 기능1(보호한도·보호대상)과 개념 일치 — 사전조사 문서 기능1 필수 항목",
        "summary": "예금보호한도, 계열 저축은행 분산예금 보호, 영업정지 후 예금인출 절차를 다룬 FAQ.",
        "owner": "yj",
    },
    # ============================================================
    # 예금보험금 안내·고객 미수령금 신청 (기능2·3) — inventory_dy.py 출신, 8페이지
    # ============================================================
    {
        "id": "ms_poss_dcmnt",
        "business": "예금보험금 안내",
        "sub_category": "예금보험금 안내 > 신청시 구비서류",
        "title": "신청시 구비서류",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtAplyPossDcmnt/selectScrn.do",
        "required": True,
        "note": "예솜24 2.1 신청서류 항목과 개념 일치",
        "summary": "본인·대리인·미성년자 등 신청인 유형별 구비서류 안내",
        "owner": "dy",
    },
    {
        "id": "ms_aply_proc",
        "business": "예금보험금 안내",
        "sub_category": "예금보험금 신청 절차 > 예금보험금 신청절차",
        "title": "예금보험금 신청절차",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtAplyProc/selectScrn.do",
        "required": True,
        "note": "예솜24 2.2 신청 절차 항목과 개념 일치",
        "summary": "보험사고 발생부터 지급공고·신청·지급까지의 절차 설명",
        "owner": "dy",
    },
    {
        "id": "ms_expln",
        "business": "예금보험금 안내",
        "sub_category": "예금보험금 안내 > 예금보험금이란?",
        "title": "예금보험금이란?",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtExpln/selectScrn.do",
        "required": True,
        "note": "예솜24 기능2 대표항목과 개념 일치",
        "summary": "예금보험금(가지급금·개산지급금)의 정의 설명",
        "owner": "dy",
    },
    {
        "id": "ms_trgt_fnst",
        "business": "예금보험금 안내",
        "sub_category": "예금보험금 안내 > 보험금 지급대상 금융회사",
        "title": "보험금 지급대상 금융회사",
        # 검색·조회 기능 페이지라 동적 검색 결과는 스냅샷에 안 담김 — 안내 문구·기본 목록만 수집 (한계 인지)
        "url": "https://www.kdic.or.kr/sp/dpstrprot/selectProtSystBamtGiveTrgtFnst.do",
        "required": False,
        "note": "파산금융회사별 검색 기능은 예솜24에 없던 내용 — 팀 협의로 포함 확정 (2026-07-13)",
        "summary": "파산금융회사별 예금보험금 지급대상 여부 검색 가능",
        "owner": "dy",
    },
    {
        "id": "uc_gudn",
        "business": "고객 미수령금 신청",
        "sub_category": "미수령금 통합조회/신청 > 고객미수령금",
        "title": "고객미수령금",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/ProtSystNramtInqAplyNramtGudn/selectScrn.do",
        "required": True,
        "note": "예솜24 기능3 대표항목과 제목·개념 일치",
        "summary": "미수령금의 정의와 인터넷·방문 신청 방법 안내",
        "owner": "dy",
    },
    {
        "id": "uc_tel_qust",
        "business": "고객 미수령금 신청",
        "sub_category": "미수령금통합신청 > 소개와 신청방법 안내 > 예금자 대상 전화문의 안내",
        "title": "예금자 대상 전화문의 안내",
        "url": "https://fins.kdic.or.kr/ua/aplygudn/DpstrTrgtTelQustGudn/selectScrn.do",
        "required": True,
        "note": "예솜24 3.2 방문 신청 항목과 유사한 전화 문의 채널",
        "summary": "명의 변경 시 문의 방법과 미수령금 관련 전화상담 안내",
        "owner": "dy",
    },
    {
        "id": "uc_itgr_aply",
        "business": "고객 미수령금 신청",
        "sub_category": "미수령금통합신청 > 소개와 신청방법 안내 > 안내",
        "title": "안내",
        "url": "https://fins.kdic.or.kr/ua/aplygudn/NramtItgrAplyItrdMthdGudn/selectScrn.do",
        "required": True,
        "note": "예솜24 기능3 대표항목 및 3.1·3.2 신청방법 항목과 개념 일치",
        "summary": "미수령금 종류와 온라인·오프라인 신청 방법 설명",
        "owner": "dy",
    },
    {
        "id": "uc_hrpe_hist",
        "business": "고객 미수령금 신청",
        "sub_category": "미수령금 통합조회/신청 > 상속인 금융거래조회",
        "title": "상속인 금융거래조회",
        "url": "https://www.kdic.or.kr/sp/dpstrprot/ProtSystHrpeHistInq/selectScrn.do",
        "required": False,
        "note": "상속인 대상 조회 기능은 예솜24에 없던 내용 — 팀 협의로 포함 확정 (2026-07-13)",
        "summary": "사망자(피상속인) 명의 미수령금을 상속인이 조회하는 서비스",
        "owner": "dy",
    },
    # ---- 파산금융회사 정보 검색 6건 — uc_gudn의 '파산금융기관 정보 검색' 버튼 연결
    # 페이지와 그 하위 카테고리. 팀 검수(2026-07-14)에서 범위 확장 확정.
    {
        "id": "uc_bkrp_fndt",
        "business": "고객 미수령금 신청",
        "sub_category": "미수령금 통합조회/신청 > 파산금융회사 정보 검색 > 파산재단현황",
        "title": "파산재단현황",
        "url": "https://www.kdic.or.kr/sp/sprtfund/selectBkrpFndtPsta.do",
        "required": False,
        "note": "uc_gudn '파산금융기관 정보 검색' 연결 페이지 — 팀 검수로 범위 확장 확정 (2026-07-14)",
        "summary": "금융권별·연도별·관할 지법별 파산재단 현황 통계표",
        "owner": "dy",
    },
    {
        "id": "uc_bkrp_mng",
        "business": "고객 미수령금 신청",
        "sub_category": "미수령금 통합조회/신청 > 파산금융회사 정보 검색 > 파산재단관리",
        "title": "파산재단관리",
        "url": "https://www.kdic.or.kr/sp/sprtfund/selectBkrpFndtMng.do",
        "required": False,
        "note": "uc_gudn '파산금융기관 정보 검색' 연결 페이지 — 팀 검수로 범위 확장 확정 (2026-07-14)",
        "summary": "파산금융회사 목록(금융권역·회사명·관재인·파산선고일·주소·연락처·진행상태) 검색",
        "owner": "dy",
    },
    {
        "id": "uc_bkrp_spcl_ast",
        "business": "고객 미수령금 신청",
        "sub_category": "미수령금 통합조회/신청 > 파산금융회사 정보 검색 > 특별자산현황",
        "title": "특별자산현황",
        "url": "https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchSpclAstPsta.do",
        "required": False,
        "note": "uc_gudn '파산금융기관 정보 검색' 연결 페이지 — 팀 검수로 범위 확장 확정 (2026-07-14)",
        "summary": "특별자산(파산재단 보유 비정형 자산)의 정의 및 유형 안내",
        "owner": "dy",
    },
    {
        "id": "uc_bkrp_spcl_mng",
        "business": "고객 미수령금 신청",
        "sub_category": "미수령금 통합조회/신청 > 파산금융회사 정보 검색 > 특별자산관리체계",
        "title": "특별자산관리체계",
        "url": "https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchSpclAstMngStm.do",
        "required": False,
        "note": "uc_gudn '파산금융기관 정보 검색' 연결 페이지 — 팀 검수로 범위 확장 확정 (2026-07-14)",
        "summary": "특별자산에 대한 채권보전조치 및 관리강화 체계 안내",
        "owner": "dy",
    },
    {
        "id": "uc_bkrp_trst_psta",
        "business": "고객 미수령금 신청",
        "sub_category": "미수령금 통합조회/신청 > 파산금융회사 정보 검색 > 신탁부동산현황",
        "title": "신탁부동산현황",
        "url": "https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchTrstRlestPsta.do",
        "required": False,
        "note": "uc_gudn '파산금융기관 정보 검색' 연결 페이지 — 팀 검수로 범위 확장 확정 (2026-07-14)",
        "summary": "신탁부동산의 정의 및 유형 안내",
        "owner": "dy",
    },
    {
        "id": "uc_bkrp_trst_mng",
        "business": "고객 미수령금 신청",
        "sub_category": "미수령금 통합조회/신청 > 파산금융회사 정보 검색 > 신탁부동산관리체계",
        "title": "신탁부동산관리체계",
        "url": "https://www.kdic.or.kr/sp/sprtfund/selectBkrpFncCoInfoSrchTrstRlestMngStm.do",
        "required": False,
        "note": "uc_gudn '파산금융기관 정보 검색' 연결 페이지 — 팀 검수로 범위 확장 확정 (2026-07-14)",
        "summary": "신탁부동산 책임회수관리시스템과 단계별 관리절차 안내",
        "owner": "dy",
    },
    # ============================================================
    # 착오송금 반환 신청 (기능4) — page_inventory_jh.py 출신 7건 + 사전조사 문서
    # 누락분 8건 추가 (2026-07-13), 15페이지. required·note는 사전조사 문서 기준.
    # ============================================================
    {
        "id": "kmrs_itrd",
        "business": "착오송금 반환 신청",
        "sub_category": "제도란",
        "title": "착오송금반환지원 제도란",
        "url": "https://www.kdic.or.kr/sp/kmrs/kmrsItrd/selectScrn.do",
        "required": True,
        "note": "예솜24 기능4 대표항목과 개념 일치 (영상 데이터 — media_summary_jh.json 참조)",
        "summary": "착오송금 반환지원 제도 소개 안내영상 페이지. '잘못 보낸 돈 되찾기 서비스'가 착오송금인이 실수로 잘못 보낸 돈을 최소 비용으로 빠르게 되찾도록 돕는 제도임을 영상으로 설명한다.",
        "owner": "jh",
    },
    {
        "id": "kmrs_proc",
        "business": "착오송금 반환 신청",
        "sub_category": "절차",
        "title": "착오송금반환지원 절차",
        "url": "https://www.kdic.or.kr/sp/kmrs/kmrsItrdProc/selectScrn.do",
        "required": True,
        "note": "예솜24 4.1 반환지원 절차 항목과 문구가 거의 동일",
        "summary": "착오송금 반환지원 5단계 절차를 설명한다: 반환지원 신청(채권매입) → 중앙행정기관·금융회사 통한 수취인 정보 확인 → 자진반환 권유 → 미반환 시 법원 지급명령 → 회수액에서 비용 차감 후 잔액 반환.",
        "owner": "jh",
    },
    {
        "id": "kmrs_apply_mthd",
        "business": "착오송금 반환 신청",
        "sub_category": "신청방법",
        "title": "착오송금반환지원 신청방법",
        "url": "https://www.kdic.or.kr/sp/kmrs/kmrsItrdAplyMthd/selectScrn.do",
        "required": True,
        "note": "예솜24 4.2 신청방법 항목과 개념 일치",
        "summary": "온라인 신청(fins.kdic.or.kr, PC만 지원, 공동인증서·이체확인증 필요)과 방문 신청(서울 중구 청계천로 30 1층, 1588-0037, 신분증·이체확인증 지참) 방법을 안내한다.",
        "owner": "jh",
    },
    {
        "id": "faq_msdr_apply",
        "business": "착오송금 반환 신청",
        "sub_category": "FAQ_반환지원신청",
        "title": "FAQ - 착오송금반환지원신청",
        "url": "https://fins.kdic.or.kr/cm/bbs/selectFaqMsdrGvbkAply.do",
        "required": True,
        "note": "예솜24 4.1·4.2 항목과 개념이 일치하며 실무 세부사항 보강",
        "summary": "착오송금 반환지원 신청 FAQ. 지원대상 금액(건당 5만원~1억원, 송금일로부터 1년 이내 신청), 지원 제외 사유(관련 소송 진행·완료, 수취인 휴·폐업 법인 또는 회생·파산, 계좌 압류 등), 공동인증서 문제 해결, 매입계약 해제 사유 등을 문답으로 다룬다.",
        "owner": "jh",
    },
    {
        "id": "faq_top10",
        "business": "착오송금 반환 신청",
        "sub_category": "FAQ_TOP10",
        "title": "고객센터 FAQ TOP 10",
        "url": "https://fins.kdic.or.kr/cm/bbs/selectFaqTop10.do",
        "required": True,
        "note": "예솜24 착오송금반환지원 절차 항목과 개념 일치 — 최다조회 질문 10건",
        "summary": "착오송금 반환지원 최다조회 질문 10건. 반환 소요기간(접수일로부터 약 2개월), 지원대상 금액(5만원~1억원), 지원 제외 사유, 적용대상 송금·수취기관(은행·금융투자회사·종금사·저축은행·신협·새마을금고·간편송금업자 등)을 다룬다.",
        "owner": "jh",
    },
    {
        "id": "receiver_attention",
        "business": "착오송금 반환 신청",
        "sub_category": "수취인_유의사항",
        "title": "착오송금수취인 유의사항",
        "url": "https://fins.kdic.or.kr/ir/addrse/AddrseAttnMttr/selectScrn.do",
        "required": True,
        "note": "예솜24 착오송금수취인 이의제기·환급신청 항목과 개념 일치",
        "summary": "착오송금 수취인 유의사항. 자진반환 기한(양도통지문 송달일로부터 2주), 기한 내 미반환 시 법원 지급명령 절차, 이의제기 방법(온라인 메뉴 또는 방문), 이체수수료 환급 신청(팩스 02-758-0270·이메일 kmrs@kdic.or.kr·방문), 지급명령 확정 후 강제집행·가압류 가능성을 안내한다.",
        "owner": "jh",
    },
    {
        "id": "receiver_docs",
        "business": "착오송금 반환 신청",
        "sub_category": "구비서류_수취인",
        "title": "구비서류안내 - 착오송금수취인",
        "url": "https://fins.kdic.or.kr/ir/aplygudn/MsdrAddrsePossDcmntGudn/selectScrn.do",
        "required": True,
        "note": "예솜24 이의제기·환급신청 구비서류 항목과 개념 일치 (첨부파일)",
        "summary": "착오송금 수취인용 서식 안내. 반환요구 이의제기서와 이체수수료 환급신청서의 온라인·방문 신청 방법, HWP·PDF 서식 다운로드, 신청 기한(자진반환 기한인 양도통지서 송달 후 2주 내)을 표로 정리한다.",
        "owner": "jh",
    },
    # --- 이하 8건: 사전조사 문서 대조로 발견된 누락분 (2026-07-13 추가) ---
    {
        "id": "sender_docs",
        "business": "착오송금 반환 신청",
        "sub_category": "구비서류_착오송금인",
        "title": "구비서류안내 - 착오송금인",
        "url": "https://fins.kdic.or.kr/ir/aplygudn/MsdrprPossDcmntGudn/selectScrn.do",
        "required": True,
        "note": "예솜24 착오송금인 신청방법 하위 구비서류 항목과 개념 일치 (첨부파일)",
        "summary": "착오송금인 신청인 유형별(본인·대리인·법인 등) 구비서류를 표로 정리한다. 반환지원 신청서, 금융거래정보 제공 요구(동의)서, 채권양도통지 위임장 등 서식의 HWP·PDF 다운로드와 유형별 신청서 샘플을 제공한다.",
        "owner": "jh",
    },
    {
        "id": "mtrs_gvbk_proc",
        "business": "착오송금 반환 신청",
        "sub_category": "소개와 방법안내 > 반환지원절차",
        "title": "반환지원절차",
        "url": "https://fins.kdic.or.kr/ir/aplygudn/MtrsGvbkSprtProc/selectScrn.do",
        "required": True,
        "note": "예솜24 반환지원 절차 항목과 절차 순서까지 일치",
        "summary": "금융안심포털의 반환지원 5단계 절차 안내(채권매입 → 수취인 연락처·주소 확보 → 자진반환 권유 → 지급명령 → 비용 공제 후 잔액 반환). 캐릭터(예툰이·예솜이) 스토리텔링 설명이 포함된다.",
        "owner": "jh",
    },
    {
        "id": "mtrs_rel_law",
        "business": "착오송금 반환 신청",
        "sub_category": "소개와 방법안내 > 관련법령 및 규정",
        "title": "관련법령 및 규정",
        "url": "https://fins.kdic.or.kr/ir/aplygudn/MtrsRelLawoRgul/selectScrn.do",
        "required": True,
        "note": "예솜24 기능4 대표항목 답변이 직접 지목한 법령·규정 메뉴 (법령링크 — 근거제시 시 추가 전처리·수집 필요)",
        "summary": "착오송금 반환지원 관련 법령·규정 모음. 예금자보호법(법률 제20431호, 2024-09-10 시행)·동 시행령(대통령령 제35228호)·착오송금반환지원 규정·시행세칙으로의 바로가기 링크를 제공한다(전문은 외부 링크·내장 문서).",
        "owner": "jh",
    },
    {
        "id": "mtrs_stut_chc",
        "business": "착오송금 반환 신청",
        "sub_category": "소개와 방법안내 > 상황선택",
        "title": "상황선택",
        "url": "https://fins.kdic.or.kr/ir/aplygudn/MtrsStutChc/selectScrn.do",
        "required": True,
        "note": "예솜24 착오송금인·수취인 분기 구조와 일치 (세부링크 로그인 필요 — 진입화면만 수집, 세부는 링크 안내)",
        "summary": "착오송금인('돈을 잘못 보냈어요' — 신청자격 확인·바로 신청)과 착오송금수취인('모르는 돈을 받았어요' — 이의제기·채무잔액 확인·이체수수료 환급신청·반환 확인)으로 메뉴를 분기하는 진입화면.",
        "owner": "jh",
    },
    {
        "id": "mtrs_vst_rcpt",
        "business": "착오송금 반환 신청",
        "sub_category": "소개와 방법안내 > 방문접수안내",
        "title": "방문접수안내",
        "url": "https://fins.kdic.or.kr/ir/aplygudn/MtrsVstRcptGudn/selectScrn.do",
        "required": True,
        "note": "예솜24 4.4 방문 신청 항목과 개념·주소 일치",
        "summary": "방문접수 안내. 운영시간(평일 09:00~17:00, 점심 12~13시), 5단계 절차(센터방문 → 신청서 제출 → 접수 → 반환지원대상 심사·채권매입 → 반환지원 진행), 본사 고객센터(서울 중구 청계천로 30 지하1층) 위치와 지하철·버스 교통편을 담는다.",
        "owner": "jh",
    },
    {
        "id": "sender_attention",
        "business": "착오송금 반환 신청",
        "sub_category": "착오송금인 > 유의사항",
        "title": "착오송금인 유의사항",
        "url": "https://fins.kdic.or.kr/ir/msdrpr/MsdrprAttnMttr/selectScrn.do",
        "required": True,
        "note": "예솜24 착오송금인 신청방법 항목의 신청대상·제외사유와 개념 일치",
        "summary": "착오송금인 유의사항. 신청대상(건당 5만원~1억원, 착오송금일로부터 1년 이내, 금융회사 반환신청 선행 필요), 회수 관련 비용률 예시(10만원 8~18%·100만원 4~13%·1,000만원 3.5~8%), 반환지원 제외 대상(정부·지자체·한국은행 등 기관, 소송 진행·완료자, 송금 후 사망자 등)을 안내한다.",
        "owner": "jh",
    },
    {
        "id": "sender_qlfc_check",
        "business": "착오송금 반환 신청",
        "sub_category": "착오송금인 > 반환지원 신청하기 > 신청대상여부 확인",
        "title": "신청대상여부 확인 (자가진단)",
        "url": "https://fins.kdic.or.kr/ir/msdrpr/selectAplyQlfcIdntyRslt.do",
        "required": True,
        "note": "예솜24 문서가 직접 예상한 화면 — 7개 항목 체크로 신청대상 여부 자가진단",
        "summary": "반환지원 신청대상 여부 자가진단 화면. 착오송금액(건당 5만원~1억원), 착오송금일(2021-07-06 이후), 신청기한(1년 이내), 금융회사 반환신청 선행·미반환 통보 여부 등 7개 항목을 체크해 대상/비대상을 확인한다.",
        "owner": "jh",
    },
    {
        "id": "kmrs_aply_trgt",
        "business": "착오송금 반환 신청",
        "sub_category": "착오송금 반환지원제도 > 착오송금반환지원 신청대상",
        "title": "착오송금반환지원 신청대상",
        "url": "https://www.kdic.or.kr/sp/kmrs/kmrsItrdAplyTrgt/selectScrn.do",
        "required": False,
        "note": "구체적 금액한도(5만~1억원)·신청기한·제외사유는 예솜24에 없던 내용 — 분석필요",
        "summary": "착오송금 반환지원 신청대상 기준을 문답형으로 안내한다. 신청 가능 금액 한도(건당 5만원 이상 1억원 이하)와 신청기한(잘못 이체한 날로부터 1년 이내) 등을 담는다.",
        "owner": "jh",
    },
    # ============================================================
    # 은닉재산 신고 (기능6) — inventory_hw.py 출신, 4페이지
    # (hw의 채무조정 8건은 jy 수집본과 중복이라 dr_* 구역으로 통합 — 파일 상단 정리 이력 참조)
    # ============================================================
    {
        "id": "ha_center",
        "business": "은닉재산 신고",
        "sub_category": "금융부실관련자 은닉재산신고",
        "title": "신고센터",
        "url": "https://www.kdic.or.kr/sp/sprtfund/SprtFndCncmDclrGudn/selectScrn.do",
        "required": True,
        "note": "예솜24 기능6 대표항목과 완전 일치 (포상금 산정기준 최대 30억원 등)",
        "summary": "은닉재산 신고센터 안내. 금융부실관련자 은닉재산 신고 시 회수기여도에 따라 회수금액의 5~20%를 구간별 차등 지급(최고한도 30억원)하는 포상금 기준표와 자동계산기, 신고 실적(제보 511건·발견재산 회수 918억원·포상금 67.6억원, 2025-12 기준)을 담는다.",
        "owner": "hw",
    },
    {
        "id": "ha_faq_dclr",
        "business": "은닉재산 신고",
        "sub_category": "고객센터 > FAQ",
        "title": "은닉재산신고 FAQ",
        "url": "https://fins.kdic.or.kr/cm/bbs/selectFaqCncmPrptDclr.do",
        "required": True,
        "note": "포상금 지급기준표, 신고 절차, 비밀보장 원칙 FAQ",
        "summary": "은닉재산신고 FAQ. 포상금 지급 기준표(회수기여금액 구간별 5~20%), 지급 절차(조사·회수 → 회수비용 공제 → 기여도 평가 → 법원 지급결정 → 지급), 포상 제외 사유, 상담전화(1588-0037, 02-758-0102~4)를 문답으로 안내한다.",
        "owner": "hw",
    },
    {
        "id": "ha_ilgl_intro",
        "business": "은닉재산 신고",
        "sub_category": "금융부실관련자 불법행위신고",
        "title": "신고센터 소개",
        "url": "https://www.kdic.or.kr/sp/sprtfund/SprtFndIvsfalUnrlIlglDclrGudn/selectScrn.do",
        "required": False,
        "note": "횡령·배임 등 별도 신고대상을 다루는 인접 제도 안내",
        "summary": "금융부실관련자의 횡령·배임 등 불법행위 신고센터 소개. 신고 방식(상담전화 02-758-0797, 우편·방문(중구 청계천로 30 조사국), 팩스 02-758-0798, 이메일 invest@kdic.or.kr)과 신고서 양식 다운로드를 제공하며, 접수 시 부실책임조사·검찰 수사의뢰로 이어진다.",
        "owner": "hw",
    },
    {
        "id": "ha_status_agree",
        "business": "은닉재산 신고",
        "sub_category": "부실책임조사",
        "title": "부실책임조사 진행현황 조회 (개인정보 동의)",
        "url": "https://www.kdic.or.kr/voc/userDataUsingAgree",
        "required": False,
        "note": "조사 진행현황 조회를 위한 동의 화면 (동적/로그인 여부 실측 필요)",
        "summary": "부실책임조사 진행현황 조회를 위한 개인정보 수집·이용 동의 화면. 수집 목적(민원처리·정보공개·개인정보 보호업무), 수집 항목(필수: 성명·휴대전화·이메일·생년월일 / 선택: 주소·전화·팩스), 보유기간(10년), 동의 거부 권리와 불이익을 고지한다.",
        "owner": "hw",
    },
    # ============================================================
    # 채무조정 안내 (기능5) — jy 수집본 채택, 8페이지
    # (hw·jy 중복 수집 통합: 본문 데이터는 jy(구 DEBT-*), required·note는 hw 큐레이션)
    # ============================================================
    {
        "id": "dr_system",
        "business": "채무조정 안내",
        "sub_category": "채무조정제도",
        "title": "채무조정제도",
        "url": "https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtLbltAjmtSyst/selectScrn.do",
        "required": True,
        "note": "예솜24 기능5 대표항목과 개념 일치 (신청자격, 구비서류 등)",
        "summary": "예금보험공사의 채무조정 제도(2001년부터 운영) 개요. 파산 금융회사 채무자 중 변제를 기대할 수 없는 주채무자·보증채무자의 신청자격, 본인·대리인 신청 시 구비서류, 신청 불가 사유(총 회수가능액이 총 채무액 이상, 재산 도피·은닉 등)를 안내한다.",
        "owner": "jy",
    },
    {
        "id": "dr_info_aply",
        "business": "채무조정 안내",
        "sub_category": "채무정보 조회 및 상담신청",
        "title": "채무정보 조회 ＆ 상담신청",
        "url": "https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtLbltInfoInqDscsnAply/selectScrn.do",
        "required": True,
        "note": "예솜24 5.2 채무 확인 방법 항목과 동일한 목적의 온라인 채널",
        "summary": "간편인증 등 본인인증으로 파산금융회사·㈜케이알앤씨(KR&C) 채무 보유 여부를 온라인 조회하고, 채무가 있으면 채무조정 상담을 신청하는 절차(조회 → 본인확인 → 상담신청 → 담당자 유선 상담)를 안내한다.",
        "owner": "jy",
    },
    {
        "id": "dr_kruc",
        "business": "채무조정 안내",
        "sub_category": "KR&C 채무조정",
        "title": "채무조정",
        "url": "https://www.kdic.or.kr/di/relsite/PbcrKrncLblarb/selectScrn.do",
        "required": True,
        "note": "예솜24 5.1-5.3-5.4와 동일 개념을 KR&C 페이지가 더 상세히 제공",
        "summary": "케이알앤씨(KR&C)가 파산재단·부실금융회사에서 인수한 대출채권 채무자 대상 채무조정 안내. 신청자격(변제를 기대할 수 없는 주채무자·보증채무자), 신청 불가 사유 4가지, 본인·대리인 구비서류(채무조정신청서, 해제조건부 채무면제 각서 등)를 담는다.",
        "owner": "jy",
    },
    {
        "id": "dr_credit_sprt",
        "business": "채무조정 안내",
        "sub_category": "신용회복 지원",
        "title": "신용회복 지원",
        "url": "https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtCredRcvrySprt/selectScrn.do",
        "required": False,
        "note": "신용회복위원회를 통한 지원 제도 안내 (기관 비교표 포함)",
        "summary": "개인신용회복지원제도 안내. 파산재단이 2005년 8월 신용회복지원 협약에 가입해 채무자의 상환기간 연장·분할상환·이자율 조정·변제기 유예·채무감면을 지원하며, 신청은 개별 금융회사가 아닌 신용회복위원회(ccrs.or.kr)에 한다는 점을 강조한다.",
        "owner": "jy",
    },
    {
        "id": "dr_psn_br",
        "business": "채무조정 안내",
        "sub_category": "파산면책",
        "title": "파산면책",
        "url": "https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtPsnBr/selectScrn.do",
        "required": False,
        "note": "법원을 통한 개인파산 절차 안내 (예솜24 원본 외 범위)",
        "summary": "법원을 통한 개인파산·면책 제도 안내. 파산절차(채무자 재산으로 파산재단을 형성해 채권자 배당)와 면책절차(잔여 채무의 변제책임을 재판으로 면제해 경제적 재출발 도모)의 개념, 파산·면책 동시 신청, 파산선고의 불이익(공무원·부동산중개업자 등 자격 제한)과 소멸을 설명한다.",
        "owner": "jy",
    },
    {
        "id": "dr_psn_rg",
        "business": "채무조정 안내",
        "sub_category": "개인회생",
        "title": "개인회생",
        "url": "https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtPsnRg/selectScrn.do",
        "required": False,
        "note": "법원을 통한 개인회생 절차(3~5년 분할상환) 안내",
        "summary": "법원을 통한 개인회생 제도 안내. 신청자격(정기 수입이 있는 급여·영업소득자), 채무총액 한도(무담보 10억원·담보부 15억원), 변제기간(최장 5년), 지급불능 요건, 종전 면책결정 후 5년 경과 요건과 개인파산과의 비교표를 담는다.",
        "owner": "jy",
    },
    {
        "id": "dr_debt_cert",
        "business": "채무조정 안내",
        "sub_category": "부채증명원 및 금융거래정보신청",
        "title": "부채증명원/금융거래정보신청",
        "url": "https://www.kdic.or.kr/sp/sprtfund/SprtFndDebtDlngAplyGudn/selectScrn.do",
        "required": False,
        "note": "파산금융회사 채무자의 부채증명원 공식 발급 절차",
        "summary": "파산금융회사 채무자의 부채증명원·금융거래정보 발급 서비스 안내. 인터넷 신청 원칙(공인인증서·휴대폰 인증), 방문 신청 시 본인·대리인 구비서류와 신청서 양식 다운로드, 법적 종결된 파산재단은 부채증명원만 신청 가능함을 안내한다.",
        "owner": "jy",
    },
    {
        "id": "dr_faq_inq",
        "business": "채무조정 안내",
        "sub_category": "채무정보조회 FAQ",
        "title": "채무정보조회 FAQ",
        "url": "https://fins.kdic.or.kr/cm/bbs/selectFaqLbltInfoInq.do",
        "required": False,
        "note": "온라인 채무정보 조회 방법을 안내하는 FAQ 게시판",
        "summary": "온라인 채무정보 조회 FAQ. 모바일 조회 방법(휴대폰인증), 서비스 운영시간 오류 시 조치(브라우저 재접속·임시파일 삭제), 공동인증서 폐기 오류 해결 등 이용 중 문제 해결법을 문답으로 안내한다.",
        "owner": "jy",
    },
]


def pages_for(owner):
    """owner 접미사(hw/yj/dy/jh/jy)로 담당 페이지만 필터링."""
    return [p for p in PAGES if p["owner"] == owner]


if __name__ == "__main__":
    # 자체검증 — 항목 추가·수정 후 python3 src/inventory.py 로 실행
    ids = [p["id"] for p in PAGES]
    dup_ids = {i for i in ids if ids.count(i) > 1}
    assert not dup_ids, f"id 중복: {dup_ids}"
    urls = [p["url"] for p in PAGES]
    dup_urls = {u for u in urls if urls.count(u) > 1}
    assert not dup_urls, f"url 중복 (복붙 실수?): {dup_urls}"
    bad_biz = [p["id"] for p in PAGES if p["business"] not in BUSINESSES]
    assert not bad_biz, f"business가 BUSINESSES에 없음: {bad_biz}"
    print(f"self-check ok — {len(PAGES)}페이지, id·url 중복 없음")
