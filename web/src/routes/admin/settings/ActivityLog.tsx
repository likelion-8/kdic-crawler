/** AD-011 관리자 활동 로그 (설정 > 활동 로그 · ADMIN 조회).
 *
 * 추가 전용 원장이다 — 수정·삭제 UI를 만들지 않는다(CM-DF-004 10절 append-only).
 * 조회·내보내기 자체가 이벤트로 기록되므로 자동 새로고침·폴링·타이핑 즉시 조회를 두지 않는다.
 * 검색어는 제출(Enter/[조회])했을 때만 질의에 반영한다.
 *
 * 셸·설정 서브탭은 app/AdminLayout.tsx가 그린다. 여기서 다시 그리지 않는다. */
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Ban, Download, Search } from 'lucide-react'
import {
  Badge,
  Button,
  ConfirmModal,
  DataTable,
  DEFAULT_PAGE_SIZE,
  EmptyState,
  Loading,
  DetailModal,
  Notice,
  Pagination,
  Select,
  TextField,
  useToast,
} from '../../../components/ui'
import type { Column } from '../../../components/ui'
import { apiRequest, isApiRequestError } from '../../../lib/api/client'
import type { Page } from '../../../lib/api/types'
import { hasRole } from '../../../lib/codes'
import { formatDate, formatTime } from '../../../lib/format'
import { useSession } from '../../../app/session'
import { EventDetail, eventDetailMeta, eventDetailTitle } from './activity/EventDetail'
import type { ActivityEventDetailData, ActivityEventRow } from './activity/EventDetail'

/** 흰 지면 + 1px 헤어라인. 그림자로 띄우지 않는다 */
const CARD_CLASS = 'rounded-md border bg-card p-5'

/** 기본 기간 최근 7일 · 한 번에 조회 가능한 최대 범위 90일 (AD-011 Description 2) */
const PERIODS = [
  { value: '7', label: '최근 7일' },
  { value: '30', label: '최근 30일' },
  { value: '90', label: '최근 90일' },
]

/** 결과는 3종 고정. '진행 중'은 활동 로그의 값이 아니다 (CM-DF-002 07절 각주) */
const RESULTS = [
  { value: '', label: '전체' },
  { value: '성공', label: '성공' },
  { value: '실패', label: '실패' },
  { value: '거부됨', label: '거부됨' },
]

const ALL = { value: '', label: '전체' }

interface Overview {
  today_count: number
  last_recorded_at: string | null
  purge_due_this_week: number
  actions: string[]
  actors: string[]
}

interface Filters {
  q: string
  period: string
  action: string
  actor: string
  result: string
}

const EMPTY_FILTERS: Filters = { q: '', period: '7', action: '', actor: '', result: '' }

/** `2026-08-03T10:05:12+09:00` → `08-03 10:05`.
 * 목업은 당일 목록이라 `10:42`만 적혀 있으나 최대 90일을 조회하므로 날짜를 병기한다. */
function stamp(iso: string): string {
  return `${formatDate(iso).slice(5)} ${formatTime(iso)}`
}

export function ActivityLog() {
  const { session } = useSession()
  const showToast = useToast()
  // 딥링크 `?q=` — AD-004 실패 상세의 [작업 기록 보기]가 job_id를 넘긴다(JobFailureDetail.tsx)
  const [searchParams] = useSearchParams()
  const deepLinkQ = searchParams.get('q')?.trim() ?? ''
  // AD-010 위험 작업 기록의 [상세]는 특정 이벤트를 지목해 온다(`?event=<id>`).
  // 키워드 검색(`?q=`)과 달리 "이 행을 열어라"는 뜻이라 선택 상태로 받는다 —
  // 안 읽으면 어느 행을 눌러도 최신 이벤트가 열린다(검증 D008).
  const deepLinkEvent = searchParams.get('event')?.trim() ?? ''
  // 입력 중인 검색어와 실제 질의에 반영된 값을 분리한다 — 타이핑마다 조회가 나가면 로그가 오염된다
  const [keyword, setKeyword] = useState(deepLinkQ)
  const [filters, setFilters] = useState<Filters>({ ...EMPTY_FILTERS, q: deepLinkQ })
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(deepLinkEvent || null)
  const [exportOpen, setExportOpen] = useState(false)
  const [exportError, setExportError] = useState<Error | null>(null)

  const overview = useQuery({
    queryKey: ['admin', 'activity', 'overview'],
    queryFn: () => apiRequest<Overview>('/api/admin/activity/overview'),
  })

  const params = new URLSearchParams({
    sort: 'occurred_at:desc',
    page: String(page),
    size: String(DEFAULT_PAGE_SIZE),
    // 날짜(일) 단위로 자른다 — 시각까지 넣으면 렌더마다 값이 달라져 조회가 반복된다(로그가 오염된다)
    from: formatDate(Date.now() - Number(filters.period) * 86_400_000),
  })
  if (filters.q) params.set('q', filters.q)
  if (filters.action) params.set('action', filters.action)
  if (filters.actor) params.set('actor', filters.actor)
  if (filters.result) params.set('result', filters.result)

  const events = useQuery({
    queryKey: ['admin', 'activity', 'events', params.toString()],
    queryFn: () => apiRequest<Page<ActivityEventRow>>(`/api/admin/activity/events?${params.toString()}`),
  })

  const rows = events.data?.items ?? []
  // 상세가 모달이 되면서 '진입 시 최신 이벤트 자동 선택'(Description 3)은 버렸다 —
  // 그대로 두면 화면을 열자마자 모달이 떠 목록을 가린다. 상세는 [상세]를 눌렀을 때만 열린다.
  // 선택 행이 필터로 사라지면 모달도 닫힌다(다른 이벤트를 대신 열지 않는다).
  const selected = rows.find((r) => r.id === selectedId)
  // `?event=`로 지목해 들어왔는데 그 이벤트가 목록에 없으면 조용히 넘어가지 않고 목록 위에 알린다 —
  // 감사 화면에서 09:18 권한 변경을 눌렀는데 10:42 프롬프트 게시 상세가 뜨는 게 원래 결함이었다.
  const deepLinkMissed =
    deepLinkEvent !== '' && selectedId === deepLinkEvent && !selected && !events.isPending

  const detail = useQuery({
    queryKey: ['admin', 'activity', 'event', selected?.id],
    queryFn: () => apiRequest<ActivityEventDetailData>(`/api/admin/activity/events/${selected!.id}`),
    enabled: selected !== undefined,
  })

  const exporting = useMutation({
    mutationFn: (reason: string) =>
      apiRequest<{ export_id: string }>('/api/admin/activity/exports', {
        method: 'POST',
        reason,
        // 내보내기 대상은 '현재 필터 결과'다 (Description 2)
        body: { filter: Object.fromEntries(params) },
      }),
    onSuccess: () => {
      setExportOpen(false)
      setExportError(null)
      showToast('내보내기를 시작했습니다')
    },
    onError: (error: Error) => {
      // 실패는 토스트가 아니라 화면 안에 남긴다 (CM-DF-001 07.4절)
      setExportOpen(false)
      setExportError(error)
    },
  })

  function patch(next: Partial<Filters>) {
    setFilters((f) => ({ ...f, ...next }))
    setPage(1)
  }

  function reset() {
    setKeyword('')
    setFilters(EMPTY_FILTERS)
    setPage(1)
  }

  const columns: Column<ActivityEventRow>[] = [
    {
      key: 'occurred_at',
      header: '시각',
      width: '104px',
      render: (r) => <span className="nums">{stamp(r.occurred_at)}</span>,
    },
    { key: 'action', header: '행위', width: '150px', render: (r) => r.action },
    { key: 'target', header: '대상', render: (r) => r.target },
    { key: 'actor', header: '실행자', width: '130px', render: (r) => r.actor },
    {
      key: 'result',
      header: '결과',
      width: '96px',
      // 결과 3종 배지 — 성공 초록 · 실패 빨강 · 거부됨 빨강 강조(+아이콘)
      render: (r) => (
        <Badge tone={r.result === '성공' ? 'green' : 'red'} kind="status">
          {r.result === '거부됨' && <Ban className="size-3" aria-hidden="true" />}
          {r.result}
        </Badge>
      ),
    },
  ]

  const canExport = hasRole(session?.role, 'ADMIN')
  const total = events.data?.total ?? 0

  return (
    <div className="flex flex-col gap-5">
      {/* ❶ 활동 로그 현황 — 회색 미니 카드 3장이 아니라 세로 헤어라인으로 나뉜 한 줄 스펙 시트 */}
      <section className={CARD_CLASS}>
        <h2 className="mb-4 text-[13px] font-semibold tracking-[-0.01em]">활동 로그 현황</h2>
        {overview.isPending && <Loading />}
        {overview.data && (
          <dl className="grid grid-cols-3 divide-x border-y">
            <div className="flex flex-col gap-1.5 py-3 pr-4">
              <dt className="text-xs text-muted-foreground">오늘 기록</dt>
              <dd className="nums text-2xl leading-none font-bold tracking-tight">
                {overview.data.today_count}건
              </dd>
            </div>
            {/* 현황 바는 오늘 기준이라 시각만 쓴다(3-1 `마지막 기록 10:42`). 날짜 병기는 목록 표만 */}
            <div className="flex flex-col gap-1.5 py-3 pr-4 pl-4">
              <dt className="text-xs text-muted-foreground">마지막 기록</dt>
              <dd className="nums text-2xl leading-none font-bold tracking-tight">
                {overview.data.last_recorded_at ? formatTime(overview.data.last_recorded_at) : '—'}
              </dd>
            </div>
            <div className="flex flex-col gap-1.5 py-3 pl-4">
              <dt className="text-xs text-muted-foreground">이번 주 파기 예정</dt>
              <dd className="nums text-2xl leading-none font-bold tracking-tight">
                {overview.data.purge_due_this_week}건
              </dd>
            </div>
          </dl>
        )}
      </section>

      {/* ❷ 검색 · 필터 · 내보내기 */}
      <form
        className="flex flex-wrap items-end gap-x-4 gap-y-3 rounded-md border bg-card px-5 py-4"
        onSubmit={(e) => {
          e.preventDefault()
          patch({ q: keyword.trim() })
        }}
      >
        <div className="min-w-50 flex-[1_1_240px]">
          <TextField
            layout="stack"
            grow
            label="검색"
            value={keyword}
            onChange={setKeyword}
            placeholder="대상 ID · 사유로 찾기"
          />
        </div>
        <Select
          layout="stack"
          label="기간"
          value={filters.period}
          options={PERIODS}
          onChange={(v) => patch({ period: v })}
        />
        <Select
          layout="stack"
          label="행위"
          value={filters.action}
          options={[ALL, ...(overview.data?.actions ?? []).map((a) => ({ value: a, label: a }))]}
          onChange={(v) => patch({ action: v })}
        />
        <Select
          layout="stack"
          label="실행자"
          value={filters.actor}
          options={[ALL, ...(overview.data?.actors ?? []).map((a) => ({ value: a, label: a }))]}
          onChange={(v) => patch({ actor: v })}
        />
        <Select
          layout="stack"
          label="결과"
          value={filters.result}
          options={RESULTS}
          onChange={(v) => patch({ result: v })}
        />
        <div className="ml-auto flex items-center gap-2">
          {/* 이 화면의 주 동작은 [조회]다 — primary는 여기에 준다.
              내보내기가 primary였던 탓에 '보조 동작이 더 중요해 보이는' 줄이 됐고,
              같은 내보내기인데 대화 로그(AD-005)에서는 secondary라 두 화면이 어긋나 있었다 */}
          <Button type="submit" variant="primary">
            <Search aria-hidden="true" />
            조회
          </Button>
          {/* 내보내기는 ADMIN에게만 노출한다. 서버가 최종 판정이므로 403도 처리한다 */}
          {canExport && (
            <Button onClick={() => setExportOpen(true)} disabled={total === 0} disabledReason={total === 0 ? '내보낼 결과가 없습니다' : undefined}>
              <Download aria-hidden="true" />
              내보내기
            </Button>
          )}
        </div>
      </form>

      {/* 실패는 화면 안에 남긴다(07.4절) — 요청 ID는 본문에 섞지 말고 보조 정보로 내린다 */}
      {exportError && (
        <div role="alert">
          <Notice
            tone="danger"
            variant="block"
            meta={
              isApiRequestError(exportError) && exportError.error.request_id
                ? `요청 ID ${exportError.error.request_id}`
                : undefined
            }
          >
            {isApiRequestError(exportError) ? exportError.error.user_message : exportError.message}
          </Notice>
        </div>
      )}

      {/* 딥링크로 지목한 이벤트를 못 찾았다 — 다른 이벤트를 대신 열지 않고 그 사실을 알린다.
          상세가 모달이 된 뒤로는 이 자리(목록 위)가 유일하게 눈에 띄는 자리다 */}
      {deepLinkMissed && (
        <Notice tone="warning" variant="block">
          요청한 이벤트({deepLinkEvent})를 현재 조건에서 찾지 못했습니다. 기간·필터를 넓혀 주세요
        </Notice>
      )}

      {/* 상세는 표 옆·아래가 아니라 모달로 뜬다 — 표는 전체 폭을 쓰고, [상세]를 누른 자리에서
          바로 결과가 보인다. 옆 칸에 두면 표가 눌리고, 아래로 내리면 화면 밖이라 눌러도
          아무 일도 안 일어난 것처럼 보였다(사용자 지적) */}
      <div className="rounded-md border bg-card">
        {/* ❸ 이벤트 목록 */}
        <section className="min-w-0 p-5">
          {/* 조회가 실패했으면 건수를 쓰지 않는다 — '0건'과 빈 상태가 조건 문제로 읽힌다 */}
          <h2 className="mb-4 text-[13px] font-semibold tracking-[-0.01em]">
            이벤트 목록{events.isError ? '' : ` · ${total.toLocaleString('ko-KR')}건`}
          </h2>
          {events.isError ? (
            <div role="alert">
              <Notice
                tone="danger"
                variant="block"
                action={
                  isApiRequestError(events.error) && events.error.error.retryable ? (
                    <Button size="sm" onClick={() => void events.refetch()}>
                      다시 시도
                    </Button>
                  ) : undefined
                }
              >
                {isApiRequestError(events.error) ? events.error.error.user_message : events.error.message}
              </Notice>
            </div>
          ) : events.isPending ? (
            <Loading />
          ) : (
            <>
              <DataTable
                caption="관리자 활동 이벤트 목록. 시각 · 행위 · 대상 · 실행자 · 결과"
                columns={columns}
                rows={rows}
                rowKey={(r) => r.id}
                rowState={(r) =>
                  r.id === selected?.id ? 'selected' : r.result === '거부됨' ? 'danger' : 'default'
                }
                onRowClick={(r) => setSelectedId(r.id)}
                // 행 클릭만으로는 키보드 조작이 안 된다 → '조치' 열에 같은 동작의 버튼을 둔다
                actions={(r) => (
                  <Button size="sm" onClick={() => setSelectedId(r.id)}>
                    상세
                  </Button>
                )}
                empty={
                  <EmptyState
                    title="조건에 맞는 이벤트가 없습니다"
                    action={
                      <>
                        <p className="text-[13px] text-muted-foreground">기간을 넓히거나 필터를 초기화해 보세요</p>
                        <Button size="sm" onClick={reset}>
                          필터 초기화
                        </Button>
                      </>
                    }
                  />
                }
              />
              {total > DEFAULT_PAGE_SIZE && (
                <div className="mt-4 flex justify-center">
                  <Pagination page={page} total={total} onPageChange={setPage} />
                </div>
              )}
            </>
          )}
        </section>

      </div>

      {/* ❹ 이벤트 상세 — 모달 */}
      <DetailModal
        open={selected !== undefined}
        title={detail.data ? eventDetailTitle(detail.data) : '이벤트 상세'}
        meta={detail.data ? eventDetailMeta(detail.data) : undefined}
        onClose={() => setSelectedId(null)}
      >
        {detail.isPending && <Loading />}
        {/* 상세 실패도 화면 안에 남긴다(07.4절) */}
        {detail.isError && (
          <div role="alert">
            <Notice
              tone="danger"
              variant="block"
              action={
                isApiRequestError(detail.error) && detail.error.error.retryable ? (
                  <Button size="sm" onClick={() => void detail.refetch()}>
                    다시 시도
                  </Button>
                ) : undefined
              }
            >
              {isApiRequestError(detail.error) ? detail.error.error.user_message : detail.error.message}
            </Notice>
          </div>
        )}
        {detail.data && <EventDetail event={detail.data} />}
      </DetailModal>

      <ConfirmModal
        open={exportOpen}
        title="활동 로그를 내보낼까요?"
        impact={
          <>
            <p>현재 필터 결과 {total.toLocaleString('ko-KR')}건을 내보냅니다.</p>
            <p>내보내기 성공 · 실패도 활동 로그에 이벤트로 기록됩니다.</p>
          </>
        }
        reason="required"
        reasonPlaceholder="예: 분기 보안 점검 자료 제출 (2026-08-03)"
        confirmLabel="내보내기"
        pending={exporting.isPending}
        onConfirm={({ reason }) => exporting.mutate(reason ?? '')}
        onCancel={() => setExportOpen(false)}
      />
    </div>
  )
}
