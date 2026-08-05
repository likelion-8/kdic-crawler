/** AD-006 §2.4 — 이력 행 클릭 시 게이트 판정 상세 (모달).
 *
 * 목표 열은 CM-DF-004 05절이 정본이라 화면에서 고칠 수 없다 → 편집 UI를 절대 만들지 않는다(§2.4).
 * 미달 실행은 실패 문항 표를 함께 보여준다(§2.3 "클릭 시 실패 문항 상세를 엽니다").
 * 네이티브 <dialog showModal()>이라 포커스 트랩·ESC·트리거 포커스 복귀를 브라우저가 처리한다. */
import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ShieldCheck, TriangleAlert, X } from 'lucide-react'
import { ColorText, DataTable, Loading } from '../../../components/ui'
import type { Column } from '../../../components/ui'
import { SectionError } from '../settings/promptops/common'
import { evalKeys, fetchGate } from './api'
import type { GateCriterion, GateFailedItem } from './api'
import { formatShortKst } from './kst'

const CRITERIA_COLUMNS: Column<GateCriterion>[] = [
  { key: 'label', header: '기준', render: (r) => r.label, width: '34%' },
  // 읽기 전용 톤 — 목표값은 화면에서 수정할 수 없다
  {
    key: 'target',
    header: '목표',
    render: (r) => <span className="text-muted-foreground">{r.target}</span>,
    width: '22%',
  },
  {
    key: 'result',
    header: '결과',
    render: (r) => <span className="font-semibold text-foreground tabular-nums">{r.result}</span>,
    width: '22%',
  },
  {
    key: 'verdict',
    header: '판정',
    render: (r) =>
      r.passed ? (
        <ColorText tone="green">통과 ✓</ColorText>
      ) : (
        <ColorText tone="red">미달 ✗</ColorText>
      ),
    width: '22%',
  },
]

const FAILED_COLUMNS: Column<GateFailedItem>[] = [
  { key: 'item_id', header: '문항 ID', render: (r) => r.item_id },
  { key: 'question', header: '질문', render: (r) => r.question },
  { key: 'expected', header: '기대 출처', render: (r) => r.expected_source },
  { key: 'actual', header: '실제 top-1', render: (r) => r.actual_top1 },
  { key: 'score', header: '점수', render: (r) => r.score.toFixed(2), align: 'right' },
]

export interface GateModalProps {
  runId: string | null
  onClose: () => void
}

export function GateModal({ runId, onClose }: GateModalProps) {
  const ref = useRef<HTMLDialogElement>(null)

  const gate = useQuery({
    queryKey: evalKeys.gate(runId ?? ''),
    queryFn: () => fetchGate(runId!),
    enabled: runId !== null,
  })

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (runId !== null && !el.open) el.showModal()
    else if (runId === null && el.open) el.close()
    return () => {
      if (el.open) el.close()
    }
  }, [runId])

  const detail = gate.data
  const title = detail
    ? `게이트 판정 상세 : ${detail.target} · ${formatShortKst(detail.started_at)} · ${detail.source}`
    : '게이트 판정 상세'

  return (
    // 기준 표가 5열이라 확인 모달(560px)보다 넓다. 좁은 화면에서는 표가 가로 스크롤한다(§2.4)
    <dialog
      ref={ref}
      className="w-[min(760px,92vw)] rounded-lg border bg-card p-0 text-card-foreground shadow-lg backdrop:bg-black/40"
      aria-labelledby="gate-title"
      onCancel={(e) => {
        e.preventDefault()
        onClose()
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose()
      }}
    >
      <div className="flex items-start justify-between gap-3 border-b px-5 py-4">
        <h2 className="inline-flex items-center gap-2 text-[15px] font-semibold" id="gate-title">
          <ShieldCheck className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
          {title}
        </h2>
        {/* 터치 타깃 44×44 (CM-DF-004 09절) */}
        <button
          type="button"
          className="-my-2 -mr-2 flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors duration-200 outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          onClick={onClose}
          aria-label="닫기"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>

      <div className="space-y-4 px-5 py-4">
        {gate.isPending && <Loading text="판정 결과를 불러오는 중…" />}

        {/* 조회 실패는 토스트가 아니라 화면 안에 남긴다 (CM-DF-001 07.4절) */}
        <SectionError error={gate.error} onRetry={() => void gate.refetch()} />

        {detail && (
          <>
            {/* 표를 감싸던 액자를 걷어낸다 — 헤더 헤어라인과 행 구분선만으로 읽힌다 */}
            <DataTable
              caption="게이트 기준별 판정"
              columns={CRITERIA_COLUMNS}
              rows={detail.criteria}
              rowKey={(r) => r.label}
              rowState={(r) => (r.passed ? 'default' : 'danger')}
            />

            {detail.failed_items.length > 0 && (
              <section>
                <h3 className="mb-2 inline-flex items-center gap-1.5 text-sm font-semibold">
                  <TriangleAlert className="size-4 shrink-0 text-danger-fg" aria-hidden="true" />
                  실패 문항 {detail.failed_items.length}건
                </h3>
                <DataTable
                  caption="기준 미달로 걸린 문항"
                  columns={FAILED_COLUMNS}
                  rows={detail.failed_items}
                  rowKey={(r) => r.item_id}
                />
              </section>
            )}

            <p className="text-xs text-muted-foreground">최근 Smoke : {detail.latest_smoke}</p>
          </>
        )}
      </div>
    </dialog>
  )
}
