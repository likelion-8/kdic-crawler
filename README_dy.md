# 예솜24 데이터 파이프라인 — 기능2·기능3 담당분 (신동엽)

실전프로젝트1(AI 서비스 데이터 파이프라인 구축)에서 전체개요 표 기준 담당 범위:

| 기능 | 필수 | 분석필요 | 합계 |
|---|---|---|---|
| 2. 예금보험금 안내 | 3 | 1 | 4 |
| 3. 고객 미수령금 신청 | 3 | 1 | 4 |

## 구성 (likelion-8/kdic-crawler 구조 준용)

- `src/inventory_dy.py` — 수집 대상 정의 (URL 8건 + 업무분류·요약·필수여부·수집 근거). 여기 있는 것만 크롤한다
- `src/crawler_dy.py` — 크롤링 → 원본 HTML 저장 → 결정론적 텍스트 변환(LLM 미사용) → 메타데이터 태깅
- `src/chunker_dy.py` — 글자수 기반 청킹 (500자/overlap 100)
- `src/validate_dy.py` — 네트워크 없이 변환·청킹 로직 자체검증
- `data/raw_html/*.html` — 원본 HTML (갱신 감지·재변환용)
- `data/text/*.txt` — 텍스트 변환본 (표는 `|` 구분 행으로 보존)
- `data/meta/*.json` — 페이지별 메타데이터 (`business_function`, `sub_category`, `source_url`, `summary`, `collected_at`, `attachments` 등 계층 검색용 필드)
- `data/chunks_dy.jsonl` — 청크 31건 (`parent_doc_id`로 원본 역참조 — Parent-Child Retrieval용)

## 실행

```bash
pip install -r requirements.txt
python3 src/crawler_dy.py    # 전체 8건 수집 (재수집·갱신 반영 트리거)
python3 src/chunker_dy.py    # 텍스트 → 청크 (크롤링 없이 단독 재실행 가능)
python3 src/validate_dy.py   # 네트워크 없이 변환·청킹 로직 자체검증
```

콘텐츠 변경 시 crawler → chunker 순으로 재실행하면 전체 재수집·재변환·재청킹됨 (트리거링 기반 갱신 반영).

## 수집 범위 확정

- 분석필요 2건(**F2-04 보험금 지급대상 금융회사**, **F3-04 상속인 금융거래조회**) 포함 확정 — 2026-07-13 팀 협의. 담당 8건 전체 수집
- F2-04는 검색·조회 기능 페이지라 동적 검색 결과는 스냅샷에 안 담김 — 안내 문구·기본 목록만 수집됨 (한계 인지)
- robots.txt 확인 완료: 담당 8건은 차단 경로(`List.do`/`Dtl.do`/`/cm/bbs/`)에 해당 없음

## 파싱 참고사항

- kdic·fins 모두 실제 본문은 `class="contents"` div에 있음
- fins 페이지는 `<body>` 태그가 2개(첫 번째가 빈 것)라 body 폴백 사용 금지
- 청킹은 글자수 기반(500자/overlap 100) 초기 프로토타입 — 기술설계상 이후 고도화 청킹으로 교체 예정
