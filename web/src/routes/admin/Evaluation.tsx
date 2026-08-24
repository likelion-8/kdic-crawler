/** AD-006 평가셋 · 평가 결과 (`KDIC-AD-PG-006`).
 *
 * 영역은 둘뿐이다: [0] 평가셋(N) 문항 편집 / [1] 평가 실행 이력.
 * 이 화면은 평가를 **실행하지 않는다** — 실행은 AD-007 · AD-008 · 파이프라인이 하고 여기는 결과 원장이다(Screen Path).
 *
 * 편집 규칙(Desc 0)
 *  - 제거는 삭제가 아니라 '제외'. 문항·이력은 남고 개수에서만 빠지며 제외 사유가 필수다
 *  - 행 저장·제외는 '편집 중 · 변경 N건'에 쌓이고, [변경 반영] 1회로 버전 증가·사유 기록·재측정 1회가 함께 실행된다
 * 셸(GNB·헤더·세션)은 app/AdminLayout.tsx가 그린다 — 여기서 다시 그리지 않는다. */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { History, ListChecks } from 'lucide-react'
import {
  Badge, Button, ColorText, ConfirmModal, DataTable, DEFAULT_PAGE_SIZE, EmptyState, InfoHint, Loading,
  Notice, Pagination, Select, useToast,
} from '../../components/ui'
import type { Column } from '../../components/ui'
import { Input } from '../../components/shadcn/input'
import { cn } from '@/lib/utils'
import { INTENT_LABEL, QUESTION_TYPE_LABEL, hasRole } from '../../lib/codes'
import { useSession } from '../../app/session'
import { Card, SectionError, modalError } from './settings/promptops/common'
import { GateModal } from './evaluation/GateModal'
import { ItemEditor } from './evaluation/ItemEditor'
import { formatShortKst } from './evaluation/kst'
import { RUN_SOURCES, RUN_TARGETS, applyChanges, evalKeys, fetchItems, fetchRuns, fetchSchedule } from './evaluation/api'
import type { EvalItem, EvalItemInput, EvaluationRun } from './evaluation/api'

/** §2.2 표 하단 '페이지당 20 | 50 | 100' */
const PAGE_SIZES = [20, 50, 100]

/** 표 첫 셀의 진입 버튼 — 행 클릭과 같은 동작을 키보드로도 열어 준다.
 * 목업은 '시각'이 링크처럼 보이는 보라 볼드다(§2.3 스타일) */
const rowLinkClass =
  'nums cursor-pointer rounded-sm p-0 text-left font-semibold text-primary underline-offset-4 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1'

/** §2.3 '대상' — 초안이 RAG인지 프롬프트인지까지 구분한다(지표 축이 다르다) */
const TARGET_OPTIONS = [
  { value: '전체', label: '전체' },
  ...RUN_TARGETS.map((t) => ({ value: t, label: t })),
]

const SOURCE_OPTIONS = [
  { value: '전체', label: '전체' },
  ...RUN_SOURCES.map((s) => ({ value: s, label: s })),
]

/** 편집 묶음에 쌓이는 변경 1건 */
type Pending =
  | { kind: 'add'; input: EvalItemInput; item: EvalItem }
  | { kind: 'edit'; input: EvalItemInput; item: EvalItem }
  | { kind: 'exclude'; item_id: string; reason: string }

/** 실행 중인 행은 지표가 아직 0이라 그대로 찍으면 오해를 부른다(M3 gap 대응) */
const isRunning = (run: EvaluationRun) => run.status === 'RUNNING' || run.status === 'QUEUED'

export function Evaluation() {
  const { session } = useSession()
  const canEdit = hasRole(session?.role, 'EDITOR')
  const showToast = useToast()
  const queryClient = useQueryClient()

  const [page, setPage] = useState(1)
  const [size, setSize] = useState(DEFAULT_PAGE_SIZE)
  const [adding, setAdding] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [pending, setPending] = useState<Pending[]>([])
  const [excludingId, setExcludingId] = useState<string | null>(null)
  const [excludeReason, setExcludeReason] = useState('')
  const [applyOpen, setApplyOpen] = useState(false)

  const [target, setTarget] = useState('전체')
  const [source, setSource] = useState('전체')
  const [runPage, setRunPage] = useState(1)
  const [gateRunId, setGateRunId] = useState<string | null>(null)

  const items = useQuery({ queryKey: evalKeys.items(page, size), queryFn: () => fetchItems(page, size) })
  const schedule = useQuery({ queryKey: evalKeys.schedule, queryFn: fetchSchedule })
  const runs = useQuery({
    queryKey: evalKeys.runs(runPage, target, source),
    queryFn: () => fetchRuns(runPage, DEFAULT_PAGE_SIZE, target, source),
  })

  const adds = pending.filter((p) => p.kind === 'add')
  const edits = pending.filter((p) => p.kind === 'edit')
  const excludes = pending.filter((p) => p.kind === 'exclude')
  const changeCount = pending.length

  const apply = useMutation({
    mutationFn: (reason: string) =>
      applyChanges(
        {
          adds: adds.map((p) => p.input),
          edits: edits.map((p) => p.input),
          excludes: excludes.map((p) => ({ item_id: p.item_id, reason: p.reason })),
        },
        reason,
      ),
    onSuccess: (res) => {
      setPending([])
      setApplyOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['eval'] })
      showToast(`평가셋 v${res.testset_version}으로 반영했습니다 · 운영 재측정 1회를 실행합니다`)
    },
  })

  const excludeReasonOf = (id: string) => excludes.find((p) => p.item_id === id)?.reason
  const stagedOf = (id: string) => [...adds, ...edits].find((p) => p.item.item_id === id)

  const total = items.data?.total ?? 0
  const from = total === 0 ? 0 : (page - 1) * size + 1
  const to = Math.min(page * size, total)

  /** 추가 문항은 목록 맨 위에 꽂힌다(§2.5). 편집한 문항은 편집본으로 갈아 끼운다 */
  const listed = (items.data?.items ?? []).map((it) => stagedOf(it.item_id)?.item ?? it)
  const rows = page === 1 ? [...adds.map((p) => p.item), ...listed] : listed

  function dropPending(itemId: string) {
    setPending((list) =>
      list.filter((p) => (p.kind === 'exclude' ? p.item_id !== itemId : p.item.item_id !== itemId)),
    )
  }

  function saveItem(input: EvalItemInput, saved: EvalItem) {
    const kind: 'add' | 'edit' = editingId === null ? 'add' : 'edit'
    setPending((list) => [
      ...list.filter((p) =>
        p.kind === 'exclude' ? p.item_id !== saved.item_id : p.item.item_id !== saved.item_id,
      ),
      { kind, input, item: saved },
    ])
    // 연속 추가 — 저장 뒤에도 입력 행을 열어 둔다(§2.5 "계속해서 다음 문항을 이어서 추가")
    setAdding(kind === 'add')
    setEditingId(null)
  }

  function confirmExclude(itemId: string) {
    if (!excludeReason.trim()) return
    setPending((list) => [...list, { kind: 'exclude', item_id: itemId, reason: excludeReason.trim() }])
    setExcludingId(null)
    setExcludeReason('')
  }

  // 거르기·자르기는 서버가 한다. 여기서 다시 자르면 그 페이지 뒤가 조용히 사라진다
  const runRows = runs.data?.items ?? []
  const runTotal = runs.data?.total ?? 0
  // "최상단 운영 행에 '(현재 운영)' 뱃지를 답니다"(Desc 1) — 지금 상태가 곧 목록의 첫 운영 행이다.
  // 첫 페이지에서만 판정한다(뒷페이지의 첫 운영 행은 '지금'이 아니다)
  const currentOpsRunId =
    runPage === 1 ? runRows.find((r) => r.target === '운영 설정' && !isRunning(r))?.run_id : undefined

  /** 행 오른쪽 끝 '조치' — 상태에 따라 [제외] / 확정 입력 / 되돌리기로 바뀐다(§2.5·§2.6) */
  function rowActions(r: EvalItem) {
    const reason = excludeReasonOf(r.item_id)
    if (reason) {
      return (
        <span className="inline-flex items-center gap-2 text-xs">
          <ColorText tone="red">제외 예정 · 사유 : {reason}</ColorText>
          <Button size="sm" onClick={() => dropPending(r.item_id)}>
            되돌리기
          </Button>
        </span>
      )
    }
    const staged = stagedOf(r.item_id)
    if (staged) {
      return (
        <span className="inline-flex items-center gap-2 text-xs">
          {/* 반영 전 상태는 색이 아니라 굵기로 — 보라는 링크·현재 위치에만 쓴다 */}
          <strong className="font-medium text-foreground">
            {staged.kind === 'add' ? '추가됨 (반영 전)' : '수정됨 (반영 전)'}
          </strong>
          <Button size="sm" onClick={() => dropPending(r.item_id)}>
            되돌리기
          </Button>
        </span>
      )
    }
    if (!canEdit) return null
    if (excludingId === r.item_id) {
      return (
        <span className="inline-flex items-center gap-2 text-xs">
          <Button size="sm" onClick={() => setExcludingId(null)}>
            취소
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!excludeReason.trim()}
            disabledReason={!excludeReason.trim() ? '제외 사유는 필수입니다' : undefined}
            onClick={() => confirmExclude(r.item_id)}
          >
            확인
          </Button>
        </span>
      )
    }
    return (
      <Button
        size="sm"
        onClick={() => {
          setExcludingId(r.item_id)
          setExcludeReason('')
        }}
      >
        제외
      </Button>
    )
  }

  const itemColumns: Column<EvalItem>[] = [
    {
      key: 'item_id',
      header: '문항 ID',
      width: '18%',
      // 행 클릭이 인라인 편집의 유일한 진입점이라 키보드로도 닿게 첫 셀을 버튼으로 둔다(§2.7 3)
      render: (r) =>
        canEdit && !excludeReasonOf(r.item_id) ? (
          <button
            type="button"
            className={rowLinkClass}
            onClick={() => {
              setEditingId(r.item_id)
              setAdding(false)
            }}
          >
            {r.item_id}
          </button>
        ) : (
          r.item_id
        ),
    },
    {
      key: 'question',
      header: '질문',
      width: '32%',
      render: (r) =>
        excludingId === r.item_id ? (
          // "[제외] 클릭 시 행 안에서 사유를 바로 입력합니다(필수)" — §2.6 각주
          <span className="flex items-center gap-1.5">
            <label className="whitespace-nowrap text-xs text-danger-fg" htmlFor="ev-exclude-reason">
              제외 사유
            </label>
            <Input
              id="ev-exclude-reason"
              className="h-8 min-w-45 flex-1 border-destructive/60 focus-visible:border-destructive focus-visible:ring-destructive/25"
              value={excludeReason}
              placeholder="예: 중복 문항 (kmrs_proc_pl1과 동일 취지)"
              onChange={(e) => setExcludeReason(e.target.value)}
              onClick={(e) => e.stopPropagation()}
              onKeyDown={(e) => {
                if (e.key === 'Enter') confirmExclude(r.item_id)
              }}
            />
          </span>
        ) : (
          r.question
        ),
    },
    { key: 'business', header: '업무', render: (r) => r.business_function, width: '16%' },
    { key: 'type', header: '유형', render: (r) => QUESTION_TYPE_LABEL[r.question_type], width: '10%' },
    { key: 'intent', header: '성격', render: (r) => INTENT_LABEL[r.intent], width: '10%' },
  ]

  /** 버전이 바뀐 지점 = 바로 아래(더 오래된) 행과 평가셋 버전이 다른 행(Desc 1) */
  const versionStartIds = new Set(
    runRows.filter((r, i) => runRows[i + 1] && runRows[i + 1].testset_version !== r.testset_version)
      .map((r) => r.run_id),
  )

  const runColumns: Column<EvaluationRun>[] = [
    {
      key: 'started_at',
      header: '일시',
      width: '11%',
      // 행 전체가 클릭 대상이지만 키보드로도 닿아야 한다 — 첫 셀을 포커스 가능한 버튼으로 둔다
      render: (r) => (
        <button type="button" className={rowLinkClass} onClick={() => setGateRunId(r.run_id)}>
          {formatShortKst(r.started_at)}
        </button>
      ),
    },
    {
      key: 'target',
      header: '대상',
      width: '11%',
      render: (r) =>
        r.target === '운영 설정' ? (
          <strong>{r.target}</strong>
        ) : (
          <span className="text-muted-foreground">{r.target}</span>
        ),
    },
    {
      key: 'source',
      header: '출처',
      render: (r) => <span className="text-muted-foreground">{r.source}</span>,
      width: '16%',
    },
    {
      key: 'metrics',
      header: '핵심 결과',
      width: '30%',
      // 지표 축은 대상별로 다르다 — 라벨까지 서버가 준 그대로 잇는다(§2.3)
      render: (r) =>
        isRunning(r) ? (
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
            <span className="pulse-dot size-1.5 shrink-0 rounded-full bg-muted-foreground" aria-hidden="true" />
            실행 중
          </span>
        ) : (
          <span className="nums text-muted-foreground">
            {r.metrics.map((m) => `${m.label} ${m.value}`).join(' · ')}
          </span>
        ),
    },
    {
      key: 'gate',
      header: '판정 · 후속',
      render: (r) => {
        const badges = (
          <>
            {r.improved_by_composition && (
              <> <Badge tone="orange" kind="status">구성 변경으로 상승</Badge></>
            )}
            {versionStartIds.has(r.run_id) && (
              <> <Badge tone="purple" kind="status">평가셋 v{r.testset_version}부터</Badge></>
            )}
          </>
        )
        if (isRunning(r))
          return (
            <span className="inline-flex items-center gap-1.5">
              <span className="pulse-dot size-1.5 shrink-0 rounded-full bg-muted-foreground" aria-hidden="true" />
              <span className="font-medium text-muted-foreground">실행 중</span>
            </span>
          )
        if (r.gate.passed) {
          return (
            <>
              <ColorText tone="green">통과 ✓</ColorText>
              {r.run_id === currentOpsRunId && <strong className="text-foreground"> (현재 운영)</strong>}
              {r.follow_up && <span className="text-muted-foreground"> {r.follow_up}</span>}
              {badges}
            </>
          )
        }
        return (
          <>
            <ColorText tone="red">미달 ✗</ColorText>
            {r.gate.warning_reason && <span className="text-muted-foreground"> {r.gate.warning_reason}</span>}
            {badges}
          </>
        )
      },
    },
  ]

  return (
    <div className="flex flex-col gap-6">
      {/* ---------------- [0] 평가셋 (N) · 문항 편집 ---------------- */}
      <Card
        title={`평가셋 (${total})`}
        icon={<ListChecks />}
        actions={
          /* 권한 없는 버튼은 숨긴다. 서버가 최종 판정이라 403도 그대로 처리한다 */
          canEdit ? (
            <Button
              size="sm"
              disabled={adding}
              disabledReason={adding ? '입력 중인 문항을 먼저 저장하거나 취소해 주세요' : undefined}
              onClick={() => {
                setAdding(true)
                setEditingId(null)
              }}
            >
              + 문항 추가
            </Button>
          ) : undefined
        }
      >
        {changeCount > 0 && (
          <div className="mb-3" role="status">
            {/* 반영 전에 반드시 읽어야 하는 상태라 옅은 색면 인셋(block) */}
            <Notice
              tone="warning"
              variant="block"
              action={
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => setPending([])} disabled={apply.isPending}>
                    모두 취소
                  </Button>
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => setApplyOpen(true)}
                    disabled={apply.isPending}
                  >
                    변경 반영
                  </Button>
                </div>
              }
            >
              편집 중 · 변경 {changeCount}건 (추가 {adds.length}
              {edits.length > 0 && ` · 수정 ${edits.length}`} · 제외 {excludes.length}) · 아직 평가셋에 반영되지
              않았습니다
            </Notice>
          </div>
        )}

        {(adding || editingId !== null) && (
          <ItemEditor
            key={editingId ?? 'new'}
            item={editingId ? rows.find((r) => r.item_id === editingId) : undefined}
            onSave={saveItem}
            onCancel={() => {
              setAdding(false)
              setEditingId(null)
            }}
          />
        )}

        {items.isPending ? (
          <Loading text="평가셋을 불러오는 중…" />
        ) : items.isError ? (
          <SectionError error={items.error} onRetry={() => void items.refetch()} />
        ) : (
          <DataTable
            caption="평가셋 문항 목록"
            columns={itemColumns}
            rows={rows}
            rowKey={(r) => r.item_id}
            rowState={(r) =>
              excludeReasonOf(r.item_id) ? 'disabled' : stagedOf(r.item_id) ? 'selected' : 'default'
            }
            onRowClick={
              canEdit
                ? (r) => {
                    if (excludeReasonOf(r.item_id) || excludingId === r.item_id) return
                    setEditingId(r.item_id)
                    setAdding(false)
                  }
                : undefined
            }
            empty={
              <EmptyState
                title="평가셋에 문항이 없습니다"
                action={
                  canEdit ? (
                    <Button size="sm" onClick={() => setAdding(true)}>
                      + 문항 추가
                    </Button>
                  ) : undefined
                }
              />
            }
            /* 조치 버튼 클릭이 행 클릭(인라인 편집 열기)까지 번지지 않게 여기서 끊는다 */
            actions={(r) => (
              // eslint-disable-next-line jsx-a11y/no-static-element-interactions, jsx-a11y/click-events-have-key-events
              <span className="inline-flex items-center" onClick={(e) => e.stopPropagation()}>
                {rowActions(r)}
              </span>
            )}
          />
        )}

        <footer className="mt-3 flex flex-wrap items-center gap-4">
          <Pagination page={page} total={total} pageSize={size} onPageChange={setPage} />
          <p className="nums text-xs text-muted-foreground">
            {total}문항 중 {from}–{to} 표시
          </p>
          <p className="ml-auto text-xs text-muted-foreground">
            페이지당{' '}
            {PAGE_SIZES.map((n, i) => (
              <span key={n}>
                {i > 0 && <span aria-hidden="true"> | </span>}
                {/* 터치 타깃 확보(CM-DF-004 09절) — 시각적으로는 텍스트 링크로 보인다 */}
                <button
                  type="button"
                  className={cn(
                    'min-h-8 min-w-8 cursor-pointer rounded-sm px-1 text-muted-foreground transition-colors duration-200 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
                    n === size && 'font-semibold text-primary underline underline-offset-4',
                  )}
                  aria-pressed={n === size}
                  onClick={() => {
                    setSize(n)
                    setPage(1)
                  }}
                >
                  {n}
                </button>
              </span>
            ))}
          </p>
        </footer>
      </Card>

      {/* ---------------- [1] 평가 실행 이력 ---------------- */}
      <Card
        title="평가 실행 이력"
        icon={<History />}
        actions={
          <div className="flex flex-wrap items-center justify-end gap-3">
            {schedule.data && (
              <>
                {/* 점수 비교는 같은 평가셋 버전끼리만 유효하다(Desc 1) → 현재 버전을 항상 보인다.
                    '왜 버전을 보이나'라는 규칙은 배지 옆 ⓘ로 접는다(카드 하단 중복 문구를 대체) */}
                <span className="inline-flex items-center gap-0.5">
                  <Badge tone="purple" kind="status">
                    평가셋 v{schedule.data.testset_version}
                  </Badge>
                  <InfoHint label="평가셋 버전 설명" size="sm">
                    점수 비교는 같은 평가셋 버전끼리만 유효합니다. 문항을 추가·수정해 버전이 오르면
                    이전 버전 점수와 직접 비교하지 마세요.
                  </InfoHint>
                </span>
              </>
            )}
            <Select
              label="대상"
              value={target}
              options={TARGET_OPTIONS}
              onChange={(v) => {
                setTarget(v)
                setRunPage(1)
              }}
            />
            <Select
              label="출처"
              value={source}
              options={SOURCE_OPTIONS}
              onChange={(v) => {
                setSource(v)
                setRunPage(1)
              }}
            />
          </div>
        }
      >
        {runs.isPending ? (
          <Loading text="실행 이력을 불러오는 중…" />
        ) : runs.isError ? (
          <SectionError error={runs.error} onRetry={() => void runs.refetch()} />
        ) : (
          <DataTable
            caption="평가 실행 이력"
            columns={runColumns}
            rows={runRows}
            rowKey={(r) => r.run_id}
            rowState={(r) => (!isRunning(r) && !r.gate.passed ? 'danger' : 'default')}
            onRowClick={(r) => setGateRunId(r.run_id)}
            empty={
              <EmptyState
                title="조건에 맞는 실행 이력이 없습니다"
                action={
                  <Button
                    size="sm"
                    onClick={() => {
                      setTarget('전체')
                      setSource('전체')
                    }}
                  >
                    필터 초기화
                  </Button>
                }
              />
            }
          />
        )}

        {/* '같은 버전끼리만 비교' 규칙은 헤더 '평가셋 vN' 배지와 표 안 버전 구분 배지가 이미
            같은 말을 하고 있다 — 카드 하단에 한 번 더 적지 않는다. 규칙은 헤더 배지 옆 ⓘ에 있다 */}
        <footer className="mt-3">
          <Pagination page={runPage} total={runTotal} onPageChange={setRunPage} />
        </footer>
      </Card>

      <GateModal runId={gateRunId} onClose={() => setGateRunId(null)} />

      <ConfirmModal
        open={applyOpen}
        title={`변경 ${changeCount}건을 평가셋에 반영할까요?`}
        impact={
          <>
            <p>
              추가 {adds.length}
              {edits.length > 0 && ` · 수정 ${edits.length}`} · 제외 {excludes.length} — 평가셋 버전이 1 올라가고
              운영 자동 재측정이 1회 실행됩니다. 몇 건을 편집했든 반영 시 한 번뿐입니다.
            </p>
            <ul className="mt-2 list-disc space-y-0.5 pl-4.5 text-sm text-foreground">
              {pending.map((p) => (
                <li key={p.kind === 'exclude' ? p.item_id : p.item.item_id}>
                  {p.kind === 'exclude'
                    ? `제외 · ${p.item_id} · 사유 : ${p.reason}`
                    : `${p.kind === 'add' ? '추가' : '수정'} · ${p.item.item_id} · ${p.item.question}`}
                </li>
              ))}
            </ul>
          </>
        }
        reason="required"
        reasonPlaceholder="예: 착오송금 수수료 문항 보강 · 중복 문항 정리"
        error={modalError(apply.error)}
        confirmLabel="변경 반영"
        pending={apply.isPending}
        onConfirm={({ reason }) => apply.mutate(reason ?? '')}
        onCancel={() => {
          setApplyOpen(false)
          apply.reset() // 다음에 연 모달에 직전 실패가 남지 않도록
        }}
      />
    </div>
  )
}
