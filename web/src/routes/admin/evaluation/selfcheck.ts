/** AD-006 평가 실행 이력 계약 자체 점검 — `pnpm check`가 돌린다.
 *
 * 이 화면에서 서버가 책임지는 세 가지만 본다(검증 D013·D098·D104):
 *  ① '핵심 결과'의 지표 라벨까지 서버가 준다
 *  ② '대상'은 서버가 실제로 넣는 두 값(운영 설정 · RAG)뿐이다
 *  ③ 대상·출처 필터와 페이지를 서버가 처리한다(한 장만 받아 화면에서 자르지 않는다)
 * 목을 고쳤는데 여기가 깨지면 화면도 깨진 것이다. */
/// <reference types="node" />
import assert from 'node:assert/strict'
import { setupServer } from 'msw/node'
import type { EvaluationRun } from './api'
import type { Page } from '../../../lib/api/types'

// 핸들러 경로가 상대 경로라 node에는 붙일 오리진이 없다 — mocks/selfcheck.ts와 같은 처리
Object.defineProperty(globalThis, 'location', { value: new URL('http://localhost/'), writable: true })
const { adEvalRagHandlers } = await import('../../../mocks/handlers/extra/ad-eval-rag')

const server = setupServer(...adEvalRagHandlers)
server.listen({ onUnhandledRequest: 'error' })

const get = async (query: string): Promise<Page<EvaluationRun>> => {
  const res = await fetch(`http://localhost/api/admin/evaluations/runs?${query}`)
  assert.equal(res.status, 200)
  return (await res.json()) as Page<EvaluationRun>
}

const all = await get('page=1&size=50&sort=started_at:desc')
assert.ok(all.total > 0, '실행 이력이 비어 있다')

// ① 지표 축 — 정확도/MRR/생성 한 종류다(프롬프트 계열 축은 서버가 그런 실행을 만들지 않는다)
for (const run of all.items) {
  if (run.status === 'RUNNING' || run.status === 'QUEUED') continue
  const labels = run.metrics.map((m) => m.label)
  assert.deepEqual(labels, ['정확도', 'MRR', '생성'], `${run.run_id}의 지표 축이 다르다`)
  assert.ok(run.metrics.every((m) => m.value !== ''), '표시값은 서버가 완성해 준다')
}

// ② 대상 어휘 — 서버가 넣지 않는 값이 목에 섞이면 필터가 영구 0건이 된다
const targets = new Set(all.items.map((r) => r.target))
for (const t of targets) {
  assert.ok(['운영 설정', 'RAG'].includes(t), `서버가 넣지 않는 대상 값이다: ${t}`)
}

// ③ 필터·페이지는 서버 몫. total은 자른 배열이 아니라 조건에 맞는 전체 건수다
const ragOnly = await get(`page=1&size=50&target=${encodeURIComponent('RAG')}`)
assert.ok(ragOnly.total > 0 && ragOnly.total < all.total, '대상 필터가 서버에서 걸리지 않는다')
assert.ok(ragOnly.items.every((r) => r.target === 'RAG'))

const bySource = await get(`page=1&size=50&source=${encodeURIComponent('RAG 파라미터 평가')}`)
assert.ok(bySource.items.every((r) => r.source === 'RAG 파라미터 평가'), '출처 필터가 서버에서 걸리지 않는다')

const first = await get('page=1&size=2&sort=started_at:desc')
const second = await get('page=2&size=2&sort=started_at:desc')
assert.equal(first.items.length, 2)
assert.equal(first.total, all.total, 'total은 그 페이지 길이가 아니라 전체 건수여야 한다')
assert.notEqual(first.items[0].run_id, second.items[0].run_id, '페이지가 서버에서 넘어가지 않는다')
// 최신순 정렬 — '(현재 운영)' 뱃지와 '평가셋 vN부터' 경계 판정이 이 순서를 전제한다
const times = all.items.map((r) => r.started_at)
assert.deepEqual(times, [...times].sort().reverse(), '최신순이 아니다')

server.close()
console.log('ad-settings eval runs selfcheck: 통과')
