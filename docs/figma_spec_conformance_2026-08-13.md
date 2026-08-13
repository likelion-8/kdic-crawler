# 기획서 ↔ 구현 대조 보고 (2026-08-13)

대상: Figma 화면설계서 `TjgCOfBuXwlHjepM2YBbFN` v12.29 (PRD-01~03 · CM-DF-002 · CM-DF-003)
↔ 실제 코드 (`api/` · `src/` · `web/`), 브랜치 `verify/figma-spec-conformance` (base `8d26a8f1`).

**모든 주장은 실제 파일을 열어 확인했고 file:line을 붙였다.** 문서(로그·README)는 근거로 쓰지 않았다.

---

## 0. 결론

관리자 백엔드는 **화면이 부르는 80개 엔드포인트 중 76개가 실재**하고, 세션·권한·감사·게이트 같은
어려운 정책들이 기획서 수치 그대로 구현돼 있다. 껍데기가 아니다.

다만 **"화면은 그려지는데 뒤에서 아무 일도 일어나지 않는" 구간이 4곳** 남아 있고,
이건 데모에서는 보이지 않다가 운영에서 터지는 종류다.

| | 항목 | 상태 |
|---|---|---|
| 🔴 | 마스킹 (개인정보) | 스텁 — `question_masked` 필드가 원문을 담아 나간다 |
| 🔴 | AD-009 요청 제한 정책 | 화면에서 저장은 되나 **실제 제한에 반영되지 않는다** |
| 🔴 | AD-008 가드레일(금칙어·마스킹) | 챗봇 응답 경로에 **적용되는 곳이 없다** |
| 🔴 | 질의 캐시 | 테이블·통계·비우기 API만 있고 **캐시가 동작하지 않는다** |
| 🟠 | 프론트 4개 호출이 백엔드에 없음 | 목에서만 동작 (AD-006는 진입 즉시 실패) |
| 🟠 | 배치 스케줄러 전무 | 02:00 변경 감지·03:00 링크 점검·정기 재측정·보관기간 파기 |
| 🟠 | LLM 타임아웃 30초·자동 재시도 1회 | 미구현 |
| 🟠 | 복합 질문 최대 3개 상한 | 플래너에 없음 |
| 🟡 | MSW 프로덕션 가드 없음 | 빌드 시 환경변수 미설정이면 목이 그대로 실린다 |

---

## 1. 정합 확인됨 — 다시 대조하지 않아도 되는 것들

| 기획서 | 코드 | 확인 |
|---|---|---|
| 세션 3타이머 절대 8h / 유휴 30m / 재확인 30m (CM-DF-003) | `api/deps.py:94-96` | ✓ 값 일치 |
| [연장]은 `last_activity_at`만 갱신, 재인증은 둘 다 | `admin_auth.py:327-334`, `:337-388` | ✓ |
| 폴링(`X-Poll: 1`)은 유휴 타이머 갱신 제외 (B-08) | `api/deps.py:100,182` | ✓ |
| `GET /session` 응답 5필드 (B-06·B-13) | `admin_auth.py:310-324` | ✓ 필드명까지 일치 |
| 로그인 5회 실패 → 10분 잠금 자동 해제 | `admin_auth.py:66-68,175` | ✓ |
| 계정 존재 비노출 (재설정 항상 202) | `admin_auth.py:798-824` | ✓ |
| 목록 봉투 `Page<T>{items,total,page,size}` (B-04) | 전 라우터 공통 | ✓ |
| 파이프라인 동시 실행 1개 → 409 retryable=false | `admin_pipeline.py:65,76,424` | ✓ |
| 게이트 정확도@5 ≥ 0.92 · MRR ≥ 0.80 | `admin_rag_params.py:77-78,207` | ✓ |
| Smoke 30/30 통과 시에만 게시 전환 | `admin_prompt.py:81,420` | ✓ |
| SSE 4종 `accepted·answer_delta·done·error` | `api/rag/sse.py:7-10` | ✓ |
| ChatResponse 필드 계약 · 복합질문 시 최상위 sources 빈 배열 | `api/schemas/chat.py:101-135` ↔ `web/src/lib/api/types.ts:80-98` | ✓ |
| 입력 500자 상한 (프론트·백엔드 양쪽) | `Composer.tsx:16`, `api/schemas/chat.py:21` | ✓ |
| 대화 복원 24시간 (DB now 기준) | `api/routers/session.py:28,63-66` | ✓ |
| 피드백 답변당 1건 upsert + PATCH 사유 보완 | `feedback.py:24-64` | ✓ |
| 검색 파라미터 K=20/5 · 리랭커 Off · 플래너 On | `api/rag/answer.py:45-46,108-109` | ✓ CM-DF-003 05절과 일치 |
| 플래너 모델 `gpt-5.6-luna` (협의 결정) | `src/query_planner.py:36` | ✓ 코드가 협의를 따라왔다 |
| AD-007·AD-008 반영값이 실제 런타임에 도달 | `src/runtime_config.py:111-123`, `prompt_builder.py:85` | ✓ 게시·반영이 장식이 아니다 |
| 활동 로그 결과 3종·추가 전용·전후 스냅샷 | `api/deps.py:327-329`, 각 라우터 | ✓ |

**PRD-03이 2026-08-03에 "미구현"으로 적어둔 것 중 그 뒤 해결된 것:**
파이프라인 잡 시스템(`src/worker.py` — 실제 크롤·청킹·색인 수행), 인덱스 적재 방식
(DELETE→재적재 였던 것이 UPSERT + 옛 경계 청크 삭제로 바뀜, `src/worker.py:322-330`),
Smoke 30 러너(`admin_prompt.py:384-445`).

> ⚠️ 참고: 백엔드 라우터만 훑으면 "잡을 실행하는 워커가 없다"는 결론이 나온다.
> 워커는 `api/`가 아니라 `src/worker.py`에 있다. 이 대조에서 실제로 한 번 빗나갔던 지점이다.

---

## 2. 결함 — 심각도순

### 🔴 F-1. 마스킹이 스텁인데 필드 이름은 `*_masked`

- `api/masking.py:31` — `mask_text()`가 입력을 **그대로 반환**한다.
- `admin_logs.py:271,408` — `question_masked` · `answer_masked_preview` · `answer_masked_full`이
  전부 원문이다.
- 기획서 요구: PRD-01 3장 "질문·답변은 마스킹 후 저장(90일)", CM-DF-004 08절.

모듈 주석에 "이번 주 마스킹은 구현하지 않기로 팀에서 정했다"고 적혀 있어 **의도된 미구현**이지만,
필드 이름이 마스킹을 약속하고 있어 AD-005를 보는 관리자는 마스킹된 값이라 믿는다. 저장본도
마스킹돼 있지 않다(`api/rag/conversation.py:25-27` — 저장은 원문, 마스킹은 읽는 쪽 책임으로 이관).

### 🔴 F-2. AD-009에서 저장한 요청 제한이 실제 제한이 아니다

- 화면이 저장하는 값: `ops_policy` 테이블 (`admin_ops.py:177-220`, 기본값 `:77-84` = ip 10/분,
  300/일, burst 3/10초, 세션 30/30분 — **기획서 수치와 정확히 일치**).
- 실제로 걸리는 제한: `api/middleware.py:113` — `settings.rate_limit_per_minute`
  (`api/config.py:64` = **30/분 고정**).
- `ops_policy`를 읽는 코드는 `admin_ops.py`(CRUD) 밖에 **한 곳도 없다**.

즉 관리자가 IP 제한을 10회로 낮춰도 서버는 계속 30회로 돈다. 추가로 일일 300회·burst·세션 단위
제한은 아예 없고, "10분 내 위반 3회 → 10분 임시 차단"도 없다 — `rate_limit_blocks`에
행을 만드는 코드가 없어(`src/schema_admin.py:222`만 존재) 차단 목록은 항상 비어 있다.

### 🔴 F-3. 가드레일(금칙어·마스킹 규칙)이 챗봇 경로에 적용되지 않는다

- `guardrail_rules` 테이블의 `kind='blocklist'`를 읽는 곳은 **추천 질문 저장 검증 한 곳뿐**
  (`admin_ops.py:502-518`).
- `kind='masking'` 규칙을 읽는 코드는 **어디에도 없다**.
- AD-008에서 금칙어를 등록해도 사용자 질문·답변에는 아무 영향이 없다.

### 🔴 F-4. 질의 캐시가 동작하지 않는다

- 기획서: TTL 24h · 적격 질문만 · 키 = 정규화 질문 + 버전 스냅샷 (PRD-03 AD-009).
- 코드: `query_cache` 테이블(`src/schema_admin.py:205`), 통계·비우기 API(`admin_ops.py:255-298`),
  키 정규화 함수(`:128-141`)까지 다 있는데 **`/api/chat` 경로가 캐시를 읽지도 쓰지도 않는다**.
  `api/rag/`·`api/routers/chat.py` 어디에도 `query_cache` 참조가 없다.
- 결과: AD-009의 적중률·절약 건수는 영원히 0이고, TTL·버전 무효화 로직도 실체가 없다.

### 🟠 F-5. 프론트가 부르는데 백엔드에 없는 엔드포인트 4개

| 화면 | 프론트 호출 | 백엔드 | 증상 |
|---|---|---|---|
| AD-006 | `GET /api/admin/evaluations/schedule` (`evaluation/api.ts:157`) | 없음 | **진입 즉시** 404 — 화면 일부가 항상 실패 |
| AD-000 | `POST /api/admin/password/reset-request` (`PasswordResetPanel.tsx:130`) | 이름이 `/password/reset` (`admin_auth.py:798`) | 비밀번호 재설정 1단계 불가 |
| AD-005 | `POST /api/admin/logs/{id}/rerun` (`logs/api.ts:188`) | 없음 (`admin_logs.py:8`에 의도적 미구현 명시) | [재실행] 실패 |
| AD-005 | `PATCH /api/admin/logs/{id}` (triage) (`logs/api.ts:193`) | 없음 | [처리 완료] 실패 |

앞의 둘은 **경로 이름만 맞추면 끝난다.** 뒤의 둘은 서버가 의도적으로 안 만든 것이라 결정이 필요하다.

### 🟠 F-6. 배치 스케줄러가 전혀 없다

기획서가 요구하는 정기 작업 — 변경 감지 02:00 · 링크 점검 03:00 · 월 1회 전체 재수집 ·
매주 월 04:00 정기 재측정 · 보관기간 경과분 파기(질문 90일 / 피드백 1년 / IP 7·30일).
`api/`·`src/` 어디에도 스케줄러(APScheduler·cron·systemd timer)가 없다. `src/worker.py`는
사람이 만든 잡만 소비한다.

부수 효과: `admin_activity.py:198-240`의 `purge_due_this_week`가 "90일 지나 지워질 예정"을 세지만
**지우는 주체가 없어** 그 수는 계속 늘기만 한다.

또 `POST /api/admin/pipeline/changes/recheck` (`admin_pipeline.py:389-406`)는 **재크롤·해시 비교를
하지 않고** 활동 로그 한 줄만 남긴 뒤 같은 목록을 돌려준다. [다시 확인] 버튼이 아무것도 확인하지 않는다.

### 🟠 F-7. LLM 타임아웃 30초 · BE 자동 재시도 1회 미구현

- 기획서(PRD-03 CB 공통 · CM-DF-002 04절): 30초 무응답 타임아웃, 타임아웃·5xx에 대해 서버가
  같은 `request_id` 계열로 1회 자동 재시도.
- 코드: `src/llm_client.py`에 timeout·retry 설정이 없고, `api/rag/answer.py:326-351`은 예외를
  오류 코드로 **매핑만** 한다. 재시도 루프가 없다.
- 결과: HCX가 느리면 사용자가 무한정 기다린다(FE 30초 폴백만 동작). CM-DF-002의
  "BE 재시도 1회" 열이 LLM_TIMEOUT·LLM_ERROR 모두에서 사실이 아니다.

### 🟠 F-8. 복합 질문 상한 3개 규칙이 없다

- 기획서: 최대 3개 분해 · 4개 이상이면 우선순위 3개 + 분리 안내.
- `src/query_planner.py:55-132` — `items` 개수에 상한이 없고 초과 안내 문구도 없다.
- PRD-03이 8/3에 지적한 그대로 남아 있다.

### 🟠 F-9. 재적재가 "임시 색인 → 평가 → 통과 시 교체"가 아니다

- 기획서(PRD-03 AD-004): 재청킹 → 재임베딩 → **임시 색인** → 홀드아웃 평가 → 통과 시 교체 ·
  캐시 무효화 (미달 시 자동 중단·기존 유지).
- 코드(`src/worker.py:322-397`): 청킹 → 검증 → **운영 테이블에 직접 UPSERT** → 버전 기록.
  중간 평가 게이트도, 교체 후 홀드아웃 자동 재측정도, 캐시 무효화도 없다.
- 개선은 있었다(과거 DELETE→재적재보다 안전). 다만 실패 시 "부분 반영 가능성"이 남는 건
  워커 자신이 인정한다(`src/worker.py:54-55`).
- 추가로 `src/worker.py:399`: 색인 후에도 **BM25 축은 API 프로세스를 재기동해야 반영**된다.
  link_guide 질의는 재적재 직후 옛 코퍼스로 검색된다.

### 🟡 F-10. MSW 프로덕션 가드 없음

`web/src/main.tsx:18` — `VITE_ENABLE_MSW === 'false'` 일 때만 목을 끈다. 즉 **미설정이면 켜진다**.
`import.meta.env.PROD` 가드가 없어 `pnpm build`를 환경변수 없이 돌리면 목이 번들에 실린다.
(`web/Dockerfile`은 `pnpm dev` 개발용 이미지라 이 자체가 사고는 아니지만, 배포 빌드 경로가 아직
없다는 뜻이기도 하다.)

### 🟡 F-11. 화면은 있는데 원천 데이터가 없는 필드들

지어내지 않고 빈 값을 내리는 정직한 처리지만, 화면에는 계속 빈칸으로 보인다.

| 화면 | 필드 | 위치 |
|---|---|---|
| AD-001 | 리소스·비용 전부 (`del admin, db`로 DB를 안 본다) | `admin_dashboard.py:245-258` |
| AD-001 | 단계별 평균 응답시간 8구간 — 이름만 있고 `avg_ms` 전부 0 | `admin_dashboard.py:55-64,206` |
| AD-001 | 업무별 분포 `[]` | `admin_dashboard.py:202` |
| AD-005 | 상세 분류(업무·마커·정규화)·오류 블록 전부 빈 문자열 | `admin_logs.py:418-445` |
| AD-005 | `source_count` · `triage` 하드코딩 | `admin_logs.py:275,277` |
| AD-009 | 추천 질문 `click_count` 전부 null | `admin_ops.py:400` |
| AD-011·AD-005 | 내보내기 — `export_id`만 발급하고 **파일이 만들어지지 않는다** | `admin_activity.py:341`, `admin_logs.py:488` |

### 🟡 F-12. 프롬프트 이름이 여전히 "예솜"

`src/prompt_builder.py:28,36,55` — 기본 시스템 프롬프트가 `"예솜"`. 기획서는 `예솜24`이고
PRD-03이 8/3에 "정정 미해결"로 적었는데 그대로다. (AD-008에서 게시하면 DB 값이 이기므로
운영 영향은 게시 전까지다.) 프롬프트 길이도 CM-DF-003 06절 `1,021자` ↔ 실측 **1,129자**로 어긋난다.

---

## 3. 이 브랜치에서 고친 것

`pnpm verify`가 **base 커밋에서 이미 깨져 있었다** — `61d5f914`가 `PageDetailActions`에
`onCancelDelete` 필수 prop을 추가하면서 셀프체크를 안 고쳤다.

- `web/src/routes/admin/knowledge/selfcheck.tsx` — 호출 2곳에 `onCancelDelete={() => {}}` 추가.

검증: `pnpm verify` → **tsc 통과 · oxlint 경고만(에러 0) · 셀프체크 11종 전체 통과**.

---

## 4. 검증 방법 · 한계

- Figma는 `use_figma`로 `0:1` 페이지의 PRD-01/02/03 · CM-DF-002 · CM-DF-003 시트 텍스트를
  통째로 덤프해 읽었다. **기획서는 수정하지 않았다**(이번 작업은 대조만).
- 코드는 `api/` 17개 라우터 전수 + `src/worker.py`·`src/query_planner.py`·`src/prompt_builder.py`·
  `api/masking.py`·`api/middleware.py`·`web/` 라우트 전수를 읽어 확인했다.
- **서버를 띄워 실제 호출한 검증은 하지 않았다.** F-5의 4건은 라우트 부재를 코드로 확인한 것이고,
  런타임 동작(SSE 지속·게이트 실측)은 정적 확인 범위다.
- CM-DF-001(공통 UI)·CM-DF-004(서비스 정책)·CB/AD 개별 화면 시트의 픽셀 단위 대조는 범위 밖이다.
