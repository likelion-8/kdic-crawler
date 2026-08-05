/** 버튼 — CM-DF-001 03절.
 * 규칙: 라벨은 동사로 / Danger는 확인 모달 안에서만 / 비활성 버튼은 숨기지 않고 사유를 밝힌다.
 * 스타일은 shadcn buttonVariants 기반: primary→default · secondary→outline · danger→destructive.
 *
 * 비활성 사유 표기(2026-08-04 개편): 예전에는 버튼 **옆에 회색 캡션**으로 상시 노출했다.
 * 사유 문장이 버튼보다 길어 툴바·표·폼 어디에 놓아도 버튼이 밀리거나 줄이 접혔고, 권한 없는
 * 계정에서는 같은 문장이 화면의 모든 컨트롤 옆에 되풀이됐다(사용자 지적).
 * 지금은 두 갈래로 나눈다.
 *  · 눈 — 버튼 위에 올리면 뜨는 툴팁. disabled 요소는 마우스 이벤트를 내지 않으므로 감싼 span이 받는다
 *  · 보조기기 — 늘 있는 sr-only 문장을 `aria-describedby`로 묶는다(툴팁을 안 열어도 읽힌다)
 * ⚠ 화면 전체가 권한으로 잠기는 경우는 여기 사유에 기대지 말 것 — 컨트롤마다 같은 말을 다는 대신
 *   화면 위에 '보기 전용' 안내를 한 번 둔다(RagParams·ops-cards 참고). */
import { useId } from 'react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Loader2 } from 'lucide-react'
import { buttonVariants } from '../shadcn/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../shadcn/tooltip'
import { cn } from '@/lib/utils'

/** 화면들이 <a>·<Link>에 버튼 룩을 입힐 때 쓰는 클래스 생성기 (shadcn 그대로 재노출) */
export { buttonVariants }

const VARIANT = {
  primary: 'default',
  secondary: 'outline',
  danger: 'destructive',
} as const

const SIZE = {
  md: 'default',
  sm: 'sm',
} as const

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  variant?: 'primary' | 'secondary' | 'danger'
  /** md=h-9 · sm=h-8(표 행 안 조치용) */
  size?: 'md' | 'sm'
  /** 왜 못 누르는지 — 비활성일 때 툴팁 + sr-only로 알린다(CM-DF-001 03절 규칙 3).
   * `loading` 중에는 쓰지 않는다 — 그때는 못 누르는 이유가 '제출 중'이지 이 문장이 아니다 */
  disabledReason?: string
  /** 제출 중. 중복 클릭을 막고 스피너를 보여준다 */
  loading?: boolean
  children: ReactNode
}

export function Button({
  variant = 'secondary',
  size = 'md',
  disabledReason,
  loading = false,
  disabled,
  className,
  children,
  ...rest
}: ButtonProps) {
  const isDisabled = disabled || loading
  // 제출 중에는 사유를 달지 않는다 — 그 순간 못 누르는 이유는 '보내는 중'이다
  const showReason = Boolean(disabled) && !loading && Boolean(disabledReason)
  const reasonId = useId()
  const btn = (
    <button
      type="button"
      // 라운드는 토큰(--radius 6px)에서 파생된 rounded-md(4px). 그림자는 쓰지 않는다 —
      // shadcn outline 배리언트의 shadow-xs를 여기서 끈다(떠 있는 면은 모달·토스트뿐)
      className={cn(buttonVariants({ variant: VARIANT[variant], size: SIZE[size] }), 'shadow-none', className)}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      aria-describedby={showReason ? reasonId : undefined}
      {...rest}
    >
      {loading && <Loader2 className="animate-spin" aria-hidden="true" />}
      {children}
    </button>
  )
  if (!showReason) return btn
  // 버튼이 폭을 채우려 하면(`w-full`) 래퍼도 함께 채워야 한다 — 래퍼가 내용폭으로 줄어들면
  // 그 안의 `w-full`은 래퍼 폭을 100%로 잡는다(로그인 버튼이 입력창의 절반으로 쪼그라들었다).
  const fillsWidth = /\bw-full\b/.test(className ?? '')
  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        {/* 트리거가 버튼이 아니라 감싼 span이다 — disabled 버튼은 mouseenter를 내지 않는다 */}
        <TooltipTrigger asChild>
          <span className={cn('inline-flex', fillsWidth && 'w-full')}>
            {btn}
            {/* 툴팁을 열지 않아도 읽히는 설명. Radix가 붙이는 aria-describedby는 열렸을 때만이라
                따로 둔다(InfoHint와 같은 방식) */}
            <span className="sr-only" id={reasonId}>
              {disabledReason}
            </span>
          </span>
        </TooltipTrigger>
        {/* break-keep — 한국어는 어절 단위로 접어야 한다. 기본 규칙이면 '입력해야'가
            '입 / 력해야'로 쪼개진다(실측) */}
        <TooltipContent className="max-w-64 text-balance break-keep">{disabledReason}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
