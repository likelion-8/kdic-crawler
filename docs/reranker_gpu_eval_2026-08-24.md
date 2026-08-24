# 리랭킹(bge-m3 계열) GPU 실측 결과 — 2026-08-24

> **한 줄 결론: 리랭킹은 계속 Off.** 운영이 실제로 쓰는 지표(Recall@5 = K_FINAL)가 리랭킹을
> 켜도 그대로거나 더 나쁜데, 문항당 +8~9초가 붙는다. 다만 이번 측정에서 **게이트 임계값
> 스케일 버그**를 하나 찾았고, 재도입할 때 쓸 모델은 `dragonkue/bge-reranker-v2-m3-ko`로
> 정해뒀다.
>
> ⚠️ 원본 결과 JSON은 이번 세션의 GPU 인스턴스(`/home/ubuntu/kdic-crawler`)에 있다.
> 이 저장소에는 `results/pipeline_holdout/retrieval_rerank_off.json`만 들어와 있고,
> `retrieval_rerank_{on_baai,on_dragonkue,on_dragonkue_k10}.json`·
> `gate_score_compare_dragonkue.json`은 아직 옮겨오지 않았다.

---

## 1. 배경 — 왜 다시 쟀나

`candidate_ranking.py`에 리랭킹이 구현돼 있지만 `pipeline.py`의 `USE_RERANKER=False`로 꺼져 있었다.
**꺼둔 직접 사유는 CPU 속도**(문항당 27~210초)였고, **품질 효과는 표본 6문항이라 판정 보류** 상태였다.
즉 "품질에 도움이 안 돼서 껐다"가 아니라 "CPU에서 못 돌려서 껐다"였고, 품질 판정은 GPU 환경으로
미뤄둔 숙제였다.

이번에 **GPU(L4) 인스턴스를 확보**해 held-out 세트 전체로 그 숙제를 끝냈다.

### 테스트셋

| 파일 | 규모 | 용도 |
|---|---|---|
| `data/testset/testset_pipeline.jsonl` | 89행 (검색채점 79 / out-of-scope 10) | 검색 품질 |
| `data/testset/testset_gate2_domain_eval.jsonl` | 143행 (pass 78 / block 65, boundary 포함) | OOS 게이트 분리력 |

### 비교 조건

- **Off** — 1차 검색(hybrid) 순위 그대로
- **BAAI** — `BAAI/bge-reranker-v2-m3` (기존 코드에 박혀 있던 모델)
- **dragonkue** — `dragonkue/bge-reranker-v2-m3-ko` (같은 모델의 한국어 파인튜닝판, max_position 8194라 `max_length=8192` 그대로 호환)

---

## 2. 검색 품질 (K_CANDIDATES=20)

| 지표 | Off | BAAI/bge-reranker-v2-m3 | dragonkue/bge-reranker-v2-m3-ko |
|---|---|---|---|
| Recall@1 | 0.650 | 0.654 | **0.793** |
| Recall@3 | 0.888 | 0.890 | **0.922** |
| **Recall@5 (=K_FINAL, 운영 지표)** | **0.956** | 0.945 (↓) | 0.956 (동률) |
| MRR | 0.857 | 0.847 | **0.946** |
| ContextHit | 0.949 | 0.937 | 0.722 ⚠️ (4절 버그로 저평가된 수치) |
| 총 소요(79문항) | 427s | 1595s | 1611s |

### 읽는 법 — 왜 "개선됐는데 안 쓰나"

Recall@1(0.650 → 0.793)과 MRR(0.857 → 0.946)은 dragonkue가 확실히 낫다. 순수 랭킹 품질만 보면
리랭커가 일을 잘한 게 맞다.

**그런데 운영은 top-1을 쓰지 않는다.** `K_FINAL=5`, 즉 상위 5개를 이어붙여 컨텍스트로 넘긴다.
그래서 실제로 답변 품질을 좌우하는 지표는 Recall@5인데, 이 값이 **Off 0.956 · dragonkue 0.956(동률) ·
BAAI 0.945(오히려 하락)**이다.

> 리랭커는 **top-5 "안에서의 순서"만 바꿀 뿐, top-5에 못 들던 정답을 새로 끌어오지 못한다.**
> 컨텍스트에 어차피 다 들어갈 5개의 내부 순서가 바뀌는 건 LLM 입력에 사실상 영향이 없다.

문항당 **+8~9초**(GPU 기준. CPU 27~210초보단 크게 개선됐지만 실서비스엔 여전히 부담)를 내고
얻는 게 그 순서 변경뿐이므로, **Off 유지가 맞다**는 결론.

---

## 3. K_CANDIDATES 20 → 10 (dragonkue, 리랭킹 On 기준)

| | K=20 | K=10 |
|---|---|---|
| 총 소요 | 1611s | **815s (정확히 절반)** |
| Recall@1 / @3 / @5 | 0.793 / 0.922 / 0.956 | 0.793 / 0.926 / 0.956 (동일) |
| MRR | 0.946 | 0.946 (동일) |

세 조건 모두에서 **Recall@10과 Recall@20이 완전히 동일(0.9599)** 했다. 즉 11~20위 후보는
이 held-out셋에서 정답을 **단 하나도 못 건졌다**.

→ K_CANDIDATES를 10으로 줄여도 품질 손실 없이 리랭킹 비용이 절반이 된다.

⚠️ **단, 이 절약은 리랭킹을 켰을 때만 생긴다.** 리랭킹이 Off인 현재 구조에서는 K_CANDIDATES를
줄여도 검색 시간이 줄지 않는다 — `route_search_chunks`의 하이브리드 경로는 BM25·Dense를
**전체 유닛(n=len(unit_ids))** 으로 돌린 뒤 `linear_fuse(...)[:k]`로 마지막에 자르기 때문에
k는 비용에 영향을 주지 않는다([retrieval.py:484-490](../src/retrieval.py#L484-L490)). Dense 단독
경로만 k가 pgvector LIMIT으로 내려가는데, 20행 vs 5행 차이는 질의 임베딩 비용에 묻힌다.
즉 **K_CANDIDATES 축소는 "리랭킹 재도입 시 비용 절반" 카드이지, 지금 당장의 최적화가 아니다.**

---

## 4. 버그 발견 — OOS 게이트 임계값 스케일 불일치

`gate_low_relevance`의 `MIN_TOP1_SCORE = 0.35`는 **bi-encoder 점수 분포 기준으로 튜닝한 값**이다.
그런데 리랭킹을 켜면 1차 검색 점수가 리랭커 점수로 덮어씌워지고, 이 게이트는 **그 새 점수에
0.35를 그대로 들이댄다.** 리랭커의 점수 스케일은 모델마다 다르다.

**실측 사례**

> 질문: "예금자 한 명이 한 금융회사에서 보호받을 수 있는 한도는 얼마인가요?"
> → dragonkue가 **정답 페이지를 1위로 정확히 찾음**. 그런데 점수가 `0.0985 < 0.35`
> → 게이트가 근거를 **통째로 삭제**.

dragonkue 조건에서 `context_hit` 실패 **22건 중 18건**이 이 패턴이었다. 2절 표의 ContextHit 0.722는
검색이 못 찾아서가 아니라 **찾아놓고 게이트가 버려서** 나온 숫자다.

**교훈**: 리랭커를 도입한다면 어떤 모델이든 `MIN_TOP1_SCORE`를 **그 모델의 점수 분포로 반드시
재보정**해야 한다. 안 그러면 정답률이 조용히 깎이고, 로그상으로는 "관련 문서 없음"으로 보여서
원인을 찾기도 어렵다.

---

## 5. OOS 게이트용 점수 비교: bi-encoder vs dragonkue 리랭킹 (143문항)

4절 버그를 감안해, **각 점수 체계마다 최적 임계값을 그리드서치로 새로 찾아** 분리력을 공정 비교했다.

| | bi-encoder (임계값 0.4772) | dragonkue 리랭킹 (임계값 ≈0.0000454) |
|---|---|---|
| 정확도 | 80.4% | **86.0%** |
| FP (OOS인데 통과) | 20건 | **11건** |
| FN (인스코프인데 차단) | 8건 | 9건 |
| 오분류 합계 | 28건 | **20건** |

> ⚠️ 둘 다 **in-sample 최적치**다. 실제 held-out 성능은 이보다 낮다. 절대값이 아니라
> **상대 비교** 목적으로만 읽을 것.

**부가 발견**: 현재 운영 중인 실제 임계값 0.35를 이 143문항(boundary 케이스 포함)에 그대로 적용하면
정확도가 **66.4%(FP 47건)** 까지 떨어진다. → 리랭커 도입 여부와 **별개로** 0.35 자체가
이 확장된 테스트셋 기준으로 재점검 여지가 있다.

**판단**: dragonkue 점수가 OOS 분리력은 더 낫지만, 게이트 판단을 위해 **매 질문마다 리랭킹을
돌려야 하므로 +8~9초 비용이 똑같이 붙는다.** (분리력 개선 가치) vs (전 질문 지연 비용)의
트레이드오프 — **미정**.

---

## 6. 종합 결론 & 후속 액션

| 항목 | 결론 | 상태 |
|---|---|---|
| 리랭킹 On 전환 | **보류.** K_FINAL=5 기준 검색 품질 이득 0, 지연 비용만 큼 | 확정 |
| RERANK_MODEL | 재도입 시 `dragonkue/bge-reranker-v2-m3-ko` (Recall@1·MRR·OOS 분리력 모두 BAAI보다 앞섬) | 코드 반영 완료 |
| K_CANDIDATES | 20→10으로 낮춰도 이 held-out셋 기준 품질 손실 없음. 단 절약 효과는 **리랭킹 On일 때만** — Off인 지금은 20 유지가 무비용 | 리랭킹 재도입 시 검토 |
| `MIN_TOP1_SCORE` 스케일 버그 | 리랭커 도입 시 **필수 재보정 항목** | 미해결(리랭킹 Off라 현재는 영향 없음) |
| 임계값 0.35 자체 | boundary 포함 143문항 기준 66.4% — 리랭커와 무관하게 재점검 필요 | 별도 이슈 |

### 이번에 코드에 반영한 것 (`src/candidate_ranking.py`)

- `RERANK_MODEL` → `dragonkue/bge-reranker-v2-m3-ko`
- `_get_reranker()`가 GPU 있으면 자동으로 `cuda`, 없으면 `cpu` (기존엔 `device="cpu"` 고정)
- 파일 상단 docstring의 "리랭킹 현재 상태" 블록을 이번 실측 결과로 교체

`pipeline.py`의 `USE_RERANKER = False`는 **그대로 둔다.**

### 원본 결과 파일

```
results/pipeline_holdout/retrieval_rerank_off.json               (저장소에 있음)
results/pipeline_holdout/retrieval_rerank_on_baai.json           (GPU 인스턴스)
results/pipeline_holdout/retrieval_rerank_on_dragonkue.json      (GPU 인스턴스)
results/pipeline_holdout/retrieval_rerank_on_dragonkue_k10.json  (GPU 인스턴스)
results/pipeline_holdout/gate_score_compare_dragonkue.json       (GPU 인스턴스)
```
