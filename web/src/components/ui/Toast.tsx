/** 토스트 — CM-DF-001 07.1절 / 07.4절 공통 원칙.
 * 화면 하단 중앙 · 3초 후 자동 소멸 · 되돌리기가 필요하면 [실행 취소] 함께.
 * 성공만 토스트로 알린다. 실패는 화면 안에 남긴다(07.4절) — 그래서 tone 배리언트가 없다. */
import { createContext, useCallback, useContext, useState } from 'react'
import type { ReactNode } from 'react'

/** 자동 소멸 3초(문서 명시). [실행 취소]가 붙으면 3초로는 누르기 어려워 7초로 둔다(12절 이슈 12) */
const TOAST_MS = 3000
const TOAST_WITH_ACTION_MS = 7000

export interface ToastAction {
  label: string
  onClick: () => void
}

interface ToastItem {
  id: number
  message: string
  action?: ToastAction
}

type ShowToast = (message: string, action?: ToastAction) => void

const ToastContext = createContext<ShowToast | null>(null)

export function useToast(): ShowToast {
  const show = useContext(ToastContext)
  if (!show) throw new Error('useToast는 <ToastProvider> 안에서만 쓸 수 있습니다')
  return show
}

let seq = 0

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])

  const dismiss = useCallback((id: number) => {
    setItems((list) => list.filter((t) => t.id !== id))
  }, [])

  const show = useCallback<ShowToast>(
    (message, action) => {
      const id = ++seq
      setItems((list) => [...list, { id, message, action }])
      // ponytail: 타이머 핸들을 보관하지 않는다. 언마운트돼도 setState는 무해하고 토스트는 수명이 짧다
      setTimeout(() => dismiss(id), action ? TOAST_WITH_ACTION_MS : TOAST_MS)
    },
    [dismiss],
  )

  return (
    <ToastContext.Provider value={show}>
      {children}
      {/* 화면 하단 중앙 — 문서 명시. 여러 개면 위로 쌓는다 */}
      <div className="pointer-events-none fixed bottom-6 left-1/2 z-[100] flex -translate-x-1/2 flex-col-reverse items-center gap-2">
        {items.map((t) => (
          <Toast key={t.id} message={t.message} action={t.action} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export interface ToastProps {
  message: string
  action?: ToastAction
  onDismiss?: () => void
}

export function Toast({ message, action, onDismiss }: ToastProps) {
  return (
    // role="status"로 스크린리더에 자동 고지(CM-DF-004 09절)
    <div
      className="pointer-events-auto flex min-w-75 max-w-[calc(100vw-2rem)] items-center justify-between gap-3 rounded-md bg-foreground px-4 py-2.5 text-sm text-background shadow-lg"
      role="status"
    >
      <span className="flex-1">{message}</span>
      {action && (
        // [실행 취소] — 터치 타깃 44px 확보(CM-DF-004 09절)
        <button
          type="button"
          className="min-h-11 shrink-0 px-1 font-bold text-background underline underline-offset-2 transition-opacity duration-200 hover:opacity-80"
          onClick={() => {
            action.onClick()
            onDismiss?.()
          }}
        >
          {action.label}
        </button>
      )}
    </div>
  )
}
