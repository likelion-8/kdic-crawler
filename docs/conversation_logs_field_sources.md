# 대화 로그(AD-005) — 원천 없는 필드 처리방침

작성: 로그 스키마 담당 · 대상: 로그 라우터 담당(admin_logs.py) · 프론트(logs/api.ts)
관련 커밋: `api/masking.py`(마스킹 스텁) · `api/schemas/logs.py`(응답 스키마)

## 0. 한 줄 요약

프론트 `ConversationLogDetail`이 요구하는 필드 중 **6개는 `rag_runs`에 원천이 없다.**
없는 값을 그럴듯한 기본값으로 채우면 화면이 운영자에게 **거짓을 말한다**(예: `source_used=false`
→ '검색 근거가 사용되지 않았습니다'). 그래서 **지어내지 않고 null**을 내보내되, 필드마다
왜 그렇게 정했는지와 나중에 어떻게 메울지를 아래에 남긴다. **이번 주에 컬럼은 추가하지
않는다(제안까지만).**

원칙 정본: `web/src/routes/admin/logs/api.ts:39-49` — "빈 상태 문구가 '검색 근거가 사용되지
않았습니다'라 운영자에게 거짓을 말하게 된다. 그래서 화면은 rag_runs가 실제로 가진 것만 그린다."

## 1. `rag_runs`가 실제로 채우는 것 (writer 기준)

컬럼 정의는 `src/schema.py`에 15개 있지만, **실제로 쓰는 것은 `src/rag_logger.py:log_rag_run`
이고 그건 11개만 채운다:**

> question · intent · question_type · retrieval_route · answer · status ·
> total_latency_ms · llm_model · embedding_model · request_id · session_id

**컬럼은 있으나 로거가 안 채우는 3개** — `trace_id` · `failure_stage` · `root_cause`.
→ 이건 "원천 없음"과 다른 문제다. **컬럼은 이미 있으니 추가할 필요가 없고, 로거/호출부만
고치면 채워진다.** 지금 상태로는 langfuse 링크와 error 블록이 **모든 행에서 비어** 있다.
(별도 항목 — 아래 §4.)

## 2. 필드별 원천 표 (ConversationLogDetail 전체)

| 필드 | 원천 | 상태 |
|---|---|---|
| request_id, question(→_masked), intent, question_type, answer(→_masked_*), status, total_latency_ms(→latency_s) | rag_runs (로거가 채움) | ✅ 있음 |
| occurred_at | rag_runs.created_at | ✅ 있음 |
| feedback, feedback_detail | feedback 테이블 (request_id 조인) | ✅ 있음 |
| trace_id → langfuse.id / failure_stage / root_cause | rag_runs (컬럼 O, **로거가 안 채움**) | ⚠️ §4 |
| langfuse.url | 서버가 Langfuse 호스트 설정으로 완성 | ✅ 파생 |
| error.{code,meaning,user_message,auto_retry,fallback} | 정적 표(codes.ts ERROR_CODES 대응) | ✅ 파생 |
| **source_count** | 답변시 계산(len sources), **미저장** | ❌ §3-A |
| **classification.source_used** | 답변시 계산(answer.py finalize_sub), **미저장** | ❌ §3-A |
| **classification.marker** | 답변시 계산(LLM 마커), **미저장** | ❌ §3-A |
| **classification.normalized** | 답변시 계산(마커 보정), **미저장** | ❌ §3-A |
| **classification.business_function** | 분류 자체가 **비활성**(2026-07-29) | ❌ §3-B |
| **triage** | 기능(PATCH triage)이 **이번 주 범위 밖** | ❌ §3-C |

## 3. 원천 없는 6개 — 결정

처리 3택: **(a)** null로 내보냄(화면이 견딤) · **(b)** 컬럼 추가 *제안만*(마이그레이션 범위 밖) ·
**(c)** 프론트에 타입 조율 요청(null 수용 또는 필드 제거).

### 3-A. 답변시 계산되나 저장 안 되는 4종 — `source_count` · `source_used` · `marker` · `normalized`

한 묶음이다. `api/rag/answer.py`가 답변을 만들 때 이미 계산한다(`finalize_sub`의 `used`,
`_build_sources`의 개수, LLM 마커/보정). 그런데 `log_rag_run`이 이 인자들을 안 받아 **버려진다.**

- **결정: (b) 컬럼 추가 제안** — 값이 실재하고 로그 화면이 쓰므로, 저장하는 게 정답이다.
  마이그레이션은 이번 주 범위 밖 → **제안만**(§5).
- **그때까지(this week): null.**
  - `source_count`는 프론트 타입이 `number | null` → **그대로 null**. 화면 `dash()`가 '—'(=모름)로
    그린다. **⚠️ 절대 0을 넣지 마라** — 0은 "근거 0건"이라는 거짓이 된다.
  - `source_used`·`marker`·`normalized`는 프론트 타입이 **non-null**(`boolean`/`string`)이라
    null을 넣으면 타입이 어긋난다 → **(c) 프론트 조율 필요**(§6). 임시로라도 `false`/`''`를
    지어내면 안 된다 — `source_used=false`는 §0의 거짓 문구를 그대로 띄운다(선례).

### 3-B. `business_function` — 분류 비활성

`src/query_classifier.py:68` — 2026-07-29 팀 결정으로 업무(business_function) 분류를 검색에
쓰지 않기로 해 `BusinessFunctionClassifier`가 주석 처리됨. **파이프라인이 아예 계산하지 않는다.**

- **결정: (a) null.** 프론트 타입이 `BusinessFunction | null`이라 null을 견딘다(→ '—').
  null=모름=사실이다(분류를 안 했으니). 거짓 아님.
- 분류를 재활성화하면 그때 (b)로 승격(컬럼 + 로거 인자).

### 3-C. `triage` — 기능 자체가 범위 밖

로그 1건의 확인 상태(미확인/확인중/처리완료). `rag_runs`에 컬럼 없음. PATCH triage(처리 완료
표시)는 이번 주 범위 밖.

- **결정: (a) 'NONE'(미확인) 고정.** 프론트 타입이 non-null `TriageStatus`라 값이 있어야 하는데,
  **'NONE'은 거짓이 아니다** — 아무도 아직 확인하지 않았다는 사실 그대로다(triage 기능이 없으니
  당연히 미확인). 그래서 §0 원칙에 안 걸린다.
- triage 기능을 만들 때 (b)로 컬럼 + PATCH 엔드포인트를 함께 설계.

## 4. 별개 항목 — `trace_id` · `failure_stage` · `root_cause` (컬럼 O, 로거 X)

이 3개는 **원천(컬럼)이 이미 있다.** 문제는 `log_rag_run`이 이 값을 안 넘겨서 **모든 행이 null**
이라는 것 → langfuse 링크·error 블록이 항상 빈다. **컬럼 추가가 아니라 로거/호출부 수정**이다:
`log_rag_run` 시그니처에 `trace_id`/`failure_stage`/`root_cause`를 더하고 `api/rag/answer.py:256`
호출부(그리고 `src/pipeline.py:201`)에서 전달하면 된다. 이 문서의 결정과 무관하게 진행 가능.

부수 효과: `status`의 **OUT_OF_SCOPE**는 `source_used`(§3-A, 미저장)에서 갈린다 → 지금은
NORMAL과 구분 불가. `source_used` 컬럼이 생기면 함께 풀린다. 그전까지 status는 NORMAL/FAILED만
정확하다.

## 5. 마이그레이션 제안 — ⚠️ 이번 주 실행 금지, 제안만

```sql
-- rag_runs 에 '답변 시점 신호' 4종 추가 (§3-A). 제안일 뿐 이번 주 실행하지 않는다.
ALTER TABLE rag_runs ADD COLUMN source_used       BOOLEAN;  -- finalize_sub used 집계(any)
ALTER TABLE rag_runs ADD COLUMN source_count      INTEGER;  -- len(_build_sources(top))
ALTER TABLE rag_runs ADD COLUMN answer_marker     TEXT;     -- LLM [SOURCE_USED]/[NO_SOURCE]
ALTER TABLE rag_runs ADD COLUMN marker_normalized BOOLEAN;  -- 마커 형식 보정 여부
```
- 병행 코드: `log_rag_run`에 위 4개 인자 추가 + `answer.py:256` 호출부에서 전달(값은 이미 계산돼 있음).
- **business_function**: 분류 재활성(팀 결정)이 선행돼야 컬럼 대상 → 지금은 대상 아님.
- **triage**: PATCH triage 기능 설계와 함께 별도 → 지금은 대상 아님.

## 6. 프론트 조율 요청 (logs/api.ts)

아래 3개는 이번 주 원천이 없어 서버가 **null**을 낸다. 프론트 타입이 non-null이라 그대로면
어긋난다. **타입을 nullable로 바꾸고, null일 때 값을 지어내 표시하지 말 것**(빈 값은 '정보 없음/—'
으로, '근거 미사용' 같은 단정 문구 금지):

| 필드 | 현재 타입 | 요청 |
|---|---|---|
| classification.source_used | `boolean` | `boolean \| null` — null이면 '판정 정보 없음' |
| classification.marker | `string` | `string \| null` — null이면 '—' |
| classification.normalized | `boolean` | `boolean \| null` — null이면 표시 안 함 |

대안: 위 4종 컬럼(§5)이 생길 때까지 상세의 **분류 블록 중 이 3필드를 숨김**. 어느 쪽이든
"빈 값 = 사실"로 보이게 하지 않는 게 핵심.

## 7. 담당자 배분

- **로그 라우터 담당(admin_logs.py)**: §3 결정대로 null/'NONE'을 낸다. `mask_text`(api/masking.py)를
  question/answer/comment에 건다. §4(로거 수정)는 원하면 같이.
- **프론트**: §6 타입 3개 nullable화.
- **팀(마이그레이션 권한자)**: §5는 다음 스프린트 안건 — 이번 주 실행 금지.

## 8. 미구현 마감 — rerun · PATCH triage (프론트 조치 필요)

대화 로그 프론트 계약(logs/api.ts)의 7종 중 조회 4종·내보내기·**후보 등록(POST
/evaluations/candidates, 이번에 평가 라우터에 구현됨)**은 채웠다. 남은 **2종은 이번 주
만들지 않는다(팀 결정)** — 서버에 엔드포인트가 없다.

| 미구현 | 프론트 호출 | 왜 뺐나 | 프론트 조치 |
|---|---|---|---|
| **재실행** | `rerunLog` → `POST /api/admin/logs/{id}/rerun` | 재실행은 파이프라인을 다시 태우는 실행 작업이라 워커(미구현)가 필요하다. change_requests·pipeline_jobs 와 같은 '기록 후 워커' 층이 서야 한다 | 버튼을 **숨기거나 비활성**. 서버는 404/405 를 낸다 |
| **처리 완료 표시** | `resolveLog` → `PATCH /api/admin/logs/{id}` (triage) | triage 컬럼이 rag_runs 에 없다(§3-C). 상태를 쓸 자리가 없어 PATCH 를 열면 값을 버리게 된다 | 버튼을 **숨김**. triage 컬럼이 생길 때(§3-C 제안) 함께 연다 |

⚠️ 두 버튼이 화면에 남아 있으면 운영자가 눌러도 아무 일이 안 일어나거나 오류만 본다. 서버가
조용히 200 을 내며 '한 척'하지 않는 게 맞다 — 없는 기능은 없다고 보이는 편이 안전하다.
서버는 해당 경로를 만들지 않아 자연히 404 가 나고, 프론트는 그 버튼을 그리지 않도록 조율한다.
