/** 전역 표기 포맷터.
 *
 * 🔴 모든 시각은 브라우저 타임존과 무관하게 KST 고정 표기다 (PRD-02 §3-f).
 * `new Date().toLocaleString()`을 화면에서 직접 쓰지 말고 반드시 이 파일을 거친다.
 * 대상 표기는 '사람이 읽는 이름 + (ID)' — ID 단독 노출 금지 (AD-011 Description 3). */
import { TIMEZONE } from './constants'

/** 파싱 실패 시 표시값. 표에서 빈칸으로 두면 열이 밀려 보여 하이픈으로 채운다 */
const INVALID = '—'

/** hourCycle 'h23' — 로케일에 따라 자정을 24:00으로 찍는 차이를 막는다 */
const KST = new Intl.DateTimeFormat('en-US', {
  timeZone: TIMEZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
})

type Instant = string | number | Date

function partsOf(value: Instant): Record<string, string> | null {
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return null
  const found: Record<string, string> = {}
  for (const p of KST.formatToParts(d)) found[p.type] = p.value
  return found
}

/** `2026-08-01` */
export function formatDate(value: Instant): string {
  const p = partsOf(value)
  return p ? `${p.year}-${p.month}-${p.day}` : INVALID
}

/** `10:42` — 목록 표의 '시각' 열 (AD-010 위험 작업 기록·AD-011 이벤트 목록) */
export function formatTime(value: Instant): string {
  const p = partsOf(value)
  return p ? `${p.hour}:${p.minute}` : INVALID
}

/** `오후 3:24` — 말풍선 시각.
 *
 * 관리자 화면의 `formatTime`(24시간 `15:24`)과 일부러 다르다. 이쪽은 대민 화면이라
 * 오전/오후 표기가 읽기 편하고, 목록의 열이 아니라 문장 옆 부가 정보라 앞자리 0을 붙이지 않는다.
 * 다른 포맷터와 같이 KST 고정이다(PRD-02 §3-f) — 사용자의 브라우저 타임존을 따르지 않는다. */
const KST_CLOCK = new Intl.DateTimeFormat('ko-KR', {
  timeZone: TIMEZONE,
  hour: 'numeric',
  minute: '2-digit',
  hour12: true,
})

export function formatClock(value: Instant): string {
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return INVALID
  const found: Record<string, string> = {}
  for (const p of KST_CLOCK.formatToParts(d)) found[p.type] = p.value
  // 로케일이 붙이는 공백·순서에 기대지 않고 직접 조립한다
  return `${found.dayPeriod} ${found.hour}:${found.minute}`
}

/** `2026-08-01 10:42:18` */
export function formatDateTime(value: Instant): string {
  const p = partsOf(value)
  return p ? `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}` : INVALID
}

/** `08-01 10:42` — 목록·헤더처럼 자리가 좁고 '올해 안'이 자명한 곳의 시각.
 * (원래 pipeline/api.ts에 있었다 — 표기 포맷은 이 파일 하나로 모은다) */
export function formatMonthDayTime(value: Instant): string {
  const date = formatDate(value)
  return date === INVALID ? date : `${date.slice(5)} ${formatTime(value)}`
}

/** `2026-08-01 10:42:18 KST` — 상세 패널 메타행 표기 (AD-011 3-4 원문) */
export function formatKst(value: Instant): string {
  const s = formatDateTime(value)
  return s === INVALID ? s : `${s} KST`
}

/** `착오송금 반환지원 안내 (PG-0142)` — 대상 표기 규칙 (PRD-02 §3-f) */
export function formatTarget(name: string, id: string): string {
  return `${name} (${id})`
}

/** `27분 12초` · 1시간 이상이면 `7시간 59분`.
 * 헤더 세션 잔여 표기(`세션 만료까지 27분 12초`, AD-010 2-1)에 쓴다.
 * 시간 단위 문구는 기획서에 예시가 없어 같은 어투로 확장했다. */
export function formatRemaining(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  return h > 0 ? `${h}시간 ${m}분` : `${m}분 ${s}초`
}
