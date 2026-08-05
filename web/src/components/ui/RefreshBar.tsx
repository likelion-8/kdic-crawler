/** `마지막 ○○ {시각} · [다시 확인]` 한 줄 — 화면을 최신으로 만드는 동작의 공통 UI.
 *
 * 왜 모았나: 같은 일을 하는 자리가 화면마다 다르게 생겼다(2026-08-04 사용자 지적).
 *  · 대시보드 — `마지막 갱신 2026-08-04 17:59:55` + [새로고침] 버튼(진행 시 스피너)
 *  · 파이프라인 변경 감지 — `마지막 확인 08-04 17:59 · 지금 확인`(밑줄 링크, 스피너 없음)
 *  · 같은 카드의 0건 상태 — `[지금 확인 ↻]` 버튼(유니코드 글리프)
 * 생김새·시각 형식·진행 표시가 셋 다 달랐다. 여기 하나로 모은다.
 *
 * 라벨은 남긴다 — '갱신'(화면 데이터를 다시 읽음)과 '확인'(서버가 원본을 다시 검사)은
 * 실제로 다른 일이라 같은 말로 덮으면 거짓이 된다. 통일하는 것은 **표기 방식**이지 낱말이 아니다. */
import { RefreshCw } from 'lucide-react'
import { Button } from './Button'
import { formatMonthDayTime } from '../../lib/format'

export interface RefreshBarProps {
  /** 마지막으로 최신화된 시각. 없으면 시각을 그리지 않는다(지어내지 않는다) */
  at?: string | number | null
  /** `마지막 {label}` — 기본 '갱신'. 서버 재검사류는 '확인' */
  label?: string
  /** 버튼 글자 — 기본 '새로고침'. 서버 재검사류는 '지금 확인' */
  action?: string
  pending?: boolean
  onRefresh: () => void
}

export function RefreshBar({ at, label = '갱신', action = '새로고침', pending = false, onRefresh }: RefreshBarProps) {
  return (
    <div className="flex items-center gap-2">
      {at != null && at !== '' && (
        <span className="nums text-xs text-muted-foreground">
          마지막 {label} {formatMonthDayTime(at)}
        </span>
      )}
      <Button size="sm" loading={pending} onClick={onRefresh}>
        <RefreshCw aria-hidden="true" />
        {action}
      </Button>
    </div>
  )
}
