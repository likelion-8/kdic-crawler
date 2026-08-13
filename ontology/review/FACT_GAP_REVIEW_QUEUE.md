# Fact Coverage Gap Review Queue

> 이 문서는 예금보험금 안내·고객 미수령금 신청에서 발견한 source-verified fact 후보다.
> 모든 항목은 도메인 승인 전이며 `kdic-core-fact-proposals.json`이나 런타임 RAG에 자동 반영되지 않는다.

## 검토 기준

- 원문 인용이 후보의 의미·조건·범위를 충분히 뒷받침하는가?
- 값이 최신성·예외 조건을 포함한 사용자 답변용 사실로 안전한가?
- 승인한다면 기존 핵심 사실과 중복되지 않는가?
- `통상`, 특정 시점, 메뉴 전용 조건은 표현을 보존해야 하는가?

## 고객 미수령금 신청

### `candidate_fact:unclaimed_funds_categories` — 고객 미수령금 주요 종류 · 예금보험금·파산배당금·개산지급금 정산금

- 대상: `service:unclaimed_funds`
- 관계: `has_fund_categories`
- 값: `{"type": "CategorySet", "values": ["deposit_insurance_payment", "bankruptcy_dividend", "provisional_payment_settlement"]}`
- 원문: [uc_gudn](https://www.kdic.or.kr/sp/dpstrprot/ProtSystNramtInqAplyNramtGudn/selectScrn.do)
- 원문 해시: `290a4f552b8ee76b8f9202f0de8dcb78d32a2b31ee94d02151b1e47124dcd8b2`
- 인용: 고객 미수령금의 종류
예금보험금
예금보험에 가입한 금융회사가 예금의 지급정지, 영업 인·허가의 취소 등 보험사고로 인하여 고객의 예금을 지급할 수 없을 때 공사가 해당 금융회사를 대신하여 지급하는 보험금을 말합니다.
파산배당금
금융회사가 파산하는 경우 남은 자산을 현금화하여 채권자들에게 그 채권액 비율대로 배당하는 금액을 말합니다.
개산지급금 정산금
파산배당금 등으로 회수한 금액에서 소요비용을 공제한 금액이 수령한 개산지급금을 초과하는 때에 그 초과금액을 예금자에게 추가로 지급하는데, 이를 개산지급금 정산금이라고 합니다.
- 검토 초점: ‘주요 종류’가 완전한 목록인지와 카테고리 명칭을 사용자 답변에 그대로 쓸지 검토한다.
- [ ] core fact로 승인
- [ ] 반려
- [ ] 수정 요청
- 검토자 / 날짜: 
- 메모: 

### `candidate_fact:unclaimed_funds_definition` — 고객 미수령금의 정의 · 부실화 금융회사 예금자 등이 찾아가지 않은 금액

- 대상: `service:unclaimed_funds`
- 관계: `has_definition`
- 값: `{"type": "Definition", "meaning": "amount_not_collected_by_depositors_of_failed_financial_institutions"}`
- 원문: [uc_gudn](https://www.kdic.or.kr/sp/dpstrprot/ProtSystNramtInqAplyNramtGudn/selectScrn.do)
- 원문 해시: `290a4f552b8ee76b8f9202f0de8dcb78d32a2b31ee94d02151b1e47124dcd8b2`
- 인용: 부실화된 금융회사의 예금자 등이 찾아가지 아니한 금액을 말합니다.
- 검토 초점: 서비스 범위의 정의로 적절한지, 다른 미수령금 범주가 포함되는지 검토한다.
- [ ] core fact로 승인
- [ ] 반려
- [ ] 수정 요청
- 검토자 / 날짜: 
- 메모: 

### `candidate_fact:unclaimed_funds_unified_application_start` — 미수령금 전국 지급대행점 통합 신청 시작 · 2016년 10월

- 대상: `service:unclaimed_funds`
- 관계: `unified_application_available_from`
- 값: `{"type": "YearMonth", "value": "2016-10", "scope": "nationwide_any_payment_agency"}`
- 원문: [uc_gudn](https://www.kdic.or.kr/sp/dpstrprot/ProtSystNramtInqAplyNramtGudn/selectScrn.do)
- 원문 해시: `290a4f552b8ee76b8f9202f0de8dcb78d32a2b31ee94d02151b1e47124dcd8b2`
- 인용: 미수령금 종류별·부실금융회사별 구분없이 ‘16.10월부터 전국 지급대행점 어디에서든 미수령금을 통합 신청할 수 있도록 하였습니다.
- 검토 초점: 원문 표기 ‘16.10월을 2016-10으로 해석한 것이 맞는지와 현재 적용 여부를 검토한다.
- [ ] core fact로 승인
- [ ] 반려
- [ ] 수정 요청
- 검토자 / 날짜: 
- 메모: 

## 예금보험금 안내

### `candidate_fact:deposit_insurance_claim_right_expiry` — 예금보험금 청구권 행사기한 · 지급개시일로부터 5년

- 대상: `concept:deposit_insurance_payment`
- 관계: `claim_right_expires_after`
- 값: `{"type": "Duration", "value": 5, "unit": "year", "anchor": "deposit_insurance_payment_start_date", "condition": "if_not_exercised"}`
- 원문: [ms_expln](https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtExpln/selectScrn.do)
- 원문 해시: `8a9ad3e4e641bff847e916ef4810d48562abc5fe0834288b074968f295c758a6`
- 인용: 예금자등의 예금보험금청구권은 「예금자보호법」제31조제7항의 규정에 의하여 예금보험금지급 개시일로부터 5년간 행사하지 아니하면 시효로 인하여 소멸하기 때문에 예금보험금이 지급되지 않습니다.
- 검토 초점: 법정 시효의 예외·중단 사유가 있는지 도메인 담당자가 확인한다.
- [ ] core fact로 승인
- [ ] 반려
- [ ] 수정 요청
- 검토자 / 날짜: 
- 메모: 

### `candidate_fact:deposit_insurance_online_application_exclusion` — 예금보험금 인터넷 신청 제외 대상 · 미성년자 및 법인

- 대상: `concept:deposit_insurance_payment`
- 관계: `online_application_excludes`
- 값: `{"type": "ActorCategorySet", "values": ["minor", "corporation"]}`
- 원문: [ms_expln](https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtExpln/selectScrn.do)
- 원문 해시: `8a9ad3e4e641bff847e916ef4810d48562abc5fe0834288b074968f295c758a6`
- 인용: 공사 홈페이지 접속을 통한 인터넷 신청은 미성년자 및 법인의 경우에는 불가하오니 이점 참고하시기 바랍니다.
- 검토 초점: 인터넷 신청만의 제한인지, 대리·방문 신청의 제한으로 오해되지 않는지 검토한다.
- [ ] core fact로 승인
- [ ] 반려
- [ ] 수정 요청
- 검토자 / 날짜: 
- 메모: 

### `candidate_fact:deposit_insurance_typical_payment_timing` — 예금보험금 신청 후 통상 입금 시점 · 다음 영업일 이내

- 대상: `procedure:deposit_insurance_payment_application`
- 관계: `has_typical_processing_time`
- 값: `{"type": "Duration", "value": 1, "unit": "business_day", "qualifier": "typically", "anchor": "application"}`
- 원문: [ms_aply_proc](https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtAplyProc/selectScrn.do)
- 원문 해시: `b398772e990453abd83695a258c409ec8a9dc4e6dbd19844a64aba34a498bba0`
- 인용: 통상 익영업일내에 예금보험금이 입금 완료됨
- 검토 초점: ‘통상’이라는 비보장 표현을 반드시 보존하고, 지급보류·추가 확인 사례에는 적용하지 않는다.
- [ ] core fact로 승인
- [ ] 반려
- [ ] 수정 요청
- 검토자 / 날짜: 
- 메모: 

