# KDIC Domain Ontology

`kdic-domain-ontology.yaml`은 예금보험공사(KDIC) RAG 서비스가 다루는 업무 지식을 위한
기계 판독 가능한 ontology v0.2다. 현재 58개 공식 페이지, 승인된 canonical entity 45개,
승인된 핵심 fact 15개와 승인된 공식 표기 47개의 canonical graph를 기준으로 한다.

## 목적

- KDIC 업무, 서비스, 대상자, 조건, 절차, 서류, 기한, 금액과 공식 페이지의 관계를 일관되게 표현한다.
- 새 지식을 추가할 때 공식 `page_id`와 원문 근거를 필수로 한다.
- 질문 확장, 근거 선택, 관리자 지식 관리, 평가 오류 분류에 쓰는 공통 어휘가 된다.

이 파일은 **현재 RAG 런타임에서 아직 읽지 않는다.** v0는 지식 스키마와 운영 규칙의 정본이며,
검색·생성·DB를 자동으로 바꾸지 않는다.

## 정본과 갱신 규칙

1. 사실의 원천은 `data/corpus.jsonl`과 해당 `source_url`이다.
2. 클래스·관계·제약 정본은 `kdic-domain-ontology.yaml`이다.
3. 새 사실에는 최소 하나의 `page_id`와 그 페이지의 `content_sha256`을 붙인다.
4. 원본 페이지 해시가 바뀌면 연결된 사실의 상태를 `needs_review`로 바꾼다.
5. ontology 결과를 RAG에 연결할 때는 held-out 검색 정확도, 출처 정확도, 지연시간, 비용을 함께 평가한다.

## 사실 저장 구조

실제 fact는 `kdic-core-fact-proposals.json`에 저장하고, 사람 승인은
`review/canonical-ontology-decisions.json`에 분리한다. canonical graph의 Fact 노드는 승인 결과와
구조화 값, 아래 형식의 원문 근거를 함께 보존한다.

```json
{
  "id": "fact_example_001",
  "subject_id": "monetary_rule:deposit_protection_limit",
  "predicate": "has_monetary_rule",
  "object": {"type": "MonetaryRule", "value": "100000000", "currency": "KRW"},
  "evidence": {
    "page_id": "dp_protlmts",
    "source_url": "https://www.kdic.or.kr/...",
    "content_sha256": "...",
    "quote": "금융회사별로 1인당 1억원까지 보호됩니다."
  },
  "status": "source_verified_domain_approved"
}
```

인용은 현재 코퍼스 본문의 literal substring이어야 한다. 답변에는 공식 원문 URL과 로컬 스냅샷
수집일을 함께 표시하며, 최신성이 중요하면 원 페이지를 다시 확인한다.

## 적용 순서

1. **v0 (완료):** 공통 어휘·관계·근거 규칙을 정의한다.
2. **v1 (완료):** `Document → Service/Concept` 메타데이터 매핑을 만들고 페이지 해시를 보존한다.
3. **v2 (현재):** 승인된 canonical entity·fact·공식 표기, 승인된 fact 보강 후보와 근거 기반 LLM Wiki를 관리한다.
4. **v3 (차단):** fresh held-out 품질 게이트 통과 후에만 query expansion 또는 reranker 보조 신호를 검토한다.

v1 산출물은 `kdic-document-concept-map.json`이다. 다음 명령으로 현재 코퍼스와 일치하는지
확인하거나 다시 생성한다.

```powershell
python src/crawler/build_ontology_map.py --check
python src/crawler/build_ontology_map.py
```

v1 원본 매핑은 코퍼스 메타데이터만 사용한 결정론적 중간 산출물이라 `unreviewed`를 유지한다.
사람 검토 결과는 이를 덮어쓰지 않고 별도 canonical draft·decision·graph 계층에 반영한다.

v2 준비 단계로 `kdic-fact-candidates.json`도 생성한다. 원문에 그대로 등장하는 금액·기간·날짜만
후보로 뽑고, 근거 문장과 `content_sha256`을 보존한다. 이 파일의 `proposed` 항목은 사실로
사용하면 안 되며, 사람이 의미·단위·조건을 검토한 뒤 ontology Fact로 승격해야 한다.

```powershell
python src/crawler/build_ontology_fact_candidates.py
```

canonical graph를 사람이 탐색할 수 있는 Obsidian vault로 변환할 수 있다. 생성된
`ontology/obsidian` 폴더를 Obsidian에서 vault로 열고 Graph view를 실행하면 BusinessDomain,
Service, Document, canonical entity, Fact, OfficialLabel 연결과 승인 상태를 볼 수 있다.

```powershell
python src/crawler/build_obsidian_ontology_vault.py
```

vault 안의 노트도 생성물이라 직접 편집하지 않는다. 수정은 YAML/코퍼스와 생성기를 통해 반영한다.

LLM이 업무영역별로 공식 원문을 찾고 답변 근거를 고를 수 있는 한글 Wiki도 생성한다.
`ontology/llm-wiki`는 6대 업무영역 페이지와 응답 규칙으로 구성된다. Wiki는 탐색 안내서일
뿐 아니라 승인 fact 15개의 구조화 값·원문 인용·`page_id`·URL·수집일·hash를 함께 제공한다.
세부 답변은 `page_id`로 `data/corpus.jsonl` 원문을 검색하고, 최신성이 중요하면 공식 URL을 다시
확인한다. 보강 후보 6개와 공식 표기 47개는 사람 승인을 마쳤다. 다만 보강 후보는 core fact 승격 전까지
답변에 사용하지 않고, 문맥상 공식 표기는 승인 후에도 검색 동의어로 자동 확장하지 않는다.

```powershell
python src/crawler/build_llm_wiki.py
python src/crawler/build_llm_wiki.py --check
```

`kdic-document-semantic-coverage.json`은 58개 공식 문서 각각에 대해 정규 개념·사실의 근거인지,
FAQ·분기 화면처럼 문서만 유지하는지 기록한다. 새 문서를 추가하면 이 파일에서 미결정 상태가 없어야
한다. 문서 전용으로 남는 FAQ도 원문 검색과 답변 출처에는 계속 사용한다.

```powershell
python src/crawler/build_ontology_document_coverage.py
python src/crawler/build_ontology_document_coverage.py --check
```

`kdic-fact-gap-review-queue.json`은 핵심 fact가 비어 있던 `예금보험금 안내`와 `고객 미수령금 신청`에
대해, 원문 인용과 현재 hash를 검증한 후보만 별도 큐로 보관한다. 이 후보는 core fact나 runtime에 자동
승격되지 않으며, 담당자 검토 후에만 별도 변경으로 반영한다.

```powershell
python src/crawler/build_fact_gap_review_queue.py
python src/crawler/build_fact_gap_review_queue.py --check
```

사실 보강 후보 6개의 사람 검토 결과는 `review/fact-gap-review-decisions.json`에 별도로 기록한다.
초기값은 모두 `pending`이며 현재 6개 모두 승인됐다. 승인된 후보도 자동으로 core fact·graph·runtime에
들어가지 않는다.

```powershell
python src/crawler/init_fact_gap_review_decisions.py # 최초 1회만 실행
python src/eval/validate_fact_gap_review_decisions.py --json
python src/crawler/record_fact_gap_review_decision.py --id "후보-ID" --decision approved --reviewer "검토자" --date 2026-08-12
```

공식 표기 47개의 승인 결과는 `review/official-label-decisions.json`에 기록한다. 현재 47개 모두
승인됐지만 `contextual_label`은 정책상 동의어가 아니며, 검색 품질 게이트를 우회하지 않는다.

```powershell
python src/eval/validate_official_label_review_decisions.py --json
python src/crawler/record_official_label_review_decision.py --id "표기-ID" --decision approved --reviewer "검토자" --date 2026-08-12
```

도메인 담당자의 승인 결과는 `review/canonical-ontology-decisions.json`에 기록한다. 초기 파일은
전 항목을 `pending`으로 만들며, 이후에는 생성기가 덮어쓰지 않는다. `approved`·`rejected`·
`needs_changes` 결정에는 검토자와 ISO 날짜가 필요하고, 거절·수정 요청에는 사유도 기록해야 한다.
현재 canonical entity 45개와 core fact 15개는 `approved`로 기록되어 있으며, 이 승인만으로 런타임 RAG가
자동 활성화되지는 않는다.

```powershell
python src/crawler/init_ontology_review_decisions.py # 최초 1회만 실행
python src/eval/validate_ontology_review_decisions.py
```

한 건의 사람 결정을 기록할 때는 아래 도구를 사용한다. 기본값은 **미리 보기**이며, 표시된 항목·결정·검토자·날짜를
확인한 뒤에만 같은 명령 끝에 `--apply`를 붙인다. `rejected`·`needs_changes`에는 `--note`가 필수다.

```powershell
python src/crawler/record_ontology_review_decision.py --kind entity --id "검토할-항목-ID" --decision approved --reviewer "검토자" --date 2026-08-12
```

`review/by-domain/`에는 같은 검토 대상을 6대 업무영역별 패킷으로 나눈다. 팀원은 자기 업무 패킷의
원문·hash·범위만 검토하고, 최종 결정은 여전히 `canonical-ontology-decisions.json`에 기록한다.

```powershell
python src/crawler/build_ontology_domain_review_packets.py
python src/crawler/build_ontology_domain_review_packets.py --check
```

고정 held-out의 ontology 보조 순위 변화는 별도 진단으로 남긴다. 이 진단은 현재 testset으로 규칙을
튜닝하지 못하도록 명시하며, 새 독립 held-out의 수집 기준과 반입 검증기는 아래 문서에 있다.

```powershell
python src/eval/analyze_canonical_ontology_assist.py
python src/eval/analyze_canonical_ontology_assist.py --check
python src/eval/audit_fresh_heldout_candidates.py
python src/eval/audit_fresh_heldout_candidates.py --check
python src/eval/validate_fresh_ontology_assist_heldout.py data/testset/ontology_assist_fresh_heldout.jsonl
python src/eval/eval_fresh_ontology_assist.py --testset data/testset/ontology_assist_fresh_heldout.jsonl --baseline results/pipeline_holdout/ontology_assist_fresh_baseline.json --output results/ontology/canonical_assist_shadow_fresh_heldout.json
```

운영 후보 스냅샷은 승인·품질 게이트가 모두 통과할 때만 생성된다. 현재는 품질 게이트가 실패한
상태이므로 아래 명령은 실패해야 정상이며 Supabase나 RAG 런타임을 바꾸지 않는다.

```powershell
python src/crawler/build_runtime_ontology_snapshot.py
```

Neo4j용 CSV/Cypher export도 생성할 수 있다. Neo4j는 이 단계에서 설치·실행하지 않으며, 필요할 때
`ontology/neo4j`의 CSV를 Neo4j import 디렉터리로 옮긴 뒤 `import.cypher`를 실행한다.

```powershell
python src/crawler/build_neo4j_ontology_export.py
python src/crawler/build_neo4j_ontology_export.py --check
```

Neo4j export는 `kdic-canonical-graph.json`의 node type과 relation을 CSV/Cypher로 내보낸다.
source-verified core fact도 상태와 함께 포함하지만, 자동 추출된 918개 fact 후보는 제외한다.

v3 도입 전에는 metadata Concept이 held-out 질문의 정답 페이지를 실제로 좁힐 수 있는지 먼저
오프라인으로 측정한다. 이 평가는 Supabase·LLM을 호출하지 않으며 운영 검색을 바꾸지 않는다.

```powershell
python src/eval/eval_ontology_concept_match.py
```

v1 metadata label은 정식 ontology 개념이나 동의어가 아니다. 운영 적용 전에 95개 label을
공식 페이지 근거와 함께 사람이 검토한다. 이 검토는 held-out 평가 데이터를 보지 않으며,
승인된 항목만 이후 검색 보조 신호 후보가 될 수 있다.

```powershell
python src/crawler/build_ontology_review_queue.py
python src/crawler/build_ontology_review_queue.py --check
```

생성되는 `ontology/review/CONCEPT_REVIEW_QUEUE.md`는 모든 후보를 `proposed`로 기록한다.
문서 탐색용 표현, 과도하게 넓은 표현, 출처 없는 동의어는 승인하지 않는다.

반복 사용된 P1/P2 metadata Concept(2개 이상 문서 연결)은 별도 정제 초안으로 기록한다. 이 단계는
`보호대상`을 금융회사와 금융상품으로 분리하고, `소개와 방법안내`처럼 탐색용인 표현을 제외한다.
또한 제목과 실제 내용이 다르다고 표시된 페이지는 해당 개념의 근거에서 제외한다. 결과의 모든
candidate는 `proposed`이며 domain reviewer 승인 전에는 평가·검색·답변에 사용하지 않는다.

```powershell
python src/crawler/build_curated_concept_proposals.py
python src/crawler/build_curated_concept_proposals.py --check
```

한 문서에만 나타나는 P3 metadata Concept은 정규 ontology 후보로 자동 승격하지 않는다. 페이지마다
중복 title/breadcrumb label을 묶고, 원문 요약·공식 URL·본문 hash와 기존 P1/P2 후보와의 **문자열상
잠재 중복**을 함께 보여 주는 triage를 만든다. 이 중복 표시는 병합 결정이 아니며 사람이 검토한다.

```powershell
python src/crawler/build_ontology_p3_triage.py
python src/crawler/build_ontology_p3_triage.py --check
```

`P3-high`는 독립 개념 후보의 검토 우선순위, `P3-medium`은 기존 후보와의 범위·상하위 관계 확인,
`P3-low`는 FAQ·개요·안내 같은 탐색/형식 label의 제외 검토를 의미한다. 어느 경우도 runtime에는 쓰지 않는다.

P3-high 중 class가 명확한 절차·신청자격·구비서류·연락창구는 typed proposal로 묶는다. 동일한
착오송금 반환지원 5단계 절차를 설명하는 두 페이지처럼 의미가 같은 공식 페이지는 한 proposal의
복수 Evidence로 보존한다. 원문에 포함된 금액·기한은 여기서 fact로 승격하지 않는다.

```powershell
python src/crawler/build_p3_typed_concept_proposals.py
python src/crawler/build_p3_typed_concept_proposals.py --check
```

`ontology/kdic-p3-typed-concept-proposals.json`의 항목도 모두 `proposed`다. domain reviewer 승인과
별도 held-out 평가 전에는 query expansion, reranking, 답변 생성에 사용할 수 없다.

P3-high의 일반 Concept 후보도 페이지 요약과 기존 Service를 기준으로 수동 정제한다. 기존 상위
Service를 설명하는 페이지는 새 엔터티를 만들지 않고 `merge_existing`으로 기록하며, 다운로드 게시판은
Document로만 유지한다. 보호한도는 `MonetaryRule` 유형만 제안하고 금액·조건 값은 비워 둔다.

```powershell
python src/crawler/build_p3_general_concept_proposals.py
python src/crawler/build_p3_general_concept_proposals.py --check
```

`ontology/kdic-p3-general-concept-proposals.json`은 P3-high 일반 페이지 27개 전체의 판단을 보존한다.
새 후보, 기존 Service 병합, 제외 항목 모두 공식 URL과 현재 content hash를 포함한다.

P1/P2와 P3 typed/general/remaining proposal은 하나의 canonical draft로 통합한다. 통합기는 entity ID 중복,
ontology class, 상위 Service 참조, Evidence의 page ID와 현재 content hash를 검증한다. 서로 다른
proposal 파일의 필드명도 `parent_service_ids`, `review_status`, `provenance`로 정규화한다.

```powershell
python src/crawler/build_canonical_ontology_draft.py
python src/crawler/build_canonical_ontology_draft.py --check
```

산출물은 `kdic-canonical-ontology-draft.json`과
`review/CANONICAL_ONTOLOGY_APPROVAL_CHECKLIST.md`다. 통합본 45개 엔터티는 전부
`pending_domain_approval`이며, 체크리스트의 박스는 검토 템플릿일 뿐 machine-readable 승인이나
운영 반영을 발생시키지 않는다. 승인 결과는 이후 별도 결정 파일로 기록한다.

핵심 fact 15개와 source-verified 공식 label 47개를 canonical graph에 연결한다. 두 그룹 모두 사람
승인을 완료했으며 결정 원본은 각각 canonical 결정 파일과 `review/official-label-decisions.json`이다.

```powershell
python src/crawler/build_core_fact_proposals.py
python src/crawler/build_official_ontology_aliases.py
python src/crawler/build_canonical_ontology_graph.py
```

최종 무결성 및 운영 준비도 판정은 아래 명령으로 실행한다.

```powershell
python src/eval/validate_ontology_schema_alignment.py
python src/eval/validate_ontology_release.py
```

스키마 정합성 검증기는 YAML의 12개 canonical class·6개 relation·상태·endpoint·Fact 원문 근거가
실제 graph와 일치하는지 확인한다. 현재 판정은 `offline_ontology_ready=true`,
`all_graph_review_items_complete=true`, `all_human_reviews_complete=true`, `runtime_ready=false`다.
사람 검토는 끝났지만 검색 품질 게이트는 별개다. 자세한 근거와 검색 비교는
`RELEASE_READINESS.md` 및 `results/ontology/release_readiness.json`에 있다.

결과의 `coverage`와 Recall은 “정확한 메타데이터 개념 일치” 단독의 성능이다. 기존 검색기와의
개선 비교가 아니며, 결과가 충분하지 않으면 동의어·검토 facts를 보강한 뒤 다시 측정한다.

## 비목표

- RDF/OWL 서버나 graph database의 즉시 도입
- 근거 없는 LLM 추출 내용을 사실로 저장
- ontology만으로 답변을 생성하거나 공식 출처를 대체
- 현재 Supabase·검색·Docker 구성 변경
