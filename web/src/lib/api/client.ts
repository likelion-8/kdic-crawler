/** REST 클라이언트 (관리자 API + 챗봇 비스트리밍 API 공통).
 * 챗봇 SSE는 성격이 달라 chat.ts가 따로 다룬다.
 *
 * 확정 규칙 (PRD-02 §3):
 *  - 오류 문구는 서버 `user_message` 그대로. FE가 만들지 않는다(서버 미도달 시만 예외).
 *  - 429/403은 자동 재호출·재시도 금지. 재시도 정책은 queryClient.ts.
 *  - 403은 화면에서 버튼을 숨겼어도 온다. 항상 처리한다(§3-d).
 *  - 쓰기 요청에는 request_id를 붙이고, 위험 작업은 변경 사유(reason)를 함께 보낸다(§3-e).
 *  - 폴링은 유휴 세션 타이머를 갱신하면 안 된다(PRD-01 §3). isPoll로 구분한다. */
import { API_BASE } from './chat'
import type { ApiError } from './types'
import { expireSession, touchIdle } from '../../app/session'

/** 관리자 API 접두어. 이 경로의 성공 응답만 유휴 타이머를 갱신한다 */
const ADMIN_PREFIX = '/api/admin'

/** 폴링 표시 헤더. 서버는 이 요청을 유휴 타이머 갱신에서 제외한다.
 * 기획서에 수단이 없어(PRD-02 MED-06) 그 절의 제안 중 헤더 방식을 택했다. */
const POLL_HEADER = 'X-Poll'

/** 서버에 도달조차 못 한 경우에만 쓰는 프론트 고정 문구.
 * chat.ts의 NETWORK_ERROR와 같은 문구다 — 기획서 LOW-05 예외 문구가 한 곳에 등록되면 그리로 합친다. */
const NETWORK_MESSAGE = '네트워크에 연결할 수 없습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.'

/** 서버가 계약(ApiError)대로 응답하지 못했을 때만 쓰는 상태코드별 대체 문구.
 * 원칙은 '문구는 서버가 준다'이므로 여기 추가할 일이 생기면 백엔드 계약을 먼저 고친다. */
const STATUS_MESSAGE: Record<number, string> = {
  401: '세션이 만료되었습니다. 다시 로그인해 주세요.',
  403: '이 작업을 수행할 권한이 없습니다.',
  429: '요청이 많아 잠시 후 다시 시도해 주세요.',
}

/** 정규화된 오류. `error.user_message`를 그대로 노출하고 `retryable`일 때만 [다시 시도]를 그린다. */
export class ApiRequestError extends Error {
  /** HTTP 상태. 네트워크 미도달은 0 */
  readonly status: number
  readonly error: ApiError

  constructor(status: number, error: ApiError) {
    super(error.user_message)
    this.name = 'ApiRequestError'
    this.status = status
    this.error = error
  }
}

export function isApiRequestError(e: unknown): e is ApiRequestError {
  return e instanceof ApiRequestError
}

export interface ApiRequestInit {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  /** JSON 직렬화해 보낼 본문 */
  body?: unknown
  /** 진행 상태·헬스 폴링. 유휴 타이머를 갱신하지 않는다 (PRD-01 §3) */
  isPoll?: boolean
  /** 위험 작업 변경 사유 — 확인 모달에서 받은 값 (CM-DF-004 03절, 쓰기 요청 전용) */
  reason?: string
  signal?: AbortSignal
}

export async function apiRequest<T>(path: string, init: ApiRequestInit = {}): Promise<T> {
  const { method = 'GET', body, isPoll = false, reason, signal } = init
  const isWrite = method !== 'GET'

  const headers: Record<string, string> = { Accept: 'application/json' }
  if (isPoll) headers[POLL_HEADER] = '1'

  let payload = body
  if (isWrite) {
    // 쓰기 요청은 request_id(멱등키)를 FE가 만들어 본문에 넣는다. 없으면 서버가 400을 준다.
    // 단 호출자가 이미 request_id를 넣었으면 그대로 둔다 — 피드백처럼 "어느 답변에 대한
    // 요청인가"를 request_id로 지목하는 호출이 있어서, 무조건 새로 만들면 그 값이 덮인다.
    // 변경 사유(reason)는 위험 작업 확인 모달에서 받은 값이다 (CM-DF-004 03절)
    const given = typeof body === 'object' && body !== null ? (body as Record<string, unknown>) : {}
    payload = {
      ...given,
      request_id: typeof given.request_id === 'string' ? given.request_id : crypto.randomUUID(),
      ...(reason === undefined ? {} : { reason }),
    }
  }
  if (payload !== undefined) headers['Content-Type'] = 'application/json'

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      signal,
      // 세션은 httpOnly 쿠키 전제 (PRD-02 MED-05 — 계약 미확정 항목, 쿠키 방식으로 진행)
      credentials: 'include',
      body: payload === undefined ? undefined : JSON.stringify(payload),
    })
  } catch (e) {
    if (signal?.aborted) throw e // 사용자가 취소한 요청은 오류가 아니다
    throw new ApiRequestError(0, {
      code: 'INTERNAL',
      user_message: NETWORK_MESSAGE,
      retryable: true,
      fallback_sources: [],
      request_id: '',
    })
  }

  if (!res.ok) {
    // 401 = 세션 만료. 화면 어디서 났든 세션 상태를 끊어 로그인으로 보낸다(RequireAuth가 처리)
    if (res.status === 401) expireSession()
    throw new ApiRequestError(res.status, await toApiError(res))
  }

  // 인증된 관리자 API 호출 성공 = 활동. 폴링은 제외한다 (PRD-01 §3)
  if (!isPoll && path.startsWith(ADMIN_PREFIX)) touchIdle()

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

async function toApiError(res: Response): Promise<ApiError> {
  const body = (await res.json().catch(() => null)) as Partial<ApiError> | null
  if (body && typeof body.user_message === 'string') {
    return {
      code: body.code ?? 'INTERNAL',
      user_message: body.user_message,
      // 429는 서버가 뭐라 하든 자동 재호출하지 않는다 (PRD-02 §3-b)
      retryable: res.status === 429 ? false : body.retryable === true,
      fallback_sources: body.fallback_sources ?? [],
      request_id: body.request_id ?? '',
    }
  }
  const retryAfter = Number(res.headers.get('Retry-After') ?? 0)
  const suffix = res.status === 429 && retryAfter ? ` (약 ${retryAfter}초)` : ''
  return {
    code: 'INTERNAL',
    user_message: (STATUS_MESSAGE[res.status] ?? '처리 중 오류가 발생했습니다.') + suffix,
    retryable: false,
    fallback_sources: [],
    // 서버가 바디를 못 준 경우에도 문의용 ID는 헤더에서 건져 본다
    request_id: res.headers.get('x-request-id') ?? '',
  }
}
