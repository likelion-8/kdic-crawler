/** 상세 모달 — 표의 [상세]를 눌렀을 때 열리는 읽기용 창.
 *
 * 왜 모달인가: 상세를 표 옆 칸에 두려면 2:1 배치가 필요한데, 관리자 표는 6~7열이라
 * 1536px 미만에서는 표가 눌려 마지막 열이 잘린다. 그래서 좁을 땐 상세를 표 **아래**로
 * 내렸더니 이번엔 [상세]를 눌러도 화면 밖(실측: 뷰포트 742px에 패널 top 908px)이라
 * 아무 일도 일어나지 않은 것처럼 보였다(사용자 지적).
 * 모달은 폭과 무관하게 늘 같은 자리에 뜨고, 표는 항상 전체 폭을 쓴다.
 *
 * ConfirmModal과 같은 네이티브 `<dialog showModal()>`이다 — 포커스 트랩·ESC·트리거로
 * 포커스 복귀·오버레이를 브라우저가 처리한다. 다른 점은 두 가지다.
 *  · 확인/취소가 아니라 **읽는 창**이라 푸터 액션을 강요하지 않는다(actions는 선택).
 *  · 내용이 길어 본문만 스크롤한다. 제목·닫기는 늘 보인다.
 *
 * ⚠ 위험 작업 확인은 여기 말고 ConfirmModal을 쓸 것 — 사유 입력·재인증·Danger 위계가 거기 있다. */
import { useEffect, useId, useRef } from 'react'
import type { ReactNode } from 'react'
import { X } from 'lucide-react'

export interface DetailModalProps {
  open: boolean
  /** 무엇의 상세인지 — 대상 이름을 쓴다(예: `페이지 삭제 요청 · 성공`) */
  title: ReactNode
  /** 제목 아래 회색 한 줄 — 식별자·시각 같은 부가 정보 */
  meta?: ReactNode
  /** 본문 아래 액션 줄. 없으면 그리지 않는다(읽기 전용 상세) */
  actions?: ReactNode
  onClose: () => void
  children: ReactNode
}

export function DetailModal({ open, title, meta, actions, onClose, children }: DetailModalProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const id = useId()

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) el.showModal()
    else if (!open && el.open) el.close() // close() 시점에 브라우저가 트리거로 포커스를 되돌린다
    return () => {
      if (el.open) el.close()
    }
  }, [open])

  return (
    // 상세는 확인 모달(560px)보다 넓다 — 표·청크 목록·전후 비교가 들어간다.
    // 높이는 화면의 85%까지만 쓰고 본문이 넘치면 본문만 스크롤한다.
    <dialog
      ref={ref}
      className="max-h-[85vh] w-200 max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-lg border bg-card p-0 text-card-foreground shadow-lg backdrop:bg-black/40 open:flex"
      aria-labelledby={`${id}-title`}
      onCancel={(e) => {
        e.preventDefault() // 닫힘은 부모의 open으로만 — ESC도 [닫기]와 동일 취급
        onClose()
      }}
      onClick={(e) => {
        if (e.target === ref.current) onClose() // 배경 클릭 = 닫기
      }}
    >
      <header className="flex shrink-0 items-start justify-between gap-4 border-b px-6 py-4">
        <div className="min-w-0">
          <h2 className="text-base font-semibold break-keep text-foreground" id={`${id}-title`}>
            {title}
          </h2>
          {meta && <p className="mt-0.5 text-xs text-muted-foreground">{meta}</p>}
        </div>
        <button
          type="button"
          className="-my-1.5 -mr-2 inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors duration-200 hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          aria-label="상세 닫기"
          onClick={onClose}
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </header>

      {/* 본문만 스크롤 — 제목과 액션은 늘 보인다 */}
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">{children}</div>

      {actions && (
        <footer className="flex shrink-0 flex-wrap items-center justify-end gap-2 border-t px-6 py-3">
          {actions}
        </footer>
      )}
    </dialog>
  )
}
