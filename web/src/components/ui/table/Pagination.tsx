/** 페이지네이션 — 기획서에 규격이 없어(CM-DF-001 12절 이슈 4) 프론트에서 정했다.
 * 기본 페이지 크기 20 · shadcn 스타일 버튼 그룹 · 현재 페이지는 색 외에 aria-current로도 알린다. */
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { buttonVariants } from '../../shadcn/button'

export const DEFAULT_PAGE_SIZE = 20
/** 한 번에 노출할 페이지 번호 개수 */
const WINDOW = 5

export interface PaginationProps {
  /** 1부터 시작 */
  page: number
  total: number
  pageSize?: number
  onPageChange: (page: number) => void
}

export function Pagination({ page, total, pageSize = DEFAULT_PAGE_SIZE, onPageChange }: PaginationProps) {
  const lastPage = Math.max(1, Math.ceil(total / pageSize))
  const start = Math.min(Math.max(1, page - Math.floor(WINDOW / 2)), Math.max(1, lastPage - WINDOW + 1))
  const pages = Array.from({ length: Math.min(WINDOW, lastPage) }, (_, i) => start + i)

  return (
    <nav className="flex items-center justify-center gap-1 py-3" aria-label="페이지 이동">
      <button
        type="button"
        className={cn(buttonVariants({ variant: 'ghost', size: 'icon-sm' }))}
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        aria-label="이전 페이지"
      >
        <ChevronLeft aria-hidden="true" />
      </button>
      {pages.map((p) => (
        <button
          key={p}
          type="button"
          className={cn(
            buttonVariants({ variant: p === page ? 'outline' : 'ghost', size: 'icon-sm' }),
            'tabular-nums shadow-none',
            // 현재 페이지는 색면이 아니라 글자색+굵기로 — 보라는 '현재 위치'에만(05.3절)
            p === page && 'font-semibold text-primary',
          )}
          aria-current={p === page ? 'page' : undefined}
          aria-label={`${p}페이지`}
          onClick={() => onPageChange(p)}
        >
          {p}
        </button>
      ))}
      <button
        type="button"
        className={cn(buttonVariants({ variant: 'ghost', size: 'icon-sm' }))}
        onClick={() => onPageChange(page + 1)}
        disabled={page >= lastPage}
        aria-label="다음 페이지"
      >
        <ChevronRight aria-hidden="true" />
      </button>
    </nav>
  )
}
