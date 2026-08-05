/** 목 서버 자체 점검 — 핸들러가 계약대로 동작하는지 확인하는 최소 스크립트.
 *
 * 테스트 프레임워크를 새로 깔지 않으려고 assert만 쓴다. 이미 있는 vite의 SSR 로더로 돌린다:
 *
 *   cd web && node -e "import('vite').then(async v=>{const s=await v.createServer({server:{middlewareMode:true},appType:'custom'});await s.ssrLoadModule('/src/mocks/selfcheck.ts');await s.close()})"
 *
 * 통과하면 "mocks selfcheck: 13개 항목 모두 통과"가 찍힌다(파이프라인 진행 확인 때문에 ~7초 걸린다).
 * 핸들러를 고쳤는데 이게 깨지면 화면도 깨진 것이다. */
/// <reference types="node" />
// ↑ tsconfig.app.json의 types는 vite/client뿐이다. 이 파일만 node에서 도는 스크립트라 여기서만 끌어온다.
import assert from 'node:assert/strict'
import { setupServer } from 'msw/node'
import type { PromptPrinciple } from '../routes/admin/settings/promptops/api'

// 핸들러 경로가 상대 경로(`/api/...`)라 브라우저에서는 페이지 오리진에 붙지만 node에는 location이
// 없다. 심어 준 뒤에 핸들러를 불러온다(그래서 여기만 동적 import다).
Object.defineProperty(globalThis, 'location', { value: new URL('http://localhost/'), writable: true })
const { adminHandlers } = await import('./handlers/admin')
const { chatHandlers } = await import('./handlers/chat')
const { adPromptOpsHandlers } = await import('./handlers/extra/ad-prompt-ops')

const server = setupServer(...chatHandlers, ...adminHandlers, ...adPromptOpsHandlers)
server.listen({ onUnhandledRequest: 'error' })

const BASE = 'http://localhost'
const post = (path: string, body: unknown, headers: Record<string, string> = {}) =>
  fetch(`${BASE}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify(body) })

/** SSE 응답을 이벤트 배열로 모은다 — lib/api/chat.ts의 parseFrames와 같은 형식 가정. */
async function collectSse(message: string) {
  const res = await post('/api/chat', { message })
  assert.equal(res.headers.get('Content-Type'), 'text/event-stream')
  const text = await res.text()
  return text
    .split('\n\n')
    .filter(Boolean)
    .map((frame) => {
      const name = frame.match(/^event: (.+)$/m)![1]
      const data = JSON.parse(frame.match(/^data: (.+)$/m)![1])
      return { name, data }
    })
}

// 1. 정보성 답변 — accepted → answer_delta 여러 번 → sources → done
{
  const events = await collectSse('예금자보호 한도가 얼마인가요?')
  assert.equal(events[0].name, 'accepted')
  assert.ok(events[0].data.request_id && events[0].data.session_id)
  assert.ok(events.filter((e) => e.name === 'answer_delta').length > 5, '델타가 여러 번 와야 한다')
  assert.ok(events.some((e) => e.name === 'sources'))
  const done = events.at(-1)!
  assert.equal(done.name, 'done')
  assert.equal(done.data.out_of_scope, false)
  assert.equal(done.data.sources.length, 3)
  // 마커는 절대 본문에 섞이면 안 된다
  assert.ok(!done.data.answer.includes('SOURCE'), '자기보고 마커가 answer에 남아 있다')
}

// 2. 민원처리 — 필요 서류(document) + 신청 페이지(link)
{
  const events = await collectSse('착오송금 반환지원 신청 방법 알려줘')
  const done = events.at(-1)!.data
  assert.ok(events.some((e) => e.name === 'attachments'))
  assert.ok(done.attachments.some((a: { kind: string }) => a.kind === 'document'))
  assert.ok(done.attachments.some((a: { kind: string }) => a.kind === 'link'))
}

// 3. 범위 외 — 본문만. 출처 이벤트가 오면 안 된다
{
  const events = await collectSse('안녕')
  assert.ok(!events.some((e) => e.name === 'sources'), 'out_of_scope인데 sources를 보냈다')
  assert.equal(events.at(-1)!.data.out_of_scope, true)
}

// 4. 역할 되묻기 — answer_delta도 sources도 없다
{
  const events = await collectSse('착오송금 수수료 알려줘')
  assert.ok(!events.some((e) => e.name === 'answer_delta'), '되묻기엔 답변 델타가 없다')
  assert.equal(events.at(-1)!.data.clarification.question, '어느 입장에서 궁금하신가요?')
}

// 5. 오류 — error 이벤트 + 폴백 출처 + retryable
{
  const events = await collectSse('오류 재현')
  const err = events.at(-1)!
  assert.equal(err.name, 'error')
  assert.equal(err.data.retryable, true)
  assert.equal(err.data.fallback_sources.length, 2)
}

// 6. 429 — SSE를 열지 않고 HTTP로 끊는다
{
  const res = await post('/api/chat', { message: '429 테스트' })
  assert.equal(res.status, 429)
  assert.equal(res.headers.get('Retry-After'), '600')
  assert.equal((await res.json()).retryable, false, '429는 자동 재호출 금지라 retryable=false')
}

// 7. 피드백 검증
{
  assert.equal((await post('/api/feedback', { vote: 'up' })).status, 400)
  const ok = await post('/api/feedback', { answer_request_id: 'r1', session_id: 's1', vote: 'up' })
  assert.ok((await ok.json()).feedback_id)
  const patch = await fetch(`${BASE}/api/feedback/fb_1`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason_codes: [], comment: '' }),
  })
  assert.equal(patch.status, 400, 'reason_codes가 비면 400')
}

// 8. Page<T> 봉투 · 필터 · 정렬
{
  const all = await (await fetch(`${BASE}/api/admin/knowledge/pages`)).json()
  assert.deepEqual(Object.keys(all).sort(), ['items', 'page', 'size', 'total'])
  assert.equal(all.size, 20, '기본 page size는 20')
  assert.equal(all.total, 30)
  assert.equal(all.items.length, 20)
  const filtered = await (await fetch(`${BASE}/api/admin/knowledge/pages?business=${encodeURIComponent('은닉재산 신고')}`)).json()
  assert.ok(filtered.total > 0 && filtered.items.every((p: { business_function: string }) => p.business_function === '은닉재산 신고'))
  const page2 = await (await fetch(`${BASE}/api/admin/knowledge/pages?page=2&size=10`)).json()
  assert.equal(page2.items.length, 10)
  assert.equal(page2.page, 2)
}

// 9. 쓰기 검증 — request_id·reason 필수
{
  assert.equal((await post('/api/admin/change-requests', { action: 'DELETE' })).status, 400)
  assert.equal((await post('/api/admin/change-requests', { action: 'DELETE', request_id: 'x' })).status, 400)
  const ok = await post('/api/admin/change-requests', { action: 'DELETE', request_id: 'x', reason: '폐지된 페이지', target_page_id: 'dp_syst' })
  assert.equal(ok.status, 201)
  assert.equal((await ok.json()).status, 'PENDING')
}

// 10. 권한 — 403 + request_id
{
  const res = await post('/api/admin/jobs', { type: 'REINDEX', request_id: 'x', reason: '테스트' }, { 'x-mock-role': 'VIEWER' })
  assert.equal(res.status, 403)
  const body = await res.json()
  assert.ok(body.request_id, '403에도 request_id가 있어야 한다')
  assert.ok(body.user_message.includes('OPERATOR'))
}

// 11. 파이프라인 — 6단계 · 시간이 지나면 진행 · 동시 실행 1개
{
  const created = await (await post('/api/admin/jobs', { type: 'REINDEX', request_id: 'j1', reason: '자체 점검' })).json()
  assert.equal(created.steps.length, 6)
  assert.equal(created.steps[0].name, '수집')
  const dup = await post('/api/admin/jobs', { type: 'REINDEX', request_id: 'j2', reason: '중복' })
  assert.equal(dup.status, 409, 'PIPELINE_CONCURRENCY=1이라 두 번째는 409')

  await new Promise((r) => setTimeout(r, 4_300)) // 1단계(4초) 통과
  const polled = await (await fetch(`${BASE}/api/admin/jobs/${created.id}`)).json()
  assert.equal(polled.steps[0].status, 'SUCCESS')
  assert.equal(polled.steps[1].status, 'RUNNING')
  assert.equal(polled.status, 'RUNNING')

  const cancelled = await (await post(`/api/admin/jobs/${created.id}/cancel`, { request_id: 'c1', reason: '점검 종료' })).json()
  assert.equal(cancelled.status, 'CANCELLED')
}

// 12. 점검 안내 — 문구는 서버가 준다
{
  const health = await (await fetch(`${BASE}/api/health?state=maintenance`)).json()
  assert.equal(health.maintenance, true)
  assert.ok(health.user_message.includes('kdic.or.kr'))
}

// 13. AD-008 초안 — 편집은 화면 로컬에만, 서버 쓰기는 게시 때뿐
{
  const base = await (await fetch(`${BASE}/api/admin/prompt/draft`)).json()
  assert.equal(base.change_count, 0, '서버에 초안이 쌓이지 않으니 편집 시작점은 항상 변경 0건')
  assert.equal(base.evaluation, null)
  assert.equal(base.dirty.prompt || base.dirty.fewshot || base.dirty.guardrail, false)

  const draft = {
    principles: base.principles.map((p: PromptPrinciple, i: number) => (i === 0 ? { ...p, text: '수정한 원칙' } : p)),
    fewshots: base.fewshots,
    blocklist: base.blocklist,
    masking: base.masking,
  }

  // 평가는 일시적이다 — 초안을 실어 보내고 결과만 받는다
  assert.equal((await post('/api/admin/prompt/evaluate', { request_id: 'e1' })).status, 400, 'draft 없이는 평가 불가')
  const evaluated = await (await post('/api/admin/prompt/evaluate', { request_id: 'e2', draft })).json()
  assert.equal(evaluated.gate.passed, true)
  const stillBase = await (await fetch(`${BASE}/api/admin/prompt/draft`)).json()
  assert.equal(stillBase.evaluation, null, '평가가 서버 초안을 만들면 안 된다')
  assert.equal(stillBase.principles[0].text, base.principles[0].text, '게시 전에는 편집이 서버에 없다')

  // 게시 게이트는 요청이 실어 온 판정으로 막는다(서버에 평가 결과가 남지 않으므로)
  const blocked = await post('/api/admin/prompt/publish', { request_id: 'p1', reason: '게이트 미통과', draft, gate_passed: false })
  assert.equal(blocked.status, 409)
  assert.equal((await post('/api/admin/prompt/publish', { request_id: 'p2', reason: '초안 없음' })).status, 400)

  const published = await (await post('/api/admin/prompt/publish', { request_id: 'p3', reason: '원칙 문구 수정', draft, gate_passed: true })).json()
  assert.equal(published.version, base.draft_version)
  const promoted = await (await fetch(`${BASE}/api/admin/prompt/draft`)).json()
  assert.equal(promoted.base_version, base.draft_version, '게시본이 새 기준값이 된다')
  assert.equal(promoted.principles[0].text, '수정한 원칙', '게시 시점에 비로소 서버가 편집 내용을 갖는다')
  assert.equal(promoted.change_count, 0)
}

// 14) 답변 본문에 URL·전화번호가 없다
// 시스템 프롬프트 원칙 3(prompt_builder.py)이 "URL·웹사이트 주소·전화번호를 답변에 직접 쓰지 마세요.
// 서류 안내와 신청 페이지, 출처 링크는 시스템이 답변 뒤에 별도로 붙여줍니다"라고 금지한다.
// 목 답변이 이 규칙을 어기면 실제 백엔드가 만들 답변과 달라져, 화면이 잘못된 전제 위에서 검증된다.
{
  const { MOCK_SCENARIOS } = await import('./data/chat')
  const FORBIDDEN = /https?:\/\/|\b[a-z0-9-]+\.(?:kdic\.or\.kr|or\.kr|co\.kr|com)\b|\b1[0-9]{3}\b|\d{2,4}-\d{3,4}-\d{4}/i
  for (const s of MOCK_SCENARIOS) {
    const hit = s.answer.match(FORBIDDEN)
    assert.ok(
      hit === null,
      `답변 본문에 URL·전화번호가 있으면 안 된다 (${s.id ?? '시나리오'}): ${hit?.[0]}`,
    )
  }
}

server.close()
console.log('mocks selfcheck: 14개 항목 모두 통과')
