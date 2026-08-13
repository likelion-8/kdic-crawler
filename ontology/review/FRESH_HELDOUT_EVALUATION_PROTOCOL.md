# 새 Ontology Assist Held-out 평가 수집 규약

> 목적은 canonical ontology 보조가 실제로 검색 품질을 높이는지 독립적으로 확인하는 것입니다.
> 이 규약과 검증기는 RAG·Supabase·LLM 호출이나 운영 검색을 변경하지 않습니다.

## 왜 새 세트가 필요한가

현재 고정 held-out 79개 정답 문항에서는 exact official label prepend가 5건의 순위를 바꿨고,
그중 2건에서 Recall@1이 하락했습니다. 이 결과를 보고 가중치·규칙을 고치면 해당 세트에 과적합될 수
있으므로, 다음 비교는 작성자와 평가자가 결과를 보지 않은 새 질문 세트에서 수행합니다.

## 수집 원칙

1. 질문 작성자는 ontology 라벨 매칭 규칙·기존 진단 사례·평가 결과를 보지 않습니다.
2. 평가 실행자는 질문의 정답 페이지와 판정 기준을 임의로 수정하지 않습니다.
3. 작성자는 질문·정답 페이지·업무영역을 독립적으로 기록하고, 다른 검토자가 원문 근거를 확인합니다.
4. 새 세트의 질문은 기존 `testset_pipeline.jsonl`의 ID와 정규화된 질문 문구를 재사용하지 않습니다.
5. 모든 질문은 공개된 KDIC 공식 페이지를 정답으로 가지며, 평가 전까지 보조 규칙 개발에 사용하지 않습니다.

## 최소 구성

- 정답이 있는 질문 72개 이상
- 6대 업무영역별 12개 이상
- `official_label_explicit` 이외의 질문(`user_paraphrase`, `typo_variant`, `multi_part`)이 50% 이상
- 각 항목에 작성자·작성일·정답 페이지·질문 형태를 기록

## JSONL 항목 형식

```json
{
  "test_id": "fresh_dp_001",
  "question": "한 사람이 받을 수 있는 예금보호 최대 금액은 얼마인가요?",
  "business_function": "예금자보호제도",
  "expected_sources": ["dp_protlmts"],
  "question_type": "fact",
  "intent": "informational",
  "query_form": "user_paraphrase",
  "authored_by": "업무 담당자 식별자",
  "authored_at": "YYYY-MM-DD"
}
```

`query_form`은 `official_label_explicit`, `user_paraphrase`, `typo_variant`, `multi_part` 중 하나입니다.

## 반입 및 검증

검토가 끝난 JSONL은 예를 들어 `data/testset/ontology_assist_fresh_heldout.jsonl`에 두고 아래 명령으로
구조와 기존 held-out 중복 여부를 검사합니다. 이 검사는 결과를 튜닝하지 않으며 파일을 수정하지 않습니다.

```powershell
python src/eval/validate_fresh_ontology_assist_heldout.py data/testset/ontology_assist_fresh_heldout.jsonl
```

검증 통과 후에만 기존 baseline과 ontology shadow를 동일한 방식으로 비교합니다. 개선 여부와 무관하게
운영 반영은 도메인 승인과 별도의 품질 게이트 통과 후에만 검토합니다.

## Fresh 평가 실행

독립 작성자가 만든 JSONL과 **동일한 `test_id`·정답 페이지·Top-5 순위**를 가진 baseline JSON을 준비한 뒤,
아래 명령을 실행합니다. 실행기는 fresh JSONL의 독립성, baseline의 ID·정답·Top-5 형식을 모두 검사한 후에만
고정 exact-label 보조를 비교합니다. 질문이나 결과를 이용해 규칙을 조정하지 않습니다.

```powershell
python src/eval/eval_fresh_ontology_assist.py `
  --testset data/testset/ontology_assist_fresh_heldout.jsonl `
  --baseline results/pipeline_holdout/ontology_assist_fresh_baseline.json `
  --output results/ontology/canonical_assist_shadow_fresh_heldout.json
```

baseline JSON에는 `per_row_retrieval` 배열이 필요하며, 각 행은 `test_id`, `gold`, 길이 5의 `top5_pages`를 포함합니다.
baseline과 fresh JSONL이 완전히 일치하지 않으면 실행기는 결과를 쓰지 않고 실패합니다.
