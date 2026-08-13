# 착오송금 반환 신청 Ontology 검토 패킷

> 이 패킷은 검토를 돕는 생성물입니다. 실제 승인 상태는 `../canonical-ontology-decisions.json`만 사용합니다.
> 어떤 항목도 승인 전에는 검색·답변·Supabase/RAG에 자동 반영되지 않습니다.

## 범위

- 공식 문서: 15개
- canonical 엔터티 결정: 11개
- source-verified 핵심 사실 결정: 7개
- source-verified 보강 후보: 0개 (core fact 자동 승격 없음)

## 검토 기준

- 용어가 공식적이고 안정적인 업무 개념인지 확인합니다.
- 클래스·상위 Service·관계·값·조건이 원문과 일치하는지 확인합니다.
- 인용과 content hash가 현재 원문을 정확히 가리키는지 확인합니다.
- `통상`, 기한, 금액, 예외 조건을 과장하거나 누락하지 않습니다.

## Canonical 엔터티

### `actor:mistaken_remitter` — 착오송금인

- 클래스: `Actor`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `sender_attention`, `sender_qlfc_check`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:mistaken_remittance_recipient_cautions` — 착오송금 수취인 유의사항

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `receiver_attention`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:mistaken_remittance_regulations` — 착오송금 반환지원 관련 법령·규정

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `mtrs_rel_law`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:mistaken_remitter_cautions` — 착오송금인 유의사항

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `sender_attention`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `contact:mistaken_remittance_visit` — 착오송금 반환지원 방문접수

- 클래스: `ContactPoint`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `mtrs_vst_rcpt`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `eligibility:mistaken_remittance_return_support` — 착오송금 반환지원 신청대상

- 클래스: `EligibilityRule`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `kmrs_aply_trgt`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `eligibility:mistaken_remittance_self_check` — 착오송금 반환지원 대상 자가진단

- 클래스: `EligibilityRule`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `sender_qlfc_check`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `procedure:mistaken_remittance_application` — 착오송금 반환지원 신청방법

- 클래스: `Procedure`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `kmrs_apply_mthd`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `procedure:mistaken_remittance_return_support` — 착오송금 반환지원 절차

- 클래스: `Procedure`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `kmrs_proc`, `mtrs_gvbk_proc`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `required_document:mistaken_remittance_recipient_forms` — 착오송금 수취인 구비서류

- 클래스: `RequiredDocument`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `receiver_docs`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `required_document:mistaken_remitter_application` — 착오송금인 신청 구비서류

- 클래스: `RequiredDocument`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `sender_docs`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

## Source-verified 핵심 사실

### `fact:mistaken_remittance_amount_range`

- 대상: `eligibility:mistaken_remittance_return_support`
- 관계: `has_monetary_range`
- 값: `{"currency": "KRW", "inclusive": true, "maximum": 100000000, "minimum": 50000, "type": "MonetaryRange"}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [kmrs_aply_trgt](https://www.kdic.or.kr/sp/kmrs/kmrsItrdAplyTrgt/selectScrn.do)
- 원문 해시: `59dc690d463cc8be1cc8bb64b0d94ffddd53dbe50698493be796c8c21e05f740`
- 인용: 신청 가능 한도는 착오송금 건당 5만원 이상 ~ 1억원 이하 입니다.
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `fact:mistaken_remittance_application_deadline`

- 대상: `eligibility:mistaken_remittance_return_support`
- 관계: `has_time_rule`
- 값: `{"anchor": "mistaken_remittance_date", "inclusive_text": "이내", "type": "Duration", "unit": "year", "value": 1}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [kmrs_aply_trgt](https://www.kdic.or.kr/sp/kmrs/kmrsItrdAplyTrgt/selectScrn.do)
- 원문 해시: `59dc690d463cc8be1cc8bb64b0d94ffddd53dbe50698493be796c8c21e05f740`
- 인용: 잘못 이체한 날로부터 1년 이내까지 신청 가능합니다
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `fact:mistaken_remittance_prior_return_request`

- 대상: `eligibility:mistaken_remittance_return_support`
- 관계: `requires_prior_action`
- 값: `{"action": "request_return_via_transfer_provider", "must_remain_unreturned": true, "type": "Requirement"}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [kmrs_aply_trgt](https://www.kdic.or.kr/sp/kmrs/kmrsItrdAplyTrgt/selectScrn.do)
- 원문 해시: `59dc690d463cc8be1cc8bb64b0d94ffddd53dbe50698493be796c8c21e05f740`
- 인용: 이체 시 이용한 금융회사, 간편송금업체 등을 통해 먼저 반환을 요청해야 합니다.
금융회사, 간편송금업체 등을 통해서도 돌려받지 못한 경우 신청 가능합니다.
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `fact:mistaken_remittance_supported_date_threshold`

- 대상: `eligibility:mistaken_remittance_self_check`
- 관계: `has_date_threshold`
- 값: `{"source_operator": "이후", "type": "DateThreshold", "value": "2021-07-06"}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [sender_qlfc_check](https://fins.kdic.or.kr/ir/msdrpr/selectAplyQlfcIdntyRslt.do)
- 원문 해시: `c6364958af05b92718e2fdc11be7a6d69921aaf04eed20a3f7bb869499b11e05`
- 인용: 착오송금일이 2021년 7월 6일 이후입니까?
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `fact:recipient_voluntary_return_deadline`

- 대상: `concept:mistaken_remittance_recipient_cautions`
- 관계: `has_time_rule`
- 값: `{"anchor": "assignment_notice_delivery", "type": "Duration", "unit": "week", "value": 2}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [receiver_attention](https://fins.kdic.or.kr/ir/addrse/AddrseAttnMttr/selectScrn.do)
- 원문 해시: `eef6c873be4dc583038bf1a4e3e394150b2933918a89740e8f92c9580cc7a4e4`
- 인용: 자진반환 기한(양도통지문 송달일로부터 2주) 내에 반환해주시기 바랍니다.
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `fact:visit_reception_hours`

- 대상: `contact:mistaken_remittance_visit`
- 관계: `has_operating_hours`
- 값: `{"days": "weekday", "end": "17:00", "start": "09:00", "type": "TimeWindow"}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [mtrs_vst_rcpt](https://fins.kdic.or.kr/ir/aplygudn/MtrsVstRcptGudn/selectScrn.do)
- 원문 해시: `81cc3ded70380a222d38b27fe3823e22cab56f56f94de34fc5a2fec01f653807`
- 인용: 방문접수는 평일 09:00 ~ 17:00까지 운영됩니다.
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `fact:visit_reception_lunch_break`

- 대상: `contact:mistaken_remittance_visit`
- 관계: `has_break_hours`
- 값: `{"end": "13:00", "start": "12:00", "type": "TimeWindow"}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [mtrs_vst_rcpt](https://fins.kdic.or.kr/ir/aplygudn/MtrsVstRcptGudn/selectScrn.do)
- 원문 해시: `81cc3ded70380a222d38b27fe3823e22cab56f56f94de34fc5a2fec01f653807`
- 인용: 점심시간 12:00 ~ 13:00
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

## Source-verified 사실 보강 후보

- 이 업무영역에는 별도 보강 후보가 없습니다.

