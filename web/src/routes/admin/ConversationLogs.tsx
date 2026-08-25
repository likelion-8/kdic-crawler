/** AD-005 대화 로그 · 모니터링 (Figma 23:484).
 *
 * 구역: [0] 필터바 / 요약 스트립 / [1] 로그 목록 표(좌) + [2][3][4] 상세 패널(우).
 * 셸(GNB·헤더·세션)은 app/AdminLayout.tsx가 그린다 — 여기서 다시 그리지 않는다.
 *
 * 지켜야 할 것
 *  - 검색·표시는 전부 마스킹된 저장본. 원문 개인정보 복호화 진입점을 두지 않는다(Desc 2)
 *  - 진입 시 행을 자동 선택하지 않는다. 로그 정독이 목적이다(Desc 2)
 *  - 실패 행은 추적 패널 대신 오류 상세를 연다(Desc 2)
 *  - VIEWER는 집계만, 그 외 역할은 마스킹된 상세까지(Desc 0)
 *  - 조회·검색·내보내기·처리 완료는 모두 AD-011에 기록된다 */
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download } from 'lucide-react'
import {
  Badge,
  Button,
  ColorText,
  ConfirmModal,
  DEFAULT_PAGE_SIZE,
  DataTable,
  EmptyState,
  Loading,
  DetailModal,
  Notice,
  Pagination,
  Select,
  TextField,
  useToast,
} from '../../components/ui'
import type { Column } from '../../components/ui'
import { isApiRequestError } from '../../lib/api/client'
import { INTENT_LABEL, hasRole } from '../../lib/codes'
import type { TriageStatus } from '../../lib/codes'
import { formatMonthDayTime } from '../../lib/format'
import { useSession } from '../../app/session'
import { LogDetailPanel, logDetailMeta, logDetailTitle } from './logs/LogDetailPanel'
import {
  DEFAULT_FILTERS,
  FEEDBACK_LABEL,
  LOG_STATUS_LABEL,
  LOG_STATUS_TONE,
  MAX_CUSTOM_DAYS,
  PERIOD_OPTIONS,
  TRIAGE_LABEL,
  dash,
  daysBetween,
  exportLogs,
  fetchLogDetail,
  fetchLogs,
  fetchSummary,
  kstToday,
  logsQueryKey,
  setLogTriage,
} from './logs/api'
import type { ConversationLogRow, LogFilters } from './logs/api'

/** 실패는 화면 안에 남긴다(07.4절) — 옅은 색면 인셋. 색은 아이콘에만 쓰고 본문은 잉크로 둔다.
 * [다시 시도] 같은 조치는 본문에 섞지 말고 action으로 넘긴다 */
function ErrorNote({ action, children }: { action?: ReactNode; children: ReactNode }) {
  return (
    <div role="alert">
      <Notice tone="danger" variant="block" action={action}>
        {children}
      </Notice>
    </div>
  )
}

/** 결과가 너무 많으면 기간을 좁히도록 안내한다(Desc 0). 임계값이 기획서에 없어 프론트가 정했다 */
const TOO_MANY = 1000

const INTENT_OPTIONS = [
  { value: '', label: '전체' },
  { value: 'informational', label: '정보성' },
  { value: 'civil_petition', label: '민원성' },
]

const STATUS_OPTIONS = [
  { value: '', label: '전체' },
  { value: 'NORMAL', label: '정상' },
  { value: 'OUT_OF_SCOPE', label: '범위 외' },
  { value: 'FAILED', label: '실패' },
]

/** 목업은 '전체'만 보여 나머지 3값은 프론트가 확정했다(11 §L2 제안) */
const TRIAGE_FILTER_OPTIONS = [
  { value: '', label: '전체' },
  { value: 'OPEN', label: '미처리' },
  { value: 'RESOLVED', label: '처리 완료' },
]
const FEEDBACK_OPTIONS = [
  { value: '', label: '전체' },
  { value: 'up', label: '👍 좋아요' },
  { value: 'down', label: '👎 아쉬워요' },
  { value: 'none', label: '없음' },
]

export function ConversationLogs() {
  const { session } = useSession()
  const showToast = useToast()
  const queryClient = useQueryClient()

  const canViewDetail = hasRole(session?.role, 'OPERATOR') // VIEWER는 집계만
  const canExport = hasRole(session?.role, 'ADMIN') // 내보내기

  // 초기 필터는 URL 을 우선한다 — 대시보드 할 일 카드가 ?feedback=down 처럼 필터를 들고
  // 넘겨야 "대시보드가 센 건수와 같은 목록"이 열린다(바통). URL 에 없는 키는 기본값.
  // 종전에는 URL 을 읽지 않아 카드를 눌러도 필터 없는 오늘 목록이 열렸다.
  const [searchParams] = useSearchParams()
  const [filters, setFilters] = useState<LogFilters>(() => {
    const next: Record<string, string> = { ...DEFAULT_FILTERS }
    for (const key of Object.keys(DEFAULT_FILTERS)) {
      const v = searchParams.get(key)
      if (v !== null) next[key] = v
    }
    return next as unknown as LogFilters
  })
  const [page, setPage] = useState(1)
  // ?request= 로 특정 행을 바로 연다 — 되돌아가기 띠의 [로그로 돌아가기]가 그 대화를 들고 온다
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get('request'))
  // 처리 상태 확인 모달 — 완료 표시와 되돌리기가 같은 모달을 방향만 바꿔 쓴다
  const [triaging, setTriaging] = useState<{ id: string; to: TriageStatus } | null>(null)

  // 필터가 바뀌면 첫 페이지로 돌아가고 선택도 푼다(선택한 행이 결과에서 빠질 수 있다)
  function patch(next: Partial<LogFilters>) {
    setFilters((prev) => ({ ...prev, ...next }))
    setPage(1)
    setSelectedId(null)
  }

  const customDays =
    filters.period === 'custom' && filters.from && filters.to ? daysBetween(filters.from, filters.to) : 0
  const rangeError =
    filters.period === 'custom' && customDays > MAX_CUSTOM_DAYS
      ? `기간은 최대 ${MAX_CUSTOM_DAYS}일까지 지정할 수 있습니다`
      : undefined

  const logs = useQuery({
    queryKey: [...logsQueryKey, 'list', filters, page],
    queryFn: () => fetchLogs(filters, page, DEFAULT_PAGE_SIZE),
    // VIEWER는 집계만 본다(Desc 0) — 숨기는 데 그치지 않고 조회 자체를 보내지 않는다(조회도 AD-011에 남는다)
    enabled: canViewDetail && rangeError === undefined,
  })

  // 스트립은 기간 필터에 연동한다. 나머지 필터(성격·상태·피드백·처리·검색)는 반영하지 않는다 —
  // 스트립 자체가 상태별 분해라 상태를 걸면 고른 칸만 남고 나머지가 0 이 된다.
  const summary = useQuery({
    queryKey: [...logsQueryKey, 'summary', filters.period, filters.from, filters.to],
    queryFn: () => fetchSummary(filters),
    enabled: rangeError === undefined,
  })
  /** 스트립 첫 칸 라벨 — 어느 기간의 숫자인지 값 옆에서 바로 읽히게 한다 */
  const summaryLabel =
    filters.period === 'today' ? '오늘 대화'
      : filters.period === '7d' ? '7일 대화'
        : filters.period === '30d' ? '30일 대화'
          : '선택 기간 대화'

  const detail = useQuery({
    queryKey: [...logsQueryKey, 'detail', selectedId],
    queryFn: () => fetchLogDetail(selectedId!),
    enabled: selectedId !== null && canViewDetail,
  })

  const triage = useMutation({
    mutationFn: ({ reason }: { reason?: string }) =>
      setLogTriage(triaging!.id, triaging!.to, reason ?? ''),
    onSuccess: (_row, _vars, _ctx) => {
      const reopened = triaging!.to === 'NONE'
      setTriaging(null)
      void queryClient.invalidateQueries({ queryKey: logsQueryKey })
      showToast(reopened ? '처리 완료를 취소했습니다 · 미처리로 돌아갑니다' : '처리 완료로 표시했습니다')
    },
  })

  const exporting = useMutation({
    mutationFn: () => exportLogs(filters),
    // 파일이 실제로 저장된 뒤에 뜨는 토스트다 — '시작했습니다'는 접수증만 받던 시절 문구였다
    onSuccess: ({ rows }) => showToast(`${rows.toLocaleString()}건을 파일로 저장했습니다`),
  })

  const columns: Column<ConversationLogRow>[] = [
    {
      key: 'time',
      header: '일시',
      // 기간 필터가 최대 90일이라 시각만으로는 어느 날 것인지 알 수 없다(2026-08-20)
      width: '104px',
      render: (r) => <span className="nums">{formatMonthDayTime(r.occurred_at)}</span>,
    },
    {
      key: 'question',
      header: '질문',
      // 범위 외 행은 회색 텍스트로 구분한다(Desc 1). '상태' 열이 있어 색만으로 알리지는 않는다
      render: (r) => (
        <span className={r.status === 'OUT_OF_SCOPE' ? 'text-muted-foreground' : undefined}>
          {r.question_masked}
        </span>
      ),
    },
    {
      key: 'intent',
      header: '성격',
      width: '72px',
      render: (r) => (
        <span className={r.status === 'OUT_OF_SCOPE' ? 'text-muted-foreground' : undefined}>
          {r.intent === null ? '—' : INTENT_LABEL[r.intent]}
        </span>
      ),
    },
    {
      key: 'status',
      header: '상태',
      width: '128px',
      render: (r) => (
        <span className="inline-flex items-center gap-1.5">
          <ColorText tone={LOG_STATUS_TONE[r.status]}>{LOG_STATUS_LABEL[r.status]}</ColorText>
          {r.triage !== 'NONE' && (
            <Badge tone={r.triage === 'RESOLVED' ? 'green' : 'orange'} kind="status">
              {TRIAGE_LABEL[r.triage]}
            </Badge>
          )}
        </span>
      ),
    },
    {
      key: 'feedback',
      header: '피드백',
      width: '64px',
      render: (r) =>
        r.feedback === null ? (
          '—'
        ) : (
          <>
            <span aria-hidden="true">{r.feedback === 'up' ? '👍' : '👎'}</span>
            <span className="sr-only">{FEEDBACK_LABEL[r.feedback]}</span>
          </>
        ),
    },
    { key: 'sources', header: '출처', width: '56px', align: 'right', render: (r) => dash(r.source_count) },
    // 응답은 초 단위 소수 1자리(단위 표기 없음, 헤더만 '응답') — §1.4
    {
      key: 'latency',
      header: '응답',
      width: '56px',
      align: 'right',
      render: (r) => <span className="nums">{r.latency_s === null ? '—' : r.latency_s.toFixed(1)}</span>,
    },
  ]

  return (
    <div className="flex flex-col gap-5">
      {/* [0] 필터 · 접근 */}
      <section
        className="flex flex-wrap items-end gap-x-4 gap-y-3 rounded-md border bg-card px-5 py-4"
        aria-label="대화 로그 필터"
      >
        <Select
          layout="stack"
          label="기간"
          value={filters.period}
          options={PERIOD_OPTIONS}
          onChange={(v) =>
            patch({
              period: v as LogFilters['period'],
              from: v === 'custom' ? kstToday() : '',
              to: v === 'custom' ? kstToday() : '',
            })
          }
        />
        {filters.period === 'custom' && (
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              시작
              <input
                type="date"
                className="h-8 rounded-md border border-input bg-transparent px-2.5 text-sm text-foreground shadow-xs transition-[color,box-shadow] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                value={filters.from}
                max={filters.to || kstToday()}
                onChange={(e) => patch({ from: e.target.value })}
              />
            </label>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              종료
              <input
                type="date"
                className="h-8 rounded-md border border-input bg-transparent px-2.5 text-sm text-foreground shadow-xs transition-[color,box-shadow] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
                value={filters.to}
                max={kstToday()}
                onChange={(e) => patch({ to: e.target.value })}
              />
            </label>
          </div>
        )}
        <Select
          layout="stack"
          label="성격"
          value={filters.intent}
          options={INTENT_OPTIONS}
          onChange={(v) => patch({ intent: v as LogFilters['intent'] })}
        />
        <Select
          layout="stack"
          label="상태"
          value={filters.status}
          options={STATUS_OPTIONS}
          onChange={(v) => patch({ status: v as LogFilters['status'] })}
        />
        <Select
          layout="stack"
          label="피드백"
          value={filters.feedback}
          options={FEEDBACK_OPTIONS}
          onChange={(v) => patch({ feedback: v as LogFilters['feedback'] })}
        />
        {/* 처리 상태(2026-08-18) — 대시보드 '미처리 나쁨 평가' 카드가 triage=OPEN 을 들고
            들어온다. 완료 처리하면 이 필터의 목록과 카드 건수가 함께 줄어야 한다 */}
        <Select
          layout="stack"
          label="처리"
          value={filters.triage}
          options={TRIAGE_FILTER_OPTIONS}
          onChange={(v) => patch({ triage: v as LogFilters['triage'] })}
        />
        <div className="min-w-45 flex-[1_1_220px]">
          <TextField
            layout="stack"
            grow
            label="질문 검색"
            value={filters.q}
            placeholder="질문 · 답변 본문에서 찾기"
            onChange={(v) => patch({ q: v })}
          />
        </div>
        {canExport && (
          <Button className="ml-auto" size="sm" onClick={() => exporting.mutate()} loading={exporting.isPending}>
            <Download aria-hidden="true" />
            내보내기
          </Button>
        )}
      </section>

      {/* 조회 한도를 넘긴 것뿐이라 오류가 아니다 — 주의(warning)로 낮춘다 */}
      {rangeError && (
        <div role="alert">
          <Notice tone="warning" variant="block">
            {rangeError}
          </Notice>
        </div>
      )}
      {exporting.isError && (
        <ErrorNote>
          {isApiRequestError(exporting.error)
            ? exporting.error.error.user_message
            : '내보내기를 시작하지 못했습니다.'}
        </ErrorNote>
      )}

      {/* 요약 스트립 — 카드 5장이 아니라 세로 헤어라인으로 나뉜 한 줄. 누르면 해당 필터가 적용된다(Desc 1) */}
      <section
        className={
          summary.data ? 'grid grid-cols-2 divide-x overflow-hidden rounded-md border bg-card sm:grid-cols-3 xl:grid-cols-5' : undefined
        }
        aria-label={`${summaryLabel} 요약`}
      >
        {summary.isPending ? (
          <Loading text="요약을 불러오는 중…" />
        ) : summary.isError ? (
          <ErrorNote>
            {isApiRequestError(summary.error)
              ? summary.error.error.user_message
              : '요약을 불러오지 못했습니다.'}
          </ErrorNote>
        ) : (
          <>
            {/* 기간은 이미 고른 값이라 건드리지 않는다 — 상태·피드백만 푼다 */}
            <SummaryCell
              label={summaryLabel}
              value={`${summary.data.total}건`}
              onClick={() => patch({ status: '', feedback: '' })}
            />
            <SummaryCell
              label="정상"
              tone="green"
              value={String(summary.data.normal)}
              onClick={() => patch({ period: 'today', status: 'NORMAL' })}
            />
            <SummaryCell
              label="범위 외"
              tone="orange"
              value={String(summary.data.out_of_scope)}
              onClick={() => patch({ period: 'today', status: 'OUT_OF_SCOPE' })}
            />
            <SummaryCell
              label="실패"
              tone="red"
              value={String(summary.data.failed)}
              onClick={() => patch({ period: 'today', status: 'FAILED' })}
            />
            <div className="flex flex-col items-start gap-1.5 px-4 py-3">
              <span className="text-xs text-muted-foreground">피드백</span>
              <span className="nums flex items-center gap-1 text-xl leading-none font-bold">
                <button
                  type="button"
                  className="rounded-sm px-1.5 py-1 text-primary outline-none transition-colors duration-200 hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
                  onClick={() => patch({ period: 'today', feedback: 'up' })}
                >
                  <span aria-hidden="true">👍</span>
                  <span className="sr-only">좋아요</span> {summary.data.feedback_up}
                </button>
                <span aria-hidden="true">/</span>
                <button
                  type="button"
                  className="rounded-sm px-1.5 py-1 text-primary outline-none transition-colors duration-200 hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
                  onClick={() => patch({ period: 'today', feedback: 'down' })}
                >
                  <span aria-hidden="true">👎</span>
                  <span className="sr-only">아쉬워요</span> {summary.data.feedback_down}
                </button>
              </span>
            </div>
          </>
        )}
      </section>

      {!canViewDetail ? (
        // "VIEWER는 집계만" (Desc 0) — 목록·상세를 숨긴다. 문구는 기획서에 없어 프론트가 썼다
        <EmptyState title="조회자(VIEWER) 권한으로는 요약 집계만 볼 수 있습니다" />
      ) : (
        // 상세는 표 옆·아래가 아니라 모달로 뜬다 — 표는 전체 폭을 쓰고, [상세]를 누른 자리에서
        // 바로 결과가 보인다(사유는 DetailModal 주석)
        <div className="rounded-md border bg-card">
          {/* [1] 로그 목록 */}
          <section className="min-w-0 p-5" aria-label="대화 로그 목록">
            {rangeError ? (
              // 범위를 넘기면 조회를 보내지 않는다 — 끝나지 않는 로딩 대신 같은 안내를 목록 자리에 둔다
              <EmptyState title={rangeError} />
            ) : logs.isPending ? (
              <Loading text="대화 로그를 불러오는 중…" />
            ) : logs.isError ? (
              <ErrorNote
                action={
                  // 다시 눌러도 결과가 같은 오류에는 재시도를 권하지 않는다(client.ts 규약)
                  isApiRequestError(logs.error) && logs.error.error.retryable ? (
                    <Button size="sm" onClick={() => void logs.refetch()}>
                      다시 시도
                    </Button>
                  ) : undefined
                }
              >
                {isApiRequestError(logs.error)
                  ? logs.error.error.user_message
                  : '대화 로그를 불러오지 못했습니다.'}
              </ErrorNote>
            ) : (
              <>
                {/* 결과가 많다는 참고성 안내 — 문장을 경고색으로 칠하지 않고 아이콘만 주의색 */}
                {logs.data.total > TOO_MANY && (
                  <Notice tone="warning" className="mb-2">
                    결과가 {logs.data.total}건입니다. 기간을 좁혀 주세요.
                  </Notice>
                )}
                <DataTable
                  caption="대화 로그 — 시각 · 질문 · 성격 · 상태 · 피드백 · 출처 수 · 응답 시간"
                  columns={columns}
                  rows={logs.data.items}
                  rowKey={(r) => r.request_id}
                  rowState={(r) =>
                    r.request_id === selectedId ? 'selected' : r.status === 'FAILED' ? 'danger' : 'default'
                  }
                  onRowClick={(r) => setSelectedId(r.request_id)}
                  empty={
                    <EmptyState
                      title="조건에 맞는 결과가 없습니다"
                      action={
                        <Button size="sm" onClick={() => patch(DEFAULT_FILTERS)}>
                          필터 초기화
                        </Button>
                      }
                    />
                  }
                  // 행 클릭만으로는 키보드로 열 수 없어 조치 열에 버튼을 둔다(11 §M13)
                  actions={(r) => (
                    <Button size="sm" onClick={() => setSelectedId(r.request_id)}>
                      상세
                    </Button>
                  )}
                />
                <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                  <p className="text-xs text-muted-foreground">
                    {logs.data.total}건 중 {logs.data.total === 0 ? 0 : (page - 1) * logs.data.size + 1}–
                    {Math.min(page * logs.data.size, logs.data.total)} 표시
                  </p>
                  <Pagination
                    page={page}
                    total={logs.data.total}
                    pageSize={logs.data.size}
                    onPageChange={setPage}
                  />
                </div>
              </>
            )}
          </section>

        </div>
      )}

      {/* [2][3][4] 상세 추적 · 오류 상세 — 모달 */}
      <DetailModal
        open={selectedId !== null}
        title={detail.data ? logDetailTitle(detail.data) : '대화 상세'}
        meta={detail.data ? logDetailMeta(detail.data) : undefined}
        onClose={() => setSelectedId(null)}
      >
        {detail.isPending ? (
          <Loading text="상세를 불러오는 중…" />
        ) : detail.isError ? (
          <ErrorNote>
            {isApiRequestError(detail.error)
              ? detail.error.error.user_message
              : '상세를 불러오지 못했습니다.'}
          </ErrorNote>
        ) : detail.data ? (
          <LogDetailPanel
            detail={detail.data}
            canRun={canViewDetail}
            onResolve={() => setTriaging({ id: selectedId!, to: 'RESOLVED' })}
            onReopen={() => setTriaging({ id: selectedId!, to: 'NONE' })}
          />
        ) : null}
      </DetailModal>


      {/* 되돌리기에까지 사유를 요구하면 잘못 누른 완료를 못 풀어 건수가 거짓인 채로 남는다 —
          완료는 사유 필수, 취소는 선택이다(백엔드 patch_log 도 같은 규칙) */}
      {triaging !== null && (
        <ConfirmModal
          open
          title={triaging.to === 'NONE' ? '처리 완료를 취소할까요?' : '이 대화를 처리 완료로 표시할까요?'}
          reason={triaging.to === 'NONE' ? 'optional' : 'required'}
          reasonPlaceholder={
            triaging.to === 'NONE' ? '예: 잘못 눌렀습니다' : '예: 원인 확인 후 프롬프트 수정 반영'
          }
          confirmLabel={triaging.to === 'NONE' ? '처리 완료 취소' : '처리 완료'}
          pending={triage.isPending}
          onCancel={() => setTriaging(null)}
          onConfirm={(payload) => triage.mutate(payload)}
          impact={
            <div className="space-y-3">
              {triage.isError && (
                <ErrorNote>
                  {isApiRequestError(triage.error)
                    ? triage.error.error.user_message
                    : triaging.to === 'NONE'
                      ? '처리 완료를 취소하지 못했습니다.'
                      : '처리 완료로 표시하지 못했습니다.'}
                </ErrorNote>
              )}
              <p className="text-[13px]">
                {triaging.to === 'NONE'
                  ? '미처리로 돌아가 대시보드 할 일 건수에 다시 포함됩니다. 남아 있던 조치 사유는 지워지고, 취소한 사실이 관리자 활동 로그에 기록됩니다.'
                  : '처리 완료로 표시해도 사용자에게 다시 보내지는 않습니다. 조치 사유는 관리자 활동 로그에 기록됩니다.'}
              </p>
            </div>
          }
        />
      )}
    </div>
  )
}

interface SummaryCellProps {
  label: string
  value: string
  tone?: 'green' | 'orange' | 'red'
  onClick: () => void
}

/** 요약 스트립 한 칸 — 아이콘 없이 숫자가 주인공. 누르면 해당 필터가 즉시 적용된다 */
function SummaryCell({ label, value, tone, onClick }: SummaryCellProps) {
  return (
    <button
      type="button"
      className="flex min-h-11 flex-col items-start gap-1.5 px-4 py-3 text-left outline-none transition-colors duration-200 hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
      onClick={onClick}
    >
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="nums text-xl leading-none font-bold tracking-tight">
        {tone ? <ColorText tone={tone}>{value}</ColorText> : value}
      </span>
    </button>
  )
}
