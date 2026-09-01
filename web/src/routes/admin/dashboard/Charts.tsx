/** AD-001 대시보드 차트 5종 — 외부 차트 라이브러리 없이 CSS/SVG로 직접 그린다(의존성 추가 금지).
 *
 * 공통 접근성 규칙(CM-DF-004 09절): 그림은 role="img" + 요약 대체 텍스트를 갖고,
 * 각 데이터 점은 sr-only 목록으로 읽힌다. 색만으로 값을 전달하지 않는다.
 * ⚠ role="img" 안쪽은 접근성 트리에서 통째로 지워진다 — 데이터 점 목록은 반드시 그 바깥에 둔다.
 * 기획서에 차트 로딩·0건 상태 규격이 없어(09 issue 8) 0건은 이 파일에서 안내 문구로 처리한다.
 *
 * 눈금(Plot): 격자·축 라벨이 없으면 막대끼리 높이를 비교할 수만 있고 '얼마인지'는 못 읽는다.
 * 세로 차트는 전부 Plot으로 감싸 왼쪽 눈금 3개 + 배경 격자 3줄을 공유한다.
 *
 * 호버(ChartTip): 열마다 Radix Tooltip을 붙이면 90일 구간에서 툴팁 루트가 90개 생긴다.
 * 활성 인덱스 하나만 상태로 들고 툴팁 한 장을 옮기는 편이 싸고, 열 사이를 지날 때 깜빡이지도 않는다.
 * 툴팁은 마우스 전용 보조 수단이다 — 값 자체는 위 sr-only 목록이 이미 읽어 준다.
 *
 * 색 규칙: 보라(chart-1)는 주계열 하나에만 쓰고, 나머지 계열·트랙은 잉크 계조(foreground/20)로 둔다.
 * 화면 전체가 보라로 물들면 강조가 강조로 읽히지 않는다. */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { TIMEZONE } from '../../../lib/constants'
import { cn } from '../../../lib/utils'

/** `2026-07-20` → `07-20` (AD-001 A-3 x축 라벨 표기) */
const md = (iso: string) => iso.slice(5)

/** 비용 표기. 원천(Langfuse)이 USD 라 그대로 쓴다 — 환율을 프론트가 지어내지 않는다.
 *  질문 1건이 $0.0013 수준이라 소수 두 자리로 자르면 전부 `$0.00` 이 되므로, $1 미만은
 *  넷째 자리까지 보여준다. 서버의 _usd_text(admin_dashboard.py)와 같은 규칙이다. */
const usd = (n: number) =>
  n >= 1000 ? `$${compact(n)}` : n >= 1 ? `$${n.toFixed(2)}` : `$${n.toFixed(4)}`

/** 요일 — 주말에 질문이 꺼지는 골을 툴팁만 보고 알 수 있게 한다.
 * `2026-07-27`은 UTC 자정으로 파싱되므로 KST로 찍어야 날짜가 밀리지 않는다 */
const WEEKDAY = new Intl.DateTimeFormat('ko-KR', { timeZone: TIMEZONE, weekday: 'short' })
const dow = (iso: string) => WEEKDAY.format(new Date(iso))

/** 눈금·툴팁용 짧은 수 — 1,240,000 → 1.2M. 눈금이 길면 그래프 폭을 먹는다 */
function compact(n: number): string {
  if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(1)}M`
  if (n >= 10_000) return `${Math.round(n / 1_000)}k`
  if (n >= 1_000) return `${+(n / 1_000).toFixed(1)}k`
  return Math.round(n).toLocaleString('ko-KR')
}

/** 축 최댓값을 1·1.5·2·3·5 배수로 올린다.
 * 실측 최댓값을 그대로 천장에 쓰면 눈금이 `162 / 81 / 0`처럼 나와 눈금 노릇을 못 하고,
 * 가장 큰 막대가 늘 천장에 닿아 '꽉 찼다'는 인상까지 준다. */
function niceMax(n: number): number {
  if (!(n > 0)) return 1
  const mag = 10 ** Math.floor(Math.log10(n))
  const r = n / mag
  return (r <= 1 ? 1 : r <= 1.5 ? 1.5 : r <= 2 ? 2 : r <= 3 ? 3 : r <= 5 ? 5 : 10) * mag
}

/** 데이터가 0건일 때 카드 안에 남기는 자리. 문구는 기획서에 없어 프론트가 정했다 */
function NoData({ text }: { text: string }) {
  return <p className="py-6 text-center text-[13px] text-muted-foreground">{text}</p>
}

/** 열이 이만큼 많아지면 '촘촘한 구간'으로 본다 — 간격과 라벨 정렬이 같이 바뀐다 */
const DENSE = 30
/** 막대 사이 간격 — 6px 고정이면 90일(89칸 × 6px = 534px)에서 간격만으로 카드 폭을 넘겨
 * 막대가 통째로 0폭이 된다(실측: [90일]을 누르면 축 라벨만 남고 그래프가 사라졌다).
 * 점이 많아지면 간격부터 줄인다 — 막대를 지우는 것보다 붙이는 편이 낫다. */
const BAR_GAP = (n: number) => (n > DENSE ? 'gap-px' : 'gap-1.5')
/** 열 하나 — `min-w-px`가 없으면 `flex-1`이 0폭까지 눌려 막대가 사라진다 */
const COL = 'min-w-px flex-1'
/** x축 라벨 줄 높이. Plot의 격자 하단 여백(`bottom-5`)과 같은 값이어야 축이 맞는다 */
const X_AXIS = 'flex h-5 items-start overflow-hidden pt-1 text-[11px] whitespace-nowrap text-muted-foreground'
/** 보조 계열 — 보라를 흐리게 쓰지 않고 잉크로 내린다 */
const INK_SERIES = 'bg-foreground/20'

/** x축 라벨 솎기 — 7개 안쪽으로 줄여 라벨끼리 겹치지 않게 한다(목업은 2일 간격 격줄).
 * 촘촘한 구간은 5개까지 더 줄인다 — 마지막 라벨을 오른쪽에 못박는 만큼(아래 XAxis)
 * 직전 라벨과의 간격이 좁아져 7개로는 `07-2008-02`처럼 붙는다(실측) */
const labelStep = (n: number) => Math.ceil(n / (n > DENSE ? 5 : 7))

/** x축 라벨 줄 — 세 차트가 같은 규칙을 쓴다.
 * 촘촘한 구간에서는 마지막 라벨만 오른쪽에 붙인다: 열 폭이 6px인데 라벨은 30px이라
 * 가운데 정렬하면 라벨이 열 밖으로 흘러 옆 카드 문구와 겹친다(실측: 90일 토큰 차트). */
function XAxis({ dates, active, gap }: { dates: string[]; active: number | null; gap?: string }) {
  const step = labelStep(dates.length)
  const last = dates.length - 1
  return (
    <ul className={cn(X_AXIS, gap)} aria-hidden="true">
      {dates.map((d, i) => {
        const text = (last - i) % step === 0 ? md(d) : ''
        // 넘치는 줄은 text-align으로 못 당긴다(LTR은 시작 모서리를 고정한 채 오른쪽으로 흘린다).
        // 마지막 라벨만 오른쪽 모서리에 못박아 왼쪽으로 흐르게 한다
        const pinRight = dates.length > DENSE && i === last
        return (
          <li
            key={d}
            className={cn(COL, 'relative text-center', active === i && 'font-semibold text-foreground')}
          >
            {pinRight ? <span className="absolute top-0 right-0">{text}</span> : text}
          </li>
        )
      })}
    </ul>
  )
}

// ---------------------------------------------------------------- 공통 틀 · 툴팁

/** 세로 차트 공통 틀 — 왼쪽 눈금 3개(최댓값·절반·0) + 배경 격자 3줄.
 * children은 `relative` 안에 놓이므로 ChartTip이 이 영역을 기준으로 자리를 잡는다. */
function Plot({
  max,
  format = compact,
  children,
}: {
  max: number
  format?: (n: number) => string
  children: ReactNode
}) {
  return (
    <div className="flex min-h-36 flex-1 gap-2">
      {/* 눈금 값은 격자와 같은 정보라 스크린리더에서는 감춘다(수치는 sr-only 목록이 읽는다) */}
      <ul
        className="nums flex w-9 flex-none flex-col justify-between pb-5 text-right text-[10px] leading-none text-muted-foreground"
        aria-hidden="true"
      >
        <li>{format(max)}</li>
        <li>{format(max / 2)}</li>
        <li>0</li>
      </ul>
      <div className="relative flex min-w-0 flex-1 flex-col">
        <div className="pointer-events-none absolute inset-x-0 top-0 bottom-5 flex flex-col justify-between" aria-hidden="true">
          <span className="h-px bg-border" />
          <span className="h-px bg-border" />
          <span className="h-px bg-border" />
        </div>
        {children}
      </div>
    </div>
  )
}

/** 호버 툴팁 한 장 — `x`(0~1)는 열의 가로 위치, `y`(0~1)는 값의 높이다.
 * 카드 밖으로 새지 않게 좌우 끝에서는 기준점을 옮기고, 위로도 60%에서 멈춘다. */
function ChartTip({ x, y = 0, children }: { x: number; y?: number; children: ReactNode }) {
  const shift = x < 0.12 ? 0 : x > 0.88 ? 100 : 50
  return (
    <div
      className="pointer-events-none absolute z-10 rounded-md border bg-popover px-2.5 py-1.5 text-[11px] leading-tight whitespace-nowrap text-popover-foreground shadow-md"
      style={{
        left: `${x * 100}%`,
        bottom: `calc(${Math.min(y, 0.6) * 100}% + 10px)`,
        transform: `translateX(-${shift}%)`,
      }}
    >
      {children}
    </div>
  )
}

/** 툴팁 첫 줄 — 날짜(요일). 값보다 작고 흐리게 둔다 */
function TipDate({ iso }: { iso: string }) {
  return (
    <span className="block text-muted-foreground">
      {md(iso)} ({dow(iso)})
    </span>
  )
}

/** 전일 대비 — 늘고 주는 것에 좋고 나쁨이 없으므로 색을 입히지 않는다 */
function Delta({ diff, format }: { diff: number; format?: (n: number) => string }) {
  const show = format ?? ((n: number) => n.toLocaleString('ko-KR'))
  return (
    <span className="ml-1 font-normal text-muted-foreground">
      {diff === 0 ? '± 0' : `${diff > 0 ? '▲' : '▼'} ${show(Math.abs(diff))}`}
    </span>
  )
}

/** 열 위에 얹는 투명 히트 영역 — 막대가 짧아도 열 전체가 호버 대상이 된다 */
function hitProps(i: number, set: (i: number | null) => void) {
  return { onMouseEnter: () => set(i), onFocus: () => set(i) }
}

// ---------------------------------------------------------------- 일별 질문 수 추이

export interface TrendPoint {
  date: string
  count: number
}

export function TrendBars({ points }: { points: TrendPoint[] }) {
  const [active, setActive] = useState<number | null>(null)
  if (points.length === 0) return <NoData text="이 기간에 기록된 질문이 없습니다" />

  const max = niceMax(Math.max(...points.map((p) => p.count), 1))
  const gap = BAR_GAP(points.length)
  const hot = active === null ? null : points[active]

  return (
    <div className="flex flex-1 flex-col gap-2">
      <Plot max={max}>
        <ul
          className={cn('relative flex min-h-0 flex-1 items-end', gap)}
          role="img"
          aria-label={`일별 질문 수 추이 ${md(points[0].date)}부터 ${md(points[points.length - 1].date)}까지`}
          onMouseLeave={() => setActive(null)}
        >
          {points.map((p, i) => (
            <li
              key={p.date}
              className={cn(COL, 'flex h-full items-end justify-center rounded-t-sm', active === i && 'bg-muted')}
              {...hitProps(i, setActive)}
            >
              {/* 마지막(최신) 막대만 진한 포인트 컬러 — AD-001 A-3 목업 */}
              <span
                className={cn(
                  'w-full max-w-[22px] min-h-0.5 rounded-t-[2px] transition-colors duration-150',
                  i === points.length - 1 || active === i ? 'bg-chart-1' : INK_SERIES,
                )}
                style={{ height: `${(p.count / max) * 100}%` }}
                aria-hidden="true"
              />
            </li>
          ))}
          {hot && active !== null && (
            <ChartTip x={(active + 0.5) / points.length} y={hot.count / max}>
              <TipDate iso={hot.date} />
              <span className="nums mt-0.5 block font-semibold">
                {hot.count.toLocaleString('ko-KR')}건
                {active > 0 && <Delta diff={hot.count - points[active - 1].count} />}
              </span>
            </ChartTip>
          )}
        </ul>
        <XAxis dates={points.map((p) => p.date)} active={active} gap={gap} />
      </Plot>
      {/* 일별 수치는 role="img" 바깥에서 읽힌다 */}
      <ul className="sr-only">
        {points.map((p) => (
          <li key={p.date}>
            {md(p.date)} {p.count}건
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------- 질문 성격 도넛

export interface IntentRatio {
  informational: number
  civil_petition: number
}

/** 원 둘레 계산용 반지름 — viewBox 좌표계 값이라 CSS 토큰으로 뺄 수 없다.
 * 링은 얇게(7) 두고 가운데 값이 크게 읽히도록 한다 — 두꺼운 색 링은 지면을 색으로 덮는다 */
const DONUT_R = 26
const DONUT_C = 2 * Math.PI * DONUT_R
const DONUT_W = 7

/** 두 조각 다 실제 데이터다. 한쪽만 칠하고 나머지를 '빈 트랙'으로 두면
 * 링이 덜 채워진 게이지처럼 보이고, 가운데 수치도 한쪽 값만 말하게 된다(사용자 지적). */
const INTENT_SEGMENTS = [
  { key: 'informational', label: '정보성', arc: 'stroke-chart-1', chip: 'bg-chart-1' },
  { key: 'civil_petition', label: '민원성', arc: 'stroke-foreground/20', chip: INK_SERIES },
] as const

export function IntentDonut({ ratio }: { ratio: IntentRatio }) {
  const [active, setActive] = useState<string | null>(null)
  const pct = (n: number) => Math.max(0, Math.min(100, n))
  const segments = [
    { ...INTENT_SEGMENTS[0], value: pct(ratio.informational) },
    { ...INTENT_SEGMENTS[1], value: pct(ratio.civil_petition) },
  ]
  // 호버 전 가운데는 큰 쪽을 말한다 — 빈 채로 두면 도넛 가운데가 그냥 구멍이 된다
  const shown = segments.find((s) => s.key === active) ?? (segments[0].value >= segments[1].value ? segments[0] : segments[1])
  // 조각의 시작 각도 = 앞 조각들의 합
  let offset = 0

  return (
    <div className="flex items-center gap-5" onMouseLeave={() => setActive(null)}>
      <div className="relative size-28 flex-none">
        {/* 12시 방향에서 시작하도록 회전 */}
        <svg
          className="size-full -rotate-90"
          viewBox="0 0 72 72"
          role="img"
          aria-label={segments.map((s) => `${s.label} ${s.value}%`).join(' · ')}
        >
          {segments.map((s) => {
            const dash = (DONUT_C * s.value) / 100
            const start = offset
            offset += dash
            return (
              <circle
                key={s.key}
                className={cn(
                  'cursor-default fill-none transition-opacity duration-150',
                  s.arc,
                  active !== null && active !== s.key && 'opacity-35',
                )}
                strokeWidth={DONUT_W}
                cx="36"
                cy="36"
                r={DONUT_R}
                strokeDasharray={`${dash} ${DONUT_C}`}
                strokeDashoffset={-start}
                onMouseEnter={() => setActive(s.key)}
              />
            )
          })}
        </svg>
        {/* 가운데 글자는 HTML로 얹는다 — SVG <text>는 도넛 회전을 되돌려야 하고 두 줄도 어렵다.
            pointer-events-none이라 조각 호버를 가리지 않는다 */}
        <p className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center leading-none">
          <span className="text-[11px] text-muted-foreground">{shown.label}</span>
          <span className="nums mt-1 text-lg font-bold text-foreground">{shown.value}%</span>
        </p>
      </div>
      <ul className="flex flex-col gap-2 text-[13px]">
        {segments.map((s) => (
          <li
            key={s.key}
            className={cn(
              '-mx-1.5 flex cursor-default items-center gap-2 rounded-sm px-1.5 py-0.5',
              active === s.key && 'bg-muted',
            )}
            onMouseEnter={() => setActive(s.key)}
          >
            <span className={cn('size-2.5 rounded-[2px]', s.chip)} aria-hidden="true" />
            {s.label} {s.value}%
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------- 업무별 비중

/** 업무별 분포 — `착오송금 31% · 예금자보호 27% …` 한 줄 평문이면 어느 쪽이 큰지 읽어서 비교해야 한다.
 * 같은 값이라도 길이로 보이면 한눈에 서열이 잡힌다. 값은 막대 옆에 그대로 남긴다(색 단독 의존 금지).
 *
 * 눈금은 최댓값이 아니라 **100%가 기준**이다. 최댓값에 맞춰 늘이면 31%와 27%가 거의 같은 길이로 보여
 * 4%p 차이가 압도적 우위처럼 읽힌다 — 비중 막대는 전체 대비 얼마인지가 정보다. */
export function RatioBars({ items }: { items: { label: string; ratio: number }[] }) {
  if (items.length === 0) return <NoData text="분류된 업무가 없습니다" />
  return (
    // 격자는 li 가 아니라 ul 이 만든다 — 업무명 칸은 auto 라 **가장 긴 이름에 맞춰** 정해지고,
    // 모든 줄이 같은 폭을 공유해 막대 시작점이 맞는다. li 마다 격자를 만들면 auto 가 줄마다
    // 따로 계산돼 층이 지고, 그렇다고 고정 폭을 주면 '고객 미수령금 신청'이 잘린다.
    // li 는 display:contents 로 자기 상자를 비워 자식 셋을 부모 격자에 그대로 넘긴다.
    <ul className="grid grid-cols-[auto_1fr_38px] items-center gap-x-2.5 gap-y-1.5 text-[12px]">
      {items.map((b) => (
        <li key={b.label} className="contents">
          <span className="whitespace-nowrap text-muted-foreground">{b.label}</span>
          <span className="block h-1.5 overflow-hidden rounded-full bg-muted">
            <span
              className={cn('block h-full rounded-full', INK_SERIES)}
              style={{ width: `${Math.min(b.ratio, 100)}%` }}
              aria-hidden="true"
            />
          </span>
          <span className="nums text-right text-foreground">{b.ratio}%</span>
        </li>
      ))}
    </ul>
  )
}

// ---------------------------------------------------------------- 단계별 평균 응답시간(웹 요청 순서)

export interface LatencyStage {
  name: string
  avg_ms: number
}

/** `total`은 서버가 준 평균 총 응답시간(avg_total_ms)이다. 단계 합과 다를 수 있고,
 * 그 차이가 곧 '어느 단계에도 안 잡힌 시간'이라 비중을 total 기준으로 낸다 —
 * 합계로 나누면 항상 100%가 되어 그 공백이 사라진다. */
export function StageBars({
  stages,
  total,
  sampleCount,
}: {
  stages: LatencyStage[]
  total: number
  /** 이 평균을 낸 실행 건수. 없으면 2건 평균과 300건 평균이 같은 무게로 읽힌다 */
  sampleCount: number
}) {
  const [active, setActive] = useState<string | null>(null)
  if (stages.length === 0) return <NoData text="측정된 단계 기록이 없습니다" />

  const max = Math.max(...stages.map((s) => s.avg_ms), 1)
  const base = Math.max(total, 1)
  // 강조 기준이 기획서에 없어(09 issue 30) 목업과 같은 결과가 되도록 상위 2개로 정했다
  const strong = new Set(
    [...stages]
      .sort((a, b) => b.avg_ms - a.avg_ms)
      .slice(0, 2)
      .map((s) => s.name),
  )

  return (
    <div className="flex flex-col gap-2">
      <ul className="flex flex-col" onMouseLeave={() => setActive(null)}>
        {stages.map((s) => (
          <li
            key={s.name}
            className={cn(
              '-mx-1.5 grid grid-cols-[86px_1fr_64px_44px] items-center gap-2.5 rounded-sm px-1.5 py-1',
              active === s.name && 'bg-muted',
            )}
            onMouseEnter={() => setActive(s.name)}
          >
            <span className="truncate text-[11px] text-muted-foreground">{s.name}</span>
            <span className="block h-2 overflow-hidden rounded-[2px] bg-muted">
              <span
                className={cn('block h-full min-w-0.5', strong.has(s.name) ? 'bg-chart-1' : INK_SERIES)}
                style={{ width: `${(s.avg_ms / max) * 100}%` }}
                aria-hidden="true"
              />
            </span>
            <span className="nums text-right text-[11px] text-foreground">{s.avg_ms.toLocaleString('ko-KR')}ms</span>
            <span className="nums text-right text-[11px] text-muted-foreground">
              {((s.avg_ms / base) * 100).toFixed(0)}%
            </span>
          </li>
        ))}
      </ul>
      {/* 서버가 준 총 응답시간. 단계 합과 벌어지면 그 차이가 미계측 구간이다.
          모수를 같은 줄 앞에 세운다 — 숫자를 읽는 자리에서 몇 건짜리 평균인지 함께 보여야 한다 */}
      <p className="nums flex justify-between border-t pt-2 text-[11px] text-muted-foreground">
        <span>
          <span className="mr-2.5 text-foreground/70">{sampleCount.toLocaleString('ko-KR')}건</span>
          평균 총 응답시간
        </span>
        <strong className="font-semibold text-foreground">{total.toLocaleString('ko-KR')}ms</strong>
      </p>
    </div>
  )
}

// ---------------------------------------------------------------- 일별 토큰 소비량(누적)

export interface TokenPoint {
  date: string
  input: number
  output: number
}

export function TokenStack({ points }: { points: TokenPoint[] }) {
  const [active, setActive] = useState<number | null>(null)
  if (points.length === 0) return <NoData text="이 기간에 기록된 토큰 사용량이 없습니다" />

  const max = niceMax(Math.max(...points.map((p) => p.input + p.output), 1))
  const gap = BAR_GAP(points.length)
  const hot = active === null ? null : points[active]

  return (
    <div className="flex flex-col gap-2">
      <ul className="flex gap-3.5 text-[11px] text-muted-foreground">
        <li className="flex items-center gap-1.5">
          <span className={cn('size-2.5 rounded-[2px]', INK_SERIES)} aria-hidden="true" />
          입력
        </li>
        <li className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-[2px] bg-chart-1" aria-hidden="true" />
          출력
        </li>
      </ul>
      <Plot max={max}>
        <ul
          className={cn('relative flex min-h-0 flex-1 items-end', gap)}
          role="img"
          aria-label="일별 토큰 소비량 (입력·출력 누적)"
          onMouseLeave={() => setActive(null)}
        >
          {points.map((p, i) => {
            // 무트래픽 날(입력·출력 0)에 0으로 나누지 않는다 — flexBasis가 NaN%가 된다
            const total = Math.max(p.input + p.output, 1)
            return (
              <li
                key={p.date}
                className={cn(COL, 'flex h-full items-end justify-center rounded-t-sm', active === i && 'bg-muted')}
                {...hitProps(i, setActive)}
              >
                <span
                  className="flex w-full max-w-8 min-h-0.5 flex-col overflow-hidden rounded-t-[2px]"
                  style={{ height: `${(total / max) * 100}%` }}
                  aria-hidden="true"
                >
                  {/* 위=출력(진), 아래=입력(연) — AD-001 A-6 목업 순서 */}
                  <span className="block flex-none bg-chart-1" style={{ flexBasis: `${(p.output / total) * 100}%` }} />
                  <span
                    className={cn('block flex-none', INK_SERIES)}
                    style={{ flexBasis: `${(p.input / total) * 100}%` }}
                  />
                </span>
              </li>
            )
          })}
          {hot && active !== null && (
            <ChartTip x={(active + 0.5) / points.length} y={(hot.input + hot.output) / max}>
              <TipDate iso={hot.date} />
              <span className="nums mt-0.5 block font-semibold">합계 {compact(hot.input + hot.output)}</span>
              <span className="nums block text-muted-foreground">
                입력 {compact(hot.input)} · 출력 {compact(hot.output)}
              </span>
            </ChartTip>
          )}
        </ul>
        <XAxis dates={points.map((p) => p.date)} active={active} gap={gap} />
      </Plot>
      {/* 일별 수치는 role="img" 바깥에서 읽힌다 */}
      <ul className="sr-only">
        {points.map((p) => (
          <li key={p.date}>
            {md(p.date)} 입력 {p.input.toLocaleString('ko-KR')} · 출력 {p.output.toLocaleString('ko-KR')}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ---------------------------------------------------------------- 일별 비용 추이(선)

export interface CostPoint {
  date: string
  usd: number
}

/** 선은 0 기준으로 그린다. 최저값을 바닥으로 삼으면 $0.0098↔$0.0124 같은 잔변동이
 * 절벽처럼 보여 비용이 폭증한 것처럼 읽힌다 — 눈금 0이 있어야 진폭을 제 크기로 본다. */
export function CostLine({ points, caption }: { points: CostPoint[]; caption: string }) {
  const [active, setActive] = useState<number | null>(null)
  if (points.length === 0) return <NoData text="이 기간에 기록된 비용이 없습니다" />

  // 천장의 하한을 1(=$1)로 두면 $0.003 짜리 선이 바닥에 붙어 아무것도 안 보인다.
  // 실측 최댓값이 작으면 그 값 기준으로 눈금을 잡는다.
  const max = niceMax(Math.max(...points.map((p) => p.usd), 0.0001))
  // viewBox를 0~100 정규 좌표로 두고 preserveAspectRatio="none"으로 늘인다 →
  // SVG 안의 x%와 HTML 오버레이의 left%가 같은 값이 되어 호버 표시가 선 위에 정확히 얹힌다.
  // 늘이면 선 굵기도 같이 찌그러지므로 vector-effect로 굵기만 고정한다.
  //
  // x는 막대 차트와 같은 '열의 가운데'다. 양 끝을 0·100에 붙이면(i/(n-1)) 점이 라벨보다
  // 반 칸씩 왼쪽으로 밀려 선 전체가 날짜와 어긋나 보인다 — 축이 같은 열을 쓰므로 좌표도 같아야 한다.
  const at = (i: number) => ((i + 0.5) / points.length) * 100
  const yOf = (v: number) => 100 - (v / max) * 100
  const line = points.map((p, i) => `${at(i)},${yOf(p.usd)}`).join(' ')
  const hot = active === null ? null : points[active]

  return (
    <div className="flex flex-col gap-2">
      <Plot max={max} format={usd}>
        <div
          className="relative min-h-0 flex-1"
          onMouseLeave={() => setActive(null)}
          role="img"
          aria-label={`일별 비용 추이. 최고 ${usd(max)}`}
        >
          {/* absolute inset-0 — `h-full`은 부모 높이가 auto라 풀리지 않고, 그러면 SVG가
              viewBox 비율(1:1)로 스스로 커져 폭만큼 높아진다(실측 396px). 박스에 못박는다 */}
          <svg className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            {/* 면적은 선의 양 끝에서 바닥으로 내린다 — 0·100으로 벌리면 선보다 넓어져 끝이 들뜬다 */}
            <polygon className="fill-chart-1/10" points={`${at(0)},100 ${line} ${at(points.length - 1)},100`} />
            <polyline
              className="fill-none stroke-chart-1"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
              points={line}
            />
          </svg>
          {/* 호버 표시 — 세로 안내선 + 그 점 하나. 점을 상시로 찍으면 90일에서 선이 덩어리가 된다 */}
          {hot && active !== null && (
            <>
              <span
                className="pointer-events-none absolute inset-y-0 w-px bg-border"
                style={{ left: `${at(active)}%` }}
                aria-hidden="true"
              />
              <span
                className="pointer-events-none absolute size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-chart-1 ring-2 ring-card"
                style={{ left: `${at(active)}%`, top: `${yOf(hot.usd)}%` }}
                aria-hidden="true"
              />
            </>
          )}
          {/* 히트 영역 — 선 위 몇 픽셀을 정확히 짚게 하지 않는다. 열 전체가 대상이다 */}
          <ul className="absolute inset-0 flex" aria-hidden="true">
            {points.map((p, i) => (
              <li key={p.date} className={COL} {...hitProps(i, setActive)} />
            ))}
          </ul>
          {hot && active !== null && (
            <ChartTip x={at(active) / 100} y={hot.usd / max}>
              <TipDate iso={hot.date} />
              <span className="nums mt-0.5 block font-semibold">
                {usd(hot.usd)}
                {active > 0 && <Delta diff={hot.usd - points[active - 1].usd} format={usd} />}
              </span>
            </ChartTip>
          )}
        </div>
        <XAxis dates={points.map((p) => p.date)} active={active} />
      </Plot>
      <ul className="sr-only">
        {points.map((p) => (
          <li key={p.date}>
            {md(p.date)} {usd(p.usd)}
          </li>
        ))}
      </ul>
      <p className="text-[11px] text-muted-foreground">{caption}</p>
    </div>
  )
}
