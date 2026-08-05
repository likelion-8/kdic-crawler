/** 안내·경고 표기 — CM-DF-001 07절(상태 피드백)의 "실패는 화면 안에 남긴다" 원칙 구현.
 *
 * 설계 의도 (이전 방식을 왜 버렸는지):
 * 처음엔 좌측 2px 액센트 바를 썼고(AI 생성 UI의 대표 상투구라 폐기), 다음엔 상단 2px 헤어라인
 * `.notice`를 썼다. 그런데 가로줄은 눈에 '구획 나눔'으로 읽히지 '경고'로 읽히지 않는다 —
 * 좌측 바를 90도 돌려놓은 것에 지나지 않았고, 문장 전체를 경고색으로 칠해 오히려 읽기 어려웠다.
 *
 * 그래서 두 가지를 바꿨다:
 *  1. **색은 아이콘에만.** 본문은 잉크(text-foreground)로 둔다 — 대비가 살고 훨씬 정제돼 보인다.
 *  2. **선이 아니라 등급.** 한 가지 장치로 다 처리하지 않고 무게에 따라 세 가지로 나눈다.
 *
 * | variant | 생김새 | 언제 |
 * |---|---|---|
 * | `inline` | 아이콘 + 본문 한 줄. 배경·테두리 없음 | 카드 안의 참고성 안내 (기본값) |
 * | `block`  | 옅은 색면 인셋 + 아이콘 + (제목) + 본문 | 조치 전에 반드시 읽어야 하는 것·실패 결과 |
 * | `banner` | block과 같되 화면 폭을 쓰는 상단 띠 | 페이지 전체에 걸리는 상태 |
 *
 * 색만으로 알리지 않는다(CM-DF-004 09절) — 본문 텍스트가 상태를 말하고, block/banner는
 * 스크린리더용 톤 라벨을 따로 읽어 준다. role(alert/status)은 호출부가 정한다. */
import type { ReactNode } from 'react'
import { CircleAlert, Info, TriangleAlert } from 'lucide-react'
import { cn } from '@/lib/utils'

export type NoticeTone = 'info' | 'warning' | 'danger'
export type NoticeVariant = 'inline' | 'block' | 'banner'

const TONE = {
  info: { Icon: Info, icon: 'text-muted-foreground', face: 'bg-muted/60', label: '안내' },
  warning: { Icon: TriangleAlert, icon: 'text-warning', face: 'bg-warning-bg/50', label: '주의' },
  danger: { Icon: CircleAlert, icon: 'text-danger-fg', face: 'bg-danger-soft/60', label: '오류' },
} as const

export interface NoticeProps {
  tone?: NoticeTone
  variant?: NoticeVariant
  /** 굵은 첫 줄 — block·banner에서만. 길면 본문으로 내린다 */
  title?: ReactNode
  /** 우측 액션([다시 시도]·[재적재 실행 →] 등) */
  action?: ReactNode
  /** 본문 아래 보조 정보(요청 ID 등) */
  meta?: ReactNode
  className?: string
  children: ReactNode
}

export function Notice({
  tone = 'info',
  variant = 'inline',
  title,
  action,
  meta,
  className,
  children,
}: NoticeProps) {
  const { Icon, icon, face, label } = TONE[tone]

  if (variant === 'inline') {
    return (
      <p className={cn('flex items-start gap-1.5 text-[13px] text-foreground', className)}>
        <Icon className={cn('mt-0.5 size-3.5 shrink-0', icon)} aria-hidden="true" />
        <span className="min-w-0">{children}</span>
        {action && <span className="ml-auto shrink-0 pl-2">{action}</span>}
      </p>
    )
  }

  return (
    <div
      className={cn(
        'flex items-start gap-2.5 rounded-md px-3.5 py-3',
        face,
        variant === 'banner' && 'w-full',
        className,
      )}
    >
      <Icon className={cn('mt-0.5 size-4 shrink-0', icon)} aria-hidden="true" />
      <div className="min-w-0 flex-1 text-sm text-foreground">
        {/* 색을 못 보는 사용자에게도 성격을 알린다 */}
        <span className="sr-only">{label}: </span>
        {title && <p className="font-medium">{title}</p>}
        <div className={cn(title && 'mt-0.5')}>{children}</div>
        {meta && <p className="mt-1 text-xs text-muted-foreground">{meta}</p>}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  )
}
