# 팀 결정 기록 — 2026-08-14

## 결정 1·2 구현 — 출처 판정 1콜 통일 + Reference Validation 전 답변 확대

- **결정 1**: 3표 다수결(`judge_answer_majority`, LLM 3콜) 폐지 — 모든 경로 단일 호출 통일.
- **결정 2**: [NO_SOURCE]일 때만 하던 사후 재확인을 **모든 답변**으로 확대하고, 검증 축을
  근거 실사용(`used_source`) + 질문-답변 적절성(`appropriate`)으로 넓힘. 답변당 LLM +1콜 지연은 팀 수용.
- `use_source_recheck` 런타임 파라미터가 이 검증 전체의 on/off 스위치(Off = 마커만 신뢰, 검증 생략).

### 바뀐 파일

| 파일 | 내용 |
|---|---|
| `src/source_check.py` | `validate_answer(question, answer_text, evidence)` 신설(src/source_check.py:124) — 단일 LLM 1콜, `AnswerValidation`(= AnswerJudgement + `appropriate`, :101), 프롬프트는 기존 SYSTEM_INSTRUCTION에 적절성 축만 추가(`VALIDATE_INSTRUCTION`, :84). 실패는 `None` = fail-open(마커 유지 + appropriate 통과). `judge_answer`/`judge_answer_majority`/`recheck_source_usage` 삭제(전 사용처 교체 완료). |
| `api/rag/answer.py` | `finalize_sub`(:185)가 스위치 On이면 **모든** 하위 답변을 `validate_answer` 1콜로 검증(:200) — `used_source`가 마커를 양방향 오버라이드, `appropriate=False`면 본문을 기존 `OUT_OF_SCOPE_MESSAGE`로 교체 + used=False(out_of_scope). ungrounded_claims 교체·refusal 1회 재생성 분기 유지. `_regenerate_once`도 다수결 → 1콜(:178, 채택 = used_source ∧ appropriate). 스위치 기본값 상수 `USE_SOURCE_RECHECK`(:51). |
| `src/pipeline.py` | recheck 자리를 `validate_answer` 1콜로 교체(src/pipeline.py:146-150) — 평가·운영 판정 정합. CLI는 출처 부착 판정까지(본문 교체는 웹 경로만). |
| `src/prompt_builder.py` | `_resolve_used_source`(:209) 콜백 계약 변경 — `recheck(본문, 마커_판정)`을 모든 답변에 호출, 결과가 최종 판정(종전: NO_SOURCE만·SOURCE_USED 불가침). |
| `api/routers/admin_prompt.py` | `_generate`의 recheck를 동일 `validate_answer`로 정렬(:282, 모든 답변·양방향 오버라이드). 결정화(deterministic) 경로는 그대로. |
| `api/routers/admin_rag_params.py` · `web/src/mocks/handlers/extra/ad-eval-rag.ts` | `use_source_recheck` 라벨을 "답변 사후 검증(전 답변 1콜)"로 현행화(목=계약 동시 수정). |
| `src/eval/eval_pipeline_generation.py` | 경로 설명 docstring 현행화(다수결 언급 제거). |
| `tests/test_source_pipeline.py` | `test_recheck_direction`을 새 계약(모든 답변 호출·양방향 오버라이드·실패 None fail-open)으로 갱신, `test_subanswer_independence`의 모킹을 `pipeline.validate_answer`로 교체. 사유 주석 포함. |

응답 스키마(`web/src/lib/api/types.ts`) 무변경. 검증: `pytest tests/ -q` 179 passed · `pnpm verify` 통과 ·
`import source_check, pipeline` 정상.

## 결정 3 — 동일 내용 복수 페이지 정답 인정

현행 유지(코드 무변경). source 판단의 전단계 이동 여부는 추후 팀 협의 예정.

## 재색인 확인 (체크리스트 4번)

- 확인 결과 **미완이었음** — 청킹 재작성(#150) 후 아무도 안 돌린 상태. main 기준 검색이
  "재색인 필요" 에러로 멈출 수 있는 상태였다.
- `index_document_chunks.py` 실행 완료(08-14): 청크 **494 → 503**(새 청킹 기준) · 문서 58 ·
  임베딩 누락 0 · `search_index_versions` ACTIVE 기록. 재색인 후 실챗으로 검색 관통 확인
  (출처 5건 정상 부착).

## Langfuse 확인 (체크리스트 5번)

- **키 유효**(auth_check 통과, `.env`: LANGFUSE_PUBLIC_KEY/SECRET_KEY/BASE_URL).
- 그러나 **웹 SSE 경로는 계측이 구조적으로 미배선**이었다 — `@observe`·`current_trace_id()`
  전달이 전부 `pipeline.py`(CLI·평가) 경로에만 있고, 웹은 스레드풀이 제너레이터를 조각
  소비해 ambient 컨텍스트가 유지되지 않는다(팀원 의문 "필요한 단계에 다 붙었는지"의 답).
- **배선 완료(08-14)**: `observability.record_trace()` 신설(SDK v4 `start_observation` —
  v4.14 는 `start_span` 이 없음, 실확인) → `sse.py` done 직전 root trace 기록(질문·답변·
  latency·복합 여부·하위질문) → `rag_runs.trace_id` 연결. `api/config.py` `langfuse_host` 를
  `LANGFUSE_BASE_URL` 폴백으로(호스트 이중 관리 방지) — AD-005 상세의 Langfuse 링크 생성.
- 실검증: 챗 1건 → `rag_runs.trace_id = 2cbae70c…` 연결 확인.
- **한계(의도)**: 웹 trace 는 root 1건(단계별 자식 span 없음) — 단계 span 은 pipeline 경로
  (CLI·평가)에서 본다. 웹 슬라이스 안에서 도는 데코된 함수(분류기·리랭커·generation)는
  부모 없이 각자 trace 가 되는 잔여 현상이 있다 — 완전한 단계 계층이 필요하면 SSE 소비를
  단일 스레드로 옮기는 후속 작업 필요.

## AD-006 [변경 반영] 대기 시간 — 실측 확인 (2026-08-14 재검수)

"평가 메뉴가 너무 오래 걸린다"의 최종 상태를 실제로 눌러 측정했다.

| 시점 | 화면 잠김 | 취소 |
|---|---|---|
| 종전(동기) | **1.5~3시간** (851문항 × OpenAI+HCX 1,702콜을 HTTP 안에서) | 불가 — 브라우저 닫아도 서버가 계속 돌았다 |
| 비동기 전환 직후 | 수십 초 (측정은 워커로 빠졌으나 851행 낱건 INSERT 가 남음) | 가능 |
| **bulk insert 후(현재)** | **855ms** | 가능 |

- 실측 방법: AD-006 문항 1건 편집 → [변경 반영] → `POST /evaluations/apply` 응답까지 계측.
- 워커 인계 확인: `pipeline_jobs` 에 `SMOKE_EVAL` 이 `targets=[run_id]` 로 인큐되고 워커가 집어
  RUNNING 으로 전환. 두 번째 요청은 QUEUED 로 대기(동시 1작업 규칙대로).
- 남은 대기의 정체는 이제 851행 스냅샷 1회 executemany 뿐이다. 측정(검색 851 + 생성 30문항)은
  전부 백그라운드다.
- 검증용으로 만든 평가셋 v2·v3 와 그 run·job 은 정리했다(문항 851 · 최대버전 1 로 복귀).
