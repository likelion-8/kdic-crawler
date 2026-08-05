/** 사용자 API 목 — CM-DF-003 03절.
 *
 * SSE를 흉내만 내지 않고 실제 ReadableStream으로 흘린다. lib/api/chat.ts의 프레임 파서·
 * 30초 유휴 폴백·abort 처리가 목만으로 검증되도록 하기 위해서다.
 *
 * ── 시나리오 트리거 표 (질문에 아래 말이 들어가면 그 시나리오. 위에서부터 첫 일치) ──
 *
 * | 질문에 포함 | 시나리오 | 화면에서 보이는 것 |
 * |---|---|---|
 * | `429` · `과부하` | 429 응답 | HTTP 429 + Retry-After, [다시 시도] 없음 |
 * | `오류` · `에러` | 부분 실패(FALLBACK) | error.user_message + 폴백 출처 2건 + [다시 시도] |
 * | `수수료` | 역할 되묻기(CB-005) | 되묻기 문구 + 역할 버튼. 출처·서류 없음 |
 * | `누구` · `이름이` · `모델` | 범위 외(정체성) | 본문만. out_of_scope=true |
 * | `안녕` · `고마워` · `반가` | 범위 외(인사·잡담) | 본문만 |
 * | `대출` · `금리` · `주식` | 범위 외(범위 밖 질문) | 본문만 |
 * | `잘못 보낸 사람` · `송금인` · `신청` · `서류` · `절차` · `방법` | 민원처리(첨부 있음) | 절차 → 필요 서류 2건 → 신청 페이지 |
 * | `잘못 받은 사람` · `수취인` · `미수령금` | 민원처리(첨부 없음) | 절차 → 신청 페이지 ('필요 서류' 섹션 통째 미노출) |
 * | `그리고` · `와 필요` · `기간은` | 복합 질문 분해 | 하위 3개 + 출처 3건(중복 제거 안 함) |
 * | (그 외 전부) | 정보성 답변 | 본문 + 참고 출처 3건 |
 *
 * 그 밖의 개발용 스위치
 * - `GET /api/health?state=maintenance` → 점검 전면 안내(CB-004 Case 6)
 * - `GET /api/health?state=degraded` → 일부 기능 비활성
 * - 질문에 `느리게` 를 넣으면 델타 간격이 5초로 늘어난다 → 30초 유휴 폴백·[중단] 개발용
 */
import { HttpResponse, delay, http } from 'msw'
import type { ChatRequest, ChatResponse, FeedbackPatch, FeedbackRequest, HealthResponse } from '../../lib/api/types'
import { FEEDBACK_FREETEXT_MAX } from '../../lib/constants'
import { MOCK_SCENARIOS, activeSuggestions, sourceOf } from '../data/chat'
import type { ChatScenario } from '../data/chat'

/** 델타 1개 크기(글자). CB-DF-000 ④ "글자 단위 실시간 출력".
 * 실제 LLM 토큰은 한글 기준 1~3자라 그 크기에 맞춘다 — 8자씩 뿜으면 화면이 뚝뚝 끊겨 보인다.
 * (화면 쪽에도 스무딩이 있어(useTypewriter) 서버가 거칠게 끊어도 흐르긴 하지만,
 *  목이 실제 서버와 비슷하게 굴어야 개발 중에 진짜 체감을 확인할 수 있다.) */
const DELTA_CHARS = 2
const DELTA_MIN_MS = 18
const DELTA_MAX_MS = 34
/** '느리게' 질문일 때의 델타 간격 — CHAT_IDLE_TIMEOUT_MS(30초) 폴백을 눈으로 확인하려고 둔다 */
const SLOW_DELTA_MS = 5_000

let seq = 0
const nextId = (prefix: string) => `${prefix}_${Date.now().toString(36)}_${(seq += 1)}`

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

function pickScenario(message: string): ChatScenario {
  const found = MOCK_SCENARIOS.find((s) => s.triggers.some((t) => message.includes(t)))
  // triggers가 빈 시나리오(정보성)가 기본값이다
  return found ?? MOCK_SCENARIOS[MOCK_SCENARIOS.length - 1]
}

function chunkText(text: string): string[] {
  const out: string[] = []
  for (let i = 0; i < text.length; i += DELTA_CHARS) out.push(text.slice(i, i + DELTA_CHARS))
  return out
}

/** SSE 본문 스트림. lib/api/chat.ts의 parseFrames가 기대하는 `event:` + `data:` + 빈 줄 형식. */
function sseStream(scenario: ChatScenario, sessionId: string, slow: boolean): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  const requestId = nextId('req')
  const startedAt = Date.now()

  return new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (event: string, data: unknown) => {
        controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`))
      }

      send('accepted', { request_id: requestId, session_id: sessionId })
      await sleep(120)

      // Type 4 오류 — 답변 본문이 없는 유일한 Type. error 이벤트로 끝낸다
      if (scenario.error) {
        await sleep(400)
        send('error', { ...scenario.error, request_id: requestId })
        controller.close()
        return
      }

      // Type 5 되묻기 — 검색 전에 되묻으므로 answer_delta·sources가 없다
      if (!scenario.clarification) {
        for (const piece of chunkText(scenario.answer)) {
          await sleep(slow ? SLOW_DELTA_MS : DELTA_MIN_MS + Math.random() * (DELTA_MAX_MS - DELTA_MIN_MS))
          send('answer_delta', { text: piece })
        }
        // 빈 배열이면 이벤트 자체를 보내지 않는다 — 어차피 섹션째 미렌더가 규칙이다(CB-DF-003 4-2).
        // 특히 out_of_scope=true인데 sources를 흘리면 프론트가 출처를 그렸다 지우는 깜빡임이 생긴다
        if (scenario.sources.length) send('sources', { sources: scenario.sources })
        if (scenario.attachments.length) send('attachments', { attachments: scenario.attachments })
      }

      const done: ChatResponse = {
        answer: scenario.answer,
        sources: scenario.sources,
        attachments: scenario.attachments,
        out_of_scope: scenario.out_of_scope,
        session_id: sessionId,
        request_id: requestId,
        latency_ms: Date.now() - startedAt,
        response_type: scenario.response_type,
        clarification: scenario.clarification,
        intent: scenario.intent,
        business_function: scenario.business_function,
      }
      send('done', done)
      controller.close()
    },
  })
}

/** GET /api/sessions/{session_id} 응답. types.ts에 없어 목이 정의했다(기획서 역기재 대상).
 *  PRD-02 §1은 이 기능을 `GET /api/conversation`이라 부르는데 CM-DF-003 04절 경로와 다르다. */
export interface RestoredMessage {
  role: 'user' | 'assistant'
  text: string
  request_id?: string
  /** 이 메시지의 시각(ISO8601 · KST). 말풍선에 `오후 3:24`로 찍는다.
   *  ⚠ 백엔드도 함께 내려야 한다 — 없으면 화면이 시각을 아예 그리지 않는다.
   *  복원된 대화에 '지금' 시각을 찍으면 90분 전 대화에 방금 시각이 붙어 거짓이 되기 때문이다 */
  at?: string
  /** 답변 말풍선 복원용. 사용자 메시지는 비어 있다 */
  response?: Pick<ChatResponse, 'sources' | 'attachments' | 'out_of_scope'>
}
export interface RestoredSession {
  session_id: string
  /** ISO8601 · KST. 이 시각이 24시간(CONVERSATION_RESTORE_WINDOW_H)보다 오래되면 서버가 404를 준다 */
  last_activity_at: string
  messages: RestoredMessage[]
}

export const chatHandlers = [
  http.post('/api/chat', async ({ request }) => {
    const body = (await request.json()) as ChatRequest
    const message = body.message ?? ''
    const sessionId = body.session_id ?? nextId('sess')
    const scenario = pickScenario(message)

    if (scenario.http_status === 429) {
      // 임시 차단 10분(RATE_BLOCK_MIN). 자동 재호출 금지라 retryable=false로 내려간다
      return HttpResponse.json(
        { ...scenario.error, request_id: nextId('req') },
        { status: 429, headers: { 'Retry-After': '600' } },
      )
    }

    return new HttpResponse(sseStream(scenario, sessionId, message.includes('느리게')), {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      },
    })
  }),

  // 등록·수정 upsert. 답변당 최종 1건 (PRD-02 §1)
  http.post('/api/feedback', async ({ request }) => {
    const body = (await request.json()) as FeedbackRequest
    if (!body.answer_request_id || !body.session_id || (body.vote !== 'up' && body.vote !== 'down')) {
      return HttpResponse.json(
        { code: 'INTERNAL', user_message: '요청 형식이 올바르지 않습니다.', retryable: false, fallback_sources: [], request_id: nextId('req') },
        { status: 400 },
      )
    }
    await delay(150)
    return HttpResponse.json({ feedback_id: nextId('fb') })
  }),

  // 사유 보완 — 자유 의견은 마스킹 후 저장 · 최대 200자
  http.patch('/api/feedback/:feedbackId', async ({ params, request }) => {
    const body = (await request.json()) as FeedbackPatch
    if (!body.reason_codes?.length) {
      return HttpResponse.json(
        { code: 'INTERNAL', user_message: '사유를 하나 이상 선택해 주세요.', retryable: false, fallback_sources: [], request_id: nextId('req') },
        { status: 400 },
      )
    }
    if ((body.comment?.length ?? 0) > FEEDBACK_FREETEXT_MAX) {
      return HttpResponse.json(
        { code: 'INTERNAL', user_message: `의견은 ${FEEDBACK_FREETEXT_MAX}자까지 입력할 수 있습니다.`, retryable: false, fallback_sources: [], request_id: nextId('req') },
        { status: 400 },
      )
    }
    await delay(150)
    return HttpResponse.json({ feedback_id: String(params.feedbackId) })
  }),

  // 대화 복원 — 마지막 활동 24시간 이내 (CONVERSATION_RESTORE_WINDOW_H)
  http.get('/api/sessions/:sessionId', ({ params }) => {
    const body: RestoredSession = {
      session_id: String(params.sessionId),
      last_activity_at: new Date(Date.now() - 90 * 60_000).toISOString(),
      messages: [
        { role: 'user', text: '예금자보호 한도가 얼마인가요?', at: new Date(Date.now() - 92 * 60_000).toISOString() },
        {
          role: 'assistant',
          text: '예금자보호제도는 원금과 소정의 이자를 합하여 금융회사별로 1인당 1억원까지 보호합니다.',
          request_id: 'req_restored_1',
          at: new Date(Date.now() - 90 * 60_000).toISOString(),
          response: { sources: [sourceOf('dp_protlmts')], attachments: [], out_of_scope: false },
        },
      ],
    }
    return HttpResponse.json(body)
  }),

  // 점검·기능 비활성 전면 안내(CB-004 Case 6). 문구는 서버가 준다 — FE가 만들지 않는다
  http.get('/api/health', ({ request }) => {
    const state = new URL(request.url).searchParams.get('state')
    if (state === 'maintenance') {
      const body: HealthResponse = {
        status: 'maintenance',
        maintenance: true,
        disabled_features: ['chat'],
        user_message:
          '답변 기능을 잠시 쉬어가고 있어요. 예금보험공사 공식 누리집(kdic.or.kr)에서 필요한 정보를 확인하실 수 있습니다.',
      }
      return HttpResponse.json(body)
    }
    if (state === 'degraded') {
      const body: HealthResponse = { status: 'degraded', maintenance: false, disabled_features: ['feedback'] }
      return HttpResponse.json(body)
    }
    const body: HealthResponse = { status: 'ok', maintenance: false, disabled_features: [] }
    return HttpResponse.json(body)
  }),

  http.get('/api/suggestions', () => HttpResponse.json(activeSuggestions())),
]
