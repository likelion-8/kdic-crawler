/** 되묻기 — CB-005 / CB-DF-001 Type 5.
 *
 * 되묻기 단계에는 출처·서류·신청 페이지가 붙지 않는다(검색 전에 되묻기 때문).
 * 선택지는 **서버가 준다**(B-01) — 상수로 박아두면 선택지가 바뀌어도 질문만 바뀌고
 * 버튼은 그대로 남는 버그가 된다. 현재 축은 업무(src/clarify.py CLARIFY_OPTIONS). */
import type { ClarificationOption } from '../../lib/api/types'
import { Button } from '../ui'
import { Bubble, BubbleText } from './Bubble'

export interface ClarificationMessageProps {
  /** 되묻기 문구. 서버가 내려준 문구를 그대로 쓴다(CB-005) */
  question: string
  /** 서버가 준 선택지. 비면 버튼을 그리지 않는다 */
  options: ClarificationOption[]
  /** 보낸/받은 시각 — 없으면 시각을 그리지 않는다 */
  at?: string | number
  /** 클릭한 라벨을 그대로 일반 메시지로 보낸다 (CB-005) */
  onSelect: (label: string) => void
}

export function ClarificationMessage({ question, options, at, onSelect }: ClarificationMessageProps) {
  return (
    <Bubble variant="bot" at={at}>
      <BubbleText text={question} />
      {/* 640px 이하에서는 세로로 쌓인다 — 목업 220×44 2개가 좁은 폭에서 깨진다(CB-DF-004 §7 I-17).
          버튼 간 16px(CB-005 3.2) · 높이 44px 이상(CM-DF-004 09절) 유지 */}
      {options.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-4">
          {options.map((option) => (
            <Button
              key={option.label}
              variant="secondary"
              className="h-auto min-h-11 flex-1 basis-[200px] whitespace-normal py-2 font-bold hover:bg-muted max-sm:basis-full"
              onClick={() => onSelect(option.label)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      )}
    </Bubble>
  )
}
