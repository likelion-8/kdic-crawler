# KDIC 검색기 평가 — 확장 통합 테스트셋 (580건)

> 개인 테스트셋 5종을 페이지당 3→10문항으로 확장·통합한 `testset_all.jsonl`(580건) 기준 재평가.
> 재현: `python3 src/eval_retrieval.py` (selftest 포함, 첫 실행 시 bge-m3 로딩).
> 이전 baseline(169문항)은 [`retrieval_experiment_results.md`](./retrieval_experiment_results.md) 참고 — 청크 크기 스윕·제품 권고는 그 문서에 있으며 여기선 재실행하지 않음.

## 실험 설계

- **코퍼스** `data/corpus.jsonl` 58 페이지(문서 1개 = 페이지 1개)
- **평가셋** `data/testset/testset_all.jsonl` **557 질문**(out_of_scope 23건 제외, 총 580건) + `testset_tail_probe.jsonl` 꼬리 프로브 4문항
- **검색기** BM25(kiwi 형태소) · Dense(bge-m3, 코사인) · Hybrid(RRF c=60)
- **색인 단위** `page`(통짜) / `faq_atomic`(FAQ→QA쌍) / `table_row`(표→3행 묶음) / `all`(FAQ+표)
- **지표** 문서찾기 MRR(정답 `page_id`가 상위에 있나) · AnswerRecall@5(top-5 유닛을 6000자로 이어붙인 컨텍스트에 `must_include`가 있나)
- **유형 분포(557건)** fact 358 · table_lookup 80 · faq 65 · link_guide 37 · file_download 17

## [1] 문서찾기 MRR (검색기 × 색인 단위)

| 검색기 | page | faq_atomic | table_row | all |
|---|---|---|---|---|
| BM25 | 0.570 | **0.711** | 0.624 | 0.685 |
| **Dense** | 0.718 | 0.719 | 0.723 | **0.724** |
| Hybrid | 0.682 | **0.730** | 0.695 | 0.720 |

## [2] Dense 유형별 MRR (색인 단위별)

| 유형 | page | faq_atomic | table_row | all |
|---|---|---|---|---|
| fact (358) | 0.705 | 0.670 | **0.708** | 0.678 |
| table_lookup (80) | 0.854 | 0.827 | **0.866** | 0.834 |
| **faq (65)** | 0.696 | **0.926** | 0.716 | **0.928** |
| link_guide (37) | 0.514 | **0.520** | 0.516 | 0.518 |
| file_download (17) | **0.889** | 0.859 | 0.860 | 0.831 |

## [3] AnswerRecall@5 전체 (정답이 컨텍스트 6000자에 포함?)

| 검색기 | page | faq_atomic | table_row | all |
|---|---|---|---|---|
| BM25 | 0.643 | 0.804 | 0.722 | **0.813** |
| **Dense** | 0.844 | **0.849** | 0.819 | 0.828 |

## [4] AnswerRecall@5 — 꼬리 프로브 4건 (잘린 표 꼬리 겨냥)

| 검색기 | page | faq_atomic | table_row | all |
|---|---|---|---|---|
| BM25 | 0.000 | 0.000 | 0.000 | 0.000 |
| **Dense** | 0.000 | 0.000 | **1.000** | **1.000** |

---

## 확장 전후 비교 (169문항 → 557문항)

문서찾기 MRR 주요 셀 변화:

| 항목 | 169문항 | 557문항 | Δ |
|---|---|---|---|
| BM25 · page | 0.534 | 0.570 | +0.036 |
| BM25 · faq_atomic | 0.691 | 0.711 | +0.020 |
| Dense · page | 0.752 | 0.718 | **-0.034** |
| Dense · all | 0.759 | 0.724 | **-0.035** |
| Hybrid · faq_atomic | 0.734 | 0.730 | -0.004 |

유형별 Dense MRR(대표 셀):

| 유형 | 169문항 | 557문항 |
|---|---|---|
| faq (faq_atomic) | 0.952 | 0.926 |
| table_lookup (table_row) | 0.876 | 0.866 |
| link_guide (page) | 0.586 | 0.514 |
| file_download (page) | 1.000 | 0.889 |

**해석**: 확장 테스트셋에서 Dense MRR이 소폭 하락(-0.03)했다. 성능이 나빠진 게 아니라, **표본이 3→10배로 늘며 난이도가 다양해져 추정치가 낙관 편향에서 내려온 것**이다. 특히 file_download가 7→17건으로 늘자 1.000→0.889로 떨어졌는데, 7건일 때의 완벽 점수는 표본이 작아 생긴 착시였다. link_guide도 17→37건에서 0.586→0.514로, 이 유형이 검색기 공통 약점임이 더 또렷해졌다. **개수 확장의 실질 효과 = 지표의 안정성·판별력 향상**(앞선 "개수↑=정밀도?" 논의와 일치).

## 핵심 관찰

1. **Dense 우위·청킹 둔감**은 확장 후에도 유지(MRR ~0.72). BM25는 여전히 청킹 민감(page 0.570 → faq_atomic 0.711).
2. **faq 청킹 효과 재확인**: faq 유형 Dense MRR이 page 0.696 → faq_atomic/all **0.926~0.928**로 급등.
3. **link_guide가 최약 유형(~0.51)** — 표본 확대로 신뢰도 있게 드러남. 링크 안내 질문 검색 개선이 다음 레버리지.
4. **꼬리 프로브 결론 불변**: 잘린 표 꼬리는 page/faq 청킹에선 Dense도 0.000, **table_row/all에서만 1.000**. 큰 표는 행 단위 청킹 필수.

## 산출물

| 파일 | 역할 |
|---|---|
| `data/testset/testset_all.jsonl` | 통합 평가셋 580건(557 검색평가 + 23 out_of_scope) |
| `src/eval_retrieval.py` | Recall@k·MRR·AnswerRecall + selftest |
| `data/testset/testset_tail_probe.jsonl` | 꼬리 겨냥 프로브 4문항 |
