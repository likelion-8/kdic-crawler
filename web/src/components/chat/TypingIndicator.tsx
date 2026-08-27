/** 답변 생성 대기 인디케이터 — 기본 문구는 CB-DF-003 02절 로딩 문구 원문 `예솜24가 생각 중입니다...`.
 * 생성 단계에 따라 문구가 바뀐다(ChatPage PHASE_TEXT — 2026-08-27 델타 비표시 전환).
 * 점 3개 bounce(150ms 간격) + 문구. LoadingText의 role="status"가 스크린리더 고지를 담당하고,
 * 점·reveal 애니메이션은 전역 prefers-reduced-motion 규칙(global.css)이 정지시킨다. */
import { LoadingText } from '../ui'
import { Bubble } from './Bubble'

const DOT = 'size-1.5 animate-bounce rounded-full bg-muted-foreground [animation-duration:0.9s]'

export function TypingIndicator({ text = '예솜24가 생각 중입니다...' }: { text?: string }) {
  return (
    <Bubble variant="bot">
      {/* 고정 상태 문구가 좁은 컨테이너에서 "중/입니다"로 꺾이지 않게 한 줄 고정 */}
      <span className="flex items-center gap-2.5 whitespace-nowrap">
        <span className="flex items-center gap-1" aria-hidden="true">
          <span className={DOT} />
          <span className={`${DOT} [animation-delay:150ms]`} />
          <span className={`${DOT} [animation-delay:300ms]`} />
        </span>
        {/* key=text — 단계 문구가 바뀌면 리마운트되어 reveal 페이드로 갈아든다 */}
        <span key={text} className="reveal">
          <LoadingText text={text} />
        </span>
      </span>
    </Bubble>
  )
}
