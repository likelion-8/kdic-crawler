/** 진행 스텝 (파이프라인 단계 표시) — CM-DF-001 08절.
 * 단계 이름·순서 정본은 lib/constants.ts PIPELINE_STEPS 다(현재 7종:
 * 수집 → 변환 → 청킹 → 검증 → 게이트 → 색인 → 반영). 여기서 다시 세지 않는다.
 * 상태 기호 4종: ✓ 완료 · ◐ 진행 중 · ✗ 실패 · ○ 대기. 작업 전체 상태 5종(CM-DF-004 04절)과 구분한다.
 * 시각은 원형 스텝 + 연결선(lucide Check/Loader2/X + 상태색)으로 그리되,
 * 기획서 고정 기호는 마크업에 유지하고 상태는 한글 텍스트로 병기한다(CM-DF-004 09절).
 * 단계 그림은 진행 중 화면 한 곳에만. 사후 화면은 <PipelineStepText>로 위치만 글로 알린다. */
import type { ReactNode } from 'react'
import { Check, Loader2, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { PIPELINE_STEPS } from '../../lib/constants'

export type StepState = 'done' | 'running' | 'failed' | 'waiting'

/** 기획서 고정 기호 — 시각은 lucide 아이콘이 대신하므로 DOM에만 남긴다(카피 보존) */
const STEP_SYMBOL: Record<StepState, string> = {
  done: '✓',
  running: '◐',
  failed: '✗',
  waiting: '○',
}
const STEP_LABEL: Record<StepState, string> = {
  done: '완료',
  running: '진행 중',
  failed: '실패',
  waiting: '대기',
}
const STEP_ICON: Record<StepState, ReactNode> = {
  done: <Check className="size-3" aria-hidden="true" />,
  running: <Loader2 className="size-3 animate-spin" aria-hidden="true" />,
  failed: <X className="size-3" aria-hidden="true" />,
  waiting: null, // 빈 원 = ○
}
/* 상태색 — 색면으로 채우지 않고 1px 테두리와 글자에만 칠한다.
 * 보라는 '진행 중'(현재 위치)에만. 완료는 성공색, 나머지는 잉크·헤어라인 */
const CIRCLE: Record<StepState, string> = {
  done: 'border-success/45 text-success',
  running: 'border-primary text-primary',
  failed: 'border-danger-fg/45 text-danger-fg',
  waiting: 'border-border text-muted-foreground',
}
const STATE_TEXT: Record<StepState, string> = {
  done: 'text-success',
  running: 'font-semibold text-primary',
  failed: 'text-danger-fg',
  waiting: 'text-muted-foreground',
}

export interface PipelineStepsProps {
  /** PIPELINE_STEPS와 같은 순서. 짧으면 나머지는 '대기'로 본다 */
  states: readonly StepState[]
}

export function PipelineSteps({ states }: PipelineStepsProps) {
  return (
    // 가로 배열 + 단계 사이 연결선. 좁은 화면에서는 줄바꿈되게 둔다
    <ol className="flex flex-wrap items-center gap-y-2">
      {PIPELINE_STEPS.map((name, i) => {
        const state = states[i] ?? 'waiting'
        return (
          <li key={name} className="flex items-center gap-1.5 text-[13px]">
            <span
              className={cn('flex size-5 shrink-0 items-center justify-center rounded-full border', CIRCLE[state])}
              aria-hidden="true"
            >
              {STEP_ICON[state]}
            </span>
            <span className="sr-only" aria-hidden="true">
              {STEP_SYMBOL[state]}
            </span>
            <span className="text-foreground">{name}</span>
            {/* 상태를 색 외에 글자로도 병기(CM-DF-004 09절) */}
            <span className={cn('text-xs', STATE_TEXT[state])}>{STEP_LABEL[state]}</span>
            {/* 연결선 — 마지막 단계 뒤에는 그리지 않는다 */}
            {i < PIPELINE_STEPS.length - 1 && <span className="mx-2.5 h-px w-4 bg-border" aria-hidden="true" />}
          </li>
        )
      })}
    </ol>
  )
}

export interface PipelineStepTextProps {
  /** 1부터 시작하는 단계 번호 */
  step: number
}

/** 사후 화면(실패 상세 등)용 — '7단계 중 5번째'처럼 위치를 글로만 알린다(09절 규칙 3).
 *  건수는 PIPELINE_STEPS 에서 세므로 단계가 늘어도 문구가 따라온다 */
export function PipelineStepText({ step }: PipelineStepTextProps) {
  return (
    <span className="text-xs text-muted-foreground">
      {PIPELINE_STEPS.length}단계 중 {step}번째
    </span>
  )
}
