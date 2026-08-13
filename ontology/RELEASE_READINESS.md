# KDIC Ontology Release Readiness

오프라인 ontology 사람 검토는 모두 완료됐지만 운영 RAG 적용은 품질 게이트 때문에 보류한다.

## 현재 결과

- 기본 Service: 6개
- canonical 도메인 승인 엔터티: 45개
- 공식 원문 인용·도메인 승인 핵심 fact: 15개
- source-verified fact 보강 후보: 6개 (예금보험금 안내 3개, 고객 미수령금 신청 3개, 전부 승인·core fact 승격 대기)
- canonical assist held-out 진단: 순위 변경 5건 중 첫 정답 순위 하락 2건 (현재 testset 튜닝 금지)
- 기존 testset fresh held-out 후보: 0개 (10개 파일 모두 provenance 또는 중복 요건 미충족)
- 공식 label 변형: 47개 (`official_label_variant` 17개, `contextual_label` 30개, 전부 승인; contextual은 검색 동의어 아님)
- canonical graph: 177 nodes, 307 relationships
- ontology schema: v0.2.0 canonical class 12개·relation 6개가 실제 graph와 정렬됨
- 공식 문서 semantic coverage: 58개 전부 결정됨 (정규 개념·사실 근거 52개, FAQ·분기 문서 전용 6개, 미결정 0개)
- Obsidian·Neo4j export: canonical graph와 동기화
- LLM Wiki: 승인 fact 15개의 구조화 값·원문 인용·page_id·URL·수집일·hash 포함
- LLM·DB 호출: 0
- 운영 코드 변경: 없음

정확한 자동 판정은 `results/ontology/release_readiness.json`에 기록한다.

## 검색 품질 판정

동일한 held-out 79문항에서 저장된 운영 검색 기준선과 shadow ontology 보조 검색을 비교했다.

| 지표 | 기준선 | Ontology 보조 | 변화 |
|---|---:|---:|---:|
| Recall@1 | 0.6055 | 0.5844 | -0.0211 |
| Recall@3 | 0.8544 | 0.8586 | +0.0042 |
| Recall@5 | 0.9219 | 0.9262 | +0.0043 |
| MRR@5 | 0.8046 | 0.8046 | 0.0000 |

Recall@5는 소폭 상승했지만 Recall@1이 하락했으므로 품질 게이트는 실패다. ontology를 검색 hard
filter, query expansion, reranker boost로 운영 적용하지 않는다. 이 결과를 바탕으로 가중치를 다시
맞추면 held-out test에 과적합되므로 현재 testset에서 추가 튜닝하지 않는다.

## 완료된 사람 결정

1. canonical entity 45개와 core fact 15개: [`review/canonical-ontology-decisions.json`](review/canonical-ontology-decisions.json)에서 모두 승인.
2. 공식 label 47개: [`review/official-label-decisions.json`](review/official-label-decisions.json)에서 모두 승인. contextual label은 동의어가 아니다.
3. fact 보강 후보 6개: [`review/fact-gap-review-decisions.json`](review/fact-gap-review-decisions.json)에서 모두 승인. 별도 core fact 변경 전까지 답변에 사용하지 않는다.

## 남은 구현과 평가

1. 승인된 보강 후보 6개를 조건·예외를 보존해 core fact로 승격하고 graph·Wiki를 재생성한다.
2. [`review/FRESH_HELDOUT_CANDIDATE_INVENTORY.md`](review/FRESH_HELDOUT_CANDIDATE_INVENTORY.md)에서 기존 10개 testset이 모두 부적격임을 확인하고, [`review/FRESH_HELDOUT_EVALUATION_PROTOCOL.md`](review/FRESH_HELDOUT_EVALUATION_PROTOCOL.md)에 따라 새 untouched testset을 수집·검증한 뒤 검색 보조 방식을 다시 평가한다.
3. Recall@1 회귀가 해소되고 품질 게이트가 통과한 경우에만 Supabase/RAG 보조 신호 구현을 별도 작업으로 진행한다.

현재 저장소가 제공하는 최종 산출물은 근거 포함 로컬 LLM Wiki, YAML과 정렬된 canonical graph,
승인된 core fact·공식 표기·fact 보강 제안, Obsidian vault, Neo4j export, 재현 가능한 오프라인 평가다.
