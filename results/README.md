# results/ — 실험 산출물(원본 수치)

`experiments/`·`src/eval/` 스크립트가 낸 결과 파일이다. `docs/*.md` 의 표와 발표 자료의 숫자는
여기서 나왔다 — 문서의 수치가 의심되면 이 파일을 다시 열어 본다. 직접 편집하지 않는다.

| 경로 | 무엇 | 만든 스크립트 | 정리 문서 |
|---|---|---|---|
| `pipeline_holdout/retrieval_rerank_off.json` · `generation_rerank_off.json` | held-out 89문항 검색·생성 기준선(리랭커 OFF) | `src/eval/eval_pipeline_retrieval.py` · `eval_pipeline_generation.py` | `docs/pipeline_heldout_baseline_89q.md` |
| `pipeline_holdout/exp_*_hcx007*.json` · `exp_*_dash002*.json` | 생성 모델 A/B(HCX-007 vs HCX-DASH-002), 마커 유무·문항 수 변형 | `src/eval/eval_pipeline_generation.py` | `docs/generation_model_ab_hcx007_vs_dash002_2026-08-26.md` |
| `pipeline_holdout/manual_review_hcx007_vs_dash002_2026-08-26.json` | 위 A/B 의 사람 검토 판정 | 수작업 | 같은 문서 |
| `goldenset_audit/01~07_*.{json,csv}` | 골든셋 감사 — 무결성·근사중복·라벨 충돌·커버리지·고립 문항·LOO·링크 규칙 | `experiments/validate_goldenset.py` | `docs/retrospective.md` |
| `routing_value/*.json` | "link_guide 만 Hybrid" 라우팅 규칙의 가치 재측정(문항별·요약) | `experiments/eval_routing_value.py` | (스크립트 docstring) |
| `prefix_embedding_eval_v1.json` | [page_title · business_function] 프리픽스 임베딩 A/B | `experiments/eval_prefix_embedding.py` | (스크립트 docstring) |
| `prompt_ab*_baseline*.csv` · `prompt_ab*_prefix*.csv` | 프롬프트 프리픽스 A/B 1·2차(+재시도분) | `experiments/eval_summary_prefix.py` 계열 | `docs/faq_format_experiments_2026-08-19.md` |
