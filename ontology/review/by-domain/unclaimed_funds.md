# 고객 미수령금 신청 Ontology 검토 패킷

> 이 패킷은 검토를 돕는 생성물입니다. 실제 승인 상태는 `../canonical-ontology-decisions.json`만 사용합니다.
> 어떤 항목도 승인 전에는 검색·답변·Supabase/RAG에 자동 반영되지 않습니다.

## 범위

- 공식 문서: 10개
- canonical 엔터티 결정: 10개
- source-verified 핵심 사실 결정: 0개
- source-verified 보강 후보: 3개 (core fact 자동 승격 없음)

## 검토 기준

- 용어가 공식적이고 안정적인 업무 개념인지 확인합니다.
- 클래스·상위 Service·관계·값·조건이 원문과 일치하는지 확인합니다.
- 인용과 content hash가 현재 원문을 정확히 가리키는지 확인합니다.
- `통상`, 기한, 금액, 예외 조건을 과장하거나 누락하지 않습니다.

## Canonical 엔터티

### `concept:bankrupt_financial_company_information_search` — 파산금융회사 정보 검색

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `uc_bkrp_fndt`, `uc_bkrp_mng`, `uc_bkrp_spcl_ast`, `uc_bkrp_spcl_mng`, `uc_bkrp_trst_mng`, `uc_bkrp_trst_psta`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:bankruptcy_estate_management` — 파산재단 관리

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `uc_bkrp_mng`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:bankruptcy_estate_status` — 파산재단 현황

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `uc_bkrp_fndt`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:special_asset_management_system` — 특별자산 관리체계

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `uc_bkrp_spcl_mng`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:special_asset_status` — 특별자산 현황

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `uc_bkrp_spcl_ast`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:trust_real_estate_management_system` — 신탁부동산 관리체계

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `uc_bkrp_trst_mng`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:trust_real_estate_status` — 신탁부동산 현황

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `uc_bkrp_trst_psta`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:unclaimed_funds_integrated_application` — 미수령금 통합신청

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `uc_itgr_aply`, `uc_tel_qust`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `contact:unclaimed_funds_phone` — 미수령금 전화문의

- 클래스: `ContactPoint`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `uc_tel_qust`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `service:heir_financial_transaction_inquiry` — 상속인 금융거래조회

- 클래스: `Service`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `uc_hrpe_hist`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

## Source-verified 핵심 사실

- 승인된 핵심 사실이 없습니다. 아래 보강 후보를 별도로 검토합니다.

## Source-verified 사실 보강 후보

### `candidate_fact:unclaimed_funds_categories` — 고객 미수령금 주요 종류 · 예금보험금·파산배당금·개산지급금 정산금

- 대상: `service:unclaimed_funds`
- 관계: `has_fund_categories`
- 값: `{"type": "CategorySet", "values": ["deposit_insurance_payment", "bankruptcy_dividend", "provisional_payment_settlement"]}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
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
- [ ] core fact 승격 제안  [ ] 반려  [ ] 수정 요청
- 메모: 

### `candidate_fact:unclaimed_funds_definition` — 고객 미수령금의 정의 · 부실화 금융회사 예금자 등이 찾아가지 않은 금액

- 대상: `service:unclaimed_funds`
- 관계: `has_definition`
- 값: `{"meaning": "amount_not_collected_by_depositors_of_failed_financial_institutions", "type": "Definition"}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [uc_gudn](https://www.kdic.or.kr/sp/dpstrprot/ProtSystNramtInqAplyNramtGudn/selectScrn.do)
- 원문 해시: `290a4f552b8ee76b8f9202f0de8dcb78d32a2b31ee94d02151b1e47124dcd8b2`
- 인용: 부실화된 금융회사의 예금자 등이 찾아가지 아니한 금액을 말합니다.
- 검토 초점: 서비스 범위의 정의로 적절한지, 다른 미수령금 범주가 포함되는지 검토한다.
- [ ] core fact 승격 제안  [ ] 반려  [ ] 수정 요청
- 메모: 

### `candidate_fact:unclaimed_funds_unified_application_start` — 미수령금 전국 지급대행점 통합 신청 시작 · 2016년 10월

- 대상: `service:unclaimed_funds`
- 관계: `unified_application_available_from`
- 값: `{"scope": "nationwide_any_payment_agency", "type": "YearMonth", "value": "2016-10"}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [uc_gudn](https://www.kdic.or.kr/sp/dpstrprot/ProtSystNramtInqAplyNramtGudn/selectScrn.do)
- 원문 해시: `290a4f552b8ee76b8f9202f0de8dcb78d32a2b31ee94d02151b1e47124dcd8b2`
- 인용: 미수령금 종류별·부실금융회사별 구분없이 ‘16.10월부터 전국 지급대행점 어디에서든 미수령금을 통합 신청할 수 있도록 하였습니다.
- 검토 초점: 원문 표기 ‘16.10월을 2016-10으로 해석한 것이 맞는지와 현재 적용 여부를 검토한다.
- [ ] core fact 승격 제안  [ ] 반려  [ ] 수정 요청
- 메모: 

