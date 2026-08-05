/** AD-010 보안·권한 화면이 쓰는 응답 타입과 호출. 경로는 CM-DF-003 04절 Auth·Access 계열.
 *
 * 계정 목록·집계·실패 내역·오늘 위험 작업은 기획서에 계약이 없어 프론트가 제안한 것이다
 * (목: mocks/handlers/extra/ad-auth.ts · report backend_notes). */
import { DEFAULT_PAGE_SIZE } from '../../../../components/ui'
import { apiRequest } from '../../../../lib/api/client'
import type { Page } from '../../../../lib/api/types'
import type { Role } from '../../../../lib/codes'
import { markReauthed } from '../../../../app/session'

/** ❶ 계정 · 세션 현황. 목록은 접혀 있고 실패 내역은 최근 4건뿐이라 집계는 서버가 준다 */
export interface SecuritySummary {
  active_sessions: number
  account_count: number
  failures_today: number
  locked: { email: string; unlock_at: string | null; lock_minutes: number }[]
}

/** 전체 계정 목록 1행. 계정 상태(status)와 세션 상태(session)는 별도 필드다(08 issue 18) */
export interface AccountRow {
  id: string
  email: string
  name: string
  role: Role
  status: '활성' | '비활성' | '초대됨' | '잠김'
  last_login_at: string | null
  last_activity_at: string | null
  session: 'CURRENT' | 'ACTIVE' | 'NONE'
  session_idle_expires_in_s: number | null
  /** 자기 자신은 강등·비활성화할 수 없다(Description 2 안전 규칙) */
  is_self: boolean
  /** 마지막 남은 ADMIN도 강등·비활성화할 수 없다 — 목록 밖 계정까지 봐야 하므로 서버 판정이다 */
  is_last_admin: boolean
}

export interface LoginFailure {
  id: string
  occurred_at: string
  email: string
  ip: string
  reason: string
  /** LOCKED면 이 시도로 임시 잠금됐다는 뜻 */
  result: 'LOCKED' | 'NONE'
  unlock_at: string | null
}

export interface RiskyOp {
  id: string
  occurred_at: string
  action: string
  target_name: string
  target_id: string | null
  actor: string
  reason: string
}

/** GET /api/admin/roles (mocks/data/admin.ts RoleDefinition과 같은 모양) */
export interface RoleDefinition {
  role: Role
  label: string
  description: string
}

export const accessKeys = {
  summary: ['admin', 'security', 'summary'] as const,
  accounts: ['admin', 'accounts'] as const,
  failures: ['admin', 'login-failures'] as const,
  risky: ['admin', 'activity', 'risky-today'] as const,
  roles: ['admin', 'roles'] as const,
}

export const fetchSummary = () => apiRequest<SecuritySummary>('/api/admin/security/summary')
export const fetchAccounts = (page: number) =>
  apiRequest<Page<AccountRow>>(`/api/admin/accounts?page=${page}&size=${DEFAULT_PAGE_SIZE}`)
export const fetchLoginFailures = () => apiRequest<Page<LoginFailure>>('/api/admin/login-failures')
export const fetchRiskyToday = () => apiRequest<Page<RiskyOp>>('/api/admin/activity/risky-today')
export const fetchRoles = () => apiRequest<RoleDefinition[]>('/api/admin/roles')

/** 위험 작업 공통 실행 — 마지막 인증 후 30분이 지났으면 비밀번호부터 확인한다(CM-DF-004 03절).
 * 재확인 성공은 유휴 타이머도 함께 초기화한다(markReauthed). */
export async function runRisky<T>(password: string | undefined, run: () => Promise<T>): Promise<T> {
  if (password !== undefined) {
    await apiRequest('/api/admin/reauth', { method: 'POST', body: { password } })
    markReauthed()
  }
  return run()
}

/** 역할 변경 · 비활성화 — 둘 다 PATCH /api/admin/accounts/{id} (사유 필수) */
export const patchAccount = (id: string, body: { role?: Role; status?: string }, reason: string) =>
  apiRequest<AccountRow>(`/api/admin/accounts/${id}`, { method: 'PATCH', body, reason })

export const createAccount = (body: { name: string; email: string; role: Role }, reason: string) =>
  apiRequest<AccountRow>('/api/admin/accounts', { method: 'POST', body, reason })
