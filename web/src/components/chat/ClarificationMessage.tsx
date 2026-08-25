/** 되묻기 — CB-005 / CB-DF-001 Type 5.
 *
 * 되묻기 단계에는 출처·서류·신청 페이지가 붙지 않는다(검색 전에 되묻기 때문).
 * 선택지는 **서버가 준다**(B-01) — 상수로 박아두면 선택지가 바뀌어도 질문만 바뀌고
 * 버튼은 그대로 남는 버그가 된다. 현재 축은 업무(src/clarify.py CLARIFY_OPTIONS).
 *
 * 답한 되묻기(2026-08-25): 사용자가 한 번 고르면 버튼 전부를 비활성으로 두고 고른 것만
 * 채움색·aria-pressed 로 남긴다. 숨기지 않는 이유는 "내가 뭘 골랐는지"가 대화 기록으로
 * 보여야 해서. 활성으로 두면 위로 스크롤해 옛 되묻기를 다시 눌렀을 때 업무명 한 단어가
 * 맥락 없이 새 메시지로 나간다 — 재작성기는 직전 턴이 되묻기일 때만 합성하므로 파편 질문이
 * 검색·캐시까지 흘러든다(query_cache 에 "채무조정"·"미수령금 찾기" 행이 쌓여 있던 원인). */
import type { ClarificationOption } from '../../lib/api/types'
import { Button } from '../ui'
import { cn } from '@/lib/utils'
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
  /** 이미 답한 되묻기 — 버튼 전부 비활성. 다음 턴이 존재하면 true */
  answered?: boolean
  /** 사용자가 고른 라벨(버튼 클릭으로 답한 경우). 채움색 + aria-pressed 로 표시 */
  selectedLabel?: string
  /** 전송 중 등 일시적으로 못 누르는 상태 — 선택 표시 없이 비활성만 */
  disabled?: boolean
}

export function ClarificationMessage({
  question,
  options,
  at,
  onSelect,
  answered = false,
  selectedLabel,
  disabled = false,
}: ClarificationMessageProps) {
  const locked = answered || disabled
  return (
    <Bubble variant="bot" at={at}>
      <BubbleText text={question} />
      {/* 640px 이하에서는 세로로 쌓인다 — 목업 220×44 2개가 좁은 폭에서 깨진다(CB-DF-004 §7 I-17).
          버튼 간 16px(CB-005 3.2) · 높이 44px 이상(CM-DF-004 09절) 유지 */}
      {options.length > 0 && (
        <div
          className={cn('mt-4 flex flex-wrap gap-4', answered && 'opacity-60')}
          role={answered ? 'group' : undefined}
          aria-label={answered ? '답한 선택지' : undefined}
        >
          {options.map((option) => {
            const selected = answered && option.label === selectedLabel
            return (
              <Button
                key={option.label}
                variant={selected ? 'primary' : 'secondary'}
                className={cn(
                  'h-auto min-h-11 flex-1 basis-[200px] whitespace-normal py-2 font-bold max-sm:basis-full',
                  !locked && 'hover:bg-muted',
                  // 고른 버튼은 비활성이어도 흐려지지 않게 — 그룹 전체가 이미 opacity-60 이다
                  selected && 'disabled:opacity-100',
                )}
                disabled={locked}
                aria-pressed={answered ? selected : undefined}
                onClick={() => onSelect(option.label)}
              >
                {option.label}
              </Button>
            )
          })}
        </div>
      )}
    </Bubble>
  )
}
