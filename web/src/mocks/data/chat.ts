/** 챗봇 목 시나리오 — CB-DF-001 답변 Type 6종을 개발 중에 전부 볼 수 있게 만든 고정 응답.
 *
 * 출처·서류 링크는 전부 실제 코퍼스(data/corpus.jsonl) 값이다. 지어낸 URL은 하나도 없다.
 * 답변 본문도 실제 청크(data/chunks_all.jsonl) 내용을 요약한 것이라 숫자가 실제와 맞다.
 *
 * ⚠ 자기보고 마커([SOURCE_USED]/[NO_SOURCE])는 answer에 넣지 않는다 — BE가 스트리밍 전에
 *   떼는 것이 계약이다(CB-DF-004 §7 I-12). 목도 같은 전제로 만든다. */
import type { BusinessFunction, Intent, ResponseType } from '../../lib/codes'
import type {
  ApiError,
  Attachment,
  Clarification,
  Source,
  SubAnswer,
  Suggestion,
} from '../../lib/api/types'
import { MOCK_SUGGESTED_QUESTIONS } from './admin'
import { MOCK_PAGES } from './pages'

/** page_id로 실제 코퍼스 페이지를 찾아 Source(= citation.format_citation()의 반환 형태)로 바꾼다. */
export function sourceOf(pageId: string): Source {
  const p = MOCK_PAGES.find((x) => x.page_id === pageId)
  if (!p) throw new Error(`mock: unknown page_id ${pageId}`)
  return { page_id: p.page_id, breadcrumb: p.sub_category, title: p.page_title, url: p.source_url }
}

/** 시나리오 1건. request_id·session_id·latency_ms는 핸들러가 채운다. */
export interface ChatScenario {
  id: string
  /** 질문에 이 말 중 하나가 들어 있으면 이 시나리오. 배열 위에서부터 첫 일치가 이긴다 */
  triggers: string[]
  answer: string
  sources: Source[]
  attachments: Attachment[]
  /** 복합 질문일 때만. 있으면 위 sources·attachments는 비운다 */
  sub_answers?: SubAnswer[]
  out_of_scope: boolean
  response_type: ResponseType
  intent?: Intent
  business_function?: BusinessFunction
  clarification?: Clarification
  /** request_id는 핸들러가 붙인다 */
  error?: Omit<ApiError, 'request_id'>
  /** 200이 아닌 HTTP 상태로 끊어야 하는 시나리오(429 등) */
  http_status?: number
}

/** 서식 다운로드 페이지 링크 — civil_petition.build_document_section()의 평탄화 결과와 같은 모양.
 * 서식 직링크(resolved_url)는 POST 전용 서블릿이라 못 쓴다 → 다운로드 버튼이 있는 페이지로 안내. */
const senderFormLinks: Attachment[] = MOCK_PAGES.find((p) => p.page_id === 'sender_docs')!
  .form_links.slice(0, 2)
  .map((f) => ({ label: f.label, url: f.url, kind: 'document' as const }))

export const MOCK_SCENARIOS: ChatScenario[] = [
  // --- Type 4. 오류 응답 (429는 SSE를 열지 않고 HTTP로 끊는다) ---
  {
    id: 'rate_limit',
    triggers: ['429', '과부하'],
    answer: '',
    sources: [],
    attachments: [],
    out_of_scope: false,
    response_type: 'ERROR',
    http_status: 429,
    error: {
      code: 'LLM_RATE_LIMIT',
      // 대기 안내만 하고 자동 재호출은 하지 않는다(PRD-02 §3-b) → retryable=false
      user_message: '요청이 많아 잠시 후 다시 시도해 주세요. (약 600초)',
      retryable: false,
      fallback_sources: [],
    },
  },
  {
    id: 'error_fallback',
    triggers: ['오류', '에러'],
    answer: '',
    sources: [],
    attachments: [],
    out_of_scope: false,
    // 검색 성공 + 생성 실패 = 부분 실패 → FALLBACK (CB-DF-002 하단 주석)
    response_type: 'FALLBACK',
    error: {
      code: 'LLM_TIMEOUT',
      user_message: '답변을 만드는 데 시간이 너무 오래 걸렸습니다. 다시 시도해 주세요.',
      retryable: true,
      fallback_sources: [sourceOf('dp_protlmts'), sourceOf('dp_faq_page')],
    },
  },
  {
    // 검색까지 실패해 붙일 출처가 없는 오류. 재시도는 되지만 2회 소진하면 공식 문의로 전환된다(CB-004 Case 5).
    // fallback_sources가 비어야 Case 5로 넘어간다 — error_fallback은 출처가 있어 Case 4에서 멈춘다.
    id: 'error_no_source',
    triggers: ['검색 실패', '타임아웃'],
    answer: '',
    sources: [],
    attachments: [],
    out_of_scope: false,
    response_type: 'ERROR',
    error: {
      // ERROR_HAS_FALLBACK가 false인 코드 — 붙일 출처가 없다는 뜻이 코드에 이미 들어 있다
      code: 'RETRIEVAL_ERROR',
      user_message: '자료를 찾는 데 시간이 너무 오래 걸렸습니다. 다시 시도해 주세요.',
      retryable: true,
      fallback_sources: [],
    },
  },

  // --- Type 5. 업무 확인 되묻기 (2026-08-24 구현분, src/clarify.py) ---
  // 아래 '역할 확인 되묻기'와 같은 clarification 스키마를 쓰지만 축이 다르다.
  // ⚠️ business_function 을 주지 않는다 — 업무를 몰라서 되묻는 턴이라 서버도 못 준다.
  //    프론트는 이 값이 있을 때만 역할 칩을 남기므로(ChatPage.selectRole), 여기서 값을 주면
  //    「입장 · 미수령금 찾기」 같은 어색한 고정이 생긴다.
  // answer 에 되묻기 문구를 넣는 것도 서버와 같다 — 화면은 버리지만 대화 복원·로그가 읽는다.
  {
    id: 'clarification_business',
    // 업무가 특정되지 않은 신청·링크성 질문. '신청'만 든 질문은 아래 민원 시나리오가 가져간다
    triggers: ['링크'],
    answer: '어떤 업무를 찾고 계신가요? 아래에서 골라주시면 바로 안내해 드릴게요.',
    sources: [],
    attachments: [],
    out_of_scope: false,
    response_type: 'CLARIFICATION',
    clarification: {
      question: '어떤 업무를 찾고 계신가요? 아래에서 골라주시면 바로 안내해 드릴게요.',
      // src/clarify.py CLARIFY_OPTIONS 와 같은 5개. value 없이 label 만 보낸다(클릭 = 업무명 전송)
      options: [
        { label: '착오송금 반환지원' },
        { label: '예금보험금·가지급금' },
        { label: '미수령금 찾기' },
        { label: '은닉재산 신고' },
        { label: '채무조정' },
      ],
    },
  },

  // --- Type 5. 역할 확인 되묻기 ---
  // ⚠️ 기획서(CB-005) 설계이나 백엔드 판정은 아직 없다 — 발동 조건 required_role 이 코퍼스에
  //    없어서다(2026-08-24 팀 결정: 설계는 남기고 미구현으로 명기). 이 목만 단독으로 존재한다.
  {
    id: 'clarification',
    // 역할이 답을 가르는 주제(수수료·반환)인데 역할 단서가 없을 때만 발동한다
    triggers: ['수수료'],
    answer: '',
    sources: [],
    attachments: [],
    out_of_scope: false,
    response_type: 'CLARIFICATION',
    intent: 'civil_petition',
    business_function: '착오송금 반환 신청',
    // 선택지는 서버가 준다(B-01) — 프론트 상수로 두면 다른 역할축에서 버튼이 그대로 남는다
    clarification: {
      question: '어느 입장에서 궁금하신가요?',
      options: [{ label: '잘못 보낸 사람(송금인)', value: 'sender' }, { label: '잘못 받은 사람(수취인)', value: 'receiver' }],
    },
  },

  // --- Type 3. 범위 외 (인사·정체성·범위 외 질문 — 프론트에서 셋이 구분되지 않는다) ---
  {
    id: 'out_of_scope_identity',
    triggers: ['누구', '이름이', '모델'],
    answer:
      '저는 예금보험공사의 AI 상담 챗봇 예솜24입니다. 예금자보호제도, 예금보험금, 착오송금 반환지원 등 예금보험공사 업무에 대해 안내해 드릴 수 있습니다.',
    sources: [],
    attachments: [],
    out_of_scope: true,
    response_type: 'ANSWER',
    intent: 'informational',
  },
  {
    id: 'out_of_scope_greeting',
    triggers: ['안녕', '고마워', '반가'],
    answer: '안녕하세요! 예금보험공사와 관련해 궁금하신 점이 있으시면 편하게 물어봐 주세요.',
    sources: [],
    attachments: [],
    out_of_scope: true,
    response_type: 'ANSWER',
    intent: 'informational',
  },
  {
    id: 'out_of_scope_other',
    triggers: ['대출', '금리', '주식', '보이스피싱 신고'],
    answer:
      '문의하신 내용은 예금보험공사에서 안내해 드리기 어려운 범위입니다. 금융 상품·거래 관련 문의는 금융감독원으로 문의해 주시기 바랍니다.',
    sources: [],
    attachments: [],
    out_of_scope: true,
    response_type: 'ANSWER',
    intent: 'informational',
  },

  // 자주 묻는 질문 3번 — 이 시나리오가 없으면 어느 트리거에도 안 걸려 기본값(예금자보호 한도)으로
  // 답한다. 묻는 건 '착오송금 반환지원 대상 금액'인데 '예금자보호 1억원'이 나가던 상태였다.
  // 금액은 corpus.jsonl의 faq_msdr_apply 원문 그대로다(건당 5만원 이상~1억원 이하).
  // 금액만 답하면 안 된다 — 1년 기한을 함께 충족해야 하는 **조건부 금액**이라
  // 조건을 빼면 근거는 맞는데 결론이 틀린 답이 된다(3제약 2 · 민원 리스크).
  {
    id: 'refund_amount_limit',
    triggers: ['대상 금액', '얼마까지', '금액 기준'],
    answer:
      '착오송금 반환지원 대상 금액은 착오송금 건당 5만원 이상 1억원 이하입니다.\n\n금액 조건을 충족하더라도 송금일로부터 1년 이내에 신청한 건에 한해 지원됩니다. 두 조건을 모두 만족해야 하므로, 신청 대상에 해당하는지는 자가진단에서 미리 확인해 보실 수 있습니다.',
    sources: [sourceOf('faq_msdr_apply'), sourceOf('sender_qlfc_check')],
    attachments: [],
    out_of_scope: false,
    response_type: 'ANSWER',
    intent: 'informational',
    business_function: '착오송금 반환 신청',
  },

  // --- Type 2. 민원처리 답변 (절차 → 필요 서류 → 신청 페이지) ---
  {
    id: 'civil_petition_with_docs',
    triggers: ['잘못 보낸 사람', '송금인', '신청', '서류', '절차', '방법'],
    answer:
      '착오송금 반환지원은 온라인과 방문 두 가지 방법으로 신청할 수 있습니다.\n\n1. 온라인 신청: PC에서 공동인증서와 이체(송금)확인증을 준비해 신청합니다.\n2. 방문 신청: 서울시 중구 청계천로 30 1층으로 신분증과 이체(송금)확인증을 지참해 방문합니다.\n\n지원 대상 금액은 착오송금 건당 5만원 이상 1억원 이하이며, 송금일로부터 1년 이내에 신청한 건에 한해 지원됩니다.',
    sources: [sourceOf('faq_msdr_apply')],
    attachments: [
      ...senderFormLinks,
      // '신청 페이지' 섹션 = civil_petition.build_link_section() 결과 (kind: 'link')
      { label: '착오송금 반환지원 신청방법', url: sourceOf('kmrs_apply_mthd').url, kind: 'link' },
    ],
    out_of_scope: false,
    response_type: 'ANSWER',
    intent: 'civil_petition',
    business_function: '착오송금 반환 신청',
  },
  // 첨부·서식이 없는 민원 — '필요 서류' 섹션이 통째로 미노출되는지 확인용(CB-DF-003 4-2 4행)
  {
    id: 'civil_petition_no_docs',
    triggers: ['잘못 받은 사람', '수취인', '미수령금'],
    answer:
      '고객 미수령금은 예금보험공사 통합신청 창구에서 조회하고 신청할 수 있습니다. 본인 명의 계좌와 신분증을 준비해 주시고, 조회 결과 미수령금이 확인되면 해당 창구에서 바로 지급 신청을 진행하시면 됩니다.',
    sources: [],
    attachments: [
      { label: '미수령금 통합신청', url: sourceOf('uc_itgr_aply').url, kind: 'link' },
    ],
    out_of_scope: false,
    response_type: 'ANSWER',
    intent: 'civil_petition',
    business_function: '고객 미수령금 신청',
  },

  // --- Type 6. 복합 질문 분해 (하위 질문 제목 + 답변. 하위 간 출처 중복 제거 금지) ---
  {
    id: 'composite',
    triggers: ['그리고', '와 필요', '기간은'],
    // 스트리밍으로 흘러가는 본문. 하위 답변을 이어붙인 것과 같다(sse.py 불변식:
    // answer_delta를 이어붙인 것 == done.answer). done에서 sub_answers로 대체돼 그려진다
    answer:
      '착오송금 반환지원 신청 방법은?\n온라인과 방문(서울시 중구 청계천로 30 1층) 두 가지로 신청할 수 있습니다.\n\n필요한 서류는?\n온라인은 공동인증서와 이체(송금)확인증, 방문은 신분증과 이체(송금)확인증이 필요합니다.\n\n처리 기간은 얼마나 걸리나요?\n자진반환 및 지급명령을 통한 회수 절차에 따라 소요 기간이 달라집니다.',
    // 🔴 sub_answers가 있으면 최상위 sources·attachments는 빈 배열이다 (백엔드 확정 2026-08-05)
    sources: [],
    attachments: [],
    // 하위 답변마다 독립 부착 — 같은 페이지가 두 번 나와도 중복 제거하지 않는다(pipeline.py _answer_one 주석)
    sub_answers: [
      {
        title: '착오송금 반환지원 신청 방법은?',
        answer: '온라인과 방문(서울시 중구 청계천로 30 1층) 두 가지로 신청할 수 있습니다.',
        sources: [sourceOf('kmrs_apply_mthd')],
        attachments: [],
      },
      {
        title: '필요한 서류는?',
        answer: '온라인은 공동인증서와 이체(송금)확인증, 방문은 신분증과 이체(송금)확인증이 필요합니다.',
        // 같은 페이지가 위 하위와 겹쳐도 지우지 않는다 — 하위별 근거가 독립이라는 뜻이다
        sources: [sourceOf('sender_docs')],
        attachments: senderFormLinks,
      },
      {
        title: '처리 기간은 얼마나 걸리나요?',
        answer: '자진반환 및 지급명령을 통한 회수 절차에 따라 소요 기간이 달라집니다.',
        sources: [sourceOf('faq_msdr_apply')],
        attachments: [],
      },
    ],
    out_of_scope: false,
    response_type: 'ANSWER',
    intent: 'informational',
    business_function: '착오송금 반환 신청',
  },

  // --- Type 1. 정보성 답변 (기본값 — 어느 트리거에도 안 걸리면 이것) ---
  {
    id: 'informational',
    triggers: [],
    answer:
      '예금자보호제도는 원금과 소정의 이자를 합하여 금융회사별로 1인당 1억원까지 보호합니다. 1억원을 넘는 금액은 보호되지 않습니다.\n\n확정기여형퇴직연금(DC형), 개인형퇴직연금(IRP), 연금저축, 사고보험금은 일반 예금과 분리해 각각 1인당 1억원까지 별도로 보호됩니다.',
    sources: [sourceOf('dp_protlmts'), sourceOf('dp_syst'), sourceOf('dp_faq_page')],
    attachments: [],
    out_of_scope: false,
    response_type: 'ANSWER',
    intent: 'informational',
    business_function: '예금자보호제도',
  },
]

/** GET /api/suggestions — CB-001 자주 묻는 질문.
 * 목록의 원천은 관리자 쪽(data/admin.ts MOCK_SUGGESTED_QUESTIONS) 하나다. 여기서 또 정의하면
 * 두 화면이 서로 다른 질문을 보여주게 된다. 활성만 골라 노출 순서대로 준다(활성 최대 10). */
export const activeSuggestions = (): Suggestion[] =>
  MOCK_SUGGESTED_QUESTIONS.filter((q) => q.active)
    .sort((a, b) => a.order - b.order)
    .map((q) => ({ id: q.id, text: q.text, business_function: q.business_function }))
