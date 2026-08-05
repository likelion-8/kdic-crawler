/** 역할 확인 되묻기 — CB-005 / CB-DF-001 Type 5.
 *
 * 되묻기 단계에는 출처·서류·신청 페이지가 붙지 않는다(검색 전에 되묻기 때문).
 * 선택지는 **서버가 준다**(B-01 확정 2026-08-05) — 예전에는 착오송금 2개를 여기 상수로
 * 박아뒀는데, 역할축이 41개라 다른 축이 오면 질문만 바뀌고 버튼은 그대로 남는 버그가 된다. */
import type { ClarificationOption } from '../../lib/api/types'
import { Button } from '../ui'
import { Bubble, BubbleText } from './Bubble'

export interface ClarificationMessageProps {
  /** 되묻기 문구. 앞 문장은 주제마다 달라지는 서버 생성 문구다(CB-005 3.4) */
  question: string
  /** 서버가 준 역할 선택지. 비면 버튼을 그리지 않는다 */
  options: ClarificationOption[]
  /** 보낸/받은 시각 — 없으면 시각을 그리지 않는다 */
  at?: string | number
  /** 클릭한 역할 라벨을 그대로 일반 메시지로 보낸다 (CB-005 3.7-1) */
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
