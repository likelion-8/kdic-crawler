/** AD-006 표기용 짧은 KST 포맷.
 * 시각 표기는 반드시 lib/format.ts를 거친다(브라우저 타임존과 무관하게 KST 고정) — 여기서는
 * 그 결과를 목업 포맷(`07-30 14:20`)으로 자르기만 한다.
 * 이 화면에서만 쓰는 포맷이라(AD-006 L5) 공통 포맷터로 올리지 않았다. */
import { formatMonthDayTime } from '../../../lib/format'

/** `07-30 14:20` — 이력 표 '시각' 열 */
export function formatShortKst(value: string): string {
  // 표기 정본은 lib/format.formatMonthDayTime 이다 — 같은 문자열을 두 번 구현하지 않는다.
  return formatMonthDayTime(value)
}
