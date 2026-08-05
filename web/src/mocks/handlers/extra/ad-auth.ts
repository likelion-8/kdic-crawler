/** AD-000 로그인 · AD-010 보안·권한 보조 목 — 기존 handlers/admin.ts에 없는 엔드포인트만 채운다.
 *
 * handlers/admin.ts가 이미 주는 것: POST login·logout·reauth · GET session · POST session/extend
 * · GET me/permissions · PATCH accounts/{id}.
 * 여기서 채우는 것: 계정 목록·생성, 계정·세션 현황 집계, 로그인 실패 내역, 오늘 위험 작업,
 * 비밀번호 재설정 2종·변경 1종, 역할별 권한 매트릭스(GET roles — 공용 목의 문구를 기획서 원문으로 덮는다).
 *
 * 🔴 PATCH /api/admin/accounts/{id}는 admin.ts가 이미 처리한다(중복 등록 금지). 그쪽 구현은
 * 상태를 저장하지 않으므로 목에서는 역할 변경 결과가 목록에 남지 않는다 — 실서버에서는 영속된다.
 *
 * 경로는 CM-DF-003 04절 Auth·Access 계열을 확장한 프론트 제안이다(기획서에 없음 — report backend_notes). */
import { HttpResponse, delay, http } from 'msw'
import type { Page } from '../../../lib/api/types'
import type { Role } from '../../../lib/codes'
import { LOGIN_LOCK_MIN, RESET_TOKEN_MIN } from '../../../lib/constants'
import { MOCK_ACCOUNTS } from '../../data/admin'

// ---------------------------------------------------------------- 공통

let seq = 0
const nextId = (prefix: string) => `${prefix}_${Date.now().toString(36)}_${(seq += 1)}`

function fail(status: number, message: string) {
  return HttpResponse.json(
    { code: 'INTERNAL', user_message: message, retryable: false, fallback_sources: [], request_id: nextId('req') },
    { status },
  )
}

/** 목 로그인 기본 계정 = '나'. 자기 강등 금지 판정(is_self)의 기준이다 */
const ME = 'admin@demo'

/** 개발용 역할 스위치 — handlers/admin.ts와 같은 규칙(x-mock-role 없으면 ADMIN) */
const roleOf = (request: Request): Role => (request.headers.get('x-mock-role') as Role | null) ?? 'ADMIN'

function denied(request: Request) {
  const mine = roleOf(request)
  if (mine === 'ADMIN') return null
  return HttpResponse.json(
    {
      code: 'INTERNAL',
      user_message: `이 작업에는 ADMIN 권한이 필요합니다. 현재 권한은 ${mine}입니다.`,
      retryable: false,
      fallback_sources: [],
      request_id: nextId('req'),
    },
    { status: 403 },
  )
}

const envelope = <T,>(items: T[]): Page<T> => ({ items, total: items.length, page: 1, size: items.length })

/** 목업 기준일(AD-010은 '오늘'만 보여준다). 시:분만 있는 목업 값을 KST ISO로 굳힌다 */
const TODAY = '2026-08-03'
const at = (hhmm: string) => `${TODAY}T${hhmm}:00+09:00`

// ---------------------------------------------------------------- 계정

/** AD-010 2-5 전체 계정 목록 1행.
 * 계정 상태와 세션 상태를 한 컬럼에 섞지 않도록 필드를 나눴다(08 issue 18).
 * is_self · is_last_admin은 서버 판정이다 — 안전 규칙(자기 강등 금지 · 마지막 ADMIN 보호)을
 * 프론트가 추측하면 목록에 없는 계정 때문에 틀린다(08 issue 17). */
export interface MockAccountRow {
  id: string
  email: string
  name: string
  role: Role
  status: '활성' | '비활성' | '초대됨' | '잠김'
  last_login_at: string | null
  last_activity_at: string | null
  session: 'CURRENT' | 'ACTIVE' | 'NONE'
  /** 유휴 만료까지 남은 초. 접속 중이 아니면 null */
  session_idle_expires_in_s: number | null
  is_self: boolean
  is_last_admin: boolean
}

/** handlers/admin.ts의 로그인 계정(MOCK_ACCOUNTS)과 같은 집합을 쓴다 — 로그인되는 계정만 목록에 있어야 한다 */
const SESSION_SEED: Record<string, { last_activity_at: string; session: MockAccountRow['session']; idle_s: number | null }> = {
  'admin@demo': { last_activity_at: at('10:44'), session: 'CURRENT', idle_s: 30 * 60 },
  'editor@demo': { last_activity_at: at('10:41'), session: 'ACTIVE', idle_s: 27 * 60 },
  'ops@demo': { last_activity_at: at('10:23'), session: 'ACTIVE', idle_s: 9 * 60 },
}

const STATUS_MAP: Record<string, MockAccountRow['status']> = {
  활성: '활성',
  잠김: '잠김',
  '초대 대기': '초대됨',
}

let accounts: MockAccountRow[] = MOCK_ACCOUNTS.map((a) => {
  const seed = SESSION_SEED[a.email]
  return {
    id: a.id,
    email: a.email,
    name: a.name,
    role: a.role,
    status: STATUS_MAP[a.status] ?? '활성',
    last_login_at: a.last_login_at,
    last_activity_at: seed?.last_activity_at ?? null,
    session: seed?.session ?? 'NONE',
    session_idle_expires_in_s: seed?.idle_s ?? null,
    is_self: a.email === ME,
    is_last_admin: false,
  }
})

/** 마지막 남은 ADMIN인지는 목록 전체를 봐야 정해진다 — 응답 시점에 계산한다 */
function withSafetyFlags(rows: MockAccountRow[]): MockAccountRow[] {
  const admins = rows.filter((r) => r.role === 'ADMIN' && r.status === '활성')
  return rows.map((r) => ({ ...r, is_last_admin: admins.length === 1 && admins[0].id === r.id }))
}

// ---------------------------------------------------------------- 로그인 실패 내역

/** AD-010 2-6. 결과 문구는 프론트가 조립한다(잠금 해제 시각을 KST 포맷터로 찍어야 해서) */
export interface MockLoginFailure {
  id: string
  occurred_at: string
  email: string
  /** 마스킹 상태로 30일 보관 (CM-DF-004 08절) */
  ip: string
  reason: '비밀번호 불일치' | '등록되지 않은 계정'
  /** LOCKED면 이 시도로 임시 잠금됐다는 뜻 */
  result: 'LOCKED' | 'NONE'
  unlock_at: string | null
}

/** "최근 4건만 표시하며, 전체 내역은 AD-011 활동 로그"(2-6 주석) — items는 4건, total은 오늘 전체 */
const LOGIN_FAILURES: MockLoginFailure[] = [
  { id: 'lf_006', occurred_at: at('09:41'), email: 'ops@demo', ip: '203.0.113.**', reason: '비밀번호 불일치', result: 'LOCKED', unlock_at: at('09:47') },
  { id: 'lf_005', occurred_at: at('09:40'), email: 'ops@demo', ip: '203.0.113.**', reason: '비밀번호 불일치', result: 'NONE', unlock_at: null },
  { id: 'lf_004', occurred_at: at('09:38'), email: 'ops@demo', ip: '203.0.113.**', reason: '비밀번호 불일치', result: 'NONE', unlock_at: null },
  { id: 'lf_003', occurred_at: at('08:22'), email: 'unknown@demo', ip: '198.51.100.**', reason: '등록되지 않은 계정', result: 'NONE', unlock_at: null },
]
const FAILURES_TODAY = 6

// ---------------------------------------------------------------- 오늘 위험 작업

/** AD-010 2-4. [상세]는 이 id로 AD-011을 연다(`/admin/settings/activity?event=<id>`) */
export interface MockRiskyOp {
  id: string
  occurred_at: string
  action: string
  target_name: string
  /** 사람이 읽는 이름 + (ID) 표기용. 없으면 이름만 쓴다 */
  target_id: string | null
  actor: string
  reason: string
}

const RISKY_TODAY: MockRiskyOp[] = [
  { id: 'ev_r01', occurred_at: at('10:42'), action: '프롬프트 게시', target_name: '답변 원칙', target_id: 'PROMPT-v17', actor: 'editor@demo', reason: '출처 규칙 강화' },
  { id: 'ev_r02', occurred_at: at('09:18'), action: '권한 변경', target_name: '계정 편집자', target_id: 'editor@demo', actor: 'admin@demo', reason: '담당 교체' },
  { id: 'ev_r03', occurred_at: at('08:05'), action: '전체 캐시 비우기', target_name: '전체 질의 캐시', target_id: null, actor: 'admin@demo', reason: '프롬프트 게시 후 무효화' },
]

// ---------------------------------------------------------------- 역할별 권한 매트릭스

/** AD-010 2-3 4행 원문. 공용 목(mocks/data/admin.ts MOCK_ROLES)은 CM-DF-002 06절을 다시 쓴 문구라
 * 화면 고정 문구와 어긋난다(검증 D026) — 이 화면이 쓰는 경로만 기획서 원문으로 덮는다.
 * label과 description이 같은 문구다: 2-7 셀렉트 기본값이 `VIEWER (조회 전용)`이라 둘이 같은 원문을 쓴다. */
const ROLE_MATRIX: { role: Role; permission: string }[] = [
  { role: 'VIEWER', permission: '조회 전용' },
  { role: 'OPERATOR', permission: '파이프라인 실행·취소·재시도 · 질의 캐시 관리' },
  { role: 'EDITOR', permission: '초안 · 콘텐츠 · 테스트셋 · 설정 편집 · 게시 · 적재' },
  { role: 'ADMIN', permission: '전체 캐시 · 롤백 · 계정 관리' },
]

// ---------------------------------------------------------------- 핸들러

export const adAuthHandlers = [
  // ---- 역할 코드값·권한 설명 (화면이 코드값·문구를 지어내지 않는다) ----
  http.get('/api/admin/roles', () =>
    HttpResponse.json(ROLE_MATRIX.map((r) => ({ role: r.role, label: r.permission, description: r.permission }))),
  ),

  // ---- AD-010 계정 · 세션 현황(❶ 요약) ----
  // 목록은 기본으로 접혀 있고 실패 내역은 최근 4건만 준다 → 요약 수치를 목록에서 파생할 수 없다
  http.get('/api/admin/security/summary', ({ request }) => {
    const no = denied(request)
    if (no) return no
    const rows = withSafetyFlags(accounts)
    return HttpResponse.json({
      active_sessions: rows.filter((r) => r.session !== 'NONE').length,
      account_count: rows.length,
      failures_today: FAILURES_TODAY,
      // 잠금은 10분 뒤 자동 해제되며 화면에서 수동 해제하지 않는다(2-2 주석)
      locked: LOGIN_FAILURES.filter((f) => f.result === 'LOCKED').map((f) => ({ email: f.email, unlock_at: f.unlock_at, lock_minutes: LOGIN_LOCK_MIN })),
    })
  }),

  // ---- 전체 계정 목록 (초대됨 · 비활성 계정까지 전부) ----
  http.get('/api/admin/accounts', ({ request }) => {
    const no = denied(request)
    if (no) return no
    return HttpResponse.json(envelope(withSafetyFlags(accounts)))
  }),

  // ---- [+ 계정 추가] (ADMIN 전용 · 사유 필수) ----
  http.post('/api/admin/accounts', async ({ request }) => {
    const no = denied(request)
    if (no) return no
    const body = (await request.json()) as { request_id?: string; reason?: string; name?: string; email?: string; role?: Role }
    if (!body.request_id) return fail(400, 'request_id가 필요합니다.')
    if (!body.reason?.trim()) return fail(400, '생성 사유를 입력해 주세요.')
    if (!body.name?.trim()) return fail(400, '이름을 입력해 주세요.')
    if (!body.email?.trim()) return fail(400, '이메일을 입력해 주세요.')
    // "같은 이메일로는 중복 생성할 수 없습니다"(2-7 주석)
    if (accounts.some((a) => a.email === body.email)) return fail(409, '같은 이메일로 등록된 계정이 이미 있습니다.')
    await delay(300)
    const created: MockAccountRow = {
      id: nextId('acc'),
      email: body.email,
      name: body.name,
      role: body.role ?? 'VIEWER',
      // 메일 설정 완료 전에는 '초대됨' 상태로 로그인할 수 없다(2-7 주석)
      status: '초대됨',
      last_login_at: null,
      last_activity_at: null,
      session: 'NONE',
      session_idle_expires_in_s: null,
      is_self: false,
      is_last_admin: false,
    }
    accounts = [...accounts, created]
    return HttpResponse.json(created, { status: 201 })
  }),

  // ---- 오늘 로그인 실패 내역 (최근 4건) ----
  http.get('/api/admin/login-failures', ({ request }) => {
    const no = denied(request)
    if (no) return no
    return HttpResponse.json({ items: LOGIN_FAILURES, total: FAILURES_TODAY, page: 1, size: LOGIN_FAILURES.length })
  }),

  // ---- 오늘 실행된 위험 작업 (AD-011 요약) ----
  http.get('/api/admin/activity/risky-today', ({ request }) => {
    const no = denied(request)
    if (no) return no
    return HttpResponse.json(envelope(RISKY_TODAY))
  }),

  // ---- AD-000 비밀번호 재설정 (메일 링크 방식) ----
  // 계정 존재 여부와 무관하게 항상 같은 응답 — 계정 탐색 차단(1-4 ①)
  http.post('/api/admin/password/reset-request', async () => {
    await delay(400)
    return HttpResponse.json({ sent: true, expires_in_min: RESET_TOKEN_MIN }, { status: 202 })
  }),

  http.post('/api/admin/password/reset-confirm', async ({ request }) => {
    const body = (await request.json()) as { token?: string; password?: string }
    // 만료·사용된 링크만 410으로 가른다 — 화면은 이때만 ① 재설정 요청으로 되돌린다(1-4 주석 · 검증 D007).
    // 정책 위반은 400이라 ③에 머문다. 개발용 스위치: token=expired 로 만료 링크 화면을 볼 수 있다
    if (!body.token || body.token === 'expired') return fail(410, '링크가 만료되었습니다. 다시 요청해 주세요')
    if ((body.password ?? '').length < 10) return fail(400, '비밀번호는 10자 이상이어야 합니다.')
    await delay(300)
    // 저장 시 그 계정의 다른 세션을 모두 종료한다(1-4 ③)
    return new HttpResponse(null, { status: 204 })
  }),

  // ---- AD-000 1-5 비밀번호 변경 (로그인 상태 · 현재 비밀번호 필수) ----
  // 이 모달 자체가 현재 비밀번호를 요구하므로 위험 작업 재확인(30분)을 거치지 않는다(1-5 주석)
  http.post('/api/admin/password/change', async ({ request }) => {
    const body = (await request.json()) as { request_id?: string; current_password?: string; new_password?: string }
    if (!body.request_id) return fail(400, 'request_id가 필요합니다.')
    // 개발용 스위치: 현재 비밀번호를 'wrong'으로 넣으면 실패 상태를 볼 수 있다
    if (!body.current_password || body.current_password === 'wrong')
      return fail(400, '현재 비밀번호가 일치하지 않습니다.')
    if ((body.new_password ?? '').length < 10) return fail(400, '비밀번호는 10자 이상이어야 합니다.')
    await delay(300)
    // 지금 쓰는 세션은 유지하고 그 계정의 다른 세션만 종료한다(1-5 주석)
    return new HttpResponse(null, { status: 204 })
  }),
]
