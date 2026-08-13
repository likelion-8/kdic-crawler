# Canonical Ontology Assist Held-out 진단

> 고정 held-out 결과를 설명하는 진단 문서입니다. 이 문서의 사례로 검색 규칙을 튜닝하거나 운영에 반영하지 않습니다.
> LLM·DB·Supabase 호출과 운영 검색 변경은 없습니다.

## 결과

- 평가 문항: 79개
- ontology 라벨 일치율: 0.1519
- 순위 변경: 5건
- 첫 정답 순위 개선: 1건
- 첫 정답 순위 하락: 2건
- 첫 정답 순위 동일: 2건
- 품질 게이트 통과: `False`

## 해석

- 정답과 겹치지 않는 ontology 페이지를 앞에 붙인 사례는 Recall@1 하락의 직접 근거다.
- 정답 페이지를 앞에 붙여 개선된 사례가 있어도, 이 held-out 결과로 규칙·가중치를 조정하지 않는다.
- 다음 비교는 새로 수집하고 누구도 결과를 보지 않은 질문 세트에서만 수행한다.

## 순위 변경 사례

### `cx03` — first_gold_rank_unchanged

- 정답 페이지: `dp_josa_itrd`, `dp_josa_law`, `dp_josa_objc`
- 매칭 label: `부보금융회사조사`
- ontology 페이지와 정답 관계: `gold_only_ontology_pages`
- 첫 정답 순위: baseline `1`, assist `1`
- baseline: `dp_josa_objc`, `dp_josa_law`, `dp_josa_itrd`, `dp_gudn`, `dp_fnst`
- assist: `dp_josa_itrd`, `dp_josa_law`, `dp_josa_objc`, `dp_gudn`, `dp_fnst`

### `cx11` — improved_first_gold_rank

- 정답 페이지: `dp_protlmts`, `ha_ilgl_intro`, `kmrs_apply_mthd`
- 매칭 label: `예금자 보호한도`
- ontology 페이지와 정답 관계: `gold_only_ontology_pages`
- 첫 정답 순위: baseline `None`, assist `1`
- baseline: `kmrs_aply_trgt`, `ha_faq_dclr`, `mtrs_rel_law`, `sender_attention`, `mtrs_gvbk_proc`
- assist: `dp_protlmts`, `kmrs_aply_trgt`, `ha_faq_dclr`, `mtrs_rel_law`, `sender_attention`

### `dp_gudn_pl1` — first_gold_rank_unchanged

- 정답 페이지: `dp_gudn`
- 매칭 label: `표시·설명·확인 제도`
- ontology 페이지와 정답 관계: `mixed_gold_and_non_gold_ontology_pages`
- 첫 정답 순위: baseline `1`, assist `1`
- baseline: `dp_gudn`, `dp_gudn_faq`, `dp_josa_law`, `dp_josa_itrd`, `dp_gudn_data`
- assist: `dp_gudn`, `dp_gudn_data`, `dp_gudn_faq`, `dp_logo`, `dp_josa_law`

### `ms_aply_proc_pl1` — regressed_first_gold_rank

- 정답 페이지: `ms_aply_proc`
- 매칭 label: `예금보험금`
- ontology 페이지와 정답 관계: `non_gold_ontology_pages`
- 첫 정답 순위: baseline `1`, assist `2`
- baseline: `ms_aply_proc`, `faq_nramt`, `ms_expln`, `ms_trgt_fnst`, `dp_syst`
- assist: `ms_expln`, `ms_aply_proc`, `faq_nramt`, `ms_trgt_fnst`, `dp_syst`

### `ms_aply_proc_pl1t` — regressed_first_gold_rank

- 정답 페이지: `ms_aply_proc`
- 매칭 label: `예금보험금`
- ontology 페이지와 정답 관계: `non_gold_ontology_pages`
- 첫 정답 순위: baseline `1`, assist `2`
- baseline: `ms_aply_proc`, `faq_nramt`, `ms_expln`, `ms_trgt_fnst`, `dp_faq_page`
- assist: `ms_expln`, `ms_aply_proc`, `faq_nramt`, `ms_trgt_fnst`, `dp_faq_page`

