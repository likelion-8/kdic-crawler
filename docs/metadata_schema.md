# 메타데이터 스키마 정의서

예금보험공사(KDIC) RAG 챗봇 데이터 파이프라인의 세 가지 핵심 산출물
`corpus.jsonl`, `chunks_all.jsonl`, `testset_all.jsonl`의 메타데이터 스키마를 정의한다.
각 파일은 1줄 = 1레코드의 JSONL 형식이며, 아래 필드 정의는 실제 산출물의 필드를
기준으로 작성했다.

- **corpus.jsonl** — 문서(페이지) 단위 코퍼스. 1줄 = 1페이지. 검색·생성의 원천 데이터.
- **chunks_all.jsonl** — 검색 색인 단위(청크) 코퍼스. 1줄 = 1청크. corpus를 청킹한 결과.
- **testset_all.jsonl** — 검색·응답 평가셋. 1줄 = 1평가 문항.

> 세 산출물(corpus.jsonl · chunks_all.jsonl · testset_all.jsonl)의 스키마를
> 모두 정의했다.

---

## 1. corpus.jsonl

문서(페이지) 단위 코퍼스. 1줄 = 1페이지이며, 총 58개 페이지 · 16개 필드로 구성된다.
메타데이터(식별·분류·수집정보)와 본문·자산(text·links·videos 등)이 한 레코드에 함께 담긴다.

### 필드 정의

| 필드 | 타입 | 설명 |
|---|---|---|
| `page_id` | string | 페이지 식별자 (파일명·청크·평가셋에서 이 값으로 페이지를 참조) |
| `source_url` | string | 수집 출처 URL |
| `business_function` | string | 6개 업무 카테고리 중 하나 — 검색 범위 1차 필터 |
| `sub_category` | string | 업무 내 하위 분류(사이트 메뉴 계층 경로) — 2차 필터 |
| `page_title` | string | 페이지 제목 |
| `required` | bool | 사전조사 분류. `true` = 필수, `false` = 분석필요(팀 판단으로 모두 포함) |
| `note` | string | 수집 근거 |
| `summary` | string | 페이지 전체 요약 |
| `collected_at` | string | 수집일자 (YYYY-MM-DD) |
| `content_sha256` | string | 본문 텍스트(`text`)의 SHA-256 해시(64자) — 콘텐츠 변경 및 재적재 감지용 |
| `links` | list | 본문 영역 내부 링크 목록 — `text`(링크 텍스트), `url`(절대경로) |
| `attachments` | list | 정적 `<a href>` 첨부파일 링크 목록(.hwp/.pdf/.doc 등) — 현재 코퍼스엔 0건, KDIC는 첨부를 JS 버튼으로 제공 |
| `form_attachments` | list | JS 버튼 방식 첨부 목록 — `label`, `file_type`, `page_url`, `resolved_url` |
| `videos` | list | 페이지 내 안내영상 URL 목록 |
| `images` | list | 본문 영역 이미지 목록 — `alt`(대체텍스트), `url`(절대경로) |
| `text` | string | 파싱된 본문 전문 |

> **표기 참고**
> - 식별자 필드의 실제 이름은 `page_id`다. (초기 설계 문서·다이어그램에서 `doc_id`로
>   표기된 것과 동일한 대상이며, 산출물의 실제 필드명은 `page_id`.)
> - `links`는 초기 필드 목록에 없었으나 실제 산출물에 포함돼 있다(58개 중 23개 페이지에
>   링크 데이터 존재).
> - `content_sha256`은 초기 필드 목록에 없었으나, 콘텐츠 변경·재적재 감지 로직을
>   구현하면서 추가됐다(아래 참조).

### content_sha256 — 콘텐츠 변경 및 재적재 감지

`content_sha256`은 **기존 문서의 내용이 바뀌었는지 확인하는 역할**만 한다.
본문 텍스트(`text`)를 SHA-256으로 해시한 64자 지문으로, 재수집 시 새로 계산한
해시가 저장된 값과 다르면 그 문서만 다시 파싱·적재한다.

- 해시 기준은 원본 HTML이 아니라 **정제된 본문 텍스트**다. HTML은 판본·세션토큰 탓에
  내용이 그대로여도 값이 튀므로, 실제 의미 있는 변경만 잡으려고 본문을 기준으로 삼는다.

**신규 페이지 감지 방식**

`content_sha256`은 이미 수집된 문서의 변경 감지용이며, **새로 생긴 페이지는 이 해시만으로
감지할 수 없다.** 현재 프로젝트는 `inventory.py`에 수집 대상 URL을 명시적으로 관리하므로,
신규 페이지가 생기면 관리자가 목록을 직접 수정하는 방식을 사용한다.

```
신규 페이지 발견
     ↓
관리자가 inventory.py에 등록
     ↓
다음 수집 시 신규 문서로 적재
```

사이트맵이나 메뉴를 자동 탐색해 새로운 URL을 발견하는 기능은 이번 실전 프로젝트 1
범위에 포함하지 않는다.

---

## 2. chunks_all.jsonl

검색 색인 단위(청크) 코퍼스. 1줄 = 1청크이며, corpus.jsonl 58개 페이지를 청킹한
결과로 총 494개 청크 · 6개 필드로 구성된다. **corpus.jsonl에서 검색·라우팅에 필요한
필드만 상속하고, 청크 식별자 하나를 추가한 축소 스키마**다. 필드 의미는 corpus와
동일하므로, 여기서는 corpus와 다른 점만 정리한다.

### corpus.jsonl과의 차이

| 구분 | 필드 | 설명 |
|---|---|---|
| **추가** | `chunk_id` | 청크 식별자. 아래 규칙 참조 |
| **상속(동일)** | `page_id` | 이 청크의 부모 페이지 = corpus의 `page_id` (parent 참조) |
| **상속(동일)** | `source_url` | corpus와 동일 |
| **상속(동일)** | `page_title` | corpus와 동일 |
| **상속(동일)** | `business_function` | corpus와 동일 — 검색 범위 필터 |
| **재분할** | `text` | corpus의 본문을 청킹 단위로 나눈 조각 |
| **제외** | `sub_category`, `required`, `note`, `summary`, `collected_at`, `content_sha256`, `links`, `attachments`, `form_attachments`, `videos`, `images` | 검색 색인에 불필요해 청크에는 담지 않음. 필요 시 `page_id`로 corpus에서 조회(parent-child) |

### chunk_id 규칙

한 페이지가 여러 청크로 쪼개졌는지에 따라 형식이 다르다.

```
안 쪼개진 페이지 (58개 중 40개):  {page_id}            예: dp_protlmts
쪼개진 페이지     (58개 중 18개):  {page_id}#{청크번호}  예: dp_fnst#0, dp_fnst#1
```

`chunk_id`에서 `#` 앞부분(또는 전체)이 곧 `page_id`이므로, 청크에서 언제든 부모
페이지를 복원할 수 있다. 검색은 작은 청크(child) 단위로 하고, 답변 생성 시 `page_id`로
원본 페이지(parent) 전문을 함께 참조하는 parent-child 구조의 연결 고리다.

---

## 3. testset_all.jsonl

검색·응답 평가셋. 1줄 = 1평가 문항이며, 총 856개 문항 · 11개 필드로 구성된다.
자동 채점이 가능하도록 정답을 서술형 한 덩어리로만 두지 않고, 채점 가능한 필드
(`expected_sources`·`must_include`·`must_not_include`·`expected_links`)로 나눴다.

### 필드 정의

| 필드 | 타입 | 설명 |
|---|---|---|
| `test_id` | string | 테스트 고유 ID |
| `question` | string | 챗봇에 입력할 질문 |
| `question_type` | string | 평가 질문 유형 |
| `business_function` | string | 업무 카테고리 |
| `expected_sources` | list | 정답 근거가 포함된 `page_id` 목록 |
| `must_include` | list | 답변에 반드시 포함되어야 하는 핵심 표현 |
| `must_not_include` | list | 답변에 포함되면 안 되는 오류 표현 |
| `expected_links` | list | 답변에 포함되어야 하는 실제 이동 URL |
| `reference_answer` | string | 사람이 작성한 기준 답변 |
| `note` | string | 평가 목적 및 주의사항 |
| `intent` | string | 질의 의도 — `informational`(정보 질문) 또는 `civil_petition`(민원 처리/신청 질문). 응답을 절차·서류·페이지 안내 3단계로 조립할지 결정하는 분기 기준 |

### test_id 규칙

기존의 `t001`, `t002` 형식 대신 문서와 바로 연결되는 형태로 변경했다.

```
dp_protlmts_q1
dp_protlmts_q2
dp_protlmts_q3

dp_syst_q1
dp_syst_q2
dp_syst_q3
```

구조:

```
{page_id}_q{문항번호}
```

이 규칙을 사용하면 어떤 문서의 평가 문항인지 바로 확인할 수 있고, 검색 결과와
정답 문서를 연결하기 쉽다.

### question_type — 질문 유형

코퍼스의 데이터 구조에 따라 다음 유형을 사용한다.

| 유형 | 평가 내용 |
|---|---|
| `fact` | 본문에 포함된 사실 및 제도 질의 |
| `table_lookup` | 표의 특정 행·열·값 조회 |
| `link_guide` | 신청·조회·이의제기 등 이동 URL 안내 |
| `file_download` | 첨부파일 및 서식 다운로드 안내 |
| `faq` | FAQ 질문-답변 매칭 |
| `out_of_scope` | 코퍼스에 없는 질문에 대한 환각 방지 |

### out_of_scope 문항

초기 테스트셋에는 `out_of_scope` 유형이 없어, 챗봇이 코퍼스에 없는 질문에 그럴듯한
답을 생성해도 검출하기 어려운 문제가 있었다. 전체 문항 수는 유지하면서 기존 일부
질문을 이 유형으로 변경했다.

```
신한은행의 현재 주택담보대출 금리는 얼마인가요?
오늘 비트코인 가격은 얼마인가요?
국민연금은 몇 살부터 받을 수 있나요?
```

설정:

```json
{
  "question_type": "out_of_scope",
  "expected_sources": [],
  "must_include": [],
  "must_not_include": ["근거 없이 생성할 수 있는 구체적 금리·가격·연령 표현"]
}
```

`out_of_scope`는 특정 거절 문구를 강제하기보다 다음을 평가한다.

- 검색 근거가 없는지
- 구체적인 수치나 사실을 임의로 생성하지 않는지
- 제공된 자료에서 확인할 수 없음을 안내하는지

### intent — 질의 의도

`question_type`(검색 관점의 질문 형태)과는 별개 축으로, **응답을 어떤 형식으로
조립할지**를 결정하는 의도 분류다.

| 값 | 의미 |
|---|---|
| `informational` | 사실·정의·수치 등을 묻는 정보성 질문 — 검색된 근거로 바로 답변 |
| `civil_petition` | 신청·접수·제출 등 절차를 실행하려는 민원 처리성 질문 — 절차 안내·서류 안내·페이지 연결 3단계로 응답 조립 |

`question_type`과 독립적인 축이라 같은 유형이라도 의도는 갈릴 수 있다(예: `fact` 유형
질문이 "보호한도가 얼마인가요"면 informational, "신청 기한이 언제까지인가요"면
civil_petition에 가까울 수 있음).

2026-07-22 시점 라벨은 사람이 전수 검수한 값이 아니라 규칙 기반 1차 라벨링이다
(`file_download`·`link_guide` 유형은 civil_petition, 나머지는 "신청/접수/제출/
구비서류/위임장/철회/취소/이의제기/지급명령/청구" 등 절차 실행 표현 포함 여부로 판단
— `src/project1_src/label_intent.py`). leave-one-out 검증 결과 전체 정확도 86.6%,
civil_petition precision 0.770/recall 0.849로 `question_type` 분류기(81.8%)와
비슷한 수준이나, 표본 검수를 거쳐 필요 시 수동 라벨링으로 보강할 여지가 있다.

### 평가 흐름

평가는 검색 단계와 생성 단계로 나뉘며, 각 단계에서 서로 다른 필드를 채점 기준으로 쓴다.

```
사용자 질문
     ↓
검색 결과 생성
     ↓
expected_sources와 비교
     ↓
Recall@K 및 MRR 계산
     ↓
생성 답변 작성
     ↓
must_include / must_not_include / expected_links 검증
```

- **검색 평가**: `expected_sources`를 기준으로 정답 문서가 검색 결과 상위에 포함됐는지 확인한다.
- **생성 평가**: `must_include`·`must_not_include`·`expected_links`를 기준으로 답변의 정확성을 확인한다.

### 평가셋 품질 검증

평가 문항 수를 늘리는 것만으로는 정확한 성능 평가가 어렵기 때문에, 문항 품질을 함께
검증했다. 특히 평가셋의 정답 근거가 사람의 기억이나 해석에만 의존하지 않도록, 원문과
비교해 근거를 확인하는 방식을 유지했다.

주요 검증 항목:

- 질문에 대응하는 정답 근거가 실제 코퍼스에 존재하는지
- `expected_sources`에 지정된 문서가 올바른 문서인지
- 질문에 여러 개의 정답 문서가 존재할 가능성이 있는지
- 질문 문장이 지나치게 원문과 동일하지 않은지
- 반대로 질문이 너무 모호해 정답을 특정할 수 없는지
- `must_include`가 실제 원문에 존재하는 표현인지
- URL 안내 문항의 링크가 실제 페이지와 연결되는지
- 동일하거나 거의 동일한 질문이 중복 생성되지 않았는지
- 질문 유형별 문항 수가 지나치게 편중되지 않았는지
- `out_of_scope` 질문이 실제로 코퍼스에 근거가 없는지
