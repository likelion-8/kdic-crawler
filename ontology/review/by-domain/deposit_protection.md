# 예금자보호제도 Ontology 검토 패킷

> 이 패킷은 검토를 돕는 생성물입니다. 실제 승인 상태는 `../canonical-ontology-decisions.json`만 사용합니다.
> 어떤 항목도 승인 전에는 검색·답변·Supabase/RAG에 자동 반영되지 않습니다.

## 범위

- 공식 문서: 17개
- canonical 엔터티 결정: 12개
- source-verified 핵심 사실 결정: 2개
- source-verified 보강 후보: 0개 (core fact 자동 승격 없음)

## 검토 기준

- 용어가 공식적이고 안정적인 업무 개념인지 확인합니다.
- 클래스·상위 Service·관계·값·조건이 원문과 일치하는지 확인합니다.
- 인용과 content hash가 현재 원문을 정확히 가리키는지 확인합니다.
- `통상`, 기한, 금액, 예외 조건을 과장하거나 누락하지 않습니다.

## Canonical 엔터티

### `actor:protected_financial_institution` — 보호대상 금융회사

- 클래스: `Actor`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dp_fnst`, `dp_fnst_srch`, `dp_svbk_hist`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:deposit_protection_logo_use_rules` — 예금보호 로고 사용 규정

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dp_logo`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:display_explanation_confirmation_scheme` — 표시·설명·확인 제도

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dp_gudn`, `dp_gudn_data`, `dp_gudn_faq`, `dp_logo`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:insured_financial_company_survey` — 부보금융회사조사

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dp_josa_itrd`, `dp_josa_law`, `dp_josa_objc`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:insured_financial_company_survey_legal_basis` — 부보금융회사조사 법적근거·관련규정

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dp_josa_law`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:international_deposit_protection_limits` — 해외 예금자 보호한도

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dp_ovrs`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:protected_financial_product` — 보호대상 금융상품

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dp_prdct`, `dp_prdct_srch`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `concept:savings_bank_name_change_history` — 저축은행 상호 변경이력

- 클래스: `Concept`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dp_svbk_hist`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `monetary_rule:deposit_protection_limit` — 예금자 보호한도

- 클래스: `MonetaryRule`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dp_protlmts`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `procedure:insured_financial_company_survey_objection` — 부보금융회사조사 소명·이의제기

- 클래스: `Procedure`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dp_josa_objc`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `service:protected_financial_institution_search` — 보호대상 금융회사 검색

- 클래스: `Service`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dp_fnst_srch`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `service:protected_financial_product_search` — 보호대상 금융상품 검색

- 클래스: `Service`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `dp_prdct_srch`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

## Source-verified 핵심 사실

### `fact:deposit_protection_limit`

- 대상: `monetary_rule:deposit_protection_limit`
- 관계: `has_limit`
- 값: `{"currency": "KRW", "scope": "per_person_per_financial_institution", "type": "MonetaryValue", "value": 100000000}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [dp_protlmts](https://www.kdic.or.kr/sp/dpstrprot/ProtSystProtLmts/selectScrn.do)
- 원문 해시: `80ae7ac40cf6e94b0114f69461c164906920ea5fa0a1265c372a5a2ff7070637`
- 인용: 금융회사별로 1인당 1억원까지 보호됩니다.
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `fact:deposit_protection_limit_effective_date`

- 대상: `monetary_rule:deposit_protection_limit`
- 관계: `effective_from`
- 값: `{"type": "Date", "value": "2025-09-01"}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [dp_faq_page](https://www.kdic.or.kr/sp/dpstrprot/ProtSystFaq/selectScrn.do)
- 원문 해시: `053957508cb2b05942fa36d7ef48414f9c69b9da76654e53d6f3163a8a80d186`
- 인용: 2025년 9월 1일부터 예금보호한도 1억원이 적용되고 있습니다.
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

## Source-verified 사실 보강 후보

- 이 업무영역에는 별도 보강 후보가 없습니다.

