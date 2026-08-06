# 예솜24 프론트엔드

예금보험공사 RAG 챗봇 **예솜24**의 사용자 화면과 관리자 콘솔입니다.
React 19 + TypeScript + Vite로 만들었습니다.

**백엔드가 붙기 전까지는 목업 데이터가 표시됩니다.** 브라우저에서 MSW(Mock Service Worker)가
API 요청을 가로채 미리 정해 둔 응답을 돌려주므로, 서버나 DB 없이도 모든 화면을 볼 수 있습니다.
백엔드가 준비되면 환경변수 두 줄로 실제 API로 전환합니다(아래 "실제 백엔드에 붙이기").

---

## 실행 방법

노트북마다 Node 버전이 다르거나 아예 설치돼 있지 않아 실행이 막히는 일이 있어 **두 가지 경로**를
둡니다. 어느 쪽이든 같은 버전에서 돕니다(Node 22.13.0 · pnpm 10.22.0).

### 방법 A — Docker (Node 설치 불필요, 권장)

Docker Desktop만 있으면 됩니다. Node·pnpm을 설치하지 않아도 되고 버전 차이로 깨질 일이 없습니다.

```bash
cd web
docker compose up
```

브라우저에서 http://localhost:5173 을 엽니다. 소스를 고치면 그대로 반영됩니다(HMR).
멈출 때는 `Ctrl+C`, 이미지까지 지우려면 `docker compose down --rmi local`.

### 방법 B — 로컬 Node

이미 Node가 깔려 있다면 이쪽이 빠릅니다.

```bash
cd web
corepack enable          # pnpm을 package.json에 적힌 버전으로 준비 (최초 1회)
pnpm install
pnpm dev                 # http://localhost:5173
```

막히는 경우별 대처:

| 증상 | 원인과 해결 |
|---|---|
| Node가 아예 없음 | [nvm](https://github.com/nvm-sh/nvm) 설치 후 `web/`에서 `nvm install && nvm use` — `.nvmrc`에 버전을 적어 두어 팀과 같은 버전이 됩니다 |
| `pnpm: command not found` | `corepack enable`을 먼저 실행하세요. Node 20+에 기본 포함이라 별도 설치가 필요 없습니다 |
| `ERR_PNPM_UNSUPPORTED_ENGINE` | Node가 20.19 미만입니다. `nvm use`로 올리거나 방법 A를 쓰세요 |
| lockfile 관련 오류 | pnpm 버전 차이입니다. `corepack enable` 후 다시 시도하세요 — `package.json`의 `packageManager`가 버전을 고정합니다 |

`.env`를 만들 필요도, API 키도 필요 없습니다.

---

## 무엇을 볼 수 있나

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

### 실제 백엔드에 붙이기

목을 끄고 실제 API를 보려면 `web/.env.local`에 두 줄을 넣습니다.

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
web/
├── Dockerfile            방법 A용 개발 이미지
├── docker-compose.yml    docker compose up 진입점
├── .dockerignore         이미지에 node_modules·dist가 딸려가지 않게
├── .nvmrc                방법 B용 Node 버전 고정
└── src/
    ├── routes/chat/      챗봇 화면
    ├── routes/admin/     관리자 화면
    ├── components/       공용 UI · 챗봇 전용 컴포넌트
    ├── lib/api/          API 클라이언트와 계약 타입
    ├── mocks/            MSW 핸들러와 목 데이터
    └── styles/           디자인 토큰 · Tailwind
```

전체 프로젝트 배경과 단계별 기록은 저장소 루트 `README.md`와 `log/`를 참고하십시오.
