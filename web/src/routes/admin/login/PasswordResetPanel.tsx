/** AD-000 1-4 비밀번호 재설정(분실 시) — ① 재설정 요청 → ② 발송 안내 / 메일 링크 진입 시 ③ 새 비밀번호 설정.
 *
 * 3단은 '조작 후 상태' 목업이라 동시에 그리지 않는다(00-meta NOTATION `*` 규칙).
 * 라우트는 로그인 화면 하나뿐이므로 메일 링크는 `/admin/login?reset_token=...`으로 들어온다
 * (기획서 제안 경로 `/admin/password/reset/confirm`은 라우터에 없다 — report doc_fixes).
 *
 * 단계 표시는 1-4의 단계명(재설정 요청 · 발송 안내 · 새 비밀번호 설정) 그대로 쓴다. */
import { useState } from 'react'
import { Eye, EyeOff, MailCheck } from 'lucide-react'
import { Button, Notice } from '../../../components/ui'
import { Card, CardContent, CardHeader } from '../../../components/shadcn/card'
import { Input } from '../../../components/shadcn/input'
import { Label } from '../../../components/shadcn/label'
import { cn } from '@/lib/utils'
import { apiRequest } from '../../../lib/api/client'
import type { ApiRequestError } from '../../../lib/api/client'
import { toRequestError } from './errors'

/** 만료·사용된 재설정 링크의 상태코드. 서버 계약에 코드값이 없어(ApiError.code는 5종 고정)
 * HTTP 410 Gone으로 약속했다 — 정책 위반 400과 갈라야 ③에 머무를 수 있다(report backend_notes). */
const LINK_GONE = 410

export interface PasswordResetPanelProps {
  /** 메일 링크의 토큰. 있으면 ③부터 시작한다 */
  token: string | null
  onBackToLogin: () => void
}

/** ①·② 요청 흐름 / ③ 링크 진입 흐름 */
type Step = 'request' | 'sent' | 'confirm'

/** 1-4 단계명 원문 순서 — 단계 표시줄에 쓴다 */
const STEPS: { key: Step; label: string }[] = [
  { key: 'request', label: '재설정 요청' },
  { key: 'sent', label: '발송 안내' },
  { key: 'confirm', label: '새 비밀번호 설정' },
]

export function PasswordResetPanel({ token, onBackToLogin }: PasswordResetPanelProps) {
  const [step, setStep] = useState<Step>(token ? 'confirm' : 'request')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [passwordAgain, setPasswordAgain] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [failure, setFailure] = useState<ApiRequestError | null>(null)

  /** 확인란 불일치 문구는 기획서에 없어(08 issue 3) 프론트가 정했다 */
  const mismatch = passwordAgain !== '' && password !== passwordAgain
  // 규칙 안내 원문의 '10자 이상'만 프론트가 막고, 조합·아이디 포함 여부는 서버 판정에 맡긴다
  const canConfirm = password.length >= 10 && passwordAgain !== '' && !mismatch

  const stepIndex = STEPS.findIndex((s) => s.key === step)

  async function call(
    path: string,
    body: Record<string, unknown>,
    onDone: () => void,
    onFail?: (e: ApiRequestError) => void,
  ) {
    if (submitting) return
    setSubmitting(true)
    setFailure(null)
    try {
      await apiRequest(path, { method: 'POST', body })
      onDone()
    } catch (e) {
      // 예상 못 한 예외도 화면 안에 남긴다 — `void call(...)`이라 다시 던지면 아무도 잡지 못한다
      const err = toRequestError(e)
      setFailure(err)
      onFail?.(err)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="w-full max-w-125" aria-labelledby="reset-title">
      <Card className="gap-4 rounded-md py-8 shadow-none">
        <CardHeader className="gap-3 px-8">
          <h1 className="text-lg font-semibold text-foreground" id="reset-title">
            비밀번호 재설정
          </h1>
          {/* 3단 진행 표시 — 현재 단계는 색 + aria-current로 함께 알린다(CM-DF-004 09절) */}
          <ol className="flex flex-wrap items-center gap-1.5 text-xs" aria-label="재설정 진행 단계">
            {STEPS.map((s, i) => (
              <li
                key={s.key}
                className="flex items-center gap-1.5"
                aria-current={i === stepIndex ? 'step' : undefined}
              >
                {i > 0 && <span className="h-px w-4 bg-border" aria-hidden="true" />}
                {/* 알약이 아니라 사각 태그 — 현재 단계는 잉크 반전, 지난·남은 단계는 헤어라인 */}
                <span
                  className={cn(
                    'nums flex size-5 items-center justify-center rounded-[3px] border text-[11px] font-bold',
                    i === stepIndex
                      ? 'border-foreground bg-foreground text-background'
                      : i < stepIndex
                        ? 'border-border bg-muted text-foreground'
                        : 'border-border text-muted-foreground',
                  )}
                  aria-hidden="true"
                >
                  {i + 1}
                </span>
                <span className={i === stepIndex ? 'font-semibold text-foreground' : 'text-muted-foreground'}>
                  {s.label}
                </span>
              </li>
            ))}
          </ol>
        </CardHeader>

        <CardContent className="space-y-4 px-8">
          {/* 실패는 토스트가 아니라 화면 안에 남긴다(CM-DF-001 07.4절). 문구는 서버 user_message 그대로 */}
          {failure && (
            <div role="alert">
              <Notice tone="danger" variant="block">
                {failure.error.user_message}
              </Notice>
            </div>
          )}

          {step === 'request' && (
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault()
                void call('/api/admin/password/reset-request', { email: email.trim() }, () => setStep('sent'))
              }}
            >
              <div className="space-y-2">
                <Label htmlFor="reset-email">가입된 이메일</Label>
                <Input
                  id="reset-email"
                  className="h-11"
                  type="email"
                  autoComplete="email"
                  placeholder="admin@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <Button
                type="submit"
                variant="primary"
                className="h-11 w-full"
                loading={submitting}
                disabled={email.trim() === ''}
                disabledReason={email.trim() === '' ? '가입된 이메일을 입력해 주세요' : undefined}
              >
                재설정 링크 보내기
              </Button>
              <p className="text-xs text-muted-foreground">
                계정 존재 여부와 무관하게 같은 완료 안내를 표시합니다 (계정 탐색 · 등록 여부 확인 차단)
              </p>
              <button
                type="button"
                className="min-h-11 rounded-sm text-[13px] font-bold text-primary transition-colors duration-200 hover:text-accent-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:outline-none"
                onClick={onBackToLogin}
              >
                ← 로그인으로 돌아가기
              </button>
            </form>
          )}

          {step === 'sent' && (
            <div className="space-y-3">
              <p className="flex items-center gap-2 text-base font-bold text-foreground" role="status">
                <MailCheck className="size-5 shrink-0" aria-hidden="true" /> 재설정 링크를 보냈습니다
              </p>
              <p className="text-sm text-foreground">
                메일이 오지 않으면 스팸함을 확인하거나 잠시 후 다시 요청해 주세요.
              </p>
              <p className="text-xs text-muted-foreground">링크 유효 시간 30분 · 1회 사용</p>
              <Button variant="secondary" className="h-11 w-full" onClick={onBackToLogin}>
                로그인으로 돌아가기
              </Button>
            </div>
          )}

          {step === 'confirm' && (
            <form
              className="space-y-4"
              onSubmit={(e) => {
                e.preventDefault()
                // "만료·사용된 링크로 진입하면 안내 후 ① 화면으로 보냅니다"(1-4 주석) — 그 경우에만 되돌린다.
                // 비밀번호 정책 위반(400)·네트워크 오류는 ③에 머물러 입력을 지키고 오류만 띄운다(검증 D007)
                void call('/api/admin/password/reset-confirm', { token, password }, onBackToLogin, (e) => {
                  if (e.status === LINK_GONE) setStep('request')
                })
              }}
            >
              <div className="space-y-2">
                <Label htmlFor="reset-password">새 비밀번호</Label>
                <div className="relative">
                  <Input
                    id="reset-password"
                    className="h-11 pr-11"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  <button
                    type="button"
                    className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-md text-muted-foreground transition-colors duration-200 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:outline-none"
                    aria-label="비밀번호 표시"
                    aria-pressed={showPassword}
                    aria-controls="reset-password"
                    onClick={() => setShowPassword((v) => !v)}
                  >
                    {showPassword ? (
                      <EyeOff className="size-4" aria-hidden="true" />
                    ) : (
                      <Eye className="size-4" aria-hidden="true" />
                    )}
                  </button>
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="reset-password-again">새 비밀번호 확인</Label>
                <Input
                  id="reset-password-again"
                  className="h-11"
                  type="password"
                  autoComplete="new-password"
                  aria-invalid={mismatch || undefined}
                  aria-describedby={mismatch ? 'reset-password-error' : undefined}
                  value={passwordAgain}
                  onChange={(e) => setPasswordAgain(e.target.value)}
                />
                {mismatch && (
                  <p className="text-xs text-destructive" id="reset-password-error" role="alert">
                    새 비밀번호가 서로 다릅니다
                  </p>
                )}
              </div>

              <p className="text-xs text-muted-foreground">10자 이상 · 영문/숫자/특수문자 조합 · 아이디 포함 불가</p>
              <Button
                type="submit"
                variant="primary"
                className="h-11 w-full"
                loading={submitting}
                disabled={!canConfirm}
                disabledReason={!canConfirm ? '새 비밀번호를 두 칸 모두 같게 입력해 주세요' : undefined}
              >
                비밀번호 변경
              </Button>
              <p className="text-xs text-muted-foreground">
                저장 시 이 계정의 다른 세션을 모두 종료하고 로그인 화면으로 이동합니다
              </p>
            </form>
          )}
        </CardContent>
      </Card>
    </section>
  )
}
