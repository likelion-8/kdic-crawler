# experiments/ — 결정의 근거가 된 실험 스크립트

운영 파이프라인(`src/`·`api/`)이 **import 하지 않는** 일회성 실험·측정 스크립트를 모아 둔 곳이다
(2026-08-31 정리, 종전 위치 `src/crawler/`·`src/eval/`). 지우지 않고 옮긴 이유: 리랭커 OFF,
Gate 2 임계값 0.66, 플래너 모델 선택, FAQ 청킹 방식 같은 **현재 설정값 하나하나가 이 스크립트의
측정 결과로 정해졌다.** 결과 문서(`docs/*.md`)의 수치를 재현하려면 이 코드가 필요하다.

실행은 전부 리포 루트에서: `.venv/Scripts/python.exe experiments/<파일>.py`
(각 스크립트가 `sys.path` 에 `src/`·`src/crawler/` 를 넣으므로 옮겨도 import 는 그대로 된다).
LLM·임베딩을 부르는 것은 비용·시간이 든다 — 파일 상단 docstring 을 먼저 읽을 것.

| 그룹 | 스크립트 | 무엇을 정했나 | 결과 문서 |
|---|---|---|---|
| 검색·임베딩 | `eval_retrieval.py` | 검색기 공통 평가 함수(Recall@k·MRR·AnswerRecall). 아래 여러 실험이 import | `docs/retrieval_eval.md` |
| | `eval_embeddings.py` | 임베딩 모델 후보 비교 → **bge-m3-ko 채택** | `docs/embedding_model_comparison.json` |
| | `route_eval.py` | BM25/Dense/Hybrid 유형별 비교 → 라우팅 규칙 | `docs/pipeline_issue_history.md`, `docs/retrospective.md` |
| | `eval_routing_value.py` | "link_guide 만 Hybrid" 규칙 재검증 | (docstring) |
| | `bf_score_fusion_eval.py` | RRF 대신 점수 직접결합 실험 → 미채택 | `docs/retrospective.md` |
| | `measure_baseline.py` | 단계별 지연 프로파일 | `docs/pipeline_latency_profile.md` |
| 임계값 | `gate2_threshold_search.py` | Gate 2 임계값 그리드서치 → **0.66** | `docs/gate2_domain_filter.md` |
| | `gate2_ab_comparison.py` | Gate 1 단독 vs Gate 1+2 | `docs/gate2_domain_filter.md` |
| | `min_top1_threshold_search.py` | 무관 질문 게이트(MIN_TOP1_SCORE) 재탐색 | `docs/min_top1_threshold_decision.md` |
| | `retrieval_gate_threshold_search.py` | 같은 게이트의 이전 측정판 | (docstring) |
| intent 분류 | `eval_intent_rules.py` / `eval_intent_morpheme.py` / `eval_intent_cosine.py` / `eval_intent_sibling.py` | 규칙·형태소·코사인·1-NN 형제효과 비교 → **LLM 분류 채택** | `docs/intent_classifier_comparison.md`, `docs/retrospective.md` |
| 청킹·프리픽스 | `eval_faq_chunk_format.py` | FAQ 청크 포맷 4변형 → 과잉 거절 판가름 | `docs/faq_format_experiments_2026-08-19.md` |
| | `eval_prefix_embedding.py` | [page_title · business_function] 프리픽스 A/B | (docstring) |
| | `eval_summary_prefix.py` | LLM 페이지 요약 프리펜드 파일럿 | `docs/faq_format_experiments_2026-08-19.md` |
| 플래너·분해 | `eval_query_decomposition.py` | HCX 복합 질문 분해 품질 | `docs/multiquery_decomposition.md` |
| | `eval_planner_split.py` | 플래너 분해 안정성(온도 1 반복) | `docs/query_planner_model_comparison.md` |
| 사후검증 | `eval_source_precheck_retro.py` / `eval_source_precheck_testset.py` | 프리체크(0콜 게이트) 소급·테스트셋 실험 — 채택 결정 대기(섀도 모드) | (docstring) |
| 비용 | `cost_audit/` (`extract_langfuse.py` → `cost_audit.py`) | 질문당 LLM 비용 실측(Langfuse × rag_runs) — 발표 수치 | `cost_audit/README.md` |
| 골든셋 | `validate_goldenset.py` / `validate_golden_labels.py` | 골든셋 자체 감사(근사중복·라벨 충돌·커버리지) | `results/goldenset_audit/`, `docs/retrospective.md` |

정기 평가(held-out 89문항)는 실험이 아니라 운영 도구라 `src/eval/eval_pipeline_retrieval.py`·
`eval_pipeline_generation.py` 에 그대로 있다. 관리자 화면의 평가(AD-006)도 그쪽을 쓴다.
