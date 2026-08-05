/** 컬러 텍스트 — CM-DF-001 05.3절 "성격 표시는 배지 대신 컬러 텍스트"(배경 없음).
 * 초록=무중단(승인·검증 후 재색인 없이 무중단 반영) / 주황=재적재 필요(주의·후속 작업)
 * 보라=현재 선택(활성 탭·현재 값) / 빨강=위험·차단(파괴적 액션·차단 상태)
 * 검증 표식('출처 ✓' 등)도 배지가 아니라 이걸 쓴다(05.2절). */
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface ColorTextProps {
  tone: 'green' | 'orange' | 'purple' | 'red'
  children: ReactNode
}

/* 배경 없음 — 배지와 구분되는 유일한 신호가 배경 유무다(05.3절) */
const TONE: Record<ColorTextProps['tone'], string> = {
  green: 'text-success',
  orange: 'text-warning',
  purple: 'text-primary',
  red: 'text-danger-fg',
}

export function ColorText({ tone, children }: ColorTextProps) {
  return <span className={cn('font-medium', TONE[tone])}>{children}</span>
}
