/** 초안 평가 문항 고르기 — AD-007(RAG 파라미터) · AD-008(프롬프트·가드레일) 공통.
 *
 * 왜 [초안 평가]가 이걸 먼저 여나: 종전에는 서버가 평가셋에서 앞 몇 건을 자동으로 집어
 * 썼고, 어느 문항으로 재는지 화면에 보이지 않았다. 그래서 평가셋에 섞여 있던 빈 문항·
 * `asdf1234` 로 판정이 나가고 있었다(2026-08-24 실측). 판정을 믿으려면 무엇으로 재는지
 * 보고 고를 수 있어야 한다.
 *
 * 문항 문구를 여기서 고치지는 않는다 — 문항 편집은 평가셋(AD-006)의 일이고, 두 화면에서
 * 같은 것을 고치게 하면 어느 쪽이 정본인지 흐려진다. 여기서는 '고르기'만 한다.
 *
 * 두 화면이 재는 것이 달라 옵션으로 갈린다:
 *  · AD-008 전후 답변 비교 — 문항마다 현행·초안 답변을 **생성**한다(LLM 2콜/문항). 범위 밖
 *    문항도 필요하다(근거를 안 써야 통과하는 축). 그래서 scope='all' + 콜 수 상한.
 *  · AD-007 검색 품질 — 문항마다 **검색**만 한다(LLM 없음). 기대 출처가 없는 문항은 정확도를
 *    부당하게 깎아 애초에 제외 대상이라 scope='in' 으로 목록에서 뺀다.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Badge, Button, DetailModal, EmptyState, Loading } from '../../../components/ui'
import { SectionError } from '../../../components/ui'
import { fetchItems } from '../evaluation/api'

/** 한 번에 불러오는 문항 수. 현행 평가셋이 89문항이라 한 장에 담긴다 —
 *  페이지를 나누면 페이지를 넘길 때 체크가 사라진 것처럼 보인다(선택은 페이지 밖에도 남는다). */
const PAGE_SIZE = 100

export interface EvalPickerDialogProps {
  open: boolean
  /** 목록 범위 — 'in' 이면 기대 출처가 있는 문항만(AD-007) */
  scope?: 'in' | 'all'
  /** 고를 수 있는 최대 건수. 없으면 상한 없음 */
  maxPicks?: number
  /** 선택 건수에 대한 비용 한 줄. 없으면 그리지 않는다 */
  costHint?: (count: number) => string
  /** 기본 선택 — 다시 열 때 마지막 선택으로 시작한다 */
  initialIds?: string[]
  /** 처음 열 때 문구로 맞춰 미리 체크할 문항(서버 기본값은 id 가 없어 문구밖에 없다) */
  initialQuestions?: string[]
  running?: boolean
  onClose: () => void
  /** [평가 실행] — 고른 문항 id 를 넘긴다. 닫기는 호출부가 판단한다 */
  onRun: (ids: string[]) => void
}

export function EvalPickerDialog({
  open,
  scope = 'all',
  maxPicks,
  costHint,
  initialIds = [],
  initialQuestions = [],
  running = false,
  onClose,
  onRun,
}: EvalPickerDialogProps) {
  const items = useQuery({
    queryKey: ['admin', 'eval-picker'],
    queryFn: () => fetchItems(1, PAGE_SIZE),
    enabled: open,
  })
  const [checked, setChecked] = useState<Record<string, boolean>>({})

  const loaded = items.data
  const rows = (loaded?.items ?? []).filter((r) => scope === 'all' || Boolean(r.expected_source))

  // 열 때마다 시작점으로 초기화한다. id 로 못 맞추는 값(서버 기본값은 문구만 준다)은 문구로 맞춘다.
  // ⚠ 의존성은 items.data(캐시의 안정된 참조)여야 한다 — rows 는 매 렌더 새 배열이라
  //   setChecked → 리렌더 → 새 배열 → 다시 effect 로 무한 루프가 된다.
  useEffect(() => {
    if (!open) return
    const byId = new Set(initialIds)
    const byText = new Set(initialQuestions)
    setChecked(
      Object.fromEntries(
        (loaded?.items ?? [])
          .filter((r) => byId.has(r.item_id) || byText.has(r.question))
          .map((r) => [r.item_id, true]),
      ),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps -- 배열 리터럴 prop 은 참조가 매번 바뀐다
  }, [open, loaded])

  const picked = rows.filter((r) => checked[r.item_id])
  const count = picked.length
  const inScopeCount = picked.filter((r) => r.expected_source).length
  const over = maxPicks !== undefined && count > maxPicks
  const blocked = count === 0 || over || inScopeCount === 0

  return (
    <DetailModal
      open={open}
      title="초안 평가 문항 고르기"
      meta={`평가셋(AD-006) 현행 버전의 활성 문항 · ${count}건 선택`}
      onClose={onClose}
      actions={
        <>
          <Button variant="secondary" onClick={onClose} disabled={running}>
            취소
          </Button>
          <Button
            onClick={() => onRun(picked.map((r) => r.item_id))}
            loading={running}
            disabled={blocked}
            disabledReason={
              count === 0
                ? '문항을 하나 이상 고르세요'
                : over
                  ? `${maxPicks}건까지 고를 수 있습니다`
                  : '기대 출처가 있는 문항을 하나 이상 고르세요'
            }
          >
            {count}건으로 평가 실행
          </Button>
        </>
      }
    >
      {/* 89문항 목록에서 몇 건만 고르려면 먼저 비울 수단이 있어야 한다 */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {costHint ? costHint(count) : `고른 문항으로만 평가합니다 (현재 ${count}건)`}
          {maxPicks !== undefined && ` · 최대 ${maxPicks}건`}
        </p>
        <div className="flex shrink-0 gap-2">
          {/* [전체 선택]은 상한이 없는 화면에만 둔다 — 상한이 있는 쪽(AD-008)에서는 누르는
              순간 상한을 넘겨 곧바로 막히는 버튼이 된다. AD-007 은 종전에 홀드아웃 전체를
              재던 화면이라, 전체를 한 번에 고르는 수단이 없으면 그 동작을 재현할 수 없다 */}
          {maxPicks === undefined && rows.length > 0 && count < rows.length && (
            <Button
              size="sm"
              variant="secondary"
              disabled={running}
              onClick={() => setChecked(Object.fromEntries(rows.map((r) => [r.item_id, true])))}
            >
              전체 선택 ({rows.length})
            </Button>
          )}
          {count > 0 && (
            <Button size="sm" variant="secondary" onClick={() => setChecked({})} disabled={running}>
              선택 해제
            </Button>
          )}
        </div>
      </div>
      {over && (
        <p className="mb-3 text-xs font-medium text-danger-fg">
          {count}건을 골랐습니다. {maxPicks}건 이하로 줄여 주세요.
        </p>
      )}
      {items.isPending ? (
        <Loading text="평가셋 문항을 불러오는 중…" />
      ) : items.isError ? (
        <SectionError error={items.error} onRetry={() => void items.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState title="평가셋에 고를 수 있는 활성 문항이 없습니다" />
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
                  disabled={running}
                  onChange={(e) =>
                    setChecked((prev) => ({ ...prev, [r.item_id]: e.target.checked }))
                  }
                />
                <span className="min-w-0 flex-1 text-[13px] break-keep">{r.question}</span>
                {/* 판정 기준이 반대라(근거를 써야 통과 / 안 써야 통과) 어느 쪽인지 보여야 한다.
                    기준은 기대 출처 유무이고, 최종 분류는 서버가 다시 정한다 */}
                {scope === 'all' && (
                  <Badge tone={r.expected_source ? 'green' : 'orange'} kind="status">
                    {r.expected_source ? '범위 안' : '범위 밖'}
                  </Badge>
                )}
              </label>
            </li>
          ))}
        </ul>
      )}
    </DetailModal>
  )
}
