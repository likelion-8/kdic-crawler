/** AD-002 지식베이스 관리 : 페이지·청크 목록.
 *
 * 화면 제목·GNB·세션은 AdminLayout이 그린다. 여기서 다시 그리지 않는다.
 * 구성(B-1) : 탭 → 검색·필터 → [+ 신규 URL 추가] / ⓘ 안내 / 신규 URL 인라인 블록(AD-003) /
 *              적용 대기 배너 / 목록 표 : 상세 패널(2:1).
 *
 * 오류 문구는 서버 user_message 그대로 쓴다 — 이 파일은 오류 문구를 만들지 않는다.
 * "페이지 내용 직접 편집은 범위 밖(CM-DF-004 04절)" (B-7) → 편집 UI를 만들지 않는다. */
import { useEffect, useId, useState } from 'react'
import { useSearchParams } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Search } from 'lucide-react'
import {
  Badge,
  Button,
  ColorText,
  ConfirmModal,
  DataTable,
  DEFAULT_PAGE_SIZE,
  EmptyState,
  InfoHint,
  DetailModal,
  Loading,
  Notice,
  Pagination,
  useToast,
} from '../../components/ui'
import type { Column, SelectOption, SortState } from '../../components/ui'
import { Input } from '../../components/shadcn/input'
import { cn } from '../../lib/utils'
import { useSession } from '../../app/session'
import { NewPageForm } from './knowledge/NewPageForm'
import { apiRequest, isApiRequestError } from '../../lib/api/client'
import type { Page } from '../../lib/api/types'
import { BUSINESS_FUNCTIONS, INDEX_STATUS_BADGE, hasRole } from '../../lib/codes'
import type { CollectionStatus, IndexStatus, KbListState } from '../../lib/codes'
import { formatDate, formatTarget } from '../../lib/format'
import {
  PageDetailActions,
  PageDetailPanel,
  pageDetailMeta,
  pageDetailTitle,
} from './knowledge/PageDetailPanel'
import type { ChangeRequestView, KbPage } from './knowledge/types'

/** 필터 '전체' 값. 목 핸들러가 '전체'를 무시(=필터 해제)로 처리한다 */
const ALL = '전체'
/** 검색 입력 디바운스 — 규격이 없어(09 issue 11) 타이핑마다 조회하지 않을 만큼만 둔다 */
const SEARCH_DEBOUNCE_MS = 300

type Tab = 'indexed' | 'targets'

/** 확인 모달이 떠 있는 위험 작업. 사유는 모달이 받아 넘긴다.
 * 개별 재수집은 위험 작업 목록(CM-DF-004 03절 '신규 URL 적용·삭제·일괄 재수집·재색인…')에 없고
 * B-7도 중립 버튼으로만 규정해 모달 없이 바로 실행한다 */
type ActionTarget =
  | { kind: 'delete'; page: KbPage }
  | { kind: 'cancelDelete'; page: KbPage }
  | { kind: 'reindex'; count: number }

/** 모달 없는 쓰기라 화면이 고정 사유를 붙인다 — 쓰기 API는 reason 필수(CM-DF-003 04절) */
const RECRAWL_REASON = '지식베이스 상세에서 개별 재수집'

interface AdminAction {
  run: () => Promise<unknown>
  /** 성공만 토스트로 알린다(07.4절) */
  success: string
}

const BUSINESS_OPTIONS: SelectOption[] = [
  { value: ALL, label: ALL },
  ...BUSINESS_FUNCTIONS.map((b) => ({ value: b, label: b })),
]

/** 상태 값 라벨 정본은 CM-DF-002 05절이다(B-3 Description 2).
 * 목록 3상태(파생) + index_status 5종 — '적용 대기'는 두 곳에 같은 뜻으로 있어 한 번만 넣는다. */
const STATE_OPTIONS: SelectOption[] = [
  { value: ALL, label: ALL },
  { value: '최신', label: '최신' },
  { value: '변경 감지', label: '변경 감지' },
  { value: '적용 대기', label: '적용 대기' },
  ...(Object.entries(INDEX_STATUS_BADGE) as [IndexStatus, string][])
    .filter(([code]) => code !== 'PENDING')
    .map(([code, label]) => ({ value: code, label })),
]

/** 목록 3상태 배지 색 — 초록=현행 / 주황=주의 / 'purple'=아직 반영 전(초안 성격) (CM-DF-001 05절).
 * 'purple'은 Badge가 중립 태그로 그린다 — 보라는 Primary·링크·포커스·현재 위치·차트 주계열에만 쓴다 */
const LIST_STATE_TONE: Record<KbListState, 'green' | 'orange' | 'purple'> = {
  최신: 'green',
  '변경 감지': 'orange',
  '적용 대기': 'purple',
}

/** 적재·협의 상태 3종 (B-9). 원문이 있는 문구는 `적재됨 ✓` · `후보 (미적재)` · `협의 중 (사이트 제한)`뿐이라
 * 나머지 차단 사유는 같은 `협의 중 (사유)` 틀로 맞췄다. 회색(tone 없음)은 평문으로 그린다. */
const COLLECTION_LABEL: Record<CollectionStatus, string> = {
  LOADED: '적재됨 ✓',
  CANDIDATE: '후보 (미적재)',
  ROBOTS_BLOCKED: '협의 중 (사이트 제한)',
  SKIPPED: '협의 중 (수집 보류)',
  FAILED: '협의 중 (수집 실패)',
}
/** 협의가 끝나기 전에는 [수집 실행]을 비활성으로 둔다 (B-9 행 동작 규칙) */
const isBlocked = (status: CollectionStatus) =>
  status === 'ROBOTS_BLOCKED' || status === 'SKIPPED' || status === 'FAILED'

/** 탭 버튼 — 트랙 bg-muted + 활성은 흰 바탕·굵은 글자(색면 대신 굵기가 현재 위치를 알린다)·aria-pressed 병기 */
const TAB_BTN =
  'inline-flex h-7 items-center gap-1 rounded-[3px] px-2.5 text-[13px] font-medium whitespace-nowrap transition-colors duration-200 outline-none focus-visible:ring-2 focus-visible:ring-ring'
const tabClass = (active: boolean) =>
  cn(
    TAB_BTN,
    active ? 'bg-background font-semibold text-foreground' : 'text-muted-foreground hover:text-foreground',
  )

/** 표를 감싸는 지면 — 그림자로 띄우지 않고 헤어라인으로만 가둔다 */
const TABLE_FRAME = 'flex min-w-0 flex-col gap-2 rounded-md border bg-card p-2 pb-3'

/** 툴바용 인라인 라벨 셀렉트 — 룩은 공통 Select(shadcn SelectTrigger 계열)와 동일, 라벨만 인라인 배치 */
function ToolbarSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: SelectOption[]
}) {
  const id = useId()
  return (
    <span className="flex items-center gap-1.5">
      <label className="text-xs text-muted-foreground" htmlFor={id}>
        {label}
      </label>
      <span className="relative inline-flex">
        <select
          id={id}
          className="h-8 appearance-none rounded-md border border-input bg-background pr-8 pl-3 text-sm whitespace-nowrap transition-[color,box-shadow] outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown
          className="pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden="true"
        />
      </span>
    </span>
  )
}

export function KnowledgePages() {
  const showToast = useToast()
  const queryClient = useQueryClient()
  const { session } = useSession()
  const role = session?.role
  const searchId = useId()

  // 권한이 없으면 버튼을 숨긴다. 서버가 최종 판정이므로 403은 아래 오류 패널이 항상 처리한다
  const canEdit = hasRole(role, 'EDITOR')
  const canRunJob = hasRole(role, 'OPERATOR')

  const [tab, setTab] = useState<Tab>('indexed')
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [business, setBusiness] = useState(ALL)
  const [state, setState] = useState(ALL)
  const [sort, setSort] = useState<SortState | undefined>(undefined)
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [target, setTarget] = useState<ActionTarget | null>(null)
  /** 신규 URL 추가(AD-003) 인라인 블록. null이면 닫힘, 문자열이면 그 후보를 프리필해 연다.
   * 별도 화면으로 보내면 목록·필터·스크롤 위치를 잃는다(P-12) */
  const [newPage, setNewPage] = useState<{ candidateId: string | null } | null>(null)
  // 활동 로그·북마크에서 `?new=1`로 바로 들어오는 경로를 살려 둔다(옛 /knowledge/new 링크가 여기로 온다)
  const [searchParams, setSearchParams] = useSearchParams()
  useEffect(() => {
    if (searchParams.get('new') === null) return
    setNewPage({ candidateId: searchParams.get('candidate') })
    // 쿼리는 한 번 쓰고 지운다 — 남겨 두면 닫은 뒤 새로고침에 다시 열린다
    setSearchParams({}, { replace: true })
  }, [searchParams, setSearchParams])

  useEffect(() => {
    const timer = setTimeout(() => setQ(search), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [search])

  // 조건이 바뀌면 첫 페이지로 — 3페이지에서 필터를 걸면 빈 화면이 나온다
  useEffect(() => setPage(1), [q, business, state, tab])

  // 탭이 목록 필터다 — '수집 대상'은 적재 전 후보·협의 중을 포함해 '적재 페이지'와 행이 다르다(B-9)
  const params = new URLSearchParams({ tab, page: String(page), size: String(DEFAULT_PAGE_SIZE) })
  if (q) params.set('q', q)
  if (business !== ALL) params.set('business', business)
  if (state !== ALL) params.set('state', state)
  if (sort) params.set('sort', `${sort.key}:${sort.dir}`)

  const pages = useQuery({
    queryKey: ['kb-pages', 'list', params.toString()],
    queryFn: () => apiRequest<Page<KbPage>>(`/api/admin/knowledge/pages?${params.toString()}`),
  })

  // 탭 라벨 건수 — 목업의 58은 예시라 하드코딩하지 않고 탭별 전체 건수를 각각 받아 쓴다
  const indexedTotal = useQuery({
    queryKey: ['kb-pages', 'total', 'indexed'],
    queryFn: () => apiRequest<Page<KbPage>>('/api/admin/knowledge/pages?tab=indexed&size=1'),
  })
  const targetsTotal = useQuery({
    queryKey: ['kb-pages', 'total', 'targets'],
    queryFn: () => apiRequest<Page<KbPage>>('/api/admin/knowledge/pages?tab=targets&size=1'),
  })

  // 적용 대기 배너 건수. 목록 필터와 무관하게 전체 기준이라 따로 센다
  const pending = useQuery({
    queryKey: ['kb-pages', 'pending'],
    queryFn: () =>
      apiRequest<Page<KbPage>>(`/api/admin/knowledge/pages?state=${encodeURIComponent('적용 대기')}&size=1`),
  })

  const action = useMutation({
    mutationFn: (a: AdminAction) => a.run(),
    onSuccess: (_data, a) => {
      showToast(a.success)
      void queryClient.invalidateQueries({ queryKey: ['kb-pages'] })
      void queryClient.invalidateQueries({ queryKey: ['kb-chunks'] })
    },
    // 실패는 토스트가 아니라 화면 안에 남긴다(07.4절) → 아래 오류 패널에서 action.error를 읽는다
  })

  const rows = pages.data?.items ?? []
  // 상세가 모달이 되면서 "진입 시 첫 행을 자동 선택"(B-6 Description 6)은 버렸다 —
  // 그대로 두면 화면을 열자마자 모달이 떠 목록을 가린다(실측: 새로고침 시 1행 모달 자동 열림).
  // 상세는 [상세]를 눌렀을 때만 열리고, 고른 행이 필터로 사라지면 모달도 닫힌다.
  const selected = rows.find((r) => r.page_id === selectedId)

  const resetFilters = () => {
    setSearch('')
    setQ('')
    setBusiness(ALL)
    setState(ALL)
  }

  /** 개별 재수집 — 확인 모달 없이 바로 실행하고 결과는 토스트·오류 패널로 알린다(09 issue 21) */
  const runRecrawl = (target: KbPage) =>
    action.mutate({
      run: () =>
        apiRequest('/api/admin/jobs', {
          method: 'POST',
          body: { type: 'SELECTED_RECRAWL', targets: [target.page_id] },
          reason: RECRAWL_REASON,
        }),
      success: '재수집 작업을 시작했습니다',
    })

  const runAction = (item: ActionTarget, reason: string) => {
    setTarget(null)
    if (item.kind === 'cancelDelete') {
      const requestId = item.page.pending_change_request_id
      if (!requestId) return
      action.mutate({
        run: () =>
          apiRequest(`/api/admin/change-requests/${requestId}/reject`, {
            method: 'POST',
            reason,
          }),
        success: '삭제 신청을 취소했습니다',
      })
      return
    }
    if (item.kind === 'delete') {
      // 삭제는 즉시 지우는 게 아니라 변경 요청으로 남아 '적용 대기'가 된다 (B-7)
      action.mutate({
        run: () =>
          apiRequest<ChangeRequestView>('/api/admin/change-requests', {
            method: 'POST',
            body: {
              action: 'DELETE',
              target_page_id: item.page.page_id,
              target_title: item.page.page_title,
              business_function: item.page.business_function,
            },
            reason,
          }),
        success: '삭제를 요청했습니다',
      })
      return
    }
    action.mutate({
      run: () => apiRequest('/api/admin/jobs', { method: 'POST', body: { type: 'REINDEX' }, reason }),
      success: '재적재 작업을 시작했습니다',
    })
  }

  const failure = isApiRequestError(action.error) ? action.error.error : null
  /** [다시 시도]는 직전과 똑같은 요청을 다시 보낸다 */
  const lastAction = action.variables
  const modal = target === null ? null : confirmContent(target)

  const indexedColumns: Column<KbPage>[] = [
    { key: 'page_id', header: '페이지 ID', sortable: true, render: (r) => r.page_id },
    { key: 'page_title', header: '제목', sortable: true, render: (r) => r.page_title },
    { key: 'business_function', header: '업무', render: (r) => r.business_function },
    {
      key: 'collected_at',
      header: '수집일',
      sortable: true,
      render: (r) => <span className="nums">{formatDate(r.collected_at)}</span>,
    },
    // Description은 '청크 수', 목업 헤더는 '청크' — 목업 헤더를 따른다(09 issue 14)
    {
      key: 'chunk_count',
      header: '청크',
      align: 'right',
      render: (r) => <span className="nums">{r.chunk_count}</span>,
    },
    {
      key: 'list_state',
      header: '상태',
      render: (r) => (
        <span className="inline-flex items-center gap-1.5">
          <Badge tone={LIST_STATE_TONE[r.list_state]} kind="status">
            {r.list_state}
          </Badge>
          {/* 목록 3상태와 index_status가 어긋날 수 있어(CM-DF-002 C-7) 반영 완료가 아니면 함께 적는다 */}
          {r.index_status !== 'INDEXED' && (
            <ColorText tone={r.index_status === 'FAILED' ? 'red' : 'orange'}>
              {INDEX_STATUS_BADGE[r.index_status]}
            </ColorText>
          )}
        </span>
      ),
    },
  ]

  const targetColumns: Column<KbPage>[] = [
    { key: 'page_id', header: '페이지 ID', sortable: true, render: (r) => r.page_id },
    { key: 'page_title', header: '제목', sortable: true, render: (r) => r.page_title },
    { key: 'business_function', header: '업무', render: (r) => r.business_function },
    { key: 'required', header: '구분', render: (r) => (r.required ? '필수' : '분석필요') },
    {
      key: 'collection_status',
      header: '적재·협의 상태',
      render: (r) =>
        r.collection_status === 'LOADED' ? (
          <ColorText tone="green">{COLLECTION_LABEL.LOADED}</ColorText>
        ) : isBlocked(r.collection_status) ? (
          <ColorText tone="orange">{COLLECTION_LABEL[r.collection_status]}</ColorText>
        ) : (
          // 후보(미적재)는 목업이 회색 평문이다 — ColorText 4색에 회색이 없어 그대로 둔다
          COLLECTION_LABEL[r.collection_status]
        ),
    },
    { key: 'owner', header: '담당', render: (r) => r.owner },
    { key: 'note', header: '수집 근거', render: (r) => r.note },
  ]

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3 border-b pb-3">
        {/* 탭 — 세그먼트 컨트롤(B-2). shadcn Tabs 룩 + aria-pressed. 건수는 탭별 API 총계로 렌더한다 */}
        <div
          className="inline-flex items-center rounded-md bg-muted p-[3px]"
          role="group"
          aria-label="목록 탭"
        >
          <button
            type="button"
            className={tabClass(tab === 'indexed')}
            aria-pressed={tab === 'indexed'}
            onClick={() => setTab('indexed')}
          >
            적재 페이지 <span className="tabular-nums">{indexedTotal.data?.total ?? 0}</span>
          </button>
          <button
            type="button"
            className={tabClass(tab === 'targets')}
            aria-pressed={tab === 'targets'}
            onClick={() => setTab('targets')}
          >
            수집 대상 <span className="tabular-nums">{targetsTotal.data?.total ?? 0}</span>
          </button>
        </div>
        {/* 두 탭이 무엇을 담는지는 한 번 알면 되는 규칙이다. 툴바 아래 문단으로 두면 탭을 옮길
            때마다 문장만 바뀌면서 표 전체가 위아래로 흔들린다 — 탭 옆으로 접는다 */}
        <InfoHint label="탭 구분 설명">
          <strong>적재 페이지</strong>는 실제로 적재돼 검색에 쓰이는 페이지입니다. <strong>수집 대상</strong>
          은 크롤링을 허용한 목록으로, 아직 적재하지 않은 후보와 협의 중 항목을 함께 담습니다. 이 목록에 없는
          페이지는 크롤링하지 않습니다.
        </InfoHint>

        {/* 검색 — placeholder 원문의 돋보기(B-3 컨트롤 표)는 lucide Search 아이콘이 대신한다 */}
        <span className="relative">
          <label className="sr-only" htmlFor={searchId}>
            검색
          </label>
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            id={searchId}
            className="h-8 w-52 pl-8"
            value={search}
            placeholder="제목·URL 검색"
            onChange={(e) => setSearch(e.target.value)}
          />
        </span>
        <ToolbarSelect label="업무" value={business} onChange={setBusiness} options={BUSINESS_OPTIONS} />
        <ToolbarSelect label="상태" value={state} onChange={setState} options={STATE_OPTIONS} />

        {canEdit && (
          <div className="ml-auto">
            <Button
              variant="primary"
              disabled={newPage !== null}
              disabledReason={newPage !== null ? '이미 입력 중입니다' : undefined}
              onClick={() => setNewPage({ candidateId: null })}
            >
              + 신규 URL 추가
            </Button>
          </div>
        )}
      </div>

      {/* 신규 URL 추가(AD-003) — 목록 위에 인라인으로 열린다. AD-006 [+ 문항 추가]와 같은 방식이다.
          key로 후보가 바뀔 때 폼 상태를 새로 시작한다(이전 입력이 남으면 다른 URL의 값이 섞인다) */}
      {newPage && (
        <NewPageForm
          key={newPage.candidateId ?? 'blank'}
          candidateId={newPage.candidateId}
          onClose={() => setNewPage(null)}
        />
      )}

      {/* 적용 대기 배너 — 0건이면 알릴 것이 없어 감춘다(09 issue 20) */}
      {(pending.data?.total ?? 0) > 0 && (
        <div role="status">
          <Notice
            tone="warning"
            variant="block"
            action={
              canRunJob && (
                <Button
                  size="sm"
                  className="whitespace-nowrap"
                  onClick={() => setTarget({ kind: 'reindex', count: pending.data?.total ?? 0 })}
                >
                  재적재 실행 →
                </Button>
              )
            }
          >
            <strong className="font-bold">적용 대기 {pending.data?.total}건</strong> : 추가·삭제한 내용은
            재적재 전까지 검색 결과에 반영되지 않습니다. 기존 인덱스로 서비스는 정상 동작합니다.
          </Notice>
        </div>
      )}

      {failure && (
        <div role="alert">
          <Notice
            tone="danger"
            variant="block"
            /* retryable일 때만 [다시 시도]를 그린다 */
            action={
              failure.retryable &&
              lastAction && (
                <Button size="sm" onClick={() => action.mutate(lastAction)}>
                  다시 시도
                </Button>
              )
            }
          >
            {failure.user_message}
          </Notice>
        </div>
      )}

      {pages.isPending && <Loading text="목록을 불러오는 중…" />}
      {pages.isError && isApiRequestError(pages.error) && (
        <div role="alert">
          <Notice
            tone="danger"
            variant="block"
            action={
              pages.error.error.retryable && (
                <Button size="sm" onClick={() => void pages.refetch()}>
                  다시 시도
                </Button>
              )
            }
          >
            {pages.error.error.user_message}
          </Notice>
        </div>
      )}

      {pages.isSuccess &&
        (tab === 'indexed' ? (
          <div className={TABLE_FRAME}>
            <DataTable
              caption="적재 페이지 목록"
              columns={indexedColumns}
              rows={rows}
              rowKey={(r) => r.page_id}
              rowState={(r) => (r.page_id === selected?.page_id ? 'selected' : 'default')}
              sort={sort}
              onSortChange={setSort}
              onRowClick={(r) => setSelectedId(r.page_id)}
              // 행 클릭은 마우스 전용이라 조치 열에 같은 동작의 버튼을 둔다(키보드 조작 보장)
              actions={(r) => (
                <Button size="sm" onClick={() => setSelectedId(r.page_id)}>
                  상세
                </Button>
              )}
              empty={
                <EmptyState
                  title="조건에 맞는 결과가 없습니다"
                  action={
                    <Button size="sm" onClick={resetFilters}>
                      필터 초기화
                    </Button>
                  }
                />
              }
            />
            <Pagination page={page} total={pages.data.total} onPageChange={setPage} />
          </div>
        ) : (
          <div className={TABLE_FRAME}>
            <DataTable
              caption="수집 대상 목록"
              columns={targetColumns}
              rows={rows}
              rowKey={(r) => r.page_id}
              // 협의 중 행은 조작할 수 없다 — 목업 배경(#FFF7E0)에 해당하는 행 상태가 공통 표에는
              // 'disabled'뿐이라 그것을 쓴다(색 대신 상태 문구·비활성 사유로 함께 알린다)
              rowState={(r) => (isBlocked(r.collection_status) ? 'disabled' : 'default')}
              // B-9 행 동작 규칙: 후보 → [수집 실행](AD-003) / 협의 중 → 비활성 / 적재됨 → 적재 페이지 뷰
              actions={(r) =>
                r.collection_status === 'LOADED' ? (
                  <Button
                    size="sm"
                    onClick={() => {
                      setTab('indexed')
                      setSelectedId(r.page_id)
                    }}
                  >
                    목록에서 보기
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    disabled={!canEdit || isBlocked(r.collection_status)}
                    disabledReason={
                      isBlocked(r.collection_status)
                        ? '협의가 끝나야 수집할 수 있습니다'
                        : '수집 실행 권한이 없습니다'
                    }
                    onClick={() => setNewPage({ candidateId: r.page_id })}
                  >
                    수집 실행
                  </Button>
                )
              }
              empty={
                <EmptyState
                  title="조건에 맞는 결과가 없습니다"
                  action={
                    <Button size="sm" onClick={resetFilters}>
                      필터 초기화
                    </Button>
                  }
                />
              }
            />
            <Pagination page={page} total={pages.data.total} onPageChange={setPage} />
          </div>
        ))}

      {/* 상세는 표 옆·아래가 아니라 모달로 뜬다 — 표는 전체 폭을 쓰고, [상세]를 누른 자리에서
          바로 결과가 보인다(사유는 DetailModal 주석) */}
      <DetailModal
        open={selected !== undefined}
        title={selected ? pageDetailTitle(selected) : '페이지 상세'}
        meta={selected ? pageDetailMeta(selected) : undefined}
        onClose={() => setSelectedId(null)}
        actions={
          selected && (
            <PageDetailActions
              page={selected}
              canRecrawl={canRunJob}
              canDelete={canEdit}
              recrawlPending={action.isPending}
              onRecrawl={runRecrawl}
              onDelete={(p) => setTarget({ kind: 'delete', page: p })}
              onCancelDelete={(p) => setTarget({ kind: 'cancelDelete', page: p })}
            />
          )
        }
      >
        {selected && <PageDetailPanel page={selected} />}
      </DetailModal>

      {modal && target && (
        <ConfirmModal
          open
          variant={modal.variant}
          title={modal.title}
          impact={modal.impact}
          reason="required"
          confirmLabel={modal.confirmLabel}
          pending={action.isPending}
          onConfirm={({ reason }) => runAction(target, reason ?? '')}
          onCancel={() => setTarget(null)}
        />
      )}
    </div>
  )
}

/** 확인 모달 문구. 삭제 문구는 B-8 목업 원문, 나머지는 같은 어투로 맞췄다(원문 없음) */
function confirmContent(target: ActionTarget) {
  if (target.kind === 'cancelDelete') {
    return {
      variant: 'normal' as const,
      title: '삭제 신청을 취소할까요?',
      confirmLabel: '삭제 신청 취소',
      impact: (
        <>
          <p>'{formatTarget(target.page.page_title, target.page.page_id)}'의 삭제 신청을 취소합니다.</p>
          <p>· 문서와 기존 검색 인덱스는 그대로 유지됩니다</p>
        </>
      ),
    }
  }
  if (target.kind === 'delete') {
    return {
      variant: 'danger' as const,
      title: '이 페이지를 삭제할까요?',
      confirmLabel: '삭제',
      impact: (
        <>
          <p>
            '{formatTarget(target.page.page_title, target.page.page_id)}'을 삭제 요청하고 '적용 대기'로
            전환합니다.
          </p>
          <p>· 재색인 전 : 삭제 요청 취소 가능</p>
          <p>· 재색인 후 : 다시 수집해 복구</p>
          <p>· 인덱스 교체 전까지 기존 인덱스로 정상 검색</p>
        </>
      ),
    }
  }
  return {
    variant: 'normal' as const,
    title: '재적재를 실행할까요?',
    confirmLabel: '재적재 실행',
    impact: (
      <>
        <p>적용 대기 {target.count}건을 인덱스에 반영합니다.</p>
        <p>· 인덱스를 바꾸는 작업은 한 번에 하나만 실행합니다</p>
        <p>· 기존 인덱스로 서비스는 정상 동작합니다</p>
      </>
    ),
  }
}
