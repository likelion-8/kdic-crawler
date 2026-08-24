/** AD-008 ④ 초안 평가 — 평가셋(AD-006) 문항 고르기 모달.
 *
 * 왜 목록에서 고르게 하나: 종전에는 서버가 평가셋 앞 4건 + 범위외 앞 2건을 자동으로 집어
 * 썼다. 어느 문항으로 재는지 화면에 보이지도 않아서, 평가셋에 섞여 있던 빈 문항·`asdf1234`
 * 같은 것으로 판정이 나가고 있었다(2026-08-24 실측). 관리자가 무엇으로 재는지 보고 고를 수
 * 있어야 판정을 믿을 수 있다.
 *
 * 문항 문구를 여기서 고치지는 않는다 — 문항 편집은 평가셋(AD-006)의 일이고, 두 화면에서
 * 같은 것을 고치게 하면 어느 쪽이 정본인지 흐려진다. 여기서는 '고르기'만 한다.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Badge, Button, DetailModal, EmptyState, Loading } from '../../../../components/ui'
import { SectionError, linkClass } from './common'
import { fetchItems } from '../../evaluation/api'
import { EVAL_PICK_MAX } from './api'
import type { EvalPick } from './api'

/** 한 번에 불러오는 문항 수. 현행 평가셋이 89문항이라 한 장에 담긴다 —
 *  페이지를 나누면 페이지를 넘길 때 체크가 사라진 것처럼 보인다(선택은 페이지 밖에도 남는다). */
const PAGE_SIZE = 100

export interface EvalPickerDialogProps {
  open: boolean
  /** 지금 골라 둔 문항. 모달을 열 때 체크 상태의 시작점이 된다 */
  selected: EvalPick[]
  onClose: () => void
  onApply: (picks: EvalPick[]) => void
}

export function EvalPickerDialog({ open, selected, onClose, onApply }: EvalPickerDialogProps) {
  const items = useQuery({
    queryKey: ['admin', 'prompt', 'eval-picker'],
    queryFn: () => fetchItems(1, PAGE_SIZE),
    enabled: open,
  })
  const [checked, setChecked] = useState<Record<string, boolean>>({})

  const loaded = items.data
  const rows = loaded?.items ?? []

  // 열 때마다 현재 선택으로 초기화한다 — 닫고 다시 열면 마지막 [적용] 상태에서 시작해야 한다.
  // 기본값(서버가 평가셋 앞 6건을 문구만 준 것)은 item_id 가 없어 id 로 못 맞춘다 → 문구로
  // 맞춰 미리 체크한다. 안 그러면 카드는 '6건'인데 모달은 '0건 선택'으로 열려 어긋나 보인다.
  //
  // ⚠ 의존성은 items.data(캐시의 안정된 참조)여야 한다. rows 를 넣으면 매 렌더 새 배열이라
  //   setChecked → 리렌더 → 새 배열 → 다시 effect 로 무한 루프가 된다.
  useEffect(() => {
    if (!open) return
    const byId = new Set(selected.map((p) => p.item_id).filter(Boolean))
    const byText = new Set(selected.filter((p) => !p.item_id).map((p) => p.question))
    setChecked(
      Object.fromEntries(
        (loaded?.items ?? [])
          .filter((r) => byId.has(r.item_id) || byText.has(r.question))
          .map((r) => [r.item_id, true]),
      ),
    )
  }, [open, selected, loaded])
  const count = Object.values(checked).filter(Boolean).length
  const over = count > EVAL_PICK_MAX
  const inScopeCount = rows.filter((r) => checked[r.item_id] && r.expected_source).length

  const apply = () =>
    onApply(
      rows
        .filter((r) => checked[r.item_id])
        .map((r) => ({ item_id: r.item_id, question: r.question, in_scope: Boolean(r.expected_source) })),
    )

  return (
    <DetailModal
      open={open}
      title="평가 문항 고르기"
      meta={`평가셋(AD-006) 현행 버전의 활성 문항 · ${count}건 선택`}
      onClose={onClose}
      actions={
        <>
          <Button variant="secondary" onClick={onClose}>
            취소
          </Button>
          <Button
            onClick={apply}
            disabled={count === 0 || over || inScopeCount === 0}
            disabledReason={
              count === 0
                ? '문항을 하나 이상 고르세요'
                : over
                  ? `${EVAL_PICK_MAX}건까지 고를 수 있습니다`
                  : '안내 범위 안 문항을 하나 이상 고르세요'
            }
          >
            {count}건 적용
          </Button>
        </>
      }
    >
      {/* 89문항 목록에서 몇 건만 고르려면 먼저 비울 수단이 있어야 한다 — 하나씩 끄게 하면
          기본 6건이 체크된 상태에서 소수 선택이 사실상 불가능하다 */}
      {count > 0 && (
        <div className="mb-2 flex justify-end">
          <button type="button" className={linkClass} onClick={() => setChecked({})}>
            선택 해제
          </button>
        </div>
      )}
      {/* 상한과 비용을 고르는 자리에서 말한다 — 적용하고 실행한 뒤 400을 받으면 늦다 */}
      <p className="mb-3 text-xs text-muted-foreground">
        문항당 현행·초안 두 벌을 생성하므로 답변 생성은 선택 건수의 2배입니다(현재{' '}
        <span className="tabular-nums">{count * 2}</span>회). 최대 {EVAL_PICK_MAX}건까지 고를 수
        있습니다 — 그 이상은 생성 요청 한도에 걸립니다.
      </p>
      {over && (
        <p className="mb-3 text-xs font-medium text-danger-fg">
          {count}건을 골랐습니다. {EVAL_PICK_MAX}건 이하로 줄여 주세요.
        </p>
      )}
      {items.isPending ? (
        <Loading text="평가셋 문항을 불러오는 중…" />
      ) : items.isError ? (
        <SectionError error={items.error} onRetry={() => void items.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title="평가셋에 활성 문항이 없습니다" />
      ) : (
        <ul className="flex flex-col divide-y">
          {rows.map((r) => (
            <li key={r.item_id}>
              {/* 행 전체가 클릭 대상이다 — 체크박스만 노리면 44px 타깃(CM-DF-004 09절)을 못 채운다 */}
              <label className="flex min-h-11 cursor-pointer items-start gap-3 py-2">
                <input
                  type="checkbox"
                  className="mt-1 size-4 shrink-0"
                  checked={Boolean(checked[r.item_id])}
                  onChange={(e) =>
                    setChecked((prev) => ({ ...prev, [r.item_id]: e.target.checked }))
                  }
                />
                <span className="min-w-0 flex-1 text-[13px] break-keep">{r.question}</span>
                {/* 판정 기준이 반대라(근거를 써야 통과 / 안 써야 통과) 어느 쪽인지 보여야 한다.
                    기준은 기대 출처 유무이고, 최종 분류는 서버가 다시 정한다 */}
                <Badge tone={r.expected_source ? 'green' : 'orange'} kind="status">
                  {r.expected_source ? '범위 안' : '범위 밖'}
                </Badge>
              </label>
            </li>
          ))}
        </ul>
      )}
    </DetailModal>
  )
}
