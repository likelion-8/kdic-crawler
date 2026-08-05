/** AD-004 데이터 접점 · 표기 규칙.
 *
 * 작업(job) 스키마는 CM-DF-003 04절에 필드 정의가 없어 여기서 정했다(10 §E 추정 목록).
 * lib/api/types.ts로 올려야 할 후보 — report의 shared_needed 참조.
 * 폴링은 반드시 isPoll:true — 유휴 세션 타이머를 갱신하면 안 된다(PRD-01 §3). */
import { apiRequest } from '../../../lib/api/client'
import type { Page } from '../../../lib/api/types'
import type { JobErrorCode, JobStatus, JobType } from '../../../lib/codes'
import { PIPELINE_STEPS } from '../../../lib/constants'
import { formatDate } from '../../../lib/format'

// ---------------------------------------------------------------- 스키마

export interface JobStep {
  /** PIPELINE_STEPS 중 하나 */
  name: string
  status: 'QUEUED' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'SKIPPED'
  /** 진행 중이면 undefined */
  elapsed_ms?: number
  /** 단계별 처리 건수 — 서버가 아직 주지 않는다(백엔드 계약 요청 항목) */
  count?: number
}

export interface PipelineJob {
  id: string
  type: JobType
  status: JobStatus
  targets: string[]
  reason: string
  created_by: string
  created_at: string
  steps: JobStep[]
  error?: { code: JobErrorCode; stage: string; detail: string }
  rollback_of?: string
  /** '전체 58페이지'처럼 대상을 그대로 쓸 문자열. 없으면 targets로 대체한다 */
  target_summary?: string
  /** 대상 건수. targets가 비는 전체 작업(전체 재수집·재적재)은 서버만 안다(백엔드 계약 요청 항목) */
  target_count?: number
  /** 실패가 인덱스에 미친 영향. 없으면 화면이 단언하지 않는다(백엔드 계약 요청 항목) */
  index_impact?: string
}

/** 원본 사이트 본문이 바뀐 페이지 (R2) */
export interface ChangedPage {
  page_id: string
  title: string
  source_title: string
  detected_at: string
}

export interface ChangedPagesResponse {
  last_checked_at: string
  items: ChangedPage[]
}

/** 확인 모달의 대상 건수·예상 소요 */
export interface JobEstimate {
  type: string
  target_count: number
  estimated_minutes: number
}

// ---------------------------------------------------------------- 호출

export const jobsQueryKey = ['admin', 'pipeline', 'jobs'] as const
export const changesQueryKey = ['admin', 'pipeline', 'changes'] as const

/** 기본 정렬 '시각 내림차순' — 기획서에 명시가 없어 프론트가 정했다(이슈 G-14) */
export function fetchJobs(page: number, size: number, isPoll: boolean) {
  return apiRequest<Page<PipelineJob>>(
    `/api/admin/jobs?page=${page}&size=${size}&sort=created_at:desc`,
    { isPoll },
  )
}

/** 진행 상태 구독. 계약이 없어(이슈 G-9) 폴링으로 간다 — 주기는 Pipeline.tsx의 POLL_MS */
export function fetchJob(id: string) {
  return apiRequest<PipelineJob>(`/api/admin/jobs/${id}`, { isPoll: true })
}

export function fetchChanges() {
  return apiRequest<ChangedPagesResponse>('/api/admin/pipeline/changes')
}

export function recheckChanges() {
  return apiRequest<ChangedPagesResponse>('/api/admin/pipeline/changes/recheck', { method: 'POST' })
}

export function fetchEstimate(type: JobType) {
  return apiRequest<JobEstimate>(`/api/admin/pipeline/estimate?type=${type}`)
}

export interface CreateJobInput {
  type: JobType
  targets?: string[]
  reason: string
  /** 재적재 모달의 청킹 모드 */
  chunk_mode?: string
}

export function createJob({ reason, ...body }: CreateJobInput) {
  return apiRequest<PipelineJob>('/api/admin/jobs', { method: 'POST', body, reason })
}

export function cancelJob(id: string, reason: string) {
  return apiRequest<PipelineJob>(`/api/admin/jobs/${id}/cancel`, { method: 'POST', reason })
}

export function retryJob(id: string, reason: string) {
  return apiRequest<PipelineJob>(`/api/admin/jobs/${id}/retry`, { method: 'POST', reason })
}

export function rollbackJob(id: string, reason: string) {
  return apiRequest<PipelineJob>(`/api/admin/jobs/${id}/rollback`, { method: 'POST', reason })
}

/** 위험 작업 전 비밀번호 재확인 (CM-DF-004 03절 · 마지막 인증 후 30분 경과 시) */
export function reauth(password: string) {
  return apiRequest<{ last_auth_at: string }>('/api/admin/reauth', { method: 'POST', body: { password } })
}

// ---------------------------------------------------------------- 라벨 · 표기

/** CM-DF-002 06절 job_type 6종. 실행 이력 '유형' 열 관측값(전체 재수집/선택 재수집/재적재)과 맞춘다 */
export const JOB_TYPE_LABEL: Record<JobType, string> = {
  FULL_RECRAWL: '전체 재수집',
  SELECTED_RECRAWL: '선택 재수집',
  REINDEX: '재적재',
  RECHUNK: '재청킹',
  REEMBED: '재임베딩',
  SMOKE_EVAL: '적재 후 확인 평가',
}

/** CM-DF-002 06절 job status 5종 */
export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  QUEUED: '대기',
  RUNNING: '진행 중',
  SUCCESS: '완료',
  FAILED: '실패',
  CANCELLED: '취소',
}

/** 칩 색 — 목업은 진행 중(연보라)·완료(초록)·실패(빨강) 3종뿐이라 대기·취소는 주황으로 맞췄다.
 * 색만으로 알리지 않도록 라벨을 항상 함께 쓴다(CM-DF-004 09절) */
export const JOB_STATUS_TONE: Record<JobStatus, 'green' | 'purple' | 'orange' | 'red'> = {
  QUEUED: 'orange',
  RUNNING: 'purple',
  SUCCESS: 'green',
  FAILED: 'red',
  CANCELLED: 'orange',
}

export const isJobActive = (job: PipelineJob) => job.status === 'QUEUED' || job.status === 'RUNNING'

/** `07-29 09:12` — 실행 이력 '시각' 열 포맷. 표기 포맷은 lib/format이 정본이라 그대로 다시 내보낸다 */
export { formatMonthDayTime } from '../../../lib/format'

/** `07-28` — 변경 감지일 표기(보조 텍스트) */
export function formatMonthDay(value: string): string {
  const date = formatDate(value)
  return date === '—' ? date : date.slice(5)
}

/** `4분 12초` — 단계 소요의 합. 진행 중이면 null(화면에서 '—') */
export function jobElapsedText(job: PipelineJob): string | null {
  if (isJobActive(job)) return null
  const ms = job.steps.reduce((sum, s) => sum + (s.elapsed_ms ?? 0), 0)
  if (ms === 0) return null
  const total = Math.round(ms / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return m > 0 ? `${m}분 ${String(s).padStart(2, '0')}초` : `${s}초`
}

/** 대상 열. 서버가 target_summary를 주면 그대로 쓰고, 없으면 targets 길이로 대체한다 */
export function jobTargetText(job: PipelineJob): string {
  if (job.target_summary) return job.target_summary
  if (job.targets.length > 0) {
    return job.type === 'SELECTED_RECRAWL' ? `변경 ${job.targets.length}페이지` : `${job.targets.length}건`
  }
  return '전체'
}

/** 실패 상세 헤더 `(대상 {N}건)`의 N. 문장형 요약(jobTargetText)은 목록 '대상' 열 전용이다.
 * 전체 작업은 targets가 비어 서버 target_count가 있어야 알 수 있다 — 없으면 undefined */
export function jobTargetCount(job: PipelineJob): number | undefined {
  return job.target_count ?? (job.targets.length > 0 ? job.targets.length : undefined)
}

/** '5. 색인'처럼 단계 번호를 붙인다. 이름을 못 찾으면 원문 그대로 */
export function stageWithIndex(stage: string): string {
  const i = PIPELINE_STEPS.indexOf(stage as (typeof PIPELINE_STEPS)[number])
  return i < 0 ? stage : `${i + 1}. ${stage}`
}

/** 1부터 시작하는 실패 단계 번호. PipelineStepText에 넘긴다 */
export function stageNumber(stage: string): number {
  const i = PIPELINE_STEPS.indexOf(stage as (typeof PIPELINE_STEPS)[number])
  return i < 0 ? 1 : i + 1
}
