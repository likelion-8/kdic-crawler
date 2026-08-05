/** 빈 상태 — CM-DF-001 07절.
 * "무엇이 없는지 + 다음 행동을 함께 제시한다. '결과 없음'만 두지 않는다" — 그래서 action을 권장한다. */
import type { ReactNode } from 'react'
import { Inbox } from 'lucide-react'

export interface EmptyStateProps {
  /** 목업 문구: '조건에 맞는 결과가 없습니다' */
  title: string
  /** 다음 행동 — 보통 <Button variant="secondary" size="sm">필터 초기화</Button> */
  action?: ReactNode
}

export function EmptyState({ title, action }: EmptyStateProps) {
  return (
    // 점선 테두리·후광 원 없이 회색 인셋 한 장 + 중립 아이콘.
    // 폭은 자리를 그대로 채운다 — `max-w-90 mx-auto`로 360px 상자를 가운데 띄우면
    // 넓은 카드·표 안에서 회색 딱지가 동동 뜬 것처럼 보인다(사용자 지적).
    // 글자는 가운데 정렬을 유지해 넓어져도 중심이 흐트러지지 않는다.
    <div className="flex w-full flex-col items-center justify-center gap-2.5 rounded-md bg-muted/50 px-4 py-8 text-center">
      <Inbox className="size-5 text-muted-foreground" aria-hidden="true" />
      <p className="text-sm text-muted-foreground">{title}</p>
      {action}
    </div>
  )
}
