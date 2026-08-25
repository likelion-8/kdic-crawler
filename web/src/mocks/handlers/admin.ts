/** 관리자 API 목 — 경로는 CM-DF-003 04절 표 그대로.
 *
 * 공통 규칙(04절 주석)
 * - 목록 응답은 전부 `Page<T>` 봉투 `{items,total,page,size}` · 기본 size 20 · `sort=필드:asc|desc`
 * - 쓰기 API는 `request_id`(멱등키)와 `reason`(변경 사유)이 필수. 없으면 400
 * - 권한이 모자라면 403 + request_id. 화면은 버튼을 숨기지 말고 사유를 옆에 쓴다(CM-DF-001 03절 규칙 3)
 *
 * ── 개발용 스위치 ──
 * - 요청 헤더 `x-mock-role: VIEWER|OPERATOR|EDITOR|ADMIN` → 그 역할로 간주(403 화면 개발용).
 *   헤더가 없으면 로그인한 역할, 로그인 전이면 ADMIN.
 * - `POST /api/admin/login` 은 비밀번호 `wrong` 이면 실패한다. 5회(LOGIN_FAIL_LOCK_COUNT) 실패 시 잠김.
 * - 파이프라인 작업은 생성 후 실제로 시간이 지나면서 단계가 진행된다(단계당 4초, 7단계=28초).
 *   폴링 화면을 목만으로 개발할 수 있다.
 */
import { HttpResponse, delay, http } from 'msw'
import type { Page } from '../../lib/api/types'
import type { Role } from '../../lib/codes'
import { hasRole } from '../../lib/codes'
import { LOGIN_FAIL_LOCK_COUNT, LOGIN_LOCK_MIN, PIPELINE_STEPS } from '../../lib/constants'
import {
  MOCK_ACCOUNTS, MOCK_ACTIVITY_EVENTS, MOCK_CHANGE_REQUESTS, MOCK_JOBS,
  MOCK_ROLES, MOCK_SUGGESTED_QUESTIONS,
} from '../data/admin'
import type { ChangeRequest, MyPermissions, PipelineJob, SuggestedQuestion } from '../data/admin'
import { MOCK_CHUNKS } from '../data/chunks'
import { MOCK_PAGES } from '../data/pages'

// ---------------------------------------------------------------- 공통 유틸

let seq = 0
const nextId = (prefix: string) => `${prefix}_${Date.now().toString(36)}_${(seq += 1)}`

const DEFAULT_PAGE_SIZE = 20

/** 목록 공통 처리 — 정렬(`sort=필드:방향`) 후 페이지 자르기. */
function envelope<T>(items: T[], url: URL): Page<T> {
  const sort = url.searchParams.get('sort')
  let rows = items
  if (sort) {
    const [field, dir] = sort.split(':')
    rows = [...items].sort((a, b) => {
      const av = (a as Record<string, unknown>)[field]
      const bv = (b as Record<string, unknown>)[field]
      const cmp = String(av ?? '').localeCompare(String(bv ?? ''), 'ko')
      return dir === 'desc' ? -cmp : cmp
    })
  }
  const page = Number(url.searchParams.get('page') ?? 1)
  const size = Number(url.searchParams.get('size') ?? DEFAULT_PAGE_SIZE)
  return { items: rows.slice((page - 1) * size, page * size), total: rows.length, page, size }
}

function fail(status: number, message: string) {
  return HttpResponse.json(
    { code: 'INTERNAL', user_message: message, retryable: false, fallback_sources: [], request_id: nextId('req') },
    { status },
  )
}

/** CSV 첨부파일 응답 — 서버(api/export_csv.py)와 같은 모양이라야 apiDownload 가 목에서도 돈다.
 *  BOM 은 엑셀이 UTF-8 로 읽게 하는 표시다(윈도우에서 없으면 한글이 깨진다). */
function csvFile(filename: string, lines: string[], rows: number) {
  return new HttpResponse('\uFEFF' + lines.join('\r\n') + '\r\n', {
    headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': `attachment; filename="${filename}"`,
      'X-Export-Rows': String(rows),
    },
  })
}

/** 로그인 상태. 헤더 x-mock-role이 있으면 그 값이 이긴다. */
let currentRole: Role = 'ADMIN'
let currentEmail = 'admin@demo'
const roleOf = (request: Request): Role => (request.headers.get('x-mock-role') as Role | null) ?? currentRole

/** 권한 부족이면 403 응답을, 충분하면 null을 돌려준다. */
function denied(request: Request, need: Role) {
  const mine = roleOf(request)
  if (hasRole(mine, need)) return null
  return HttpResponse.json(
    {
      code: 'INTERNAL',
      user_message: `이 작업에는 ${need} 권한이 필요합니다. 현재 권한은 ${mine}입니다.`,
      retryable: false,
      fallback_sources: [],
      request_id: nextId('req'),
    },
    { status: 403 },
  )
}

interface WriteBody {
  request_id?: string
  reason?: string
}
/** 쓰기 공통 검증 — request_id·reason 누락은 400. */
function missingWriteFields(body: WriteBody) {
  if (!body?.request_id) return fail(400, 'request_id가 필요합니다.')
  if (!body?.reason?.trim()) return fail(400, '변경 사유를 입력해 주세요.')
  return null
}

// ---------------------------------------------------------------- 세션

const SESSION_START = Date.now()
let idleSince = Date.now()
let lastAuthAt = Date.now()
const loginFails: Record<string, number> = {}

// ---------------------------------------------------------------- 파이프라인 작업 진행

/** 단계 하나에 걸리는 시간. 7단계 = 28초면 폴링 UI를 한 화면에서 다 볼 수 있다. */
const STEP_MS = 4_000
const liveJobs = new Map<string, PipelineJob>()

/** 경과 시간으로 단계 상태를 다시 계산한다. 타이머를 안 써서 탭이 백그라운드여도 어긋나지 않는다. */
function progressed(job: PipelineJob): PipelineJob {
  if (job.status !== 'QUEUED' && job.status !== 'RUNNING') return job
  const elapsed = Date.now() - job.started_at_ms
  const doneCount = Math.floor(elapsed / STEP_MS)
  const steps = PIPELINE_STEPS.map((name, i) => {
    if (i < doneCount) return { name, status: 'SUCCESS' as const, elapsed_ms: STEP_MS }
    if (i === doneCount) return { name, status: 'RUNNING' as const }
    return { name, status: 'QUEUED' as const }
  })
  const finished = doneCount >= PIPELINE_STEPS.length
  return {
    ...job,
    status: finished ? 'SUCCESS' : elapsed < 500 ? 'QUEUED' : 'RUNNING',
    steps: finished ? steps.map((s) => ({ ...s, status: 'SUCCESS' as const, elapsed_ms: STEP_MS })) : steps,
  }
}

const allJobs = () => [...[...liveJobs.values()].map(progressed), ...MOCK_JOBS]

// ---------------------------------------------------------------- 가변 상태(목 안에서만 산다)

const changeRequests: ChangeRequest[] = [...MOCK_CHANGE_REQUESTS]
let suggestedQuestions: SuggestedQuestion[] = [...MOCK_SUGGESTED_QUESTIONS]
const drafts: Record<string, { saved_at: string; version: number; body: unknown }> = {}

// ---------------------------------------------------------------- 핸들러

export const adminHandlers = [
  // ---- 인증 (AD-000 · 공통 셸) ----
  http.post('/api/admin/login', async ({ request }) => {
    const body = (await request.json()) as { email?: string; password?: string }
    const email = body.email ?? ''
    if ((loginFails[email] ?? 0) >= LOGIN_FAIL_LOCK_COUNT) {
      return fail(423, `로그인 시도가 ${LOGIN_FAIL_LOCK_COUNT}회 실패해 ${LOGIN_LOCK_MIN}분간 잠겼습니다.`)
    }
    const account = MOCK_ACCOUNTS.find((a) => a.email === email)
    if (!account || body.password === 'wrong') {
      loginFails[email] = (loginFails[email] ?? 0) + 1
      const left = LOGIN_FAIL_LOCK_COUNT - loginFails[email]
      return fail(401, `이메일 또는 비밀번호가 올바르지 않습니다. (남은 시도 ${left}회)`)
    }
    if (account.status === '잠김') return fail(423, '잠긴 계정입니다. 관리자에게 문의해 주세요.')
    loginFails[email] = 0
    currentRole = account.role
    currentEmail = account.email
    idleSince = Date.now()
    lastAuthAt = Date.now()
    await delay(200)
    return HttpResponse.json({ email: account.email, name: account.name, role: account.role })
  }),

  http.post('/api/admin/logout', () => new HttpResponse(null, { status: 204 })),

  // 위험 작업 전 비밀번호 재확인 — 유효 시간 ADMIN_REAUTH_WINDOW_MIN(30분)
  http.post('/api/admin/reauth', async ({ request }) => {
    const body = (await request.json()) as { password?: string }
    if (body.password === 'wrong') return fail(401, '비밀번호가 올바르지 않습니다.')
    lastAuthAt = Date.now()
    return HttpResponse.json({ last_auth_at: new Date(lastAuthAt).toISOString() })
  }),

  // 3타이머(절대 8h · 유휴 30분 · 재인증 30분)를 화면이 그대로 그릴 수 있게 초 단위로 준다
  http.get('/api/admin/session', ({ request }) => {
    const now = Date.now()
    return HttpResponse.json({
      email: currentEmail,
      role: roleOf(request),
      absolute_expires_in_s: Math.max(0, Math.floor((SESSION_START + 8 * 3600_000 - now) / 1000)),
      idle_expires_in_s: Math.max(0, Math.floor((idleSince + 30 * 60_000 - now) / 1000)),
      reauth_valid_until_s: Math.max(0, Math.floor((lastAuthAt + 30 * 60_000 - now) / 1000)),
    })
  }),

  // [연장] — 유휴 타이머만 리셋된다. 절대 만료는 갱신되지 않는다(PRD-01 §3)
  http.post('/api/admin/session/extend', () => {
    idleSince = Date.now()
    return HttpResponse.json({ idle_expires_in_s: 30 * 60 })
  }),

  http.get('/api/admin/roles', () => HttpResponse.json(MOCK_ROLES)),

  http.get('/api/admin/me/permissions', ({ request }) => {
    const role = roleOf(request)
    const all = [
      { key: 'kb.read', need: 'VIEWER' as Role },
      { key: 'pipeline.run', need: 'OPERATOR' as Role },
      { key: 'kb.write', need: 'EDITOR' as Role },
      { key: 'draft.write', need: 'EDITOR' as Role },
      { key: 'change_request.approve', need: 'ADMIN' as Role },
      { key: 'account.manage', need: 'ADMIN' as Role },
      { key: 'activity.export', need: 'ADMIN' as Role },
    ]
    const body: MyPermissions = { role, allowed: all.filter((p) => hasRole(role, p.need)).map((p) => p.key) }
    return HttpResponse.json(body)
  }),

  // 역할·상태 변경 — ADMIN 전용, 사유 필수
  http.patch('/api/admin/accounts/:id', async ({ params, request }) => {
    const no = denied(request, 'ADMIN')
    if (no) return no
    const body = (await request.json()) as WriteBody & { role?: Role; status?: string }
    const bad = missingWriteFields(body)
    if (bad) return bad
    const account = MOCK_ACCOUNTS.find((a) => a.id === params.id)
    if (!account) return fail(404, '계정을 찾을 수 없습니다.')
    return HttpResponse.json({ ...account, role: body.role ?? account.role, status: body.status ?? account.status })
  }),

  // ---- 지식베이스 (AD-002) ----
  http.get('/api/admin/knowledge/pages', ({ request }) => {
    const url = new URL(request.url)
    const q = (url.searchParams.get('q') ?? '').trim()
    const business = url.searchParams.get('business')
    const state = url.searchParams.get('state')
    let rows = MOCK_PAGES
    if (q) rows = rows.filter((p) => p.page_title.includes(q) || p.source_url.includes(q) || p.page_id.includes(q))
    if (business && business !== '전체') rows = rows.filter((p) => p.business_function === business)
    if (state && state !== '전체') rows = rows.filter((p) => p.list_state === state || p.index_status === state)
    return HttpResponse.json(envelope(rows, url))
  }),

  http.get('/api/admin/knowledge/chunks', ({ request }) => {
    const url = new URL(request.url)
    const pageId = url.searchParams.get('page_id')
    const q = (url.searchParams.get('q') ?? '').trim()
    let rows = MOCK_CHUNKS
    if (pageId) rows = rows.filter((c) => c.page_id === pageId)
    if (q) rows = rows.filter((c) => c.title.includes(q) || c.preview.includes(q))
    return HttpResponse.json(envelope(rows, url))
  }),

  // ---- 신규 URL 사전 검증 · 미리보기 (AD-003) ----
  http.post('/api/admin/previews', async ({ request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as WriteBody & { url?: string; business_function?: string }
    if (!body.request_id) return fail(400, 'request_id가 필요합니다.')
    if (!body.url) return fail(400, 'URL을 입력해 주세요.')
    // crawl_targets 밖의 URL은 수집 금지(PRD-01 B-1-c 삭제·수집 정책)
    if (!/^https:\/\/(www|fins)\.kdic\.or\.kr\//.test(body.url)) {
      return fail(400, '수집 허용 목록(kdic.or.kr)에 없는 주소입니다. 등록할 수 없습니다.')
    }
    await delay(700) // 1~4단계(수집·변환·청킹·검증)를 실제로 도는 시간
    const sample = MOCK_PAGES[0]
    return HttpResponse.json({
      preview_id: nextId('pv'),
      url: body.url,
      // 자동 추출값 — 관리자가 검토 후 고칠 수 있는 초안이다
      extracted: {
        page_title: sample.page_title,
        business_function: body.business_function ?? sample.business_function,
        sub_category: sample.sub_category,
        summary: sample.summary,
        content_sha256: sample.content_sha256,
      },
      chunks: MOCK_CHUNKS.filter((c) => c.page_id === sample.page_id),
      warnings: ['본문에서 표를 2개 발견했습니다. 청킹 결과를 확인해 주세요.'],
    })
  }),

  // ---- 변경 요청 · 승인 (AD-002 · AD-003) ----
  http.post('/api/admin/change-requests', async ({ request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as WriteBody & Partial<ChangeRequest>
    const bad = missingWriteFields(body)
    if (bad) return bad
    const created: ChangeRequest = {
      id: nextId('cr'),
      action: body.action ?? 'UPDATE',
      target_page_id: body.target_page_id ?? '',
      target_title: body.target_title ?? '',
      business_function: body.business_function ?? '예금자보호제도',
      reason: body.reason!,
      requested_by: currentEmail,
      requested_at: new Date().toISOString(),
      status: 'PENDING',
    }
    changeRequests.unshift(created)
    return HttpResponse.json(created, { status: 201 })
  }),

  http.get('/api/admin/change-requests', ({ request }) => {
    const url = new URL(request.url)
    const status = url.searchParams.get('status')
    const rows = status ? changeRequests.filter((c) => c.status === status) : changeRequests
    return HttpResponse.json(envelope(rows, url))
  }),

  /** 변경 요청 확정 — 요청/승인 2단계를 없앴다(팀 결정 2026-08-04). 편집 권한자가 바로 확정한다.
   *  ⚠ 백엔드도 이 권한으로 맞춰야 한다(구 계약은 ADMIN 전용이었다) */
  http.post('/api/admin/change-requests/:id/approve', async ({ params, request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as WriteBody
    const bad = missingWriteFields(body)
    if (bad) return bad
    const target = changeRequests.find((c) => c.id === params.id)
    if (!target) return fail(404, '변경 요청을 찾을 수 없습니다.')
    if (target.status !== 'PENDING') return fail(409, '이미 처리된 요청입니다.')
    Object.assign(target, {
      status: 'APPROVED', decided_by: currentEmail, decided_at: new Date().toISOString(), decision_reason: body.reason,
    })
    return HttpResponse.json(target)
  }),

  /** 변경 요청 버리기 — 승인자가 따로 없어 '반려'가 아니라 내 미리보기를 버리는 동작이다 */
  http.post('/api/admin/change-requests/:id/reject', async ({ params, request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as WriteBody
    const bad = missingWriteFields(body)
    if (bad) return bad
    const target = changeRequests.find((c) => c.id === params.id)
    if (!target) return fail(404, '변경 요청을 찾을 수 없습니다.')
    if (target.status !== 'PENDING') return fail(409, '이미 처리된 요청입니다.')
    Object.assign(target, {
      status: 'REJECTED', decided_by: currentEmail, decided_at: new Date().toISOString(), decision_reason: body.reason,
    })
    return HttpResponse.json(target)
  }),

  // ---- 파이프라인 작업 (AD-004) ----
  http.post('/api/admin/jobs', async ({ request }) => {
    const no = denied(request, 'OPERATOR')
    if (no) return no
    const body = (await request.json()) as WriteBody & { type?: PipelineJob['type']; targets?: string[] }
    const bad = missingWriteFields(body)
    if (bad) return bad
    // PIPELINE_CONCURRENCY = 1 — 동시 실행은 1개뿐이라 실행 버튼이 비활성되는 조건이다
    const running = allJobs().find((j) => j.status === 'RUNNING' || j.status === 'QUEUED')
    if (running) return fail(409, `이미 실행 중인 작업이 있습니다. (${running.id})`)
    const job: PipelineJob = {
      id: nextId('job'),
      type: body.type ?? 'REINDEX',
      status: 'QUEUED',
      targets: body.targets ?? [],
      reason: body.reason!,
      created_by: currentEmail,
      created_at: new Date().toISOString(),
      started_at_ms: Date.now(),
      steps: PIPELINE_STEPS.map((name) => ({ name, status: 'QUEUED' as const })),
    }
    liveJobs.set(job.id, job)
    return HttpResponse.json(job, { status: 202 })
  }),

  http.get('/api/admin/jobs', ({ request }) => HttpResponse.json(envelope(allJobs(), new URL(request.url)))),

  http.get('/api/admin/jobs/:id', ({ params }) => {
    const id = String(params.id)
    const job = liveJobs.has(id) ? progressed(liveJobs.get(id)!) : MOCK_JOBS.find((j) => j.id === id)
    if (!job) return fail(404, '작업을 찾을 수 없습니다.')
    return HttpResponse.json(job)
  }),

  http.post('/api/admin/jobs/:id/cancel', async ({ params, request }) => {
    const no = denied(request, 'OPERATOR')
    if (no) return no
    const body = (await request.json()) as WriteBody
    const bad = missingWriteFields(body)
    if (bad) return bad
    const live = liveJobs.get(String(params.id))
    if (!live) return fail(404, '취소할 수 있는 작업이 아닙니다.')
    // 취소 시점의 단계 상태를 그대로 얼려 둔다 — 어디까지 갔는지가 실패 상세의 핵심 정보다
    const frozen = { ...progressed(live), status: 'CANCELLED' as const }
    liveJobs.set(frozen.id, frozen)
    return HttpResponse.json(frozen)
  }),

  http.post('/api/admin/jobs/:id/retry', async ({ params, request }) => {
    const no = denied(request, 'OPERATOR')
    if (no) return no
    const body = (await request.json()) as WriteBody
    const bad = missingWriteFields(body)
    if (bad) return bad
    const prev = allJobs().find((j) => j.id === String(params.id))
    if (!prev) return fail(404, '작업을 찾을 수 없습니다.')
    // 재시도는 같은 작업을 되살리는 게 아니라 새 job을 만든다(활동 로그가 둘 다 남아야 한다)
    const job: PipelineJob = {
      ...prev,
      id: nextId('job'),
      status: 'QUEUED',
      created_at: new Date().toISOString(),
      created_by: currentEmail,
      reason: body.reason!,
      started_at_ms: Date.now(),
      steps: PIPELINE_STEPS.map((name) => ({ name, status: 'QUEUED' as const })),
      error: undefined,
    }
    liveJobs.set(job.id, job)
    return HttpResponse.json(job, { status: 202 })
  }),

  // 긴급 롤백(REQ-OPS-003) — 직전 성공 색인으로 되돌리는 새 작업
  http.post('/api/admin/jobs/:id/rollback', async ({ params, request }) => {
    const no = denied(request, 'ADMIN')
    if (no) return no
    const body = (await request.json()) as WriteBody
    const bad = missingWriteFields(body)
    if (bad) return bad
    const job: PipelineJob = {
      id: nextId('job'),
      type: 'REINDEX',
      status: 'QUEUED',
      targets: [],
      reason: body.reason!,
      created_by: currentEmail,
      created_at: new Date().toISOString(),
      started_at_ms: Date.now(),
      steps: PIPELINE_STEPS.map((name) => ({ name, status: 'QUEUED' as const })),
      rollback_of: String(params.id),
    }
    liveJobs.set(job.id, job)
    return HttpResponse.json(job, { status: 202 })
  }),

  // ---- 활동 로그 (AD-011) — 추가 전용. 수정·삭제 API는 만들지 않는다 ----
  http.get('/api/admin/activity/events', ({ request }) => {
    const url = new URL(request.url)
    const q = (url.searchParams.get('q') ?? '').trim()
    const actor = url.searchParams.get('actor')
    const result = url.searchParams.get('result')
    let rows = MOCK_ACTIVITY_EVENTS
    if (q) rows = rows.filter((e) => e.action.includes(q) || e.target.includes(q))
    if (actor) rows = rows.filter((e) => e.actor === actor)
    if (result) rows = rows.filter((e) => e.result === result)
    return HttpResponse.json(envelope(rows, url))
  }),

  http.get('/api/admin/activity/events/:id', ({ params }) => {
    const event = MOCK_ACTIVITY_EVENTS.find((e) => e.id === params.id)
    if (!event) return fail(404, '이벤트를 찾을 수 없습니다.')
    // 상세는 당시 스냅샷을 함께 준다(AD-011)
    return HttpResponse.json({ ...event, snapshot: { before: { list_state: '최신' }, after: { list_state: '적용 대기' } } })
  }),

  // 내보내기 자체도 활동 로그에 남는 이벤트다(PRD-01 B-2).
  // 서버는 접수증이 아니라 CSV 파일을 그대로 내려준다(2026-08-25 QA 이후) — 목도 같은 모양이라야
  // 백엔드 없이 개발할 때 '토스트는 뜨는데 파일이 없다'가 재현된다
  http.post('/api/admin/activity/exports', async ({ request }) => {
    const no = denied(request, 'ADMIN')
    if (no) return no
    const body = (await request.json()) as WriteBody
    const bad = missingWriteFields(body)
    if (bad) return bad
    await delay(400)
    const header = '발생시각(KST),행위자,권한,작업,대상,결과,사유,request_id,IP'
    const lines = MOCK_ACTIVITY_EVENTS.map((e) =>
      [e.occurred_at, e.actor, e.actor_role, e.action, e.target, e.result, e.reason ?? '', e.request_id, e.ip]
        .map((v) => `"${String(v).replaceAll('"', '""')}"`)
        .join(','))
    return csvFile(`activity-log-${nextId('exp')}.csv`, [header, ...lines], MOCK_ACTIVITY_EVENTS.length)
  }),

  // ---- 초안 자동 저장 (DRAFT_AUTOSAVE_MS = 10초 주기) ----
  http.put('/api/admin/drafts/:screen', async ({ params, request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const screen = String(params.screen)
    const body = (await request.json()) as WriteBody & Record<string, unknown>
    // 초안 저장은 위험 작업이 아니라 사유를 받지 않는다. request_id만 확인한다
    if (!body.request_id) return fail(400, 'request_id가 필요합니다.')
    const version = (drafts[screen]?.version ?? 0) + 1
    drafts[screen] = { saved_at: new Date().toISOString(), version, body }
    return HttpResponse.json({ screen, saved_at: drafts[screen].saved_at, version })
  }),

  // ---- 추천 질문 (AD-009) — 목록 전체를 통째로 교체한다 ----
  http.put('/api/admin/suggested-questions', async ({ request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as WriteBody & { items?: SuggestedQuestion[] }
    const bad = missingWriteFields(body)
    if (bad) return bad
    const items = body.items ?? []
    // 활성 최대 10 (types.ts Suggestion 주석 · CB-001)
    if (items.filter((i) => i.active).length > 10) return fail(400, '활성 추천 질문은 최대 10개까지입니다.')
    suggestedQuestions = items
    return HttpResponse.json({ items: suggestedQuestions, total: suggestedQuestions.length, page: 1, size: suggestedQuestions.length })
  }),

  http.get('/api/admin/suggested-questions', ({ request }) =>
    HttpResponse.json(envelope(suggestedQuestions, new URL(request.url)))),
]
