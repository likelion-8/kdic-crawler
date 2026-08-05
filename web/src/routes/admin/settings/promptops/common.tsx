/** AD-008 · AD-009 두 화면이 함께 쓰는 껍데기.
 * 공통 UI 컴포넌트(components/ui)에 없는 것만 여기 둔다 — 카드·인라인 오류·편집 모달 3개뿐이고,
 * 다른 화면도 쓰게 되면 components/ui로 올린다(report shared_needed 참조). */
import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'
import { Button, DirtyDot, InfoHint } from '../../../../components/ui'
import { Separator } from '../../../../components/shadcn/separator'
import { isApiRequestError } from '../../../../lib/api/client'
import { cn } from '@/lib/utils'

/* --- 화면 공용 유틸 클래스 (구 BEM .plink 대체) --- */

/** 목업의 보라 링크 — 동작은 버튼이라 button 요소에 입힌다 */
export const linkClass =
  'inline-flex min-h-6 cursor-pointer items-center gap-1 rounded-sm p-0 text-[13px] font-medium text-primary underline-offset-4 transition-colors duration-200 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 disabled:cursor-not-allowed disabled:text-muted-foreground/70 disabled:no-underline'

export interface CardProps {
  /** 카드 제목(15px 세미볼드) */
  title: string
  /** 제목 왼쪽 lucide 아이콘(size-4) — 장식이라 aria-hidden */
  icon?: ReactNode
  /** 초안 수정 표시 — 제목 오른쪽 위 빨간 점(CM-DF-001 02절) */
  dirty?: boolean
  /** 제목 오른쪽 회색 메타(예: `v1.4 기준 · 07-30`) */
  meta?: ReactNode
  /** 제목 옆 ⓘ — 카드가 무엇을 하는지 설명하는 문단을 제목 아래 펼쳐 두는 대신 여기로 접는다.
   * 오류·경고나 지금 조작의 결과를 바꾸는 고지는 넣지 말 것(숨기면 사고다) */
  hint?: ReactNode
  /** 헤더 우측 액션 */
  actions?: ReactNode
  /** 852폭 풀 카드 여부 — 기본은 2컬럼 중 한 칸 */
  wide?: boolean
  children: ReactNode
}

export function Card({ title, icon, dirty = false, meta, hint, actions, wide = false, children }: CardProps) {
  const id = useId()
  return (
    <section
      /* 그림자 없는 헤어라인 섹션 — 그림자는 진짜 오버레이(모달·토스트)만 쓴다 */
      className={cn('rounded-md border bg-card p-5', wide && 'w-full')}
      aria-labelledby={id}
    >
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h2 className="inline-flex items-center gap-2 text-[15px] font-semibold" id={id}>
          {icon && (
            <span className="text-muted-foreground [&_svg]:size-4" aria-hidden="true">
              {icon}
            </span>
          )}
          <span className="inline-flex items-start gap-0.5">
            {title}
            {dirty && <DirtyDot label={`${title} 변경됨`} />}
          </span>
        </h2>
        {hint && <InfoHint label={`${title} 설명`}>{hint}</InfoHint>}
        {meta && <div className="text-xs text-muted-foreground">{meta}</div>}
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </header>
      <Separator className="my-3.5" />
      {children}
    </section>
  )
}

/** 확인 모달 안에 남길 오류 — `<dialog showModal()>`은 top layer라 화면 본문에 그린 오류가
 * 모달에 가려 보이지 않는다. 실패해도 모달을 닫지 말고 이 값을 ConfirmModal.error로 넘긴다(검증 D014).
 * 문구 규칙은 SectionError와 같다 — 계약 밖 예외까지 문구를 지어내지 않는다. */
export function modalError(error: unknown): { user_message: string; request_id?: string } | null {
  if (!error) return null
  const api = isApiRequestError(error) ? error : null
  return {
    user_message: api ? api.error.user_message : '처리 중 오류가 발생했습니다.',
    request_id: api?.error.request_id || undefined,
  }
}

/** 실패 패널은 화면 6곳이 함께 쓴다 — 공통 컴포넌트가 정본이고 여기서는 다시 내보내기만 한다 */
export { SectionError } from '../../../../components/ui'
export type { SectionErrorProps } from '../../../../components/ui'

export interface EditDialogProps {
  open: boolean
  /** 모달 제목 — 목업 원문 그대로 */
  title: string
  /** 제목 우측 도구(검색·추가 버튼) */
  tools?: ReactNode
  /** 하단 액션. 없으면 [닫기]만 */
  footer?: ReactNode
  onClose: () => void
  children: ReactNode
}

/** 편집 모달 — ConfirmModal과 같은 이유로 네이티브 <dialog>를 쓴다.
 * 포커스 트랩·ESC·트리거로 포커스 복귀·오버레이를 브라우저가 처리한다(CM-DF-004 09절). */
export function EditDialog({ open, title, tools, footer, onClose, children }: EditDialogProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const id = useId()

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) el.showModal()
    else if (!open && el.open) el.close()
    return () => {
      if (el.open) el.close()
    }
  }, [open])

  return (
    <dialog
      ref={ref}
      className="max-h-[calc(100vh-96px)] w-[min(852px,calc(100vw-48px))] rounded-lg border bg-card p-0 text-card-foreground shadow-lg backdrop:bg-black/40"
      aria-labelledby={id}
      onCancel={(e) => {
        e.preventDefault() // 닫힘은 부모 open으로만 — ESC도 [닫기]와 같게 취급
        onClose()
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose()
      }}
    >
      <header className="flex items-center gap-3 border-b px-5 py-4">
        <h2 className="text-[15px] font-semibold" id={id}>
          {title}
        </h2>
        {tools && <div className="ml-auto flex items-center gap-2">{tools}</div>}
        {/* 터치 타깃 44×44 (CM-DF-004 09절) */}
        <button
          type="button"
          className={cn(
            '-my-2 -mr-2 flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground transition-colors duration-200 outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring',
            !tools && 'ml-auto',
          )}
          onClick={onClose}
          aria-label="닫기"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </header>
      <div className="max-h-[56vh] overflow-auto px-5 py-4">{children}</div>
      <footer className="flex justify-end gap-2 border-t px-5 py-3">
        {footer ?? (
          <Button variant="secondary" onClick={onClose}>
            닫기
          </Button>
        )}
      </footer>
    </dialog>
  )
}
