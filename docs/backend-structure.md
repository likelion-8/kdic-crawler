# 백엔드 구조 (FastAPI) — 개선안

팀 초안(`api/` 계층 분리, routers/schemas/services/db/middleware)의 **큰 방향은 맞다.**
아래는 그 위에서 **코드·프론트 실물과 대조해 고친 것**만 적는다. 근거는 전부 `파일:줄`로 단다.

계약의 정본 순서는 이미 정해져 있다 — 기획서(CM-DF-003 04절) → `web/src/lib/api/types.ts` →
`web/src/lib/codes.ts` → `web/src/mocks/`. 이 문서는 그 계약을 **어느 파일에 담을지**만 다룬다.

---

## 0. 초안에서 바꾼 것 — 요약

| # | 초안 | 개선안 | 이유 |
|---|---|---|---|
| 1 | 라우트 목록을 기획서 표에서 뽑음 (`/api/admin/pages`, `/api/admin/eval-sets`, `/api/conversation` …) | **프론트가 실제로 부르는 경로로 교체** (`/api/admin/knowledge/pages`, `/api/admin/evaluations/items`, `/api/sessions/{id}` …) | 프론트 17화면이 이미 그 경로로 fetch한다. 초안 경로로 만들면 전 화면 404 |
| 2 | 라우터를 화면(AD-00x)으로 분할 | **프론트 핸드오프의 도메인 코드(A·B·D·E·G·K·L·M·O·P·R)로 분할** | 같은 도메인이 여러 화면에 걸쳐 있다. 핸드오프·목·Swagger 태그가 한 어휘를 쓰게 됨 |
| 3 | `services/` 6개 (라우터마다 1개) | **`rag/` 3파일 + `jobs/` 2파일만.** 나머지 라우터는 서비스 없이 직접 | 어댑터가 실제로 필요한 건 RAG·잡 두 곳뿐. 나머지는 "호출만 하는 층"이라 보일러플레이트 |
| 4 | `api/db/models.py`에 13테이블 (그런데 4절은 "정본은 `src/schema.py`"라고 씀 — 모순) | **`src/schema.py` 그대로 두고 `src/schema_admin.py` 한 파일 추가** | DB 정의가 두 군데로 갈리면 팀 공유 Supabase가 어긋난다. 같은 `MetaData`를 써야 FK도 걸린다 |
| 5 | (없음) | **`api/__init__.py` sys.path 부트스트랩** | `from src.pipeline import ...`는 그냥 터진다 (§1-1) |
| 6 | (없음) | **프로세스 모델 절** — 워밍업·워커 수·`def` vs `async def` | bge-m3 2GB·CPU 싱글턴이다. 이걸 모르면 첫 배포에서 바로 막힌다 (§6) |
| 7 | `alembic/` 선반영 | 일단 **없이 간다.** 트리거 조건만 정해둠 | §5 |
| 8 | (없음) | **함정 28건 표** (§3 끝) | 목이 계약과 어긋나는 곳이 있다. 목만 보고 만들면 틀린다 |

> **2026-08-05 갱신** — 기획서 수정 151건을 확정·반영하면서 계약이 몇 곳 바뀌었다. 이 문서에 반영된 것 :
> 함정 **#20**(`answer_request_id` 분리) · **#25**(`clarification.options[]`) · **#26**(`sub_answers[]` 모양) ·
> **#27**(`reauth` 응답) · **#28**(재인증 대상 3종에 게시 없음) · §1-2 (d) · §3 `/api/ready` 삭제 · §5.
---

## 1. 🔴 구조보다 먼저 — 코드를 안 고치면 `api/`가 아예 안 뜬다

> 📌 **2026-08-07 현황 — 이 절의 3건은 모두 처리됐다.** 아래 진단·처방은 작성 당시
> (2026-08-05, `api/`가 없던 시점) 기준이며, 왜 그렇게 해야 했는지의 근거로 남겨 둔다.
>
> | | 처방 | 실제 |
> |---|---|---|
> | 1-1 | `api/__init__.py`에서 `src/`를 `sys.path`에 올린다 | ✅ **권고안 그대로.** `api/__init__.py`가 (b)안을 택한 이유까지 적어 두고 있다 |
> | 1-2 | `_answer_one()`이 dict를 반환하도록 `pipeline.py`를 고친다 | ⚠️ **다른 방식으로 대체됐다.** `pipeline.py`는 문자열 반환 그대로 두고(Streamlit·CLI가 계속 쓴다), `api/rag/answer.py`가 `query_decomposer`·`query_classifier`·`retrieval`·`candidate_ranking`·`citation`·`civil_petition`·`prompt_builder`·`source_check`를 **직접 조립**해 구조화 응답을 만든다. `rag_answer_structured()`는 끝내 만들지 않았다 — 아래 (a)~(d) 표는 그래서 `pipeline.py`가 아니라 `api/rag/answer.py`가 지켜야 할 항목으로 읽어야 한다 |
> | 1-3 | `llm_client`에 `.stream()` 계열 추가 | ✅ **완료.** `call_hyperclova()`(`.invoke()`)와 별도로 스트리밍 제너레이터가 있고 `api/rag/sse.py`가 이를 소비한다 |
>
> ⚠️ 그리고 **SSE 이벤트는 4종으로 줄었다** — `accepted → answer_delta* → done | error`.
> `sources`·`attachments` 이벤트는 2026-08-05에 폐지됐고 출처는 `done`에 실린다
> (`api/rag/sse.py`, `web/src/mocks/README.md` §3).

초안 4절이 "기존 `src/` 기능을 불러 쓴다"고 전제하는데, **작성 당시 상태로는 import가 안 됐다.**
구조를 정하는 것과 별개로 아래 3건이 선행 작업이었다.

### 1-1. `src/` 모듈은 평평하게 임포트한다 — `from src.pipeline import ...`는 터진다

`pipeline.py:10-23`이 `from query_decomposer import ...`, `from citation import ...` 식으로
**형제 모듈을 평평하게** 임포트한다. 그래서 리포 루트에서:

```
$ python3 -c "from src.pipeline import rag_answer"
ModuleNotFoundError: No module named 'query_decomposer'   # ← pipeline.py:10에서 죽는다
```

`import src` 자체는 된다(`__init__.py`가 없어도 PEP 420 네임스페이스 패키지라서). **문제는 패키지
여부가 아니라 안쪽의 평평한 임포트다** — `src/`가 `sys.path`에 없으면 `pipeline`을 실행하는 순간 터진다.

**고치는 법 — `src/schema.py:30-33`이 이미 쓰는 방식 그대로, 한 곳에서만.**

```python
# api/__init__.py  — 전부
"""`api` 패키지를 임포트하면 src/를 sys.path에 올린다.

src/ 모듈끼리 `from citation import ...`처럼 평평하게 임포트하므로, src/가 sys.path에
없으면 pipeline 하나 부르는 순간 터진다. src/schema.py:30-33이 같은 방식을 이미 쓴다.
src/crawler는 retrieval._build_engines()가 실행 시점에 __file__ 기준으로 직접 올리므로
(retrieval.py:12, 317-318) 여기서는 src/만 올리면 되고 cwd와도 무관하다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
```

그리고 **`api/` 안에서는 평평하게 임포트한다** — `from pipeline import rag_answer`,
`from db import get_session`. `from src.pipeline import ...`가 아니다.

> `src/__init__.py`를 **추가하지 마라.** 패키지로 만들어도 내부 평평 임포트는 그대로 깨지는데,
> `import src.pipeline`이 되는 것처럼 보여서 더 헷갈린다. 16개 모듈 + `src/crawler/` 30개
> 스크립트 + `tests/`를 전부 상대 임포트로 바꾸는 건 이 프로젝트가 치를 값이 아니다.

### 1-2. `rag_answer_structured()`는 없다

초안 본문이 `src/pipeline.py의 rag_answer_structured()`를 부른다고 썼는데 **그 함수는 리포에 없다.**
있는 건 `rag_answer(query) -> str`(`pipeline.py:136`)뿐이고, 출처·서류 링크가 이미
**문자열 안에 이어붙여진 뒤**다(`prompt_builder.assemble_*_answer` → `_render_list`).

프론트 `ChatResponse`는 `answer` / `sources[]` / `attachments[]` / `out_of_scope`가 **따로**여야 한다
(`web/src/lib/api/types.ts:55-70`).

**다행히 재료는 이미 dict다.** `citation.format_all_citations()`(citation.py:44)이 내놓는
`{page_id, breadcrumb, title, url}`은 프론트 `Source` 타입과 **필드명까지 같다.**
`civil_petition.build_civil_petition_answer()`(civil_petition.py:92)의 `documents`/`links`가
`Attachment`가 된다.

필드 단위 대응표는 `web/src/mocks/README.md` §5에 있다. 다만 **"마지막 한 줄만 빼면 된다"는 말은
과장이다** — 실제로는 4곳이다:

```python
# src/pipeline.py — _answer_one()을 dict 반환으로
def _answer_one(query, timings) -> dict:
    ...
    body, used_source = _resolve_used_source(llm_text, recheck)   # (b)
    return {"answer": body, "out_of_scope": not used_source,
            "sources": citations, "attachments": ..., "intent": intent}
```

| | 할 일 | 왜 |
|---|---|---|
| (a) | `_answer_one()`(pipeline.py:55-108)이 dict를 반환 | 지금은 조립된 문자열 |
| (b) | `_resolve_used_source()`를 **직접** 호출 | `assemble_*_answer()`가 그 불리언을 삼킨다(prompt_builder.py:186, 197). `out_of_scope`를 못 받는다 |
| (c) | 🔴 `civil_petition` 갈래에서도 `format_all_citations()`를 호출 | 지금 그 갈래는 citations를 **아예 계산하지 않는다**(pipeline.py:72-77). 그대로 두면 민원성 답변의 `sources[]`가 항상 빈 배열이다 |
| (d) | 복합 질문은 **`sub_answers:[{title, answer, sources[], attachments[]}]`**로. 출처는 **하위 블록마다 각각** 붙이고 **하위 간 중복 제거는 금지**. `sub_answers`가 있으면 최상위 `sources`는 빈 배열 | 지금은 `"\n\n".join(f"**{q}**\n{a}")`로 하나의 문자열이 된다(pipeline.py:130). 프론트는 이 마크다운을 **받지 않겠다**고 못 박았다(핸드오프 B7). 중복 제거는 `pipeline.py:55-61`이 *"같은 문서가 여러 하위 답변의 근거면 각각에 보이는 게 맞다 — 다시 도입하지 말 것"*이라 명시 (A-02 확정 2026-08-05) |

⚠ `_render_list`·`_format_source_line`은 **지우지 마라** — `python3 src/pipeline.py` CLI가 계속 쓴다.

### 1-3. 스트리밍이 없다

`llm_client.call_hyperclova`(llm_client.py:42-46)는 `ChatClovaX.invoke()` — 단발 호출이다.
SSE `answer_delta`를 진짜 토큰 단위로 흘리려면 `.stream()` 계열로 바꿔야 한다.
안 바꾸면 완성된 답변을 서버가 쪼개 보내는 흉내만 가능하다(목이 하는 방식과 같음).

그리고 **바꿀 때 반드시 지킬 것 — 마커 누출.** `[SOURCE_USED]`/`[NO_SOURCE]`는 LLM 출력의 첫 줄로
지시돼 있고(prompt_builder.py:32) `_strip_no_source_marker`가 **사후에** 뗀다(prompt_builder.py:141).
그냥 흘리면 마커가 첫 델타로 사용자 화면에 찍힌다(핸드오프 B1 — "프론트는 버퍼링하지 않는다").

"첫 개행까지만 버퍼링"으로는 **부족하다.** `_MARKER_RE`(prompt_builder.py:137-138)는 볼드 감싸기·
내부 공백·콜론·후행 공백까지 받아주고 `.strip()`으로 선행 공백도 흡수한다 — 응답이 빈 줄로 시작하면
개행 게이트를 통과해 마커가 새어나간다. **첫 글자부터 `_MARKER_RE`가 매치되거나 확정적으로 불일치할
때까지 버퍼링**하고 그 뒤에 흘려라.

그리고 `USE_QUERY_DECOMPOSITION=True`(pipeline.py:43)라 **마커는 응답당 1개가 아니라 하위 질문당
1개**다(pipeline.py:128-129). 프론트의 "첫 줄 선두 1회 제거" 방어로는 두 번째 이후를 못 잡는다 —
하위 답변마다 버퍼링해야 한다.

---

## 2. 폴더 구조

```
kdic-crawler/
├── src/                          # 기존 그대로. 손대는 곳은 아래 2개뿐
│   ├── pipeline.py               #  └ §1-2: _answer_one() dict 반환
│   ├── llm_client.py             #  └ §1-3: .stream() 추가
│   ├── schema.py                 # RAG 코어 5테이블 — 정본. 손대지 않는다
│   └── schema_admin.py           # ★ 신규 — 관리자·운영 테이블 (§5)
│
├── api/
│   ├── __init__.py               # ★ sys.path 부트스트랩 (§1-1). 이 파일이 전부다
│   ├── main.py                   # 앱 조립 · lifespan 워밍업 · CORS · 예외 핸들러 등록
│   ├── config.py                 # Settings — web/src/lib/constants.ts와 값이 같아야 한다
│   ├── deps.py                   # get_db · current_admin · require_role · require_reason · require_reauth
│   ├── errors.py                 # ★ 도메인 예외 → ApiError 정규화. 문구가 사는 유일한 곳
│   ├── pagination.py             # ★ Page[T] 봉투 + page/size/sort 파싱 (목록 엔드포인트가 20개 넘는다)
│   ├── middleware.py             # ★ 폴더 아님 — request_id · X-Poll · rate limit 3개뿐
│   │
│   ├── routers/                  # 프론트 도메인 코드 = Swagger 태그 (§3)
│   │   ├── chat.py               # B   POST /api/chat (SSE)
│   │   ├── public.py             # B'  health · suggestions · sessions/{id} · feedback
│   │   ├── auth.py               # A   login·session·reauth·password·accounts·roles·me
│   │   ├── knowledge.py          # K   knowledge/* · previews · change-requests
│   │   ├── pipeline.py           # P   jobs/* · pipeline/changes · pipeline/estimate
│   │   ├── logs.py               # G   logs/* (대화 로그)
│   │   ├── dashboard.py          # D   dashboard/*
│   │   ├── evaluations.py        # E   evaluations/*
│   │   ├── rag_params.py         # R   rag-params/*
│   │   ├── promptops.py          # M   prompt/* · guardrails/*
│   │   ├── ops.py                # O   ops-policy · cache · blocks · suggested-questions
│   │   └── activity.py           # L   activity/* · drafts/{screen}
│   │
│   ├── schemas/                  # Pydantic. types.ts·codes.ts·routes/admin/*/api.ts를 옮긴 것
│   │   ├── common.py             # ApiError · Page[T] · codes.ts enum 전량
│   │   ├── chat.py
│   │   └── <라우터명>.py          # 라우터와 1:1
│   │
│   ├── rag/                      # ★ services/ 대신. src/와 API 사이 어댑터가 진짜 필요한 곳
│   │   ├── engine.py             # 워밍업 · 싱글턴 잠금 · 스레드 오프로드 (§6)
│   │   ├── answer.py             # pipeline dict → ChatResponse
│   │   └── sse.py                # 마커 제거 · 이벤트 순서 · 무응답 처리
│   │
│   └── jobs/                     # ★ 초안에 없던 것 — 잡은 HTTP 요청보다 오래 산다
│       ├── runner.py             # 동시 1개 강제 · 단계 진행 기록 · 취소/재시도
│       └── steps.py              # src/crawler/*.py · embed_corpus.py 호출
│
└── tests/                        # 계약 테스트는 새로 만들지 않는다 — §8
```

**`api/db/` 폴더는 없앴다.** 초안의 `session.py`는 `src/db.py:44 get_session`을 감싸는 3줄이라
`deps.py`에 두면 되고, `models.py`는 `src/schema.py`와 정본이 갈려 위험하다(§5).

```python
# api/deps.py — DB 의존성은 이게 전부다
from db import get_session  # src/db.py:44 — @contextmanager라 Depends에 직접 못 넣는다

def get_db():
    with get_session() as session:
        yield session
```

---

## 3. 라우터 분할 — 프론트가 부르는 경로가 정본

프론트는 **91개 엔드포인트**(관리자 85 · 공개 6)를 이미 부르고 있다.
`web/src/mocks/handlers/`가 그 전량을 응답한다 — **응답 모양이 필요하면 기획서보다 여기가 빠르다.**

### 초안과 실제가 갈린 곳 (이대로 만들면 화면이 죽는다)

| 초안 경로 | 프론트가 실제로 부르는 경로 |
|---|---|
| `GET /api/admin/pages` | `GET /api/admin/knowledge/pages?tab=indexed\|targets&q=&business=&state=&sort=&page=&size=` |
| `GET /api/admin/pages/{id}/chunks` | `GET /api/admin/knowledge/chunks?page_id=` |
| `GET/POST /api/admin/crawl-targets` | **없음.** 수집 대상은 `knowledge/pages?tab=targets`, 신규는 `POST /api/admin/previews` → `POST /api/admin/change-requests` |
| `DELETE /api/admin/crawl-targets/{id}` | **없음.** 삭제도 `POST /api/admin/change-requests {action:'DELETE'}` (핸드오프 K7) |
| `GET/POST/PATCH /api/admin/eval-sets` | `GET /api/admin/evaluations/items` · `POST /api/admin/evaluations/items/validate` · `POST /api/admin/evaluations/apply` |
| `POST /api/admin/eval-runs` | `GET /api/admin/evaluations/runs?target&source&page&size&sort` · `GET /api/admin/evaluations/runs/{run_id}/gate` — `target` **3값**(`운영 설정`·`RAG 초안`·`프롬프트 초안`) · `source` **4값**(`수동 실행`·`프롬프트 게시 게이트`·`파이프라인 후속`·`RAG 파라미터 평가`). ⚠ 2026-08-05 전에는 같은 경로에 목이 2벌이라 2값 어휘가 섞여 있었다 — 죽은 쪽을 지웠으니 이제 목이 곧 계약이다 (A-10·A-11 확정) |
| `GET /api/admin/conversations` | `GET /api/admin/logs` (+ `/summary` · `/{request_id}` · `/{request_id}/rerun` · `/exports`) |
| `GET /api/admin/activity-logs` | `GET /api/admin/activity/events` (+ `/overview` · `/risky-today` · `/exports`) |
| `GET/PATCH /api/admin/settings/rag` | `GET /api/admin/rag-params` (+ `/evaluate` · `/ab-search` · `/apply` · `/history` · `/history/{id}/rollback`) |
| `.../settings/prompt` · `.../guardrail` | `GET/PUT /api/admin/prompt/draft` · `/prompt/versions` · `/prompt/publish` · `/prompt/versions/{v}/rollback` · `/emergency-rollback` · `POST /api/admin/guardrails/masking/validate` |
| `POST /api/admin/settings/cache/purge` | `POST /api/admin/cache/purge` (+ `GET /api/admin/cache/stats`) |
| `GET /api/conversation` | `GET /api/sessions/{session_id}` — 24h 초과·없는 세션은 **404** |

### 초안에 아예 없던 것

`GET /api/suggestions` · `GET/PUT /api/admin/suggested-questions` (+`/validate`) ·
`GET /api/admin/me/permissions` · `GET /api/admin/roles` · `GET /api/admin/security/summary` ·
`GET /api/admin/login-failures` · `GET /api/admin/blocks` + `POST /api/admin/blocks/{id}/release` ·
`GET/PUT /api/admin/ops-policy` · `GET /api/admin/dashboard/summary|trend|resources` ·
`GET /api/admin/pipeline/changes` + `/recheck` + `/estimate` ·
`POST /api/admin/jobs/{id}/rollback`(긴급 롤백, ADMIN) · `PUT /api/admin/drafts/{screen}`(10초 자동저장) ·
`POST /api/admin/change-requests/{id}/approve|reject` · `POST /api/admin/previews/{id}/reject`

> 도메인별 상세 계약(필드·상태코드·호출 순서)은 `docs/frontend-handoff.md` §6과
> `web/src/routes/admin/*/api.ts`가 정본이다. 여기서 되풀이하지 않는다.

### 🔴 목만 보고 만들면 틀리는 것 — 실제 프론트 코드를 읽고 뽑은 함정

라우터를 나누기 전에 이건 알고 시작해야 한다. 전부 `web/src` 실코드 근거다.

| # | 함정 | 근거 |
|---|---|---|
| 1 | **`POST /api/admin/reauth`의 '비밀번호 틀림'을 401로 주지 마라.** 프론트는 상태코드 401을 무조건 세션 만료로 해석해 `expireSession()`하고 로그인으로 튕긴다 — **재확인 모달에서 오타 한 번에 로그아웃된다.** 403(또는 422)으로 내려라. ⚠ 목이 401을 주고 있으니 목을 따라 하면 안 된다 | `lib/api/client.ts:107` / 목 `handlers/admin.ts:162` |
| 2 | **`POST /api/chat`만 `request_id`가 없다.** 이 요청 하나만 공통 래퍼를 안 타고 raw fetch라 본문이 정확히 `{message, session_id?}`다. 여기서 멱등키를 필수로 걸면 프론트가 400을 맞는다 | `lib/api/chat.ts:70` · `types.ts:72-75` |
| 3 | **SSE 30초 공백 = 폴백이 아니라 중단.** 프론트는 스트림을 abort하고 `LLM_TIMEOUT` 오류 말풍선으로 바꾼다. 긴 생성 구간에도 `answer_delta`가 계속 나가야 한다. SSE 주석형 하트비트(`: ping`)는 **타이머를 갱신하지 못한다** — 파서가 `data:` 있는 프레임만 이벤트로 친다 | `routes/chat/ChatPage.tsx:316-329` · `lib/api/chat.ts:26-41` |
| 4 | **`done` 페이로드가 확정본이다.** 프론트는 `sources`/`attachments` 이벤트를 상태로 쓰지 않고 `done`으로 말풍선을 통째로 다시 만든다. `done`에 빠진 필드는 화면에서 사라지고, 흘려보낸 `answer`도 `done.answer`로 덮인다 | `routes/chat/ChatPage.tsx:311-312` |
| 5 | **`GET /api/admin/session`은 시각이 아니라 '남은 초'**(`absolute_expires_in_s`·`idle_expires_in_s`·`reauth_valid_until_s`). ISO 타임스탬프로 바꾸면 세션 3타이머가 통째로 깨진다. 그리고 이 호출은 **항상 `X-Poll`**이라 유휴 타이머를 갱신하면 안 된다(갱신하면 유휴 만료가 영원히 안 온다) | `app/session.ts:28-34, 76-84, 103` |
| 6 | **`POST /evaluations/items/validate`는 검증 실패도 200.** 실패는 본문 `{ok:false, errors:[{field,message}]}`로 표현한다. 422로 주면 필드 하이라이트가 안 된다. `field` 값은 `item_id`·`question`·`expected_source` 셋뿐 | `routes/admin/evaluation/ItemEditor.tsx:51-54` |
| 7 | **`GET /evaluations/corpus`만 `Page<T>` 봉투가 아니다** — `{items:[...]}`뿐 | `routes/admin/evaluation/api.ts:163` |
| 8 | **잡 상태코드**: `POST /jobs`·`retry`·`rollback`은 **202 + `PipelineJob` 본문**, `cancel`만 200. 204·빈 본문 불가. 동시 실행 초과는 **409 + `retryable:false`**(true면 [다시 시도]가 떠서 계속 409를 맞는다) | 목 `handlers/admin.ts:336-337, 350, 373, 397, 420` |
| 9 | **잡 목록 정렬이 기능 계약이다.** 프론트는 '진행 중 작업은 항상 1페이지'라고 가정해 `page=1`에서만 active job을 찾고, 긴급 롤백 버튼도 1페이지 첫 SUCCESS 행에만 붙인다. 정렬이 깨지면 폴링·롤백이 조용히 오작동한다 | `routes/admin/Pipeline.tsx:120-125, 203` |
| 10 | **`GET /logs/summary`는 필터를 반영하지 않는다.** 항상 KST '오늘' 기준 집계다. 목록 필터를 재사용하면 라벨('오늘 대화')과 값이 어긋난다 | `routes/admin/ConversationLogs.tsx:131-132` |
| 11 | **VIEWER 차단은 화면 숨김이 아니라 서버 계약.** `GET /api/admin/logs`·`/{id}`는 VIEWER에게 **403**이어야 하고 `/logs/summary`는 허용이다 | `ConversationLogs.tsx:101, 128, 137` |
| 12 | **`POST /evaluations/candidates` 본문은 `{source_request_id, request_id}`.** 대상을 가리키는 건 `source_request_id`인데 **목 핸들러가 그 값을 읽지도 않는다** — 목만 보고 만들면 대상이 유실된다 | `routes/admin/logs/api.ts:201-206` |
| 13 | **같은 경로에 목이 두 벌 있고 `extra/`가 이긴다.** `knowledge/pages`·`previews`는 `mocks/handlers/extra/ad-knowledge.ts` 판본이 계약이다(`admin.ts` 판본엔 `owner`·`split_rule`·`collection_status`가 빠져 있다) | `mocks/browser.ts:23-32` |
| 14 | **`state` 파라미터 하나가 두 어휘를 받는다** — 한글 3상태(`최신`·`변경 감지`·`적용 대기`)와 `index_status` 코드를 OR로 매칭. `tab` 기본값은 `indexed`(배지 건수 질의가 `tab`을 아예 안 보낸다) | `KnowledgePages.tsx:74-82, 223` |
| 15 | **`from`/`to`는 KST 날짜(`YYYY-MM-DD`) 양끝 포함.** `occurred_at`이 `+09:00` ISO여야 날짜 경계가 맞는다 | `routes/admin/logs/api.ts:139-161` |
| 16 | **`PUT /prompt/draft`·`POST /prompt/draft/discard`는 어느 화면도 안 부른다**(AD-008은 초안을 localStorage에 둔다). 구현 우선순위에서 빼도 된다. 대신 `/prompt/evaluate`·`/publish`가 **초안 전문을 body에 실어 온다** | `settings/promptops/useLocalDraft.ts:15` · `api.ts:201, 206` |
| 17 | **`gate_passed`는 클라이언트 주장이다** — 서버에 평가 결과가 남지 않는 구조라 요청이 판정을 실어 온다. 그대로 믿지 말고 서버가 재검증해야 한다(핸드오프 M4) | `settings/PromptGuardrail.tsx:132, 345` |
| 18 | 목록 `page`는 **1-base**. 오류 봉투는 **평평**하다 — `{error:{...}}`로 감싸면 프론트가 서버 문구를 버리고 고정 문구로 떨어진다 | `lib/api/client.ts:118-129` |
| 19 | 🔴 **공개 API에서 401을 쓰지 마라.** 프론트는 **경로를 안 보고** 401이면 `expireSession()`을 부른다 — 챗봇 쪽 401 하나가 열려 있던 관리자 세션까지 끊는다. 익명 차단은 401 말고 다른 4xx + `ApiError` 봉투로 | `lib/api/client.ts:107, 112` |
| 20 | ~~`POST /api/feedback`의 `request_id`만 멱등키가 아니다~~ → **2026-08-05 해소.** 한 이름이 두 뜻이던 것을 **`answer_request_id`로 분리**했다(B-07 확정). 이제 `request_id`는 어디서나 쓰기 멱등키고, 피드백이 가리키는 답변은 `answer_request_id`다. upsert 키 = `(session_id, answer_request_id)`. 응답 `{feedback_id}`가 있어야 PATCH가 가능하므로 **POST → PATCH 순서 의존**은 그대로 | `components/chat/FeedbackWidget.tsx:64` · `lib/api/types.ts:101-108` |
| 21 | **`PATCH /api/feedback/{id}`는 `reason_codes: []`도 200이어야 한다** — 칩 없이 의견만 쓴 등록을 프론트가 허용한다. ⚠ 목이 400을 주는데 **목이 틀렸다.** `comment`는 200자 | `FeedbackWidget.tsx:102, 117` |
| 22 | **`GET /api/suggestions`는 `Page<T>` 봉투가 아니다** — `Suggestion` 배열 그대로. active만·정렬·최대 10건 | `types.ts:119` · `ChatPage.tsx:180` |
| 23 | **`done.request_id`가 비면 피드백 위젯이 아예 안 그려진다.** 그리고 `done.error`가 있으면 델타를 다 흘렸어도 오류 말풍선으로 교체되고, `done.clarification`이 있으면 되묻기 말풍선으로 교체되며 `answer`는 버려진다 → **되묻기 턴엔 `answer_delta`·`sources`를 아예 보내지 마라** | `ChatPage.tsx:603, 335-339, 342-353` |
| 25 | 🔴 **`clarification`에 `options[]`를 반드시 실어라** — 2026-08-05 전에는 프론트가 착오송금 2개를 상수로 박고 있었는데 지웠다. 지금은 `{question, options:[{label, value?}]}`이고 **`options`가 비면 버튼이 하나도 안 그려진다**. 역할축이 41개라 서버가 축마다 다른 선택지를 줘야 한다. 선택 시 프론트는 `label`을 **일반 메시지로 그대로 전송**하므로 요청 스키마에 새 필드는 없다 (B-01 확정) | `components/chat/ClarificationMessage.tsx` · `lib/api/types.ts:54-64` |
| 26 | **복합 질문은 `sub_answers[]`로 내려라.** 마크다운 문자열(`**하위질문**\n답변`)을 `answer`에 이어붙이면 프론트가 파싱하지 않는다. 모양은 `sub_answers:[{title, answer, sources[], attachments[]}]`이고 **출처는 하위 블록마다 각각** 붙인다 — 하단에 모으면 어느 주장의 근거인지 끊긴다. **하위 간 출처 중복 제거 금지**(2026-07-30에 중복 제거 로직을 넣었다가 하위 답변의 출처가 통째로 사라지는 버그를 냈다). `sub_answers`가 있으면 최상위 `sources`는 빈 배열 (A-02 확정) | `src/pipeline.py:55-61, 130` |
| 27 | **`POST /api/admin/reauth` 응답은 `{reauth_valid_until_s}`** 하나다. 별도의 '마지막 인증 시각 조회' GET을 만들지 마라 — `GET /api/admin/session`이 이미 같은 값을 준다. 30분 창 계산은 **서버가** 하고 화면은 `reauth_valid_until_s <= 0`일 때만 비밀번호 슬롯을 띄운다 (B-13 확정) | `app/session.ts:28-34` |
| 28 | **재인증이 필요한 쓰기는 3종뿐** — 전체 캐시 비우기 · 권한 변경 · 롤백. **프롬프트 게시(`POST /prompt/publish`)에는 걸지 마라.** 게시는 롤백으로 되돌릴 수 있고 게시 직후 Smoke 실패 시 자동 롤백까지 있다 (A-14 확정) | `CM-DF-001 2.3` |
| 24 | **`GET /api/health`는 30초 폴링 + `X-Poll`.** 판정은 `maintenance===true \|\| status==='maintenance'` → 전면 배너, `disabled_features`에 `'chat'` 포함 → 입력 잠금. `'degraded'`만으로는 질문을 계속 받는다 | `ChatPage.tsx:167-175` |

---

## 4. 계층 규칙 — `services/`를 라우터마다 만들지 않는다

초안은 라우터 11개에 서비스 6개를 뒀는데, 그중 4개(`knowledge`·`eval`·`activity_log`·일부 `auth`)는
**"세션 받아 쿼리하고 Pydantic으로 바꿔 돌려주는" 통과층**이 된다. 파일만 늘고 읽을 게 늘어난다.

| 층 | 하는 일 | 안 하는 일 |
|---|---|---|
| `routers/` | 요청 검증 → 처리 → 응답. **CRUD는 여기서 SQLAlchemy를 직접 써도 된다** | RAG·잡 실행을 직접 하지 않는다 |
| `rag/` | `src/pipeline` 호출, SSE 변환, 워밍업/동시성 관리 | 검색·프롬프트 로직을 옮겨오지 않는다 (`src/`가 정본) |
| `jobs/` | 크롤·재적재 실행, 동시 1개 강제, 진행 기록 | HTTP를 모른다 |
| `deps.py` | 인증·역할·`reason`·재인증·**활동 로그 기록** | 도메인 로직 없음 |

**서비스 파일은 "라우터 2개 이상이 같은 로직을 쓸 때" 만든다.** 그 전엔 만들지 않는다.

### 활동 로그는 서비스가 아니라 의존성이어야 한다

핸드오프 §3-7: *"6번 이후의 모든 쓰기 API가 여기 기록된다. 나중에 붙이면 소급 불가."*
`activity_log_service.record(...)`를 각 라우터가 **호출하는** 구조면 한 곳만 빠뜨려도 조용히 누락된다.

쓰기 라우터가 의존성으로 선언하게 만든다:

```python
@router.post("/api/admin/cache/purge",
             dependencies=[Depends(require_role("ADMIN")),
                           Depends(require_reauth),
                           Depends(audit("전체 캐시 비우기"))])
```

`reason` 필수 검증(C2), `X-Poll` 제외(C6), 403에 `request_id` 싣기(C4)도 같은 자리에서 끝난다.

---

## 5. DB — 정본은 `src/schema.py` 하나

초안은 `api/db/models.py`에 13테이블을 두면서 4절엔 "정본은 `src/schema.py`"라고 적었다. 둘 중 하나만 해야 한다.

**`src/schema.py`를 정본으로 남긴다.** 이유: `src/crawler/index_document_chunks.py`,
`index_evaluation_sets.py`, `retrieval.PgVectorDenseRetriever`(retrieval.py:164),
`query_classifier`(query_classifier.py:40), `rag_logger`가 전부 여기서 테이블을 import한다.
`api/`로 옮기면 크롤러가 API를 임포트하는 역방향 의존이 생긴다.

**새 테이블은 `src/schema_admin.py` 한 파일에 넣는다** — `from schema import metadata`로
같은 `MetaData`를 공유하면 `documents`로 FK도 걸리고, `python3 src/schema.py`는 손 안 대도 계속 돈다.

붙일 순서는 화면 의존성 순이다(핸드오프 §3):

```
1차  admin_accounts · admin_sessions · admin_login_failures · password_reset_tokens · admin_activity_logs
2차  chat_sessions · chat_messages · feedback          (챗봇 저장·복원·피드백)
3차  pipeline_jobs · change_requests · previews · documents 확장컬럼
4차  evaluation_runs · evaluation_results · testset 버전 · rag_param_versions
5차  prompt_versions · guardrail_rules · ops_policy · query_cache · rate_limit_blocks
     · suggested_questions · admin_drafts
```

필요 컬럼은 `docs/frontend-handoff.md` §5 표에 이미 있다.

### alembic — 아직 넣지 않는다. 넣을 조건만 정해둔다

`metadata.create_all(checkfirst=True)`는 **테이블 존재만 보고 컬럼 diff는 안 한다.**
`schema.py:158-160`이 이미 그 함정에 걸려 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`로 손 패치를 했다.

**트리거: 그 손 패치가 두 번째로 나오는 순간 alembic을 넣는다.** 테이블 20개가 팀 공유 Supabase에서
동시에 자라므로 그 순간은 곧 온다. 미리 넣지 않는 이유는 지금 넣으면 초기 테이블 생성이
`create_all`과 alembic 두 경로로 갈려서다.

---

## 6. 프로세스 모델 — 초안에 통째로 빠진 절

이 파이프라인은 평범한 CRUD 백엔드가 아니다. `uvicorn api.main:app`을 기본값으로 띄우면 막힌다.

| 사실 | 근거 | 결과 |
|---|---|---|
| bge-m3를 **CPU에 프로세스당 1회** 로딩(~10초, ~2GB) | `retrieval.py:79-81` `_get_model` | `--workers N`이면 메모리 N배. **`--workers 1`로 시작.** 1~2GB 컨테이너에서 워커 4개면 부팅 중 OOM-kill(502)이다 |
| 검색 엔진 조립이 **첫 호출 때** 일어남 (Kiwi/BM25 ~4초 + Supabase 왕복 2회 + bge-m3 ~10초) | `retrieval.py:310` `_build_engines` | **lifespan에서 미리 돌린다.** 안 하면 첫 사용자가 `POST /api/chat`에서 ~15초를 통째로 맞는다 |
| `_engines`·`_MODEL_CACHE`·`_QEMB_CACHE`·`_classifiers`가 **잠금 없는 전역 dict** (리포 전체에 Lock이 0개) | `retrieval.py:62-63, 307` · `query_classifier.py:74, 78-80` | 값이 깨지진 않지만(GIL) 동시 첫 요청 2건이 **모델을 각각 로딩**해 순간 4GB를 쓴다. 워밍업이 이걸 같이 막는다 |
| `_QEMB_CACHE`에 **상한이 없다** | `retrieval.py:66-71` | 평가 스크립트(단명 프로세스)엔 문제없지만 상주 서버는 질문마다 1024차원 벡터가 쌓여 RSS가 단조 증가한다. 상한을 걸거나 `--max-requests`로 주기적 재시작 |
| 전 구간이 **동기·블로킹** (`SentenceTransformer.encode`, Kiwi, sync SQLAlchemy, httpx 기반 LLM 호출 2종) | `retrieval.py:70, 50, 181` · `db.py:31` · `llm_client.py:45` · `query_classifier.py:133` | **챗봇 엔드포인트를 `async def`로 쓰지 마라.** 이벤트 루프가 멈춰 다른 사용자 SSE가 같이 얼어붙는다. 평범한 `def`로 두면 FastAPI가 스레드풀로 돌린다 |
| **`data/corpus.jsonl`이 서버 디스크에 있어야 한다** | `citation.py:18` · `civil_petition.py:24` · `_build_engines`가 `chunking.build_units("all")`로 여기서 494유닛을 다시 만든다 | DB만으로는 안 된다. 배포 이미지에 이 파일을 넣어야 한다 |
| 반대로 **`chunks_all.jsonl`·`dense_cache/`는 서버에 필요 없다** | 검색은 `PgVectorDenseRetriever`(retrieval.py:328, 148-183)가 Postgres에서 읽는다. `dense_cache`는 임베딩·평가 스크립트 전용 | 이미지에 넣지 마라. `bm25_cache`도 없으면 부팅 시 ~4초에 재생성되므로 선택 사항 |

워밍업은 Streamlit이 이미 하고 있는 것을 그대로 옮기면 된다(`src/app.py:227-232`):

```python
# api/rag/engine.py
@asynccontextmanager
async def lifespan(app):
    from retrieval import _build_engines
    from query_classifier import _get_classifier
    await run_in_threadpool(_build_engines)          # bge-m3 로딩 + BM25 + pgvector 연결
    await run_in_threadpool(_get_classifier, "question_type")
    yield
```

**잡 실행(`POST /api/admin/jobs`)은 웹 프로세스에서 돌리지 마라.** 전체 재수집은 분 단위이고
"동시 실행 1개" 제약이 있다(`web/src/lib/constants.ts`). 별도 프로세스 + DB advisory lock으로
직렬화한다. FastAPI `BackgroundTasks`는 워커가 죽으면 잡도 같이 사라져서 안 맞는다.

---

## 7. 빠진 의존성 — 지금 상태로는 `pip install -r requirements.txt` 후에도 안 돈다

`requirements.txt`에 **`openai`가 없다.** `query_classifier.py:119`가 `from openai import OpenAI`를
부르고 그게 `classify_intent`의 본체다(pipeline.py:63에서 매 질문마다 탄다).
`pydantic`(`intent_llm_common.py:16`)은 `qdrant_client`·`langchain-core`를 타고 딸려 들어와서
설치는 되지만 선언은 없다 — 명시적으로 박는 게 맞다.

`.env.example`에도 **`OPENAI_API_KEY`가 없다.** 그런데 이게 없어도 **아무 오류도 안 난다** —
`classify_intent`가 모든 예외를 삼키고 `informational`로 돌려준다(`query_classifier.py:155-156`).
실제로 그 조용한 폴백이 상시 발동해서 `civil_petition` 경로(필요 서류·신청 페이지)가
**한 번도 실행된 적이 없었다**(2026-08-04 수정, 핸드오프 §4).
(`OPENAI_INTENT_MODEL`은 기본값 `gpt-5.4-mini`가 있어 선택이다 — `query_classifier.py:103`.)

**추가할 것**: `openai` · `pydantic` · `pydantic-settings` · `fastapi` · `uvicorn[standard]` · `bcrypt`.
`.env.example`에 `OPENAI_API_KEY=` · `OPENAI_INTENT_MODEL=` 두 줄.

그 이상은 넣지 마라 —
SSE는 FastAPI `StreamingResponse`에 제너레이터를 넘기면 되고(`sse-starlette` 불필요),
세션 쿠키는 `secrets.token_urlsafe(32)`를 `admin_sessions`에 저장해 조회하면 되므로
서명 라이브러리(`itsdangerous`)가 필요 없다. `passlib`도 `bcrypt` 직접 호출로 충분하다.

**API를 붙인 뒤 `civil_petition` 경로를 반드시 E2E로 한 번 태울 것.** 여태 안 돌아본 코드다.

---

## 8. 계약 테스트는 공짜로 얻는다

`web/src/mocks/selfcheck.ts`가 SSE 이벤트 순서 · `Page<T>` 봉투 · 400/403 검증 · 파이프라인 진행을
**실제로 찔러보는 13항목**이다. `BASE`를 FastAPI 주소로 바꾸고 `setupServer` 두 줄만 지우면
같은 assert가 진짜 서버를 검증한다(`web/src/mocks/README.md` §8).

파이썬으로 다시 짜지 마라. 계약 테스트를 새로 만드는 대신 이걸 CI에 건다.

---

## 9. 구현 순서

핸드오프 §3의 0~16번을 그대로 쓴다(의존성 순으로 이미 정렬돼 있다). 폴더 대응만 적으면:

| 단계 | 만들 것 | 파일 |
|---|---|---|
| **0** | 뼈대 — CORS(쿠키), `ApiError` 정규화, `Page[T]`, `request_id`/`reason` 검증 | `__init__.py` · `main.py` · `config.py` · `errors.py` · `pagination.py` · `deps.py` · `middleware.py` |
| **0.5** | 🔴 §1의 3건 (sys.path · dict 반환 · `.stream()`) | `src/pipeline.py` · `src/llm_client.py` |
| **1** | ★ `POST /api/chat` (SSE) — **이것만 되면 챗봇 5화면이 전부 산다** | `routers/chat.py` · `rag/*` |
| 2~3 | `health` · `suggestions` | `routers/public.py` |
| 4~5 | 피드백 · 대화 복원 | `routers/public.py` + `chat_sessions`·`chat_messages`·`feedback` |
| 6~7 | 관리자 인증 + **활동 로그 쓰기(같이 붙인다)** | `routers/auth.py` · `deps.audit` · 1차 테이블 |
| 8 | 지식베이스 조회 — `documents`·`document_chunks`가 이미 있어 **가장 싸다** | `routers/knowledge.py` |
| 9~10 | 잡 · 변경요청 | `routers/pipeline.py` · `jobs/*` (+ `routers/knowledge.py`) |
| 11~12 | 대화 로그 · 대시보드 | `routers/logs.py` · `routers/dashboard.py` |
| 13~16 | 평가 · RAG 파라미터 · 프롬프트 · 운영정책 (**서로 독립, 순서 무관**) | 나머지 라우터 |

CORS는 처음부터 정확히: 세션이 httpOnly 쿠키라 `allow_credentials=True` +
`allow_origins=["http://localhost:5173"]`이 필요하다. **`*`는 못 쓴다**(`lib/api/client.ts:91`).

---

## 10. `main.py`와 `schema.py` (초안 4절에 대한 답)

역할이 겹치지 않는 게 맞다 — 초안 결론에 동의한다. 다만 정확히는:

- `api/main.py` — 앱 **조립**. 라우터 등록 · CORS · 예외 핸들러 · lifespan 워밍업. 로직 없음.
- `src/schema.py` — DB **테이블 정의**. FastAPI를 모른다. `python3 src/schema.py`로 단독 실행된다.
- `api/schemas/` — **API 계약**(Pydantic). DB 모델과 목적이 달라 분리하는 것도 맞다.
  다만 손으로 새로 쓰지 말고 `web/src/lib/api/types.ts`·`lib/codes.ts`·`routes/admin/*/api.ts`를 **옮겨 적어라.**
  프론트가 이미 확정한 값이고, 다르면 화면이 깨진다.
