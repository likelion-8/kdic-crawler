# KDIC 검색기 실험 종합 결과 (BM25 · Dense · Hybrid)

> KDIC 챗봇 검색 단계의 baseline 구축 및 청킹 처치 A/B 실험. `feature/retrieval-eval` 브랜치.
> 재현: `python3 src/eval_retrieval.py` (selftest 포함, 첫 실행 시 bge-m3 다운로드).

## 실험 설계

- **코퍼스** `data/corpus.jsonl` 58 페이지(문서 1개 = 페이지 1개)
- **평가셋** `data/testset/testset_all.jsonl` 169 질문(out_of_scope 제외) + `testset_tail_probe.jsonl` 꼬리 프로브 4문항
- **검색기** BM25(kiwi 형태소) · Dense(bge-m3, 코사인) · Hybrid(RRF c=60)
- **색인 단위** `page`(통짜) / `faq_atomic`(FAQ→QA쌍) / `table_row`(표→3행 묶음, 헤더 반복) / `all`(FAQ+표)
- **지표**
  - **문서찾기**: Recall@k, MRR (정답 `page_id`가 상위에 있나)
  - **답 뽑기**: AnswerRecall@5 (검색된 top-5 유닛을 6000자로 이어붙인 컨텍스트에 `must_include`가 실제로 있나)

## [1] 문서찾기 MRR (검색기 × 색인 단위)

| 검색기 | page | faq_atomic | table_row | all |
|---|---|---|---|---|
| BM25 | 0.534 | **0.691** | 0.588 | 0.663 |
| **Dense** | **0.752** | 0.755 | 0.752 | **0.759** |
| Hybrid | 0.695 | 0.734 | 0.693 | 0.716 |

## [2] Dense 유형별 MRR (색인 단위별)

| 유형 | page | faq_atomic | table_row | all |
|---|---|---|---|---|
| fact (100) | 0.744 | 0.704 | 0.735 | 0.705 |
| table_lookup (24) | 0.861 | 0.833 | **0.876** | 0.856 |
| **faq (21)** | 0.717 | **0.952** | 0.719 | **0.952** |
| link_guide (17) | 0.586 | 0.604 | 0.581 | 0.599 |
| file_download (7) | 1.000 | 1.000 | 1.000 | 1.000 |

## [3] AnswerRecall@5 전체 (정답이 컨텍스트 6000자에 포함?)

| 검색기 | page | faq_atomic | table_row | all |
|---|---|---|---|---|
| BM25 | 0.574 | 0.698 | 0.675 | **0.740** |
| Dense | **0.805** | 0.822 | 0.793 | 0.799 |

## [4] AnswerRecall@5 — 꼬리 프로브 (잘린 표 꼬리 겨냥)

| 검색기 | page | faq_atomic | table_row | all |
|---|---|---|---|---|
| BM25 | 0.000 | 0.000 | 0.000 | 0.000 |
| **Dense** | **0.000** | 0.000 | **1.000** | **1.000** |

---

## 핵심 결론

1. **Dense(bge-m3)가 문서찾기 최강** (MRR 0.752). 한국어 자연어 질문엔 의미매칭 > 어휘매칭.
2. **청킹은 유형별 맞춤약.** FAQ 청킹 → faq만 0.717→**0.952**. 표 청킹 → table_lookup만 0.861→0.876.
3. **순진한 Hybrid(균등 RRF)는 항상 Dense보다 낮음** — 약한 BM25가 강한 Dense를 끌어내림. 가중 융합/유형 라우팅 필요.
4. **표는 "문서찾기"엔 청킹이 거의 불필요** — Dense가 통짜로도 표 페이지를 잘 찾음(0.861), table_row가 MRR을 안 올림.
5. **표 청킹의 진짜 가치는 "답 뽑기"에 있음 — [4]가 결정적.** 통짜 baseline은 잘린 표 꼬리 질문에 답을 하나도 못 냄(**0.000**). 3행 청킹으로 **1.000**. 문서찾기 MRR은 이 4문항에 멀쩡한 점수를 줘서 잘림 피해를 못 봄 → **두 지표가 정반대 결론.**
6. **트레이드오프:** 표를 잘게 쪼개면 꼬리 답은 0→1.0으로 완벽해지지만 Dense 전체 AnswerRecall은 소폭 하락(0.805→0.793). 작은 청크 = 유닛당 컨텍스트 감소. **꼬리 정밀도 ↔ 일반 컨텍스트 풍부함의 교환.**
7. **BM25는 꼬리 엔티티를 청킹해도 못 찾음(0.000)** — 회사명이 흔한 형태소로 쪼개져 변별력 상실. 엔티티 조회는 Dense 경로가 정답.

### 청크 크기 스윕 (꼬리 프로브 AnswerRecall, Dense)

| 행/청크 | 유닛 수 | 꼬리 AnswerRecall@5 |
|---|---|---|
| 40 | 81 | 0.250 |
| 10 | 163 | 0.250 |
| **3** | 417 | **1.000** |
| 1 | 1148 | 1.000 |

→ 3행/청크가 sweet spot (1.000 달성 + 유닛 폭증 억제). 기본값으로 채택.

## 방법론 메모

- **문서찾기 지표(MRR)는 잘림 피해에 눈멀어 있음.** 페이지 단위라 정답이 꼬리에서 잘려도 페이지만 찾으면 만점. 잘림/청킹 효과는 **AnswerRecall(답 단위)** 로만 보임.
- 꼬리 프로브 4문항은 `uc_bkrp_mng`(파산재단 표 493행)의 **잘림 경계(토큰 8192 ≈ 13,959자) 뒤에만 존재하는 회사**로 구성. baseline Dense가 임베딩 시 못 본 영역.
- `page` 모드는 리팩터 전 baseline 수치를 정확히 재현 → 델타는 순수 처치 효과.

## 제품 권고

| 처치 | 근거 | 결정 |
|---|---|---|
| FAQ atomic 청킹 | 문서찾기 faq MRR +0.235 | 즉시 도입 |
| 표 row-chunking (3행) | 꼬리 답 0.000→**1.000** (MRR엔 무효) | 답변 단계 필수 |
| Hybrid 가중/유형 라우팅 | 균등 RRF < Dense | faq=BM25, 그 외=Dense |
| 청크 크기 튜닝 | 꼬리 정밀도 ↔ 컨텍스트 교환 | 표=3행, 유형별 조정 |
| 노이즈 제거(dp_prdct_srch) | 효과 미검증 | 후속 |

## 산출물

| 파일 | 역할 |
|---|---|
| `src/retrieval.py` | BM25·Dense·Hybrid + PageRanked(유닛→페이지) |
| `src/chunking.py` | `build_units(mode)` — page/faq_atomic/table_row/all |
| `src/eval_retrieval.py` | Recall@k·MRR·AnswerRecall + selftest |
| `data/testset/testset_tail_probe.jsonl` | 꼬리 겨냥 프로브 4문항 |
