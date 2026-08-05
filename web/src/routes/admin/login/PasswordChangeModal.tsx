/** AD-000 1-5 비밀번호 변경 (로그인 상태 · 모달).
 *
 * 위험 작업 재확인(30분)을 거치지 않는다 — "이 모달 자체가 현재 비밀번호를 요구하므로
 * 위험 작업 재확인(30분)을 따로 거치지 않습니다"(1-5 주석). 그래서 reauth·변경 사유가 없다.
 * 목업은 전용 모달이지만 헤더 `비밀번호 변경` + ✕ · 푸터 `취소`/`변경` 구성이 그대로라
 * 공통 ConfirmModal의 슬롯에 3필드 폼만 얹는다(새 모달을 만들지 않는다 · CM-DF-001 머리말).
 *
 * 🔴 진입점이 없다 — Description 1의 "헤더 계정 메뉴 [비밀번호 변경]"이 목업에 없어(08 issue 2)
 * 셸(app/AdminLayout)에 계정 메뉴가 생기면 거기서 이 모달을 열면 된다(report doc_fixes). */
import { useState } from 'react'
import { ConfirmModal } from '../../../components/ui'
import { Input } from '../../../components/shadcn/input'
import { Label } from '../../../components/shadcn/label'
import { apiRequest } from '../../../lib/api/client'
import type { ApiRequestError } from '../../../lib/api/client'
import { toRequestError } from './errors'

export interface PasswordChangeModalProps {
  open: boolean
  onClose: () => void
}

/** 규칙 안내 원문(1-5). 재설정 ③의 문구와 다르다 — 기획서가 화면마다 다른 규칙을 적었다(08 issue 20) */
const RULE = '10자 이상 · 영문/숫자/특수문자 조합 · 최근 사용한 비밀번호 재사용 불가'

export function PasswordChangeModal({ open, onClose }: PasswordChangeModalProps) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [nextAgain, setNextAgain] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [failure, setFailure] = useState<ApiRequestError | null>(null)

  // 규칙 안내 원문의 '10자 이상'만 프론트가 막고, 조합·재사용 여부는 서버 판정에 맡긴다(재설정 ③과 같은 기준)
  const incomplete = current === '' || next === '' || nextAgain === ''
  const mismatch = nextAgain !== '' && next !== nextAgain
  const tooShort = next !== '' && next.length < 10
  const blocked = incomplete
    ? '현재 비밀번호와 새 비밀번호를 입력해 주세요'
    : tooShort
      ? '새 비밀번호는 10자 이상이어야 합니다'
      : mismatch
        ? '새 비밀번호가 서로 다릅니다'
        : undefined

  const close = () => {
    setCurrent('')
    setNext('')
    setNextAgain('')
    setFailure(null)
    onClose()
  }

  async function submit() {
    if (blocked || submitting) return
    setSubmitting(true)
    setFailure(null)
    try {
      await apiRequest('/api/admin/password/change', {
        method: 'POST',
        body: { current_password: current, new_password: next },
      })
      // "변경 성공 시 지금 쓰는 세션은 유지하고 그 계정의 다른 세션만 종료합니다"(1-5 주석) — 서버 몫이다
      close()
    } catch (e) {
      // "현재 비밀번호가 틀리면 입력한 새 비밀번호는 유지한 채 오류를 표시합니다"(1-5 주석)
      setFailure(toRequestError(e))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <ConfirmModal
      open={open}
      title="비밀번호 변경"
      impact={
        <div className="space-y-4">
          <div className="space-y-2">
            <Label className="text-foreground" htmlFor="pwchange-current">
              현재 비밀번호
            </Label>
            <Input
              id="pwchange-current"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label className="text-foreground" htmlFor="pwchange-next">
              새 비밀번호
            </Label>
            <Input
              id="pwchange-next"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
          </div>

          <div className="space-y-2">
            <Label className="text-foreground" htmlFor="pwchange-next-again">
              새 비밀번호 확인
            </Label>
            <Input
              id="pwchange-next-again"
              type="password"
              autoComplete="new-password"
              aria-invalid={mismatch || undefined}
              aria-describedby={mismatch ? 'pwchange-error' : undefined}
              value={nextAgain}
              onChange={(e) => setNextAgain(e.target.value)}
            />
            {mismatch && (
              <p className="text-xs text-destructive" id="pwchange-error" role="alert">
                새 비밀번호가 서로 다릅니다
              </p>
            )}
          </div>

          <p className="text-xs text-muted-foreground">{RULE}</p>
        </div>
      }
      // 실패해도 모달을 닫지 않고 오류를 모달 안에 남긴다(top layer라 본문에 그리면 가려진다)
      error={
        failure && { user_message: failure.error.user_message, request_id: failure.error.request_id || undefined }
      }
      confirmDisabled={blocked !== undefined}
      confirmDisabledReason={blocked}
      confirmLabel="변경"
      pending={submitting}
      onConfirm={() => void submit()}
      onCancel={close}
    />
  )
}
