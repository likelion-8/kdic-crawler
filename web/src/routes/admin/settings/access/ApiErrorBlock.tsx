/** 조회 실패를 화면 안에 남기는 블록 — "실패는 토스트가 아니라 화면 안에"(CM-DF-001 07.4절).
 * 문구는 서버 user_message 그대로, [다시 시도]는 retryable === true일 때만 그린다(PRD-02 §3-b).
 * AD-010/AD-011 두 화면이 같은 모양을 쓰므로 공통 컴포넌트 승격 후보다(report shared_needed). */
import { Button, Notice } from '../../../../components/ui'
import { isApiRequestError } from '../../../../lib/api/client'

export interface ApiErrorBlockProps {
  error: unknown
  onRetry?: () => void
}

/** 서버 미도달(네트워크)일 때만 프론트 문구를 쓴다 — client.ts가 이미 그 문구를 넣어 준다 */
export function ApiErrorBlock({ error, onRetry }: ApiErrorBlockProps) {
  if (!isApiRequestError(error)) {
    return (
      <div className="my-2" role="alert">
        <Notice tone="danger" variant="block">
          처리 중 오류가 발생했습니다.
        </Notice>
      </div>
    )
  }
  return (
    <div className="my-2" role="alert">
      <Notice
        tone="danger"
        variant="block"
        meta={error.error.request_id && `요청 ID ${error.error.request_id}`}
        action={
          error.error.retryable &&
          onRetry && (
            <Button size="sm" onClick={onRetry}>
              다시 시도
            </Button>
          )
        }
      >
        {error.error.user_message}
      </Notice>
    </div>
  )
}
