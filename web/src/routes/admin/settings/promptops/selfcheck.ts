/** AD-008 로컬 초안 자체 점검 — `pnpm check`가 돌린다.
 *
 * 서버 자동 저장을 걷어내면서 서버가 주던 파생값(change_count·dirty)과 초안 보관을 화면이 떠안았다.
 * 이 셋만 본다 — 깨지면 편집 흔적이 사라지거나 남의 게시분을 덮어쓴다.
 *  ① change_count : 수정·추가·삭제·순서 변경·토글을 각각 1건으로 센다
 *  ② 복구 판정 : base_version이 같을 때만 되살리고, 다르면(다른 관리자가 게시) 버린다
 *  ③ deriveDraft : 기준값 위에 로컬 편집분을 얹은 결과가 카드가 그리는 초안이다
 * 훅(useLocalDraft)은 렌더가 필요해 여기서 돌리지 않는다 — 판정 로직만 순수 함수로 뽑아 검사한다. */
/// <reference types="node" />
// ↑ tsconfig.app.json의 types는 vite/client뿐이다. 이 파일만 node에서 도는 스크립트라 여기서만 끌어온다.
import assert from 'node:assert/strict'
import type { PromptDraft, PromptDraftContent } from './api'
import { countChanges, deriveDraft, isStale, parseStored } from './useLocalDraft'

const BASE: PromptDraft = {
  draft_version: 'v1.5',
  base_version: 'v1.4',
  base_updated_at: '2026-07-30T14:20:00+09:00',
  change_count: 0,
  principles: [
    { id: 'p1', text: '근거 자료에 있는 내용만으로 답변', dirty: false },
    { id: 'p2', text: '금액·날짜·연락처는 원문 그대로만 인용', dirty: false },
  ],
  locked_principle: '근거 사용 마커 표기',
  char_count: 778,
  dirty: { prompt: false, fewshot: false, guardrail: false },
  fewshots: [{ id: 'fs_1', question: '보호 한도는?', answer: '5천만원입니다.' }],
  blocklist: {
    active: true,
    items: [
      { id: 'bw_01', pattern: '수익 보장', type: '단어', scope: '답변', action: '차단', active: true },
      { id: 'bw_02', pattern: '원금 보장', type: '단어', scope: '답변', action: '차단', active: true },
    ],
  },
  masking: {
    active: true,
    items: [
      { id: 'mk_01', name: '주민등록번호', pattern: '\\d{6}[-]\\d{7}', replacement: '******-*******', validated: true, sample_count: 12, active: true },
    ],
  },
  evaluation: null,
}

const content = (): PromptDraftContent => structuredClone({
  principles: BASE.principles,
  fewshots: BASE.fewshots,
  blocklist: BASE.blocklist,
  masking: BASE.masking,
})

// ① change_count — 편집 종류별로 1건씩
{
  assert.equal(countChanges(BASE, content()).total, 0, '편집이 없으면 0건이다')

  const edited = content()
  edited.principles[1] = { ...edited.principles[1], text: '금액은 원문 그대로만 인용' }
  const one = countChanges(BASE, edited)
  assert.deepEqual(one, { prompt: 1, fewshot: 0, guardrail: 0, total: 1 }, '원칙 1행 수정 = 1건')

  const added = content()
  added.principles.push({ id: 'p_new', text: '새 원칙', dirty: true })
  assert.equal(countChanges(BASE, added).prompt, 1, '원칙 추가 = 1건')

  const moved = content()
  moved.principles.reverse()
  assert.equal(countChanges(BASE, moved).prompt, 2, '순서 변경도 편집이다 — 자리가 바뀐 2행')

  const removed = content()
  removed.blocklist.items = removed.blocklist.items.slice(1)
  assert.equal(countChanges(BASE, removed).guardrail, 1, '금칙어 1건 제외 = 1건(뒤 행이 당겨져도 1건)')

  const toggled = content()
  toggled.masking.active = false
  assert.equal(countChanges(BASE, toggled).guardrail, 1, '마스킹 스위치 = 1건')

  const restored = content()
  restored.blocklist.items = [restored.blocklist.items[1], restored.blocklist.items[0]]
  assert.equal(countChanges(BASE, restored).guardrail, 0, '규칙 목록은 순서에 의미가 없다')
}

// ② 복구 / 폐기 판정 — base_version이 같을 때만 되살린다
{
  const saved = JSON.stringify({ base_version: 'v1.4', content: content(), saved_at: '2026-08-04T09:00:00+09:00' })
  const stored = parseStored(saved)
  assert.ok(stored, '내가 쓴 값은 그대로 읽힌다')
  assert.equal(isStale(stored, 'v1.4'), false, '기준값이 같으면 복구한다(새로고침·탭 이탈 복귀)')
  assert.equal(isStale(stored, 'v1.5'), true, '그 사이 다른 관리자가 게시했으면 버린다')
  assert.equal(isStale(stored, undefined), false, '초안 조회 전에는 판단하지 않는다')
  assert.equal(isStale(null, 'v1.4'), false)

  assert.equal(parseStored(null), null, '보관된 초안이 없으면 null')
  assert.equal(parseStored('{'), null, '깨진 값에 화면이 넘어가지 않는다')
  assert.equal(parseStored('{"base_version":"v1.4"}'), null, '형식이 어긋난 옛 값은 버린다')
}

// ③ deriveDraft — 기준값 + 로컬 편집분
{
  const untouched = deriveDraft(BASE, null, null)
  assert.equal(untouched.change_count, 0)
  assert.equal(untouched.dirty.prompt, false)

  const edited = content()
  edited.principles[0] = { ...edited.principles[0], text: '근거 자료에 있는 내용만으로 답변한다' }
  const merged = deriveDraft(BASE, edited, null)
  assert.equal(merged.change_count, 1)
  assert.deepEqual(merged.dirty, { prompt: true, fewshot: false, guardrail: false }, '탭·카드 빨간 점')
  assert.equal(merged.principles[0].dirty, true, '수정한 행에만 점이 붙는다')
  assert.equal(merged.principles[1].dirty, false)
  assert.equal(merged.char_count, 778 + 2, "전문 길이는 기준값에서 본문 길이 차이('한다' 2자)만큼만 움직인다")
  assert.equal(merged.base_version, 'v1.4', '기준값(버전·잠긴 원칙)은 서버 것을 그대로 쓴다')
}

console.log('ad-008 로컬 초안 selfcheck: 통과')
