/** 텍스트 입력 — CM-DF-001 04절: "placeholder는 지시문이 아니라 '입력 예시'를 보여줄 것".
 * (목업 placeholder: `예: 분기 정기 재수집`) */
import { useId } from 'react'
import { Input } from '../../shadcn/input'
import { Textarea } from '../../shadcn/textarea'
import { Field } from './Field'
import type { FieldOptions } from './Field'

export interface TextFieldProps extends FieldOptions {
  value: string
  onChange: (value: string) => void
  /** '예: ...' 형태의 입력 예시 */
  placeholder?: string
  maxLength?: number
  disabled?: boolean
  /** URL·제목·질문처럼 값이 긴 항목 — 기본 300px 대신 행의 남은 폭을 다 쓴다.
   * (숫자·짧은 이름까지 늘리면 폼이 허전해져 기본값은 그대로 둔다) */
  grow?: boolean
  /** 안내 문구·요약처럼 **문장**이 들어가는 항목 — 한 줄 입력이 아니라 여러 줄로 받는다.
   * 내용에 따라 높이가 자동으로 늘어난다(field-sizing-content). */
  multiline?: boolean
}

export function TextField({
  value,
  onChange,
  placeholder,
  maxLength,
  disabled,
  grow = false,
  multiline = false,
  ...field
}: TextFieldProps) {
  const id = useId()
  const shared = {
    id,
    value,
    placeholder,
    maxLength,
    disabled,
    'aria-describedby': field.error ? `${id}-error` : undefined,
    'aria-invalid': field.error ? true : undefined,
    onChange: (e: { target: { value: string } }) => onChange(e.target.value),
  }
  return (
    // 여러 줄이면 라벨을 첫 줄에 맞춰 위로 정렬한다(가운데 정렬이면 라벨이 허공에 뜬다)
    <Field id={id} value={value} alignTop={multiline} {...field}>
      {multiline ? (
        <Textarea {...shared} className="min-h-16 w-full resize-y text-sm" rows={2} />
      ) : (
        <Input {...shared} className={`h-8 max-w-full text-sm ${grow ? 'w-full' : 'w-75'}`} type="text" />
      )}
    </Field>
  )
}
