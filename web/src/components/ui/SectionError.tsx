/** 요청 실패를 화면 안에 남기는 공통 패널 — CM-DF-001 07.4절 "실패는 토스트가 아니라 화면 안에".
 *
 * 왜 모았나: 같은 패널이 세 벌 있었다(2026-08-04 전수 점검).
 *  · `settings/promptops/common.tsx`의 SectionError — 6개 화면이 쓰던 사실상의 정본
 *  · `Dashboard.tsx`의 QueryError — 같은 모양의 사본
 *  · `KnowledgeNew`의 FailurePanel — 같은 모양이되 **요청 ID를 안 보여줬다**
 * 사본이 갈라지면서 '문의할 때 댈 요청 ID'가 화면마다 있기도 없기도 했다. 하나로 합친다.
 *
 * 규칙 두 가지는 세 벌 모두 같았고 여기서도 지킨다.
 *  · 문구는 서버 `user_message` 그대로 — 계약 밖 예외까지 프론트가 지어내지 않는다
 *  · `retryable === true`이고 재시도 수단이 있을 때만 [다시 시도]를 그린다 */
import { Button } from './Button'
import { Notice } from './Notice'
import { isApiRequestError } from '../../lib/api/client'

export interface SectionErrorProps {
  /** 실패한 요청의 오류. 문구는 서버 user_message를 그대로 쓴다(PRD-02 §3) */
  error: unknown
  /** retryable === true일 때만 [다시 시도]를 그린다 */
  onRetry?: () => void
}

export function SectionError({ error, onRetry }: SectionErrorProps) {
  if (!error) return null
  const api = isApiRequestError(error) ? error : null
  // 계약 밖 예외(스크립트 오류 등)까지 문구를 지어내지 않는다 — 서버가 준 문구만 노출한다
  const message = api ? api.error.user_message : '처리 중 오류가 발생했습니다.'
  const retryable = api?.error.retryable === true
  // 조치 전에 읽어야 하는 실패 결과라 옅은 색면 인셋(block) — 문장은 잉크로 두고 색은 아이콘만 쓴다
  return (
    <div className="mt-3" role="alert">
      <Notice
        tone="danger"
        variant="block"
        meta={api?.error.request_id && `요청 ID ${api.error.request_id}`}
        action={
          retryable && onRetry ? (
            <Button size="sm" onClick={onRetry}>
              다시 시도
            </Button>
          ) : undefined
        }
      >
        {message}
      </Notice>
    </div>
  )
}
