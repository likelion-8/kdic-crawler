/** 토글 — CM-DF-001 04절: "이진 값. 라벨로 현재 상태를 글자로도 표기".
 * 색만으로 상태를 알리지 않도록 On/Off 글자를 항상 함께 렌더한다(CM-DF-004 09절).
 * 컨트롤은 shadcn Switch(Radix) — 스페이스바 조작·포커스·role=switch를 Radix가 처리한다. */
import { useId } from 'react'
import { Switch } from '../../shadcn/switch'
import { cn } from '@/lib/utils'
import { Field } from './Field'
import type { FieldOptions } from './Field'

export interface ToggleProps extends FieldOptions {
  checked: boolean
  onChange: (checked: boolean) => void
  onLabel?: string
  offLabel?: string
  disabled?: boolean
}

export function Toggle({
  checked,
  onChange,
  onLabel = 'On',
  offLabel = 'Off',
  disabled,
  ...field
}: ToggleProps) {
  const id = useId()
  const stateLabel = checked ? onLabel : offLabel

  return (
    <Field id={id} value={stateLabel} {...field}>
      <span className="inline-flex items-center gap-2">
        <Switch
          id={id}
          checked={checked}
          disabled={disabled}
          aria-describedby={field.error ? `${id}-error` : undefined}
          onCheckedChange={onChange}
        />
        {/* 상태 글자는 잉크 — 보라는 컨트롤(Switch) 채움에만 */}
        <span className={cn('text-xs font-medium', disabled ? 'text-muted-foreground' : 'text-foreground')}>
          {stateLabel}
        </span>
      </span>
    </Field>
  )
}
