# Streamlit 데모 은퇴 기록 (2026-08-14)

## 무엇을 없앴나

- `src/app.py` — Streamlit 채팅 데모 UI (순수 화면 코드, 비즈니스 로직 없음)
- `.streamlit/config.toml` — Streamlit 테마 설정
- `requirements.txt`의 데모 UI 섹션(이미 주석 처리돼 있던 `streamlit` 핀)

## 왜

React 웹(web/) + FastAPI(api/)가 사용자 화면을 완전히 대체했다(P3 웹 서비스 분리,
docs/frontend-handoff.md 148행 "이관 대상 아님, 이 프론트가 대체한다"). 두 UI를 유지할
이유가 없고, 안 쓰는 진입점이 남아 있으면 "실행 경로가 몇 개인가"를 헷갈리게 만든다.

## 없어지지 않는 것 (혼동 주의)

**`src/pipeline.py`는 현역이다.** Streamlit이 쓰던 조립본이지만 지금도 다음이 쓴다:

- 터미널 CLI (`python src/pipeline.py`) — 빠른 수동 확인용
- 평가 스크립트 전부 (`src/eval/eval_pipeline_*`, `measure_baseline`)
- 관리자 화면의 평가 실행 (api/routers/admin_evaluations.py → eval 모듈 경유)

실서비스(React 웹)의 실행 경로는 `api/rag/answer.py`(SSE 스트리밍 조립)이고,
pipeline.py는 측정·데모용 조립본이라는 역할 분담은 이 은퇴와 무관하게 유지된다.
두 조립본의 차이(출처 판정 단일 vs 3표 다수결)는 별도 통일 작업 예정.

## 복구가 필요하면

코드는 git 히스토리에 영구 보존된다. 삭제 직전 버전:

    git log --follow --oneline -- src/app.py     # 마지막 커밋 확인
    git show <해시>:src/app.py > src/app.py      # 파일 복원

당시 실행 방법: `pip install streamlit` 후 `streamlit run src/app.py`
(임베딩 오프라인 플래그 등 환경 설정은 app.py 상단 주석 참고).
