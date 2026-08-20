/** AD-006 평가셋 · 평가 결과 — 이 화면이 부르는 API 계약.
 *
 * 평가 실행 이력·상세는 CM-DF-003 04절의 `GET /api/admin/evaluations/runs` · `/{run_id}`를 그대로 쓴다
 * (기존 목 핸들러 `mocks/handlers/admin.ts`).
 * 문항 편집·코퍼스 검색·게이트 판정 상세는 04절에 계약이 없어(11-ad-005-006 §3 "대부분 계약 미정")
 * 프론트가 시그니처를 정했고 `mocks/handlers/extra/ad-eval-rag.ts`가 이 모양을 돌려준다. */
import { apiRequest } from '../../../lib/api/client'
import type { BusinessFunction, Intent, JobStatus, QuestionType } from '../../../lib/codes'
import type { Page } from '../../../lib/api/types'

/** 이력 표 '핵심 결과' 한 칸. **대상별로 지표 축이 다르다**(§2.3 "핵심 결과 컬럼은 대상별로 지표 축이 다름")
 *  — RAG 계열 `정확도 / MRR / 생성`, 프롬프트 계열 `회귀 / 인용 / 중대 위반`.
 * 어느 축인지는 서버만 알므로 라벨까지 서버가 내려주고 화면은 `label value`를 ' · '로 잇는다(§4 H7 제안). */
export interface RunMetric {
  label: string
  /** 반올림까지 끝난 표시 문자열 — 점수 3자리 · 퍼센트 1자리 · 초 1자리(H7) */
  value: string
}

/** §2.3 '대상' 3종. 초안이 RAG인지 프롬프트인지가 지표 축을 가른다 */
export type RunTarget = '운영 설정' | 'RAG 초안' | '프롬프트 초안'
export const RUN_TARGETS: RunTarget[] = ['운영 설정', 'RAG 초안', '프롬프트 초안']

/** '출처' 필터 옵션. 목록 응답에서 뽑으면 그 페이지 안에서만 만들어지므로 고정 사전을 쓴다(검증 D104) */
export const RUN_SOURCES = [
  '수동 실행', '프롬프트 게시 게이트', '파이프라인 후속', 'RAG 파라미터 평가',
] as const

/** 평가 실행 1건 — CM-DF-003 04절에 필드 정의가 없어 이 화면이 계약을 들고 있다 */
export interface EvaluationRun {
  run_id: string
  target: RunTarget
  /** 실행을 유발한 곳(RUN_SOURCES) */
  source: string
  started_at: string
  finished_at: string | null
  status: JobStatus
  item_count: number
  metrics: RunMetric[]
  /** 게이트 판정 — 통과 건수·총 건수 모두 서버가 준다. 미달이어도 반영·게시를 막지
   *  않는다(2026-08-19 경고 전환) — warning_reason 은 '무엇이 목표에 못 미쳤나'다 */
  gate: { passed: boolean; smoke_passed: number; smoke_total: number; warning_reason?: string }
  /** '판정 · 후속' 열의 후속 텍스트 — `→ 11:40 반영됨` · `→ 게시 v1.4` (§2.3) */
  follow_up?: string
  /** 이 실행이 쓴 평가셋 버전. 바뀐 지점에 '평가셋 vN부터' 구분 뱃지를 단다(Desc 1) */
  testset_version: number
  /** 재측정 점수가 직전보다 올랐다 → '구성 변경으로 상승' 뱃지(Desc 0) */
  improved_by_composition?: boolean
}

/** 기대 출처 — 표시 포맷 `{doc_id} · {제목}` (AD-006 §2.5) */
export interface ExpectedSource {
  doc_id: string
  title: string
}

/** 평가셋 문항 1건. 컬럼 = 문항 ID / 질문 / 업무 / 유형 / 성격 (AD-006 §2.2) */
export interface EvalItem {
  item_id: string
  question: string
  business_function: BusinessFunction
  question_type: QuestionType
  intent: Intent
  expected_source: ExpectedSource
}

/** 인라인 입력 행이 서버로 보내는 값 (AD-006 §2.5) */
export interface EvalItemInput {
  item_id: string
  question: string
  business_function: BusinessFunction
  question_type: QuestionType
  intent: Intent
  expected_source_id: string
}

/** 검증에 걸린 '필드'를 알아야 그 필드만 붉게 칠할 수 있다(AD-006 §2.2 "걸린 항목만 붉게") */
export type EvalItemField = 'item_id' | 'question' | 'expected_source'

export interface EvalFieldError {
  field: EvalItemField
  /** 서버 문구 그대로 노출한다 */
  message: string
}

/** 저장 시 자동 검증 ① 기대 출처가 코퍼스에 존재 ② 중복 질문 ③ 개인정보 포함 (AD-006 Desc 0) */
export interface EvalItemValidation {
  ok: boolean
  errors: EvalFieldError[]
  /** ok일 때만 — 자동 생성된 문항 ID가 확정된 최종 형태 */
  item?: EvalItem
}

/** 헤더 '다음 자동 확인' — 정기 재측정(매주 월 04:00, AD-006 Desc 1 ③) */
export interface EvalSchedule {
  next_check_at: string
  /** 현재 평가셋 버전. 이력 비교는 같은 버전끼리만 유효하다(Desc 1) */
  testset_version: number
}

/** 편집 묶음 반영 결과 — 버전 증가 1회 + 운영 자동 재측정 1회 (AD-006 §2.6) */
export interface EvalApplyResult {
  testset_version: number
  rerun_id: string
}

export interface EvalApplyRequest {
  adds: EvalItemInput[]
  edits: EvalItemInput[]
  excludes: { item_id: string; reason: string }[]
}

/** 게이트 판정 상세 모달의 표 1행 (AD-006 §2.4) */
export interface GateCriterion {
  /** `Smoke 30문항` · `검색 정확도@5` 처럼 한글 표기가 정본 */
  label: string
  /** `0.92 이상` · `30/30` — 화면에서 수정 불가(CM-DF-004 05절) */
  target: string
  result: string
  passed: boolean
}

/** 미달 실행에서만 내려온다 (AD-006 H8) */
export interface GateFailedItem {
  item_id: string
  question: string
  expected_source: string
  actual_top1: string
  score: number
}

export interface GateDetail {
  run_id: string
  /** 모달 제목 `게이트 판정 상세 : {대상} · {시각} · {출처}` 재료 */
  target: string
  source: string
  started_at: string
  criteria: GateCriterion[]
  /** 모달 하단 한 줄. 서버 문구 그대로 */
  latest_smoke: string
  failed_items: GateFailedItem[]
}

const BASE = '/api/admin/evaluations'

export const evalKeys = {
  items: (page: number, size: number) => ['eval', 'items', page, size] as const,
  schedule: ['eval', 'schedule'] as const,
  corpus: (q: string) => ['eval', 'corpus', q] as const,
  runs: (page: number, target: string, source: string) => ['eval', 'runs', page, target, source] as const,
  gate: (runId: string) => ['eval', 'gate', runId] as const,
}

export function fetchItems(page: number, size: number) {
  return apiRequest<Page<EvalItem>>(`${BASE}/items?page=${page}&size=${size}`)
}

export function fetchSchedule() {
  return apiRequest<EvalSchedule>(`${BASE}/schedule`)
}

/** 기대 출처 자동완성 — 2자 이상에서만 부른다(H6 제안 확정) */
export function searchCorpus(q: string) {
  return apiRequest<{ items: ExpectedSource[] }>(`${BASE}/corpus?q=${encodeURIComponent(q)}`)
}

/** `ignoreId`를 주면 중복 질문 검사에서 그 문항 자신은 빼고 본다(기존 행 편집) */
export function validateItem(body: EvalItemInput, ignoreId?: string) {
  return apiRequest<EvalItemValidation>(`${BASE}/items/validate`, {
    method: 'POST',
    body: { ...body, ignore_id: ignoreId },
  })
}

/** 사유 필수 — 위험 작업 공통(CM-DF-004 03절) */
export function applyChanges(body: EvalApplyRequest, reason: string) {
  return apiRequest<EvalApplyResult>(`${BASE}/apply`, { method: 'POST', body, reason })
}

export function fetchGate(runId: string) {
  return apiRequest<GateDetail>(`${BASE}/runs/${runId}/gate`)
}

/** 평가 실행 이력 — §3 API 접점 `GET /api/admin/evaluations/runs?target&source&page`.
 * 거르기·자르기는 전부 서버가 한다. 한 장만 받아 화면에서 자르면 100건 뒤가 조용히 사라진다(검증 D104). */
export function fetchRuns(page: number, size: number, target: string, source: string) {
  const filters =
    (target === '전체' ? '' : `&target=${encodeURIComponent(target)}`) +
    (source === '전체' ? '' : `&source=${encodeURIComponent(source)}`)
  return apiRequest<Page<EvaluationRun>>(
    `${BASE}/runs?page=${page}&size=${size}&sort=started_at:desc${filters}`,
  )
}
