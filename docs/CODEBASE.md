# 코드베이스 안내 (온보딩)

> ⚠️ **이 문서는 P1(데이터 파이프라인, `src/crawler/`)만 다룬다.**
> P2 RAG 코어는 `src/` 루트(`pipeline.py`·`retrieval.py`·`citation.py` 등), API는 `api/`,
> 화면은 `web/`에 있다. 그쪽 구조는 `docs/backend-structure.md` 참고.

KDIC 안내문서 기반 한국어 RAG 챗봇의 **데이터 파이프라인 + 검색 평가** 저장소.
전체는 **수집 → 변환 → 코퍼스 → 검증 → 검색·평가** 5단계로 흐른다. 각 파일은 이 중 한 단계에 속한다.

## 한눈에 보기

```mermaid
flowchart TD
    INV[inventory.py<br/>수집 대상 목록] --> CRAWL
    subgraph S1[1. 수집 · raw HTML 저장]
      CRAWL[crawler_dy/yj/hw · crawl_*_jh/jy<br/>fetch_dyntable · fetch_extra]
    end
    CRAWL --> RAW[(data/raw_html/*.html)]
    CRAWL --> MEDIA[(data/media_summary_jh.json<br/>착오송금 영상·첨부 위치)]
    RAW --> PARSE[2. 변환<br/>parse_raw_html.py]
    PARSE --> TXT[(data/text/*.txt)]
    TXT --> BUILD[3. 코퍼스<br/>build_corpus.py + hashing.py]
    BUILD --> CORP[(data/corpus.jsonl<br/>+ data/meta/*.json)]
    CORP --> VAL[4. 검증<br/>validate_*.py]
    CORP --> RET
    CORP --> EMB
    TESTSET[(data/testset/*.jsonl)] --> RET
    subgraph S5[5. 검색·평가 · 제품 산출물 생성]
      RET[chunking.py → retrieval.py<br/>→ eval_retrieval.py]
      EMB[chunking.py → retrieval.py<br/>→ embed_corpus.py]
    end
    RET --> DOCS[(docs/retrieval_eval.md<br/>연구·비교 결과)]
    EMB --> PROD[(dense_cache/*.npy + chunks_all.jsonl<br/>= 임베딩·평가용 · 운영 검색은 Supabase)]
    MEDIA --> PROD
```

## 단계별 파일

> 아래 표의 파일명은 모두 **`src/crawler/`** 아래에 있다(2026-08-04 P1 분리).
> 예외는 `retrieval.py` 하나로, P2 런타임이 함께 쓰기 때문에 `src/` 루트에 남아 있다.

### 1. 수집 (Crawl) — 사이트에서 원본 HTML 저장
| 파일 | 역할 |
|---|---|
| `inventory.py` | **수집 대상 페이지 통합 목록**(팀원 5명 병합). "여기 있는 것만 크롤한다" — 시작점 |
| `crawler_dy.py` / `crawler_yj.py` | 크롤러 + 규칙기반 HTML→텍스트 (LLM 미사용). 워커 재수집은 `crawler_dy.fetch` 를 쓴다 |
| `crawl_mistaken_remittance_jh.py` | 착오송금 도메인 크롤러 (+영상·첨부 추출) |
| `fetch_dyntable.py` | **동적 조회표** 수집(검색폼+페이지네이션 결과표 전체 행) |
| `fetch_extra.py` | 페이지네이션 뒷페이지 + 게시판 상세(첨부 URL) 수집 |

### 2. 변환 (Parse) — HTML → 정규화 텍스트
| 파일 | 역할 |
|---|---|
| `parse_raw_html.py` | `raw_html/*.html` → `text/*.txt` 일괄 변환. 표는 `\|` 구분 행으로 보존 (`crawler_dy.html_to_text` 재사용) |

### 3. 코퍼스 (Build) — 텍스트+메타 → 문서 코퍼스
| 파일 | 역할 |
|---|---|
| `build_corpus.py` | `text/` + `meta/` → **`data/corpus.jsonl`** (페이지 1개 = 1줄 = 메타+본문). 파이프라인의 핵심 산출물 |
| `hashing.py` | 갱신 감지 기준 = 본문 텍스트의 `content_sha256` (HTML 아님 — 판본·세션토큰 탓에 튀므로) |

### 4. 검증 (Validate) — 산출물 일관성 체크
| 파일 | 역할 |
|---|---|
| `validate_testset.py` | 테스트셋 ↔ 코퍼스 정합성(정답 page_id 존재, 필드 스키마 등) |

### 5. 검색·평가 (Retrieval / Eval) — ⭐ 최근 추가분
| 파일 | 역할 |
|---|---|
| `chunking.py` | `build_units(mode)` — 색인 단위 결정(`page`/`faq_atomic`/`table_row`/`all`). FAQ·표 탐지는 규칙 기반 |
| `retrieval.py` ⚠️ **`src/` 루트** | **BM25 · Dense · Hybrid(RRF)** 검색기 + `PageRanked`(유닛→페이지 접기). 운영 Dense는 `PgVectorDenseRetriever`(Supabase), `QdrantDenseRetriever`는 롤백 대비 잔존 |
| `eval_retrieval.py` ⚠️ **`experiments/`로 이동**(2026-08-31) | 문서찾기(Recall@k·MRR) + 답뽑기(AnswerRecall) 평가 + 지표 selftest. 실험 스크립트 전체 목록은 [`experiments/README.md`](../experiments/README.md) |
| `embed_corpus.py` | **임베딩 일괄 생성 단일 진입점.** 4개 모드 벡터를 `data/dense_cache/`에 저장 + `data/chunks_all.jsonl` 덤프. 한 사람이 실행·커밋하면 팀 공유 |

## 데이터 산출물 (`data/`)

| 경로 | 무엇 | 만든이 |
|---|---|---|
| `raw_html/*.html` (58) | 수집한 원본 HTML | 1단계 |
| `text/*.txt` (58) | 정규화 본문 텍스트 | 2단계 |
| `meta/*.json` (58) | 페이지별 메타(URL·카테고리·수집일·해시 등) | 3단계 |
| `media_summary_jh.json` | 착오송금 페이지의 **영상·첨부 위치** 추출. 챗봇이 "어디서 보라" 안내에 사용(코퍼스 본문과 별개). `crawl_mistaken_remittance_jh.py` 산출 | 1단계 |
| **`corpus.jsonl`** (58줄) | **문서 코퍼스** = 메타+본문. 검색의 입력 | 3단계 |
| `testset/testset_all.jsonl` (851) | 통합 평가셋(골든셋) = 담당자별 세트 + `testset_ambiguous` 병합 | 사람 작성 |
| `testset/testset_ambiguous.jsonl` (277) | 역할·범위가 모호한 질의 세트. `amb_` 접두 test_id | 사람 작성 |
| `testset/testset_pipeline.jsonl` (89) | **held-out** 파이프라인 평가셋(`testset_all`과 겹치지 않음) | 사람 작성 |
| `testset/testset_tail_probe.jsonl` (4) | 잘린 표 꼬리 겨냥 프로브 | 5단계 |
| **`chunks_all.jsonl`** (494줄) | **제품용 청크** = `all` 모드 유닛. `{chunk_id, page_id, source_url, page_title, business_function, text}` — 출처 인용·필터링까지 self-contained. 임베딩과 순서 일치 | 5단계 |
| `dense_cache/*.npy` + `manifest.json` | **팀 공유 Dense 임베딩**(커밋됨). 파일명=내용 해시 → 코퍼스 변경 시 자동 무효화. `embed_corpus.py`로 생성 | 5단계 |

## 처음 보는 사람 — 읽기 순서

1. **`README.md`** — 프로젝트가 뭘/왜 하는지 (연구계획서)
2. **`data/corpus.jsonl` 첫 줄** — 데이터가 어떻게 생겼는지 (모든 것의 중심)
3. **`src/crawler/inventory.py`** — 무엇을 수집하는지
4. **`src/crawler/build_corpus.py`** docstring — 코퍼스가 어떻게 만들어지는지
5. **`experiments/eval_retrieval.py`** + **`docs/retrieval_eval.md`** — 검색을 어떻게 평가/비교하는지

## 자주 쓰는 실행 커맨드

```bash
# 코퍼스 재생성 (네트워크 불필요, 로컬 raw_html 사용)
python3 src/crawler/build_corpus.py

# 텍스트 변환만 다시
python3 src/crawler/parse_raw_html.py

# 테스트셋 정합성 검증
python3 src/crawler/validate_testset.py

# 검색기 비교 평가 (BM25/Dense/Hybrid × 색인단위) — 첫 실행 시 bge-m3 다운로드
python3 experiments/eval_retrieval.py

# 임베딩 + 제품 청크 재생성 (코퍼스 갱신 후 실행 → data/dense_cache/ 와 chunks_all.jsonl 재커밋)
python3 src/crawler/embed_corpus.py

# Supabase 적재 (검색이 실제로 읽는 곳)
python3 src/schema.py                         # 스키마 생성 (재실행 안전)
python3 src/crawler/index_document_chunks.py  # documents/document_chunks 전량 교체
python3 src/crawler/index_evaluation_sets.py  # evaluation_dataset/test_set upsert

# 개별 모듈 자가검증
python3 src/crawler/chunking.py      # 청킹 단위 수 확인
python3 src/crawler/hashing.py       # 해시 자체검사
```

## 제품(챗봇)이 실제로 쓰는 것

**2026-08-03 Qdrant → Supabase Postgres(pgvector) 전환** 이후 런타임 경로가 바뀌었다(`src/retrieval.py:327`).

- **Dense 검색**: Supabase `document_chunks`(494행, `embedding vector(1024)`)를 `PgVectorDenseRetriever`가 읽는다(`src/retrieval.py:148`). 질문 인코딩만 bge-m3를 쓴다.
- **BM25**: `corpus.jsonl`에서 `build_units("all")`로 부팅 시 재구성한다.
- ⚠️ **`dense_cache/*.npy`·`chunks_all.jsonl`은 런타임에 쓰이지 않는다** — 임베딩·평가 스크립트 전용이라 서버 이미지에 넣을 필요가 없다. 그래서 **DB만 갱신하고 `embed_corpus.py`를 안 돌리면 평가 수치가 운영을 설명하지 못한다.**
- 나머지 3개 청킹 모드(page/faq_atomic/table_row)는 "청킹이 왜 필요한지" 증명한 **실험 비교군**이지 제품용이 아니다. 근거는 `docs/retrieval_eval.md`.

## 참고
- **의도 분류는 학습 모델이 아니라 API다** — 2026-08-03에 Kiwi+TF-IDF+LogReg에서 OpenAI Structured Output으로 갈아탔다(`src/query_classifier.py:99`). `data/intent_classifier/*.pkl`과 재학습 스크립트는 더 이상 없고, `OPENAI_API_KEY`가 없으면 예외를 삼키고 `informational`로 조용히 폴백해 민원처리 경로가 통째로 안 돈다.
- 크롤러가 담당자별로 나뉜 건 팀원 5명이 업무 기능을 나눠 수집했기 때문 (`inventory.py` 상단 owner 매핑 참고).
- 변환은 **전부 규칙 기반**(LLM 미사용) — 원문 보존·재현성이 원칙.
- **크로스 플랫폼(맥·윈도우):** 모든 텍스트 파일 I/O는 `encoding="utf-8"` 명시(윈도우 기본 cp949로 한글 깨짐 방지), `.gitattributes`가 `.jsonl` 줄바꿈을 LF로 고정(CRLF면 공유 임베딩 캐시 해시가 틀어짐).
- 파이프라인 시각 자료는 `docs/worklog/pipeline_p1.html`(P1 시점), 검색 실험 결과는 `docs/retrieval_eval.md` 에 있음.
