/** 슬라이더 — CM-DF-001 04절: "연속 값. 눈금으로 '방향'을 반드시 드러낼 것".
 * 목업 눈금 예: `0  의미 검색 ────── 1  키워드 검색` → scaleStart/scaleEnd로 주입.
 * ponytail: 네이티브 <input type=range> 유지 — 라벨 연결(htmlFor)·좌우 화살표 키 조작이
 * 브라우저 기본으로 검증돼 있다(Radix Slider는 thumb에 라벨을 못 잇는다). 룩만 shadcn과 맞췄다. */
import { useId } from 'react'
import type { CSSProperties } from 'react'
import { Field } from './Field'
import type { FieldOptions } from './Field'

export interface SliderProps extends FieldOptions {
  value: number
  onChange: (value: number) => void
  min?: number
  max?: number
  step?: number
  /** 왼쪽 끝의 의미 (예: '의미 검색') */
  scaleStart?: string
  /** 오른쪽 끝의 의미 (예: '키워드 검색') */
  scaleEnd?: string
  disabled?: boolean
}

export function Slider({
  value,
  onChange,
  min = 0,
  max = 1,
  step = 0.1,
  scaleStart,
  scaleEnd,
  disabled,
  ...field
}: SliderProps) {
  const id = useId()
  const filled = max === min ? 0 : ((value - min) / (max - min)) * 100

  return (
    <Field id={id} value={value} {...field}>
      <div className="inline-flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <input
            id={id}
            // 손잡이는 잉크 테두리 + 그림자 없음. 보라는 채움 트랙(아래 style)에만 남긴다
            className="h-4 w-40 cursor-pointer appearance-none bg-transparent outline-none disabled:cursor-not-allowed disabled:opacity-50 [&::-moz-range-thumb]:size-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border [&::-moz-range-thumb]:border-foreground/60 [&::-moz-range-thumb]:bg-background [&::-webkit-slider-thumb]:size-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-foreground/60 [&::-webkit-slider-thumb]:bg-background"
            type="range"
            value={value}
            min={min}
            max={max}
            step={step}
            disabled={disabled}
            // 채움 트랙 — 토큰 CSS 변수로만 그린다(hex 금지).
            // ⚠ tailwind.css의 @theme inline 변수는 :root에 실재하지 않는다 — tokens.css 변수만 쓸 것
            style={
              {
                background: `linear-gradient(to right, var(--color-primary) ${filled}%, var(--color-track) ${filled}%) center / 100% 6px no-repeat`,
                borderRadius: '9999px',
              } as CSSProperties
            }
            aria-describedby={field.error ? `${id}-error` : undefined}
            onChange={(e) => onChange(Number(e.target.value))}
          />
          <span className="text-sm tabular-nums">{value}</span>
        </div>
        {/* 눈금 = 방향 표시. 색만으로는 방향을 알 수 없으므로 항상 글자로 */}
        {(scaleStart || scaleEnd) && (
          <div className="flex w-40 justify-between text-xs text-muted-foreground">
            <span>
              {min} {scaleStart}
            </span>
            <span>
              {max} {scaleEnd}
            </span>
          </div>
        )}
      </div>
    </Field>
  )
}
