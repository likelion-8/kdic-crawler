# 평가 API(AD-006) 구현 노트 · 남은 갭

작성: C 트랙(평가) · 대상: 팀(스키마 권한자)·프론트(evaluation/api.ts, DraftStatusBar)
관련 파일: api/routers/admin_evaluations.py · api/schemas/evaluations.py · api/routers/admin_drafts.py

## 0. 무엇을 만들었나

평가 화면(AD-006) 백엔드 7종 + 자동저장 PUT. 실행 채점 로직은 **새로 짜지 않고**
`src/eval/eval_pipeline_retrieval.py`·`eval_pipeline_generation.py`를 감쌌다.

| 엔드포인트 | 상태 |
|---|---|
| GET /runs · /runs/{id}/gate · /items · /corpus | ✅ 조회(테이블 그대로 직렬화) |
| POST /items/validate | ✅ 필드별 오류(E6) — 코퍼스 존재·중복 질문·개인정보 |
| POST /apply | ✅ 버전 스냅샷 + 재측정 run 생성 + **재측정 실행**을 한 트랜잭션(E7) — 서버 재검증 포함(§2) |
| POST /candidates | ✅ 대화 로그 → 후보(sentinel 버전 'candidate') |

문항 목록·재측정 대상은 골든셋에서 온다: `testset_items` 가 비어 있으면 `evaluation_dataset`
(is_active)을 **버전 1** 로 씨딩한다(`_bootstrap_if_empty`, 조회/반영 진입에서 지연 실행).
held-out `test_set` 은 편집 대상이 아니라 얼려 둔 벤치마크라 씨딩하지 않는다.
| PUT /api/admin/drafts/{screen} | ✅ 자동저장(활동 로그 안 남김) — version 갭(§4) |

## 1. 게이트·지표는 서버가 못 박는다 (E1·E2·E4·E10)

- 목표값 정본 = `admin_evaluations.GATE_CRITERIA`(0.92↑/0.80↑/99.5%↑/10초↓/30of30).
  프론트 상수로 박으면 '관리자 화면에서 기준을 낮추는 우회'가 뚫린다 — 반드시 서버가 내려준다.
- `compute_gate()`가 **passed 와 기준별 판정을 함께** 계산해 `evaluation_runs.gate`(JSONB)에
  담고, 목록(GET /runs)과 상세(GET /gate)가 그 한 값을 읽는다(어긋남 방지).
- `metrics`는 [{label, value}] 배열이고 value 는 반올림까지 끝낸 문자열(점수 3자리·퍼센트
  1자리·초 1자리). **생성 성공률(generation_success_rate)을 넣는다** — 환각률로 대체하지 않는다.

## 2. apply 재측정은 한 트랜잭션에서 실제로 실행된다 (E7)

`POST /apply`는 한 트랜잭션·한 커밋으로 (1) 새 버전 스냅샷을 testset_items 에 쌓고 (2) 재측정
run 을 만들고 (3) **재측정을 실제로 실행**한다(`_measure`). 실패하면 버전 반영까지 롤백해
'측정 안 된 버전'이나 영구 RUNNING 이 남지 않는다. 응답은 `{testset_version, rerun_id}`.

- `_measure` 는 src/eval 채점을 **감싸기만** 한다(새로 짜지 않음): 검색은 `eval_retrieval`,
  생성은 `eval_pipeline_generation.evaluate_generation`(출처 정확률·OOS 거절·must_include·실패
  기록 포함 — 이번에 재사용 가능한 함수로 추출). 문항별 결과를 **evaluation_results 에 적어**
  item_count(GET /runs)·failed_items(GET /gate)의 원천을 남긴다.
- ⚠️ 측정은 문항 수만큼 OpenAI·HCX 를 부르는 **수 분짜리 작업**이라 apply 요청이 그만큼 오래
  걸린다. 현재 팀에 워커(Redis·ARQ 예정)가 없어 동기로 돈다. 워커가 서면 apply 는 run 을
  RUNNING 으로 남기고 마감을 워커에 넘기는 방식으로 바꾼다 — 그 마감 진입점이 이미 있는
  `run_evaluation(db, run_id)`(내부적으로 같은 `_measure` 를 부르고 커밋)이다. CLI 로도 부를 수 있다.

## 3. 문항 스냅샷 방식

testset_items 는 **버전 단위로 행을 쌓는다**(schema_admin 주석). apply 는 현재 버전 문항을
새 버전으로 복제하며 edits/excludes/adds 를 적용한다. 제외는 행을 지우지 않고
`excluded=true`+`exclude_reason`으로 표시한다(왜 뺐는지가 다음 버전에서 필요). 버전이 바뀌면
문항의 UUID(item_id)도 새로 발급되므로 프론트는 apply 후 목록을 다시 불러온다.

## 4. 🔴 팀·프론트 조치가 필요한 갭

### 4-A. testset_items 에 intent·question_type 컬럼이 없다
편집용 `testset_items`에는 두 컬럼이 없다(원본 `evaluation_dataset`에만 있다). 그래서:
- **GET /items**: `question_type`·`intent`를 **null**로 낸다(지어내지 않는다 — 로그 화면과 같은
  원칙). 프론트 타입은 non-null 이므로 조율 필요(null 수용 또는 컬럼 추가 후 채움).
- **POST /apply·/candidates**: 입력에 실려 온 intent·question_type 을 **저장하지 못한다**(버려짐).

→ **제안(실행 금지, 이번 주 범위 밖)**: `testset_items`에 컬럼 2개 추가.
```sql
ALTER TABLE testset_items ADD COLUMN question_type TEXT;
ALTER TABLE testset_items ADD COLUMN intent TEXT;
```
그 뒤 `_item_to_dict`/`_input_to_row`(admin_evaluations.py)에서 null 대신 실제 값을 쓰면 된다.
`testset_items`는 2026-08-12 신설이라 아직 비어 있어 추가 부담이 낮다 — 그래도 마이그레이션은
스키마 권한자가 한 커밋으로 돌린다.

### 4-B. admin_drafts 에 저장 횟수 카운터가 없다
자동저장 응답 `{screen, saved_at, version}`의 version 을 프론트가 기대하는데, `admin_drafts`는
이력을 남기지 않는 임시 보관 테이블이라 저장 횟수 컬럼이 없다. 지금은 **version=1 고정**으로
내보낸다(content 저장 자체는 정확하다).

→ **제안(실행 금지)**: 정확한 카운터가 필요하면 컬럼 추가.
```sql
ALTER TABLE admin_drafts ADD COLUMN save_count INTEGER NOT NULL DEFAULT 0;
```
upsert 시 `save_count = admin_drafts.save_count + 1`로 올리고 그 값을 version 으로 내보낸다.
version 이 UI 표시용 카운터일 뿐이면(정확도가 중요치 않으면) 현행 1 고정도 무방하다 —
프론트와 합의할 것.

## 5. 출처(RUN_SOURCES) 어휘
apply 재측정 run 은 `source='파이프라인 후속'`으로 기록한다(RUN_SOURCES 4종 중 가장 가깝다).
'평가셋 반영 후 재측정'에 딱 맞는 값이 사전에 없다(E9) — 고정 코드값이 정해지면 맞춘다.
