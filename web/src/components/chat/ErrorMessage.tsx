/** 오류 말풍선 — CB-004 Case 3(오류) · Case 4(부분 실패 폴백).
 *
 * 🔴 문구는 서버 `user_message`를 그대로 쓴다. 화면마다 다른 오류 문구를 만들지 않는다(CB-004 공통 회색 박스).
 * 🔴 `retryable === true`일 때만 [다시 시도]. 429는 안내만 하고 자동 재호출하지 않는다(PRD-02 §3-b). */
import { CircleAlert, RefreshCw } from 'lucide-react'
import type { ApiError } from '../../lib/api/types'
import { Button } from '../ui'
import { Bubble, BubbleText } from './Bubble'
import { SourceCard } from './SourceCard'

export interface ErrorMessageProps {
  error: ApiError
  /** 보낸/받은 시각 — 없으면 시각을 그리지 않는다 */
  at?: string | number
  /** 없으면 [다시 시도]를 그리지 않는다 — 같은 질문 2회 소진 시 화면이 버튼을 걷어간다(CB-004 Case 5) */
  onRetry?: () => void
}

/** 폴백 출처 카드에 함께 붙는 안내 (CB-DF-002 Type 4 원문) */
const FALLBACK_NOTICE = '대신 관련 자료를 찾아드렸어요'

export function ErrorMessage({ error, at, onRetry }: ErrorMessageProps) {
  // 검색 성공 + 생성 실패 = Case 4. 이때는 오류 테두리를 쓰지 않고 일반 회색 말풍선이다
  const hasFallback = error.fallback_sources.length > 0
  const showRetry = error.retryable && onRetry !== undefined

  return (
    <Bubble
      variant={hasFallback ? 'bot' : 'error'}
      at={at}
      footer={
        <div className="flex flex-wrap items-center gap-3">
          {/* 시각 크기는 목업(28px대)을 지키되 after 확장으로 터치 타깃 44px을 채운다(CM-DF-004 09절) */}
          {showRetry && (
            <Button
              variant="secondary"
              size="sm"
              className="relative font-semibold after:absolute after:-inset-x-1 after:-inset-y-1.5 after:content-['']"
              onClick={onRetry}
            >
              <RefreshCw aria-hidden="true" /> 다시 시도
            </Button>
          )}
          {/* "문의에 쓸 수 있도록 요청 ID를 함께 표시합니다" (CB-004 Desc 3행) */}
          {/* 빈 문자열뿐 아니라 null·undefined도 걸러낸다 — 백엔드가 SSE 오류에 이 값을
              안 싣는 경로가 있어(미들웨어 이전 예외) 그대로 두면 '요청 ID null'이 찍힌다 */}
          {error.request_id && (
            <span className="text-xs text-muted-foreground">요청 ID {error.request_id}</span>
          )}
        </div>
      }
    >
      {hasFallback ? (
        <BubbleText text={error.user_message} />
      ) : (
        <div className="flex items-start gap-2">
          <CircleAlert className="mt-1 size-4 shrink-0 text-destructive" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <BubbleText text={error.user_message} />
          </div>
        </div>
      )}

      {hasFallback && (
        <section className="mt-3">
          <p className="mb-2">{FALLBACK_NOTICE}</p>
          {/* 정상 답변의 출처 카드와 동일 컴포넌트 재사용 (CB-004 Case 4 프론트 동작 규격) */}
          <ol className="flex flex-col gap-2">
            {error.fallback_sources.map((s, i) => (
              <li key={`${s.page_id}-${i}`}>
                <SourceCard title={s.title} subtitle={s.breadcrumb} url={s.url} />
              </li>
            ))}
          </ol>
        </section>
      )}
    </Bubble>
  )
}
