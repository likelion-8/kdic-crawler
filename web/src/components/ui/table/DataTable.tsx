/** 데이터 표 — CM-DF-001 06절.
 * 행 상태 4종: 기본 / 선택 / 위험 강조 / 비활성.
 * 규칙: 강조는 배경색 하나로만 · 행 안 조치 버튼은 소형 Secondary(Danger는 모달에서만)
 *      · 표 우측 끝 열은 항상 '조치'다. 화면이 달라도 위치를 바꾸지 않는다.
 * → '조치' 열은 columns로 받지 않고 actions prop으로만 받아 위치를 강제한다.
 * 정렬·페이지·sticky 헤더는 기획서에 규격이 없어(12절 이슈 4) 프론트에서 정했다.
 *
 * ⚠ thead의 sticky 기준은 뷰포트가 아니라 아래 `overflow-x-auto` 래퍼다 — 가로 스크롤을 켜면
 * 세로축도 함께 스크롤 컨테이너가 되기 때문이다. 그래서 top은 0 말고 다른 값을 줄 수 없고
 * (주면 헤더가 표 안쪽으로 내려와 행을 덮는다), 페이지를 스크롤할 때 헤더는 표와 함께 올라간다.
 * 화면 상단 sticky 상태 바와 겹치는 문제는 그쪽 z-index를 이 헤더(z-10)보다 높게 잡아 푼다.
 * 스타일은 shadcn table 이식: 행 h-11 · 셀 px-3 · 헤더 text-xs muted · hover bg-muted/50. */
import { useId } from 'react'
import type { ReactNode } from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import { cn } from '@/lib/utils'
import { EmptyState } from '../EmptyState'

/** 행 상태는 CM-DF-001 06절 4종 그대로다. 한때 AD-002 '협의 중' 행의 주의색 배경(#FFF7E0)
 * 때문에 'warn'을 5번째로 뒀었는데, 정작 어느 화면도 쓰지 않았고 그 행은 조작이 막힌 행이라
 * 'disabled'가 의미상 맞다(KnowledgePages.tsx). 죽은 상태를 지웠다 — A-52 확정 2026-08-05. */
export type RowState = 'default' | 'selected' | 'danger' | 'disabled'

/* 행 상태 4종 — 강조는 배경색 하나로만(06절 규칙 2). 색은 시맨틱 토큰만.
 * 좌측 액센트 바는 쓰지 않는다. 선택 행도 보라 색면 대신 중립 배경 + 글자 굵기로 구분한다. */
const ROW_STATE: Record<RowState, string> = {
  default: 'bg-card',
  selected: 'bg-muted font-medium text-foreground',
  danger: 'bg-danger-soft/70 text-danger-fg',
  disabled: 'bg-muted text-muted-foreground cursor-not-allowed',
}

export interface Column<T> {
  key: string
  header: ReactNode
  render: (row: T) => ReactNode
  sortable?: boolean
  width?: string
  align?: 'left' | 'right'
}

export interface SortState {
  key: string
  dir: 'asc' | 'desc'
}

export interface DataTableProps<T> {
  /** 스크린리더용 표 설명 — 시각적으로는 숨긴다 */
  caption: string
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  /** 기본 'default'. 선택=상세 패널 연결 행, 위험 강조=실패·반복 차단, 비활성=조작 불가 */
  rowState?: (row: T) => RowState
  /** 마지막 '조치' 열. 소형 Secondary 버튼을 넣는다 */
  actions?: (row: T) => ReactNode
  /** '조치' 열 이름. 열 이름 옆에 ⓘ(InfoHint)를 달아 조작 규칙을 접을 때 쓴다 */
  actionsHeader?: ReactNode
  sort?: SortState
  onSortChange?: (sort: SortState) => void
  onRowClick?: (row: T) => void
  /** 행 단위로 클릭 가능 여부를 가른다(예: AD-004 실행 이력은 실패 행만 상세가 있다).
   * 없으면 비활성 아닌 모든 행이 클릭 가능하다. */
  rowClickable?: (row: T) => boolean
  /** 빈 표 — 기본은 07절 빈 상태를 그대로 재사용 */
  empty?: ReactNode
}

export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  rowState,
  actionsHeader = '조치',
  actions,
  sort,
  onSortChange,
  onRowClick,
  rowClickable,
  empty,
}: DataTableProps<T>) {
  const id = useId()
  const colCount = columns.length + (actions ? 1 : 0)

  const toggleSort = (key: string) => {
    if (!onSortChange) return
    onSortChange({ key, dir: sort?.key === key && sort.dir === 'asc' ? 'desc' : 'asc' })
  }

  const sortIcon = (key: string) => {
    if (sort?.key !== key) return <ArrowUpDown className="size-3.5 text-muted-foreground/70" aria-hidden="true" />
    return sort.dir === 'asc' ? (
      <ArrowUp className="size-3.5" aria-hidden="true" />
    ) : (
      <ArrowDown className="size-3.5" aria-hidden="true" />
    )
  }

  return (
    // 관리자 최소 폭 1024 — 넘치는 표는 가로 스크롤(12절 이슈 10)
    <div className="relative w-full overflow-x-auto">
      {/* 색만으로 알리지 않도록 위험·비활성 행에 텍스트 설명을 연결한다(CM-DF-004 09절) */}
      <span id={`${id}-danger`} className="sr-only">
        조치가 필요한 행
      </span>
      <span id={`${id}-disabled`} className="sr-only">
        조작할 수 없는 행
      </span>
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                style={{ width: c.width }}
                className={cn(
                  'sticky top-0 z-10 h-10 border-b border-border bg-card px-3 text-left align-middle text-[11px] font-medium whitespace-nowrap text-muted-foreground',
                  c.align === 'right' && 'text-right',
                )}
                aria-sort={
                  sort?.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined
                }
              >
                {c.sortable && onSortChange ? (
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 rounded-sm font-medium transition-colors duration-200 hover:text-foreground"
                    onClick={() => toggleSort(c.key)}
                  >
                    {c.header}
                    {sortIcon(c.key)}
                  </button>
                ) : (
                  c.header
                )}
              </th>
            ))}
            {actions && (
              <th
                scope="col"
                className="sticky top-0 z-10 h-10 border-b border-border bg-card px-3 text-left align-middle text-[11px] font-medium whitespace-nowrap text-muted-foreground"
              >
                {actionsHeader}
              </th>
            )}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={colCount} className="p-6">
                {empty ?? <EmptyState title="조건에 맞는 결과가 없습니다" />}
              </td>
            </tr>
          ) : (
            rows.map((row) => {
              const state = rowState?.(row) ?? 'default'
              const clickable = onRowClick && state !== 'disabled' && (rowClickable?.(row) ?? true)
              return (
                <tr
                  key={rowKey(row)}
                  className={cn(
                    'border-b border-border/70 transition-colors duration-200',
                    ROW_STATE[state],
                    state === 'default' && 'hover:bg-muted/50',
                    clickable && 'cursor-pointer',
                  )}
                  aria-current={state === 'selected' || undefined}
                  aria-disabled={state === 'disabled' || undefined}
                  aria-describedby={
                    state === 'danger'
                      ? `${id}-danger`
                      : state === 'disabled'
                        ? `${id}-disabled`
                        : undefined
                  }
                  onClick={clickable ? () => onRowClick(row) : undefined}
                >
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={cn(
                        'h-11 px-3 align-middle whitespace-nowrap',
                        c.align === 'right' && 'text-right',
                      )}
                    >
                      {c.render(row)}
                    </td>
                  ))}
                  {actions && <td className="h-11 px-3 align-middle whitespace-nowrap">{actions(row)}</td>}
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}
