/** 관리자 세션 3타이머 전역 상태 (PRD-01 §3 · CM-DF-004 03절).
 *
 *  | 타이머 | 값 | 갱신 조건 |
 *  |---|---|---|
 *  | 절대 | 8시간 | 갱신 불가. 만료 시 강제 로그아웃 |
 *  | 유휴 | 30분 | [연장] · 인증된 관리자 API · 초안 자동 저장 — 🔴 폴링 제외 |
 *  | 재확인 | 30분 | 비밀번호 재확인 성공 시. [연장]으로는 면제되지 않는다 |
 *
 *  표시값은 유휴 잔여와 절대 잔여 중 짧은 쪽이다.
 *  서버는 '남은 초'로 내려주고 프론트는 받은 즉시 만료 시각(epoch ms)으로 굳힌다
 *  — 서버·클라이언트 시계가 어긋나도 카운트다운이 튀지 않는다.
 *
 *  fetch 래퍼(lib/api/client.ts)가 React 밖에서 touchIdle을 호출하므로
 *  Context가 아니라 모듈 스토어 + useSyncExternalStore로 둔다.
 *  (client.ts ↔ session.ts는 순환 import지만 서로 함수 선언만 참조해 초기화 순서에 걸리지 않는다) */
import { useEffect, useState, useSyncExternalStore } from 'react'
import type { Role } from '../lib/codes'
import { ADMIN_REAUTH_WINDOW_MIN, ADMIN_SESSION_IDLE_MIN } from '../lib/constants'
import { apiRequest } from '../lib/api/client'

/** 세션 종료 2분 전 경고 (CM-DF-004 03절 "종료 2분 전 경고").
 * constants.ts에 없어 여기 둔다 — 기획서 상수표에는 SESSION_WARN_BEFORE_MIN = 2로 있다. */
const WARN_BEFORE_MS = 2 * 60_000
const IDLE_WINDOW_MS = ADMIN_SESSION_IDLE_MIN * 60_000
const REAUTH_WINDOW_MS = ADMIN_REAUTH_WINDOW_MIN * 60_000

/** GET /api/admin/session 응답 — 3타이머를 '남은 초'로 준다 */
export interface SessionResponse {
  email: string
  role: Role
  absolute_expires_in_s: number
  idle_expires_in_s: number
  reauth_valid_until_s: number
}

/** 프론트 보관 형태 — 만료 '시각'(epoch ms)으로 굳힌 값 */
export interface AdminSession {
  /** 로그인 계정. 헤더에 그대로 노출된다 (`admin@demo`) */
  email: string
  role: Role
  /** 갱신되지 않는다 */
  absoluteExpiresAt: number
  /** [연장]·인증된 관리자 API로 갱신된다 */
  idleExpiresAt: number
  /** 이 시각을 넘기면 위험 작업 전 비밀번호 재확인이 필요하다 */
  reauthValidUntil: number
}

export type SessionStatus = 'loading' | 'authenticated' | 'anonymous'

export interface SessionState {
  status: SessionStatus
  session: AdminSession | null
}

let state: SessionState = { status: 'loading', session: null }
const listeners = new Set<() => void>()

function emit(next: SessionState) {
  state = next
  for (const l of listeners) l()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function useSession(): SessionState {
  return useSyncExternalStore(subscribe, () => state)
}

/** 서버 응답(남은 초) → 보관 형태(만료 시각) */
export function toSession(res: SessionResponse, now: number = Date.now()): AdminSession {
  return {
    email: res.email,
    role: res.role,
    absoluteExpiresAt: now + res.absolute_expires_in_s * 1000,
    idleExpiresAt: now + res.idle_expires_in_s * 1000,
    reauthValidUntil: now + res.reauth_valid_until_s * 1000,
  }
}

export function setSession(session: AdminSession) {
  emit({ status: 'authenticated', session })
}

/** 세션 종료. 401·만료·로그아웃 어디서 났든 여기로 모인다 */
export function expireSession() {
  if (state.status === 'anonymous' && state.session === null) return
  emit({ status: 'anonymous', session: null })
}

let loading = false

/** 부팅 시·로그인 직후 호출. 세션 확인 자체는 활동이 아니므로 유휴 타이머를 건드리지 않는다(isPoll) */
export async function loadSession(): Promise<void> {
  if (loading) return
  loading = true
  try {
    setSession(toSession(await apiRequest<SessionResponse>('/api/admin/session', { isPoll: true })))
  } catch {
    expireSession()
  } finally {
    loading = false
  }
}

/** [연장] — 유휴 타이머만 되돌린다. 마지막 인증 시각·절대 8시간은 갱신되지 않는다 */
export async function extendSession(): Promise<void> {
  const res = await apiRequest<{ idle_expires_in_s: number }>('/api/admin/session/extend', {
    method: 'POST',
  })
  const s = state.session
  if (!s) return
  setSession({ ...s, idleExpiresAt: Date.now() + res.idle_expires_in_s * 1000 })
}

export async function logout(): Promise<void> {
  try {
    await apiRequest('/api/admin/logout', { method: 'POST' })
  } finally {
    expireSession()
  }
}

/** 인증된 관리자 API 성공 시 호출. 서버가 늘린 유휴 만료를 같은 규칙으로 미러링한다 */
export function touchIdle() {
  const s = state.session
  if (!s) return
  setSession({ ...s, idleExpiresAt: Date.now() + IDLE_WINDOW_MS })
}

/** 비밀번호 재확인(POST /api/admin/reauth) 성공 후 호출.
 * 재확인 30분과 유휴 타이머를 함께 초기화한다 (CM-DF-004 03절) */
export function markReauthed() {
  const s = state.session
  if (!s) return
  const now = Date.now()
  setSession({ ...s, idleExpiresAt: now + IDLE_WINDOW_MS, reauthValidUntil: now + REAUTH_WINDOW_MS })
}

/** 표시용 잔여 시간 = min(유휴 잔여, 절대 잔여) (CM-DF-004 03절) */
export function sessionRemainingMs(s: AdminSession, now: number = Date.now()): number {
  return Math.min(s.idleExpiresAt, s.absoluteExpiresAt) - now
}

/** 위험 작업 전 비밀번호 재확인이 필요한가 (마지막 인증 후 30분 경과) */
export function needsReauth(s: AdminSession, now: number = Date.now()): boolean {
  return s.reauthValidUntil - now <= 0
}

/** [연장]이 의미 있는가.
 * 절대 잔여가 유휴 창(30분)보다 짧으면 유휴를 되돌려도 표시 시간(min)이 늘지 않는다.
 * 기획서 "절대 8시간이 임박하면 [연장]을 비활성화하고 재로그인을 안내" 를 이 조건으로 구현했다. */
export function canExtend(s: AdminSession, now: number = Date.now()): boolean {
  return s.absoluteExpiresAt - now > IDLE_WINDOW_MS
}

export interface SessionCountdown {
  remainingMs: number
  /** 종료 2분 전 — 배너 노출 */
  warning: boolean
  /** false면 [연장] 비활성 + 재로그인 안내 */
  extendable: boolean
}

/** 헤더 카운트다운. 1초마다 갱신하고 0이 되면 세션을 끊는다.
 * 잔여 시간에는 aria-live를 걸지 않는다 — 스크린리더가 매초 읽으면 화면을 쓸 수 없다. */
export function useSessionCountdown(): SessionCountdown | null {
  const { session } = useSession()
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (session && sessionRemainingMs(session, now) <= 0) expireSession()
  }, [session, now])

  if (!session) return null
  const remaining = sessionRemainingMs(session, now)
  return {
    remainingMs: Math.max(0, remaining),
    warning: remaining <= WARN_BEFORE_MS,
    extendable: canExtend(session, now),
  }
}
