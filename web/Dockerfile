# 예솜24 프론트엔드 개발 서버 — 팀원 노트북 환경 차이를 없애기 위한 이미지.
#
# Node·pnpm을 설치하지 않아도 `docker compose up`만으로 같은 버전에서 돕니다.
# node 버전은 web/.nvmrc, pnpm 버전은 package.json의 packageManager와 맞춰 둡니다.
FROM node:22.13.0-alpine

WORKDIR /app

# corepack이 package.json의 packageManager를 읽어 지정된 pnpm 버전을 자동으로 씁니다.
# 팀원마다 pnpm 버전이 달라 lockfile이 튀는 문제를 여기서 막습니다.
#
# ⚠️ node 이미지에 번들된 corepack은 npm 레지스트리 서명키가 만료돼
#    "Cannot find matching keyid"로 죽습니다. 최신 corepack을 먼저 깔아야 합니다.
RUN npm install -g corepack@latest && corepack enable

# 의존성 파일만 먼저 복사해 레이어를 캐시합니다 — 소스만 바뀌면 install을 다시 하지 않습니다.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

EXPOSE 5173

# --host 0.0.0.0 이 없으면 컨테이너 안에서만 열려 호스트 브라우저가 붙지 못합니다.
CMD ["pnpm", "dev", "--host", "0.0.0.0"]
