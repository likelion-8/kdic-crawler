# 은닉재산 신고 Ontology 검토 패킷

> 이 패킷은 검토를 돕는 생성물입니다. 실제 승인 상태는 `../canonical-ontology-decisions.json`만 사용합니다.
> 어떤 항목도 승인 전에는 검색·답변·Supabase/RAG에 자동 반영되지 않습니다.

## 범위

- 공식 문서: 4개
- canonical 엔터티 결정: 3개
- source-verified 핵심 사실 결정: 2개
- source-verified 보강 후보: 0개 (core fact 자동 승격 없음)

## 검토 기준

- 용어가 공식적이고 안정적인 업무 개념인지 확인합니다.
- 클래스·상위 Service·관계·값·조건이 원문과 일치하는지 확인합니다.
- 인용과 content hash가 현재 원문을 정확히 가리키는지 확인합니다.
- `통상`, 기한, 금액, 예외 조건을 과장하거나 누락하지 않습니다.

## Canonical 엔터티

### `contact:concealed_assets_report_center` — 은닉재산 신고센터

- 클래스: `ContactPoint`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `ha_center`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `contact:financial_misconduct_report_center` — 금융부실관련자 불법행위 신고센터

- 클래스: `ContactPoint`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `ha_ilgl_intro`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `service:failure_responsibility_investigation_status` — 부실책임조사 진행현황 조회

- 클래스: `Service`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 근거 페이지: `ha_status_agree`
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

## Source-verified 핵심 사실

### `fact:concealed_assets_reward_maximum`

- 대상: `contact:concealed_assets_report_center`
- 관계: `has_monetary_limit`
- 값: `{"currency": "KRW", "operator": "maximum", "type": "MonetaryValue", "value": 3000000000}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [ha_center](https://www.kdic.or.kr/sp/sprtfund/SprtFndCncmDclrGudn/selectScrn.do)
- 원문 해시: `dba66fb0b1581bf925c8cc2eff706e7efe2468c6ad22d9b6fd438d70e51cd799`
- 인용: 최대 30억원의 포상금을 지급하고 있음
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

### `fact:concealed_assets_reward_rate`

- 대상: `contact:concealed_assets_report_center`
- 관계: `has_percentage_range`
- 값: `{"basis": "recovered_amount_after_costs", "maximum": 20, "minimum": 5, "type": "PercentageRange"}`
- 현재 결정: `approved` (hjy10 · 2026-08-12)
- 원문: [ha_center](https://www.kdic.or.kr/sp/sprtfund/SprtFndCncmDclrGudn/selectScrn.do)
- 원문 해시: `dba66fb0b1581bf925c8cc2eff706e7efe2468c6ad22d9b6fd438d70e51cd799`
- 인용: 회수금액(소요비용 공제)의 5~20% 수준에서 차등 산정
- [ ] 승인  [ ] 반려  [ ] 수정 요청
- 결정은 `../canonical-ontology-decisions.json`에 기록: 

## Source-verified 사실 보강 후보

- 이 업무영역에는 별도 보강 후보가 없습니다.

