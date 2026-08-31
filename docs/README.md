# docs/ 안내

이 폴더의 문서가 각각 무엇이고, 무엇부터 봐야 하는지 정리한 인덱스다.
**개별 문서를 요약하지 않는다** — 어디에 무엇이 있고 그 내용이 언제 기준인지만 적는다.

---

## 무엇부터 볼까 — 목적별 진입점

| 하려는 일 | 순서 |
|---|---|
| **처음 왔다 / 프로젝트가 뭔지 알고 싶다** | 루트 [`README.md`](../README.md)(P3 계획서) → [`CODEBASE.md`](CODEBASE.md)(실행 방법) → [`retrieval_eval.md`](retrieval_eval.md)(왜 이 검색 구조인지) |
| **파이프라인 코드를 고치러 왔다** | [`pipeline_issue_history.md`](pipeline_issue_history.md) **상단 "현재 상태 요약"** → 해당 이슈 절 |
| **API를 붙이거나 계약을 확인한다** | [`web/src/mocks/README.md`](../web/src/mocks/README.md)(계약 정본) → [`frontend-handoff.md`](frontend-handoff.md) → [`backend-structure.md`](backend-structure.md) |
| **데이터·코퍼스를 만진다** | [`metadata_schema.md`](metadata_schema.md) → [`CODEBASE.md`](CODEBASE.md) → [`search_scope_definition.md`](search_scope_definition.md) |
| **왜 이렇게 결정했는지 알고 싶다** | [`retrospective.md`](retrospective.md) → 각 실험 문서 |
| **프론트를 띄워본다** | [`web/README.md`](../web/README.md) |

> ⚠️ **`pipeline_issue_history.md`는 802줄이다.** 앞부터 읽으면 지금 코드와 정반대 결론을
> 얻는다(이슈 5의 결정이 이슈 5-A에서 뒤집힌다). **반드시 상단 요약 표를 먼저 본다.**

---

## 문서는 세 종류다

이번 정리에서 문제가 됐던 것이 전부 ①과 ②가 안 갈려서 생겼다. 새 문서를 쓸 때도 셋 중
어디에 속하는지 먼저 정하면 된다.

| | 종류 | 성격 |
|---|---|---|
| ① | **Current** | 현재 코드·구조를 설명한다. **코드가 바뀌면 같이 고쳐야 한다.** |
| ② | **Historical** | 그때 그렇게 측정·판단했다는 기록. **고치지 않는다.** 지금과 다르면 그건 오류가 아니라 이력이다 |
| ③ | **Generated** | 스크립트가 만든다. **직접 편집 금지** — 다음 실행에 덮어쓰인다 |

---

## ① Current — 코드와 함께 최신을 유지할 문서

| 문서 | 무엇이 있나 | 언제 기준 |
|---|---|---|
| [`CODEBASE.md`](CODEBASE.md) | P1 데이터 파이프라인(`src/crawler/`) 온보딩. 단계별 파일 표, 데이터 산출물, **파이프라인 실행 커맨드 정본**(운영 절차는 `admin_account_setup.md`) | 2026-08-05 · Supabase 전환 반영됨. ⚠️ P2 RAG 코어·`api/`·`web/`은 다루지 않는다 |
| [`metadata_schema.md`](metadata_schema.md) | `corpus.jsonl`(58) · `chunks_all.jsonl`(494) · `testset_all.jsonl`(851) 필드 정의. **필드 정본** | 2026-08-05 |
| [`search_scope_definition.md`](search_scope_definition.md) | 6개 업무 × 58페이지 카탈로그(브레드크럼·URL·요약) | 2026-08-05 · ⚠️ 업무 필터는 2026-07-22에 껐다(문서 상단 참고) |
| [`pipeline_issue_history.md`](pipeline_issue_history.md) | **상단 요약 = Current**(코드 대조 11행), 본문 = Historical(이슈 1~6 + 5-A·5-B 이력) | 요약은 2026-08-07 코드 대조 · 본문은 07-23~08-04 |
| [`backend-structure.md`](backend-structure.md) | FastAPI 구조 개선안. **§3 함정 28건**, §6 프로세스 모델(bge-m3 2GB·`--workers 1`·`async def` 금지) | 2026-08-05 작성 + 08-07 현황 주석. §1의 처방 3건은 처리됨(그 표 참고) |
| [`frontend-handoff.md`](frontend-handoff.md) | 프론트→백엔드 인수인계. **§6 프론트가 정한 계약 108행**, §5 DB 테이블 현황, §7 못 만든 것 8건 | 2026-08-03 작성 + 08-07 현황 갱신. **계약은 유효**, 현황 서술만 시점 차이 있음 |
| [`search_index_versioning.md`](search_index_versioning.md) | 재적재 버전 관리 결정. **왜 청크가 아니라 입력 스냅샷인지**, 활성 전환·롤백 흐름, 설계가 성립하려면 지켜야 할 전제 2개, 근거로 쓰면 안 되는 주장 2건 | 2026-08-10 결정 · 워커 구현은 3주차 |
| [`admin_account_setup.md`](admin_account_setup.md) | 관리자 계정 생성·비밀번호 변경 절차(운영 런북). 손으로 치면 깨지는 값 2개(`status`·`role`), 검증 명령 | 2026-08-10 · ⚠️ 계정 관리 API(AD-010)가 생기면 폐기한다(§6) |

---

## ② Historical — 그때의 측정·판단. 고치지 않는다

| 문서 | 무엇이 있나 | 언제 기준 |
|---|---|---|
| [`retrieval_eval.md`](retrieval_eval.md) | 검색기 3종 × 색인 단위 4종 비교. 169문항·557문항 두 규모, 확장 전후 비교, **청크 크기 스윕(3행 채택 근거)**, 제품 적용 결정 | 측정 2026-07-15(169) · 07-16(557) · 08-07 두 문서 병합 |
| [`pipeline_heldout_baseline_89q.md`](pipeline_heldout_baseline_89q.md) | held-out 89문항 정식 평가(Recall@5 0.922 · MRR 0.806). **dev 평가 vs 최종 test 평가 원칙**이 여기에만 있다 | 측정 2026-07-30 · 리랭킹 Off |
| [`intent_classifier_comparison.md`](intent_classifier_comparison.md) | intent 분류 4자 비교(TF-IDF/HCX-007/gpt-4o-mini/gpt-5.4-mini), 채택 근거, **데이터 국외 이전 검토** | 실험 2026-08-02 · 코드 반영은 08-03 완료(§7) · ⚠️ 부록 산출물 대부분은 저장소에 없다 |
| [`multiquery_decomposition.md`](multiquery_decomposition.md) | 복합 질문 분해 1차(규칙, 폐기) vs 2차(항상-LLM, 채택). ⚠️ **§7의 "현재 설계 명세"는 2026-08-09 쿼리 플래너로 교체됐다** — 상단 「현재 상태」 절을 먼저 볼 것. 본문은 `USE_QUERY_PLANNER=False` 폴백 경로 명세로 유효 | 본문 2026-08-03 · 상단 현재 상태 08-09 |
| [`query_planner_model_comparison.md`](query_planner_model_comparison.md) | 멀티쿼리+intent를 **한 번의 structured-output 호출**로 합치는 쿼리 플래너의 3모델 비교(HCX-007 / gpt-5.4-mini / gpt-5.6-luna, 100문항 joint). 채택 근거·현행 대비 개선폭 | 실험 2026-08-07 · 코드 반영 08-09(`28ab749`) |
| [`query_planner_token_waste.md`](query_planner_token_waste.md) | 교체 **직전** 방식(HCX 분해 + 하위질문마다 별도 intent)의 토큰 낭비 실측. false split·단일 질문 분해 오버헤드·출처 재확인 비중(29%) | 측정 2026-08-07 · 위 비교 문서와 짝 |
| [`retrospective.md`](retrospective.md) | P1~P2 전체를 "무엇을 채택·폐기했나"로 재구성. **8장 반복 패턴**(초기 측정 불신·지표 하나만 보면 반대 결론·형제 질문 누수) | 2026-08-03 · 2.4 리랭커 절만 08-07 정정 |

---

## ③ Generated — 직접 편집 금지

| 문서 | 생성 주체 | 언제 기준 |
|---|---|---|
| [`pipeline_latency_profile.md`](pipeline_latency_profile.md) | `experiments/measure_baseline.py` (`write_text`로 통째 덮어씀) | 측정 2026-07-23 · **리랭커 ON 시절 값**이라 현재 동작이 아니다 |

⚠️ 이 파일을 다시 생성하면 수치가 그때 환경 기준으로 바뀐다. 여러 문서가 지금 값을 인용하고
있으므로 무심코 재실행하지 말 것.

---

## docs/ 안의 md 아닌 것

| 파일 | 무엇 |
|---|---|
| `pipeline.html` | 크롤러 데이터 파이프라인 시각 자료. ⚠️ "챗봇 응답 생성 계층은 비어 있습니다" 서술은 **P1 시점 기준**이며 지금은 생성 레이어·API·프론트가 다 있다 |
| `embedding_model_comparison.json` | 임베딩 4종(bge-m3 / bge-m3-ko / Qwen3-8B / Nemotron-8B) 비교 원본 결과. 유형별 MRR 포함. 요약은 `log/P2_report.md` 3장 |

## docs/ 밖 문서

| 위치 | 무엇 | 종류 |
|---|---|---|
| [`../README.md`](../README.md) | **P3 연구계획서**(관리자+웹 서비스화). README가 아니라 계획서다 | Current(계획) |
| `../log/P1_plan.md` · `P1_report.md` · `P2_plan.md` · `P2_report.md` | P1·P2 계획서와 결과 보고서 | Historical |
| `../log/0714~0806.md` | 일일 스탠드업 14개 | Historical |
| [`../web/README.md`](../web/README.md) | 프론트 실행 방법 · 목 시나리오 표 | Current |
| [`../web/src/mocks/README.md`](../web/src/mocks/README.md) | **API 계약 정본.** SSE 계약, 관리자 API 권한, 파이썬↔API 필드 매핑 | Current |
| `../infra/kdic-postgres-server/README.md` | 로컬 PostgreSQL+pgvector 도커 환경 | Current · ⚠️ 운영은 Supabase다. 이 로컬 환경을 지금 쓰는지는 문서만으로 판단 불가 |

---

## 문서 읽는 법

1. **`log/`는 정본이 아니다.** 일일 스탠드업은 그날의 작업 기록이고 요구사항의 원천이 아니다.
   실제로 코드 주석이 `log/0729.md 3항`을 근거로 인용해 버그를 만든 전례가 있다
   (`pipeline_issue_history.md` 이슈 4). 요구사항은 기획서·계약 문서에서 확인한다.
2. **현재 구현 상태는 코드를 우선한다.** 그다음이 `pipeline_issue_history.md` 상단 요약이고,
   산문 문서는 마지막이다. 인용하기 전에 `파일:줄`로 확인하는 습관을 들인다.
3. **과거 실험 결과와 현재 운영 설정은 다를 수 있다.** 예: 리랭커는 `USE_RERANKER=False`가
   현재값이지만 그 사유는 **CPU 속도**이고, 품질 효과는 아직 판정 보류다(측정 두 번이 엇갈렸다).
   "껐다"와 "효과 없다"를 같은 말로 읽지 않는다.
4. **수치를 인용할 때는 평가셋을 함께 적는다.** 같은 지표가 169 / 557 / 821 / 851문항 기준으로
   여러 번 측정됐다. 세트를 안 밝히면 다음 사람이 비교할 수 없다.
   (`testset_all.jsonl`은 현재 851건이라, 옛 문서의 재현 명령을 그대로 돌려도 그 수치가 안 나온다.)
5. **문서를 고칠 때는 과거 사실을 현재형으로 덮어쓰지 말고 "작성 당시 / 현재"를 분리한다.**
   당시 판단을 지우면 왜 그 길로 갔는지가 사라진다.
