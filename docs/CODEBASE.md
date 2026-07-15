# 코드베이스 안내 (온보딩)

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
    RAW --> PARSE[2. 변환<br/>parse_raw_html.py]
    PARSE --> TXT[(data/text/*.txt)]
    TXT --> BUILD[3. 코퍼스<br/>build_corpus.py + hashing.py]
    BUILD --> CORP[(data/corpus.jsonl<br/>+ data/meta/*.json)]
    CORP --> VAL[4. 검증<br/>validate_*.py]
    CORP --> RET[5. 검색·평가]
    TESTSET[(data/testset/*.jsonl)] --> RET
    subgraph S5[5. 검색·평가]
      RET[chunking.py → retrieval.py → eval_retrieval.py]
    end
    RET --> DOCS[(docs/retrieval_experiment_results.md)]
```

## 단계별 파일

### 1. 수집 (Crawl) — 사이트에서 원본 HTML 저장
| 파일 | 역할 |
|---|---|
| `inventory.py` | **수집 대상 페이지 통합 목록**(팀원 5명 병합). "여기 있는 것만 크롤한다" — 시작점 |
| `crawler_dy.py` / `crawler_yj.py` / `crawler_hw.py` | 담당자별 크롤러 + 규칙기반 HTML→텍스트 (LLM 미사용) |
| `crawl_mistaken_remittance_jh.py` | 착오송금 도메인 크롤러 (+영상·첨부 추출) |
| `crawl_debt_adjustment_raw_html_jy.py` | 채무조정 8개 페이지 원본 HTML |
| `fetch_dyntable.py` | **동적 조회표** 수집(검색폼+페이지네이션 결과표 전체 행) |
| `fetch_extra.py` | 페이지네이션 뒷페이지 + 게시판 상세(첨부 URL) 수집 |

### 2. 변환 (Parse) — HTML → 정규화 텍스트
| 파일 | 역할 |
|---|---|
| `parse_raw_html.py` | `raw_html/*.html` → `text/*.txt` 일괄 변환. 표는 `\|` 구분 행으로 보존 (`crawler_dy.html_to_text` 재사용) |
| `paser_hw.py` | hw 담당 변환 보조 |

### 3. 코퍼스 (Build) — 텍스트+메타 → 문서 코퍼스
| 파일 | 역할 |
|---|---|
| `build_corpus.py` | `text/` + `meta/` → **`data/corpus.jsonl`** (페이지 1개 = 1줄 = 메타+본문). 파이프라인의 핵심 산출물 |
| `hashing.py` | 갱신 감지 기준 = 본문 텍스트의 `content_sha256` (HTML 아님 — 판본·세션토큰 탓에 튀므로) |

### 4. 검증 (Validate) — 산출물 일관성 체크
| 파일 | 역할 |
|---|---|
| `validate_testset.py` | 테스트셋 ↔ 코퍼스 정합성(정답 page_id 존재, 필드 스키마 등) |
| `validate_dy.py` / `validate_yj.py` | 담당자별 HTML→텍스트 변환 검증 (네트워크 불필요) |

### 5. 검색·평가 (Retrieval / Eval) — ⭐ 최근 추가분
| 파일 | 역할 |
|---|---|
| `chunking.py` | `build_units(mode)` — 색인 단위 결정(`page`/`faq_atomic`/`table_row`/`all`). FAQ·표 탐지는 규칙 기반 |
| `retrieval.py` | **BM25 · Dense(bge-m3) · Hybrid(RRF)** 검색기 + `PageRanked`(유닛→페이지 접기) |
| `eval_retrieval.py` | 문서찾기(Recall@k·MRR) + 답뽑기(AnswerRecall) 평가 + 지표 selftest |

## 데이터 산출물 (`data/`)

| 경로 | 무엇 | 만든이 |
|---|---|---|
| `raw_html/*.html` (58) | 수집한 원본 HTML | 1단계 |
| `text/*.txt` (58) | 정규화 본문 텍스트 | 2단계 |
| `meta/*.json` (58) | 페이지별 메타(URL·카테고리·수집일·해시 등) | 3단계 |
| **`corpus.jsonl`** (58줄) | **문서 코퍼스** = 메타+본문. 검색의 입력 | 3단계 |
| `testset/testset_all.jsonl` (174) | 통합 평가셋(질문·정답 page_id·must_include) | 사람 작성 |
| `testset/testset_tail_probe.jsonl` (4) | 잘린 표 꼬리 겨냥 프로브 | 5단계 |
| `dense_cache/*.npy` | Dense 임베딩 캐시 (gitignore, 자동 재생성) | 5단계 |

## 처음 보는 사람 — 읽기 순서

1. **`README.md`** — 프로젝트가 뭘/왜 하는지 (연구계획서)
2. **`data/corpus.jsonl` 첫 줄** — 데이터가 어떻게 생겼는지 (모든 것의 중심)
3. **`src/inventory.py`** — 무엇을 수집하는지
4. **`src/build_corpus.py`** docstring — 코퍼스가 어떻게 만들어지는지
5. **`src/eval_retrieval.py`** + **`docs/retrieval_experiment_results.md`** — 검색을 어떻게 평가/비교하는지

## 자주 쓰는 실행 커맨드

```bash
# 코퍼스 재생성 (네트워크 불필요, 로컬 raw_html 사용)
python3 src/build_corpus.py

# 텍스트 변환만 다시
python3 src/parse_raw_html.py

# 테스트셋 정합성 검증
python3 src/validate_testset.py

# 검색기 비교 평가 (BM25/Dense/Hybrid × 색인단위) — 첫 실행 시 bge-m3 다운로드
python3 src/eval_retrieval.py

# 개별 모듈 자가검증
python3 src/chunking.py      # 청킹 단위 수 확인
python3 src/hashing.py       # 해시 자체검사
```

## 참고
- 크롤러가 담당자별로 나뉜 건 팀원 5명이 업무 기능을 나눠 수집했기 때문 (`inventory.py` 상단 owner 매핑 참고).
- 변환은 **전부 규칙 기반**(LLM 미사용) — 원문 보존·재현성이 원칙.
- 파이프라인 시각 자료는 `docs/pipeline.html` 에도 있음.
