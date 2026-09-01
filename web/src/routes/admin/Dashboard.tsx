/** AD-001 대시보드 (운영 모니터링).
 *
 * 구성(AD-001 A-1 목업 순서 고정 · 5구역): 상태 칩 → KPI 4종 →
 * 일별 질문 수 추이 · 질문 성격/업무 분포 → 단계별 평균 응답시간(웹 요청 순서) → 리소스 모니터링.
 * 상시 확인 지표 5종(CM-DF-004 10절)은 **그리지 않는다**(2026-08-04 팀 결정).
 * 정책 원문이 "임계치를 넘으면 대시보드 배너로 드러냅니다" 한 줄뿐이라 임계치 값이 어디에도 없고,
 * 5종 중 '요청 제한 초과'·'링크 점검 실패'는 백엔드에 데이터 원천 자체가 없다. 기준 없이 경고를
 * 띄우면 운영자가 근거 없는 빨간불을 보게 되므로, 임계치가 확정될 때까지(P3) 화면에서 내렸다.
 *
 * 셸(GNB·헤더·세션)은 app/AdminLayout.tsx가 그린다. 여기서 다시 그리지 않는다.
 * 목업의 숫자는 예시이므로 전부 API 응답으로 렌더한다.
 *
 * 갱신 정책: 기획서에 폴링 주기가 없다(09 issue 7). 자동 폴링을 넣지 않고
 * [새로고침]과 마지막 갱신 시각만 둔다 — 켜 두기만 해도 호출이 나가는 화면을 만들지 않는다. */
import { Fragment, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Loading, RefreshBar, SectionError } from '../../components/ui'
import { cn } from '../../lib/utils'
import { apiRequest } from '../../lib/api/client'
import { formatDate, formatTime } from '../../lib/format'
import { CostLine, IntentDonut, RatioBars, StageBars, TokenStack, TrendBars } from './dashboard/Charts'
import type { CostPoint, IntentRatio, LatencyStage, TokenPoint, TrendPoint } from './dashboard/Charts'

/** 기간 선택 3종 — AD-001 A-3 `기간 : 7일 | 30일 | 90일` */
const RANGES = [7, 30, 90] as const
type Range = (typeof RANGES)[number]

/** 상태 칩의 실패 종류별 문구와 이동처 (AD-001 A-2).
 * 답변 실패 → 대화 로그(AD-005) 실패 필터 / 파이프라인 실패 → AD-004.
 *
 * 종류를 나눠 각각 링크를 다는 이유는 둘이 같은 날 겹칠 수 있어서다. 한 숫자·한 링크였을
 * 때는 파이프라인이 실패한 날 답변 실패가 통째로 가려졌다.
 *
 * 쿼리 키·값은 AD-005 가 읽는 이름이어야 한다(LogFilters·LogStatus). 종전 `?result=fail` 은
 * 그런 필터가 없어 조용히 무시됐고, 칩이 '실패 3건'이라 해 놓고 137건 전체 목록을 열었다. */
const FAILURE_KIND: Record<string, { label: string; to: string }> = {
  ERROR_RATE: { label: '답변 실패', to: '/admin/logs?status=FAILED' },
  PIPELINE: { label: '파이프라인 실패', to: '/admin/pipeline' },
}

/** 대시보드 API는 CM-DF-003 04절에 없다(09 issue D절).
 * mocks/handlers/extra/ad-dash-activity.ts가 정의한 모양을 그대로 옮겼다. */
/**
 * 할 일 — 대시보드를 '지표판'이 아니라 '시작점'으로 만드는 값(AD-DF-000 관리자 작업 흐름 ①).
 * target 은 이 건수를 보여줄 화면과 필터라, 카드를 누르면 서버가 센 것과 같은 목록이 열린다.
 * count 가 0 이어도 항목을 지우지 않는다 — 사라지면 '없는 것'과 '못 센 것'이 구분되지 않는다.
 */
interface DashboardTodo {
  key: 'FEEDBACK_DOWN' | 'PIPELINE_OPEN' | 'GATE_FAILED'
  label: string
  count: number
  target: { screen: 'logs' | 'pipeline' | 'evaluations'; filter: Record<string, string> }
}

interface DashboardSummary {
  generated_at: string
  todos: DashboardTodo[]
  /** errors 는 건수가 0 인 종류를 싣지 않는다 — 비면 level 이 OK 다 */
  service: { level: 'OK' | 'ERROR'; errors: { key: string; count: number }[] }
  kpi: {
    pages: number
    chunks: number
    questions_today: number
    avg_latency_ms: number
    pipeline: { status: string; last_run_at: string }
  }
  distribution: { intent: IntentRatio; business: { label: string; ratio: number }[] }
}

/** 단계별 평균 응답시간. summary(오늘 고정)와 달리 기간을 고른다.
 *  sample_count 는 이 평균을 낸 실행 건수 — 전 구간을 다 돈 질문만 모수라
 *  KPI '평균 응답시간'(오늘 전체 질문)과 값이 다르다. */
interface LatencyResponse {
  range: number
  sample_count: number
  avg_total_ms: number
  stages: LatencyStage[]
}

interface TrendResponse {
  range: number
  points: TrendPoint[]
}

interface ResourceResponse {
  range: number
  tokens: TokenPoint[]
  cost: CostPoint[]
  cost_caption: string
  today: { tokens_text: string; cost_text: string; concurrency_text: string; gpu_text: string }
  /** 항목별 비중. share 가 null 이면 그 단계는 단가가 등록되지 않아 비용을 못 매긴 것이다
   *  (amount_text 가 토큰 수 + 그 사실을 적는다). 0% 로 그리면 '안 썼다'로 읽힌다. */
  cost_breakdown: { label: string; amount_text: string; share: number | null }[]
}

/** 상태 표기 공통 — 채운 알약 대신 선행 점 + 글자. 색은 점이, 뜻은 글자가 나른다 */
const STATUS = 'nums inline-flex items-center gap-1.5 text-[13px] font-medium'

/** KPI 값의 단위 — 숫자(굵게)와 단위(작고 흐리게)를 분리해 자릿수가 주인공이 되게 한다 */
function Unit({ children }: { children: ReactNode }) {
  return <span className="text-sm font-normal text-muted-foreground">{children}</span>
}

/** 기간·뷰 전환. 목업은 `7일 | 30일 | 90일` 평문이라 컨트롤 형태가 없어(09 issue 6)
 * shadcn Tabs 룩의 세그먼트 + aria-pressed로 현재 값을 알린다(색 단독 의존 금지). */
function Segmented<T extends string | number>({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: T
  options: { value: T; label: string }[]
  onChange: (value: T) => void
}) {
  return (
    <div className="inline-flex items-center gap-1.5" role="group" aria-label={label}>
      <span className="text-xs text-muted-foreground">{label}</span>
      <div className="inline-flex items-center rounded-md bg-muted p-[3px]">
        {options.map((o) => (
          <button
            key={String(o.value)}
            type="button"
            aria-pressed={o.value === value}
            className={cn(
              'inline-flex h-7 items-center rounded-[3px] px-2.5 text-[13px] font-medium whitespace-nowrap transition-colors duration-200 outline-none focus-visible:ring-2 focus-visible:ring-ring',
              o.value === value ? 'bg-background font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground',
            )}
            onClick={() => onChange(o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}

/** KPI 한 칸 — 코너 아이콘 없이 라벨 한 줄 + 수치. 숫자가 주인공이다 */
/** 서버 todos[].target.screen → 라우트. 필터는 그대로 쿼리로 넘겨 대시보드가 센 것과 같은 목록이 열리게 한다 */
const TODO_ROUTE: Record<DashboardTodo['target']['screen'], string> = {
  logs: '/admin/logs',
  pipeline: '/admin/pipeline',
  evaluations: '/admin/evaluation',
}
function todoHref(t: DashboardTodo): string {
  const q = new URLSearchParams(t.target.filter).toString()
  return q ? `${TODO_ROUTE[t.target.screen]}?${q}` : TODO_ROUTE[t.target.screen]
}

function KpiCard({ label, value }: { label: string; value: ReactNode }) {
  return (
    <>
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="nums text-2xl leading-tight font-bold tracking-tight text-foreground">{value}</span>
    </>
  )
}

/** KPI 링크 겉면 — 칸 전체가 클릭 대상. 카드가 아니라 스펙 시트의 한 칸이라 보더·그림자가 없다 */
const KPI_LINK =
  'flex h-full flex-col gap-1.5 bg-card px-5 py-4 no-underline transition-colors duration-200 outline-none hover:bg-muted/50 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset'

/** 섹션 공통 — 흰 지면 + 1px 헤어라인. 떠 있는 카드로 만들지 않는다 */
/* min-w-0 : 그리드 트랙 기본값(auto)은 자식의 최소 콘텐츠 폭까지 늘어난다.
 * 카드 안 차트가 넘치면 그 폭이 트랙을 밀어 페이지 전체에 가로 스크롤이 생긴다 —
 * 넘침은 카드 안에서 끝나야 한다 */
const SECTION_CARD = 'flex min-w-0 flex-col gap-3 rounded-md border bg-card p-5'
const SECTION_TITLE = 'text-[13px] font-semibold tracking-[-0.01em] text-foreground'

/** `2026-07-29T03:00:00+09:00` → `07-29 03:00` (KPI 파이프라인 카드 목업 표기) */
function shortStamp(iso: string): string {
  return `${formatDate(iso).slice(5)} ${formatTime(iso)}`
}

export function Dashboard() {
  const queryClient = useQueryClient()
  const [trendRange, setTrendRange] = useState<Range>(7)
  const [latencyRange, setLatencyRange] = useState<Range>(7)
  const [resourceRange, setResourceRange] = useState<Range>(7)
  const [resourceView, setResourceView] = useState<'ops' | 'cost'>('ops')

  const summary = useQuery({
    queryKey: ['admin', 'dashboard', 'summary'],
    queryFn: () => apiRequest<DashboardSummary>('/api/admin/dashboard/summary'),
  })
  const trend = useQuery({
    queryKey: ['admin', 'dashboard', 'trend', trendRange],
    queryFn: () => apiRequest<TrendResponse>(`/api/admin/dashboard/trend?range=${trendRange}`),
  })
  const latency = useQuery({
    queryKey: ['admin', 'dashboard', 'latency', latencyRange],
    queryFn: () => apiRequest<LatencyResponse>(`/api/admin/dashboard/latency?range=${latencyRange}`),
  })
  const resources = useQuery({
    queryKey: ['admin', 'dashboard', 'resources', resourceRange],
    queryFn: () => apiRequest<ResourceResponse>(`/api/admin/dashboard/resources?range=${resourceRange}`),
  })

  const data = summary.data
  const rangeOptions = RANGES.map((r) => ({ value: r, label: `${r}일` }))

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b pb-3">
        {data && (
          <>
            {data.service.level === 'OK' ? (
              <p className={STATUS}>
                <span className="size-1.5 rounded-full bg-success" aria-hidden="true" /> 서비스 정상
              </p>
            ) : (
              <p className={cn(STATUS, 'text-danger-fg')}>
                <span className="size-1.5 rounded-full bg-current" aria-hidden="true" /> 서비스 오류 :
                {data.service.errors.map((e, i) => (
                  <Fragment key={e.key}>
                    {i > 0 && <span className="text-muted-foreground">·</span>}
                    <Link
                      className="font-semibold text-primary hover:underline"
                      to={FAILURE_KIND[e.key]?.to ?? '/admin/logs'}
                    >
                      {FAILURE_KIND[e.key]?.label ?? e.key} {e.count}건 →
                    </Link>
                  </Fragment>
                ))}
              </p>
            )}
          </>
        )}
        <div className="ml-auto">
          <RefreshBar
            at={data?.generated_at}
            pending={summary.isFetching || trend.isFetching || resources.isFetching}
            onRefresh={() => void queryClient.invalidateQueries({ queryKey: ['admin', 'dashboard'] })}
          />
        </div>
      </div>

      {summary.isPending && <Loading />}
      {summary.error && <SectionError error={summary.error} onRetry={() => void summary.refetch()} />}

      {data && (
        <>
          {/* 할 일 — KPI 보다 위. 대시보드가 지표판이 아니라 시작점이 되게 하는 줄이다
              (AD-DF-000 관리자 작업 흐름 ①). 0건이어도 항목을 지우지 않는다 — 사라지면
              '없는 것'과 '못 센 것'이 구분되지 않는다. 건수를 누르면 서버가 그 건수를 센 것과
              같은 필터의 목록이 열린다(todoHref). */}
          <ul
            aria-label="할 일"
            className="grid grid-cols-1 gap-px overflow-hidden rounded-md border bg-border md:grid-cols-3"
          >
            {data.todos.map((t) => (
              <li key={t.key} className="bg-card">
                <Link className={KPI_LINK} to={todoHref(t)}>
                  <KpiCard
                    label={t.label}
                    value={
                      <>
                        {t.count}
                        <Unit>건 · 이동 →</Unit>
                      </>
                    }
                  />
                </Link>
              </li>
            ))}
          </ul>

          {/* KPI 4종 — 4장의 카드가 아니라 헤어라인으로 나뉜 한 줄 스펙 시트.
              칸 사이 1px은 gap-px + 바탕 bg-border가 낸다(칸마다 보더를 그리면 모서리가 겹친다) */}
          <ul className="grid grid-cols-2 gap-px overflow-hidden rounded-md border bg-border xl:grid-cols-4">
            <li className="bg-card">
              <Link className={KPI_LINK} to="/admin/knowledge/pages">
                <KpiCard
                  label="지식베이스 규모"
                  value={
                    <>
                      {data.kpi.pages}
                      <Unit> 페이지</Unit> <Unit>· </Unit>
                      {data.kpi.chunks}
                      <Unit> 청크</Unit>
                    </>
                  }
                />
              </Link>
            </li>
            <li className="bg-card">
              <Link className={KPI_LINK} to="/admin/logs">
                <KpiCard
                  label="오늘 질문 수"
                  value={
                    <>
                      {data.kpi.questions_today}
                      <Unit>건</Unit>
                    </>
                  }
                />
              </Link>
            </li>
            <li className="bg-card">
              {/* 이 칸의 이동 대상만 기획서에 없다(09 issue 2) → 같은 화면의 단계별 카드로 보낸다 */}
              <a className={KPI_LINK} href="#stage-latency">
                <KpiCard
                  label="평균 응답시간"
                  value={
                    <>
                      {(data.kpi.avg_latency_ms / 1000).toFixed(1)}
                      <Unit>s</Unit>
                    </>
                  }
                />
              </a>
            </li>
            <li className="bg-card">
              <Link className={KPI_LINK} to="/admin/pipeline">
                <KpiCard
                  label="파이프라인"
                  value={
                    <>
                      {data.kpi.pipeline.status} <Unit>({shortStamp(data.kpi.pipeline.last_run_at)})</Unit>
                    </>
                  }
                />
              </Link>
            </li>
          </ul>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
            <section className={SECTION_CARD}>
              <div className="flex flex-wrap items-center gap-4">
                <h2 className={cn(SECTION_TITLE, 'mr-auto')}>일별 질문 수 추이</h2>
                <Segmented label="기간" value={trendRange} options={rangeOptions} onChange={setTrendRange} />
              </div>
              {trend.isPending && <Loading />}
              {trend.error && <SectionError error={trend.error} onRetry={() => void trend.refetch()} />}
              {trend.data && <TrendBars points={trend.data.points} />}
            </section>

            <section className={SECTION_CARD}>
              <h2 className={SECTION_TITLE}>질문 성격 · 업무별 분포</h2>
              <IntentDonut ratio={data.distribution.intent} />
              <div className="mt-auto">
                <h3 className="mb-2 text-[11px] font-medium text-muted-foreground">업무별</h3>
                <RatioBars items={data.distribution.business} />
              </div>
            </section>
          </div>

          <section className={SECTION_CARD} id="stage-latency">
            <div className="flex flex-wrap items-center gap-4">
              <h2 className={cn(SECTION_TITLE, 'mr-auto')}>단계별 평균 응답시간 (ms)</h2>
              <Segmented label="기간" value={latencyRange} options={rangeOptions} onChange={setLatencyRange} />
            </div>
            {latency.isPending && <Loading />}
            {latency.error && <SectionError error={latency.error} onRetry={() => void latency.refetch()} />}
            {latency.data && (
              // 모수(sample_count)는 총계 줄 앞에 선다 — KPI '평균 응답시간'은 오늘 전체 질문
              // 평균이고 이 값은 전 구간을 다 돈 질문만 모수라, 몇 건짜리인지가 같이 보여야 한다
              <StageBars
                stages={latency.data.stages}
                total={latency.data.avg_total_ms}
                sampleCount={latency.data.sample_count}
              />
            )}
          </section>

          <section className={SECTION_CARD}>
            <div className="flex flex-wrap items-center gap-4">
              <h2 className={cn(SECTION_TITLE, 'mr-auto')}>리소스 모니터링</h2>
              <Segmented label="기간" value={resourceRange} options={rangeOptions} onChange={setResourceRange} />
              <Segmented
                label="보기"
                value={resourceView}
                options={[
                  { value: 'ops', label: '운영 지표' },
                  { value: 'cost', label: '비용 분석' },
                ]}
                onChange={setResourceView}
              />
            </div>
            {resources.isPending && <Loading />}
            {resources.error && <SectionError error={resources.error} onRetry={() => void resources.refetch()} />}
            {resources.data &&
              // items-start를 빼 블록들의 아래 끝을 맞춘다 — 수치 목록만 일찍 끝나면 단차로 보인다
              (resourceView === 'ops' ? (
                <div className="grid gap-4 xl:grid-cols-[1fr_1fr_260px]">
                  <div className="min-w-0">
                    <h3 className="mb-2 text-[13px] font-medium text-foreground/80">일별 토큰 소비량</h3>
                    <TokenStack points={resources.data.tokens} />
                  </div>
                  <div className="min-w-0">
                    <h3 className="mb-2 text-[13px] font-medium text-foreground/80">일별 비용 추이 ($)</h3>
                    <CostLine points={resources.data.cost} caption={resources.data.cost_caption} />
                  </div>
                  <ul className="flex flex-col justify-between divide-y">
                    <Figure label="오늘 토큰" value={resources.data.today.tokens_text} />
                    <Figure label="오늘 비용" value={resources.data.today.cost_text} />
                    <Figure label="동시 요청 (현재/피크)" value={resources.data.today.concurrency_text} />
                    <Figure label="GPU 사용률" value={resources.data.today.gpu_text} />
                  </ul>
                </div>
              ) : (
                // 비용 분석 뷰는 목업이 없다(09 issue 5). 추이 + 항목별 비중으로 구성했다
                <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
                  <div className="min-w-0">
                    <h3 className="mb-2 text-[13px] font-medium text-foreground/80">일별 비용 추이 ($)</h3>
                    <CostLine points={resources.data.cost} caption={resources.data.cost_caption} />
                  </div>
                  <ul className="flex flex-col justify-between divide-y">
                    {resources.data.cost_breakdown.map((c) => (
                      <Figure
                        key={c.label}
                        label={c.label}
                        value={c.share === null ? c.amount_text : `${c.amount_text} · ${c.share}%`}
                      />
                    ))}
                  </ul>
                </div>
              ))}
          </section>
        </>
      )}
    </div>
  )
}

/** 리소스 수치 한 줄 — 낱개 보더 상자 대신 헤어라인으로 나뉜 스펙 시트의 한 행 */
function Figure({ label, value }: { label: string; value: string }) {
  return (
    <li className="flex min-h-9 items-center justify-between gap-3 py-1 text-[13px] text-muted-foreground">
      <span>{label}</span>
      <strong className="nums font-semibold text-foreground">{value}</strong>
    </li>
  )
}
