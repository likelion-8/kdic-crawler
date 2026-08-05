/** 확인 모달 (위험 액션 공통) — CM-DF-001 01절.
 * 슬롯 ①제목 ②영향 고지 ③변경 대비(diff, 선택) ④변경 사유 ⑤액션 버튼.
 * 금지: 파괴적·보안·운영 정책 액션을 확인·사유·감사 기록 없이 실행(2.4절).
 *
 * 네이티브 <dialog showModal()>을 쓴다 — 포커스 트랩·ESC·트리거로 포커스 복귀·오버레이(::backdrop)를
 * 브라우저가 처리한다. 지원 환경이 최신 Chrome·Edge라 직접 구현할 이유가 없다(CM-DF-004 09절).
 * 스타일만 shadcn Dialog 룩(rounded-lg·shadow-lg·backdrop)으로 얹었다 —
 * 그림자·라운드는 '진짜 떠 있는 면'인 모달·토스트에만 허용한다(카드에는 쓰지 않는다). */
import { useEffect, useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { TriangleAlert, X } from 'lucide-react'
import { Button } from './Button'
import { Notice } from './Notice'
import { Input } from '../shadcn/input'

/** 변경 사유 최대 길이. 기획서에 값이 없어 피드백 자유의견(200자)과 맞췄다 — 기획서 확정 필요 */
export const REASON_MAX_LENGTH = 200

export interface ConfirmModalProps {
  open: boolean
  /** danger → 실행 버튼 Danger + 제목 옆 ⚠ (복구 불가 액션) */
  variant?: 'normal' | 'danger'
  /** ① '~할까요?' 의문형 한 줄. 무엇을 하는지만 쓴다(경고는 ②에서) */
  title: string
  /** ② 대상 건수·예상 소요·서비스 영향·복구 가능 여부. 되돌릴 수 없으면 '복구 불가' 명시 */
  impact: ReactNode
  /** ③ 설정·콘텐츠를 바꾸는 액션에만(AD-007/008/009). 삭제·재수집·재적재 계열은 넣지 않는다 */
  diff?: ReactNode
  /** ④ AD-DF-003 매트릭스의 '사유 입력' 열을 따름 */
  reason?: 'required' | 'optional' | 'none'
  reasonPlaceholder?: string
  /** 사유 라벨. 화면마다 원문이 다르다(계정 생성 모달은 '생성 사유') */
  reasonLabel?: string
  /** 사유 입력 아래 빨강 각주 — 기획서가 UI 카피로 못박은 줄이 있는 화면에서 쓴다 */
  reasonNote?: ReactNode
  /** 화면 고유의 추가 비활성 조건(예: 이름·이메일 공백). 사유·비밀번호 조건과 OR로 합쳐진다 */
  confirmDisabled?: boolean
  confirmDisabledReason?: string
  /** 실행 실패 시 모달 안에 남길 오류.
   * <dialog showModal()>은 top layer라 화면 본문에 그린 오류가 모달에 가려 안 보인다 —
   * 그래서 오류는 반드시 모달 내부에 그린다(검증 D014). */
  error?: { user_message: string; request_id?: string } | null
  /** 고위험 액션(전체 캐시 비우기·권한 변경·롤백). 마지막 인증 30분 경과 시에만 true */
  reauth?: boolean
  /** ⑤ 동사 라벨('삭제' '실행' '반영') */
  confirmLabel: string
  /** 제출 중. 성공 응답 후 부모가 open=false로 닫는다(기획서 미규정 — 12절 이슈 7 대응) */
  pending?: boolean
  onConfirm: (payload: { reason?: string; password?: string }) => void
  /** ESC · 배경 클릭 · [취소] 공통 */
  onCancel: () => void
}

export function ConfirmModal({
  open,
  variant = 'normal',
  title,
  impact,
  diff,
  reason = 'none',
  reasonPlaceholder = '예: 페이지 폐지 · 원문 URL 404 확인 (2026-07-31)',
  reasonLabel = '변경 사유',
  reasonNote,
  confirmDisabled: extraDisabled = false,
  confirmDisabledReason,
  error,
  reauth = false,
  confirmLabel,
  pending = false,
  onConfirm,
  onCancel,
}: ConfirmModalProps) {
  const ref = useRef<HTMLDialogElement>(null)
  const id = useId()
  const [reasonText, setReasonText] = useState('')
  const [password, setPassword] = useState('')
  const [reasonTouched, setReasonTouched] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) {
      el.showModal()
      setReasonText('')
      setPassword('')
      setReasonTouched(false)
    } else if (!open && el.open) {
      el.close() // close() 시점에 브라우저가 트리거로 포커스를 되돌린다
    }
    return () => {
      if (el.open) el.close()
    }
  }, [open])

  // 2.5절 실행 비활성 조건: (사유 필수 && 공백) || (재인증 && 비밀번호 공백).
  // '불일치'는 프론트가 알 수 없어 서버 검증에 맡긴다(12절 이슈 2).
  const reasonEmpty = reasonText.trim() === ''
  const reasonMissing = reason === 'required' && reasonEmpty
  const passwordMissing = reauth && password === ''
  const confirmDisabled = reasonMissing || passwordMissing || extraDisabled
  const disabledReason = reasonMissing
    ? `${reasonLabel}를 입력해야 실행할 수 있습니다`
    : passwordMissing
      ? '비밀번호를 확인해야 실행할 수 있습니다'
      : extraDisabled
        ? confirmDisabledReason
        : undefined

  const cancel = () => {
    if (!pending) onCancel() // 제출 중에는 닫지 않는다(중복 요청·상태 불일치 방지)
  }

  return (
    // 폭은 문서상 "520~560px 고정" — 목업값 560(w-140)으로 확정. 오버레이 40%는 문서 명시값
    <dialog
      ref={ref}
      className="w-140 max-w-[calc(100vw-2rem)] rounded-lg border bg-card p-6 text-card-foreground shadow-lg backdrop:bg-black/40"
      aria-labelledby={`${id}-title`}
      onCancel={(e) => {
        e.preventDefault() // 닫힘은 부모의 open으로만 — ESC도 취소와 동일 취급(2.3절)
        cancel()
      }}
      onClick={(e) => {
        if (e.target === ref.current) cancel() // 배경 클릭 = 취소(2.3절)
      }}
    >
      <h2
        className="relative flex items-center gap-2 pr-9 text-base font-semibold text-foreground"
        id={`${id}-title`}
      >
        {variant === 'danger' && (
          <span className="text-destructive" role="img" aria-label="되돌릴 수 없는 작업">
            <TriangleAlert className="size-4" aria-hidden="true" />
          </span>
        )}
        {title}
        {/* 닫기 ✕ — 목업 우상단 (검증 D080) */}
        <button
          type="button"
          className="absolute -top-1 right-0 flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors duration-200 hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          onClick={cancel}
          disabled={pending}
          aria-label="닫기"
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </h2>

      <div className="mt-3 text-sm leading-relaxed text-muted-foreground">{impact}</div>

      {/* ③ 변경 대비(diff) — 설정·콘텐츠 변경 액션에만 */}
      {diff && <div className="mt-3 rounded-md border bg-muted/50 p-3 text-xs">{diff}</div>}

      {reason !== 'none' && (
        <div className="mt-4" data-slot="confirm-field">
          <label
            className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-foreground"
            htmlFor={`${id}-reason`}
          >
            {reasonLabel}
            {/* '필수 / 선택' 라벨은 빨강 — CM-DF-001 실측(--color-attention) */}
            <span className="text-xs font-normal text-destructive">
              {reason === 'required' ? '필수' : '선택'}
            </span>
          </label>
          <Input
            id={`${id}-reason`}
            className="shadow-none"
            type="text"
            value={reasonText}
            maxLength={REASON_MAX_LENGTH}
            placeholder={reasonPlaceholder}
            aria-invalid={reasonTouched && reasonMissing ? true : undefined}
            aria-describedby={reasonTouched && reasonMissing ? `${id}-reason-error` : undefined}
            onChange={(e) => setReasonText(e.target.value)}
            onBlur={() => setReasonTouched(true)}
          />
          {/* 인라인 유효성 오류 — 기획서에 규격 없음(12절 이슈 8). 빨강 12px·필드 하단으로 정함 */}
          {reasonTouched && reasonMissing && (
            <p className="mt-1 text-xs text-destructive" id={`${id}-reason-error`}>
              {reasonLabel}를 입력해 주세요
            </p>
          )}
          {/* 기획서가 UI 카피로 못박은 각주 — 사유 입력 아래, 빨강 (검증 D091) */}
          {reasonNote && <p className="mt-1.5 text-xs text-destructive">{reasonNote}</p>}
        </div>
      )}

      {reauth && (
        <div className="mt-4" data-slot="confirm-field">
          <label
            className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-foreground"
            htmlFor={`${id}-password`}
          >
            비밀번호 확인
            <span className="text-xs font-normal text-destructive">필수</span>
          </label>
          <Input
            id={`${id}-password`}
            className="shadow-none"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
      )}

      {/* 실행 실패 — 모달을 닫지 않고 여기 남긴다. 문구는 서버 user_message 그대로.
          조치 전에 반드시 읽어야 하는 실패 결과라 옅은 색면 인셋(block)으로 세운다 */}
      {error && (
        <div className="mt-4" role="alert">
          <Notice
            tone="danger"
            variant="block"
            meta={error.request_id && `요청 ID ${error.request_id}`}
          >
            {error.user_message}
          </Notice>
        </div>
      )}

      {/* ⑤ 좌 [취소](Secondary) / 우 [실행](Primary·Danger) */}
      <div className="mt-6 flex items-center justify-end gap-3">
        <Button variant="secondary" onClick={cancel} disabled={pending}>
          취소
        </Button>
        <Button
          variant={variant === 'danger' ? 'danger' : 'primary'}
          disabled={confirmDisabled}
          disabledReason={disabledReason}
          loading={pending}
          onClick={() =>
            onConfirm({
              reason: reason === 'none' ? undefined : reasonText.trim(),
              password: reauth ? password : undefined,
            })
          }
        >
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  )
}
