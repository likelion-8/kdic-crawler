/** AD-010 보안·권한이 쓰는 목 계약 자체 점검 — 화면이 기대하는 필드·권한 게이트가 맞는지 본다.
 *
 * 화면 컴포넌트는 useSession(useSyncExternalStore)을 쓰는데 서버 스냅샷이 없어 SSR 렌더가 안 된다.
 * 그래서 여기서는 응답 계약만 확인한다(문구 점검은 login/selfcheck.tsx). mocks/selfcheck.ts와 같은 방식:
 *
 *   cd web && node -e "import('vite').then(async v=>{const s=await v.createServer({server:{middlewareMode:true},appType:'custom'});await s.ssrLoadModule('/src/routes/admin/settings/access/selfcheck.ts');await s.close()})"
 *
 * 통과하면 "ad-auth access selfcheck: 통과"가 찍힌다. */
/// <reference types="node" />
// ↑ tsconfig.app.json의 types는 vite/client뿐이다. 이 파일만 node에서 도는 스크립트라 여기서만 끌어온다.
import assert from 'node:assert/strict'
import { setupServer } from 'msw/node'
import type { AccountRow, LoginFailure, RiskyOp, RoleDefinition, SecuritySummary } from './api'

// 핸들러 경로가 상대 경로(`/api/...`)라 node에는 붙일 오리진이 없다. 심어 준 뒤 불러온다
Object.defineProperty(globalThis, 'location', { value: new URL('http://localhost/'), writable: true })
const { adAuthHandlers } = await import('../../../../mocks/handlers/extra/ad-auth')

const server = setupServer(...adAuthHandlers)
server.listen({ onUnhandledRequest: 'error' })

const BASE = 'http://localhost'
const get = (path: string, headers: Record<string, string> = {}) => fetch(`${BASE}${path}`, { headers })
const post = (path: string, body: unknown, headers: Record<string, string> = {}) =>
  fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  })

// 1. ❶ 계정·세션 현황 집계 — 목록이 접혀 있어도 요약이 나와야 한다
{
  const summary = (await (await get('/api/admin/security/summary')).json()) as SecuritySummary
  assert.equal(summary.active_sessions, 3)
  assert.equal(summary.failures_today, 6)
  assert.equal(summary.locked.length, 1, '임시 잠금 건이 있어야 경고 상태 바가 그려진다')
  assert.ok(summary.locked[0].email)
}

// 2. 전체 계정 목록 — 초대됨·잠김까지 전부 + 안전 규칙 플래그(서버 판정)
{
  const page = (await (await get('/api/admin/accounts?page=1&size=20')).json()) as { items: AccountRow[]; total: number }
  const byEmail = new Map(page.items.map((a) => [a.email, a]))
  assert.equal(page.total, 5)
  assert.equal(byEmail.get('admin@demo')!.is_self, true, '본인 계정 행은 조치 불가')
  assert.equal(byEmail.get('admin@demo')!.is_last_admin, true, '마지막 남은 ADMIN도 조치 불가')
  assert.equal(byEmail.get('editor@demo')!.is_self, false)
  assert.equal(byEmail.get('invited@demo')!.status, '초대됨')
  assert.equal(byEmail.get('viewer@demo')!.status, '잠김')
  assert.equal(byEmail.get('ops@demo')!.session, 'ACTIVE')
}

// 3. 권한 — 계정 관리는 ADMIN 전용. 화면에서 숨겨도 서버가 403으로 막는다
{
  const res = await get('/api/admin/accounts', { 'x-mock-role': 'EDITOR' })
  assert.equal(res.status, 403)
  const body = (await res.json()) as { user_message: string; request_id: string }
  assert.ok(body.user_message.includes('ADMIN'))
  assert.ok(body.request_id, '403은 요청 ID와 함께 남긴다(CM-DF-004 03절)')
}

// 4. [+ 계정 추가] — 사유 필수 · 중복 이메일 차단 · 생성 직후 '초대됨'
{
  const noReason = await post('/api/admin/accounts', { request_id: 'r1', name: '홍길동', email: 'new@kdic.or.kr' })
  assert.equal(noReason.status, 400)

  const dup = await post('/api/admin/accounts', { request_id: 'r2', reason: '중복 확인', name: '관리자', email: 'admin@demo' })
  assert.equal(dup.status, 409)

  const created = await post('/api/admin/accounts', {
    request_id: 'r3', reason: '운영 인력 합류', name: '홍길동', email: 'new@kdic.or.kr', role: 'VIEWER',
  })
  assert.equal(created.status, 201)
  assert.equal(((await created.json()) as AccountRow).status, '초대됨')

  const page = (await (await get('/api/admin/accounts')).json()) as { total: number }
  assert.equal(page.total, 6, '생성한 계정이 목록에 바로 보인다')
}

// 5. 로그인 실패 내역 — 최근 4건만 주되 전체 건수는 total로 온다(2-6 주석)
{
  const page = (await (await get('/api/admin/login-failures')).json()) as { items: LoginFailure[]; total: number }
  assert.equal(page.items.length, 4)
  assert.equal(page.total, 6)
  const locked = page.items.find((f) => f.result === 'LOCKED')!
  assert.ok(locked.unlock_at, '잠금 해제 시각이 있어야 결과 문구를 만든다')
  assert.ok(locked.ip.includes('**'), 'IP는 마스킹 상태로 온다(CM-DF-004 08절)')
  assert.ok(page.items.some((f) => f.reason === '등록되지 않은 계정'), '계정 존재 여부 구분은 이 내역에만 남는다')
}

// 6. 오늘 위험 작업 — [상세]가 AD-011로 갈 이벤트 ID를 함께 준다
{
  const page = (await (await get('/api/admin/activity/risky-today')).json()) as { items: RiskyOp[]; total: number }
  assert.equal(page.total, 3)
  assert.ok(page.items.every((r) => r.id && r.actor && r.reason), '실행자·사유 없는 위험 작업은 없다')
}

// 7. 비밀번호 재설정 — 계정 존재 여부와 무관하게 같은 응답 / 만료 링크(410)와 정책 위반(400)을 가른다
{
  const a = await post('/api/admin/password/reset-request', { request_id: 'r4', email: 'admin@demo' })
  const b = await post('/api/admin/password/reset-request', { request_id: 'r5', email: 'nobody@nowhere' })
  assert.equal(a.status, 202)
  assert.deepEqual(await a.json(), await b.json(), '계정 탐색이 가능하면 안 된다')

  const expired = await post('/api/admin/password/reset-confirm', { request_id: 'r6', token: 'expired', password: 'abcdefghij1!' })
  assert.equal(expired.status, 410, '만료·사용된 링크만 ① 화면으로 되돌린다(1-4 주석)')
  assert.equal(((await expired.json()) as { user_message: string }).user_message, '링크가 만료되었습니다. 다시 요청해 주세요')

  const weak = await post('/api/admin/password/reset-confirm', { request_id: 'r7', token: 't', password: 'short' })
  assert.equal(weak.status, 400, '정책 위반은 ③에 머물러야 하므로 만료와 다른 코드다')

  const ok = await post('/api/admin/password/reset-confirm', { request_id: 'r8', token: 't', password: 'abcdefghij1!' })
  assert.equal(ok.status, 204)
}

// 8. 비밀번호 변경(1-5) — 현재 비밀번호 필수 · 재인증 없이 실행된다
{
  const wrong = await post('/api/admin/password/change', { request_id: 'r9', current_password: 'wrong', new_password: 'abcdefghij1!' })
  assert.equal(wrong.status, 400)
  assert.equal(((await wrong.json()) as { user_message: string }).user_message, '현재 비밀번호가 일치하지 않습니다.')

  const ok = await post('/api/admin/password/change', { request_id: 'r10', current_password: 'pw', new_password: 'abcdefghij1!' })
  assert.equal(ok.status, 204)
}

// 9. 역할별 권한 매트릭스 — 2-3 원문 4행 · 셀렉트 기본값 `VIEWER (조회 전용)`
{
  const roles = (await (await get('/api/admin/roles')).json()) as RoleDefinition[]
  assert.equal(roles.length, 4)
  assert.equal(roles[0].role, 'VIEWER')
  assert.equal(roles[0].description, '조회 전용')
  assert.equal(`${roles[0].role} (${roles[0].label})`, 'VIEWER (조회 전용)')
  assert.equal(roles[3].description, '전체 캐시 · 롤백 · 계정 관리')
}

server.close()
console.log('ad-auth access selfcheck: 통과')
