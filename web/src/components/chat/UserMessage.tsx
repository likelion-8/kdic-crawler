/** 사용자 말풍선 — CB-002 마커 1 "오른쪽 정렬, 아바타도 오른쪽에 배치". */
import { Bubble, BubbleText } from './Bubble'

export interface UserMessageProps {
  text: string
  /** 보낸/받은 시각 — 없으면 시각을 그리지 않는다 */
  at?: string | number
}

export function UserMessage({ text, at }: UserMessageProps) {
  return (
    <Bubble variant="user" at={at}>
      <BubbleText text={text} />
    </Bubble>
  )
}
