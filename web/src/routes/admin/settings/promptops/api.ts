/** AD-008 프롬프트·가드레일 / AD-009 운영 정책 API 계약 + 호출부.
 *
 * 두 화면의 엔드포인트는 CM-DF-003 04절에 없다. 기획서 12절 §4.4 · 13절 §12의 '추정 API 접점'을
 * 그대로 옮긴 것이라 백엔드와 계약을 맞출 때 이 파일이 협의 대상이다(report backend_notes 참조).
 * 목은 src/mocks/handlers/extra/ad-prompt-ops.ts 가 이 타입을 그대로 구현한다. */
import type { Page, Source } from '../../../../lib/api/types'
import type { BusinessFunction } from '../../../../lib/codes'
import { apiRequest } from '../../../../lib/api/client'
import { markReauthed } from '../../../../app/session'

// ---------------------------------------------------------------- AD-008 타입

export interface PromptPrinciple {
  id: string
  /** 번호를 뺀 본문. 순번은 화면이 붙인다 */
  text: string
  /** 초안에서 수정된 행 — 행 오른쪽 위 빨간 점(AD-008 §2.4) */
  dirty: boolean
}

export interface FewshotExample {
  id: string
  question: string
  answer: string
}

export type BlocklistType = '단어' | '정규식' | '사전'
export type GuardrailScope = '질문' | '답변' | '질문 + 답변'

export interface BlocklistRule {
  id: string
  pattern: string
  type: BlocklistType
  scope: GuardrailScope
  action: string
  active: boolean
}

export interface MaskingRule {
  id: string
  name: string
  pattern: string
  replacement: string
  /** 패턴을 고치면 false. 샘플 검증을 통과해야 저장할 수 있다(§2.6) */
  validated: boolean
  sample_count: number
  active: boolean
}

/** 유지 ✓ / 개선 △ / 회귀 ✗ (§2.7 Description 4) */
export type EvalVerdict = 'KEEP' | 'IMPROVED' | 'REGRESSED'

export interface PromptEvalItem {
  id: string
  question: string
  verdict: EvalVerdict
  /** 판정 한 줄 사유 */
  note: string
  before: { answer: string; sources: Source[] }
  after: { answer: string; sources: Source[] }
}

export interface PromptGate {
  passed: boolean
  source_attached: { passed: boolean; count: number; total: number }
  out_of_scope: { passed: boolean; count: number; total: number }
  guardrail: { passed: boolean }
}

export interface PromptEvaluation {
  ran_at: string
  summary: { total: number; keep: number; improved: number; regressed: number }
  items: PromptEvalItem[]
  gate: PromptGate
}

/** 편집 대상 4종. AD-008은 이걸 로컬(localStorage)에 들고 있다가 평가·게시 때 실어 보낸다.
 *  base_version·change_count·dirty 같은 파생값은 화면이 기준값과 비교해 스스로 계산하므로 보내지 않는다. */
export interface PromptDraftContent {
  principles: PromptPrinciple[]
  fewshots: FewshotExample[]
  blocklist: { active: boolean; items: BlocklistRule[] }
  masking: { active: boolean; items: MaskingRule[] }
}

export interface PromptDraft extends PromptDraftContent {
  draft_version: string
  base_version: string
  base_updated_at: string
  change_count: number
  /** 편집 불가 시스템 원칙 — 항상 마지막 행(§2.4) */
  locked_principle: string
  char_count: number
  /** 탭·카드 제목 오른쪽 위 빨간 점 */
  dirty: { prompt: boolean; fewshot: boolean; guardrail: boolean }
  /** 초안을 수정하면 null — 평가가 무효화된다(§2.2) */
  evaluation: PromptEvaluation | null
}

export interface PromptVersion {
  version: string
  created_at: string
  author: string
  reason: string
  status: '현행' | '보관' | '실패'
  /** 긴급 롤백(CM-DF-004 05절 REQ-OPS-003) 후보 = 직전 정상 버전 */
  emergency_candidate: boolean
}

/** 게시 직후 Smoke 결과 — 문항 수는 서버가 정한다(프론트는 세트 크기를 알지 않는다) */
export interface PublishResult {
  version: string
  smoke: { passed: number; total: number }
}

export interface ValidationResult {
  passed: boolean
  sample_count?: number
  message: string
}

// ---------------------------------------------------------------- AD-009 타입

export interface OpsPolicy {
  version: string
  ip_per_min: number
  ip_per_day: number
  session_per_30min: number
  /** 서버 고정값. 화면은 표시만 한다(13절 H-4) */
  burst_per_10s: number
  over_limit_message: string
  auto_purge: boolean
}

export interface CacheStats {
  hit_rate: number
  saved_generations: number
  entries: number
  extension: string
  /** false면 값이 아니라 '예정' 표시로 회색 처리한다(13절 M-2) */
  extension_applied: boolean
  last_purged_at: string
  last_purge_reason: string
}

export interface BlockEntry {
  id: string
  subject: string
  kind: 'IP' | '세션'
  reason: string
  blocked_at: string
  expires_at: string
  /** 누적 차단 횟수. 2회 이상이면 행 전체를 붉게 강조(§6) */
  count: number
}

/** GET/PUT /api/admin/suggested-questions — 목록 전체를 통째로 교체한다(handlers/admin.ts) */
export interface SuggestedQuestion {
  id: string
  text: string
  business_function: BusinessFunction
  active: boolean
  order: number
  /** 최근 7일 클릭. 집계 경로가 없어 서버가 null 을 내린다(admin_ops.py:401) */
  click_count: number | null
}

// ---------------------------------------------------------------- 쿼리 키

export const promptKeys = {
  draft: ['admin', 'prompt', 'draft'] as const,
  versions: ['admin', 'prompt', 'versions'] as const,
}

export const opsKeys = {
  policy: ['admin', 'ops-policy'] as const,
  cache: ['admin', 'cache', 'stats'] as const,
  blocks: ['admin', 'blocks'] as const,
  suggestions: ['admin', 'suggested-questions'] as const,
}

// ---------------------------------------------------------------- 공통

/** 위험 작업 비밀번호 재확인. 성공하면 재확인 30분·유휴 30분이 함께 갱신된다(CM-DF-003 04절) */
export async function reauthenticate(password: string): Promise<void> {
  await apiRequest('/api/admin/reauth', { method: 'POST', body: { password } })
  markReauthed()
}

/** 사유가 필요한 쓰기 — client.ts가 request_id와 reason을 본문에 넣는다 */
function write<T>(path: string, reason: string, body?: unknown): Promise<T> {
  return apiRequest<T>(path, { method: 'POST', body, reason })
}

// ---------------------------------------------------------------- AD-008 호출

/** 편집 시작점 — 서버는 게시본 기준값을 준다. 그 위에 얹는 편집은 로컬에만 쌓인다 */
export const fetchPromptDraft = () => apiRequest<PromptDraft>('/api/admin/prompt/draft')

/** @deprecated AD-008은 로컬 초안(localStorage)이라 호출하지 않는다 — 서버 쓰기는 게시 때뿐이다.
 *  초안 API를 쓰는 다른 화면과 백엔드 계약 문서 대조를 위해 시그니처만 남긴다. */
export const savePromptDraft = (patch: Partial<PromptDraft>) =>
  apiRequest<PromptDraft>('/api/admin/prompt/draft', { method: 'PUT', body: patch })

/** @deprecated AD-008은 로컬 초안이라 호출하지 않는다 — 되돌리기는 [초기화](로컬 비우기)로 끝난다.
 *  초안 API를 쓰는 다른 화면과 백엔드 계약 문서 대조를 위해 시그니처만 남긴다. */
export const discardPromptDraft = (reason: string) =>
  write<PromptDraft>('/api/admin/prompt/draft/discard', reason)

/** [전후 비교] — 초안을 실어 보내 일시 평가한다. 서버 초안을 만들지도 바꾸지도 않는다 */
export const evaluatePrompt = (draft: PromptDraftContent) =>
  apiRequest<PromptEvaluation>('/api/admin/prompt/evaluate', { method: 'POST', body: { draft } })

export const fetchPromptVersions = (page: number, size: number) =>
  apiRequest<Page<PromptVersion>>(`/api/admin/prompt/versions?page=${page}&size=${size}`)

export const rollbackVersion = (version: string, reason: string) =>
  write<PromptDraft>(`/api/admin/prompt/versions/${encodeURIComponent(version)}/rollback`, reason)

export const emergencyRollback = (version: string, reason: string) =>
  write<PromptVersion>(`/api/admin/prompt/versions/${encodeURIComponent(version)}/emergency-rollback`, reason)

/** [게시] — 이 시점에 비로소 초안이 서버에 저장되고 운영에 반영된다.
 *  `gate_passed`는 직전 [초안 평가]의 회귀 게이트 결과다. 평가가 일시적이라 서버가 들고 있지 않아 함께 보낸다.
 *
 *  ⚠ 요청/승인 2단계는 없앴다(팀 결정 2026-08-04) — 편집 권한자(EDITOR 이상)가 바로 게시한다.
 *  사전 차단은 회귀 게이트가, 사후 추적은 활동 로그(AD-011)와 긴급 롤백이 맡는다. */
export const publishPrompt = (reason: string, draft: PromptDraftContent, gate_passed: boolean) =>
  write<PublishResult>('/api/admin/prompt/publish', reason, { draft, gate_passed })

export const validateMasking = (pattern: string, replacement: string) =>
  apiRequest<ValidationResult>('/api/admin/guardrails/masking/validate', {
    method: 'POST',
    body: { pattern, replacement },
  })

// ---------------------------------------------------------------- AD-009 호출

export const fetchOpsPolicy = () => apiRequest<OpsPolicy>('/api/admin/ops-policy')

export const saveOpsPolicy = (patch: Partial<OpsPolicy>, reason: string) =>
  apiRequest<OpsPolicy>('/api/admin/ops-policy', { method: 'PUT', body: patch, reason })

export const fetchCacheStats = () => apiRequest<CacheStats>('/api/admin/cache/stats')

export const purgeCache = (scope: 'query' | 'all', reason: string, query?: string) =>
  write<CacheStats>('/api/admin/cache/purge', reason, { scope, query })

export const fetchBlocks = (page: number, size: number) =>
  apiRequest<Page<BlockEntry>>(`/api/admin/blocks?page=${page}&size=${size}`)

export const releaseBlock = (id: string, reason: string) =>
  write<void>(`/api/admin/blocks/${id}/release`, reason)

export const fetchSuggestedQuestions = () =>
  apiRequest<Page<SuggestedQuestion>>('/api/admin/suggested-questions?size=50')

/** 목록 전체 교체(PUT). 사유는 활동 로그용이라 조작별로 다르게 넣는다 */
export const saveSuggestedQuestions = (items: SuggestedQuestion[], reason: string) =>
  apiRequest<Page<SuggestedQuestion>>('/api/admin/suggested-questions', {
    method: 'PUT',
    body: { items },
    reason,
  })

/** 저장 전 가드레일 금칙어 검사 — 미통과면 저장 차단(CM-DF-004 07절) */
export const validateSuggestion = (text: string, business_function: BusinessFunction) =>
  apiRequest<ValidationResult>('/api/admin/suggested-questions/validate', {
    method: 'POST',
    body: { text, business_function },
  })
