/** 앱 셸 자체 점검 — 세션 3타이머 계산과 KST 포맷터.
 *
 * 프레임워크를 새로 깔지 않으려고 assert만 쓴다. mocks/selfcheck.ts와 같은 방식으로 돌린다:
 *
 *   cd web && node -e "import('vite').then(async v=>{const s=await v.createServer({server:{middlewareMode:true},appType:'custom'});await s.ssrLoadModule('/src/app/selfcheck.ts');await s.close()})"
 *
 * 통과하면 "app selfcheck: 통과"가 찍힌다. 여기가 깨지면 헤더 세션 표시나 시각 표기가 깨진 것이다. */
/// <reference types="node" />
// ↑ tsconfig.app.json의 types는 vite/client뿐이다. 이 파일만 node에서 도는 스크립트라 여기서만 끌어온다.
import assert from 'node:assert/strict'
import { canExtend, needsReauth, sessionRemainingMs, toSession } from './session'
import { formatDate, formatKst, formatRemaining, formatTarget, formatTime } from '../lib/format'

const T0 = Date.UTC(2026, 7, 1, 0, 0, 0)
const MIN = 60_000

// 1. 남은 초 → 만료 시각
{
  const s = toSession(
    {
      email: 'admin@demo',
      role: 'ADMIN',
      absolute_expires_in_s: 8 * 3600,
      idle_expires_in_s: 30 * 60,
      reauth_valid_until_s: 30 * 60,
    },
    T0,
  )
  assert.equal(s.absoluteExpiresAt, T0 + 8 * 3600_000)
  assert.equal(s.idleExpiresAt, T0 + 30 * MIN)

  // 표시값은 유휴·절대 중 짧은 쪽 (CM-DF-004 03절)
  assert.equal(sessionRemainingMs(s, T0), 30 * MIN)
  assert.equal(sessionRemainingMs(s, T0 + 29 * MIN), 1 * MIN)

  // 절대가 30분보다 많이 남았으면 [연장]은 의미가 있다
  assert.equal(canExtend(s, T0), true)
  assert.equal(needsReauth(s, T0), false)
  assert.equal(needsReauth(s, T0 + 31 * MIN), true, '재확인 30분이 지나면 비밀번호를 다시 받는다')
}

// 2. 절대 만료가 임박하면 [연장]은 표시 시간을 늘리지 못한다 → 비활성 + 재로그인 안내
{
  const s = toSession(
    {
      email: 'admin@demo',
      role: 'ADMIN',
      absolute_expires_in_s: 20 * 60,
      idle_expires_in_s: 30 * 60,
      reauth_valid_until_s: 0,
    },
    T0,
  )
  assert.equal(sessionRemainingMs(s, T0), 20 * MIN, '절대 잔여가 더 짧으면 그쪽이 표시값')
  assert.equal(canExtend(s, T0), false)
  assert.equal(needsReauth(s, T0), true)
}

// 3. 시각은 브라우저 타임존과 무관하게 KST 고정 (PRD-02 §3-f)
{
  const utc = '2026-08-01T01:42:18Z' // = KST 10:42:18
  assert.equal(formatKst(utc), '2026-08-01 10:42:18 KST')
  assert.equal(formatTime(utc), '10:42')
  assert.equal(formatDate(utc), '2026-08-01')
  // 날짜가 넘어가는 경계: UTC 8/1 16:00 = KST 8/2 01:00
  assert.equal(formatDate('2026-08-01T16:00:00Z'), '2026-08-02')
  assert.equal(formatTime('2026-08-01T15:00:00Z'), '00:00', '자정은 24:00이 아니라 00:00')
  assert.equal(formatKst('안 날짜'), '—')
}

// 4. 잔여 시간 문구 · 대상 표기
{
  assert.equal(formatRemaining(27 * MIN + 12_000), '27분 12초')
  assert.equal(formatRemaining(-5000), '0분 0초')
  assert.equal(formatRemaining(2 * 3600_000 + 5 * MIN), '2시간 5분')
  assert.equal(formatTarget('착오송금 반환지원 안내', 'PG-0142'), '착오송금 반환지원 안내 (PG-0142)')
}

console.log('app selfcheck: 통과')
