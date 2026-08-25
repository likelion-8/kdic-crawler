# Gate 2 — 임베딩 유사도 기반 도메인 판정 게이트 (2026-08-19)

Gate 1(룰 기반, `src/gate1.py`) 뒤·쿼리 플래너 앞에 추가한 두 번째 OOS 필터. Gate 1이 놓친
out-of-domain 중, 참조 사전과의 임베딩 유사도로 "확실하다"고 판단되는 경우만 추가로 고정
응답 후 종료(EXIT)한다. 4단계 캐스케이드(Gate 1 룰 → **Gate 2 임베딩** → Gate 3 크로스인코더
[미구현] → Gate 4 Supervisor LLM[미구현]) 중 두 번째 단계이며, Gate 1과 마찬가지로 하드
블록이 가능한 유일한 두 게이트다(Gate 3·4는 신호만 넘기는 설계).

## 설계 원칙

**정밀도 우선** — Gate 1과 동일한 철학. OOS를 많이 잡는 것(recall)이 아니라 정상 질문을
잘못 차단하지 않는 것(precision)이 유일한 목표. 애매하면 무조건 CONTINUE.

**개별 문장 벡터, centroid 아님** — 참조 사전(`config/gate2_reference.json`)의 클러스터
안 문장을 평균 내 대표 벡터 하나로 뭉치지 않는다. 문장 하나하나를 독립 벡터로 저장하고,
판정 시 전체 참조 벡터 중 최댓값(nearest neighbor)을 쓴다. 이 방식에서는 짧은 단어("커피")와
긴 문장("집에서 커피 맛있게 내리는 법 알려줘")을 같은 클러스터에 섞어도 서로 평균으로
희석되지 않는다 — 그래서 커버리지를 넓히려 짧은 단어형 항목을 섞어 넣는 것이 기존 항목의
판정 정확도를 깎지 않는다(2026-08-19 팀 확인).

## 판정 로직

```
s_id  = max cos(q, in_domain 참조 벡터)   # 질의와 가장 가까운 in_domain 예시 유사도
s_ood = max cos(q, out_of_domain 참조 벡터)
block = (s_ood >= threshold) AND (s_ood > s_id)
```

`threshold` 단독이 아니라 `s_ood > s_id` margin 비교를 함께 요구한다 — 인접도메인 어휘
(신용등급·대출 상담 등)가 out_domain 참조와 표면적으로 가까워 `s_ood`가 높게 나와도, 그
질문이 실제 도메인 코퍼스와 더 가깝다면(`s_id`가 더 크면) 오차단하지 않기 위한 안전장치.

## 참조 사전 구성 (`config/gate2_reference.json`)

- `in_domain`: business_function 6종(예금자보호제도/착오송금 반환 신청/고객 미수령금 신청/
  채무조정 안내/예금보험금 안내/은닉재산 신고)과 1:1로 대응하는 6클러스터, 각 10문항(총 60).
- `out_of_domain`: 4카테고리(일상잡담/인접도메인/개인정보상담요청/프롬프트인젝션) × 2클러스터,
  총 78문항. 일상잡담·인접도메인 등 클러스터에는 완성 문장 외에 3~5개씩 짧은 명사(구)형 항목
  ("커피", "영화", "종합소득세" 등)을 섞어 짧은 입력에 대한 판정 커버리지를 넓혔다.
- `threshold`(0.66)·`decision_rule`도 이 파일에 함께 저장 — **하드코딩 금지**, 항상 config에서
  읽는다.

## 벡터 캐시 (`data/gate2_cache/`, `src/crawler/build_gate2_reference.py`로 생성)

- `in_domain_emb.npy` / `out_domain_emb.npy` — 참조 문장 개별 임베딩(dragonkue/BGE-m3-ko,
  `retrieval.py`와 동일 모델·`normalize_embeddings=True`).
- `manifest.json` — 버전·모델명 + 각 벡터 행에 대응하는 (cluster_id, business_function/category,
  question) 메타데이터.
- **캐시 로드 실패(파일 없음·손상·config 버전 불일치)는 서버를 죽이지 않는다** — `src/gate2.py`가
  경고 로그만 남기고 이후 모든 요청에서 항상 CONTINUE로 폴백한다(Gate 2를 건너뛰고 파이프라인은
  그대로 진행).

## Threshold 결정 (`src/crawler/gate2_threshold_search.py`)

held-out 테스트셋 `data/testset/testset_gate2_domain_eval.jsonl`(143문항, 4그룹 —
clear_in_domain 40 / boundary_in_domain 38 / clear_out_domain 35 / boundary_out_domain 30)으로
0.30~0.90 그리드서치. in_domain 두 그룹(clear/boundary) 오탐률이 모두 0%인 후보 중
out_domain 차단율이 가장 높은 지점을 채택했다.

| threshold | clear_in 오탐 | boundary_in 오탐 | clear_out 차단 | boundary_out 차단 |
|---|---|---|---|---|
| **0.66(채택)** | 0.0% | 0.0% | 57.1% | 6.7% |
| 0.76 | 0.0% | 0.0% | 34.3% | 0.0% |

`boundary_in_domain`(도메인 핵심 키워드만 짧게 입력한 경우 등, 오차단 시 안전 문제가 되는
핵심 검증 그룹)과 `clear_in_domain` 모두 0.66에서 오차단 0건 — 상세는
`data/gate2_cache/threshold_search_report.json`.

**인접도메인 어휘 중첩 특별 검증**: `boundary_in_domain` 중 채무조정/신용/대출 계열 키워드가
섞인 7건 전수 점검 결과 threshold=0.66에서 전부 정상 통과(오차단 0건) — out_domain 참조의
"신용등급"·"대출 상담" 같은 짧은 항목이 경계선 채무조정 질문을 잘못 밀어내는 현상은 실측상
발생하지 않았다.

## Gate 1과의 A/B 비교 (`src/crawler/gate2_ab_comparison.py`)

Gate 2는 Gate 1 뒤에 위치하므로(Gate 1이 EXIT하면 Gate 2는 평가되지 않음) 진짜 기여도는
"전체 차단율"이 아니라 **Gate 1이 놓친 질문 중 Gate 2가 추가로 잡아내는 증분**이다.

| 그룹 | A: Gate1만 | B: Gate1+Gate2 | Gate2 증분 |
|---|---|---|---|
| clear_in_domain | 0.0% | 0.0% | 0.0% |
| boundary_in_domain | 0.0% | 0.0% | 0.0% |
| clear_out_domain | 11.4% | 60.0% | **+48.6%p** |
| boundary_out_domain | 0.0% | 6.7% | +6.7%p |

Gate 1 룰에 없는 카테고리(세금/인접기관/개인정보 대행 요청 등)를 Gate 2가 대량으로 추가
차단하면서도 in_domain 두 그룹은 A/B 모두 오차단 0건 — 안전 유지 확인. 상세는
`data/gate2_cache/ab_comparison_report.json`.

## 고정 응답 — 카테고리 비노출

외부 응답 문구는 판정된 카테고리(일상잡담/인접도메인/개인정보상담요청/프롬프트인젝션)와
무관하게 전부 동일하다 — Gate 1의 `resp_out_of_domain`을 그대로 재사용한다
(`api/rag/answer.fixed_gate_response`, Gate 1·Gate 2 공용). 어떤 카테고리·클러스터로
판정됐는지는 내부 로그(trace 메타데이터, `gate2_nearest_category` 등)에만 남기고 사용자에게는
노출하지 않는다 — 특히 "프롬프트인젝션으로 판정됨" 사실 자체를 절대 노출하지 않는다.

## 파이프라인 통합

- 웹(`api/rag/sse.py`): 가드레일 → **Gate 1**(원문) → 재작성(후속 턴) → 캐시 → **Gate 2**(재작성문)
  → 쿼리 플래너 순(2026-08-25 Gate 1 을 재작성·캐시 앞으로 이동). 웹은 ambient
  trace가 없어(threadpool 소비) `record_trace` 메타데이터로 Gate 2 결과를 남긴다.
- CLI(`src/pipeline.rag_answer`): Gate 1 → **Gate 2** → 기존 흐름. `@observe`로 열린 trace
  아래 `gate1_rulebase` → `gate2_embedding` span을 남긴다(`record_gate2_span`,
  `src/observability.py`).

## 관련 파일

| 파일 | 역할 |
|---|---|
| `config/gate2_reference.json` | 참조 사전 + threshold + decision_rule |
| `data/gate2_cache/*.npy`, `manifest.json` | 참조 벡터 캐시(빌드 산출물) |
| `data/testset/testset_gate2_domain_eval.jsonl` | held-out 평가셋(143문항) |
| `src/gate2.py` | 판정 로직(`run_gate2`), 캐시 로드+안전 폴백 |
| `src/crawler/build_gate2_reference.py` | 참조 사전 → 벡터 캐시 빌드 |
| `src/crawler/gate2_threshold_search.py` | threshold 그리드서치 |
| `src/crawler/gate2_ab_comparison.py` | Gate1 단독 vs Gate1+Gate2 비교 |
