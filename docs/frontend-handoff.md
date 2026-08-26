# 백엔드 핸드오프 — 예솜24 프론트엔드

프론트(React·TS·Vite SPA)는 17화면이 다 만들어져 있다. 이 문서는 "무엇을 만들면 프론트가
그대로 붙는가"만 다룬다.

> 📌 **이 문서는 2026-08-03 작성 시점 기준이고, 그때는 백엔드가 한 줄도 없었다.**
> 이후 2026-08-05~06에 공개 API 6종이 구현됐다(§1 표 참고). **계약(§6 108행)과 작업
> 순서(§3)는 그대로 유효하지만, "아직 없다"는 서술은 §3의 6번(관리자 인증) 이후에만
> 해당한다.** 각 절의 현황 서술을 읽을 때 이 시점 차이를 감안할 것.

**요청/응답 모양은 [`web/src/mocks/README.md`](../web/src/mocks/README.md)가 정본이다.**
엔드포인트 표·SSE 프레임 계약·검증 규칙(400/403/409)·목 시나리오 트리거·파이썬 필드 매핑이 거기 있다.
여기서는 되풀이하지 않고, 리포 최상위 관점(순서·재사용·DB·미구현)만 적는다.

계약의 원천 순서: 기획서(CM-DF-003 03·04절) → `web/src/lib/api/types.ts`(타입) → `web/src/lib/codes.ts`(코드값) → `web/src/mocks/`(그 계약대로 도는 목).

---

## 1. 지금 상태

| | 상태 |
|---|---|
| 프론트 | 17화면 완성. 챗봇 5화면(CB-001~005)은 SPA 한 페이지, 관리자 12화면(AD-000~011)은 라우트 12개 (`web/src/app/router.tsx`) |
| 백엔드 (작성 당시) | 없음. FastAPI 프로젝트 자체가 리포에 없었다 |
| 백엔드 (현재) | **`api/` 18파일 · 공개 API 6종 구현됨** — `POST /api/chat`(SSE) · `GET /api/health` · `GET /api/suggestions` · `POST /api/feedback` · `PATCH /api/feedback/{id}` · `GET /api/sessions/{id}`. 라우터 4개(public·chat·feedback·session). **관리자 API는 아직 없다** — `api/routers/`에 auth·knowledge·pipeline 등이 없고 `src/schema_admin.py`도 없다. 즉 §3의 0~5번은 끝났고 6~16번이 남았다 |
| 데이터 | 목(MSW)이 전부 대신한다. 엔드포인트 **91개**(관리자 85 · 공개 6)를 목이 응답한다. 공개 6종은 이제 실서버로 전환 가능하다(§1 "목을 끄는 법") |
| 코드량 | `web/src` 163파일 / ts·tsx 108개 · css 54개 / 약 19,300줄 |
| git | ~~`web/`은 아직 커밋되지 않았다~~ → **2026-08-05 커밋됨** (현재 `web/` 트래킹 169파일, `node_modules` 제외) |

### 실행

```bash
cd web && pnpm install && pnpm dev     # http://localhost:5173 — 목이 기본 켜짐, 백엔드 없이 전부 동작
```

### 검증

```bash
cd web
pnpm check     # selfcheck 8개 모듈 (app · chat · mocks 12항목 · ad-settings · ad-knowledge · ad-auth ×2 · chat-page)
pnpm build     # tsc -b + vite build
pnpm verify    # tsc + oxlint + check 한 번에
```

`pnpm check`·`pnpm build` 모두 2026-08-03 기준 통과 상태다. 테스트 러너는 안 깔았다 —
`scripts/selfcheck.mjs`가 vite의 SSR 로더로 각 모듈 옆 `selfcheck.ts(x)`를 돌리고, 하나라도 던지면 exit 1이라 CI에 그대로 걸 수 있다.

### 목을 끄는 법

`web/.env.local`(= `.env.example` 복사)에 두 줄. 프론트 코드는 한 줄도 안 고친다.

```
VITE_ENABLE_MSW=false
VITE_API_BASE=http://localhost:8000
```

핸들러 배열에서 일부만 빼면 **부분 전환**도 된다(챗봇만 실서버, 나머지는 계속 목). 자세한 건 mocks/README §1.

> ⚠ **CORS.** vite 프록시가 없고(`web/vite.config.ts`는 react 플러그인만), 세션은 httpOnly 쿠키 전제라
> `credentials: 'include'`로 나간다(`lib/api/client.ts:91`). `VITE_API_BASE`를 채우는 순간 교차 오리진이므로
> FastAPI에 `allow_credentials=True` + `allow_origins=["http://localhost:5173"]`이 필요하다. 쿠키를 쓰는 이상 `*`는 못 쓴다.

---

## 2. 디렉터리 지도

```
web/
├─ .env.example              목 on/off · API 주소 (복사해서 .env.local)
├─ scripts/selfcheck.mjs     pnpm check 러너
└─ src/
   ├─ main.tsx               렌더 전에 목 부트스트랩을 await
   ├─ app/                   라우터 · 관리자 셸 · 인증 가드 · 세션 3타이머 · queryClient
   ├─ lib/                   ★ 계약이 사는 곳
   ├─ components/            ui/(범용) · shadcn/(shadcn/ui 프리미티브) · chat/(말풍선·출처·피드백)
   ├─ routes/                chat/(CB) · admin/(AD 12화면)
   ├─ mocks/                 ★ 가짜 백엔드
   └─ styles/                tokens.css(기획서 고정값 정본) · tailwind.css(시맨틱 브리지) · global.css
```

스타일 스택은 **Tailwind CSS v4 + shadcn/ui**다(2026-08-04 재디자인). 기획서 고정값(#7E57C2 ·
#FEE500 · Noto Sans KR · 820/720px)은 `styles/tokens.css`가 정본이고 `styles/tailwind.css`가
shadcn 시맨틱 변수(--primary 등)로 브리지한다 — **색·치수를 바꾸려면 tokens.css만 만지면 된다.**
백엔드 작업에는 영향이 없다(스타일은 전부 프론트 빌드 안에서 끝난다).

| 경로 | 무엇인가 | 백엔드가 볼 이유 |
|---|---|---|
| `lib/api/types.ts` | **프론트가 기대하는 스키마 전부.** ApiError · `Page<T>` · Source · Attachment · ChatResponse · ChatStreamEvent · HealthResponse 등 | Pydantic 모델을 여기에 맞추면 끝. 여기 없는 필드는 프론트가 안 쓴다 |
| `lib/codes.ts` | **enum 정본.** 업무 6종 · intent · response_type · error code · 역할(누적형 VIEWER<OPERATOR<EDITOR<ADMIN) · job type/status · index status | 서버 enum 값이 다르면 배지·분기가 통째로 어긋난다 |
| `lib/constants.ts` | 기획서에 박힌 상수(세션 8h/30분/30분, 로그인 5회 10분, 캐시 24h, 파이프라인 동시 1, Smoke 30, 파이프라인 6단계 이름) | 서버도 같은 값을 강제해야 한다. 프론트 판정은 우회 가능하다 |
| `lib/api/client.ts` | REST 래퍼. 쓰기 요청에 `request_id` 자동 부착, 위험 작업 `reason`, 폴링 `X-Poll: 1`, 401→세션 만료 | 공통 규약(§6 C행)이 여기서 나온다 |
| `lib/api/chat.ts` | SSE 클라이언트. fetch+ReadableStream 직접 파싱(EventSource는 POST 불가), 30초 무응답 폴백, abort=중단 | SSE 프레임을 정확히 이 모양으로 보내야 한다 |
| `mocks/handlers/` | 91개 엔드포인트 목. 도메인별로 나뉜다 | **응답 예시가 필요하면 여기를 읽는 게 가장 빠르다** |
| `mocks/data/pages.ts`·`chunks.ts` | 실제 코퍼스에서 뽑은 목 데이터(30페이지·28청크) | 손으로 고치지 말 것 (mocks/README §7) |
| `mocks/selfcheck.ts` | SSE 순서·`Page<T>` 봉투·400/403·파이프라인 진행을 실제로 찔러보는 12항목 | `BASE`만 바꾸면 **실서버 계약 테스트로 재사용된다** (mocks/README §8) |
| `routes/admin/*/api.ts` | 기획서에 계약이 없어 프론트가 제안한 스키마들 (pipeline · logs · evaluation · rag · promptops · access) | 해당 도메인 스키마의 정본이 이 파일들이다 |

---

## 3. 백엔드가 만들 것 — 작업 순서

의존성 순이다. **0번과 1번만 있으면 챗봇이 실제로 돈다.**

| # | 만들 것 | 이게 없어 막힌 화면 | 기존 파이썬 재사용 |
|---|---|---|---|
| **0** | ✅ FastAPI 뼈대 — CORS(쿠키), 오류를 `ApiError{code,user_message,retryable,fallback_sources,request_id}`로 정규화하는 예외 핸들러, 목록 `Page<T>` 봉투, 쓰기 요청 `request_id`/`reason` 검증(없으면 400), 403에 request_id | 전부 | `db.py`(엔진·세션) |
| **1** | ✅ ★ **`POST /api/chat` (SSE)** — `accepted → answer_delta* → done \| error` (⚠️ `sources`·`attachments` 이벤트는 2026-08-05에 없앴다 — 출처는 `done`에 실린다) | 챗봇 5화면(CB-001~005) 전부 | **구현됨** — `api/rag/sse.py`. `pipeline._answer_one()`이 아니라 `api/rag/answer.py`가 빌딩블록을 직접 조립한다 |
| 2 | ✅ `GET /api/health` | CB-004 Case 6 점검 배너 · 입력 잠금 (`disabled_features`에 `chat` 포함 여부로 판정) | — |
| 3 | ✅ `GET /api/suggestions` | CB-001 자주 묻는 질문 TOP 10. 없으면 `WelcomeScreen.tsx`의 `FALLBACK_SUGGESTIONS` 상수로 떨어진다 | — |
| 4 | ✅ `POST /api/feedback` · `PATCH /api/feedback/{id}` | 답변 하단 피드백 위젯 | **구현됨** — `feedback` 테이블 신설 완료 |
| 5 | ✅ `GET /api/sessions/{session_id}` | 새로고침·재방문 대화 복원(24h) | **구현됨** — `chat_sessions`/`chat_messages` 신설 완료 |
| 6 | 관리자 인증 — `login`·`logout`·`session`·`session/extend`·`reauth`·`roles`·`me/permissions` | **관리자 12화면 전부.** `RequireAuth`가 `GET /api/admin/session`으로 게이트한다 | 없음 |
| 7 | 활동 로그 쓰기 — `admin_activity_logs` 적재 | 6번 이후의 모든 쓰기 API가 여기 기록된다. 나중에 붙이면 소급 불가라 6번과 같이 붙이는 게 싸다 | 없음 |
| 8 | 지식베이스 조회 — `knowledge/pages`·`knowledge/chunks` | AD-002 | **`documents`·`document_chunks` 테이블이 이미 있다.** 가장 저렴한 관리자 화면 |
| 9 | 파이프라인 — `jobs` (POST/GET/{id}/cancel/retry/rollback) + `pipeline/changes`·`estimate` | AD-004, AD-002·003의 재수집·재적재 | `src/crawler/` 수집·변환·청킹 스크립트, `embed_corpus.py` |
| 10 | 변경 요청 — `previews` · `change-requests` (+approve/reject) | AD-003, AD-002 삭제/제외 | 없음 |
| 11 | 대화 로그 — `logs` 7종 | AD-005. 1·4·5번이 남긴 데이터가 있어야 의미가 있다 | `rag_runs`가 뼈대. 컬럼 부족(§5).<br>**검색 후보·단계별 소요는 Langfuse가 전담한다**(2026-08-04 팀 결정에 맞춰 프론트 계약에서 걷어냄). 상세 응답에는 `langfuse: {id, url}`과 `total_latency_ms`만 담고, 화면은 링크 한 줄로 넘긴다 — 서버가 채울 것은 `rag_runs.trace_id`뿐이다 |
| 12 | 대시보드 — `dashboard/summary`·`trend`·`resources` | AD-001. 9·7·11번의 집계다. 마지막에 붙는 게 맞다 | — |
| 13 | 평가 — `evaluations/*` | AD-006 | `eval_pipeline_retrieval.py`·`eval_pipeline_generation.py`, `evaluation_dataset`·`test_set` 테이블 |
| 14 | RAG 파라미터 — `rag-params/*` | AD-007 | `pipeline.py` 상수(K_CANDIDATES·K_FINAL·USE_*), `retrieval.HYBRID_LINEAR_ALPHA` |
| 15 | 프롬프트·가드레일 — `prompt/*`·`guardrails/*` | AD-008 | `prompt_builder.SYSTEM_INSTRUCTION`·`FEW_SHOT_EXAMPLES` |
| 16 | 운영 정책 — `ops-policy`·`cache/*`·`blocks`·`suggested-questions` | AD-009 | 없음 |

> 13~16은 서로 독립이라 순서를 바꿔도 된다. 6·7만 선행이면 된다.

---

## 4. 기존 파이썬 코드 재사용 지도

**핵심 한 줄: `rag_answer()`가 마크다운 문자열로 평탄화하는 마지막 단계만 걷어내면 `ChatResponse`가 된다.**
그 문자열을 만드는 재료는 이미 구조화된 dict이고, `citation.py`가 내놓는 dict는 `Source` 타입과 **필드명까지 일치한다.**

필드 단위 대응표는 mocks/README §5에 있다. 여기서는 모듈별로 있는 것/없는 것만 가른다.

| 모듈 | 이미 있는 것 | 없는 것 · 손볼 곳 |
|---|---|---|
| `src/pipeline.py` | `rag_answer(query)` → 답변 문자열. `_rag_answer_traced()`가 단계별 `timings` 포함 튜플 반환(`timings["total"]` → `latency_ms`). `_answer_one()`이 분류→검색→재정렬→근거조립→프롬프트→LLM 전 과정 | ⚠ **평탄화 지점 2곳**: `_answer_one()` 79~82줄 `assemble_*_answer(...)` 호출. 여기서 문자열로 합치는 대신 dict를 그대로 반환하면 된다. 복합 질문은 106줄 `"\n\n".join(f"**{q}**\n{a}")` — 이 `**제목**` 마크다운이 곧 §7-1의 원인이다 |
| `src/citation.py` | `format_citation(chunk_id)` → `{page_id, breadcrumb, title, url}`. `format_all_citations()`가 page_id 기준 중복 제거(관련도 순 유지) | **그대로 직렬화하면 `Source`다.** 손댈 게 없다 |
| `src/civil_petition.py` | `build_civil_petition_answer(top)` → `{procedure, documents[], links[]}`. `documents`=`{page_id,label,url}`, `links`=`{title,url,breadcrumb}` | `Attachment{label,url,kind}`로 변환 필요 — documents→`kind:'document'`, links→`kind:'link'`(`title`을 `label`로). `procedure`는 프롬프트 재료이므로 응답에 안 내보낸다 |
| `src/prompt_builder.py` | `_resolve_used_source(llm_text, recheck)` → `(본문, used_source)`. 마커 변형(`[SOURCE USED]`)까지 정규화한 뒤, 마커가 `[NO_SOURCE]`일 때만 `source_check.recheck_source_usage()`로 한 번 더 판정한다(`pipeline.USE_SOURCE_RECHECK=True`) | `assemble_informational_answer()`(158~165) · `assemble_civil_petition_answer()`(168~179)가 `_render_list`로 문자열을 이어붙이는 지점. **API는 이 3번 단계만 안 하면 된다.** ⚠ `_render_list`·`_format_source_line`은 CLI(`python3 src/pipeline.py`)가 계속 쓰므로 지우지 말 것 |
| `src/retrieval.py` | `route_search_chunks(query,k)` → `[(chunk_id, score, text)]`. `PgVectorDenseRetriever`가 Supabase `document_chunks`에 직접 쿼리(`is_active` 필터 포함, exact search) | ⚠ 엔진 조립(`_build_engines()`)이 `src/crawler/chunking.py`로 로컬 JSONL을 읽어 BM25를 만든다 — **서버 프로세스가 `data/corpus.jsonl`·`chunks_all.jsonl`에 접근 가능해야 한다.** 첫 호출에서 한 번만 조립되는 싱글턴이라, 웜업 요청을 한 번 태우는 편이 좋다 |
| `src/llm_client.py` | `call_hyperclova(messages)` — ChatClovaX `.invoke()` | 🔴 **단발 호출이라 스트리밍이 안 된다.** `answer_delta`를 실제 토큰 단위로 흘리려면 `.stream()` 계열로 바꿔야 한다. 안 바꾸면 완성된 답변을 서버가 쪼개 보내는 흉내(목과 같은 방식)만 가능하다.<br>2026-08-04 이후 `source_check` 재확인 호출이 추가돼 `done`까지의 총 대기가 더 늘었다 |
| `src/query_classifier.py` | `classify_intent(query)` → `informational`/`civil_petition` (OpenAI structured output, 실패 시 informational 폴백). `classify_query_type()`은 코사인 방식 | ⚠ **OpenAI 키가 필요하다**(`OPENAI_API_KEY`). 기본 모델은 코드상 `gpt-5.4-mini`(`.env`의 `OPENAI_INTENT_MODEL`로 교체 가능). 2026-08-04 커밋 주석이 모델 변천을 `HCX-007 → gpt-4o-mini → gpt-5.4-mini → gpt-5.6-luna`로 적어 기획서의 luna가 현재 방향임을 확인했다.<br>🔴 **이 폴백이 여태 상시 발동하고 있었다** — 일부 모델이 `temperature=0`을 거부해 `except`가 매번 삼켰다(2026-08-04 수정, `_parse_intent`). 즉 실서버 답변은 100% informational이었고 `civil_petition` 경로(필요 서류·신청 페이지)는 한 번도 실행된 적이 없다. **API를 붙일 때 이 경로를 반드시 E2E로 한 번 태울 것** |
| `src/query_decomposer.py` | `decompose_query(query)` → 하위 질문 리스트 | **§6 B7의 `sub_answers[].title` 재료가 이미 여기 있다.** 하위 질문 문자열이 곧 제목이다 |
| `src/candidate_ranking.py` | `rerank()`·`top_k_cut()` | 리랭커는 `pipeline.USE_RERANKER=False`로 꺼져 있다 — CPU에서 문항당 96초가 걸려 실서비스에 못 쓴다. **CPU에서는 켜지 말 것.** GPU 재검증 후 도입 여부를 정한다(루트 `README.md` 2.4절) |
| `src/performance.py` | `measure_time()` 컨텍스트 매니저 | 초 단위 → `latency_ms`는 ×1000 |
| `src/db.py` | `get_engine()`·`get_session()` (Supabase transaction pooler, NullPool) | FastAPI 의존성으로 그대로 감싸면 된다 |
| `src/app.py` | Streamlit 데모 UI | **이관 대상 아님.** 이 프론트가 대체한다 |

**아예 없는 것** (새로 써야 함): `response_type`, `clarification`(역할 되묻기), 오류 정규화 계층, 세션·대화 저장, 마스킹, 스트리밍.

---

## 5. DB에 없는 테이블

> 📌 **2026-08-07 갱신.** 작성 당시 `src/schema.py`는 6개(중 1개는 이후 삭제)를 만들었으나
> 지금은 **9개**다 — 챗봇 저장·복원·피드백·추천질문 테이블이 §3의 3~5번을 구현하며 추가됐다.
> 아래 두 표를 실제 스키마에 맞춰 갱신했다. **관리자용 테이블은 여전히 하나도 없다.**

### 있는 것

| 테이블 | 용도 | 관리자 화면과의 관계 |
|---|---|---|
| `documents` | 수집 원본 58페이지 | AD-002 페이지 목록의 뼈대 |
| `document_chunks` | 검색 단위 494청크 + `embedding vector(1024)` | AD-002 청크 목록, 검색 |
| `evaluation_dataset` | 골든셋(testset_all) + embedding | AD-006 문항 |
| `test_set` | held-out(testset_pipeline) | AD-006 문항 |
| `rag_runs` | 질의 1건의 실행 기록 | AD-005 대화 로그의 뼈대 |
| ~~`rag_retrieval_results`~~ | **2026-08-04 삭제.** 질문 1건당 20행 부담 대비 실익이 낮다고 판단, Langfuse trace로 이관(팀 결정) | 프론트도 같은 방향으로 정리했다 — AD-005 상세의 `retrieval[]`·`stages[]`를 없애고 Langfuse 링크(§6 G5)로 대체 |
| **`feedback`** ✨ | 답변별 좋아요·싫어요 + 사유·의견 | §3 4번 구현되며 추가됨. 아래 "없는 것"에서 올라왔다 |
| **`chat_sessions`** ✨ | 대화 세션 | §3 5번(24h 복원) 구현되며 추가됨 |
| **`chat_messages`** ✨ | 세션 내 메시지 | 〃 |
| **`suggested_questions`** ✨ | 추천 질문(자주 묻는 질문 TOP 10) | `GET /api/suggestions` 구현되며 추가됨 |

`documents.is_active` → `document_chunks.is_active` 동기화 트리거가 걸려 있다
(`sync_document_chunks_is_active`, schema.py:235-248). 관리자 '검색 제외'는 이 플래그로 처리하면 된다.

### 없는 것 — 관리자 화면이 요구하는 것

기획서 CM-DF-003 04절이 **이름과 컬럼까지 적어 둔 것**(`pipeline_jobs`, `admin_activity_logs`, `admin_sessions`, `testsets`/`testset_items`)조차 코드에 없다.

| 없는 테이블(제안명) | 필요한 화면·엔드포인트 | 근거 |
|---|---|---|
| `admin_accounts` · `admin_sessions` · `admin_login_failures` · `password_reset_tokens` | AD-000·AD-010 전부 | `admin_sessions`의 3필드(`session_started_at`·`last_activity_at`·`last_auth_at`)는 CM-DF-003 04절에 스펙이 있다 |
| `admin_activity_logs` | AD-011 + 모든 쓰기 API | CM-DF-003 04절: 실행자·작업·대상·전후값·사유·결과 + `detail` JSONB. **추가 전용 · 90일 보관 · 상세는 이 레코드 하나로 렌더(조인 금지)** |
| `pipeline_jobs` (+ 단계) | AD-004, AD-002/003의 재수집·재적재 | CM-DF-003 04절이 컬럼 목록까지 적어 뒀다: `job_type`·`status`·`current_stage`·`failed_stage`·`job_error`·`retry_count`·`stage_counts`·`reason`·실행자·시각 |
| `change_requests` · `previews` | AD-003 적재 승인, AD-002 삭제 | 삭제도 DELETE가 아니라 change-request다(§6 K8) |
| `evaluation_runs` · `evaluation_results` | AD-006 실행 이력·게이트 판정 | schema.py:5-6이 "안 만든다"고 명시 |
| `testset_items` 버전 | AD-006 문항 편집·`testset_version` | 현 `evaluation_dataset`/`test_set`에 버전·편집 이력 컬럼이 없다 |
| `rag_param_versions` (current/draft/history) | AD-007 | 파라미터가 지금은 파이썬 상수다(`pipeline.K_CANDIDATES` 등) |
| `prompt_versions` · `prompt_drafts` · `prompt_publish_requests` · `guardrail_rules` | AD-008 | 프롬프트가 지금은 `prompt_builder.SYSTEM_INSTRUCTION` 문자열 상수다 |
| `ops_policy` · `query_cache` · `rate_limit_blocks` | AD-009 | `suggested_questions`는 이제 있다(위 표) |
| `admin_drafts` | `PUT /api/admin/drafts/{screen}` 10초 자동저장 | — |
| `documents` 확장 컬럼 | AD-002 상세·수집 대상 탭 | `owner`·`collection_status`·`collection_note`·`link_check`·`first_indexed_at`·`split_rule`·`index_status`·`pending_action` — 전부 `corpus.jsonl` 16키에 없는 P3 확장 필드 (§6 K2·K3) |

---

## 6. 프론트가 정한 계약 (백엔드가 맞춰야 할 것)

구현·검증 과정에서 나온 백엔드 요청 **113건을 중복 제거해 108행으로 합쳤다**(여러 에이전트가 각자 적어 마커 제거·피드백 키·폴링·재인증·복합 질문 등이 중복 기재돼 있었다).
**FE정** = 기획서에 없어서 프론트가 정한 것 → 백엔드가 다르게 만들면 화면이 깨지니, 값을 바꿀 거면 먼저 알려 달라.
근거 칸의 `파일:줄`은 `web/src` 기준이다.

### C. 전 API 공통

| # | 계약 | 구분 | 근거 |
|---|---|---|---|
| C1 | 목록 응답은 전부 `{items, total, page, size}` 봉투. 쿼리 `?page=&size=&sort=필드:asc\|desc`, 기본 size=20 | **FE정** | `lib/api/types.ts:24` |
| C2 | 쓰기 요청 body에 `request_id`(멱등키) 필수. 위험 작업은 `reason` 추가 필수. 없으면 400 | 기획서 CM-DF-003 04절 | `lib/api/client.ts:70-81` |
| C3 | 단, `POST /api/admin/logs/exports`·`/evaluations/candidates`는 비위험 → **reason을 필수로 두지 말 것** | **FE정** | 요청 57 |
| C4 | 권한 부족은 **403 + `request_id`**. 프론트가 버튼을 숨겨도 403은 온다 — 항상 처리한다 | 기획서 PRD-02 §3-d | `lib/api/client.ts:27-31` |
| C5 | 세션은 httpOnly 쿠키(`credentials:'include'`). 기획서 미확정(PRD-02 MED-05)이라 쿠키로 진행했다 | **FE정** | `lib/api/client.ts:91` |
| C6 | 폴링 요청은 `X-Poll: 1` 헤더를 붙인다. 서버는 이 요청을 **유휴 세션 타이머 갱신·활동 로그 '조회' 기록에서 제외**해야 한다 | **FE정** (PRD-02 MED-06 제안 중 택1) | `lib/api/client.ts:19` |
| C7 | 오류 문구는 **항상 서버 `user_message`**. 프론트는 서버에 도달조차 못 한 경우에만 고정 문구를 쓴다 | 기획서 | `lib/api/client.ts:23-31` |
| C8 | 모든 시각은 브라우저 타임존과 무관하게 KST 고정 표기 | 기획서 PRD-02 §3-f | `lib/constants.ts` TIMEZONE |

### B. 챗봇 `POST /api/chat` (SSE)

| # | 계약 | 구분 | 근거 |
|---|---|---|---|
| B1 | 🔴 자기보고 마커 `[SOURCE_USED]`/`[NO_SOURCE]`를 **`answer_delta`에 절대 싣지 마라.** 첫 델타를 흘리기 전에 서버가 뗀다. 프론트는 첫 줄 선두 1회 제거만 방어하고 버퍼링하지 않는다 | 기획서 CM-DF-003 06절 | 요청 3·14 |
| B2 | `out_of_scope=true`면 `sources`·`attachments` 이벤트를 보내지 마라(그렸다가 done에서 걷어내는 깜빡임) | | 요청 5 |
| B3 | `accepted`의 `session_id`·`request_id`는 `done`의 값과 **같아야 한다**(URL replaceState·피드백 키) | | 요청 11 |
| B4 | `done`에 `business_function` 필수 — 역할 칩 유지/초기화(주제 변경) 판정의 **유일한 근거**. 되묻기 턴에도 필요 | | 요청 9 |
| B5 | `sources`는 중복 제거·관련도 정렬을 **서버가 끝낸 상태**로 보낸다 | | 요청 2 |
| B6 | `attachments.kind`로 섹션이 갈린다 — `document`=필요 서류, `link`=신청 페이지 CTA. 둘 다 `label`·`url` 필수(URL은 화면에 노출 안 하고 도메인만 표시) | | 요청 4 |
| B7 | **신규 스키마 요청**: `sub_answers: [{title, answer, sources[], attachments[]}]` 최대 3, 순서=표시 순서. 하위 제목을 `answer` 안 `**…**` 마크다운으로 내리는 방식은 받지 않는다("마크다운 파싱 불필요"). 하위 간 sources 중복 제거 금지 | **FE정** | 요청 7·81 / §7-1 |
| B8 | `response_type` enum이 기획서 미정(FALLBACK·ERROR 2개만 언급). 프론트는 `ANSWER\|CLARIFICATION\|FALLBACK\|ERROR`로 확정해 뒀다. 복합 질문 식별값(`COMPOSITE`)이 추가로 필요 | **FE정** | `lib/codes.ts:42` / 요청 82 |
| B9 | 역할 되묻기 응답 방식 확정 요청 — 지금은 라벨 문자열(`잘못 보낸 사람(송금인)`)만 `message`로 간다. `ChatRequest`에 `role`을 넣을지, 서버가 직전 되묻기 컨텍스트로 원질문을 복원할지 | | 요청 8·85 / §7-3 |
| B10 | `clarification.options[]`가 없다. 지금은 역할 버튼 라벨이 프론트 상수다. 착오송금 외 주제가 생기면 서버가 줘야 한다 | **FE정** | mocks/README §6-3 |
| B11 | 오류 응답의 `request_id`를 **항상** 채울 것. 비면 문의용 요청 ID 줄이 사라진다 | | 요청 6 |
| B12 | 429는 SSE를 열지 말고 HTTP 429 + `Retry-After` + `ApiError`(`retryable:false`). "Retry-After 동안 입력 잠금"을 구현하려면 **본문에 `retry_after_s`가 필요**하다 | | 요청 12 |
| B13 | `accepted` 후 30초 무응답 시 서버가 `error` 이벤트를 줄 수 있으면 프론트 고정 타임아웃 문구를 뺄 수 있다 | | 요청 87 |
| B14 | 같은 질문 재시도 카운터(최대 2회)가 지금은 클라이언트 로컬이라 새로고침하면 0으로 돌아간다. 서버가 내려주면 그 값을 쓴다 | | 요청 15 |
| B15 | 범위 외 응답의 추천 칩은 현재 전역 `/api/suggestions` 상위 2건 재사용. `done`에 `next_questions[]`가 있으면 그쪽이 맞다 | | 요청 88 |
| B16 | 챗봇 아바타 이미지 출처 확정 요청(`bot_avatar_url` 같은 필드인지 정적 에셋인지) | | 요청 84 / §7-2 |

### B'. 챗봇 부속

| # | 계약 | 구분 | 근거 |
|---|---|---|---|
| B17 | `GET /api/health`의 `maintenance=true`(또는 `status='maintenance'`) + `user_message`가 Case 6 전면 안내의 **유일한 판정·문구 근거**. 해제하면 30초 안에 자동 원복 | | 요청 13 |
| B18 | `disabled_features` 값 사전 확정 요청 — 프론트는 `'chat'` 포함 여부로 입력을 잠근다. 키 문자열이 다르면 잠금이 통째로 안 걸린다 | | 요청 86 |
| B19 | `GET /api/sessions/{id}` 응답 스키마가 types.ts에 없어 목 모양을 그대로 썼다: `{session_id, last_activity_at, messages[{role,text,request_id?,response?{sources,attachments,out_of_scope}}]}`. 24h 초과·없는 세션은 **404** | **FE정** | `routes/chat/ChatPage.tsx:69` / 요청 10 |
| B20 | 🔴 `POST /api/feedback`의 `request_id`는 **'피드백을 붙일 답변의 id'**로 확정할 것. 공통 멱등키와 필드명을 공유하는 구조라 서버 문서에도 명시가 필요하다(답변당 1건 upsert 키도 이 값) | | 요청 0·83 |
| B21 | `PATCH /api/feedback/{id}`는 `reason_codes`가 비어도 `comment`만 있으면 **200**이어야 한다(등록 활성 조건 = 칩 또는 의견 하나라도). 현재 목은 400을 준다 | | 요청 1 |
| ~~B22~~ | ~~푸터 '개인정보처리방침'·'AI 서비스 이용안내' 실제 URL 2종 필요~~ → **철회(2026-08-05)**. 푸터 자체를 제거해 URL이 필요 없어졌다. 다만 대화가 마스킹 후 보관된다는 사실을 챗봇 화면에서 알릴 경로도 함께 사라졌으니, 기관 공통 푸터나 다른 고지가 이를 덮는지 확인이 필요하다 | | 요청 89 |

### A. 인증·권한 (AD-000 · AD-010)

| # | 계약 | 구분 | 근거 |
|---|---|---|---|
| A1 | 로그인 401 본문의 `user_message`는 **계정 존재 여부를 드러내지 않는 공통 문구**여야 한다(기획서 원문: `로그인에 실패했습니다. 아이디와 비밀번호를 다시 확인해 주세요.`). 현재 목은 남은 시도 횟수를 덧붙인다 | | 요청 16 |
| A2 | 임시 잠금은 **423** + `user_message`. 잔여 카운트다운을 그리려면 본문에 `locked_until`(ISO)이 추가로 필요 | | 요청 17 |
| A3 | 관리자 역할이 없는 계정 로그인은 **403**(Case 3 권한 없음 화면). 본문 `request_id`를 화면에 그대로 표시한다 | | 요청 18 |
| A4 | **신규 계약 5종**: `GET /api/admin/security/summary`·`GET/POST /api/admin/accounts`·`GET /api/admin/login-failures`·`GET /api/admin/activity/risky-today`. 필드 정의는 `routes/admin/settings/access/api.ts`가 전부 | **FE정** | 요청 19 |
| A5 | `AccountRow`는 **계정 상태**(`status: 활성\|비활성\|초대됨\|잠김`)와 **세션 상태**(`session: CURRENT\|ACTIVE\|NONE`, `session_idle_expires_in_s`)를 분리할 것. 한 컬럼에 섞으면 '비활성인데 접속 중'을 표현 못 한다 | | 요청 20 |
| A6 | `is_self`·`is_last_admin`은 **서버가 판정**해야 한다. 프론트는 한 페이지만 보므로 '마지막 남은 ADMIN'을 알 수 없다(안전 규칙이 뚫린다) | | 요청 21 |
| A7 | 역할 변경·비활성화는 `PATCH /api/admin/accounts/{id}` 하나(`{role}` 또는 `{status:'비활성'}` + reason + request_id). **반영 즉시 대상 계정 세션 종료 + '권한 변경' 이벤트 기록은 서버 책임** | | 요청 22 |
| A8 | 위험 작업 전 재확인은 `needsReauth`(마지막 인증 30분 경과)일 때만 `POST /reauth` 선행. 재확인 성공은 `last_auth_at`과 `last_activity_at`을 **함께** 갱신 | 기획서 CM-DF-003 04절 | 요청 23 |
| A9 | 비밀번호 재설정 요청은 계정 존재 여부와 무관하게 **같은 202**(계정 탐색 차단) | | 요청 24 |
| A10 | 초기 설정·재설정 메일 링크는 `/admin/login?reset_token=<token>`. 기획서가 제안한 `/admin/password/reset/confirm`은 라우터에 없다 | **FE정** | 요청 25 |
| A11 | `reset-confirm`: 만료·사용된 링크는 **410**, 비밀번호 정책 위반은 **400**으로 가를 것. `ApiError.code` 5종으로는 못 가른다. 화면은 410일 때만 ① 재설정 요청으로 되돌린다 | | 요청 90 |
| A12 | **신규**: `POST /api/admin/password/change` — `{request_id, current_password, new_password}` → 204. 불일치 400 + user_message, 5회 실패 시 10분 잠금, 성공 시 **현재 세션 유지 + 같은 계정의 다른 세션만 종료** + '비밀번호 변경' 이벤트. 위험 작업 재확인 대상 아님 | **FE정** | 요청 91 |
| A13 | `security/summary.account_count`는 '초대됨·비활성 포함 전체 계정 수'로 정의할 것 | | 요청 94 |
| A14 | `GET /api/admin/roles`의 `label`·`description` 문구 정본 확정 필요. 셀렉트는 `${role} (${label})`로 조립한다 | | 요청 93 |

### D. 대시보드 (AD-001)

| # | 계약 | 구분 | 근거 |
|---|---|---|---|
| D1 | 대시보드 API가 CM-DF-003 04절에 **하나도 없다.** 신규 3종 제안: `GET /api/admin/dashboard/summary`·`/trend?range=7\|30\|90`·`/resources?range=7\|30\|90`. 응답 모양 정본은 `mocks/handlers/extra/ad-dash-activity.ts` | **FE정** | 요청 27 |
| D2 | 상태 칩 [실패 건 보기 →]의 목적지를 서버가 `service.cause`로 알려줄 것 — `ERROR_RATE`면 AD-005 실패 필터, `PIPELINE`이면 AD-004. FE는 이 값으로만 분기한다 | **FE정** | 요청 28 |
| D3 | **상시 지표 5종(`indicators`)은 응답에서 뺐다** — 2026-08-04 팀 결정(P-11). 임계치 값이 기획서 어디에도 없고, 5종 중 '요청 제한 초과'·'링크 점검 실패'는 백엔드에 원천이 없다(grep 무결과). 기준 없이 경고를 띄우지 않기로 했다. **만들지 말 것.** 임계치가 확정되면 `[{key,label,value_text,threshold_text,exceeded}]`로 되살린다 | **FE정** | 요청 29 |
| D3' | 리소스 카드 표시 문자열($·M 등)은 서버가 완성해서 줄 것 — 통화·단위 표기를 프론트가 지어내지 않는다. **2026-08-26: 통화를 ₩ → $ 로 바꿨다** — 원천이 Langfuse 이고 USD 로 주는데 환율을 정한 사람이 없어, 환산해서 지어내는 대신 원치를 그대로 쓴다(`cost[].usd`). 단가가 등록되지 않은 모델(HCX-007)은 `cost_breakdown[].share=null` + 토큰 수로 내려간다 — 0원으로 채우면 '공짜'로 읽힌다 | **FE정** | 요청 30 |
| D4 | 단계별 평균 응답시간은 **응답 8구간 고정**이며 서버가 준 배열 순서를 그대로 그린다. 순서를 바꾸거나 구간을 빼면 화면이 틀어진다 | 기획서 CM-DF-003 05절 | 요청 31 |

### L. 활동 로그 (AD-011)

| # | 계약 | 구분 | 근거 |
|---|---|---|---|
| L1 | `GET /activity/events`에 `action`·`from`(YYYY-MM-DD) 파라미터 필요. `q`는 목이 action+target을 보지만 **서버는 target·reason을 대상**으로 할 것 | | 요청 32 |
| L2 | **신규**: `GET /api/admin/activity/overview` — `today_count`·`last_recorded_at`·`purge_due_this_week`·`actions[]`·`actors[]`. 필터 선택지를 FE가 하드코딩하지 않으려면 이 facets가 필요 | **FE정** | 요청 33 |
| L3 | 상세의 `snapshot`은 **전후값이 있는 이벤트에만** 실을 것(FE는 존재 여부로만 블록을 그린다). `approval{requested_by, approved_by, reauthed_at}`도 마찬가지 | | 요청 34 |
| L4 | 이벤트 `target`은 '사람이 읽는 이름 + (ID)' 형식(ID 단독 노출 금지). `target_name`+`target_id`로 나눠 주면 FE가 `lib/format.ts:58 formatTarget`으로 조립한다 | | 요청 35 |
| L5 | **접속 IP는 서버가 마스킹**해서 보낼 것. 지금은 FE가 임시로 가린다. IP 보관 30일 / 로그 90일이라 **31~90일 전 이벤트의 IP 표기 규칙**(빈칸/—)도 정해야 한다 | | 요청 36 / §7-6 |
| L6 | `POST /activity/exports` 산출물 형식(CSV/XLSX)·파일명·건수 상한·완료 통지 방식이 기획서에 없다. 지금 화면은 '시작했습니다'까지만 알린다 | | 요청 37 |
| L7 | `activity/risky-today`의 `id`는 AD-011 `event_id`와 **같은 값**이어야 한다(현 목은 `ev_r01~03`이라 딥링크가 해석되지 않는다) | | 요청 92 |
| L8 | 활동 로그 이벤트가 파이프라인 작업의 `job_id`를 남겨야 AD-004 [작업 기록 보기] 딥링크(`?q={job_id}`)가 결과를 낸다. 정규식 추측 대신 이벤트에 `action_code`/`link`를 실어 이동처를 서버가 정하는 편이 안전 | | 요청 107 |
| L9 | 위험 작업 [상세]는 `/admin/settings/activity?event=<event_id>`로 이동한다. 페이지 이력 링크는 `?q={page_id}` | **FE정** | 요청 26·47 |

### K. 지식베이스 (AD-002 · AD-003)

> AD-003(신규 URL 추가)은 **AD-002 화면 안의 인라인 블록**이다(2026-08-04, P-12). 화면만 합쳤고 **API는 그대로**다 — `previews`·`change-requests`·`jobs` 호출 순서와 계약에 변화 없음.

| # | 계약 | 구분 | 근거 |
|---|---|---|---|
| K1 | `GET /knowledge/pages?q=&business=&state=&sort=&page=&size=` → `Page<KbPage>`. `state`는 한글 3상태(`최신`·`변경 감지`·`적용 대기`)와 `index_status` 코드를 **둘 다** 받는 계약으로 붙였다 | **FE정** | 요청 38 |
| K2 | `KbPage`에 `owner`(담당)·`collection_status`·`link_check`·`first_indexed_at`이 없다. AD-002 상세 '수집·점검' 카드가 요구 | | 요청 39 |
| K3 | `pages`에 `tab=indexed\|targets` 파라미터와 **탭별 total** 필요. 수집 대상 탭은 적재 전 후보·협의 중 행을 포함하고 행마다 `collection_status`(CANDIDATE/LOADED/ROBOTS_BLOCKED/SKIPPED/FAILED)·`owner`·`split_rule`이 있어야 한다 — 셋 다 `corpus.jsonl` 16키에 없는 P3 확장 필드다 | | 요청 97 |
| K4 | `KbChunk`에 `split_rule`(분할 방식)이 없어 화면에서 뺐다 | | 요청 40 |
| K5 | `POST /previews` 요청에 사람 입력값(`required`·`page_title`·`sub_category`·`note`·`summary`)을 함께 받고, 응답에 `extracted.page_id`(업무 접두어+주제 규칙 초안, 수정 가능)·`estimate`(예상 소요)·`split_rule`·**하위분류 자동추출 실패 플래그**를 추가할 것 | | 요청 41·96 |
| K6 | **신규**: `POST /api/admin/previews/{preview_id}/reject` (reason 필수) | **FE정** | 요청 42 |
| K7 | 삭제는 DELETE가 아니라 `POST /change-requests {action:'DELETE', target_page_id, target_title, business_function}` + reason. 성공 후 해당 페이지 `list_state`가 '적용 대기'로 바뀌어야 화면이 맞는다 | | 요청 43 |
| K8 | `POST /change-requests`(action='ADD') 본문에 **`page` 객체**를 받아야 한다: `page_id`·`source_url`·`business_function`·`sub_category`·`page_title`·`required`·`note`·`summary`·`owner`. 현 계약엔 3개 자리뿐이라 수집 근거가 서버에 도달하지 못한다 | | 요청 95 |
| K9 | 재수집=`POST /jobs {type:'SELECTED_RECRAWL', targets:[page_id]}`, 재적재=`{type:'REINDEX'}`. 둘 다 request_id·reason 필수, 동시 실행 1개 초과 시 409 | | 요청 44 |
| K10 | 적재 승인은 `change-requests(ADD)` → `/{id}/approve` → `jobs(REINDEX)` **3콜 체인**이다. 중간 실패 시 프론트가 자동 재시도하지 않으므로 서버가 `request_id` 멱등키로 중복 승인을 막을 것 | | 요청 45 |
| K11 | 협의 중 행의 '사유' 텍스트(SKIPPED/FAILED 문구)를 프론트가 임시로 지었다. 서버가 `collection_note`를 주면 그 값을 쓴다 | | 요청 98 |
| K12 | 개별 재수집은 확인 모달이 없어 프론트가 고정 사유 `지식베이스 상세에서 개별 재수집`을 보낸다. 이 값이 활동 로그에 남아도 되는지 확정 필요 | | 요청 99 |
| K13 | 단건 조회 경로(`GET /knowledge/pages/{page_id}`)가 생기면 그쪽으로 바꾸는 게 맞다. 지금은 `?tab=targets&q={page_id}`로 1건을 조회해 AD-003 프리필을 만든다 | **FE정** | 요청 100 |
| K14 | 권한 매핑을 목 그대로 따랐다: 미리보기·변경요청 **EDITOR** / 작업 실행 **OPERATOR** / 승인 **ADMIN** | **FE정** | 요청 48 |

### P. 파이프라인 (AD-004)

| # | 계약 | 구분 | 근거 |
|---|---|---|---|
| P1 | 진행 상태 **구독 계약이 없어** `GET /jobs/{id}`를 3초 폴링(`X-Poll: 1`)한다. SSE로 갈지 폴링일지 CM-DF-003 04절에 명시해 달라 — SSE가 생기면 이 부분만 교체하면 된다 | **FE정** | `routes/admin/Pipeline.tsx:59` / 요청 46·50 |
| P2 | `PipelineJob`·`JobStep`에 4필드 추가 요청: `target_summary`(`전체 58페이지` 등 '대상' 열 문자열) · `target_count`(targets가 비는 전체 작업의 대상 건수) · `index_impact`(실패가 인덱스에 미친 영향, **서버 판정값**) · `JobStep.count`(단계별 처리 건수 `1. 수집 58`) | | `routes/admin/pipeline/api.ts:20,37,39` / 요청 49·101·102·103 / §7-4·5 |
| P3 | **신규 3종**: `GET /pipeline/changes` → `{last_checked_at, items[]}` · `POST /pipeline/changes/recheck`(OPERATOR) · `GET /pipeline/estimate?type=FULL_RECRAWL\|REINDEX\|SELECTED_RECRAWL` → `{type, target_count, estimated_minutes}` | **FE정** | 요청 51 |
| P4 | 진행 중 작업 전용 조회(`GET /jobs?status=RUNNING,QUEUED&size=1` 또는 current-job)가 필요. 지금은 '동시 실행 1개 + 최신순 1페이지에 있다'는 가정으로 대체했다 | **FE정** | 요청 104 |
| P5 | 긴급 롤백(`/jobs/{id}/rollback`, ADMIN)은 프론트가 직전에 `POST /reauth`를 보내지만, **서버도 재인증 유효성을 독립 검증**해야 한다. `PUT /ops-policy`도 마찬가지(프론트 판정은 우회 가능) | | 요청 58·110 |

### G. 대화 로그 (AD-005)

| # | 계약 | 구분 | 근거 |
|---|---|---|---|
| G1 | **API 7종 전부 미정이라 목으로 계약을 잡았다.** 스키마 정본은 `routes/admin/logs/api.ts`: `GET /logs?from&to&status&intent&feedback&q&page&size` · `GET /logs/summary`(항상 오늘 기준) · `GET /logs/{request_id}` · `POST /logs/{request_id}/rerun` · `PATCH /logs/{request_id}{triage,reason}` · `POST /evaluations/candidates{source_request_id}` · `POST /logs/exports` | **FE정** | 요청 52 |
| G2 | 권한 경계: 목록·상세 **OPERATOR 이상(VIEWER는 403)**, 후보 등록 EDITOR, 내보내기 ADMIN. 'VIEWER는 집계만'은 화면 숨김이 아니라 **서버 계약**이어야 한다 | | 요청 53·106 |
| G3 | `q`는 반드시 **마스킹된 저장본만** 대상으로 검색. 응답에 원문 복호화 필드를 넣지 말 것(프론트에 진입점을 만들지 않았다) | | 요청 54 |
| G4 | 답변 전문은 `answer_masked_preview` + `answer_masked_full` **두 필드를 상세 응답에 함께** 담을 것('전체 펼치기'는 추가 호출 없는 클라이언트 토글) | | 요청 55 |
| G5 | **검색 후보·단계별 소요는 화면에서 뺐다**(2026-08-04 팀 결정: Langfuse 이관). 상세 응답에 `langfuse: {id, url} \| null`과 `total_latency_ms`만 담을 것. `url`은 **완성된 주소**여야 한다 — 프론트가 Langfuse 호스트를 알 이유가 없고, 조각을 붙이면 배포 환경이 바뀔 때마다 깨진다. `trace_id`는 있는데 URL을 못 만드는 상황이면 `{id, url: null}`로 주면 화면이 ID만 글로 보여준다. 기획서 AD-005 상세 목업의 '검색 상위 5건'·'단계별 소요' 블록은 이 결정으로 폐기(P-10) | **FE정** | 요청 56 / `src/schema.py`(`rag_retrieval_results` 삭제·`rag_runs.trace_id` 존재) |
| G6 | `POST /logs/exports` 본문에 `feedback` 필터 수용 — 화면 결과와 내보낸 결과가 같아야 한다 | | 요청 105 |

### E. 평가 (AD-006)

| # | 계약 | 구분 | 근거 |
|---|---|---|---|
| E1 | `GET /evaluations/runs`의 `metrics`를 숫자 4필드 대신 **`[{label, value}]` 배열**로. 대상별 지표 축이 다르다(RAG=정확도/MRR/생성, 프롬프트=회귀/인용/중대 위반). 반올림(점수 3자리·퍼센트 1자리)까지 서버가 끝낸 문자열로 | **FE정** | 요청 60·108 |
| E2 | `metrics`에 **생성 성공률**(`generation_success_rate`)이 없다. 기획서 핵심 결과 원문은 `정확도 0.922 · MRR 0.806 · 생성 100%`인데 현 필드로는 못 그린다(환각률로 대체하지 않았다 — 의미가 다름) | | 요청 59 |
| E3 | `runs`에 `target`·`source`·`page`·`size`를 **서버가 처리**하고 `total`은 필터 적용 후 전체 건수. `follow_up`(`→ 11:40 반영됨`)·`testset_version`·`improved_by_composition` 필드 추가 | **FE정** | `routes/admin/evaluation/api.ts:185` / 요청 61·108 |
| E4 | 게이트 판정 상세를 별도 리소스(`GET /evaluations/runs/{run_id}/gate`)로 뒀다. **목표값(0.92↑/0.80↑/99.5%↑/10초↓/30of30)은 반드시 서버가 내려줘야 한다** — 프론트 상수로 박으면 '관리자 화면에서 기준을 낮추는 우회'를 막는 설계가 무너진다 | 기획서 CM-DF-004 05절 | 요청 62 |
| E5 | 프롬프트 초안 실행은 게이트 축이 다른데(회귀/인용/중대 위반) 기획서에 미달 모달 목업이 없다. **축이 다른 실행의 게이트 상세 계약**이 필요 | | 요청 112 |
| E6 | 문항 편집 계약 전체가 신규: `GET /items`(Page 봉투) · `POST /items/validate`(**필드별 오류 `{field, message}[]`** — 걸린 필드만 붉게 칠하려면 field 필수) · `POST /apply`(`{adds, edits, excludes[{item_id, reason}]}` + reason 필수 → `{testset_version, rerun_id}`) | **FE정** | 요청 63 |
| E7 | 반영은 **버전 증가 1회 + 운영 재측정 1회가 서버 한 트랜잭션**에서 끝나야 한다(여러 건 편집해도 재측정 1회) | | 요청 63 |
| E8 | **신규**: `GET /evaluations/corpus?q=` (기대 출처 선택용). 이게 없으면 문항 추가 폼 자체가 구현 불가. 응답은 `{items:[{doc_id, title}]}`로 가정했다 | **FE정** | 요청 64 |
| E9 | '출처' 필터 옵션(현재 4종: 수동 실행 / 프롬프트 게시 게이트 / 파이프라인 후속 / RAG 파라미터 평가)을 고정 코드값 사전으로 CM-DF-002에 넣거나 옵션 조회 엔드포인트를 줄 것 | | 요청 109 |
| E10 | `run.gate.passed`와 기준별 판정이 어긋나지 않게 **서버가 함께 계산**해 내려줄 것(현 목 데이터는 목록 '통과'인데 게이트 상세는 '미달'로 갈린다 — 목 데이터 정합성 문제) | | 요청 69 |

### R. RAG 파라미터 (AD-007)

| # | 계약 | 구분 | 근거 |
|---|---|---|---|
| R1 | **신규 6종**: `GET /rag-params`(params 메타 + current + draft + gate) · `POST /evaluate` · `POST /ab-search` · `POST /apply`(reason 필수) · `GET /history` · `POST /history/{id}/rollback`. 특히 **파라미터 메타(현행값·반영 시점·min/max/step·옵션·슬라이더 눈금)를 서버가 내려주는 형태**로 잡았다 — CM-DF-003 05절 표가 바뀌어도 프론트 재배포가 필요 없고 '목업 숫자 하드코딩 금지'도 지켜진다 | **FE정** | 요청 65 |
| R2 | `POST /rag-params/evaluate` 응답에 `draft_signature`(평가한 초안의 지문). '평가 이후 초안을 수정하면 평가 무효화'를 판정하려면 서버가 무엇을 평가했는지 알려줘야 한다 | | 요청 66 |
| R3 | `POST /rag-params/apply`는 게이트 미통과 시 **409**로 막을 것(프론트도 막지만 서버가 최종 판정). 실패 응답에 **현재 적용값 전문**을 실어 주면 '실패 시 이전 버전 유지'를 화면이 그대로 다시 그린다 | | 요청 67 |
| R4 | 쓰기 권한을 전부 **EDITOR**로 가정했다(AD-007에 승인 분리가 없다는 기획서 0.4절 근거). ADMIN 전용이어야 하면 알려 달라 — 화면은 숨김만 바꾸면 되고 403은 이미 처리 중이다 | **FE정** | 요청 68 |

### M. 프롬프트·가드레일 (AD-008)

| # | 계약 | 구분 | 근거 |
|---|---|---|---|
| M1 | **신규 11종**: `GET/PUT /prompt/draft` · `POST /prompt/draft/discard` · `POST /prompt/evaluate` · `GET /prompt/versions` · `POST /prompt/versions/{v}/rollback` · `.../emergency-rollback` · `POST /prompt/publish` · `GET/POST /prompt/publish-requests` · `.../{id}/approve\|reject\|cancel` · `POST /guardrails/masking/validate`. 스키마 정본은 `routes/admin/settings/promptops/api.ts` | **FE정** | 요청 70 |
| M2 | 프롬프트 초안은 **서버가 상태를 갖는다**: PUT 응답에 `change_count`·`dirty(prompt/fewshot/guardrail)`·`char_count` 포함, 초안이 바뀌면 `evaluation`을 null로 무효화(프론트는 diff를 계산하지 않는다) | | 요청 72 |
| M3 | 가드레일(금칙어·마스킹)은 프롬프트 초안 객체 안에 함께 실려 온다. 별도 `GET/PUT /guardrails`를 만들 거면 초안 `change_count`와의 동기화 규칙을 먼저 정할 것 | | 요청 73 |
| M4 | 게시 응답은 `{version, smoke:{passed,total}}` — Smoke 30문항 결과를 함께 줄 것(토스트에 그대로 쓴다). 실패 시 현행 유지 + user_message | | 요청 74 |
| M5 | 긴급 롤백은 `POST /reauth`를 **별도 호출로 먼저** 끝낸 뒤 본 요청. 본 요청 바디에 password를 싣지 않는다 | | 요청 75 |
| M6 | 마스킹 검증 응답 `{passed, sample_count, message}` — 정규식 문법 오류·과대 매칭을 **서버가 판정**하고 문구를 준다. 미통과 규칙이 섞인 PUT은 400으로 막을 것 | | 요청 76 |
| M7 | 게시·승인에 비밀번호 재확인이 필요한지 확정 필요. CM-DF-001 2.3 고위험 3종(전체 캐시 비우기·권한 변경·롤백)에 없어 UI에서 재인증 입력을 뺐다 | | 요청 111 |

### O. 운영 정책 (AD-009)

| # | 계약 | 구분 | 근거 |
|---|---|---|---|
| O1 | **신규 6종**: `GET/PUT /ops-policy` · `GET /cache/stats` · `POST /cache/purge(scope=query\|all)` · `GET /blocks` · `POST /blocks/{id}/release` · `POST /suggested-questions/validate`(금칙어 검사) | **FE정** | 요청 71 |
| O2 | 추천 질문은 기존 `PUT /suggested-questions`(전체 교체)를 쓴다. reason이 필수라 활성 토글·순서 변경에도 자동 사유가 붙는다 — 활동 로그 노이즈가 문제면 PATCH 단위 API를 신설할 것 | | 요청 77 |
| O3 | `SuggestedQuestion.click_count`를 화면은 '최근 7일 클릭'으로 렌더한다. **서버가 7일 윈도우 집계를 주도록 필드명을 맞추거나 별도 필드 필요.** 애초에 추천 칩 클릭 수집 경로 자체가 계약에 없다 | | 요청 78 |
| O4 | 차단 목록은 `expires_at`(만료 시각) 필수. 프론트가 만료된 행의 [해제]를 비활성화하고 남은 시간을 확인 모달에 표시한다 | | 요청 79 |
| O5 | `PUT /ops-policy`는 **부분 패치**(변경된 필드만)로 보내고 응답에 새 `version`을 담을 것. `burst_per_10s`는 읽기 전용 | | 요청 80 |

---

## 7. 프론트가 못 만든 것

계약이 없어서 남긴 구멍이다. **화면 버그가 아니라 스키마 부재다** — 해당 계약이 생기면 붙일 자리에 주석으로 표시해 뒀다.

| # | 못 만든 것 | 막힌 이유 | 자리 |
|---|---|---|---|
| 1 | **복합 질문(Type 6) 하위 답변 렌더** — 하위 질문 제목 블록, 하위별 독립 출처 | `ChatResponse`가 `answer: string` + 평면 `sources[]`뿐이라 출처를 하위에 매핑할 수 없다. 제목을 `answer` 안 `**…**`로 받는 것은 "마크다운 파싱 불필요" 규칙과 충돌해 금지. **§6 B7이 생기면 `SubAnswerBlock`을 붙인다** | `components/chat/AnswerMessage.tsx:8-14` (검증 D001) |
| 2 | **챗봇 아바타 3단 폴백**(등록 이미지 → 기본 아이콘 → 이모지) 중 이모지만 있다 | 이미지 소스가 아예 없다 — 정적 에셋도, API 필드도 없다(§6 B16) | `components/chat/Bubble.tsx:18-21` (D067) |
| 3 | **역할 되묻기 후 재검색** — 역할 버튼은 라벨 문자열만 보낸다 | `ChatRequest`에 `role`도 원질문 자리도 없다. 서버가 세션 문맥으로 원질문을 복원하지 못하면 재검색이 성립하지 않는다(§6 B9) | `routes/chat/ChatPage.tsx:375` (D070) |
| 4 | **파이프라인 단계별 처리 건수** — `1. 수집 58` 대신 단계 이름만 나온다. 실패 상세 '처리 실적'도 숫자 없이 나온다 | `JobStep.count` 미제공(§6 P2) | `routes/admin/pipeline/api.ts:20` (D044·D046) |
| 5 | **실패의 '인덱스 영향'** — '반영' 단계 이전 실패에만 정본 문구를 쓰고 그 외에는 '확인할 수 없음'으로 둔다 | 서버 판정값이어야 하는데 `index_impact`가 없다(§6 P2). 화면이 단언하지 않도록 일부러 비워 뒀다 | `routes/admin/pipeline/api.ts:39` (D045) |
| 6 | **접속 IP 마스킹을 프론트가 하고 있다** | 서버가 원문 IP를 준다. 서버 마스킹이 시작되면 프론트 `maskIp`는 통과만 하도록 손봐야 한다(§6 L5) | `routes/admin/settings/activity/EventDetail.tsx:62` |
| 7 | **사용자 재시도 카운터가 새로고침 시 리셋된다** | 질문 텍스트 기준 클라이언트 로컬 상태다. 서버가 카운트를 내려주면 그 값을 쓴다(§6 B14) | `routes/chat/ChatPage.tsx:38` |
| 8 | **대시보드 상시 지표 배너를 아예 없앴다** | 임계치가 정해지지 않았고 2종은 원천도 없다. P3에서 기준이 서면 다시 붙인다(§6 D3) | 요청 29 |

검증에서 나온 결함 104건(`_defects.json`) 중 대부분은 수정했고, 위 8건이 **계약 부재로 보류된 것**이다.

---

## 8. 주의

- **커밋 금지**: `.env`, HCX/NCP·OpenAI API Key. `.jsonl` LF 고정, dense 임베딩 캐시 규칙, "HTML→텍스트에 LLM 미사용" 같은 리포 불변식은 여기서 되풀이하지 않는다.
- ⚠ **`.gitignore`의 Python 템플릿 함정.** 루트 `.gitignore`의 `lib/`·`build/`·`dist/`·`var/`는 앵커가 없어 **하위 경로까지 전부** 걸린다 — `web/src/lib/`(API 클라이언트·enum·상수)가 통째로 무시돼 커밋에서 빠져 있었다. 2026-08-03에 `/lib/`처럼 루트 앵커로 고쳤다(setuptools가 만드는 건 루트의 그 디렉터리들이다). **앞으로 루트 `.gitignore`에 디렉터리 규칙을 추가할 때는 반드시 `/`로 시작할 것.**
- ~~`web/`은 아직 git에 안 올라가 있다~~ → **2026-08-05 커밋 완료.** 위 `.gitignore` 함정은 그 커밋에서 실제로 문제가 됐던 것이라 기록을 남겨 둔다.
- `web/public/mockServiceWorker.js`는 `pnpm exec msw init public/`가 생성한 파일이다. 손대지 말 것.
- ~~`web/README.md`는 Vite 템플릿 원문이라 이 프로젝트 내용이 아니다~~ → **작성 당시 사실이었으나 이후 예솜24 프론트 실행 안내로 다시 쓰였다.** 지금 프론트 문서는 셋이다 — 이 파일(백엔드 핸드오프) · [`web/README.md`](../web/README.md)(실행·목 시나리오) · [`web/src/mocks/README.md`](../web/src/mocks/README.md)(API 계약 정본).
- 기획서 문구·수치를 인용할 때는 코드/데이터로 먼저 검증한다 — 산문 문서는 stale일 수 있다. 이 문서의 수치도 2026-08-03 기준이다.
