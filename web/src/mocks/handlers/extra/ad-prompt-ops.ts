/** AD-008 프롬프트·가드레일 / AD-009 운영 정책 목.
 *
 * 기존 handlers/admin.ts에 없는 경로만 여기 둔다(등록은 mocks/browser.ts에서 한다).
 * 경로는 기획서 12절 4.4 · 13절 12절의 '추정 API 접점'을 그대로 따랐다 — 백엔드 계약 확정 대상.
 *
 * 공통 규칙은 handlers/admin.ts와 동일하다.
 *  - 목록은 Page<T> 봉투 · 쓰기는 request_id + reason 필수(없으면 400) · 권한 부족은 403
 *  - 역할은 요청 헤더 `x-mock-role`로 바꾼다. 헤더가 없으면 ADMIN
 *    (handlers/admin.ts의 로그인 상태는 모듈 밖에서 읽을 수 없어 공유하지 않는다)
 *  - 비밀번호 재확인은 기존 `POST /api/admin/reauth`를 그대로 쓴다(비밀번호 `wrong`이면 401)
 */
import { HttpResponse, delay, http } from 'msw'
import type { Page, Source } from '../../../lib/api/types'
import type { BusinessFunction, Role } from '../../../lib/codes'
import { hasRole } from '../../../lib/codes'
// 계약(타입)의 정본은 화면 쪽 api.ts다. 타입 전용 import라 번들에는 남지 않는다
import type {
  BlockEntry, BlocklistRule, CacheStats, FewshotExample, MaskingRule, OpsPolicy,
  PromptDraft, PromptDraftContent, PromptEvalItem, PromptEvaluation, PromptVersion,
} from '../../../routes/admin/settings/promptops/api'

// ---------------------------------------------------------------- 공통 유틸

let seq = 0
const nextId = (prefix: string) => `${prefix}_${Date.now().toString(36)}_${(seq += 1)}`

const DEFAULT_PAGE_SIZE = 20

function envelope<T>(items: T[], url: URL): Page<T> {
  const page = Number(url.searchParams.get('page') ?? 1)
  const size = Number(url.searchParams.get('size') ?? DEFAULT_PAGE_SIZE)
  return { items: items.slice((page - 1) * size, page * size), total: items.length, page, size }
}

function fail(status: number, message: string, retryable = false) {
  return HttpResponse.json(
    { code: 'INTERNAL', user_message: message, retryable, fallback_sources: [], request_id: nextId('req') },
    { status },
  )
}

const roleOf = (request: Request): Role => (request.headers.get('x-mock-role') as Role | null) ?? 'ADMIN'

function denied(request: Request, need: Role) {
  const mine = roleOf(request)
  if (hasRole(mine, need)) return null
  return fail(403, `이 작업에는 ${need} 권한이 필요합니다. 현재 권한은 ${mine}입니다.`)
}

interface WriteBody {
  request_id?: string
  reason?: string
}

/** AD-008은 초안을 서버에 쌓지 않는다. 평가·게시가 그때그때 편집 내용을 실어 보낸다.
 *  `gate_passed`는 직전 [전후 비교]의 회귀 게이트 결과 — 평가가 일시적이라 서버에 남아 있지 않다. */
interface DraftBody {
  draft?: PromptDraftContent
  gate_passed?: boolean
}

function missingWriteFields(body: WriteBody) {
  if (!body?.request_id) return fail(400, 'request_id가 필요합니다.')
  if (!body?.reason?.trim()) return fail(400, '변경 사유를 입력해 주세요.')
  return null
}

const nowIso = () => new Date().toISOString()

// ---------------------------------------------------------------- AD-008 데이터

/** 6원칙 원문 — 기획서 12절 §2.4 표 그대로 */
const BASE_PRINCIPLES: string[] = [
  '근거 자료에 있는 내용만으로 답변',
  '금액·날짜·연락처는 원문 그대로만 인용',
  'URL·주소·전화번호 직접 쓰지 않기',
  '친절·정중, 불확실한 내용은 단정하지 않기',
  'few-shot 예시의 사실 차용 금지',
  '정체 질문에는 "예솜24"로 답하기',
]

/** 게시 직후 Smoke 문항 수 — **서버가 정하는 값**이라 목이 들고 있는다.
 * 프론트 상수(lib/constants.ts)로 두면 서버가 세트를 바꿔도 화면 문구만 옛 숫자로 남는다.
 * 게이트 기준을 화면이 알면 안 된다는 규칙과 같은 이유다(handoff §6 E4) */
const SMOKE_SET_SIZE = 30

/** 시스템 프롬프트 전문 길이(CM-DF-003 06절 "778자"). 원칙 문구를 고치면 그 차이만큼 움직인다 */
const BASE_CHAR_COUNT = 778
const sumLength = (list: string[]) => list.reduce((n, t) => n + t.length, 0)

const SAMPLE_SOURCE: Source = {
  page_id: 'ip_aply_docs',
  breadcrumb: '예금보험금 안내 › 구비서류',
  title: '예금보험금 신청 시 구비서류',
  url: 'https://www.kdic.or.kr/protect/insurance_payment.do',
}

/** 대표 질의 6건 — 기획서 §2.7이 문구를 준 3건 + 나머지 3건은 목 데이터 */
const EVAL_ITEMS: PromptEvalItem[] = [
  {
    id: 'q1',
    question: '위임장 발급 방법은 어디서 확인하나요?',
    verdict: 'IMPROVED',
    note: '서식 위치와 절차를 단계로 안내해 근거 페이지와 일치도가 올라감',
    before: {
      answer:
        '위임장은 대리인이 예금보험금을 신청할 때 필요합니다. 위임인의 인감을 날인해 대리인 신분증과 함께 지급대행지점에 제출하세요.',
      sources: [SAMPLE_SOURCE],
    },
    after: {
      answer:
        "위임장 서식은 '예금보험금 안내 > 신청 시 구비서류' 페이지에서 내려받을 수 있습니다. ① 서식 내려받기 → ② 위임인·대리인 정보 작성과 인감 날인 → ③ 대리인 신분증과 함께 지급대행지점에 제출 순서로 진행하세요.",
      sources: [SAMPLE_SOURCE],
    },
  },
  {
    id: 'q2',
    question: '보호 한도는 얼마인가요?',
    verdict: 'KEEP',
    note: '금액·근거 출처 동일',
    before: { answer: '예금자보호 한도는 금융회사별로 1인당 원금과 이자를 합해 5천만원입니다.', sources: [SAMPLE_SOURCE] },
    after: { answer: '예금자보호 한도는 금융회사별로 1인당 원금과 이자를 합해 5천만원입니다.', sources: [SAMPLE_SOURCE] },
  },
  {
    id: 'q3',
    question: '안녕 (잡담)',
    verdict: 'KEEP',
    note: '범위 외 안내 문구 동일',
    before: { answer: '안녕하세요, 예금보험공사 AI챗봇 예솜24입니다. 무엇을 도와드릴까요?', sources: [] },
    after: { answer: '안녕하세요, 예금보험공사 AI챗봇 예솜24입니다. 무엇을 도와드릴까요?', sources: [] },
  },
  {
    id: 'q4',
    question: '착오송금 반환 신청은 어떻게 하나요?',
    verdict: 'KEEP',
    note: '절차·서류 안내 동일',
    before: { answer: '착오송금 반환지원은 예금보험공사 누리집 또는 방문으로 신청할 수 있습니다.', sources: [SAMPLE_SOURCE] },
    after: { answer: '착오송금 반환지원은 예금보험공사 누리집 또는 방문으로 신청할 수 있습니다.', sources: [SAMPLE_SOURCE] },
  },
  {
    id: 'q5',
    question: '미수령금은 어디서 조회하나요?',
    verdict: 'KEEP',
    note: '조회 경로 동일',
    before: { answer: '고객 미수령금은 예금보험공사 누리집의 미수령금 조회에서 확인할 수 있습니다.', sources: [SAMPLE_SOURCE] },
    after: { answer: '고객 미수령금은 예금보험공사 누리집의 미수령금 조회에서 확인할 수 있습니다.', sources: [SAMPLE_SOURCE] },
  },
  {
    id: 'q6',
    question: '은닉재산 신고는 어떻게 하나요?',
    verdict: 'KEEP',
    note: '신고 경로 동일',
    before: { answer: '은닉재산은 예금보험공사 은닉재산 신고센터로 신고할 수 있습니다.', sources: [SAMPLE_SOURCE] },
    after: { answer: '은닉재산은 예금보험공사 은닉재산 신고센터로 신고할 수 있습니다.', sources: [SAMPLE_SOURCE] },
  },
]

const BLOCK_ACTION_ANSWER = '답변 생성 차단 → 안전 문구로 대체'

/** 12건 — 앞 4건은 기획서 §2.10 목업 원문, 나머지 8건("… 외 8건")은 목 데이터 */
const BLOCKLIST: BlocklistRule[] = [
  { id: 'bw_01', pattern: '수익 보장', type: '단어', scope: '답변', action: BLOCK_ACTION_ANSWER, active: true },
  { id: 'bw_02', pattern: '원금 손실 없음', type: '단어', scope: '답변', action: BLOCK_ACTION_ANSWER, active: true },
  {
    id: 'bw_03',
    pattern: '비속어 기본 사전 (외부 사전)',
    type: '사전',
    scope: '질문 + 답변',
    action: '질문이면 범위 외 안내 · 답변이면 차단',
    active: true,
  },
  {
    id: 'bw_04',
    pattern: '\\d{6}[-]\\d{7} (주민번호 형태)',
    type: '정규식',
    scope: '질문',
    action: '입력 즉시 경고(개인정보 입력 금지 안내)',
    active: true,
  },
  { id: 'bw_05', pattern: '확정 수익', type: '단어', scope: '답변', action: BLOCK_ACTION_ANSWER, active: true },
  { id: 'bw_06', pattern: '무조건 승인', type: '단어', scope: '답변', action: BLOCK_ACTION_ANSWER, active: true },
  { id: 'bw_07', pattern: '100% 보장', type: '단어', scope: '답변', action: BLOCK_ACTION_ANSWER, active: true },
  { id: 'bw_08', pattern: '원금 보장', type: '단어', scope: '답변', action: BLOCK_ACTION_ANSWER, active: true },
  { id: 'bw_09', pattern: '대출 알선', type: '단어', scope: '질문 + 답변', action: BLOCK_ACTION_ANSWER, active: true },
  { id: 'bw_10', pattern: '투자 권유', type: '단어', scope: '답변', action: BLOCK_ACTION_ANSWER, active: true },
  { id: 'bw_11', pattern: '불법 사금융', type: '단어', scope: '질문 + 답변', action: BLOCK_ACTION_ANSWER, active: false },
  {
    id: 'bw_12',
    pattern: '\\d{2,6}[-]\\d{2,6}[-]\\d{2,8} (계좌번호 형태)',
    type: '정규식',
    scope: '질문',
    action: '입력 즉시 경고(개인정보 입력 금지 안내)',
    active: true,
  },
]

/** 3건 — 기획서 §2.11 목업 원문 */
const MASKING: MaskingRule[] = [
  { id: 'mk_01', name: '주민등록번호', pattern: '\\d{6}[-]\\d{7}', replacement: '******-*******', validated: true, sample_count: 12, active: true },
  { id: 'mk_02', name: '계좌번호', pattern: '\\d{2,6}[-]\\d{2,6}[-]\\d{2,8}', replacement: '***-****-***', validated: true, sample_count: 9, active: true },
  { id: 'mk_03', name: '전화번호', pattern: '01[016789][-]?\\d{3,4}[-]?\\d{4}', replacement: '010-****-****', validated: true, sample_count: 15, active: true },
]

/** few-shot 5개 — 기획서에 문안이 없어 목 데이터로 채웠다(탭 라벨의 건수만 정본) */
const FEWSHOTS: FewshotExample[] = [
  { id: 'fs_1', question: '예금자보호 한도가 얼마인가요?', answer: '금융회사별로 1인당 원금과 이자를 합해 5천만원까지 보호됩니다.' },
  { id: 'fs_2', question: '착오송금 반환지원 신청은 어디서 하나요?', answer: '예금보험공사 누리집의 착오송금 반환지원 신청 페이지에서 신청할 수 있습니다.' },
  { id: 'fs_3', question: '보호되지 않는 상품도 있나요?', answer: '투자성 상품 등 일부는 예금자보호 대상이 아닙니다. 상품별 보호 여부는 원문에서 확인해 주세요.' },
  { id: 'fs_4', question: '너 누구야?', answer: '저는 예금보험공사 AI챗봇 예솜24입니다.' },
  { id: 'fs_5', question: '오늘 날씨 어때?', answer: '예금보험공사 업무와 관련된 질문에만 답변드릴 수 있습니다.' },
]

/** 편집 시작점 = 게시본 기준값. 편집은 화면 로컬에만 쌓이므로 서버 초안은 항상 '변경 없음' 상태다
 *  (change_count 0 · dirty 전부 false · evaluation null) */
const draft: PromptDraft = {
  draft_version: 'v1.5',
  base_version: 'v1.4',
  base_updated_at: '2026-07-30T14:20:00+09:00',
  change_count: 0,
  principles: BASE_PRINCIPLES.map((text, i) => ({ id: `p${i + 1}`, text, dirty: false })),
  locked_principle: '근거 사용 마커 표기',
  char_count: BASE_CHAR_COUNT,
  dirty: { prompt: false, fewshot: false, guardrail: false },
  fewshots: FEWSHOTS,
  blocklist: { active: true, items: BLOCKLIST },
  masking: { active: true, items: MASKING },
  evaluation: null,
}

const versions: PromptVersion[] = [
  {
    version: 'v1.4',
    created_at: '2026-07-30T14:20:00+09:00',
    author: 'admin@demo',
    reason: '[NO_SOURCE] 마커 규칙 삭제 (6원칙)',
    status: '현행',
    emergency_candidate: false,
  },
  {
    version: 'v1.2',
    created_at: '2026-07-23T11:05:00+09:00',
    author: 'admin@demo',
    reason: 'URL 생성 금지 강화',
    status: '보관',
    emergency_candidate: true,
  },
]


/** 초안을 건드리면 최신 평가가 무효가 된다(§2.2 "평가 이후 초안을 수정하면 ②부터 다시") */
function touchDraft() {
  draft.evaluation = null
  draft.char_count =
    BASE_CHAR_COUNT + sumLength(draft.principles.map((p) => p.text)) - sumLength(BASE_PRINCIPLES)
  draft.change_count =
    draft.principles.filter((p) => p.dirty).length + (draft.dirty.guardrail ? 1 : 0) + (draft.dirty.fewshot ? 1 : 0)
  draft.dirty.prompt = draft.principles.some((p) => p.dirty)
}

function nextVersion(current: string): string {
  const [major, minor] = current.replace('v', '').split('.')
  return `v${major}.${Number(minor) + 1}`
}

/** 게시된 편집 내용을 새 기준값으로 승격한다 — 서버가 초안 내용을 갖는 유일한 시점이다 */
function promote(content: PromptDraftContent, version: string) {
  draft.principles = content.principles.map((p) => ({ ...p, dirty: false }))
  draft.fewshots = content.fewshots
  draft.blocklist = content.blocklist
  draft.masking = content.masking
  draft.base_version = version
  draft.base_updated_at = nowIso()
  draft.draft_version = nextVersion(version)
  draft.dirty = { prompt: false, fewshot: false, guardrail: false }
  touchDraft()
}

/** 대표 질의 6건 회귀 판정. 목은 초안 내용을 실제로 돌려보지 않고 고정 결과를 준다 */
function evaluate(): PromptEvaluation {
  const improved = EVAL_ITEMS.filter((i) => i.verdict === 'IMPROVED').length
  const regressed = EVAL_ITEMS.filter((i) => i.verdict === 'REGRESSED').length
  return {
    ran_at: nowIso(),
    summary: { total: EVAL_ITEMS.length, keep: EVAL_ITEMS.length - improved - regressed, improved, regressed },
    items: EVAL_ITEMS,
    gate: {
      passed: regressed === 0,
      source_attached: { passed: true, count: 6, total: 6 },
      out_of_scope: { passed: true, count: 2, total: 2 },
      guardrail: { passed: true },
    },
  }
}

// ---------------------------------------------------------------- AD-009 데이터

const opsPolicy: OpsPolicy = {
  version: 'v1.0',
  ip_per_min: 10,
  ip_per_day: 300,
  session_per_30min: 30,
  burst_per_10s: 3,
  over_limit_message: '잠시 후 다시 시도해 주세요. 문의가 많아 잠깐 대기 중이에요.',
  auto_purge: true,
}

const cacheStats: CacheStats = {
  hit_rate: 0.34,
  saved_generations: 1204,
  entries: 3812,
  extension: '시맨틱 캐시',
  extension_applied: false,
  last_purged_at: '2026-07-29T03:02:00+09:00',
  last_purge_reason: '전체 재적재 완료',
}

/** 한 건은 차단 유지 중, 한 건은 이미 만료 — 두 상태를 한 화면에서 볼 수 있게 지금 시각 기준으로 만든다 */
const BOOT = Date.now()
let blocks: BlockEntry[] = [
  {
    id: 'blk_01',
    subject: '211.34.x.x',
    kind: 'IP',
    reason: '10분 내 3회',
    blocked_at: new Date(BOOT - 3 * 60_000).toISOString(),
    expires_at: new Date(BOOT + 7 * 60_000).toISOString(),
    count: 3,
  },
  {
    id: 'blk_02',
    subject: 'sess_8f2c',
    kind: '세션',
    reason: '일일 300회',
    blocked_at: new Date(BOOT - 32 * 60_000).toISOString(),
    expires_at: new Date(BOOT - 22 * 60_000).toISOString(),
    count: 1,
  },
]

// ---------------------------------------------------------------- 핸들러

export const adPromptOpsHandlers = [
  // ================= AD-008 프롬프트 · 가드레일 =================

  /** 편집 시작점 — 게시본 기준값을 준다. 로컬 편집분은 화면이 이 위에 얹는다 */
  http.get('/api/admin/prompt/draft', () => HttpResponse.json(draft)),

  /** ⚠ AD-008 미사용 — 초안은 서버에 쌓이지 않는다(편집은 localStorage, 서버 쓰기는 게시 때뿐).
   *  서버 초안 API를 쓰는 다른 화면·백엔드 계약 대조를 위해 핸들러만 남긴다. */
  http.put('/api/admin/prompt/draft', async ({ request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as WriteBody & Partial<PromptDraft>
    if (!body.request_id) return fail(400, 'request_id가 필요합니다.')
    if (body.principles) {
      draft.principles = body.principles.map((p, i) => ({
        ...p,
        dirty: p.text !== BASE_PRINCIPLES[i],
      }))
    }
    if (body.blocklist) {
      draft.blocklist = body.blocklist
      draft.dirty.guardrail = true
    }
    if (body.masking) {
      // 2026-08-19 정책 변경: 샘플 검증 미통과 패턴도 저장을 막지 않는다 — 화면 경고로만 인지시킨다
      draft.masking = body.masking
      draft.dirty.guardrail = true
    }
    touchDraft()
    return HttpResponse.json(draft)
  }),

  /** ⚠ AD-008 미사용 — 되돌리기는 [초기화](로컬 비우기)로 끝나 서버를 건드리지 않는다.
   *  위 PUT과 같은 이유로 핸들러만 남긴다. */
  http.post('/api/admin/prompt/draft/discard', async ({ request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as WriteBody
    const bad = missingWriteFields(body)
    if (bad) return bad
    draft.principles = BASE_PRINCIPLES.map((text, i) => ({ id: `p${i + 1}`, text, dirty: false }))
    draft.blocklist = { active: true, items: BLOCKLIST }
    draft.masking = { active: true, items: MASKING }
    draft.dirty = { prompt: false, fewshot: false, guardrail: false }
    touchDraft()
    return HttpResponse.json(draft)
  }),

  /** [전후 비교] — 실어 보낸 초안으로 대표 질의 6건을 돌리는 **일시 평가**.
   *  결과만 돌려주고 서버 초안 상태는 건드리지 않는다. 실제로 수 초 걸리는 작업이라 지연을 준다 */
  http.post('/api/admin/prompt/evaluate', async ({ request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as WriteBody & DraftBody
    if (!body.draft) return fail(400, '평가할 초안 내용이 필요합니다.')
    await delay(1_200)
    return HttpResponse.json(evaluate())
  }),

  http.get('/api/admin/prompt/versions', ({ request }) =>
    HttpResponse.json(envelope(versions, new URL(request.url))),
  ),

  /** [롤백] — 선택 버전을 새 초안으로 복원할 뿐 즉시 반영하지 않는다(§2.5) */
  http.post('/api/admin/prompt/versions/:version/rollback', async ({ params, request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as WriteBody
    const bad = missingWriteFields(body)
    if (bad) return bad
    const target = versions.find((v) => v.version === params.version)
    if (!target) return fail(404, '버전을 찾을 수 없습니다.')
    draft.principles = BASE_PRINCIPLES.map((text, i) => ({ id: `p${i + 1}`, text, dirty: i === 2 }))
    draft.dirty.prompt = true
    touchDraft()
    return HttpResponse.json(draft)
  }),

  /** 긴급 롤백(REQ-OPS-003) — 게이트를 기다리지 않고 직전 정상 버전을 즉시 현행으로 */
  http.post('/api/admin/prompt/versions/:version/emergency-rollback', async ({ params, request }) => {
    const no = denied(request, 'ADMIN')
    if (no) return no
    const body = (await request.json()) as WriteBody
    const bad = missingWriteFields(body)
    if (bad) return bad
    const target = versions.find((v) => v.version === params.version)
    if (!target) return fail(404, '해당 버전을 찾을 수 없습니다.')
    if (target.status === '현행') return fail(400, '이미 현행 버전입니다.')
    // 2026-08-19 정책 변경: Smoke 미달 버전도 롤백을 막지 않는다 — 경고 표시는 화면 몫
    for (const v of versions) v.status = v.version === target.version ? '현행' : '보관'
    target.emergency_candidate = false
    return HttpResponse.json(target)
  }),

  /** 게시 — 즉시 Smoke 30문항 실행 후 전환.
   *  요청/승인 2단계는 없앴다(팀 결정 2026-08-04). 편집 권한자(EDITOR 이상)가 바로 게시한다 —
   *  회귀 게이트는 경고로만 인지시키고(2026-08-19 정책 변경), 사후 추적은 활동 로그와 긴급 롤백이 맡는다.
   *  ⚠ 백엔드도 이 권한으로 맞춰야 한다(구 계약은 ADMIN 전용 + publish-requests 승인 경로였다) */
  http.post('/api/admin/prompt/publish', async ({ request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as WriteBody & DraftBody
    const bad = missingWriteFields(body)
    if (bad) return bad
    if (!body.draft) return fail(400, '게시할 초안 내용이 필요합니다.')
    // 2026-08-19 정책 변경: 회귀 게이트는 게시를 막지 않는다 — 미통과는 화면 경고로만 인지시킨다
    await delay(800)
    const published = draft.draft_version
    for (const v of versions) v.status = '보관'
    versions.unshift({
      version: published,
      created_at: nowIso(),
      author: 'admin@demo',
      reason: body.reason!,
      status: '현행',
      emergency_candidate: false,
    })
    promote(body.draft, published)
    return HttpResponse.json({ version: published, smoke: { passed: SMOKE_SET_SIZE, total: SMOKE_SET_SIZE } })
  }),

  /** 마스킹 패턴 샘플 검증 — 판정은 경고 표시용이며 저장을 막지 않는다(2026-08-19 정책 변경, §2.11) */
  http.post('/api/admin/guardrails/masking/validate', async ({ request }) => {
    const no = denied(request, 'EDITOR')
    if (no) return no
    const body = (await request.json()) as { pattern?: string; replacement?: string }
    await delay(400)
    try {
      new RegExp(body.pattern ?? '')
    } catch {
      return HttpResponse.json({ passed: false, sample_count: 0, message: '정규식 문법이 올바르지 않습니다.' })
    }
    if (!body.replacement?.trim()) {
      return HttpResponse.json({ passed: false, sample_count: 0, message: '대체 형식을 입력해 주세요.' })
    }
    // 과대 매칭 방지 — 아무 문자열이나 다 잡는 패턴은 실패로 본다
    if (/^[.*+\s]*$/.test(body.pattern ?? '')) {
      return HttpResponse.json({ passed: false, sample_count: 0, message: '샘플 대화 전체가 매칭됩니다(과대 매칭).' })
    }
    return HttpResponse.json({ passed: true, sample_count: 12, message: '샘플 12건 통과' })
  }),

  // ================= AD-009 운영 정책 =================

  http.get('/api/admin/ops-policy', () => HttpResponse.json(opsPolicy)),

  http.put('/api/admin/ops-policy', async ({ request }) => {
    const no = denied(request, 'ADMIN')
    if (no) return no
    const body = (await request.json()) as WriteBody & Partial<OpsPolicy>
    const bad = missingWriteFields(body)
    if (bad) return bad
    if ((body.ip_per_min ?? 0) < 1) return fail(422, '분당 요청은 1회 이상이어야 합니다.')
    if ((body.ip_per_day ?? 0) < (body.ip_per_min ?? 0)) {
      return fail(422, '일일 요청은 분당 요청보다 크거나 같아야 합니다.')
    }
    await delay(500)
    Object.assign(opsPolicy, {
      ip_per_min: body.ip_per_min ?? opsPolicy.ip_per_min,
      ip_per_day: body.ip_per_day ?? opsPolicy.ip_per_day,
      session_per_30min: body.session_per_30min ?? opsPolicy.session_per_30min,
      over_limit_message: body.over_limit_message ?? opsPolicy.over_limit_message,
      auto_purge: body.auto_purge ?? opsPolicy.auto_purge,
      version: nextVersion(opsPolicy.version),
    })
    return HttpResponse.json(opsPolicy)
  }),

  http.get('/api/admin/cache/stats', () => HttpResponse.json(cacheStats)),

  /** 질의별(OPERATOR 이상) / 전체(ADMIN) 비우기 */
  http.post('/api/admin/cache/purge', async ({ request }) => {
    const body = (await request.json()) as WriteBody & { scope?: 'query' | 'all'; query?: string }
    const no = denied(request, body.scope === 'all' ? 'ADMIN' : 'OPERATOR')
    if (no) return no
    const bad = missingWriteFields(body)
    if (bad) return bad
    if (body.scope === 'query' && !body.query?.trim()) return fail(400, '비울 질의를 입력해 주세요.')
    await delay(600)
    const removed = body.scope === 'all' ? cacheStats.entries : 1
    cacheStats.entries -= removed
    cacheStats.last_purged_at = nowIso()
    cacheStats.last_purge_reason = body.scope === 'all' ? '전체 비우기' : `질의별 비우기 (${body.query})`
    return HttpResponse.json({ removed, ...cacheStats })
  }),

  http.get('/api/admin/blocks', ({ request }) => HttpResponse.json(envelope(blocks, new URL(request.url)))),

  http.post('/api/admin/blocks/:id/release', async ({ params, request }) => {
    const no = denied(request, 'OPERATOR')
    if (no) return no
    const body = (await request.json()) as WriteBody
    const bad = missingWriteFields(body)
    if (bad) return bad
    if (!blocks.some((b) => b.id === params.id)) return fail(404, '차단 항목을 찾을 수 없습니다.')
    blocks = blocks.filter((b) => b.id !== params.id)
    return new HttpResponse(null, { status: 204 })
  }),

  /** 추천 질문 저장 전 금칙어 검사 — 미통과면 저장 차단(CM-DF-004 07절) */
  http.post('/api/admin/suggested-questions/validate', async ({ request }) => {
    const body = (await request.json()) as { text?: string; business_function?: BusinessFunction }
    const text = body.text ?? ''
    const hit = draft.blocklist.items.find((rule) => rule.type === '단어' && rule.active && text.includes(rule.pattern))
    if (hit) {
      return HttpResponse.json({ passed: false, message: `금칙어 '${hit.pattern}'가 포함되어 저장할 수 없습니다.` })
    }
    return HttpResponse.json({ passed: true, message: '' })
  }),
]
