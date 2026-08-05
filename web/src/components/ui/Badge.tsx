/** 배지·칩 — CM-DF-001 05절.
 * 허용은 3가지뿐: ①상태(현행·초안·실패) ②집계(무중단 2·현재 2건) ③위험 경고(재적재 필요·복구 불가).
 * 설명 문구·메타데이터·검증 표식은 배지로 만들지 말고 일반 텍스트/ColorText로 쓴다(05절 금지).
 * ※배지를 남발하면 색이 의미를 잃는다 — 한 화면 5개 이내(문서 주의문).
 * children이 필수인 이유: 상태를 색만으로 알리면 안 된다(CM-DF-004 09절). */
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface BadgeProps {
  /** 초록=현행·무중단 / 보라=초안 / 주황=주의·후속작업 / 빨강=실패·복구불가 */
  tone: 'green' | 'purple' | 'orange' | 'red'
  /** 허용 3분류. 어디에 해당하는지 명시하게 해서 남용을 막는다(05절) */
  kind: 'status' | 'count' | 'warning'
  children: ReactNode
}

/* 색 조합은 CM-DF-001 05절 실측값을 브리지한 시맨틱 토큰 그대로.
 * 채운 알약(pill) 대신 1px 보더 + 컬러 글자 + 아주 옅은 배경 — 화면을 알록달록하게 덮지 않는다.
 * purple(초안)은 중립 톤으로 내렸다: 보라는 Primary·링크·포커스·현재 위치에만 쓴다. */
const TONE: Record<BadgeProps['tone'], string> = {
  green: 'border-success/35 bg-success-bg/50 text-success',
  purple: 'border-border bg-muted text-foreground',
  orange: 'border-warning/35 bg-warning-bg/50 text-warning',
  red: 'border-danger-fg/35 bg-danger-soft/60 text-danger-fg',
}

export function Badge({ tone, kind, children }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex w-fit shrink-0 items-center gap-1 rounded-[3px] border px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap',
        TONE[tone],
        // 집계 배지는 숫자가 흔들리지 않게 고정폭 숫자
        kind === 'count' && 'tabular-nums',
      )}
    >
      {children}
    </span>
  )
}
