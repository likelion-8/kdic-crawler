/** AD-004(파이프라인) · AD-005(대화 로그) 전용 목 — handlers/admin.ts에 없는 접점만 채운다.
 *
 * admin.ts가 이미 가진 것(작업 생성·목록·취소·재시도·롤백)은 그대로 쓰고,
 * 여기서는 기획서에만 있고 계약이 없는 것들을 채운다(10 §E · 11 §3).
 *  - 변경 페이지 알림 / 지금 확인 ↻ (AD-004 R2)
 *  - 확인 모달의 대상 건수·예상 소요 (AD-004 B-6·B-7 · 이슈 G-23)
 *  - 대화 로그 목록·요약·상세·조치·내보내기 (AD-005 전부)
 *
 * 목업 숫자는 예시라 여기 데이터도 예시다. 화면은 이 응답만 보고 그린다(하드코딩 금지).
 * 단계별 소요 합계는 응답 시간과 일치시켜 두었다 — 기획서 목업은 5.9 vs 9.2로 어긋난다(11 §M1).
 */
import { HttpResponse, delay, http } from 'msw'
import type { Page } from '../../../lib/api/types'
import type { BusinessFunction, ErrorCode, Intent, QuestionType, Role, TriageStatus } from '../../../lib/codes'
import { hasRole } from '../../../lib/codes'

// ---------------------------------------------------------------- 공통

let seq = 0
const nextId = (prefix: string) => `${prefix}_${Date.now().toString(36)}_${(seq += 1)}`

function fail(status: number, message: string) {
  return HttpResponse.json(
    { code: 'INTERNAL', user_message: message, retryable: false, fallback_sources: [], request_id: nextId('req') },
    { status },
  )
}

/** CSV 첨부파일 응답 — 서버(api/export_csv.py)와 같은 모양이라야 apiDownload 가 목에서도 돈다.
 *  BOM 은 엑셀이 UTF-8 로 읽게 하는 표시다(윈도우에서 없으면 한글이 깨진다). */
function csvFile(filename: string, lines: string[], rows: number) {
  return new HttpResponse('\uFEFF' + lines.join('\r\n') + '\r\n', {
    headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': `attachment; filename="${filename}"`,
      'X-Export-Rows': String(rows),
    },
  })
}

/** handlers/admin.ts와 같은 개발용 스위치 — 헤더가 없으면 ADMIN으로 본다 */
const roleOf = (request: Request): Role => (request.headers.get('x-mock-role') as Role | null) ?? 'ADMIN'

function denied(request: Request, need: Role) {
  const mine = roleOf(request)
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

/** KST 기준 오늘(YYYY-MM-DD). 브라우저 타임존과 무관하게 고정한다 */
const KST_TODAY = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Seoul',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
}).format(new Date())

const at = (hhmm: string, date: string = KST_TODAY) => `${date}T${hhmm}:00+09:00`

// ---------------------------------------------------------------- AD-004 변경 페이지 알림

/** 원본 사이트 본문이 바뀐 페이지 1건 (AD-004 R2) */
export interface ChangedPage {
  page_id: string
  /** 카드 1행 — 짧은 제목 */
  title: string
  /** 보조 표기에 쓰는 원문 제목 */
  source_title: string
  /** 본문 변경을 감지한 시각 */
  detected_at: string
}

const CHANGED_PAGES: ChangedPage[] = [
  {
    page_id: 'kmrs_apply_mthd',
    title: '착오송금 반환지원 신청',
    source_title: '착오송금 반환지원 신청 방법',
    detected_at: '2026-07-28T04:12:00+09:00',
  },
  {
    page_id: 'dp_faq_page',
    title: '예금자보호 FAQ',
    source_title: '예금자보호제도 FAQ',
    detected_at: '2026-07-27T03:41:00+09:00',
  },
]

let lastCheckedAt = '2026-07-29T03:00:00+09:00'

export interface ChangedPagesResponse {
  last_checked_at: string
  items: ChangedPage[]
}

// ---------------------------------------------------------------- AD-004 실행 전 견적

/** 확인 모달의 '대상'·'예상 소요' (이슈 G-23 — 서버가 줘야 하는 값) */
export interface JobEstimate {
  type: string
  /** 전체 재수집=페이지 수 · 재적재=문서 수 */
  target_count: number
  estimated_minutes: number
}

const ESTIMATES: Record<string, JobEstimate> = {
  FULL_RECRAWL: { type: 'FULL_RECRAWL', target_count: 58, estimated_minutes: 12 },
  REINDEX: { type: 'REINDEX', target_count: 58, estimated_minutes: 8 },
  SELECTED_RECRAWL: { type: 'SELECTED_RECRAWL', target_count: CHANGED_PAGES.length, estimated_minutes: 4 },
}

// ---------------------------------------------------------------- AD-005 대화 로그

export type LogStatus = 'NORMAL' | 'OUT_OF_SCOPE' | 'FAILED'
export type FeedbackVote = 'up' | 'down'

/** 목록 한 행 — 컬럼: 시각/질문/성격/상태/피드백/출처/응답 (AD-005 1.4) */
export interface ConversationLogRow {
  request_id: string
  occurred_at: string
  /** 마스킹된 저장본. 원문은 어떤 권한으로도 볼 수 없다 */
  question_masked: string
  /** 플래너 전에 끝난 건(캐시 적중·가드레일 거절·Gate EXIT)은 null */
  intent: Intent | null
  /** 성격이 없는 행이 왜 비었는지 — 표의 분류 칸이 이 값을 대신 적는다. 평소 경로는 null */
  served_from?: 'cache' | 'guardrail' | 'gate1' | 'gate2' | 'gate3' | 'clarify' | null
  status: LogStatus
  feedback: FeedbackVote | null
  /** 실패 건은 null(화면에서 '—') */
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
 *  `rag_retrieval_results` 테이블은 삭제됐고 `rag_runs`에는 `total_latency_ms`만 있다
 *  (src/schema.py) — 이 두 가지를 서버가 만들어 낼 방법이 없어 추적으로 넘긴다.
 *  ⚠ 백엔드는 `rag_runs.trace_id`를 채우고, 여기 `url`은 **완성된 주소**로 내려줘야 한다.
 *     프론트가 Langfuse 호스트를 알 이유가 없고, 조각을 붙이면 배포 환경이 바뀔 때마다 깨진다. */
export interface LangfuseTrace {
  id: string
  url: string | null
}

export interface LogErrorDetail {
  /** 앞 4행은 서버가 rag_runs.error_code 하나에서 파생한다(api/rag/answer.ERROR_CATALOG).
   *  그 컬럼(2026-08-19) 이전 실패에는 분류 기록이 없어 전부 null 로 온다 */
  code: ErrorCode | null
  /** 코드 + 뜻 병기용 뒷부분 */
  meaning: string | null
  /** 사용자에게 실제로 나갔던 문구 */
  user_message: string | null
  /** 서버가 스스로 재시도했는지. 재시도는 구현하지 않기로 확정해 현재 전부 '없음' */
  auto_retry: string | null
  fallback: string | null
  /** rag_runs.failure_stage — 단계별 소요가 아니라 '어디서 멈췄나' 한 값 */
  failure_stage: string | null
  /** rag_runs.root_cause */
  root_cause: string | null
}

/** rag_runs.observation — 모양의 정본은 api/rag/observation.py */
export interface RunObservation {
  subs: {
    question: string
    intent: Intent | null
    top: { chunk_id: string; page_id: string; score: number }[]
    marker: boolean | null
    used_source: boolean | null
    kind: string | null
    appropriate: boolean | null
    normalized: boolean | null
    /** Gate3(검색 관련도 게이트, 2026-08-25)가 이 하위 질문에서 EXIT했으면 "gate3" */
    exit_at: string | null
    gate3_reason: string | null
    retrieval_top1_score: number | null
    retrieval_threshold: number | null
  }[]
}

export interface ConversationLogDetail extends ConversationLogRow {
  /** 관측 신설(2026-08-14) 이전 대화는 null. 캐시 응답도 검색을 안 타 null 이다 */
  observation: RunObservation | null
  /** 답변을 낸 경로. gate3만 검색은 돌고 생성만 건너뛴다(관측이 채워짐) — 나머지 다섯은
   *  검색·생성 둘 다 안 타 성격·유형·근거가 없다. 평소 경로는 null */
  served_from: 'cache' | 'guardrail' | 'gate1' | 'gate2' | 'gate3' | 'clarify' | null
  /** 그 경로에서 걸린 규칙 이름(Gate 1 의 FIXED_GREETING 등). 원시 식별자 */
  served_label: string | null
  classification: {
    intent: Intent | null
    business_function: BusinessFunction | null
    question_type: QuestionType | null
    source_used: boolean | null
    /** 첫 줄 근거 사용 마커. 판정 원천이 없으면 null 이다 */
    marker: string | null
    /** 마커가 어긋나 정규화로 보정한 건 */
    normalized: boolean
  }
  langfuse: LangfuseTrace | null
  /** rag_runs.total_latency_ms */
  total_latency_ms: number | null
  answer_masked_preview: string
  answer_masked_full: string
  /** 본문 뒤에 붙는 출처·서류·하위 답변. 원천은 chat_messages(rag_runs 와 request_id 로 이어진다) */
  answer_composition?: {
    sources: { page_id: string; breadcrumb: string; title: string; url: string }[]
    attachments: { label: string; url: string; kind: 'document' | 'link' }[]
    sub_answers: {
      title: string
      answer: string
      sources: { page_id: string; breadcrumb: string; title: string; url: string }[]
      attachments: { label: string; url: string; kind: 'document' | 'link' }[]
    }[]
  } | null
  feedback_detail: {
    vote: FeedbackVote
    at: string
    reason_label: string
    comment: string
  } | null
  error: LogErrorDetail | null
  /** [처리 완료 표시] 때 받은 조치 사유. 아직 처리하지 않았으면 null */
  triage_reason: string | null
}

const ANSWER_FULL =
  '착오송금일로부터 1년 이내에 예금보험공사에 반환지원을 신청할 수 있습니다. 신청 시에는 착오송금 사실을 확인할 수 있는 이체확인증과 신분증 사본이 필요하며, 온라인 신청 페이지 또는 방문 접수로 진행합니다. 신청 후 예금보험공사가 수취인의 연락처를 확인해 자진 반환을 안내하고, 반환이 이루어지지 않으면 지급명령 등 회수 절차를 진행합니다.'

const rows: ConversationLogRow[] = [
  {
    request_id: '4a01-77bc', occurred_at: at('09:41'), question_masked: '예금자보호 한도가 얼마인가요?',
    intent: 'informational', status: 'NORMAL', feedback: 'up', source_count: 2, latency_s: 7.9, triage: 'NONE',
  },
  {
    // 위 4a01-77bc 와 같은 질문 — 저장해 둔 답을 그대로 돌려준 건이라 소요가 1초대다
    request_id: '2b77-05e1', occurred_at: at('09:40'), question_masked: '예금자보호 한도가 얼마인가요?',
    intent: null, served_from: 'cache', status: 'NORMAL', feedback: null, source_count: null, latency_s: 1.2,
    triage: 'NONE',
  },
  {
    // Gate 1 규칙 필터가 인사로 판정해 즉답한 건 — LLM 을 안 불러 0.1초다.
    // 상태는 '범위 외'다 — fixed_gate_response 가 out_of_scope=True 로 감싸 rag_runs 에
    // OUT_OF_SCOPE 로 남는다(api/rag/answer.py:573). 캐시·되묻기는 out_of_scope=False 라 정상이다
    request_id: '9c40-1d22', occurred_at: at('09:39'), question_masked: '안녕하세요',
    intent: null, served_from: 'gate1', status: 'OUT_OF_SCOPE', feedback: null, source_count: null, latency_s: 0.1,
    triage: 'NONE',
  },
  {
    request_id: '7d1a-93f2', occurred_at: at('09:38'), question_masked: '착오송금 반환지원 신청 방법',
    intent: 'civil_petition', status: 'NORMAL', feedback: 'down', source_count: 3, latency_s: 5.9, triage: 'NONE',
  },
  {
    request_id: '8f2c-41ab', occurred_at: at('09:36'), question_masked: '예금보험금 신청 서류 알려주세요',
    intent: 'civil_petition', status: 'FAILED', feedback: null, source_count: null, latency_s: null, triage: 'NONE',
  },
  {
    // 복합 질문 — 플래너가 둘로 나눠 하위마다 근거·출처가 따로 붙는다
    request_id: 'e410-2f9b', occurred_at: at('09:34'), question_masked: '착오송금 신청 방법과 필요 서류는?',
    intent: 'civil_petition', status: 'NORMAL', feedback: null, source_count: 3, latency_s: 12.4,
    triage: 'NONE',
  },
  {
    // 업무 되묻기 — 어느 업무인지 정해지지 않아 선택지로 되물었다. 검색·생성을 안 타 1초대
    request_id: 'f733-6b02', occurred_at: at('09:33'), question_masked: '신청 링크 알려줘',
    intent: null, served_from: 'clarify', status: 'NORMAL', feedback: null, source_count: null, latency_s: 1.1,
    triage: 'NONE',
  },
  {
    request_id: '2b58-0c14', occurred_at: at('09:31'), question_masked: '안녕',
    intent: 'informational', status: 'OUT_OF_SCOPE', feedback: null, source_count: 0, latency_s: 3.1, triage: 'NONE',
  },
  {
    request_id: '9e33-5f70', occurred_at: at('09:24'), question_masked: '대출 금리 알려줘',
    intent: 'informational', status: 'OUT_OF_SCOPE', feedback: 'down', source_count: 0, latency_s: 4.0, triage: 'NONE',
  },
  {
    request_id: '1c47-a8d9', occurred_at: at('09:17'), question_masked: '미수령금 조회는 어디서 하나요?',
    intent: 'civil_petition', status: 'NORMAL', feedback: null, source_count: 2, latency_s: 8.8, triage: 'NONE',
  },
  {
    request_id: '6d92-3e11', occurred_at: at('09:11'), question_masked: '보호대상 금융상품인지 확인',
    intent: 'informational', status: 'NORMAL', feedback: 'up', source_count: 1, latency_s: 7.2, triage: 'NONE',
  },
  {
    request_id: '0af6-b273', occurred_at: at('09:04'), question_masked: '예금보험 가입 금융회사 조회',
    intent: 'informational', status: 'NORMAL', feedback: 'up', source_count: 3, latency_s: 6.5, triage: 'NONE',
  },
  {
    request_id: '3f80-cc45', occurred_at: at('08:57'), question_masked: '착오송금 반환지원 신청서 양식',
    intent: 'civil_petition', status: 'NORMAL', feedback: null, source_count: 2, latency_s: 8.1, triage: 'NONE',
  },
  {
    request_id: '5b21-9d06', occurred_at: at('08:49'), question_masked: '오늘 날씨 어때',
    intent: 'informational', status: 'OUT_OF_SCOPE', feedback: null, source_count: 0, latency_s: 2.8, triage: 'RESOLVED',
  },
  // 기간 필터(7일/30일)를 눌러야 보이는 어제·지난주 건
  {
    request_id: 'ab19-4e82', occurred_at: at('16:20', shiftKstDate(-1)), question_masked: '은닉재산 신고 포상금은 얼마인가요?',
    intent: 'informational', status: 'NORMAL', feedback: 'up', source_count: 2, latency_s: 6.9, triage: 'NONE',
  },
  {
    request_id: 'cd57-1a30', occurred_at: at('11:02', shiftKstDate(-8)), question_masked: '채무조정 신청 자격이 궁금해요',
    intent: 'civil_petition', status: 'NORMAL', feedback: null, source_count: 1, latency_s: 7.4, triage: 'NONE',
  },
]

/** KST 오늘에서 n일 이동한 날짜(YYYY-MM-DD) */
function shiftKstDate(days: number): string {
  const base = new Date(`${KST_TODAY}T00:00:00+09:00`)
  base.setUTCDate(base.getUTCDate() + days)
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(base)
}

/** 상세는 목록 행에서 파생하고, 목업에 값이 있는 2건만 실제 값을 채운다 */
const DETAIL_OVERRIDE: Record<string, Partial<ConversationLogDetail>> = {
  // Gate 1 EXIT — '분류 기록 없음 — 범위 판정 (Gate 1) · 인사' 가 뜨는 상태
  '9c40-1d22': {
    served_from: 'gate1',
    served_label: 'FIXED_GREETING',
    observation: null,
    classification: {
      intent: null, business_function: null, question_type: null,
      source_used: null, marker: null, normalized: false,
    },
    langfuse: null,
  },
  // 캐시 적중 — 검색·생성을 건너뛰어 관측이 없다. 판정을 지어내지 않고 null 로 둔다
  '2b77-05e1': {
    served_from: 'cache',
    served_label: null,
    observation: null,
    classification: {
      // 플래너를 안 타 성격·유형이 저장되지 않는다 — 화면은 '분류 기록 없음'을 적는다
      intent: null, business_function: null, question_type: null,
      source_used: null, marker: null, normalized: false,
    },
    langfuse: null,
  },
  // 업무 되묻기 — 분류 줄이 '업무 되묻기' 한 줄로만 뜨는 상태
  'f733-6b02': {
    served_from: 'clarify',
    served_label: null,
    observation: null,
    classification: {
      intent: null, business_function: null, question_type: null,
      source_used: null, marker: null, normalized: false,
    },
    langfuse: null,
    answer_masked_preview: '어떤 업무를 찾고 계신가요? 아래에서 골라주시면 바로 안내해 드릴게요.',
    answer_masked_full: '어떤 업무를 찾고 계신가요? 아래에서 골라주시면 바로 안내해 드릴게요.',
    // 되묻기 턴에는 출처·서류가 붙지 않는다(검색 전에 끝난다)
    answer_composition: { sources: [], attachments: [], sub_answers: [] },
  },
  // 복합 질문 — 분류 줄에 '복합 질문 2개', 하위마다 답변·서류·출처가 따로 붙는다.
  // 하위 판정이 갈려 출처 판정이 '일부 사용'으로 뜬다.
  'e410-2f9b': {
    classification: {
      intent: 'civil_petition', business_function: '착오송금 반환 신청', question_type: 'fact',
      source_used: true, marker: '혼재', normalized: false,
    },
    observation: {
      subs: [
        {
          question: '착오송금 반환지원 신청 방법은 무엇인가요?',
          intent: 'civil_petition',
          top: [
            { chunk_id: 'faq_msdr_apply#2', page_id: 'faq_msdr_apply', score: 0.882 },
            { chunk_id: 'faq_msdr_apply#5', page_id: 'faq_msdr_apply', score: 0.804 },
          ],
          marker: true, used_source: true, kind: 'grounded', appropriate: true, normalized: false,
          exit_at: null, gate3_reason: null, retrieval_top1_score: null, retrieval_threshold: null,
        },
        {
          question: '착오송금 반환지원 신청에 필요한 서류는 무엇인가요?',
          intent: 'civil_petition',
          top: [{ chunk_id: 'sender_docs#1', page_id: 'sender_docs', score: 0.641 }],
          marker: false, used_source: false, kind: 'refusal', appropriate: true, normalized: false,
          exit_at: null, gate3_reason: null, retrieval_top1_score: null, retrieval_threshold: null,
        },
      ],
    },
    langfuse: { id: 'tr_e4102f9b', url: 'https://langfuse.example.com/trace/tr_e4102f9b' },
    total_latency_ms: 12400,
    answer_masked_preview: '착오송금 반환지원은 온라인과 방문 두 가지 방법으로…',
    answer_masked_full: '착오송금 반환지원은 온라인과 방문 두 가지 방법으로 신청할 수 있습니다.',
    answer_composition: {
      // 🔴 하위가 있으면 최상위 sources·attachments 는 빈 배열이다(챗봇 응답과 같은 불변식)
      sources: [],
      attachments: [],
      sub_answers: [
        {
          title: '착오송금 반환지원 신청 방법은 무엇인가요?',
          answer:
            '온라인 신청은 공동인증서와 이체(송금)확인증을 준비해 진행하고, 방문 신청은 서울시 중구 청계천로 30 1층에서 접수합니다.',
          sources: [{
            page_id: 'faq_msdr_apply', breadcrumb: '착오송금 반환지원 > 자주 묻는 질문',
            title: '착오송금 반환지원 자주 묻는 질문',
            url: 'https://www.kdic.or.kr/msdr/faq.do',
          }],
          attachments: [{
            label: '착오송금 반환지원 신청방법',
            url: 'https://www.kdic.or.kr/msdr/apply_mthd.do', kind: 'link',
          }],
        },
        {
          title: '착오송금 반환지원 신청에 필요한 서류는 무엇인가요?',
          answer: '안내해 드릴 수 있는 자료에서 해당 내용을 찾지 못했습니다.',
          sources: [],
          attachments: [],
        },
      ],
    },
  },
  '7d1a-93f2': {
    classification: {
      intent: 'civil_petition', business_function: '착오송금 반환 신청', question_type: 'fact',
      // 마커가 남아 있는 건 — 2026-08-20 이전 대화이거나, AD-008 게시 프롬프트가 아직
      // 마커를 요구하는 경우다(파싱은 하위호환으로 유지). 대괄호까지가 서버가 내리는 값이다
      source_used: true, marker: '[SOURCE_USED]', normalized: false,
    },
    langfuse: { id: 'tr_7d1a93f2', url: 'https://langfuse.example.com/trace/tr_7d1a93f2' },
    total_latency_ms: 5900,
    answer_masked_preview: '착오송금일로부터 1년 이내에… 필요 서류 … 신청 페이지 …',
    answer_masked_full: ANSWER_FULL,
    feedback_detail: {
      vote: 'down', at: at('09:39'), reason_label: '내용이 부정확',
      comment: '필요 서류 목록이 실제 신청 페이지와 달라요',
    },
    // 👎 사유가 '서류 목록이 다르다'인 건 — 관리자가 실제로 나간 서류 링크를 여기서 확인한다
    answer_composition: {
      sources: [{
        page_id: 'faq_msdr_apply', breadcrumb: '착오송금 반환지원 > 자주 묻는 질문',
        title: '착오송금 반환지원 자주 묻는 질문',
        url: 'https://www.kdic.or.kr/msdr/faq.do',
      }],
      attachments: [
        { label: '착오송금 반환지원 신청서', url: 'https://www.kdic.or.kr/msdr/form1.do', kind: 'document' },
        { label: '개인정보 수집·이용 동의서', url: 'https://www.kdic.or.kr/msdr/form2.do', kind: 'document' },
        { label: '착오송금 반환지원 신청방법', url: 'https://www.kdic.or.kr/msdr/apply_mthd.do', kind: 'link' },
      ],
      sub_answers: [],
    },
  },
  '8f2c-41ab': {
    classification: {
      intent: 'civil_petition', business_function: '예금보험금 안내', question_type: 'link_guide',
      source_used: false, marker: null, normalized: false,
    },
    langfuse: { id: 'tr_8f2c41ab', url: 'https://langfuse.example.com/trace/tr_8f2c41ab' },
    total_latency_ms: null,
    answer_masked_preview: '',
    answer_masked_full: '',
    feedback_detail: null,
    // 🔴 서버는 ERROR_CATALOG 의 문구를 그대로 내려주고 failure_stage 는 **원시 식별자**다
    // (화면이 STAGE_LABEL 로 '답변 생성'으로 옮겨 적는다). 목이 이미 다듬은 값을 주면
    // 라벨 매핑이 목 모드에서 검증되지 않는다. 자동 재시도는 없다(2026-08-19 확정).
    error: {
      code: 'LLM_TIMEOUT',
      meaning: '답변 생성 시간 초과',
      user_message: '답변 생성이 지연되고 있어요. 잠시 후 다시 시도해 주세요.',
      auto_retry: '없음',
      fallback: '제공됨',
      failure_stage: 'llm',
      root_cause: 'TimeoutError: 답변 생성 시간 초과(30초)',
    },
  },
}

/** 조치 사유는 서버가 rag_runs.triage_reason 에 보관한다 — 목에서는 메모리에만 */
const triageReasons: Record<string, string> = {}

function detailOf(row: ConversationLogRow): ConversationLogDetail {
  const base: ConversationLogDetail = {
    ...row,
    // 관측(rag_runs.observation). source_count 가 있는 행은 근거를 그만큼 만들어 실화면과
    // 같은 모양을 낸다. 범위 외 답변은 근거 없이 빈 top — '데이터 없음' 갈래의 목업이다.
    observation: {
      subs: [{
        question: row.question_masked,
        intent: row.intent,
        // chunk_id 는 '{page_id}#{번호}' 규약이다(api/rag/observation.page_of · chunks_all.jsonl).
        // 종전에는 chunk_id 앞부분과 page_id 가 서로 달라(dp_protlmts#c2 / dp_faq_page_1) 실제로
        // 올 수 없는 값이었다. 같은 페이지에서 청크가 여럿 뽑히는 흔한 경우도 함께 만든다 —
        // 화면이 그 둘을 구분해 그리는지 목에서 바로 보이게(2026-08-26).
        top: Array.from({ length: row.source_count ?? 0 }, (_, i) => {
          const page = i % 2 === 0 ? 'dp_protlmts' : `dp_faq_page_${Math.ceil(i / 2)}`
          return {
            chunk_id: `${page}#${i}`,
            page_id: page,
            score: Number((0.87 - i * 0.06).toFixed(3)),
          }
        }),
        marker: (row.source_count ?? 0) > 0,
        used_source: (row.source_count ?? 0) > 0,
        kind: (row.source_count ?? 0) > 0 ? 'grounded' : 'refusal',
        appropriate: true,
        normalized: false,
        exit_at: null, gate3_reason: null, retrieval_top1_score: null, retrieval_threshold: null,
      }],
    },
    classification: {
      intent: row.intent,
      business_function: row.status === 'OUT_OF_SCOPE' ? null : '예금자보호제도',
      question_type: row.status === 'OUT_OF_SCOPE' ? 'out_of_scope' : 'faq',
      source_used: (row.source_count ?? 0) > 0,
      // 2026-08-20(exp/hcx007-no-marker-v1) 이후 프롬프트에서 마커 지시를 뺐다 — 정상 응답엔
      // 마커가 없어 관측에 null 로 남는다. 판정은 사후검증이 한다(api/rag/sse.py _MarkerStripper).
      // 'SOURCE_UNUSED' 는 백엔드에 없는 값이었다(실제 값은 '[SOURCE_USED]' | '[NO_SOURCE]' | '혼재')
      marker: null,
      normalized: false,
    },
    // 평소 경로는 검색·생성을 탄다. 플래너 앞에서 끝난 건만 값이 있다(DETAIL_OVERRIDE 참고)
    served_from: null,
    served_label: null,
    // 추적이 없는 실행도 있다 — trace_id를 못 남긴 경우(로깅 실패는 응답을 막지 않는다)
    langfuse: null,
    total_latency_ms: row.latency_s === null ? null : Math.round(row.latency_s * 1000),
    answer_masked_preview: '답변 미리보기…',
    answer_masked_full: ANSWER_FULL,
    // 근거를 쓴 건에는 참고 출처가 붙는다. 서류·신청 페이지는 민원 답변에만 있어 여기선 비운다
    answer_composition: {
      sources: (row.source_count ?? 0) > 0
        ? [{
            page_id: 'dp_protlmts', breadcrumb: '예금자보호제도 > 보호한도',
            title: '예금자보호 한도', url: 'https://www.kdic.or.kr/protect/limit.do',
          }]
        : [],
      attachments: [],
      sub_answers: [],
    },
    feedback_detail: null,
    error: null,
    triage_reason: triageReasons[row.request_id] ?? null,
  }
  return { ...base, ...DETAIL_OVERRIDE[row.request_id] }
}

// ---------------------------------------------------------------- 핸들러

export const adPipelineLogsHandlers = [
  // ---- AD-004 변경 페이지 알림 ----
  http.get('/api/admin/pipeline/changes', () =>
    HttpResponse.json<ChangedPagesResponse>({ last_checked_at: lastCheckedAt, items: CHANGED_PAGES })),

  // [지금 확인 ↻] — 수동 재검사. 본문 해시를 다시 떠 보는 동작이라 시간이 걸린다
  http.post('/api/admin/pipeline/changes/recheck', async ({ request }) => {
    const no = denied(request, 'OPERATOR')
    if (no) return no
    await delay(900)
    lastCheckedAt = new Date().toISOString()
    return HttpResponse.json<ChangedPagesResponse>({ last_checked_at: lastCheckedAt, items: CHANGED_PAGES })
  }),

  // ---- AD-004 확인 모달의 대상·예상 소요 ----
  http.get('/api/admin/pipeline/estimate', async ({ request }) => {
    const type = new URL(request.url).searchParams.get('type') ?? 'FULL_RECRAWL'
    const estimate = ESTIMATES[type]
    if (!estimate) return fail(404, '예상 소요를 계산할 수 없는 작업 유형입니다.')
    await delay(250) // 모달을 연 뒤 값이 채워지는 걸 화면에서 볼 수 있게
    return HttpResponse.json(estimate)
  }),

  // ---- AD-005 대화 로그 ----
  http.get('/api/admin/logs', ({ request }) => {
    // VIEWER는 집계만 — 목록(마스킹 질문)도 서버가 막는다. 화면 숨김만으로는 계약이 아니다(Desc 0)
    const no = denied(request, 'OPERATOR')
    if (no) return no
    const url = new URL(request.url)
    const from = url.searchParams.get('from')
    const to = url.searchParams.get('to')
    const status = url.searchParams.get('status')
    const intent = url.searchParams.get('intent')
    const feedback = url.searchParams.get('feedback')
    const q = (url.searchParams.get('q') ?? '').trim()

    let list = rows
    // occurred_at은 +09:00 고정이라 앞 10글자가 곧 KST 날짜다
    if (from) list = list.filter((r) => r.occurred_at.slice(0, 10) >= from)
    if (to) list = list.filter((r) => r.occurred_at.slice(0, 10) <= to)
    if (status) list = list.filter((r) => r.status === status)
    if (intent) list = list.filter((r) => r.intent === intent)
    if (feedback === 'none') list = list.filter((r) => r.feedback === null)
    else if (feedback) list = list.filter((r) => r.feedback === feedback)
    // 검색은 마스킹된 저장본만 훑는다(원문 개인정보는 저장하지 않는다)
    if (q) list = list.filter((r) => r.question_masked.includes(q))

    const sorted = [...list].sort((a, b) => b.occurred_at.localeCompare(a.occurred_at))
    const page = Number(url.searchParams.get('page') ?? 1)
    const size = Number(url.searchParams.get('size') ?? 20)
    const body: Page<ConversationLogRow> = {
      items: sorted.slice((page - 1) * size, page * size),
      total: sorted.length,
      page,
      size,
    }
    return HttpResponse.json(body)
  }),

  // 요약 스트립은 필터와 무관하게 항상 '오늘' 기준이다(11 §H2 대응)
  // 스트립은 기간에 연동한다(from·to 는 목록과 같은 KST 날짜). 둘 다 없으면 오늘 —
  // 나머지 필터는 반영하지 않는다(스트립이 상태별 분해라 상태를 걸면 나머지 칸이 0 이 된다)
  http.get('/api/admin/logs/summary', ({ request }) => {
    const url = new URL(request.url)
    const from = url.searchParams.get('from') || KST_TODAY
    const to = url.searchParams.get('to') || KST_TODAY
    const inRange = rows.filter((r) => {
      const day = r.occurred_at.slice(0, 10)
      return day >= from && day <= to
    })
    const body: LogSummary = {
      total: inRange.length,
      normal: inRange.filter((r) => r.status === 'NORMAL').length,
      out_of_scope: inRange.filter((r) => r.status === 'OUT_OF_SCOPE').length,
      failed: inRange.filter((r) => r.status === 'FAILED').length,
      feedback_up: inRange.filter((r) => r.feedback === 'up').length,
      feedback_down: inRange.filter((r) => r.feedback === 'down').length,
    }
    return HttpResponse.json(body)
  }),

  http.get('/api/admin/logs/:requestId', ({ params, request }) => {
    // VIEWER는 집계만 — 마스킹된 상세도 볼 수 없다
    const no = denied(request, 'OPERATOR')
    if (no) return no
    const row = rows.find((r) => r.request_id === params.requestId)
    if (!row) return fail(404, '대화 로그를 찾을 수 없습니다.')
    return HttpResponse.json(detailOf(row))
  }),

  // [처리 완료 표시] / [처리 완료 취소] — 완료는 사유 필수, 되돌리기는 선택(admin_logs.patch_log)
  http.patch('/api/admin/logs/:requestId', async ({ params, request }) => {
    const no = denied(request, 'OPERATOR')
    if (no) return no
    const body = (await request.json()) as { request_id?: string; reason?: string; triage?: TriageStatus }
    if (!body.request_id) return fail(400, 'request_id가 필요합니다.')
    const triage = body.triage ?? 'RESOLVED'
    if (triage === 'RESOLVED' && !body.reason?.trim()) return fail(400, '조치 사유를 입력해 주세요.')
    const row = rows.find((r) => r.request_id === params.requestId)
    if (!row) return fail(404, '대화 로그를 찾을 수 없습니다.')
    row.triage = triage
    // 되돌리면 서버가 조치 사유도 지운다 — 남겨 두면 '미처리인데 사유가 있는' 행이 된다
    if (triage === 'NONE') delete triageReasons[row.request_id]
    else triageReasons[row.request_id] = body.reason ?? ''
    return HttpResponse.json(row)
  }),

  // 내보내기 — CSV 파일을 그대로 내려준다(2026-08-25 QA 이후). 사실 자체는 활동 로그에 남는다(AD-005 Desc 0)
  http.post('/api/admin/logs/exports', async ({ request }) => {
    const no = denied(request, 'ADMIN')
    if (no) return no
    const body = (await request.json()) as { request_id?: string }
    if (!body.request_id) return fail(400, 'request_id가 필요합니다.')
    await delay(500)
    const header = '발생시각(KST),request_id,질문(마스킹),의도,상태,피드백,출처 수,응답시간(초),처리 상태'
    const lines = rows.map((r) =>
      [r.occurred_at, r.request_id, r.question_masked, r.intent ?? '', r.status, r.feedback ?? '',
       r.source_count ?? '', r.latency_s ?? '', r.triage]
        .map((v) => `"${String(v).replaceAll('"', '""')}"`)
        .join(','))
    return csvFile(`conversation-log-${nextId('exp')}.csv`, [header, ...lines], rows.length)
  }),
]
