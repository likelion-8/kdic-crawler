# 쿼리 플래너(멀티쿼리 + Intent) 모델 비교 — HCX-007 vs gpt-5.4-mini vs gpt-5.6-luna

"멀티쿼리 분해 + intent 분류를 **한 번의 structured-output API 호출**로 처리"하는 쿼리 플래너를
세 모델로 비교하고, **현행 파이프라인(2콜 방식) 대비 성능 향상**을 실측한 문서다.
모든 수치는 실제 API 호출 실측이며, 짝꿍 문서 [query_planner_token_waste.md](query_planner_token_waste.md)
(현행 방식 토큰 낭비 실측)와 이어진다.

> **한 줄 요약**
> **gpt-5.6-luna**가 종합 1위 — joint 정확도 89%, intent macro F1 0.946, false split 0%.
> 현행 파이프라인(HCX-DASH-002 분해 + gpt-5.6-luna intent, 2.6콜)을 **gpt-5.6-luna 단일
> structured-output 호출**로 바꾸면 **joint 정확도 79%→89%(+10%p), false split 11.9%→0%,
> 질문당 호출 2.6→1, 토큰 2,007→539(-73%)**로 정확도·비용·지연이 동시에 개선된다.

---

## 1. 왜 intent + 멀티쿼리를 한 번의 호출로 합치는가

현행은 **멀티쿼리 분해(HCX-DASH-002)**와 **intent 분류(gpt-5.6-luna)**가 서로 다른 호출·다른
벤더로 분리돼 있다. 이 둘을 한 호출로 합치는 게 합당한 이유:

1. **입력이 같다.** 두 판단 모두 **질문 텍스트만** 필요하고, 검색·생성 이전(맨 앞) 같은 단계에서
   일어난다. 반면 NO_SOURCE 판정은 답변·근거가 있어야 해서 이 호출에 못 합친다(별도 트랙).
2. **고정 호출을 줄인다.** intent 분류는 어차피 모든 질문에 필요한 호출이다. 여기에 "쪼갤지"
   판단을 얹으면, 지금 따로 나가던 분해 호출(HCX)이 통째로 사라진다 — 분해가 intent 호출에
   얹혀 가므로 사실상 공짜가 된다([query_planner_token_waste.md](query_planner_token_waste.md)
   에서 분해 호출이 전체 토큰의 7.9%임을 실측).
3. **판단이 서로 연관된다.** 복합인지 감지하면서 각 하위 질문의 intent를 함께 정하는 게, 쪼갠
   결과를 다른 모델에 다시 넘겨 intent를 매기는 것보다 일관적이다(아래 실측이 이를 뒷받침).
4. **형식 보장.** structured output으로 `{should_split, items:[{question, intent}]}`를 강제하면
   파싱 흔들림이 없다(단, 형식 보장이지 정확도 보장은 아님 — 정확도는 모델 몫).

**joint 호출이 반환하는 구조**:
```json
{ "should_split": true,
  "items": [ { "question": "독립 검색할 하위 질문", "intent": "informational | civil_petition" } ] }
```

---

## 2. 실험 설계

- **테스트셋**: `data/testset/testset_query_decomposition.jsonl` (100문항). 이번에 각
  `expected_items` 항목에 **per-item intent 라벨**(informational/civil_petition)을 추가했다.
  항목 162개(informational 66 / civil_petition 96), 질문 단위로 informational 30 /
  civil_petition 46 / **혼합 복합질문 24**. per-item 라벨이라 복합 질문의 하위 intent까지 채점 가능.
- **intent 라벨 기준**(코드 `intent_llm_common.py` 스펙): informational=정의·개념·사실·수치
  (무엇인가/한도/감면율/대상 상품/처리·지급 기간/포상금 개념), civil_petition=신청·신고·조회·
  반환·수령 등 실행 + 그 방법·서류·절차·어디서·신청 자격·신청 기한.
- **비교 대상**:
  - **CURRENT (baseline)**: 현행 2콜 — HCX-DASH-002 `decompose_query`(멀티쿼리) + gpt-5.6-luna
    `classify_intent`를 하위질문마다 호출.
  - **HCX-007**: joint 1콜, 프롬프트-JSON(native SO 미지원).
  - **gpt-5.4-mini**: joint 1콜, native structured output.
  - **gpt-5.6-luna**: joint 1콜, native structured output.
- **동일 조건**: 세 joint 모델에 의미가 동일한 같은 시스템 프롬프트(분해 규칙 + intent 규칙)를
  줬다. 실행 1회(100문항). temperature는 모델 제약에 맞춤(gpt-5.4-mini=0, gpt-5.6-luna·HCX-007은
  0 미지원/기본값).
- **채점**:
  - 멀티쿼리: should_split 정확도, false split(단일→복합), under split(복합→단일), 개수 일치.
  - intent: 모델 하위질문을 expected 항목에 키워드로 매칭 후 intent 비교 → per-class recall,
    matched 정확도, macro F1, confusion.
  - **joint strict**: 분해 정답 + 개수 일치 + 매칭된 모든 하위 intent 정답을 전부 만족한 비율.

---

## 3. Structured Output 지원 차이 (실측 확인)

| 모델 | native SO | 실측 결과 |
|---|---|---|
| gpt-5.4-mini | ✅ | `response_format`으로 스키마 강제, 100% 형식 성공 |
| gpt-5.6-luna | ✅ | 동일. 단 `temperature=0` 미지원 → 기본값으로 호출 |
| HCX-007 | ❌ | `with_structured_output()`이 **400 에러**(`parallel_tool_calls` invalid) — langchain-naver 래퍼 비호환. **프롬프트-JSON으로 우회**, JSON 파싱 99% 성공(100건 중 1건 실패) |

HCX-007은 API가 형식을 강제하지 못하므로(모델이 형식을 "따라주는" 것), OpenAI와 완전히 동일한
형식 보장 조건이 아니다.

---

## 4. 모델별 결과 (100문항 1회 실측)

### 4.1 종합 비교표

| 모델 | 방식 | Schema성공 | 멀티쿼리 정확도 | False Split | Under Split | Intent 정확도(matched) | Macro F1 | **Joint 정확도** | 평균 지연 | 평균 토큰 | 콜/질문 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **CURRENT** (2콜) | HCX분해+luna intent | 100% | 91.0% | 11.9% | 6.9% | 91.0% | 0.890 | 79.0% | 2.62s | 2,007 | 2.6 |
| HCX-007 | 프롬프트-JSON 1콜 | 99% | **99.0%** | 2.4% | **0.0%** | 72.7% | 0.708 | 56.6% | 8.36s | 833 | 1 |
| gpt-5.4-mini | native SO 1콜 | 100% | 90.0% | **0.0%** | 17.2% | 93.9% | 0.894 | 81.0% | **1.44s** | **489** | 1 |
| **gpt-5.6-luna** | native SO 1콜 | 100% | 95.0% | **0.0%** | 8.6% | **98.0%** | **0.946** | **89.0%** | 1.87s | 539 | 1 |

### 4.2 Intent per-class recall & confusion

| 모델 | recall informational | recall civil_petition | confusion (gold→pred) |
|---|---:|---:|---|
| CURRENT | 87.9% | 87.5% | I→I 58, I→C 5 / C→C 84, C→I 9 |
| HCX-007 | **97.0%** | **50.5%** ⚠️ | I→I 64, I→C 1 / **C→C 48, C→I 41** |
| gpt-5.4-mini | 87.9% | 84.4% | I→I 58, I→C 1 / C→C 81, C→I 8 |
| **gpt-5.6-luna** | 90.9% | **91.7%** | I→I 60, I→C 2 / **C→C 88, C→I 1** |

---

## 5. 모델별 해석

**gpt-5.6-luna — 종합 최고.** 멀티쿼리·intent 어느 쪽도 무너지지 않는 유일한 모델. joint 정확도
89%, intent 두 클래스 모두 90%+ (macro F1 0.946), false split 0%, under split 8.6%로 균형.
native SO로 형식 보장. 지연 1.87s·토큰 539로 가볍다. confusion이 가장 깨끗하다(C→I 오분류 1건).

**HCX-007 — 분해는 최고, intent는 붕괴.** should_split 정확도 99%·under split 0%로 **쪼개기는
세 모델 중 최고**지만, joint 프롬프트에서 **intent가 무너진다**: civil_petition을 informational로
41건이나 오분류(civil recall 50.5%). 기존 intent-전용 실험에선 HCX-007이 91%였는데, "분해+intent를
한 프롬프트로" 시키자 intent 판단이 크게 나빠졌다. 게다가 **지연 8.36s로 4~6배 느리고** native SO
미지원. → joint 플래너로는 부적합.

**gpt-5.4-mini — 가장 빠르고 저렴하나 under-split.** false split 0%·intent 정확도 93.9%로 깔끔하고
지연 1.44s·토큰 489로 가장 경제적. 하지만 **under split 17.2%** — 복합 질문을 안 쪼개고 한 덩어리로
두는 보수적 경향이 강해, 복합 질문 처리에서 손해가 크다.

**CURRENT(현행 2콜) — 분해 품질이 발목.** intent는 준수(gpt-5.6-luna를 쓰므로)하나, HCX-DASH-002
분해가 **false split 11.9%**로 단일 질문을 자주 과잉분해한다(토큰 낭비 문서의 그 문제). 게다가
질문당 2.6콜·2,007토큰으로 가장 무겁다.

---

## 6. 현행 파이프라인 대비 성능 향상 (CURRENT → gpt-5.6-luna joint)

가장 나은 joint 모델(gpt-5.6-luna)로 바꿨을 때, 현행 2콜 파이프라인 대비:

| 지표 | CURRENT (2콜) | gpt-5.6-luna joint (1콜) | 변화 |
|---|---:|---:|---|
| **Joint 정확도** (분해+intent 모두 정답) | 79.0% | **89.0%** | **+10.0%p** |
| Intent macro F1 | 0.890 | **0.946** | +0.056 |
| Intent 정확도(matched) | 91.0% | **98.0%** | +7.0%p |
| should_split 정확도 | 91.0% | 95.0% | +4.0%p |
| **False Split**(불필요 과잉분해) | 11.9% | **0.0%** | **-11.9%p** |
| Under Split | 6.9% | 8.6% | +1.7%p |
| **질문당 LLM 호출** | 2.6 | **1.0** | **-62%** |
| **질문당 토큰** | 2,007 | **539** | **-73%** |
| 평균 지연 | 2.62s | **1.87s** | -29% |
| 출력 형식 | 파싱 의존 | **native SO 보장** | — |

**핵심**: 단순히 비용만 주는 게 아니라 **정확도(+10%p)·false split 제거·호출수·토큰·지연을 전부
동시에 개선**한다. false split 11.9%→0%는 [토큰 낭비 문서](query_planner_token_waste.md)에서
지적한 과잉분해 비용을 실질적으로 없앤다는 뜻이다.

- 유일한 소폭 손해는 under split 6.9%→8.6%(+1.7%p) — 복합 질문을 살짝 덜 쪼갠다. 품질 영향은
  작지만, 프롬프트 보강으로 더 줄일 여지가 있다.
- **참고**: 현행도 intent를 이미 gpt-5.6-luna로 처리하므로(질문이 이미 OpenAI로 전송됨), joint로
  합쳐도 **데이터 국외 이전 노출이 새로 늘지 않는다** — 오히려 HCX 분해 호출이 빠져 CLOVA 의존이
  준다. (공공기관 규정 검토 자체는 현행과 동일하게 여전히 필요.)

---

## 7. 추천

**1순위: gpt-5.6-luna로 joint(멀티쿼리+intent) 단일 structured-output 호출.**

단순 정확도만이 아니라 요청된 축을 모두 고려한 근거:

| 고려 축 | gpt-5.6-luna | 비고 |
|---|---|---|
| Joint/intent 정확도 | ✅ 최고(89% / macroF1 0.946) | 두 클래스 모두 90%+ |
| False split 비용 | ✅ 0% | 현행 11.9% 제거 |
| Under split 품질 | 🟡 8.6% | gpt-5.4-mini(17.2%)보다 훨씬 나음 |
| Structured Output | ✅ native 보장 | HCX-007은 미지원 |
| 토큰/비용 | ✅ 539/질문, 1콜 | 현행 2,007의 27% |
| 지연 | ✅ 1.87s | HCX-007(8.36s)의 1/4 |
| API 오류율 | ✅ 0% | — |
| 도입 리스크 | ✅ 낮음 | 이미 운영 intent 모델이라 벤더 추가 없음 |

- **HCX-007을 안 쓰는 이유**: 분해는 최고지만 intent가 붕괴(civil recall 50.5%)하고 느리며 native
  SO 미지원. 국내 처리(데이터 국외 이전 회피)가 규정상 필수라면, "HCX-007로 분해만 + intent는
  별도"처럼 분리해야 하는데 그러면 joint의 이점(1콜)이 사라진다.
- **gpt-5.4-mini를 안 쓰는 이유**: 가장 싸고 빠르지만 under split 17.2%로 복합 질문을 자주 놓친다.
  비용이 극단적으로 중요하고 복합 질문 비중이 낮다면 대안.

---

## 8. 한계

1. **1회 실측이다.** LLM 확률론적 특성상 재실행 시 수치가 ±수%p 흔들린다. 특히 gpt-5.6-luna 89%
   vs gpt-5.4-mini 81% 같은 우열은 방향은 분명하나, 최종 확정 전 3회 반복 재측정 권장.
2. **intent 라벨의 fuzzy 구간.** 자격/기한/대상/처리기간 같은 항목은 informational/civil_petition
   경계가 모호해 라벨에 노이즈가 있다(문서에 라벨 규칙 명시). 절대 정확도에 영향을 줄 수 있으나,
   **세 모델을 같은 라벨로 채점하므로 상대 비교는 공정**하다.
3. **토큰 비교의 벤더 혼재.** CURRENT의 토큰은 HCX(분해)+OpenAI(intent) 혼합이라, OpenAI-only인
   joint와 요금 단가가 다르다. 토큰 수는 효율의 근사 지표이고, 정확한 비용은 각 벤더 요금표 적용
   필요. (호출 수 2.6→1 감소는 벤더 무관하게 확실한 이득.)
4. **under split은 이 테스트셋(복합질문 58%) 기준**이라 운영 평균과 다를 수 있다.

---

## 9. 다음 단계

1. **gpt-5.6-luna joint 3회 반복 재측정**으로 우열 확정.
2. **분해 프롬프트 보강**으로 gpt-5.6-luna의 under split(8.6%) 축소.
3. **NO_SOURCE 트랙(별도)**: 이 joint와 무관하게, 답변 생성 후 출처 검증(현행 recheck 29% 비용)
   개선은 [토큰 낭비 문서](query_planner_token_waste.md) 7절 참고.
4. 운영 반영 시 데이터 국외 이전 규정 검토(현행과 동일 조건).

---

### 부록 — 재현
- 라벨: 각 `expected_items` 항목에 `intent` 필드 추가(informational/civil_petition).
- joint 하네스: 동일 시스템 프롬프트로 `{should_split, items:[{question,intent}]}` 요청 —
  OpenAI는 `response_format`(pydantic), HCX-007은 프롬프트-JSON 후 파싱. 임시 스크립트(미커밋).
- 채점: 멀티쿼리(should_split/false·under split/개수), intent(키워드 매칭 후 per-class recall·
  macro F1·confusion), joint strict(셋 다 정답).
