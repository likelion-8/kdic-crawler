/** AD-006 표기용 짧은 KST 포맷.
 * 시각 표기는 반드시 lib/format.ts를 거친다(브라우저 타임존과 무관하게 KST 고정) — 여기서는
 * 그 결과를 목업 포맷(`07-30 14:20` · `08-04(월) 04:00`)으로 자르기만 한다.
 * 두 포맷 모두 기획서에 이 화면에서만 나와(AD-006 L5) 공통 포맷터로 올리지 않았다. */
import { formatDate, formatMonthDayTime } from '../../../lib/format'

const INVALID = '—'
const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토']

/** `07-30 14:20` — 이력 표 '시각' 열 */
export function formatShortKst(value: string): string {
  // 표기 정본은 lib/format.formatMonthDayTime 이다 — 같은 문자열을 두 번 구현하지 않는다.
  // 이 이름은 formatCheckKst(요일 병기)가 계속 쓴다.
  return formatMonthDayTime(value)
}

/** `08-04(월) 04:00` — 헤더 '다음 자동 확인' */
export function formatCheckKst(value: string): string {
  const date = formatDate(value)
  if (date === INVALID) return INVALID
  const [y, m, d] = date.split('-').map(Number)
  // UTC로 만들어 요일만 센다 — 이미 KST로 확정된 날짜라 오프셋이 다시 끼어들면 안 된다
  const weekday = WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()]
  const short = formatShortKst(value)
  return `${short.slice(0, 5)}(${weekday}) ${short.slice(6)}`
}
