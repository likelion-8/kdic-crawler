/** ad-eval-rag — AD-006 평가셋 문항 편집 · 게이트 판정 상세 / AD-007 RAG 파라미터 · A/B 비교 목.
 *
 * CM-DF-003 04절에 계약이 있는 접점(`GET /api/admin/evaluations/runs`·`/{run_id}`)은 기존
 * `handlers/admin.ts`가 그대로 처리한다. 여기에는 04절에 **없는** 접점만 둔다.
 * 응답 모양의 정본은 화면 쪽 계약 파일이다:
 *   - `routes/admin/evaluation/api.ts`
 *   - `routes/admin/settings/rag/api.ts`
 *
 * 수치의 출처
 *   - 파라미터 현행값·반영 시점 = CM-DF-003 05절 표
 *   - 게이트 목표값 = AD-006 §2.4 모달(= CM-DF-004 05절). 화면에서 수정할 수 없어 서버가 준다
 *   - A/B·정량 비교 수치 = AD-007 §1.5·§1.6 목업 */
import { HttpResponse, delay, http } from 'msw'
import type { QuestionType, Role } from '../../../lib/codes'
import { hasRole } from '../../../lib/codes'
import { MOCK_PAGES } from '../../data/pages'
import type {
  EvalApplyRequest, EvalApplyResult, EvalItem, EvalItemInput, EvalItemValidation, EvalSchedule,
  EvaluationRun, ExpectedSource, GateDetail, RunMetric,
} from '../../../routes/admin/evaluation/api'
import type { Page } from '../../../lib/api/types'
import type {
  AbSearchResponse, ParamValue, RagGate, RagHistoryEntry, RagParam, RagParamsResponse,
} from '../../../routes/admin/settings/rag/api'

// ---------------------------------------------------------------- 공통

let seq = 0
const nextId = (prefix: string) => `${prefix}_${Date.now().toString(36)}_${(seq += 1)}`

function fail(status: number, message: string) {
  return HttpResponse.json(
    { code: 'INTERNAL', user_message: message, retryable: false, fallback_sources: [], request_id: nextId('req') },
    { status },
  )
}

/** handlers/admin.ts와 같은 개발용 스위치 — `x-mock-role` 헤더가 있으면 그 역할로 본다 */
function denied(request: Request, need: Role) {
  const mine = (request.headers.get('x-mock-role') as Role | null) ?? 'ADMIN'
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

// ---------------------------------------------------------------- AD-006 평가셋 문항

/** AD-006 §2.2 목업 4행은 원문 그대로 둔다. 나머지는 코퍼스(MOCK_PAGES)로 채워 89문항을 만든다
 *  — CM-DF-003 07절 "testset_pipeline.jsonl 89문항". */
const MOCKUP_ITEMS: EvalItem[] = [
  {
    item_id: 'dp_protlmts_pl1', question: '보호 한도는?', business_function: '예금자보호제도',
    question_type: 'fact', intent: 'informational',
    expected_source: { doc_id: 'dp_protlmts', title: '보호한도' },
  },
  {
    item_id: 'ha_faq_dclr_pl1', question: '익명 신고도 포상금?', business_function: '은닉재산 신고',
    question_type: 'faq', intent: 'informational',
    expected_source: { doc_id: 'ha_faq_dclr', title: '은닉재산 신고 FAQ' },
  },
  {
    item_id: 'sender_qlfc_check_pl1', question: '신청 가능 송금액은?', business_function: '착오송금 반환 신청',
    question_type: 'table_lookup', intent: 'informational',
    expected_source: { doc_id: 'sender_qlfc_check', title: '신청 가능 여부 확인' },
  },
  {
    item_id: 'pl_uc_itgr_aply_1', question: '미수령금 통합신청은?', business_function: '고객 미수령금 신청',
    question_type: 'link_guide', intent: 'civil_petition',
    expected_source: { doc_id: 'pl_uc_itgr_aply', title: '미수령금 통합 신청' },
  },
]

/** 평가셋 문항에 허용되는 유형 4종 — §2.5 입력 필드 표 원문(서식 받기·범위 외는 문항 유형이 아니다) */
const TYPE_CYCLE: QuestionType[] = ['fact', 'faq', 'table_lookup', 'link_guide']
const QUESTION_TEMPLATES = [
  (title: string) => `${title} 어떻게 확인하나요?`,
  (title: string) => `${title} 신청 절차 알려주세요`,
  (title: string) => `${title} 관련 필요한 서류는?`,
]

function seedItems(): EvalItem[] {
  const rows = [...MOCKUP_ITEMS]
  // 89문항이 될 때까지 코퍼스를 돌며 채운다. 기대 출처는 실제 page_id라 검증을 통과한다
  for (let i = 0; rows.length < 89; i += 1) {
    const page = MOCK_PAGES[i % MOCK_PAGES.length]
    const round = Math.floor(i / MOCK_PAGES.length) + 1
    rows.push({
      item_id: `${page.page_id}_pl${round + 1}`,
      question: QUESTION_TEMPLATES[i % QUESTION_TEMPLATES.length](page.page_title),
      business_function: page.business_function,
      question_type: TYPE_CYCLE[i % TYPE_CYCLE.length],
      intent: i % 3 === 0 ? 'civil_petition' : 'informational',
      expected_source: { doc_id: page.page_id, title: page.page_title },
    })
  }
  return rows
}

let items = seedItems()
let testsetVersion = 12

const corpusDocs: ExpectedSource[] = MOCK_PAGES.map((p) => ({ doc_id: p.page_id, title: p.page_title }))

/** 저장 시 자동 검증 ① 기대 출처 존재 ② 중복 질문 ③ 개인정보 (AD-006 Desc 0) */
function validate(input: EvalItemInput, ignoreId?: string): EvalItemValidation {
  const errors: EvalItemValidation['errors'] = []
  if (!input.question.trim()) {
    errors.push({ field: 'question', message: '질문을 입력해 주세요' })
  }
  const duplicate = items.find(
    (it) => it.item_id !== ignoreId && it.question.trim() === input.question.trim(),
  )
  if (duplicate) {
    errors.push({ field: 'question', message: `같은 질문이 이미 평가셋에 있습니다 (${duplicate.item_id})` })
  }
  // 개인정보 포함 여부 — 주민번호·계좌·전화 형태만 본다(가드레일 마스킹 규칙과 같은 축)
  if (/\d{6}[-]\d{7}|01[016789][-]?\d{3,4}[-]?\d{4}/.test(input.question)) {
    errors.push({ field: 'question', message: '질문에 개인정보로 보이는 값이 있습니다. 지운 뒤 저장해 주세요' })
  }
  const source = corpusDocs.find((d) => d.doc_id === input.expected_source_id)
  if (!source) {
    errors.push({
      field: 'expected_source',
      message: `기대 출처 '${input.expected_source_id || '(미지정)'}'는 코퍼스에 없습니다`,
    })
  }
  if (!/^[a-z0-9_#]+$/.test(input.item_id)) {
    errors.push({ field: 'item_id', message: '문항 ID는 영소문자·숫자·밑줄만 쓸 수 있습니다' })
  }
  if (errors.length > 0 || !source) return { ok: false, errors }
  return {
    ok: true,
    errors: [],
    item: {
      item_id: input.item_id,
      question: input.question.trim(),
      business_function: input.business_function,
      question_type: input.question_type,
      intent: input.intent,
      expected_source: source,
    },
  }
}

/** AD-006 §2.3 이력 표 — 목업 5행 + 상태 다양성(미달 · 실행 중) 3행.
 * '핵심 결과'는 **대상별로 지표 축이 다르므로**(§2.3) 서버가 라벨까지 완성해 내려준다.
 * seed가 원지표(raw)를 함께 들고 있는 건 게이트 판정 상세(§2.4) 표를 같은 실행에서 만들기 위해서다. */
interface RunSeed extends Omit<EvaluationRun, 'metrics'> {
  raw: { recall_at_5: number; mrr: number; generation_rate: number; avg_latency_ms: number }
  /** 프롬프트 계열 지표 축 — 회귀 / 인용 / 중대 위반 */
  prompt?: { regression: string; citation_rate: number; critical: number }
}

const PASSED_GATE = { passed: true, smoke_passed: 30, smoke_total: 30 }

const runs: RunSeed[] = [
  {
    run_id: 'run_20260803_0930', target: '운영 설정', source: '수동 실행',
    started_at: '2026-08-03T09:30:00+09:00', finished_at: '2026-08-03T09:47:00+09:00', status: 'SUCCESS',
    item_count: 580, testset_version: 12, gate: PASSED_GATE,
    raw: { recall_at_5: 0.912, mrr: 0.784, generation_rate: 100, avg_latency_ms: 5_240 },
  },
  {
    run_id: 'run_20260802_1810', target: '프롬프트 초안', source: '프롬프트 게시 게이트',
    started_at: '2026-08-02T18:10:00+09:00', finished_at: '2026-08-02T18:29:00+09:00', status: 'SUCCESS',
    item_count: 30, testset_version: 12,
    gate: {
      passed: false, smoke_passed: 27, smoke_total: 30,
      blocked_reason: 'Smoke 통과 30건 미만 — 게시할 수 없습니다',
    },
    raw: { recall_at_5: 0.889, mrr: 0.741, generation_rate: 98.9, avg_latency_ms: 5_910 },
    prompt: { regression: '5/6', citation_rate: 97.2, critical: 1 },
  },
  {
    run_id: 'run_20260801_1400', target: 'RAG 초안', source: 'RAG 파라미터 평가',
    started_at: '2026-08-01T14:00:00+09:00', finished_at: null, status: 'RUNNING',
    item_count: 580, testset_version: 12,
    gate: { passed: false, smoke_passed: 0, smoke_total: 30 },
    raw: { recall_at_5: 0, mrr: 0, generation_rate: 0, avg_latency_ms: 0 },
  },
  {
    run_id: 'run_20260730_1420', target: '운영 설정', source: '파이프라인 후속',
    started_at: '2026-07-30T14:20:00+09:00', finished_at: '2026-07-30T14:38:00+09:00', status: 'SUCCESS',
    item_count: 89, testset_version: 12, gate: PASSED_GATE,
    raw: { recall_at_5: 0.922, mrr: 0.806, generation_rate: 100, avg_latency_ms: 5_200 },
  },
  {
    run_id: 'run_20260729_1105', target: 'RAG 초안', source: 'RAG 파라미터 평가',
    started_at: '2026-07-29T11:05:00+09:00', finished_at: '2026-07-29T11:24:00+09:00', status: 'SUCCESS',
    item_count: 89, testset_version: 12, gate: PASSED_GATE, follow_up: '→ 11:40 반영됨',
    raw: { recall_at_5: 0.918, mrr: 0.801, generation_rate: 100, avg_latency_ms: 5_300 },
  },
  {
    run_id: 'run_20260728_0400', target: '운영 설정', source: '파이프라인 후속',
    started_at: '2026-07-28T04:00:00+09:00', finished_at: '2026-07-28T04:19:00+09:00', status: 'SUCCESS',
    // 평가셋 v12의 첫 재측정 = 구성이 바뀐 뒤 점수가 오른 실행(Desc 0)
    item_count: 89, testset_version: 12, gate: PASSED_GATE, improved_by_composition: true,
    raw: { recall_at_5: 0.921, mrr: 0.804, generation_rate: 100, avg_latency_ms: 5_180 },
  },
  {
    run_id: 'run_20260724_1612', target: '프롬프트 초안', source: '프롬프트 게시 게이트',
    started_at: '2026-07-24T16:12:00+09:00', finished_at: '2026-07-24T16:26:00+09:00', status: 'SUCCESS',
    item_count: 6, testset_version: 11, gate: PASSED_GATE, follow_up: '→ 게시 v1.4',
    raw: { recall_at_5: 0.915, mrr: 0.799, generation_rate: 100, avg_latency_ms: 5_400 },
    prompt: { regression: '6/6', citation_rate: 99.6, critical: 0 },
  },
  {
    run_id: 'run_20260721_0400', target: '운영 설정', source: '파이프라인 후속',
    started_at: '2026-07-21T04:00:00+09:00', finished_at: '2026-07-21T04:18:00+09:00', status: 'SUCCESS',
    item_count: 89, testset_version: 11, gate: PASSED_GATE,
    raw: { recall_at_5: 0.92, mrr: 0.803, generation_rate: 100, avg_latency_ms: 5_210 },
  },
]

/** 퍼센트는 1자리, 정수면 소수점을 붙이지 않는다(목업 `100%` · `99.6%`) */
const pct = (n: number) => `${Number.isInteger(n) ? n : n.toFixed(1)}%`

function metricsOf(run: RunSeed): RunMetric[] {
  if (run.status === 'RUNNING' || run.status === 'QUEUED') return []
  if (run.prompt) {
    return [
      { label: '회귀', value: run.prompt.regression },
      { label: '인용', value: pct(run.prompt.citation_rate) },
      { label: '중대 위반', value: String(run.prompt.critical) },
    ]
  }
  return [
    { label: '정확도', value: run.raw.recall_at_5.toFixed(3) },
    { label: 'MRR', value: run.raw.mrr.toFixed(3) },
    { label: '생성', value: pct(run.raw.generation_rate) },
  ]
}

/** raw·prompt는 게이트 상세를 만들기 위한 서버 내부값이라 응답에서 뺀다 */
function toRun({ raw, prompt, ...wire }: RunSeed): EvaluationRun {
  return { ...wire, metrics: metricsOf({ ...wire, raw, prompt }) }
}

/** AD-006 §2.4 목표 열 — CM-DF-004 05절이 정본이라 화면에서 못 고친다. 서버가 내려준다 */
function gateOf(runId: string): GateDetail | null {
  const run = runs.find((r) => r.run_id === runId)
  if (!run) return null
  const seconds = run.raw.avg_latency_ms / 1000
  return {
    run_id: run.run_id,
    target: run.target,
    source: run.source,
    started_at: run.started_at,
    criteria: [
      {
        label: 'Smoke 30문항',
        target: `${run.gate.smoke_total}/${run.gate.smoke_total}`,
        result: `${run.gate.smoke_passed}/${run.gate.smoke_total}`,
        passed: run.gate.smoke_passed >= run.gate.smoke_total,
      },
      {
        label: '검색 정확도@5', target: '0.92 이상',
        result: run.raw.recall_at_5.toFixed(3), passed: run.raw.recall_at_5 >= 0.92,
      },
      {
        label: '순위 품질 MRR', target: '0.80 이상',
        result: run.raw.mrr.toFixed(3), passed: run.raw.mrr >= 0.8,
      },
      {
        label: '생성 성공률', target: '99.5% 이상',
        result: pct(run.raw.generation_rate), passed: run.raw.generation_rate >= 99.5,
      },
      {
        label: '평균 응답 시간', target: '10초 이하',
        result: `${seconds.toFixed(1)}초`, passed: seconds <= 10,
      },
    ],
    latest_smoke: '08-01 10:42 프롬프트 v1.5 게시 직후 자동 실행 → 30/30 통과 ✓',
    failed_items: run.gate.passed
      ? []
      : [
          {
            item_id: 'kmrs_fee_pl1', question: '반환지원 수수료는 얼마인가요?',
            expected_source: 'kmrs_apply_mthd', actual_top1: 'kmrs_itrd', score: 0.41,
          },
          {
            item_id: 'dp_prot_fnnc_pl2', question: '보호되지 않는 상품은?',
            expected_source: 'dp_prot_fnnc', actual_top1: 'dp_protlmts', score: 0.38,
          },
        ],
  }
}

// ---------------------------------------------------------------- AD-007 파라미터

/** 실서버 admin_rag_params.py:_param_meta 와 키·라벨·범위를 1:1로 맞춘다(목이 곧 계약).
 * 옛 목 전용 키(top_k_*·fusion_alpha·llm_model·temperature·max_tokens 등)는 실서버가
 * 노출하지 않아 제거했다 — 2026-08-13 실백엔드 대조 정렬. min/max/step 도 서버 값이다 */
const RAG_PARAMS: RagParam[] = [
  {
    key: 'k_candidates', label: '1차 후보 수', group: 'retrieval', control: 'stepper',
    apply_timing: '무중단', min: 5, max: 50, step: 5,
    note: 'route_search_chunks 1차 후보 청크 수 (Recall@20 99%+ 실측)',
  },
  {
    key: 'k_final', label: '최종 근거 수', group: 'retrieval', control: 'stepper',
    apply_timing: '무중단', min: 1, max: 10, step: 1,
    note: 'LLM 에 넘기는 근거 청크 수 (AnswerRecall@5 기준과 동일 k)',
  },
  {
    key: 'min_top1_score', label: '무관 질문 게이트 임계값', group: 'retrieval', control: 'slider',
    apply_timing: '무중단', min: 0, max: 1, step: 0.05,
    scale_start: '관대(통과 많음)', scale_end: '엄격(차단 많음)',
    note: 'top-1 점수가 미만이면 근거를 비워 환각 차단 (0.35 = 인스코프 오차단 0 실측)',
  },
  {
    key: 'use_reranker', label: '리랭커(cross-encoder)', group: 'retrieval', control: 'toggle',
    apply_timing: '무중단',
    note: 'CPU 문항당 96초 실측으로 기본 Off — GPU 확보 시 재검증(README 2.4)',
  },
  {
    key: 'use_query_planner', label: '쿼리 플래너(분해+intent 한 콜)', group: 'retrieval', control: 'toggle',
    apply_timing: '무중단',
    note: 'gpt-5.6-luna structured output (100문항 joint 89% 실측)',
  },
  {
    key: 'use_query_decomposition', label: '복합 질문 분해(플래너 Off 폴백)', group: 'retrieval',
    control: 'toggle', apply_timing: '무중단',
    note: '플래너를 껐을 때만 쓰는 HCX 분해 경로',
  },
  {
    key: 'use_source_recheck', label: '답변 사후 검증(전 답변 1콜)', group: 'generation',
    control: 'toggle', apply_timing: '무중단',
    note: '마커 오표기(출처 소실 54% 실측)를 별도 LLM 판정으로 복구',
  },
]

let currentValues: Record<string, ParamValue> = {
  k_candidates: 20,
  k_final: 5,
  min_top1_score: 0.35,
  use_reranker: false,
  use_query_planner: true,
  use_query_decomposition: true,
  use_source_recheck: true,
}

/** 실서버 시그니처는 sha256[:16] opaque 토큰(admin_rag_params.py:156)이다. 목도 불투명 해시를 줘
 * 프론트가 포맷에 기대는 회귀(JSON.stringify 비교 → 실백엔드 영구 stale, 2026-08-13 실측)를 막는다 */
function mockSignature(draft: Record<string, ParamValue>): string {
  const canon = JSON.stringify(Object.fromEntries(Object.entries(draft).sort()))
  let h = 2166136261 // FNV-1a
  for (let i = 0; i < canon.length; i += 1) {
    h ^= canon.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return (h >>> 0).toString(16).padStart(16, '0')
}

const EMPTY_GATE: RagGate = {
  passed: false, draft_signature: null, evaluated_at: null,
  blocked_reason: '초안 평가를 실행해야 [운영 반영]이 활성화됩니다',
  warning: null, holdout_total: 89, holdout_passed: 0, smoke_total: 0, smoke_passed: 0,
  quantitative: null,
}
let gate: RagGate = { ...EMPTY_GATE }

/** AD-007 §1.7 목업 3행 */
const history: RagHistoryEntry[] = [
  {
    id: 'rp_20260730_1420', changed_at: '2026-07-30T14:20:00+09:00',
    summary: '복합 질문 분해 Off → On', actor: 'admin',
    reason: '하위 요구 누락 개선 · 분해셋 38건 검증',
  },
  {
    id: 'rp_20260728_1105', changed_at: '2026-07-28T11:05:00+09:00',
    summary: '검색 라우팅 : 키워드 병용 기본 → 의미 검색 기본', actor: 'admin',
    reason: '유형별 재검증 · 링크 안내 질의만 키워드 병용이 우세',
  },
  {
    id: 'rp_20260728_1040', changed_at: '2026-07-28T10:40:00+09:00',
    summary: '업무 필터 On → Off', actor: 'admin',
    reason: '업무 필터 없이 0.786 > 분류기 필터 0.764',
  },
]

/** 롤백 대상 시점의 값. 목이라 이력 id별 스냅샷만 들고 있는다 */
const historyValues: Record<string, Record<string, ParamValue>> = {
  rp_20260730_1420: { ...currentValues, use_query_planner: false },
  rp_20260728_1105: { ...currentValues, use_reranker: true, k_final: 7 },
  rp_20260728_1040: { ...currentValues, min_top1_score: 0.3 },
}

function chipsOf(values: Record<string, ParamValue>): string[] {
  const chips = [`후보 ${values.k_candidates}`, `근거 ${values.k_final}`]
  if (values.use_reranker) chips.push('리랭커 On')
  return chips
}

/** AD-007 §1.5 목업. 상위 5건은 Description 3 기준(목업 3행은 카드 높이 탓) */
const AB_BASE = [
  { title: '반환지원 FAQ #3', doc_id: 'faq_msdr_apply#3', score: 0.84, is_answer: true },
  { title: '진행상황 조회', doc_id: 'mtrs_stut_chc', score: 0.77, is_answer: false },
  { title: '제도 소개', doc_id: 'kmrs_itrd', score: 0.65, is_answer: false },
  { title: '반환지원 FAQ #2', doc_id: 'faq_msdr_apply#2', score: 0.6, is_answer: false },
  { title: '자진 반환 절차', doc_id: 'mtrs_gvbk_proc', score: 0.55, is_answer: false },
]

/** "결과를 저장해 두지 않고 그때그때 검색하므로 점수가 미세하게 다를 수 있음"(§1.5)을 그대로 흉내 낸다 */
function hitsFor(alpha: number) {
  const shift = (Number(alpha) - 0.4) * 0.1
  return AB_BASE.map((h, i) => ({
    rank: i + 1,
    title: h.title,
    doc_id: h.doc_id,
    score: Number(Math.max(0, h.score + shift + (Math.random() - 0.5) * 0.01).toFixed(2)),
    is_answer: h.is_answer,
  }))
}

// ---------------------------------------------------------------- 핸들러

export const adEvalRagHandlers = [
  // ---- AD-006 평가셋 ----
  http.get('/api/admin/evaluations/items', ({ request }) => {
    const url = new URL(request.url)
    const page = Number(url.searchParams.get('page') ?? 1)
    const size = Number(url.searchParams.get('size') ?? 20)
    return HttpResponse.json({
      items: items.slice((page - 1) * size, page * size),
      total: items.length,
      page,
      size,
    })
  }),

  http.get('/api/admin/evaluations/schedule', () => {
    // 매주 월 04:00 정기 재측정(AD-006 Desc 1 ③) — 다음 월요일을 계산해 준다
    const next = new Date()
    next.setHours(4, 0, 0, 0)
    do {
      next.setDate(next.getDate() + 1)
    } while (next.getDay() !== 1)
    const body: EvalSchedule = { next_check_at: next.toISOString(), testset_version: testsetVersion }
    return HttpResponse.json(body)
  }),

  http.get('/api/admin/evaluations/corpus', ({ request }) => {
    const q = (new URL(request.url).searchParams.get('q') ?? '').trim()
    const rows = q
      ? corpusDocs.filter((d) => d.doc_id.includes(q) || d.title.includes(q)).slice(0, 8)
      : []
    return HttpResponse.json({ items: rows })
  }),

  http.post('/api/admin/evaluations/items/validate', async ({ request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as EvalItemInput & { request_id?: string; ignore_id?: string }
    if (!body.request_id) return fail(400, 'request_id가 필요합니다.')
    await delay(250)
    return HttpResponse.json(validate(body, body.ignore_id))
  }),

  // 묶음 반영 — 버전 증가 1회 + 운영 자동 재측정 1회 (AD-006 §2.6)
  http.post('/api/admin/evaluations/apply', async ({ request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as EvalApplyRequest & { request_id?: string; reason?: string }
    if (!body.request_id) return fail(400, 'request_id가 필요합니다.')
    if (!body.reason?.trim()) return fail(400, '변경 사유를 입력해 주세요.')
    await delay(600)
    const excluded = new Set(body.excludes.map((e) => e.item_id))
    const edited = new Map(body.edits.map((e) => [e.item_id, e]))
    items = items
      .filter((it) => !excluded.has(it.item_id))
      .map((it) => {
        const patch = edited.get(it.item_id)
        if (!patch) return it
        const checked = validate(patch, it.item_id)
        return checked.item ?? it
      })
    const added = body.adds.map((a) => validate(a).item).filter((x): x is EvalItem => Boolean(x))
    items = [...added, ...items]
    testsetVersion += 1
    const result: EvalApplyResult = { testset_version: testsetVersion, rerun_id: nextId('run') }
    return HttpResponse.json(result)
  }),

  /** 실행 이력 — 대상·출처 필터와 페이지를 서버가 처리한다(§3 `GET .../runs?target&source&page`).
   * handlers/admin.ts의 같은 경로보다 앞에 등록되므로 이쪽이 이긴다(browser.ts 주석). */
  http.get('/api/admin/evaluations/runs', ({ request }) => {
    const url = new URL(request.url)
    const target = url.searchParams.get('target')
    const source = url.searchParams.get('source')
    const page = Number(url.searchParams.get('page') ?? 1)
    const size = Number(url.searchParams.get('size') ?? 20)
    const rows = runs
      .filter((r) => (target ? r.target === target : true))
      .filter((r) => (source ? r.source === source : true))
      .sort((a, b) => b.started_at.localeCompare(a.started_at))
      .map(toRun)
    const body: Page<EvaluationRun> = {
      items: rows.slice((page - 1) * size, page * size),
      total: rows.length,
      page,
      size,
    }
    return HttpResponse.json(body)
  }),

  http.get('/api/admin/evaluations/runs/:runId/gate', ({ params }) => {
    const detail = gateOf(String(params.runId))
    return detail ? HttpResponse.json(detail) : fail(404, '평가 실행을 찾을 수 없습니다.')
  }),

  // ---- AD-007 RAG 파라미터 ----
  http.get('/api/admin/rag-params', () => {
    const body: RagParamsResponse = { params: RAG_PARAMS, current: currentValues, draft: null, gate }
    return HttpResponse.json(body)
  }),

  http.post('/api/admin/rag-params/evaluate', async ({ request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as { draft: Record<string, ParamValue>; request_id?: string }
    if (!body.request_id) return fail(400, 'request_id가 필요합니다.')
    await delay(1400) // 홀드아웃 89문항 실행 — 로딩 상태를 볼 수 있는 시간
    const t = Number(body.draft.min_top1_score ?? currentValues.min_top1_score)
    const worse = t > Number(currentValues.min_top1_score)
    gate = {
      passed: true,
      draft_signature: mockSignature(body.draft),
      evaluated_at: new Date().toISOString(),
      blocked_reason: null,
      // 게이트는 통과했지만 현행보다 낮아진 지표가 있으면 경고(§1.6)
      warning: worse ? 'A/B 비교 결과가 현행보다 낮습니다. 그래도 반영하려면 사유에 근거를 남겨 주세요' : null,
      holdout_total: 89, holdout_passed: 89, smoke_total: 0, smoke_passed: 0,
      quantitative: {
        basis: '기준 : 링크 안내로 분류된 문항 59건 · 2026-07-28 측정. 융합 비중은 이 질의에만 영향하므로 분모가 전체 평가셋과 다릅니다',
        metrics: [
          { label: '순위 품질', a: 0.718, b: worse ? 0.703 : 0.731 },
          { label: '검색 정확도', a: 0.847, b: worse ? 0.831 : 0.859 },
        ],
        improved: worse ? 4 : 12,
        regressed: worse ? 11 : 3,
        recommendation: worse ? '→ A 유지 권장' : '→ B 반영 권장',
      },
    }
    return HttpResponse.json(gate)
  }),

  http.post('/api/admin/rag-params/ab-search', async ({ request }) => {
    const body = (await request.json()) as { query?: string; draft: Record<string, ParamValue> }
    if (!body.query?.trim()) return fail(400, '비교할 질의를 입력해 주세요.')
    await delay(800)
    const draftChips = chipsOf(body.draft)
    const baseChips = chipsOf(currentValues)
    const res: AbSearchResponse = {
      query: body.query,
      a: {
        label: 'A. 현행 운영값', chips: baseChips, changed_chips: [],
        hits: hitsFor(Number(currentValues.min_top1_score)),
      },
      b: {
        label: 'B. 초안 (편집 중)', chips: draftChips,
        changed_chips: draftChips.filter((c) => !baseChips.includes(c)),
        hits: hitsFor(Number(body.draft.min_top1_score ?? currentValues.min_top1_score)),
      },
    }
    return HttpResponse.json(res)
  }),

  http.post('/api/admin/rag-params/apply', async ({ request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as {
      draft: Record<string, ParamValue>
      request_id?: string
      reason?: string
    }
    if (!body.request_id) return fail(400, 'request_id가 필요합니다.')
    if (!body.reason?.trim()) return fail(400, '변경 사유를 입력해 주세요.')
    if (!gate.passed) return fail(409, '최신 초안 평가가 게이트를 통과해야 반영할 수 있습니다.')
    await delay(500)
    const changed = RAG_PARAMS.filter((p) => String(body.draft[p.key]) !== String(currentValues[p.key]))
    const entry: RagHistoryEntry = {
      id: nextId('rp'),
      changed_at: new Date().toISOString(),
      summary: changed
        .map((p) => `${p.label} ${currentValues[p.key]} → ${body.draft[p.key]}`)
        .join(' · '),
      actor: 'admin',
      reason: body.reason,
    }
    historyValues[entry.id] = { ...currentValues }
    history.unshift(entry)
    currentValues = { ...body.draft }
    gate = { ...EMPTY_GATE }
    const res: RagParamsResponse = { params: RAG_PARAMS, current: currentValues, draft: null, gate }
    return HttpResponse.json(res)
  }),

  http.get('/api/admin/rag-params/history', () =>
    HttpResponse.json({ items: history, total: history.length, page: 1, size: history.length })),

  http.post('/api/admin/rag-params/history/:id/rollback', async ({ params, request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const snapshot = historyValues[String(params.id)]
    if (!snapshot) return fail(404, '되돌릴 설정 이력을 찾을 수 없습니다.')
    // 초안만 복원한다. 실제 적용은 [운영 반영]이 한다(§1.7)
    return HttpResponse.json({ draft: snapshot })
  }),
]
