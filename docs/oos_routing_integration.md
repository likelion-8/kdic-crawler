# KDIC RAG OOS 라우팅 통합

현재 OOS 경로는 `src/oos_routing.py`가 정본이다. CLI(`src/pipeline.py`)와 웹 SSE
(`api/rag/answer.py`, `api/rag/sse.py`)가 같은 게이트 계약을 사용한다.

## 실행 순서

1. `src/eval/eval_pipeline_generation.py`로 현재 held-out 기준선을 측정한다. 결과의
   `oos_적절거절률`, `인스코프_오거절률`, `effective_params`를 보존한다.
2. 검색 Top5가 있는 경우에만 Context Supervisor가 질문·근거·Scope KB를 보고
   `ANSWERABLE`, `OOS`, `INSUFFICIENT_EVIDENCE` 중 하나를 반환한다. OOS와 근거부족은
   서로 다른 고정 안내문을 사용하며, 둘 다 답변 생성 LLM을 호출하지 않는다.
3. 기준선과 supervisor 단독 결과를 비교한 뒤, `min_route_cosine_score`를 821개
   인스코프 질문에서 오차단 0인 지점으로 조정한다. 애매한 점수는 항상 통과시킨다.
4. GPU에서 리랭커를 재판정하고 `min_rerank_top1_score`를 인스코프/OOS 분포로
   측정한다. 리랭커가 Off이면 이 게이트와 모델 호출 모두 실행되지 않는다.

## 런타임 파라미터

| 이름 | 기본값 | 역할 |
|---|---:|---|
| `min_top1_score` | `0.35` | 기존 임베딩 검색점수 게이트 |
| `min_route_cosine_score` | `0.0` | 1-NN 라우팅 코사인 극단값 게이트; 실측 전 비활성 |
| `min_rerank_top1_score` | `-100.0` | cross-encoder 로짓 게이트; GPU 실측 전 비활성 |
| `use_reranker` | `false` | GPU 리랭커 사용 여부 |
| `use_context_supervisor` | `true` | Top5·Scope KB 기반 3-way supervisor 사용 여부 |

세 임계값은 코드 호출부에 고정하지 않고 `runtime_config.get_param()`으로 읽는다.
관리자 화면에서 값을 바꾸면 `rag_param_versions`의 current 값이 TTL 이후 또는
관리자 반영 직후 같은 프로세스에서 적용된다.

## 장애 시 동작

- 룰/게이트 신호를 계산하지 못하면 다음 단계로 통과한다.
- Context Supervisor가 호출되지 않거나 구조화 출력이 실패하면 `ANSWERABLE`로
  fail-open해 기존 생성 경로를 보존한다.
- 검색점수 게이트가 근거를 전멸시킨 경우에는 supervisor를 호출하지 않고 OOS로
  종료한다.

Grounding Verifier(`source_check.py`)는 생성 후 환각 대응 트랙이므로 이 캐스케이드와
분리해 계속 측정한다.
