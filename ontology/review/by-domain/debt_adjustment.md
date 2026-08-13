# 채무조정 안내 Ontology 검토 패킷

> 이 패킷은 검토를 돕는 생성물입니다. 실제 승인 상태는 `../canonical-ontology-decisions.json`만 사용합니다.
> 어떤 항목도 승인 전에는 검색·답변·Supabase/RAG에 자동 반영되지 않습니다.

## 범위

- 공식 문서: 8개
- canonical 엔터티 결정: 5개
- source-verified 핵심 사실 결정: 4개
- source-verified 보강 후보: 0개 (core fact 자동 승격 없음)

## 검토 기준

- 용어가 공식적이고 안정적인 업무 개념인지 확인합니다.
- 클래스·상위 Service·관계·값·조건이 원문과 일치하는지 확인합니다.
- 인용과 content hash가 현재 원문을 정확히 가리키는지 확인합니다.
- `통상`, 기한, 금액, 예외 조건을 과장하거나 누락하지 않습니다.

## Canonical 엔터티

### `concept:bankruptcy_discharge` — 파산·면책

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dr_psn_br`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:individual_rehabilitation` — 개인회생

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dr_psn_rg`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `service:credit_recovery_support` — 신용회복 지원

- 클래스: `Service`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dr_credit_sprt`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `service:debt_certificate_financial_information_request` — 부채증명원·금융거래정보 신청

- 클래스: `Service`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dr_debt_cert`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `service:debt_information_inquiry_consultation` — 채무정보 조회·상담신청

- 클래스: `Service`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dr_info_aply`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

## Source-verified 핵심 사실

### `fact:individual_rehabilitation_income_requirement`

- 대상: `concept:individual_rehabilitation`
- 관계: `has_eligibility`
- 값: `{"requirement": "continuing_regular_reliable_income", "type": "Requirement"}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [dr_psn_rg](https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtPsnRg/selectScrn.do)
- 원문 해시: `9901d6f02393e4636842e0a032491c81b5740c3b4822176ea1da7ebba2fe4252`
- 인용: 정기적이고, 확실한 수입을 계속하여 얻을 가능성이 있는 사람이어야 합니다.
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `fact:individual_rehabilitation_repayment_period`

- 대상: `concept:individual_rehabilitation`
- 관계: `has_time_rule`
- 값: `{"maximum": 5, "type": "Duration", "unit": "year"}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [dr_psn_rg](https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtPsnRg/selectScrn.do)
- 원문 해시: `9901d6f02393e4636842e0a032491c81b5740c3b4822176ea1da7ebba2fe4252`
- 인용: 변제기간
5년을 초과할 수 없습니다.
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `fact:individual_rehabilitation_secured_debt_limit`

- 대상: `concept:individual_rehabilitation`
- 관계: `has_monetary_limit`
- 값: `{"currency": "KRW", "debt_type": "secured", "operator": "not_exceed", "type": "MonetaryValue", "value": 1500000000}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [dr_psn_rg](https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtPsnRg/selectScrn.do)
- 원문 해시: `9901d6f02393e4636842e0a032491c81b5740c3b4822176ea1da7ebba2fe4252`
- 인용: 무담보 채무의 경우 10억 원, 담보부 채무의 경우 15억 원을 넘지 않아야 합니다.
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `fact:individual_rehabilitation_unsecured_debt_limit`

- 대상: `concept:individual_rehabilitation`
- 관계: `has_monetary_limit`
- 값: `{"currency": "KRW", "debt_type": "unsecured", "operator": "not_exceed", "type": "MonetaryValue", "value": 1000000000}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [dr_psn_rg](https://www.kdic.or.kr/rb/lbltajmt/LbltAjmtSprtPsnRg/selectScrn.do)
- 원문 해시: `9901d6f02393e4636842e0a032491c81b5740c3b4822176ea1da7ebba2fe4252`
- 인용: 무담보 채무의 경우 10억 원, 담보부 채무의 경우 15억 원을 넘지 않아야 합니다.
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

## Source-verified 사실 보강 후보

- 이 업무영역에는 별도 보강 후보가 없습니다.

