/** 스테퍼 — CM-DF-001 04절: "정수 · 범위가 좁은 값. 우측에 현행값 병기".
 * min/max/step은 화면 스펙에서 주입한다(12절 이슈 19 — 이 문서엔 예시값 20뿐). */
import { useId } from 'react'
import { Minus, Plus } from 'lucide-react'
import { buttonVariants } from '../../shadcn/button'
import { Input } from '../../shadcn/input'
import { cn } from '@/lib/utils'
import { Field } from './Field'
import type { FieldOptions } from './Field'

export interface StepperProps extends FieldOptions {
  value: number
  onChange: (value: number) => void
  min?: number
  max?: number
  step?: number
  disabled?: boolean
}

export function Stepper({ value, onChange, min, max, step = 1, disabled, ...field }: StepperProps) {
  const id = useId()
  const clamp = (v: number) => Math.min(max ?? Infinity, Math.max(min ?? -Infinity, v))
  const atMin = min !== undefined && value <= min
  const atMax = max !== undefined && value >= max
  const stepBtn = cn(buttonVariants({ variant: 'outline', size: 'icon-sm' }), 'shadow-none')

  return (
    <Field id={id} value={value} {...field}>
      <div className="inline-flex items-center gap-1">
        <button
          type="button"
          className={stepBtn}
          onClick={() => onChange(clamp(value - step))}
          disabled={disabled || atMin}
          aria-label={`${field.label} 줄이기`}
        >
          <Minus aria-hidden="true" />
        </button>
        {/* number 입력이라 위/아래 화살표 키 조작이 브라우저 기본으로 동작한다(키보드 접근성).
            스피너 화살표는 좌우 버튼과 중복이라 숨긴다(키보드 조작은 그대로) */}
        <Input
          id={id}
          className="h-8 w-14 px-1 text-center tabular-nums shadow-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
          type="number"
          inputMode="numeric"
          value={value}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          aria-describedby={field.error ? `${id}-error` : undefined}
          aria-invalid={field.error ? true : undefined}
          onChange={(e) => {
            const next = Number(e.target.value)
            if (!Number.isNaN(next)) onChange(clamp(next))
          }}
        />
        <button
          type="button"
          className={stepBtn}
          onClick={() => onChange(clamp(value + step))}
          disabled={disabled || atMax}
          aria-label={`${field.label} 늘리기`}
        >
          <Plus aria-hidden="true" />
        </button>
      </div>
    </Field>
  )
}
