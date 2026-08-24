# 목(MSW) 서버 — 백엔드 팀용 안내

프론트가 백엔드 없이 혼자 돌게 하는 가짜 API다. **여기 적힌 요청/응답 모양이 프론트가 기대하는
계약 전부**이므로, FastAPI 쪽을 이 표에 맞추면 목을 끄는 것만으로 붙는다.

- 계약 정본: Figma 기획서(CM-DF-003 03·04절) → 프론트 타입은 `src/lib/api/types.ts`, 코드값은 `src/lib/codes.ts`
- 이 파일에 없는 필드는 **프론트가 안 쓴다.** 더 줘도 무시되고, 여기 있는 걸 빼면 화면이 깨진다.

---

## 1. 목을 끄고 진짜 API를 붙이는 법

```bash
# web/.env.local  (.env.example 복사해서 만든다)
VITE_ENABLE_MSW=false          # 목 끄기
VITE_API_BASE=http://localhost:8000   # FastAPI 주소
```

그게 전부다. 프론트 코드는 한 줄도 안 고친다.

- `VITE_ENABLE_MSW`를 비워 두거나 `true`면 목이 켜진다(**기본 켜짐**). 끌 때만 `false`.
- `VITE_API_BASE`가 비어 있으면 같은 오리진(`/api/...`)으로 요청한다 = 목이 가로챈다.
  값을 채우면 그 주소로 나가므로 **목과 같이 쓰면 안 된다**(목 핸들러는 상대 경로만 잡는다).
- 부트스트랩은 `src/mocks/browser.ts`의 `enableMocking()`이다. `main.tsx`에서 렌더 전에 한 번 `await` 한다.
- 워커 스크립트 `public/mockServiceWorker.js`는 `pnpm exec msw init public/`로 생성된 파일이다. 손대지 말 것.

**부분 전환도 된다.** 챗봇만 먼저 붙였다면 `browser.ts`의 `handlers` 배열에서 `chatHandlers`만 빼면
그 요청만 실제 서버로 나간다(나머지는 계속 목).

---

## 2. 사용자 API

전부 `src/lib/api/types.ts`의 타입이다. 아래 표의 타입 이름은 그 파일을 가리킨다.

| 메서드 | 경로 | 요청 | 응답 |
|---|---|---|---|
| POST | `/api/chat` | `ChatRequest` `{message, session_id?}` | **SSE 스트림** (아래 3장) 또는 429 `ApiError` |
| POST | `/api/feedback` | `FeedbackRequest` `{answer_request_id, session_id, vote}` | `FeedbackResponse` `{feedback_id}` |
| PATCH | `/api/feedback/{feedback_id}` | `FeedbackPatch` `{reason_codes[], comment?}` | `{feedback_id}` |
| GET | `/api/sessions/{session_id}` | — | `RestoredSession` `{session_id, last_activity_at, messages[]}` |
| GET | `/api/health` | — | `HealthResponse` `{status, maintenance, disabled_features[], user_message?}` |
| GET | `/api/suggestions` | — | `Suggestion[]` (활성 최대 10) |

검증 규칙(목이 실제로 거는 것)

- `POST /api/feedback` — `answer_request_id`·`session_id`·`vote('up'|'down')` 없으면 **400**
  (`answer_request_id` = 피드백을 붙일 **답변**의 id. 쓰기 멱등키 `request_id`와 뜻이 달라 이름을 나눴다 — B-07, 2026-08-05)
- `PATCH /api/feedback/{id}` — `reason_codes` 비면 400, `comment` 200자 초과(`FEEDBACK_FREETEXT_MAX`)면 400
- `GET /api/health?state=maintenance|degraded` — 점검 화면(CB-004 Case 6) 개발용 스위치.
  **`user_message`는 서버가 준다. 프론트는 오류·점검 문구를 만들지 않는다.**

### `/api/sessions/{id}` 는 기획서와 이름이 다르다

PRD-01 B-2 API 인벤토리는 이 기능을 `GET /api/conversation`이라 적었고, CM-DF-003 04절 표는
`GET /api/admin/... ` 계열과 함께 `/api/sessions/{session_id}`로 적었다. 프론트는 **후자**를 따랐다.
백엔드는 둘 중 하나로 통일하고 기획서를 고쳐야 한다(§6 참조).

---

## 3. SSE 계약 (`POST /api/chat`)

`Content-Type: text/event-stream`. 프레임은 `event: <이름>\ndata: <JSON>\n\n`.

```
accepted     {request_id, session_id}
answer_delta {text}                    ← 여러 번. 글자 단위(목은 8자씩 50~80ms 간격)
done         ChatResponse 전문
error        ApiError                  ← done 대신 온다
```

이 4종이 전부다. `sources`·`attachments` 이벤트는 2026-08-05에 없앴다 — 근거 사용 판정이
스트리밍이 끝난 뒤에 확정돼 어차피 `done`과 같은 시점에 나갔다. 출처는 `done`의
`sources`·`attachments`(복합 질문이면 `sub_answers` 안의 것)로 그린다.

**지켜야 하는 것**

1. `answer_delta`에 자기보고 마커(`[SOURCE_USED]`/`[NO_SOURCE]`)를 **절대 넣지 마라.**
   `prompt_builder._strip_no_source_marker()`가 떼는 그 마커다. 스트리밍 전에 서버에서 제거한다.
   (프론트가 떼려면 첫 줄이 올 때까지 렌더를 붙들어야 해서 스트리밍 체감이 죽는다.)
2. `out_of_scope=true`면 `done.sources`를 **빈 배열로** 준다. 프론트는 `done`을 받고서야 출처
   섹션을 그리므로, 값이 실려 오면 그렸다 지우는 깜빡임이 아니라 잘못된 출처가 그대로 남는다.
3. 429는 SSE를 열지 말고 **HTTP 429 + `Retry-After` 헤더 + `ApiError` 본문**으로 끊는다.
   `retryable=false`로 준다 — 자동 재호출은 금지고 사용자가 직접 다시 보낸다(PRD-02 §3-b).
4. `[중단]`은 클라이언트 `AbortController`다. 서버 취소 API는 없다.

### 시나리오 트리거 (목 개발용)

질문에 아래 말이 들어가면 그 시나리오가 나온다. 위에서부터 첫 일치. 표의 정본은
`src/mocks/handlers/chat.ts` 파일 상단 주석이다.

| 질문에 포함 | 나오는 것 |
|---|---|
| `429` `과부하` | HTTP 429 |
| `오류` `에러` | 부분 실패 — `error.user_message` + `fallback_sources` 2건 + [다시 시도] |
| `링크` | 업무 되묻기 — `clarification` 5선택지. answer·sources 없음 |
| `누구` `이름이` `모델` | 범위 외(정체성) |
| `안녕` `고마워` `반가` | 범위 외(인사·잡담) |
| `대출` `금리` `주식` | 범위 외(범위 밖 질문) |
| `잘못 보낸 사람` `송금인` `신청` `서류` `절차` `방법` | 민원처리 — 절차 + 필요 서류 2 + 신청 페이지 |
| `잘못 받은 사람` `수취인` `미수령금` | 민원처리 — 첨부 없음(필요 서류 섹션 통째 미노출) |
| `그리고` `와 필요` `기간은` | 복합 질문 분해 |
| 그 외 전부 | 정보성 답변 + 참고 출처 3건 |
| (아무 질문 + `느리게`) | 델타 간격 5초 — 30초 유휴 폴백·[중단] 개발용 |

---

## 4. 관리자 API

경로는 CM-DF-003 04절 표 그대로다. 공통 규칙 3가지.

- **목록은 전부 `Page<T>` 봉투** `{items, total, page, size}`. 기본 `size=20`.
  쿼리 `?page=&size=&sort=필드:asc|desc` 지원.
- **쓰기 API는 `request_id`(멱등키)와 `reason`(변경 사유)이 body에 필수.** 없으면 **400**.
  (초안 자동저장 `PUT /drafts/{screen}`만 예외 — 위험 작업이 아니라 `request_id`만 본다.)
- **권한 부족은 403 + `request_id`.** 프론트는 버튼을 숨기지 않고 비활성으로 두되, 사유는 툴팁 + sr-only로 알린다(옆에 글자로 상시 노출하지 않는다 — 2026-08-04, P-13). 화면 전체가 잠기면 위에 '보기 전용' 안내를 한 번 둔다.

| 메서드 | 경로 | 필요 권한 | 비고 |
|---|---|---|---|
| POST | `/api/admin/login` | — | `{email, password}` → `{email, name, role}`. 5회 실패 시 10분 잠김 |
| POST | `/api/admin/logout` | — | 204 |
| POST | `/api/admin/reauth` | — | 위험 작업 전 비밀번호 재확인 → `{last_auth_at}` |
| GET | `/api/admin/session` | — | 3타이머 초 단위: `absolute_expires_in_s`·`idle_expires_in_s`·`reauth_valid_until_s` |
| POST | `/api/admin/session/extend` | — | **유휴만** 리셋. 절대 만료(8h)는 갱신 불가 |
| GET | `/api/admin/roles` | VIEWER | `RoleDefinition[]` |
| GET | `/api/admin/me/permissions` | VIEWER | `{role, allowed: string[]}` — 버튼 활성 판단용 |
| PATCH | `/api/admin/accounts/{id}` | ADMIN | `{role?, status?, request_id, reason}` |
| GET | `/api/admin/knowledge/pages` | VIEWER | 필터 `q`·`business`·`state` |
| GET | `/api/admin/knowledge/chunks` | VIEWER | 필터 `page_id`·`q` |
| POST | `/api/admin/previews` | EDITOR | `{url, business_function, request_id}` → 자동추출값 + 청크 + 경고. kdic.or.kr 밖 URL은 400 |
| POST | `/api/admin/change-requests` | EDITOR | 생성 → 201 |
| GET | `/api/admin/change-requests` | VIEWER | 필터 `status` |
| POST | `/api/admin/change-requests/{id}/approve` | ADMIN | 이미 처리된 건은 409 |
| POST | `/api/admin/change-requests/{id}/reject` | ADMIN | 〃 |
| POST | `/api/admin/jobs` | OPERATOR | 202. **동시 실행 1개**(`PIPELINE_CONCURRENCY`) 초과면 409 |
| GET | `/api/admin/jobs` | VIEWER | 실행 이력 |
| GET | `/api/admin/jobs/{id}` | VIEWER | 진행 상태 폴링 대상 |
| POST | `/api/admin/jobs/{id}/cancel` | OPERATOR | 단계 상태를 그 시점으로 얼려 반환 |
| POST | `/api/admin/jobs/{id}/retry` | OPERATOR | **새 job을 만든다**(활동 로그에 둘 다 남아야 함) |
| POST | `/api/admin/jobs/{id}/rollback` | ADMIN | 긴급 롤백 → REINDEX job(`rollback_of`) |
| GET | `/api/admin/evaluations/runs` | VIEWER | `page`·`size`·`sort` + 필터 `target=운영 설정\|RAG 초안\|프롬프트 초안` · `source=수동 실행\|프롬프트 게시 게이트\|파이프라인 후속\|RAG 파라미터 평가` (A-10·A-11 확정) |
| GET | `/api/admin/evaluations/runs/{run_id}` | VIEWER | 게이트 판정 포함 |
| GET | `/api/admin/activity/events` | VIEWER | 필터 `q`·`actor`·`result` |
| GET | `/api/admin/activity/events/{id}` | VIEWER | 당시 스냅샷 포함 |
| POST | `/api/admin/activity/exports` | ADMIN | 내보내기 자체도 활동 로그 이벤트다 |
| PUT | `/api/admin/drafts/{screen}` | EDITOR | 10초 주기 자동저장 → `{screen, saved_at, version}`. **AD-008은 제외**(6절 8) |
| GET/PUT | `/api/admin/suggested-questions` | VIEWER/EDITOR | PUT은 목록 통째 교체. 활성 10개 초과 400 |

**활동 로그는 추가 전용이다.** 수정·삭제 엔드포인트를 만들지 마라(PRD-01 B-1-c).

### 파이프라인 진행 시뮬레이션

`POST /api/admin/jobs`로 만든 작업은 목 안에서 **실제로 시간이 지나면서 진행된다.**
단계는 `PIPELINE_STEPS`(수집·변환·청킹·검증·색인·반영) 6개, 단계당 4초 → 24초에 SUCCESS.
`GET /api/admin/jobs/{id}`를 폴링하면 `steps[].status`가 QUEUED → RUNNING → SUCCESS로 바뀐다.
타이머가 아니라 `Date.now() - started_at_ms`로 매 요청마다 다시 계산하므로 탭을 백그라운드에 둬도 안 어긋난다.

### 개발용 역할 전환

요청 헤더 `x-mock-role: VIEWER|OPERATOR|EDITOR|ADMIN`를 붙이면 그 역할로 간주한다.
403 화면과 비활성 버튼 사유를 로그인 없이 개발할 때 쓴다. 헤더가 없으면 로그인한 역할, 로그인 전이면 ADMIN.

---

## 5. 지금 파이썬 코드 ↔ API 필드 매핑

**핵심: 계약을 만족시키는 데 새 로직이 필요 없다. 이미 만든 dict를 평탄화하지 말고 그대로 내보내면 된다.**

`src/pipeline.py`의 `rag_answer()`는 지금 **마크다운 문자열 하나**를 반환한다. 그런데 그 문자열을
만드는 재료는 이미 구조화된 dict다 — 문자열로 합치는 마지막 한 단계(`prompt_builder.assemble_*`)만
걷어내면 그대로 `ChatResponse`가 된다.

| API 필드 | 지금 코드의 출처 | 해야 할 일 |
|---|---|---|
| `answer` | `prompt_builder._strip_no_source_marker(llm_text)[0]` | 마커 뗀 **본문만**. `_render_list()`로 붙인 "참고 출처"·"필요 서류"·"신청 페이지" 문자열은 빼고 준다 |
| `out_of_scope` | `prompt_builder._resolve_used_source(llm_text, recheck)[1]` (`used_source`) — 마커 원값이 아니다. `pipeline.USE_SOURCE_RECHECK=True`면 `[NO_SOURCE]` 판정만 `source_check`가 한 번 더 뒤집는다 | `out_of_scope = not used_source`. 지금은 이 값으로 "출처를 붙일까 말까"를 정하는데, 그 대신 **불리언을 그대로 내려주면** 프론트가 판단한다 |
| `sources[]` | `citation.format_all_citations(chunk_ids)` | **이미 `{page_id, breadcrumb, title, url}` dict 리스트다.** `Source` 타입과 필드명까지 일치 — 그대로 직렬화 |
| `attachments[]` (필요 서류) | `civil_petition.build_civil_petition_answer(top)["documents"]` | `{page_id, label, url}` → `{label, url, kind: "document"}` |
| `attachments[]` (신청 페이지) | 같은 dict의 `["links"]` | `{title, url, breadcrumb}` → `{label: title, url, kind: "link"}` |
| (본문 절차) | 같은 dict의 `["procedure"]` | LLM 프롬프트 재료다. 응답에 따로 내보내지 않는다 |
| `intent` | `query_classifier.classify_intent(query)` | `informational` / `civil_petition` 그대로 |
| `business_function` | `retrieval.route_search_chunks`가 고른 업무 | 로깅·분석용. 프론트는 렌더 분기에 쓰지 않는다 |
| `latency_ms` | `pipeline._rag_answer_traced()`의 `timings["total"]` | 초 → ms |
| `response_type` | 없음 | 새로 붙여야 한다(§6 I-04) |
| `clarification` | `clarify.clarification_payload()` | 판정은 플래너·재작성기의 `needs_clarification` 필드 |
| `error{}` | 없음 | 예외를 `{code, user_message, retryable, fallback_sources[]}`로 정규화하는 계층이 필요하다 |

### 구체적으로 어디를 자르면 되나

```python
# pipeline.py _answer_one() 마지막
if intent == "civil_petition":
    answer = assemble_civil_petition_answer(llm_text, civil_petition_answer)   # ← 문자열로 합치는 지점
else:
    answer = assemble_informational_answer(llm_text, citations)                # ← 여기도
```

`prompt_builder.py` 158~179줄을 보면 두 함수 모두

1. `_strip_no_source_marker(llm_text)` → `(본문, used_source)`
2. `used_source`가 False면 본문만 반환 (= `out_of_scope=true`, 부착 없음)
3. True면 `_render_list("참고 출처", citations, ...)` 같은 걸 **문자열로 이어붙임**

3번만 안 하면 된다. 즉 `_strip_no_source_marker`의 두 값 + `citations` / `civil_petition_answer`를
그대로 묶어서 반환하는 함수를 하나 더 만들면 `ChatResponse`가 완성된다.
`_render_list`·`_format_source_line`은 **CLI(`python3 src/pipeline.py`)에서 계속 쓰므로 지우지 말 것.**

### 서버에서 반드시 해야 하는 것 (프론트가 못 하는 것)

- **마커 제거** — `[SOURCE_USED]`/`[NO_SOURCE]`가 `answer_delta`에 섞이면 사용자 화면에 그대로 찍힌다.
- **오류 정규화** — 문구를 프론트가 만들면 카피 통제가 깨진다. `user_message`는 항상 서버 것.
- **마스킹** — 피드백 자유 의견·대화 로그는 저장 전에 마스킹(PRD-02).
- **빈 배열** — 항목이 없으면 빈 배열을 주면 된다. 프론트가 섹션째 렌더하지 않는다.
  "자료 없음" 같은 빈 상태 문구를 서버가 만들어 보내지 마라(CB-DF-003 규칙).

---

## 6. 이 목을 만들며 발견한 기획서 구멍

프론트가 임의로 메운 곳이다. 백엔드와 값이 갈리면 여기가 원인이다.

1. **`response_type` enum 전량 미정** (CB-DF-004 I-04). `codes.ts`는 `ANSWER|CLARIFICATION|FALLBACK|ERROR`
   4값으로 확정해 뒀는데 기획서엔 `FALLBACK|ERROR` 두 개만 언급된다. 정보성/민원성 구분은 `intent`로 한다.
2. **대화 복원 경로 불일치** — `GET /api/conversation`(PRD-01) vs `/api/sessions/{id}`(CM-DF-003 04절).
3. ~~**`clarification` 옵션 출처 미정** (I-11)~~ → **해소.** 서버가 `question`과 `options[]`를
   함께 준다(`src/clarify.py`). 업무 되묻기는 label만 보내고, 클릭하면 그 업무명이 그대로
   다음 메시지로 전송된다.
4. **`Page<T>` 봉투가 기획서에 없다.** 프론트가 정했다. 필드명(`items/total/page/size`)을 확정해 주기 바란다.
5. **작업 진행 폴링 주기 미정** (10-ad-003-004 issue). 목은 4초/단계로 만들었다. SSE로 갈지 폴링일지 결정 필요.
6. **`GET /api/admin/jobs`(이력 목록)가 04절 표에 없다.** AD-004 실행 이력 화면이 필요로 해서 목에 넣었다.
7. **활동 로그 `action` 값 목록**이 CM-DF-002 07절 이벤트 사전으로 넘겨져 있는데 그 사전이 아직 없다.
   목은 한국어 문자열을 그대로 썼다(`'페이지 삭제 요청'` 등).
8. **AD-008(프롬프트·가드레일)은 서버 초안을 쓰지 않는다.** 04절의 초안 자동저장(`PUT /api/admin/drafts/{screen}`,
   10초 주기)에서 이 화면만 빠진다 — 게시 버튼을 눌러야 서버에 저장되는 편이 통념에 맞다는 판단이라,
   편집은 화면 로컬 + `localStorage`에 두고 **서버 쓰기는 게시 시점 한 번**뿐이다. 그래서 계약이 이렇게 바뀐다.
   - `POST /prompt/evaluate` — body에 `{draft}` 필수(없으면 400). **일시 평가라 서버 초안·평가 결과를 만들지 않는다.**
   - `POST /prompt/publish`, `POST /prompt/publish-requests` — body에 `{draft, gate_passed}` 추가.
     서버에 평가 결과가 남지 않으므로 **회귀 게이트 판정을 요청이 실어 온다**(미통과면 409).
     `gate_passed`는 클라이언트 주장이라 그대로 신뢰하면 안 된다 — 서버가 평가를 보관해 재확인하려면
     `evaluation_id`로 바꾸자(프론트는 어느 쪽이든 맞춘다).
   - 게시 요청에는 초안이 함께 보관된다(`PublishRequest.draft`). 승인은 **요청에 실린 초안**을 게시한다
     (승인자 화면에는 편집분이 없다). 목록 응답에서는 생략해도 된다.
   - `PUT /prompt/draft`·`POST /prompt/draft/discard`는 AD-008에서 호출하지 않는다. 계약 대조용으로 목에만 남아 있다.
   - 한계: localStorage라 **다른 기기·브라우저에서 이어서 편집할 수 없다.** 서버 초안이 필요해지면 되돌리면 된다.

---

## 7. 목 데이터 재생성

`src/mocks/data/pages.ts`·`chunks.ts`는 **실제 코퍼스에서 뽑은 것**이다. 손으로 고치지 마라.
`data/corpus.jsonl`(58페이지) / `data/chunks_all.jsonl`(494청크)가 바뀌면 다시 뽑는다.

- `pages.ts` — 6개 업무를 모두 덮는 30건. `page_id`·`source_url`·`sub_category`·`page_title`은 실제 값.
- `chunks.ts` — 6개 페이지에서 28청크.
- `list_state`·`index_status`·`asset_counts`는 **코퍼스에 없는 P3 확장 필드**다(AD-002 B-6).
  화면 상태를 다 볼 수 있게 일부러 흩뿌려 넣었다.
- `chat.ts`의 답변 본문·금액·기한도 실제 청크에서 가져온 값이라 숫자가 맞다.
  (착오송금 건당 5만원 이상 1억원 이하 · 송금일로부터 1년 이내 → `faq_msdr_apply#0`)

---

## 8. 목이 계약대로 도는지 확인

`src/mocks/selfcheck.ts`가 SSE 이벤트 순서·`Page<T>` 봉투·400/403 검증·파이프라인 진행·AD-008 초안 계약을
실제로 찔러본다.
테스트 러너를 새로 깔지 않고 이미 있는 vite의 SSR 로더로 돌린다.

```bash
cd web && node -e "import('vite').then(async v=>{const s=await v.createServer({server:{middlewareMode:true},appType:'custom'});await s.ssrLoadModule('/src/mocks/selfcheck.ts');await s.close()})"
# → mocks selfcheck: 13개 항목 모두 통과   (파이프라인 진행 확인 때문에 ~7초)
```

**백엔드를 붙인 뒤에도 쓸 수 있다.** `BASE`를 FastAPI 주소로 바꾸고 `setupServer` 두 줄만 지우면
같은 assert가 진짜 서버를 검증하는 계약 테스트가 된다.
