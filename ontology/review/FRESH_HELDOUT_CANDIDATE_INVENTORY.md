# 기존 Testset의 새 Held-out 후보 점검

> 이 문서는 질문 원문을 출력하지 않는 메타데이터 점검 결과입니다. 어떤 기존 세트도 자동 선택하지 않습니다.
> 새 held-out은 `FRESH_HELDOUT_EVALUATION_PROTOCOL.md`의 작성자·날짜·질문 형태·중복 검증을 모두 통과해야 합니다.

| 파일 | 문항 | 정답 보유 | ID 중복 | 질문 중복 | fresh held-out 사용 가능 | 사유 |
|---|---:|---:|---:|---:|---|---|
| `data/testset/testset_all.jsonl` | 851 | 819 | 0 | 0 | `False` | missing_required_fresh_holdout_provenance |
| `data/testset/testset_ambiguous.jsonl` | 277 | 267 | 0 | 0 | `False` | missing_required_fresh_holdout_provenance |
| `data/testset/testset_dy.jsonl` | 140 | 140 | 0 | 0 | `False` | missing_required_fresh_holdout_provenance |
| `data/testset/testset_hw.jsonl` | 120 | 117 | 0 | 0 | `False` | missing_required_fresh_holdout_provenance |
| `data/testset/testset_jh.jsonl` | 69 | 66 | 0 | 0 | `False` | missing_required_fresh_holdout_provenance |
| `data/testset/testset_jy.jsonl` | 80 | 80 | 0 | 0 | `False` | missing_required_fresh_holdout_provenance |
| `data/testset/testset_pipeline.jsonl` | 89 | 79 | 89 | 88 | `False` | currently_used_as_frozen_ontology_assist_heldout, test_id_overlaps_frozen_heldout, normalized_question_overlaps_frozen_heldout, missing_required_fresh_holdout_provenance |
| `data/testset/testset_query_decomposition.jsonl` | 100 | 0 | 0 | 1 | `False` | normalized_question_overlaps_frozen_heldout, missing_required_fresh_holdout_provenance |
| `data/testset/testset_tail_probe.jsonl` | 4 | 4 | 0 | 0 | `False` | missing_required_fresh_holdout_provenance |
| `data/testset/testset_yj.jsonl` | 170 | 153 | 0 | 0 | `False` | missing_required_fresh_holdout_provenance |

## 다음 조치

- 표에 `false`인 기존 세트는 이 평가에 재사용하지 않습니다.
- 독립 작성자가 새 JSONL을 작성한 뒤 `validate_fresh_ontology_assist_heldout.py`로 반입 검증합니다.
- 검증 통과 전에는 ontology 보조 규칙을 바꾸거나 운영 검색에 적용하지 않습니다.
