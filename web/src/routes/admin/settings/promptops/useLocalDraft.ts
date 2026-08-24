/** AD-008 로컬 초안 — 편집은 화면 안에만 쌓이고, 서버 쓰기는 [게시] 때뿐이다.
 *
 * 왜 localStorage인가: 서버 자동 저장(CM-DF-003 04절 `PUT /api/admin/drafts/{screen}` 10초)을 걷어내면
 * 편집 도중 새로고침·탭 이탈에 편집분이 통째로 날아간다. 같은 목적(세션 끊김 보호)을 브라우저가 대신한다.
 * 한계: 같은 브라우저에서만 이어진다 — 다른 기기·시크릿 창에서는 이어서 편집할 수 없다.
 *
 * 왜 base_version이 같을 때만 복구하나: 내가 편집하는 사이 다른 관리자가 게시하면 기준값이 바뀐다.
 * 낡은 기준 위에서 만든 편집분을 새 기준에 되살리면 남의 게시분을 조용히 덮어쓰게 된다. 그래서 버린다.
 *
 * 파생값(change_count·dirty·char_count)도 여기서 계산한다 — 서버가 초안을 들고 있지 않기 때문이다. */
import { useEffect, useState } from 'react'
import type { PromptDraft, PromptDraftContent, PromptEvaluation, PromptPrinciple } from './api'

/** v1 = 값 형식 버전. 형식을 바꾸면 키를 올려 옛 값이 저절로 무시되게 한다 */
export const LOCAL_DRAFT_KEY = 'kdic.admin.prompt-draft.v1'

export interface StoredDraft {
  /** 어느 게시본 위에서 편집했는지 — 복구 여부를 가르는 유일한 기준 */
  base_version: string
  content: PromptDraftContent
  saved_at: string
}

/** 형식이 어긋난 값(손으로 고쳤거나 옛 버전)은 조용히 버린다 — 화면이 깨지는 것보다 낫다 */
export function parseStored(raw: string | null): StoredDraft | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as StoredDraft
    return typeof value?.base_version === 'string' && Array.isArray(value?.content?.principles) ? value : null
  } catch {
    return null
  }
}

/** 복구 판정 — 기준값이 그대로일 때만 되살린다(위 주석) */
export function isStale(stored: StoredDraft | null, baseVersion: string | undefined): boolean {
  return stored !== null && baseVersion !== undefined && stored.base_version !== baseVersion
}

// localStorage는 사파리 시크릿·용량 초과에서 던진다. 편집을 막을 이유는 아니라 삼킨다(메모리로는 계속된다)
function readRaw(): string | null {
  try {
    return window.localStorage.getItem(LOCAL_DRAFT_KEY)
  } catch {
    return null
  }
}

function writeRaw(value: StoredDraft): void {
  try {
    window.localStorage.setItem(LOCAL_DRAFT_KEY, JSON.stringify(value))
  } catch {
    /* 저장만 못 할 뿐 편집은 이어진다 */
  }
}

function removeRaw(): void {
  try {
    window.localStorage.removeItem(LOCAL_DRAFT_KEY)
  } catch {
    /* 지울 수 없으면 base_version 불일치 판정이 다음 진입에서 다시 버린다 */
  }
}

export interface LocalDraft {
  /** 서버 기준값 위에 얹을 편집분. 없으면 null */
  content: PromptDraftContent | null
  /** 편집하는 사이 다른 관리자가 게시해 초안을 버렸다 — 화면이 안내를 띄운다 */
  discarded: boolean
  save: (content: PromptDraftContent) => void
  clear: () => void
}

export function useLocalDraft(baseVersion: string | undefined): LocalDraft {
  // 초안 조회가 끝나기 전 첫 렌더에는 baseVersion이 없다. 값은 한 번만 읽고 비교는 렌더에서 한다
  const [stored, setStored] = useState<StoredDraft | null>(() => parseStored(readRaw()))
  const discarded = isStale(stored, baseVersion)

  // 낡은 초안은 즉시 지운다. 안내는 이번 방문 동안만 남기면 되므로 메모리 값(stored)은 그대로 둔다
  useEffect(() => {
    if (discarded) removeRaw()
  }, [discarded])

  return {
    content: discarded ? null : (stored?.content ?? null),
    discarded,
    save: (content) => {
      const next: StoredDraft = { base_version: baseVersion ?? '', content, saved_at: new Date().toISOString() }
      setStored(next)
      writeRaw(next)
    },
    clear: () => {
      setStored(null)
      removeRaw()
    },
  }
}

// ---------------------------------------------------------------- 파생값 계산

/** 평가·게시에 실어 보낼 4종만 뽑는다 */
export function contentOf(draft: PromptDraft): PromptDraftContent {
  return {
    principles: draft.principles,
    fewshots: draft.fewshots,
    blocklist: draft.blocklist,
    masking: draft.masking,
  }
}

/** 키 순서에 흔들리지 않는 비교용 서명 */
const sig = (item: object): string =>
  JSON.stringify(Object.entries(item).sort(([a], [b]) => (a < b ? -1 : 1)))

/** 순서가 곧 내용인 목록(원칙 = 프롬프트 본문 순서) — 자리마다 비교한다 */
function countByPosition(base: string[], next: string[]): number {
  let changed = 0
  for (let i = 0; i < Math.max(base.length, next.length); i += 1) {
    if (base[i] !== next[i]) changed += 1
  }
  return changed
}

/** 순서에 의미가 없는 목록(규칙·예시) — id로 맞춰 수정·추가·삭제를 각 1건으로 센다 */
function countById<T extends { id: string }>(base: T[], next: T[]): number {
  const before = new Map(base.map((item) => [item.id, sig(item)]))
  const alive = new Set(next.map((item) => item.id))
  return (
    next.filter((item) => before.get(item.id) !== sig(item)).length +
    base.filter((item) => !alive.has(item.id)).length
  )
}

export interface DraftChanges {
  prompt: number
  fewshot: number
  guardrail: number
  total: number
}

/** 상태 바의 '변경 N건'과 탭·카드 빨간 점의 근거 */
export function countChanges(base: PromptDraftContent, next: PromptDraftContent): DraftChanges {
  const prompt = countByPosition(
    base.principles.map((p) => p.text),
    next.principles.map((p) => p.text),
  )
  const fewshot = countById(base.fewshots, next.fewshots)
  const guardrail =
    countById(base.blocklist.items, next.blocklist.items) +
    countById(base.masking.items, next.masking.items) +
    (base.blocklist.active === next.blocklist.active ? 0 : 1) +
    (base.masking.active === next.masking.active ? 0 : 1)
  return { prompt, fewshot, guardrail, total: prompt + fewshot + guardrail }
}

const textLength = (list: PromptPrinciple[]) => list.reduce((n, p) => n + p.text.length, 0)

/** 서버 기준값 + 로컬 편집분 + 일시 평가 = 화면이 그리는 초안 */
export function deriveDraft(
  baseline: PromptDraft,
  content: PromptDraftContent | null,
  evaluation: PromptEvaluation | null,
): PromptDraft {
  if (!content) return { ...baseline, evaluation }
  const changes = countChanges(baseline, content)
  return {
    ...baseline,
    ...content,
    // 행 오른쪽 빨간 점 — 순서 변경도 편집이라 자리로 비교한다(countByPosition과 같은 기준)
    principles: content.principles.map((p, i) => ({ ...p, dirty: p.text !== baseline.principles[i]?.text })),
    // 전문 길이(778자)는 서버가 준 값이다. 로컬 편집분은 원칙 본문 길이 차이만큼만 움직인다
    char_count: baseline.char_count + textLength(content.principles) - textLength(baseline.principles),
    change_count: changes.total,
    dirty: { prompt: changes.prompt > 0, fewshot: changes.fewshot > 0, guardrail: changes.guardrail > 0 },
    evaluation,
  }
}
