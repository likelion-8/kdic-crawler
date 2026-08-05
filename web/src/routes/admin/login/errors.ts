/** 인증 화면 공통 — ApiRequestError가 아닌 예외를 '화면에 남길 수 있는' 오류로 바꾼다.
 *
 * 로그인·재설정·비밀번호 변경은 전부 `void submit()`으로 호출한다. 여기서 다시 던지면
 * 아무도 잡지 못해 unhandled rejection이 되고 사용자에게는 피드백이 전혀 남지 않는다(검증 D083).
 * 문구는 서버가 준 게 아닐 때만 쓰는 프론트 고정 문구다(client.ts의 미도달 예외와 같은 취급). */
import { ApiRequestError, isApiRequestError } from '../../../lib/api/client'

export function toRequestError(e: unknown): ApiRequestError {
  if (isApiRequestError(e)) return e
  return new ApiRequestError(0, {
    code: 'INTERNAL',
    user_message: '처리 중 오류가 발생했습니다.',
    retryable: false,
    fallback_sources: [],
    request_id: '',
  })
}
