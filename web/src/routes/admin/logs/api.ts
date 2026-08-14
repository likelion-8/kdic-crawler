/** AD-005 데이터 접점 · 표기 규칙.
 *
 * 관리자 대화 로그 API는 CM-DF-003 04절에 없어 여기서 정했다(11 §3 제안 시그니처).
 * lib/api/types.ts로 올려야 할 후보 — report의 shared_needed 참조.
 * 질문·답변·의견은 모두 마스킹된 저장본이다. 원문 복원 진입점은 만들지 않는다(Desc 2). */
import { apiRequest } from '../../../lib/api/client'
import type { Page } from '../../../lib/api/types'
import type { BusinessFunction, ErrorCode, Intent, QuestionType, TriageStatus } from '../../../lib/codes'
import { TIMEZONE } from '../../../lib/constants'
import { formatDate, formatTime } from '../../../lib/format'

// ---------------------------------------------------------------- 스키마

export type LogStatus = 'NORMAL' | 'OUT_OF_SCOPE' | 'FAILED'
export type FeedbackVote = 'up' | 'down'

export interface ConversationLogRow {
  request_id: string
  occurred_at: string
  /** 마스킹된 저장본 */
  question_masked: string
  intent: Intent
  status: LogStatus
  feedback: FeedbackVote | null
  source_count: number | null
  latency_s: number | null
  triage: TriageStatus
}

export interface LogSummary {
  total: number
  normal: number
  out_of_scope: number
  failed: number
  feedback_up: number
  feedback_down: number
}

/** 실행 추적(검색 후보·단계별 소요)은 Langfuse가 전담한다(2026-08-04 팀 결정).
 *
 * 원래 이 화면은 `rag_retrieval_results` 테이블(검색 후보/선정/점수)과 단계별 timings를
 * 직접 그렸는데, 그 테이블은 질문 1건당 20행 부담 대비 실익이 낮다고 판단해 삭제됐고
 * `rag_runs`에는 `total_latency_ms` 하나뿐이라 단계별 시간도 원천이 없다(src/schema.py).
 * 두 구획을 목업대로 남겨 두면 실서버에서 영구히 빈 채로 뜨는데, 빈 상태 문구가
 * '검색 근거가 사용되지 않았습니다'라 운영자에게 거짓을 말하게 된다.
 *
 * 그래서 화면은 **rag_runs가 실제로 가진 것만** 그리고, 추적은 Langfuse로 보낸다.
 * URL은 서버가 완성해 준다 — 프론트가 Langfuse 호스트를 알 이유가 없고, 조각으로 받아
 * 붙이면 배포 환경이 바뀔 때마다 프론트를 고쳐야 한다. */
export interface LangfuseTrace {
  /** rag_runs.trace_id */
  id: string
  /** 바로 열 수 있는 완성 URL. 없으면 링크를 그리지 않는다(id만 글로 보여준다) */
  url: string | null
}

export interface LogErrorDetail {
  code: ErrorCode
  meaning: string
  user_message: string
  auto_retry: string
  fallback: string
  /** rag_runs.failure_stage — 어느 단계에서 멈췄나. 단계별 소요는 Langfuse가 갖는다 */
  failure_stage: string | null
  /** rag_runs.root_cause */
  root_cause: string | null
}

export interface ConversationLogDetail extends ConversationLogRow {
  classification: {
    intent: Intent
    business_function: BusinessFunction | null
    question_type: QuestionType
    /** rag_runs 에 원천 컬럼이 없어 서버가 null 을 내린다(admin_logs.py 모듈 주석) */
    source_used: boolean | null
    /** 서버가 원천 부재로 항상 null 을 내린다(admin_logs.py get_log) */
    marker: string | null
    /** 마커가 어긋나 정규화로 보정한 건 — 급증하면 프롬프트 점검(AD-008) 신호 */
    normalized: boolean | null
  }
  /** 검색 후보·단계별 소요는 여기 없다 — Langfuse가 갖는다(위 LangfuseTrace 주석) */
  langfuse: LangfuseTrace | null
  /** rag_runs.total_latency_ms — 단계별 분해 없이 총합만 남았다 */
  total_latency_ms: number | null
  answer_masked_preview: string
  answer_masked_full: string
  feedback_detail: {
    vote: FeedbackVote
    at: string
    reason_label: string
    comment: string
  } | null
  error: LogErrorDetail | null
}

// ---------------------------------------------------------------- 필터

export type PeriodKey = 'today' | '7d' | '30d' | 'custom'

/** 기간 옵션 — 오늘 기본 · 7일 · 30일 · 직접 지정(최대 90일) (Desc 0) */
export const PERIOD_OPTIONS = [
  { value: 'today', label: '오늘' },
  { value: '7d', label: '7일' },
  { value: '30d', label: '30일' },
  { value: 'custom', label: '직접 지정' },
]

/** 직접 지정 최대 범위 (Desc 0 "최대 90일") */
export const MAX_CUSTOM_DAYS = 90

export interface LogFilters {
  period: PeriodKey
  /** period가 custom일 때만 쓴다 (YYYY-MM-DD) */
  from: string
  to: string
  intent: '' | Intent
  status: '' | LogStatus
  /** '' 전체 · up · down · none(피드백 없음) */
  feedback: '' | FeedbackVote | 'none'
  q: string
}

export const DEFAULT_FILTERS: LogFilters = {
  period: 'today',
  from: '',
  to: '',
  intent: '',
  status: '',
  feedback: '',
  q: '',
}

const KST_DATE = new Intl.DateTimeFormat('en-CA', {
  timeZone: TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})

/** KST 기준 오늘(YYYY-MM-DD). 브라우저 타임존과 무관하다 */
export const kstToday = () => KST_DATE.format(new Date())

/** KST 오늘에서 n일 이동 */
export function kstShift(days: number): string {
  const base = new Date(`${kstToday()}T00:00:00+09:00`)
  base.setUTCDate(base.getUTCDate() + days)
  return KST_DATE.format(base)
}

/** 두 날짜(YYYY-MM-DD) 사이 일수 */
export function daysBetween(from: string, to: string): number {
  const ms = new Date(`${to}T00:00:00+09:00`).getTime() - new Date(`${from}T00:00:00+09:00`).getTime()
  return Math.floor(ms / 86_400_000) + 1
}

/** 기간 선택 → 서버로 보낼 from·to */
export function periodRange(f: LogFilters): { from: string; to: string } {
  if (f.period === 'custom') return { from: f.from, to: f.to }
  const to = kstToday()
  if (f.period === '7d') return { from: kstShift(-6), to }
  if (f.period === '30d') return { from: kstShift(-29), to }
  return { from: to, to }
}

// ---------------------------------------------------------------- 호출

export const logsQueryKey = ['admin', 'logs'] as const

export function fetchLogs(filters: LogFilters, page: number, size: number) {
  const { from, to } = periodRange(filters)
  const params = new URLSearchParams({ page: String(page), size: String(size) })
  if (from) params.set('from', from)
  if (to) params.set('to', to)
  if (filters.status) params.set('status', filters.status)
  if (filters.intent) params.set('intent', filters.intent)
  if (filters.feedback) params.set('feedback', filters.feedback)
  if (filters.q.trim()) params.set('q', filters.q.trim())
  return apiRequest<Page<ConversationLogRow>>(`/api/admin/logs?${params.toString()}`)
}

export function fetchSummary() {
  return apiRequest<LogSummary>('/api/admin/logs/summary')
}

export function fetchLogDetail(requestId: string) {
  return apiRequest<ConversationLogDetail>(`/api/admin/logs/${requestId}`)
}

export function rerunLog(requestId: string) {
  return apiRequest<ConversationLogRow>(`/api/admin/logs/${requestId}/rerun`, { method: 'POST' })
}

/** [처리 완료 표시] — 조치 사유 필수 (Desc 4) */
export function resolveLog(requestId: string, reason: string) {
  return apiRequest<ConversationLogRow>(`/api/admin/logs/${requestId}`, {
    method: 'PATCH',
    body: { triage: 'RESOLVED' },
    reason,
  })
}

/** [테스트셋 보강 후보로 등록] — 마스킹된 질문과 기대 출처 초안만 넘긴다 (Desc 3) */
export function addEvalCandidate(requestId: string) {
  return apiRequest<{ candidate_id: string; status: string }>('/api/admin/evaluations/candidates', {
    method: 'POST',
    body: { source_request_id: requestId },
  })
}

/** 내보내기 — 사실 자체가 활동 로그(AD-011)에 남는다 */
export function exportLogs(filters: LogFilters) {
  const { from, to } = periodRange(filters)
  return apiRequest<{ export_id: string; estimated_rows: number }>('/api/admin/logs/exports', {
    method: 'POST',
    // 내보내기 대상은 화면에 보이는 현재 필터 결과다 — fetchLogs가 보내는 조건과 같아야 한다
    body: {
      from,
      to,
      status: filters.status,
      intent: filters.intent,
      feedback: filters.feedback,
      q: filters.q.trim(),
    },
  })
}

// ---------------------------------------------------------------- 라벨 · 표기

export const LOG_STATUS_LABEL: Record<LogStatus, string> = {
  NORMAL: '정상',
  OUT_OF_SCOPE: '범위 외',
  FAILED: '실패',
}

/** 색만으로 알리지 않도록 라벨과 함께 쓴다(CM-DF-004 09절) */
export const LOG_STATUS_TONE: Record<LogStatus, 'green' | 'orange' | 'red'> = {
  NORMAL: 'green',
  OUT_OF_SCOPE: 'orange',
  FAILED: 'red',
}

/** CM-DF-002 06절 triage_status 3종 */
export const TRIAGE_LABEL: Record<TriageStatus, string> = {
  NONE: '미확인',
  IN_REVIEW: '확인 중',
  RESOLVED: '처리 완료',
}

export const FEEDBACK_LABEL: Record<FeedbackVote, string> = {
  up: '👍 좋아요',
  down: '👎 아쉬워요',
}

/** `08-01 09:38` — 상세 부제 시각 포맷 */
export function formatMonthDayTime(value: string): string {
  const date = formatDate(value)
  return date === '—' ? date : `${date.slice(5)} ${formatTime(value)}`
}

/** 값 없음은 표에서 '—'로 채운다(열이 밀리지 않게) */
export const dash = (value: string | number | null | undefined) =>
  value === null || value === undefined || value === '' ? '—' : String(value)
