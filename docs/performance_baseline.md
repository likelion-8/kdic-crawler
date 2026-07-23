# RAG 파이프라인 성능 baseline

측정일: (측정 스크립트 실행 시점 기준, docs 커밋 시점 참고)

## 측정 시점 설정

- retrieval_top_n (1차 후보): 20
- final_top_k (재정렬 후 최종): 5
- reranker_model: BAAI/bge-reranker-v2-m3
- embedding_model: dragonkue/BGE-m3-ko
- llm_model: HCX-DASH-002 (HyperCLOVA X, via langchain-naver ChatClovaX)
- few_shot: 3건 고정(testset_all.jsonl reference_answer 발췌, prompt_builder.py)

## 웜업 실행 (모델/인덱스 최초 로딩 포함, 참고용 - 비교 대상 아님)

- 질문: 예금자 본인이 직접 예금보험금을 찾으러 갈 때 필요한 서류는 무엇인가요?
- total: 176.69s

## 대표 질문별 단계 시간 (웜업 이후, 단위: 초)

| 유형 | 질문 | query_classification | retrieval | reranking | context_building | prompt_building | llm_call | total |
|---|---|---|---|---|---|---|---|---|
| 정보성 | 예금자 본인이 직접 예금보험금을 찾으러 갈 때 필요한 서류는 무엇인가요? | 0.01 | 0.26 | 99.47 | 0.00 | 0.00 | 2.17 | 101.90 |
| 민원성 | 예금보험금 위임장 양식은 어디서 다운로드 받나요? | 0.15 | 0.02 | 105.42 | 0.01 | 0.00 | 2.18 | 107.78 |
| 표 조회 | 김천저축은행 보험사고일이 언제였나요? | 0.11 | 0.01 | 131.72 | 0.00 | 0.00 | 0.98 | 132.83 |
| 근거 부족(범위 밖) | 불법 대부업체나 사채업자의 살인적인 고금리 피해를 금융감독원에 정식으로 신고하고 구제받는 절차를 상세히 설명해 주세요. | 0.62 | 0.05 | 160.78 | 0.00 | 0.00 | 4.93 | 166.39 |

## 병목 확인

가장 느린 단계(4개 질문 합산 기준): **reranking**
