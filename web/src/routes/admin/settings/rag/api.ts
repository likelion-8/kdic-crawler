/** AD-007 RAG 파라미터 설정 · A/B 비교 — 이 화면이 부르는 API 계약.
 *
 * CM-DF-003 04절에 이 화면의 엔드포인트가 없다(12-ad-007-008 §4.4 "기획서엔 엔드포인트 명시 없음").
 * 프론트가 정한 시그니처이며 `mocks/handlers/extra/ad-eval-rag.ts`가 이 모양을 돌려준다.
 * 파라미터 현행값·반영 시점의 정본은 CM-DF-003 05절 표이며 **서버가 내려준다**(화면 하드코딩 금지). */
import { apiRequest } from '../../../../lib/api/client'
import type { Page } from '../../../../lib/api/types'

export type ParamValue = number | boolean | string

/** 반영 시점 — CM-DF-003 05절 '반영 시점' 열. 무중단 = 재색인 불필요 */
export type ApplyTiming = '무중단' | '재적재 필요'

/** 컨트롤 종류는 CM-DF-001 04절 4종에 대응한다 */
export type ParamControl = 'stepper' | 'toggle' | 'slider' | 'select'

export interface RagParam {
  key: string
  /** 카드에 그대로 찍는 라벨 (AD-007 §1.3·§1.4 원문) */
  label: string
  /** ① 검색 시점 파라미터 / ② 답변 생성 설정 */
  group: 'retrieval' | 'generation'
  control: ParamControl
  apply_timing: ApplyTiming
  min?: number
  max?: number
  step?: number
  /** select 전용 */
  options?: string[]
  /** slider 눈금 — "방향을 반드시 드러낼 것"(CM-DF-001 04절) */
  scale_start?: string
  scale_end?: string
  /** 라벨 아래 보조 설명(예: `링크 안내 질의 전용`) */
  note?: string
}

/** ④ 정량 비교 결과 (AD-007 §1.6) */
export interface QuantMetric {
  label: string
  a: number
  b: number
}

export interface QuantCompare {
  /** 분모 기준 안내 한 줄. 서버 문구 그대로 */
  basis: string
  metrics: QuantMetric[]
  improved: number
  regressed: number
  /** `→ A 유지 권장` 같은 판정 문구 */
  recommendation: string
}

/** ③ 초안 평가 결과 = 배포 게이트 (AD-007 §1.6 · Desc 0 ③) */
export interface RagGate {
  /** 최신 평가가 게이트를 통과했는가. false면 [운영 반영] 불가 */
  passed: boolean
  /** 평가 시점의 초안 지문. 현재 초안과 다르면 평가가 무효화된다(Desc 0) */
  draft_signature: string | null
  evaluated_at: string | null
  /** 미통과 사유. 서버 문구 그대로 노출 */
  blocked_reason: string | null
  /** 게이트는 통과했지만 현행보다 낮아진 지표가 있을 때의 경고 문구 */
  warning: string | null
  holdout_total: number
  holdout_passed: number
  smoke_total: number
  smoke_passed: number
  quantitative: QuantCompare | null
}

export interface RagParamsResponse {
  params: RagParam[]
  /** 현행 운영값 */
  current: Record<string, ParamValue>
  /** 편집 중 초안. 없으면 현행과 같다 */
  draft: Record<string, ParamValue> | null
  gate: RagGate
}

export interface AbHit {
  rank: number
  title: string
  doc_id: string
  score: number
  /** 정답 포함 여부(✓) */
  is_answer: boolean
}

export interface AbColumn {
  /** `A. 현행 운영값` / `B. 초안 (편집 중)` */
  label: string
  /** 설정 요약 칩 */
  chips: string[]
  /** B에서 바뀐 칩만 주황 강조 (AD-007 §1.5) */
  changed_chips: string[]
  hits: AbHit[]
}

export interface AbSearchResponse {
  query: string
  a: AbColumn
  b: AbColumn
}

/** ⑤ 설정 이력 1행 (AD-007 §1.7) */
export interface RagHistoryEntry {
  id: string
  changed_at: string
  /** `복합 질문 분해 Off → On` */
  summary: string
  actor: string
  reason: string
}

const BASE = '/api/admin/rag-params'

export const ragKeys = {
  params: ['rag', 'params'] as const,
  history: ['rag', 'history'] as const,
}

export function fetchParams() {
  return apiRequest<RagParamsResponse>(BASE)
}

/** [초안 평가] — 평가셋(홀드아웃 계열, 편집 반영) + A/B를 현재 인덱스에서 즉시 실행 (Desc 0 ②) */
export function evaluateDraft(draft: Record<string, ParamValue>) {
  return apiRequest<RagGate>(`${BASE}/evaluate`, { method: 'POST', body: { draft } })
}

/** [비교 실행] — 같은 질문으로 A/B 동시 검색. 결과를 저장하지 않는다(§1.5) */
export function abSearch(query: string, draft: Record<string, ParamValue>) {
  return apiRequest<AbSearchResponse>(`${BASE}/ab-search`, { method: 'POST', body: { query, draft } })
}

/** [운영 반영] — 사유 필수. 무중단 즉시 적용, 실패 시 이전 버전 유지 (Desc 0 ③) */
export function applyDraft(draft: Record<string, ParamValue>, reason: string) {
  return apiRequest<RagParamsResponse>(`${BASE}/apply`, { method: 'POST', body: { draft }, reason })
}

export function fetchHistory() {
  return apiRequest<Page<RagHistoryEntry>>(`${BASE}/history`)
}

/** [롤백] — 그 시점 값으로 **초안만** 복원한다. 실제 적용은 [운영 반영]이 해야 한다(§1.7) */
export function rollbackTo(id: string) {
  return apiRequest<{ draft: Record<string, ParamValue> }>(`${BASE}/history/${id}/rollback`, {
    method: 'POST',
    body: {},
  })
}
