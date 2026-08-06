# 예솜24 프론트엔드

예금보험공사 RAG 챗봇 **예솜24**의 사용자 화면과 관리자 콘솔입니다.
React 19 + TypeScript + Vite로 만들었고, **백엔드 없이 단독으로 돕니다.**

## 바로 띄우기

```bash
pnpm install
pnpm dev          # http://localhost:5173
```

Node 20+ / pnpm 9+면 됩니다. `.env`를 만들 필요도, API 키도 필요 없습니다.
브라우저에서 MSW(Mock Service Worker)가 API 요청을 가로채 응답합니다.

| 경로 | 화면 |
|---|---|
| `/` | 챗봇 — 웰컴 · 대화 · 오류 · 역할 되묻기 |
| `/admin` | 관리자 — 로그인은 `admin@demo`, 비밀번호는 아무거나 (`wrong`이면 실패 화면) |

관리자 계정을 `editor@demo` · `ops@demo` · `viewer@demo`로 바꾸면 권한별로 노출되는 버튼이
달라집니다.

### 질문별로 나오는 화면

목이 질문에 든 단어로 시나리오를 고릅니다. 배열 위에서부터 첫 일치가 이깁니다.

| 이렇게 물으면 | 이런 화면 |
|---|---|
| 예금자보호 한도가 얼마인가요? | 정보성 답변 + 참고 출처 |
| 착오송금 반환지원 신청은 어떻게 하나요? | 민원 답변 + 필요 서류 + 신청 페이지 |
| 처리 기간은 어떻게 되나요? | 복합 질문 — 하위 질문별로 답과 출처가 분리 |
| 수수료가 얼마인가요? | 역할 되묻기(송금인/수취인) |
| 오류 / 검색 실패 / 과부하 | 오류 · 재시도 · 요청 제한 화면 |
| 대출 금리 알려줘 | 범위 밖 응답 |

## 이 목이 곧 계약입니다

`src/lib/api/types.ts`가 **프론트가 기대하는 응답 스키마 전부**입니다. 백엔드 Pydantic 모델을
여기에 맞추면 목을 끄는 것만으로 붙습니다.

| 파일 | 역할 |
|---|---|
| `src/lib/api/types.ts` | API 계약 정본 |
| `src/mocks/handlers/` | 실제로 동작하는 목. 경로·상태코드·SSE 이벤트까지 서버와 같은 모양 |
| `src/mocks/README.md` | 목 시나리오와 실제 파이프라인 함수의 대응표 |

목을 끄고 실제 백엔드를 보려면 `.env.local`에 다음을 넣습니다.

```
VITE_ENABLE_MSW=false
VITE_API_BASE=http://localhost:8000
```

⚠️ `VITE_` 접두사가 붙은 값은 **번들에 그대로 공개됩니다.** DB·LLM 자격증명을 넣지 마십시오.

## 검증

```bash
pnpm verify       # tsc -b + oxlint + selfcheck
```

테스트 프레임워크를 따로 두지 않고, 각 모듈 옆의 `selfcheck.ts(x)`가 `assert`로 계약을 지킵니다.
렌더 규칙(빈 배열이면 헤딩째 미렌더 등)이 깨지면 여기서 걸립니다.

## 구조

```
src/
├── routes/chat/      챗봇 화면
├── routes/admin/     관리자 화면
├── components/       공용 UI · 챗봇 전용 컴포넌트
├── lib/api/          API 클라이언트와 계약 타입
├── mocks/            MSW 핸들러와 목 데이터
└── styles/           디자인 토큰 · Tailwind
```

전체 프로젝트 배경과 단계별 기록은 저장소 루트 `README.md`와 `log/`를 참고하십시오.
