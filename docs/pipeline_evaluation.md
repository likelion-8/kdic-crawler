# 파이프라인 평가 (evaluate_pipeline.py)

`data/testset/testset_all.jsonl`(853문항)을 RAG 파이프라인에 전부 흘려 답변을 저장하고, 품질을
평가한다. **팀원이 그대로 재실행·재현·이해**할 수 있도록 커맨드·설계 원칙·산출물·한계를 정리한다.

## 핵심 설계 원칙 — 왜 자동 지표를 줄였나

**문자열로 '의미'를 재려는 지표는 계속 샌다.** 거절했는지("확인할 수 없습니다" / "답변을 드릴 수
없습니다" / "안내가 어렵습니다"…), 정답을 담았는지 같은 건 표현이 무한해서 규칙을 아무리 기워도
다음 표현이 새어 나온다 — 두더지 잡기다. 실제로 이 평가를 만들며 그런 결함(거절 오탐·누락,
must_include 형식 오탐, intent leak)이 반복해서 나왔고, **매번 답변을 사람이 직접 읽어야** 진실이
잡혔다.

그래서 역할을 갈랐다:

| | 무엇으로 | 신뢰도 |
|---|---|---|
| **구조적 사실** (생성 성공·응답시간·정답 출처) | 자동(aggregate) | 견고 — 문자열 의미해석 없음 |
| **의미 판단** (정확도·거절 적절성) | **사람이 읽는 층화 표본**(`--sample`) | 앵커 |
| 보조(프록시·judge) | 표본을 고르는 힌트 / 미검증 참고 | 지표로 보고하지 않음 |

**자동 숫자 하나로 "진짜 품질"을 주려 하지 않는다.** 정확도의 신뢰 수치는 사람 표본 채점에서 나온다.

## 1. 실행 커맨드

```bash
# 채점 로직만 검증 (모델·HCX 불필요, 항상 먼저)
python3 src/evaluate_pipeline.py --selftest

# 소규모 확인 (앞 N문항) — 전량 전에 반드시 먼저
python3 src/evaluate_pipeline.py --limit 50

# 전량 실행 (문항당 HCX 1회) — 답변을 results/에 저장
python3 src/evaluate_pipeline.py

# RateLimit 등으로 실패한 문항만 재실행해 병합
python3 src/evaluate_pipeline.py --retry-failed

# 정확도·거절 앵커: 사람 채점용 층화 표본 80건 추출
python3 src/evaluate_pipeline.py --sample

# intent 정확도 실제값 (leave-one-out) — summary 값은 leak, 5장 참고
python3 src/evaluate_pipeline.py --loo-intent
```

### 재현 시 주의
- **Qdrant 임베디드는 단일 프로세스.** 평가 도는 동안 챗봇(`python3 src/pipeline.py`) 터미널을
  열지 말 것 — 락 충돌로 죽는다.
- **HCX 키는 repo 루트 `.env`**(커밋 금지). RateLimit(429)로 일부 문항이 실패하면 코드 오류가
  아니라 격리(`failed_cases.jsonl`)되니 `--retry-failed`로 채운다.
- 첫 실행은 임베딩 모델(`dragonkue/BGE-m3-ko`) 로딩이 있다.

## 2. 출력 파일 (`results/`, gitignore)

| 파일 | 내용 |
|---|---|
| `baseline_results.jsonl` | 문항별 답변·사용청크 페이지·시간(+프록시 플래그는 표본 선별 힌트용) |
| `baseline_summary.json` | **구조 지표만** (3장) |
| `failed_cases.jsonl` | 실행 실패 문항(주로 RateLimit) — `--retry-failed` 대상 |
| `review_sample.jsonl` | (--sample) **사람 채점 표본** — 정확도·거절의 앵커 |

## 3. summary 지표 (구조적 사실만)

| 지표 | 정의 |
|---|---|
| 생성 성공률 | 오류 없이 답변이 나온 비율 |
| 평균 응답시간 | 문항당 timings.total 평균 |
| 정답 출처 포함률(in-scope) | 답변에 사용한 top 청크의 페이지에 정답 페이지가 있나(복수정답 허용) |

문자열 의미해석이 없어 두더지 잡기가 없다. (2026-07-23 전량: 성공률 1.0, 평균 1.62s,
정답출처 0.93. ※ 정답출처는 라우팅이 leak된 분류기를 써 다소 낙관적일 수 있음 — 5장.)

## 4. 정확도·거절 = 사람 표본 채점 (`--sample`)

`review_sample.jsonl`은 80건을 층화로 뽑는다 — (a)프록시가 오답 의심한 것 (b)out_of_scope
(거절 적절성) (c)in-scope인데 거절한 것(과잉거절 의심) (d)유형 대표. **프록시는 여기서 '표본을
고르는 힌트'로만 쓰인다**(`_힌트_*` 필드, 판정 아님).

각 항목에 질문·기준답변·실제답변이 있고, 팀원이 채우는 칸이 있다:
- `정확한가`: 예 / 아니오 / 애매
- `거절_적절`: 예 / 아니오 / 해당없음
- `메모`: 근거

**이 칸을 채우면 그게 신뢰 가능한 정확도·거절 수치가 된다**(신뢰구간 포함). 나중에 프록시·judge가
이 사람 채점과 상관있는지도 이걸로 검증한다. `--judge`/`--validate-judge` 코드는 남아 있으나
(미검증) summary에는 넣지 않는다.

## 5. intent 정확도는 leak — `--loo-intent`로 볼 것

`classify_intent`(및 question_type·business_function 분류기)은 `testset_all.jsonl` 질문들과의
**1-최근접**이다. 평가 질문이 그 참조셋에 **그대로 들어 있어** 최근접이 자기 자신이 된다 →
`intent_정확도` 같은 건 train=test self-match라 무의미. 그래서 **summary에서 뺐다.**

- 실제 추정치: `--loo-intent`(자기 자신 제외 재측정). 2026-07-23 = **0.888**(n=823, in-scope).
- 같은 이유로 retrieval 라우팅도 leak된 분류기를 쓰므로 정답 출처(0.93)는 다소 낙관적일 수 있다.
- 근본 해결(분류기 참조셋과 평가셋 분리)은 P2 과제.

## 6. 이 평가로 드러난 품질 이슈 (P2 개선 과제)

사람 표본 채점으로 확정할 것들이지만, 조사 중 눈에 띈 방향:
- **거절이 잘 안 됨** — out_of_scope 상당수를 거절하지 않고 답한다(근거 없는 답변 = 민원 리스크,
  설계 3제약 中 2). oos 문항이 33건뿐이라 먼저 늘려 재측정 권장.
- **과잉 거절** — 답할 수 있는 in-scope 문항을 거절하는 경우가 있다.
- **민원 서류 섹션 누락** — 민원 답변의 절반가량에 '필요 서류' 섹션이 없다(`civil_petition.py`
  조건 확인).
