# 게이트 차단 2건 — 근본 원인과 해결안

관리자 초안 흐름(① 편집 → ② 평가 → ③ 반영/게시)에서 두 화면 모두 ③ 도달 불가. 모든 주장 file:line 실측 재확인함.

| | 화면 | 원인 한 줄 |
|---|---|---|
| 차단 1 | AD-007 RAG 파라미터 | 서버는 sha256 해시를 주는데(`api/routers/admin_rag_params.py:156-160`) 프론트는 `JSON.stringify(draft)`와 비교(`web/src/routes/admin/settings/RagParams.tsx:116`) → 항상 stale → [운영 반영] 영구 비활성 |
| 차단 2 | AD-008 프롬프트 | 표본 4문항 100% 게이트(`api/routers/admin_prompt.py:83,371-372`) × 비결정 생성(temperature 0.2, seed 없음, `src/llm_client.py:41`) × **운영에는 있는 마커 오표기 복구(source_check)가 평가 경로에는 없음** → 같은 초안도 실행마다 판정이 뒤집힘 |

---

## 차단 1 (AD-007) — 시그니처 계약 버그

백엔드 `draft_signature()`는 정렬 정규화 JSON의 sha256 앞 16자다(`admin_rag_params.py:156-160`). 프론트는 이걸 `JSON.stringify(draft)`와 문자열 비교하므로(`RagParams.tsx:116`) 실백엔드에서는 평가 직후에도 무조건 stale. MSW 목이 `draft_signature: JSON.stringify(body.draft)`를 반환해(`web/src/mocks/handlers/extra/ad-eval-rag.ts:523`) 목에서만 통과했다 — 목이 프론트의 틀린 가정에 맞춰진 상태.

### 후보 비교

| 후보 | 장점 | 단점 | 계약 안정성 |
|---|---|---|---|
| **(a) 평가 시점 draft 스냅샷 로컬 보관 + 값 비교** (시그니처는 opaque 토큰) | 프론트만 수정(우리 몫), 동기, 서버 해시 방식이 바뀌어도 무영향 | 스냅샷 시딩 1줄 필요(새로고침 시 서버 `draft`로 복원) | **최고** — 시그니처 포맷에 아무 가정 없음 |
| (b) crypto.subtle로 동일 해시 재계산 | 서버와 같은 판정 로직 | Python `json.dumps(sort_keys, separators, ensure_ascii=False)` 정규화를 JS로 복제하는 그림자 계약(숫자 직렬화 차이로 조용히 어긋남), async라 렌더 경로에 부적합 | 낮음 — 해시 알고리즘이 계약이 돼버림 |
| (c) 백엔드가 JSON 문자열 반환 | 프론트 무수정처럼 보임 | 백엔드는 팀원 몫. 게다가 `JSON.stringify(draft)`는 **삽입 순서** 직렬화라 서버의 정렬 직렬화와 여전히 불일치 → 고쳐도 또 틀림. apply의 서버측 지문 대조(`admin_rag_params.py:453`)와 이중 포맷 | 낮음 |

**권장: (a).** 서버가 저장한 draft는 곧 평가된 draft이므로(`_stored_gate`가 저장 draft의 지문을 그대로 복원, `admin_rag_params.py:245-259`) 새로고침 후에도 `server.draft`를 스냅샷으로 쓰면 정확하다.

### diff 스케치 — `web/src/routes/admin/settings/RagParams.tsx` (프론트 몫, 즉시 수정 가능)

```tsx
// 상태 추가 (기존 draft state 옆, ~L66)
const [evaluated, setEvaluated] = useState<Values | null>(null)

// L70 useEffect — 서버 초안 시딩 시 스냅샷도 시딩 (gate가 있으면 server.draft = 평가된 초안)
useEffect(() => {
  if (server && draft === null) {
    setDraft({ ...(server.draft ?? server.current) })
    if (server.gate.draft_signature !== null && server.draft) setEvaluated({ ...server.draft })
  }
}, [server, draft])

// L74-80 evaluate 뮤테이션 — onSuccess 2번째 인자(variables)가 평가에 보낸 값
onSuccess: (gate, values) => {
  setEvaluated({ ...values })
  queryClient.setQueryData<RagParamsResponse>(ragKeys.params, (prev) => prev ? { ...prev, gate } : prev)
},

// L116 — 시그니처는 "평가가 존재하는가"만 보고, stale은 값으로 판정
const stale = gate.draft_signature !== null &&
  (evaluated === null || changedParams(server.params, draft, evaluated).length > 0)
```

`changedParams`(L41-43)를 재사용하므로 deep-equal 헬퍼 추가도 불필요(값이 평면 `Record<string, ParamValue>`).

### 목 정렬 — "목이 곧 계약" 복구 (`ad-eval-rag.ts`, 프론트 몫)

시그니처를 opaque 토큰으로 — 프론트가 다시는 포맷에 기댈 수 없게 한다:

```ts
// L523: draft_signature: JSON.stringify(body.draft) → opaque 해시로
function mockSignature(draft: Record<string, ParamValue>): string {
  const canon = JSON.stringify(Object.fromEntries(Object.entries(draft).sort()))
  let h = 2166136261 // FNV-1a — 실서버와 값은 다르지만 "같은 내용=같은 토큰, 포맷은 불투명" 계약이 같다
  for (let i = 0; i < canon.length; i++) { h ^= canon.charCodeAt(i); h = Math.imul(h, 16777619) }
  return (h >>> 0).toString(16).padStart(16, '0')
}
draft_signature: mockSignature(body.draft),
```

추가 목 어긋남(같은 파일, 같은 PR에서 정리 권장):
- 목 파라미터 키가 `top_k_candidate`/`fusion_alpha`/`llm_model` 등(`ad-eval-rag.ts:300-337`)인데 실서버는 `k_candidates`/`k_final`/`min_top1_score`/`use_*` 7종(`admin_rag_params.py:91-121`). 특히 서버는 `fusion_alpha`(HYBRID_LINEAR_ALPHA)를 **의도적으로 비노출**(`admin_rag_params.py:22-23`).
- `RagParams.tsx:138`의 상호 제약이 목 키 `'top_k_final'`/`'top_k_candidate'`로 하드코딩 → 실서버 키(`k_final`/`k_candidates`)에서는 조용히 no-op. 같이 수정.
- 목 gate가 `smoke_total: 30, smoke_passed: 30`(`ad-eval-rag.ts:529`)인데 실서버는 이 화면에서 항상 `smoke 0/0`(`admin_rag_params.py:196-199,242`).

---

## 차단 2 (AD-008) — 비결정 평가 위 100% 게이트

실측 재확인: 게이트 `passed = src_ok == len(in_scope) and oos_ok == len(oos) and guard_hits == 0 and regressed == 0`(`admin_prompt.py:371-372`), 표본 `EVAL_IN_SCOPE = 4`(`:83`), Smoke `activate = passed == SMOKE_TOTAL`(30/30 전건, `:420`), 생성은 `temperature=0.2`·seed 없음(`llm_client.py:41`).

### 표준 기법 정리 (웹 조사)

1. **디코딩 결정화** — temperature=0(그리디) + seed 고정. OpenAI·Azure 모두 seed는 "best-effort"이며 완전 결정성은 보장 안 됨(GPU 비결합 연산·배칭). [OpenAI cookbook](https://developers.openai.com/cookbook/examples/reproducible_outputs_with_the_seed_parameter) · [Azure reproducible output](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/how-to/reproducible-output?view=foundry-classic) · [seed+temp0에도 비결정 사례](https://community.openai.com/t/chatcompletions-are-not-deterministic-even-with-seed-set-temperature-0-top-p-0-n-1/685769)
2. **n회 반복 다수결 / pass^k** — 문항당 k회 생성해 다수결. 비용 k배. 결정화와 택일(seed 고정 후 재실행은 같은 출력이라 무의미).
3. **재시도 확인(flaky-test 패턴)** — 실패 문항만 다른 seed로 1회 재생성, 재실패 시에만 실패 확정("2회 연속 실패"). 비용이 실패 건수에만 비례.
4. **임계값 게이트** — 문항당 통과확률 p=0.9면 4/4 전건 통과확률은 0.9⁴≈66%, 30/30은 p=0.97에도 0.97³⁰≈40%. 소표본 100% 요구는 통계적으로 게이트가 아니라 동전던지기다.
5. **표본 확대 / paired 비교** — 문항 수를 늘려 분산 축소, 전/후를 같은 문항·같은 근거로 짝지어 뒤집힌 문항만 판정(McNemar식). 이 코드는 이미 paired 구조(같은 검색 근거로 전/후 생성, `admin_prompt.py:314-316`)라 절반은 갖췄다.

**HCX(CLOVA Studio) 지원 확인:** Chat Completions v3가 `seed`(1~4,294,967,295, "일관된 결과 생성"; 0=랜덤 기본)와 `temperature` 0.00~1.00(0 허용)을 지원한다 — [CLOVA Studio Chat Completions v3 API](https://api.ncloud-docs.com/docs/en/clovastudio-chatcompletionsv3). 코드 경로도 열려 있다: `langchain-naver==0.1.1`의 `ChatClovaX`는 `BaseChatOpenAI` 상속(`site-packages/langchain_naver/chat_models.py:96`)이라 `seed` 필드가 요청 페이로드에 그대로 실린다(`langchain_openai/chat_models/base.py:759,1352`). **신규 의존성 없이 지금 바로 주입 가능.**

### 이 코드베이스의 진짜 근본 원인 — 평가가 운영보다 엄격하다

운영 파이프라인은 마커가 `[NO_SOURCE]`일 때 `source_check.recheck_source_usage()`로 오표기를 복구한다(`src/pipeline.py:140-147`, 기본 On `src/pipeline.py:76`). 마커 오표기는 실측 54%(근거 사용 61건 중 33건, `src/source_check.py` 모듈 주석), `[SOURCE_USED]` 방향 오판은 0건. 그런데 **평가·Smoke의 `_generate()`는 원시 마커만 판정한다**(`admin_prompt.py:333`) — "출처 부착 3/4에서 항상 1건이 흔들린다"는 실측은 정확히 이 오표기 노이즈다. 즉 게이트가 재는 것은 프롬프트 품질이 아니라 **운영에서는 이미 복구되는 마커의 알려진 결함**이다. 평가를 운영과 같은 판정으로 맞추는 것이 최우선 수정.

### 권장안 (우선순위 순)

1. **판정 정렬** — `_generate()`에 운영과 동일한 recheck 적용(아래 diff). 지배적 노이즈원 제거 + "평가=운영" 원칙 복구.
2. **평가·Smoke 경로만 결정화** — `llm_client`에 평가 전용 클라이언트(temperature 0, seed 고정) 추가. 운영 경로(`pipeline.py:125`, `api/rag/sse.py`)는 0.2 그대로 — 호출부가 opt-in하므로 운영 영향 0. (주의: `llm_client.py:21-36` 주석대로 기존 실측치는 전부 0.2 기준 — 평가 경로 온도만 바꾸는 것이라 운영 재측정 불요.)
3. **게이트 공식** — HCX seed도 best-effort이므로 잔여 흔들림 대비: 출처 부착 `src_ok >= 3/4`(1건 허용), 회귀는 **REGRESSED 후보만 seed 바꿔 1회 재생성, 재실패 시에만 확정**(2회 연속 실패). 범위외 2/2·금칙어 0건은 유지(`[NO_SOURCE]` 방향과 문자열 매칭은 역사적으로 안정).
4. **Smoke 30/30** — 같은 문제이며 이항 확률상 더 심각(p=0.97에도 통과율 40%). 전건 통과 의미는 유지하되 **실패 문항만 seed 바꿔 1회 재시도 후 판정**. 실패 시 '실패' 버전 기록(`admin_prompt.py:421-433`) 부작용이 있어 오탐 비용이 특히 크다.
5. (선택) `EVAL_IN_SCOPE` 4→8 확대 — HCX 콜 (8+2)×2=20, ~2분. 3번까지로 부족하면.

### diff 스케치 (백엔드 몫 — 팀 전달용)

`src/llm_client.py` — 평가 전용 클라이언트 추가, 운영 경로 무변경:

```python
EVAL_SEED = 20260813  # 평가·Smoke 전용. 운영(_get_client)은 0.2 그대로

def _get_eval_client():
    if "eval" not in _client:
        from langchain_naver import ChatClovaX
        _client["eval"] = ChatClovaX(model_name=os.environ["CLOVA_MODEL"],
                                     api_key=os.environ["CLOVA_STUDIO_API_KEY"],
                                     temperature=0.0, seed=EVAL_SEED, max_tokens=2048)
    return _client["eval"]

def call_hyperclova(messages, *, deterministic=False, seed=None):
    client = _get_eval_client() if deterministic else _get_client()
    if deterministic and seed is not None:
        client = client.bind(seed=seed)   # 재시도 확인용 — seed만 바꿔 1회 더
    response = client.invoke(messages)
    return response.content
```

`api/routers/admin_prompt.py` — `_generate` 판정 정렬 + 결정화(`:318-334`):

```python
def _generate(question, si, few_shot, *, seed=None):
    ...
    raw = call_hyperclova([("system", si), ("human", human)], deterministic=True, seed=seed)
    body, marker_used = prompt_builder._strip_no_source_marker(raw)
    # 운영과 동일한 마커 오표기 복구(pipeline.py:140-147). 같은 근거 본문을 넘긴다.
    if not marker_used and top and runtime_config.get_param("use_source_recheck", pipeline.USE_SOURCE_RECHECK):
        from source_check import recheck_source_usage
        marker_used = recheck_source_usage(body, context)
    ...
```

게이트 공식(`:355-374` 부근) — 회귀 확정 재시도 + 임계값:

```python
if before_ok and not after_ok:                      # REGRESSED 후보 → seed 바꿔 1회 확인
    a2_body, a2_marker, _ = _generate(q, content["system_instruction"], content["few_shot"], seed=EVAL_SEED + 1)
    after_ok = (a2_marker if kind == "in" else not a2_marker) and not [w for w in blockwords if w in a2_body]
# 확정된 after_ok 로 기존 IMPROVED/KEEP/REGRESSED 분기 그대로

gate["passed"] = (src_ok >= max(len(in_scope) - 1, 1)   # 출처 부착 ≥ 3/4
                  and oos_ok == len(oos) and guard_hits == 0 and regressed == 0)
gate["source_attached"]["passed"] = src_ok >= max(len(in_scope) - 1, 1)
```

Smoke(`:409-420`) — 실패 문항만 재시도:

```python
for q in questions:
    ok = _smoke_one(q, content)                     # 기존 본문 판정을 함수로 추출
    if not ok:
        ok = _smoke_one(q, content, seed=EVAL_SEED + 1)   # flaky 흡수 — 2연속 실패만 실패
    if ok: passed += 1
activate = passed == SMOKE_TOTAL                    # 전건 통과 의미는 유지
```

프론트 계약 영향: `PromptEvaluation`/`PublishResult` 응답 모양 무변경 — `web/src/lib/api/types.ts`·목 수정 불요(게이트 수치 의미만 문서화).

---

## 팀 전달 체크리스트

**프론트 몫 (web/ — 우리가 직접 수정):**
- [ ] `RagParams.tsx:116` stale 판정을 로컬 스냅샷 값 비교로 교체(+ L70 시딩, L76 onSuccess) — 차단 1 해소
- [ ] `RagParams.tsx:138` 상호 제약 키를 실서버 키(`k_final`/`k_candidates`)로 수정
- [ ] `ad-eval-rag.ts:523` 목 시그니처를 opaque 해시로 교체(위 `mockSignature`)
- [ ] `ad-eval-rag.ts:300-337,529` 목 파라미터 키 7종·`smoke 0/0`을 실서버(`admin_rag_params.py:91-121,242`)와 정렬 — `fusion_alpha`는 서버가 의도적 비노출이므로 목에서 제거
- [ ] `web && pnpm verify` + 실백엔드로 ①→②→③ 관통 확인

**백엔드 몫 (api/·src/ — 팀원에게 전달, 코드 수정 금지 규약):**
- [ ] `llm_client.py` 평가 전용 클라이언트(temperature 0 + seed, CLOVA v3 지원 확인됨·langchain-naver 0.1.1 passthrough 확인됨). 운영 경로 무변경
- [ ] `admin_prompt.py:_generate`에 운영과 동일한 `source_check` 복구 적용(`use_source_recheck` 파라미터 존중) — 흔들리는 "출처 부착 1건"의 근본 원인
- [ ] `admin_prompt.py:371-372` 게이트: 출처 부착 ≥ 3/4 + REGRESSED는 seed 재시도로 2연속 실패만 확정
- [ ] `admin_prompt.py:409-420` Smoke: 실패 문항만 seed 재시도 후 전건 판정
- [ ] 검증: 무변경 초안으로 evaluate 2회 연속 실행 → 판정·verdict 동일해야 함 (현재는 뒤집힘, 실측 2026-08-13)
