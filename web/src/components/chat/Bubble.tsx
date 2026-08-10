/** 말풍선 뼈대 — CM-DF-003 02절(아바타 38px 원형 · 말풍선 최대폭 68% · 모서리 사용자 18/4/18/18 · 챗봇 4/18/18/18).
 * 답변 렌더러 4종(답변·오류·되묻기·대기)이 전부 이 껍데기를 쓴다. 화면 전용이라 components/ui로 올리지 않았다.
 * 고정 수치(68%·radii·아바타 38px)는 tokens.css 변수를 그대로 참조한다 — 값 하드코딩 금지. */
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { formatClock } from '../../lib/format'
import { Avatar } from './Avatar'
import { AVATARS } from './avatars'

export interface BubbleProps {
  /** error = 오류 전용 테두리 변형 (CB-004 Case 3 "테두리 #D94C4C"). Case 4(폴백)는 bot을 쓴다 */
  variant: 'user' | 'bot' | 'error'
  /** 아바타 없이 말풍선만 — 역할 선택 결과 말풍선은 아바타가 없다 (CB-005 3.1) */
  hideAvatar?: boolean
  /** 보낸/받은 시각(epoch ms 또는 ISO). 없으면 시각을 그리지 않는다 */
  at?: string | number
  /** 말풍선 바깥 아래에 붙는 영역 — AI 고지·[다시 시도] (CB-002 마커 8 / CB-004 Case 3 목업) */
  footer?: ReactNode
  children: ReactNode
}

/** 화자별 아바타 — 소스는 avatars.ts 한곳에서 정하고, 폴백은 Avatar 컴포넌트가 처리한다.
 * 오류 말풍선도 말하는 쪽은 챗봇이라 봇 아바타를 그대로 쓴다. */
const AVATAR = {
  user: AVATARS.user,
  bot: AVATARS.bot,
  error: AVATARS.bot,
} as const

export function Bubble({ variant, hideAvatar = false, at, footer, children }: BubbleProps) {
  const avatar = AVATAR[variant]
  const isUser = variant === 'user'
  return (
    // bubble-in(global.css) — 새 말풍선이 짧게 떠오르며 들어온다. 진입 1회뿐이라 재렌더에는 안 돈다
    <div className={cn('bubble-in flex items-start gap-3', isUser && 'ml-auto flex-row-reverse')}>
      {!hideAvatar && <Avatar {...avatar} />}
      <div
        className={cn(
          'flex min-w-0 max-w-(--chat-bubble-max) flex-col gap-2',
          isUser && 'items-end',
        )}
      >
        {/* 오류는 스크린리더에 즉시 고지한다 (CB-004 §7-17 접근성 제안) */}
        <div
          data-variant={variant}
          role={variant === 'error' ? 'alert' : undefined}
          className={cn(
            // break-keep: 한글을 음절이 아니라 어절 단위로 줄바꿈한다("중/입니다" 방지).
            // 공백 없는 긴 문자열(URL 등)은 overflow-wrap:anywhere가 여전히 안전하게 꺾는다
            'px-5 py-3.5 text-[15px] leading-relaxed break-keep [overflow-wrap:anywhere]',
            isUser
              ? 'rounded-(--chat-radius-user) bg-user-bubble text-user-bubble-fg'
              : 'rounded-(--chat-radius-bot) border bg-card text-card-foreground',
            variant === 'error' && 'border-destructive/60',
          )}
        >
          {children}
        </div>
        {/* 말풍선 아래 한 줄 — 왼쪽은 조치(피드백 등), 오른쪽은 시각.
            둘 다 말풍선 폭 안에서 양 끝에 붙어 말풍선의 좌우 경계와 줄이 맞는다.
            시각이 없으면(구 계약으로 복원된 대화) 그 자리를 비운다 — 지금 시각을 찍으면 거짓이다 */}
        {(footer || at !== undefined) && (
          // -mt-1 : 말풍선과의 간격(gap-2)을 줄여 이 줄을 말풍선 쪽에 붙인다
          <div className="-mt-1 flex w-full items-start justify-between gap-3">
            {/* 왼쪽이 비어도 시각이 오른쪽에 남도록 자리를 지킨다.
                items-start인 이유: 피드백 사유 폼이 펼쳐지면 items-center가 시각을 폼 한가운데로
                끌어내린다 — 시각은 늘 첫 줄(버튼 줄)에 붙어 있어야 한다 */}
            <div className="min-w-0">{footer}</div>
            {at !== undefined && (
              <time
                // 투표 버튼의 **윗변**에 글자 윗줄을 맞춘다(세로 중앙 정렬이 아니다).
                // 버튼 테두리(1px) + px-2.5 버튼의 시각적 상단선과 맞도록 살짝만 내린다
                className="mt-0.5 shrink-0 text-[11px] leading-4 text-muted-foreground tabular-nums"
                dateTime={new Date(at).toISOString()}
              >
                {formatClock(at)}
              </time>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/** `**볼드**`만 <strong>으로 바꾼다 — LLM이 계약(마크다운 미사용)을 어기고 내보내는 유일한
 * 표기가 볼드라, 리터럴 별표가 그대로 노출되는 것(2026-08-10 보고)만 최소로 고친다.
 * 그 외 마크다운은 계속 파싱하지 않는다(CM-DF-003 02절). 스트리밍 중 아직 안 닫힌 `**`는
 * 잠시 리터럴로 보이다가 닫히는 순간 굵게 바뀐다. */
function renderInline(p: string) {
  const parts = p.split(/\*\*([^*]+)\*\*/g)
  if (parts.length === 1) return p
  return parts.map((s, i) => (i % 2 === 1 ? <strong key={i}>{s}</strong> : s))
}

/** 말풍선 본문 텍스트 — 마크다운 파싱 없이 문단 단위로만 나눈다 (CM-DF-003 02절 표기 원칙).
 * 문단 안의 홑 줄바꿈(①②③ 번호 목록 등)은 `whitespace-pre-wrap`이 그대로 살린다. */
export function BubbleText({ text, caret = false }: { text: string; caret?: boolean }) {
  const paragraphs = text.split(/\n{2,}/).filter((p) => p.trim() !== '')
  const last = paragraphs.length - 1
  return (
    <>
      {paragraphs.map((p, i) => (
        // 문단은 스트리밍 중 뒤에만 붙으므로 index key로 충분하다(중간 삽입·정렬 없음)
        <p key={i} className="whitespace-pre-wrap not-last:mb-2.5">
          {renderInline(p)}
          {/* 커서는 반드시 마지막 문단 '안'에 둔다 — <p> 밖에 두면 블록 다음 줄로 떨어져
              글자와 떨어진 채 홀로 깜빡인다(사용자 지적). 글 끝을 따라다녀야 자연스럽다 */}
          {caret && i === last && <Caret />}
        </p>
      ))}
      {/* 첫 델타가 오기 전(문단 0개)에도 커서는 보여야 한다 */}
      {caret && paragraphs.length === 0 && (
        <p className="whitespace-pre-wrap">
          <Caret />
        </p>
      )}
    </>
  )
}

/** 스트리밍 커서 — 글자 높이에 맞춘 얇은 세로 막대 */
function Caret() {
  return (
    <span
      className="ml-0.5 inline-block h-[1.05em] w-0.5 animate-pulse rounded-full bg-foreground align-text-bottom [animation-duration:1s]"
      aria-hidden="true"
    />
  )
}
