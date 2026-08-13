# KDIC crawler/RAG — LLM 작업 안내

이 파일은 코드 에이전트와 LLM의 저장소 진입점이다. 프로젝트를 수정하기 전에
[`docs/LLM_WIKI.md`](docs/LLM_WIKI.md)를 읽고, 작업 영역에 해당하는 정본 문서를 추가로 읽는다.
KDIC 업무 지식·검색 의미·지식 그래프 작업이면 [`ontology/README.md`](ontology/README.md)와
[`ontology/kdic-domain-ontology.yaml`](ontology/kdic-domain-ontology.yaml)도 읽는다.

## 사실의 우선순위

서로 다른 설명이 충돌하면 다음 순서를 따른다.

1. 현재 코드와 테스트
2. API 스키마: `api/schemas/`, `web/src/lib/api/types.ts`
3. Current 문서: `docs/README.md`의 Current 표
4. Historical/Generated 문서
5. `log/`의 일일 기록

과거 실험 결과는 당시 사실로 보존한다. 현재 동작처럼 인용하지 않는다.

## 반드시 지킬 불변식

- 운영 데이터베이스와 벡터 검색 저장소는 Supabase Postgres + pgvector다. 사용자가 명시하지
  않으면 `infra/kdic-postgres-server`의 로컬 Docker 환경을 시작하거나 구현하지 않는다.
- 웹 RAG는 `api/rag/answer.py` + `api/rag/sse.py`, CLI/Streamlit RAG는
  `src/pipeline.py`가 각각 조립한다. 공통 파라미터나 흐름을 바꾸면 두 경로를 함께 대조한다.
- `src/` 모듈은 flat import를 사용한다. `api/__init__.py`가 `src/`를 `sys.path`에 넣는다.
- 웹 API 계약은 Python Pydantic 모델과 TypeScript 타입 양쪽을 함께 유지한다. SSE의 최종 정본은
  `done` 이벤트다.
- 복합 질문의 출처와 첨부는 각 `sub_answer`에 둔다. 하위 답변 사이에서 출처를 중복 제거하지 않는다.
- 런타임 Dense 검색은 Supabase의 `document_chunks`를 읽는다. `data/dense_cache/`와
  `data/chunks_all.jsonl`은 평가·적재 산출물이지 운영 검색 입력이 아니다.
- 검토 완료 ontology 사실은 공식 `page_id`와 현재 `content_sha256` 근거를 가져야 한다.
  ontology 도메인 매핑을 held-out 평가 없이 검색 hard filter로 사용하지 않는다.
- `data/corpus.jsonl` 메타데이터를 바꾸면 `python src/crawler/build_ontology_map.py --check`를
  실행한다. 실패하면 생성기로 갱신하며 `ontology/kdic-document-concept-map.json`을 직접 편집하지 않는다.
- P1/P2 정제 초안은 `ontology/kdic-curated-concept-proposals.json`이며 모든 항목은 domain reviewer
  승인 전 `proposed`다. 이 파일의 동의어·개념을 검색이나 답변에 연결하지 않는다.
- P3 단일 문서 label은 `ontology/kdic-p3-concept-triage.json`에서만 검토한다. `potential_parent_candidate_ids`는
  문자열 중복 힌트일 뿐 ontology 병합 결정이나 런타임 신호가 아니다.
- P3 typed 후보는 `ontology/kdic-p3-typed-concept-proposals.json`에 있으며 domain reviewer 승인 전
  `proposed`다. 원문 요약의 금액·기한을 이 파일에서 검토된 fact로 간주하지 않는다.
- P3 일반 후보와 기존 Service 병합·제외 판단은 `ontology/kdic-p3-general-concept-proposals.json`에
  있다. `MonetaryRule.fact_values`가 비어 있으면 유형 제안일 뿐 답변 가능한 수치 사실이 아니다.
- 전체 후보의 통합 정본 초안은 `ontology/kdic-canonical-ontology-draft.json`이다. 생성 결과이므로
  직접 편집하지 말고 `src/crawler/build_canonical_ontology_draft.py`와 원본 proposal을 수정한다.
  `pending_domain_approval` 엔터티는 검색·답변·fact 추론에 사용할 수 없다.
- 최종 판정은 `results/ontology/release_readiness.json`이다. `runtime_ready=false`인 동안 ontology
  graph·fact·label을 운영 RAG에 연결하지 않는다. 검증은 `python src/eval/validate_ontology_release.py`로 한다.
- 품질·비용·속도 개선은 테스트 통과만으로 주장하지 않는다. 같은 held-out 평가셋에서 정확도,
  호출 수/토큰, 지연시간을 함께 비교한다.

## 현재 주요 스위치

- Query planner: On (`src/query_planner.py`의 `USE_QUERY_PLANNER`)
- Query decomposition fallback: On
- Reranker: Off (`src/pipeline.py`의 `USE_RERANKER`)
- Business-function hard filter: Off (`src/retrieval.py`)
- Low-relevance gate: top-1 `< 0.35`
- `[NO_SOURCE]` 사후 재확인: On

값은 코드가 최종 정본이다. 이 목록과 코드가 달라지면 같은 변경에서 이 문서도 갱신한다.

## 기본 검증

```powershell
# 저장소 루트
.\.venv\Scripts\python.exe -m pytest -q

# 프론트엔드
cd web
pnpm verify
```

데이터 재생성, Supabase 적재, 외부 LLM 평가, 크롤링은 상태·비용·외부 시스템을 바꾸므로 요청 범위를
확인한 뒤 실행한다.
