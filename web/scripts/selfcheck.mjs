/** 자체 점검 러너 — `pnpm check`.
 *
 * 테스트 프레임워크를 새로 깔지 않는다. 각 모듈 옆의 selfcheck 파일이 assert만 쓰고,
 * 이미 있는 vite의 SSR 로더로 TS/JSX를 그대로 읽어 돌린다.
 * 하나라도 던지면 exit 1 이라 CI에 그대로 걸 수 있다.
 */
import { readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const SRC = fileURLToPath(new URL('../src', import.meta.url))

/** src 아래 selfcheck.ts / selfcheck.tsx 를 전부 찾는다 */
function findChecks(dir) {
  const found = []
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) found.push(...findChecks(path))
    else if (/^selfcheck\.tsx?$/.test(name)) found.push(path)
  }
  return found.sort()
}

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
let failed = 0

for (const path of findChecks(SRC)) {
  const id = `/src/${relative(SRC, path)}`
  try {
    await server.ssrLoadModule(id)
  } catch (e) {
    failed += 1
    console.error(`\n✗ ${id}\n${e instanceof Error ? (e.stack ?? e.message) : String(e)}`)
  }
}

await server.close()

if (failed > 0) {
  console.error(`\n자체 점검 실패: ${failed}개 파일`)
  process.exit(1)
}
console.log('\n자체 점검 전체 통과')
