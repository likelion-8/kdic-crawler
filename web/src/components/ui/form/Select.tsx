/** 셀렉트 — CM-DF-001 04절: "고정 목록. 값이 6개 이하면 셀렉트, 그 이상은 검색형".
 * options가 6개를 넘으면 이 컴포넌트 대신 검색형 입력을 쓸지 화면 스펙에서 판단할 것.
 * ponytail: 네이티브 <select> 유지 — 라벨 연결(htmlFor)·키보드·SSR(selfcheck) 동작이 검증돼 있다.
 * 룩만 shadcn SelectTrigger와 맞췄다. Radix Select가 필요해지면 그때 교체.
 *
 * 폭은 140px 하한 + 내용 맞춤이다. 고정 140px로 두었더니 옵션 라벨을 서버가 주는 필터
 * (활동 로그의 '행위'·'실행자')와 모델 목록에서 선택된 값이 잘려, 무엇이 선택돼 있는지
 * 화면에서 확인할 수 없었다. 상한은 부모 폭(max-w-full)이라 모달·카드 밖으로는 못 나간다. */
import { useId } from 'react'
import { ChevronDown } from 'lucide-react'
import { Field } from './Field'
import type { FieldOptions } from './Field'

export interface SelectOption {
  value: string
  label: string
}

export interface SelectProps extends FieldOptions {
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
  disabled?: boolean
}

export function Select({ value, onChange, options, disabled, ...field }: SelectProps) {
  const id = useId()
  const selected = options.find((o) => o.value === value)

  return (
    // 대비 표기는 코드값이 아니라 라벨로 보여준다('현행 전체 → 착오송금')
    <Field id={id} value={selected?.label ?? value} {...field}>
      {/* max-w-full·min-w-0을 span에도 건다 — select의 max-w-full은 이 span을 기준으로 재는데
          span 자체에 상한이 없으면 span이 select 크기만큼 자라서 상한이 무의미해진다.
          긴 옵션 라벨에서 모달 밖으로 삐져나가고 가로 스크롤이 생겼다 (2026-08-05) */}
      <span className="relative inline-flex max-w-full min-w-0">
        <select
          id={id}
          className="h-8 w-auto min-w-35 max-w-full appearance-none rounded-md border border-input bg-transparent pr-8 pl-3 text-sm whitespace-nowrap transition-[color,box-shadow] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20"
          value={value}
          disabled={disabled}
          aria-describedby={field.error ? `${id}-error` : undefined}
          aria-invalid={field.error ? true : undefined}
          onChange={(e) => onChange(e.target.value)}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown
          className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
      </span>
    </Field>
  )
}
