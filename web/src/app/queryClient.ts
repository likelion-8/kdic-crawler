/** TanStack Query 전역 설정.
 *
 *  - 429는 재시도 금지 — 대기 안내만 하고 자동 반복 호출하지 않는다 (PRD-02 §3-b).
 *  - 403·401도 재시도 금지 — 다시 보내도 결과가 같고, 거부 이벤트만 쌓인다 (§3-d).
 *  - 창 포커스 자동 재조회 끔 — 관리자 활동 로그는 '조회 자체'가 이벤트로 기록되므로
 *    탭 전환마다 조회가 나가면 안 된다 (PRD-02 C-2 12).
 *  - 폴링이 필요한 화면(AD-004 진행 상태)은 refetchInterval을 직접 주되,
 *    호출은 apiRequest(..., { isPoll: true })로 보내 유휴 세션 타이머를 건드리지 않는다. */
import { QueryClient } from '@tanstack/react-query'
import { isApiRequestError } from '../lib/api/client'

/** 다시 보내도 결과가 바뀌지 않는 상태 */
const NO_RETRY_STATUS = new Set([400, 401, 403, 404, 409, 422, 429])

function shouldRetry(failureCount: number, error: Error): boolean {
  if (isApiRequestError(error) && NO_RETRY_STATUS.has(error.status)) return false
  return failureCount < 2
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: shouldRetry,
      refetchOnWindowFocus: false,
      staleTime: 30_000,
    },
    mutations: {
      // 쓰기는 절대 자동 재시도하지 않는다 — 중복 실행은 활동 로그에 그대로 남는다
      retry: false,
    },
  },
})
