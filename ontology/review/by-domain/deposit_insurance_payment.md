# 예금보험금 안내 Ontology 검토 패킷

> 이 패킷은 검토를 돕는 생성물입니다. 실제 승인 상태는 `../canonical-ontology-decisions.json`만 사용합니다.
> 어떤 항목도 승인 전에는 검색·답변·Supabase/RAG에 자동 반영되지 않습니다.

## 범위

- 공식 문서: 4개
- canonical 엔터티 결정: 4개
- source-verified 핵심 사실 결정: 0개
- source-verified 보강 후보: 3개 (core fact 자동 승격 없음)

## 검토 기준

- 용어가 공식적이고 안정적인 업무 개념인지 확인합니다.
- 클래스·상위 Service·관계·값·조건이 원문과 일치하는지 확인합니다.
- 인용과 content hash가 현재 원문을 정확히 가리키는지 확인합니다.
- `통상`, 기한, 금액, 예외 조건을 과장하거나 누락하지 않습니다.

## Canonical 엔터티

### `actor:deposit_insurance_payment_target_institution` — 보험금 지급대상 금융회사

- 클래스: `Actor`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `ms_trgt_fnst`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:deposit_insurance_payment` — 예금보험금

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `ms_expln`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `procedure:deposit_insurance_payment_application` — 예금보험금 신청 절차

- 클래스: `Procedure`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `ms_aply_proc`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `required_document:deposit_insurance_application` — 예금보험금 신청 구비서류

- 클래스: `RequiredDocument`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `ms_poss_dcmnt`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

## Source-verified 핵심 사실

- 승인된 핵심 사실이 없습니다. 아래 보강 후보를 별도로 검토합니다.

## Source-verified 사실 보강 후보

### `candidate_fact:deposit_insurance_claim_right_expiry` — 예금보험금 청구권 행사기한 · 지급개시일로부터 5년

- 대상: `concept:deposit_insurance_payment`
- 관계: `claim_right_expires_after`
- 값: `{"anchor": "deposit_insurance_payment_start_date", "condition": "if_not_exercised", "type": "Duration", "unit": "year", "value": 5}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [ms_expln](https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtExpln/selectScrn.do)
- 원문 해시: `8a9ad3e4e641bff847e916ef4810d48562abc5fe0834288b074968f295c758a6`
- 인용: 예금자등의 예금보험금청구권은 「예금자보호법」제31조제7항의 규정에 의하여 예금보험금지급 개시일로부터 5년간 행사하지 아니하면 시효로 인하여 소멸하기 때문에 예금보험금이 지급되지 않습니다.
- 검토 초점: 법정 시효의 예외·중단 사유가 있는지 도메인 담당자가 확인한다.
- [ ] core fact 승격 제안  [ ] 반려  [ ] 수정 요청
- 메모: 

### `candidate_fact:deposit_insurance_online_application_exclusion` — 예금보험금 인터넷 신청 제외 대상 · 미성년자 및 법인

- 대상: `concept:deposit_insurance_payment`
- 관계: `online_application_excludes`
- 값: `{"type": "ActorCategorySet", "values": ["minor", "corporation"]}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [ms_expln](https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtExpln/selectScrn.do)
- 원문 해시: `8a9ad3e4e641bff847e916ef4810d48562abc5fe0834288b074968f295c758a6`
- 인용: 공사 홈페이지 접속을 통한 인터넷 신청은 미성년자 및 법인의 경우에는 불가하오니 이점 참고하시기 바랍니다.
- 검토 초점: 인터넷 신청만의 제한인지, 대리·방문 신청의 제한으로 오해되지 않는지 검토한다.
- [ ] core fact 승격 제안  [ ] 반려  [ ] 수정 요청
- 메모: 

### `candidate_fact:deposit_insurance_typical_payment_timing` — 예금보험금 신청 후 통상 입금 시점 · 다음 영업일 이내

- 대상: `procedure:deposit_insurance_payment_application`
- 관계: `has_typical_processing_time`
- 값: `{"anchor": "application", "qualifier": "typically", "type": "Duration", "unit": "business_day", "value": 1}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [ms_aply_proc](https://www.kdic.or.kr/sp/dpstrprot/DpsmIbamtAplyProc/selectScrn.do)
- 원문 해시: `b398772e990453abd83695a258c409ec8a9dc4e6dbd19844a64aba34a498bba0`
- 인용: 통상 익영업일내에 예금보험금이 입금 완료됨
- 검토 초점: ‘통상’이라는 비보장 표현을 반드시 보존하고, 지급보류·추가 확인 사례에는 적용하지 않는다.
- [ ] core fact 승격 제안  [ ] 반려  [ ] 수정 요청
- 메모: 

