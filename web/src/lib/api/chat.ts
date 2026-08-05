/** 챗봇 SSE 클라이언트.
 *
 * EventSource는 POST를 못 하므로 fetch + ReadableStream으로 SSE를 직접 파싱한다.
 * 규칙(PRD-02 §2·§3-b·§3-c):
 *  - [중단] = 클라이언트 abort (서버 취소 API 없음)
 *  - 델타 수신 간격 30초 무응답 → '완료 후 일괄 표시'로 폴백(델타 페인팅만 중단, done은 계속 기다림)
 *  - 429는 대기 안내만. 자동 재호출 금지
 */
import { CHAT_IDLE_TIMEOUT_MS } from '../constants'
import type { ApiError, ChatRequest, ChatResponse, ChatStreamEvent, Source } from './types'

export const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export interface ChatStreamHandlers {
  onAccepted?(d: { request_id: string; session_id: string }): void
  onDelta?(text: string): void
  onSources?(sources: Source[]): void
  onAttachments?(a: ChatResponse['attachments']): void
  onDone?(res: ChatResponse): void
  onError?(err: ApiError): void
  /** 델타가 30초간 없어 일괄 표시로 전환됨 — 화면은 '답변 생성 중'만 유지한다 */
  onFallback?(): void
}

/** SSE 프레임(`event:` + `data:`, 빈 줄로 구분)을 파싱해 이벤트 단위로 흘려보낸다. */
function* parseFrames(buffer: string): Generator<ChatStreamEvent> {
  for (const frame of buffer.split('\n\n')) {
    let name = 'message'
    const dataLines: string[] = []
    for (const line of frame.split('\n')) {
      if (line.startsWith('event:')) name = line.slice(6).trim()
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
    }
    if (!dataLines.length) continue
    try {
      yield { event: name, data: JSON.parse(dataLines.join('\n')) } as ChatStreamEvent
    } catch {
      // 잘린 프레임 — 다음 청크에서 이어 받는다
    }
  }
}

/** 서버에 도달조차 못 한 경우에만 쓰는 프론트 고정 문구.
 * 원칙은 "오류 문구는 서버 user_message" 이지만 서버가 없으면 문구도 없다(기획서 예외 등록 대상). */
const NETWORK_ERROR: ApiError = {
  code: 'INTERNAL',
  user_message: '네트워크에 연결할 수 없습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.',
  retryable: true,
  fallback_sources: [],
  request_id: '',
}

export async function streamChat(
  req: ChatRequest,
  handlers: ChatStreamHandlers,
  signal: AbortSignal,
): Promise<void> {
  let idleTimer: ReturnType<typeof setTimeout> | undefined
  let painting = true // false = 일괄 표시 모드

  const resetIdle = () => {
    clearTimeout(idleTimer)
    idleTimer = setTimeout(() => {
      painting = false
      handlers.onFallback?.()
    }, CHAT_IDLE_TIMEOUT_MS)
  }

  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(req),
      credentials: 'include',
      signal,
    })

    if (res.status === 429) {
      const retryAfter = Number(res.headers.get('Retry-After') ?? 0)
      const body = (await res.json().catch(() => null)) as ApiError | null
      handlers.onError?.(
        body ?? {
          ...NETWORK_ERROR,
          code: 'LLM_RATE_LIMIT',
          user_message: `요청이 많아 잠시 후 다시 시도해 주세요.${retryAfter ? ` (약 ${retryAfter}초)` : ''}`,
          retryable: false, // 자동 재호출 금지 — 사용자가 직접 다시 보낸다
        },
      )
      return
    }
    if (!res.ok || !res.body) {
      const body = (await res.json().catch(() => null)) as ApiError | null
      handlers.onError?.(body ?? NETWORK_ERROR)
      return
    }

    resetIdle()
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
    let buffer = ''

    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += value
      // 마지막 조각은 프레임이 덜 왔을 수 있으니 남겨둔다
      const cut = buffer.lastIndexOf('\n\n')
      if (cut === -1) continue
      const complete = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)

      for (const ev of parseFrames(complete)) {
        resetIdle()
        switch (ev.event) {
          case 'accepted':
            handlers.onAccepted?.(ev.data)
            break
          case 'answer_delta':
            if (painting) handlers.onDelta?.(ev.data.text)
            break
          case 'sources':
            handlers.onSources?.(ev.data.sources)
            break
          case 'attachments':
            handlers.onAttachments?.(ev.data.attachments)
            break
          case 'done':
            handlers.onDone?.(ev.data)
            break
          case 'error':
            handlers.onError?.(ev.data)
            break
        }
      }
    }
  } catch (e) {
    if (signal.aborted) return // [중단] — 오류가 아니다
    handlers.onError?.(NETWORK_ERROR)
  } finally {
    clearTimeout(idleTimer)
  }
}
