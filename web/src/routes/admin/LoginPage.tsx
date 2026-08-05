/** AD-000 관리자 로그인 · 인증 상태 (Figma 519:1087).
 *
 * 셸(GNB·헤더) 밖에서 렌더한다 — "인증 전에는 관리자 GNB와 운영 데이터를 노출하지 않습니다"(Description 0).
 * 성공하면 ?returnTo로 복귀하고 없으면 /admin으로 간다(Description 0).
 *
 * 인증 상태 4종(1-3)은 2×2 카드가 아니라 '상태'다. 응답 상태코드로 갈라 한 번에 하나만 그린다.
 *  401 → Case 1 로그인 실패 / 423 → Case 2 임시 잠금 / 403 → Case 3 권한 없음 / ?returnTo → Case 4 세션 만료
 * 오류 문구는 서버 user_message를 그대로 쓴다(PRD-02 §3). 카드 안 목업 문구는 서버가 내려줄 문구의 예시다. */
import { useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router'
import { Button, Notice } from '../../components/ui'
import { Card, CardContent, CardDescription, CardHeader } from '../../components/shadcn/card'
import { Checkbox } from '../../components/shadcn/checkbox'
import { Input } from '../../components/shadcn/input'
import { Label } from '../../components/shadcn/label'
import { apiRequest } from '../../lib/api/client'
import type { ApiRequestError } from '../../lib/api/client'
import { loadSession } from '../../app/session'
import { toRequestError } from './login/errors'
import { PasswordResetPanel } from './login/PasswordResetPanel'

/** 아이디 저장 — 저장 대상은 아이디뿐이다(비밀번호는 저장하지 않는다).
 * 저장 매체·만료가 기획서에 없어(08 issue 28) localStorage + 수동 해제로 정했다. */
const SAVED_ID_KEY = 'kdic.admin.saved_id'

/** 진입 안무 순서 — routes/chat/WelcomeScreen.tsx와 같은 패턴 */
const revealAt = (i: number) => ({ '--reveal-i': i }) as CSSProperties

interface LoginResponse {
  email: string
  name: string
  role: string
}

export function LoginPage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const returnTo = params.get('returnTo')
  /** 메일 링크로 진입하면 ③ 새 비밀번호 설정부터 시작한다(1-4 ③) */
  const resetToken = params.get('reset_token')

  const [mode, setMode] = useState<'login' | 'reset'>(resetToken ? 'reset' : 'login')
  const [loginId, setLoginId] = useState(() => localStorage.getItem(SAVED_ID_KEY) ?? '')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(() => localStorage.getItem(SAVED_ID_KEY) !== null)
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [failure, setFailure] = useState<ApiRequestError | null>(null)
  /** Case 4 안내는 [다시 로그인]으로 닫는다 */
  const [expiredNoticeOpen, setExpiredNoticeOpen] = useState(returnTo !== null)

  const idRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)

  // 임시 잠금(423) 중에는 제출을 막는다 — 다시 눌러도 서버가 같은 응답을 준다
  const locked = failure?.status === 423
  const canSubmit = loginId.trim() !== '' && password !== '' && !locked

  async function submit() {
    if (!canSubmit || submitting) return // 중복 제출 잠금(1-3)
    setSubmitting(true)
    setFailure(null)
    try {
      await apiRequest<LoginResponse>('/api/admin/login', {
        method: 'POST',
        body: { email: loginId.trim(), password },
      })
      if (remember) localStorage.setItem(SAVED_ID_KEY, loginId.trim())
      else localStorage.removeItem(SAVED_ID_KEY)
      await loadSession()
      void navigate(returnTo ?? '/admin', { replace: true })
    } catch (e) {
      // 예상 못 한 예외도 화면 안 오류 블록으로 흘린다 — `void submit()`이라 다시 던지면
      // 아무도 잡지 못하고 사용자에게는 피드백이 남지 않는다(검증 D083)
      const err = toRequestError(e)
      // 오류 시 아이디는 유지하되 비밀번호는 지운다(Description 1).
      // 단 서버에 닿지도 못한 경우(status 0)는 그대로 둬야 [다시 시도]가 같은 요청을 보낼 수 있다
      if (err.status !== 0) setPassword('')
      setFailure(err)
    } finally {
      setSubmitting(false)
    }
  }

  if (mode === 'reset') {
    return (
      <LoginShell>
        <PasswordResetPanel token={resetToken} onBackToLogin={() => setMode('login')} />
      </LoginShell>
    )
  }

  return (
    <LoginShell>
      <form
        className="w-full"
        onSubmit={(e) => {
          e.preventDefault() // Enter로 제출(Description 1)
          void submit()
        }}
      >
        {/* 폼 카드는 뜨지 않는다 — 흰 지면 + 1px 보더 + 여백 */}
        <Card className="gap-4 rounded-md py-8 shadow-none">
          <CardHeader className="reveal gap-1 px-8" style={revealAt(1)}>
            <h1 className="text-lg font-semibold text-foreground">관리자 로그인</h1>
            <CardDescription>등록된 관리자 계정으로 로그인해 주세요.</CardDescription>
          </CardHeader>
          <CardContent className="reveal space-y-4 px-8" style={revealAt(2)}>
            {/* Case 4 · 세션 만료 — 보호된 URL에서 넘어왔을 때만(RequireAuth가 returnTo를 붙인다) */}
            {expiredNoticeOpen && failure === null && (
              <div role="status">
                <Notice
                  tone="info"
                  variant="block"
                  action={
                    <Button
                      size="sm"
                      onClick={() => {
                        setExpiredNoticeOpen(false)
                        idRef.current?.focus()
                      }}
                    >
                      다시 로그인
                    </Button>
                  }
                >
                  안전한 이용을 위해 세션이 종료되었습니다. 다시 로그인하면 이전 화면으로 돌아갑니다.
                </Notice>
              </div>
            )}

            {failure && (
              <FailureState
                failure={failure}
                onDismiss={() => {
                  setFailure(null)
                  passwordRef.current?.focus()
                }}
                onRetry={() => void submit()}
                onOtherAccount={() => {
                  setFailure(null)
                  setLoginId('')
                  setPassword('')
                  idRef.current?.focus()
                }}
                onBack={() => {
                  // 보호된 URL로 직접 들어온 경우 뒤로 갈 곳이 없을 수 있다(08 issue 21) → 챗봇 첫 화면으로
                  if (window.history.length > 1) void navigate(-1)
                  else void navigate('/')
                }}
              />
            )}

            <div className="space-y-2">
              <Label htmlFor="login-id">아이디 또는 이메일</Label>
              <Input
                ref={idRef}
                id="login-id"
                className="h-11"
                type="text"
                autoComplete="username"
                placeholder="admin@example.com"
                value={loginId}
                onChange={(e) => setLoginId(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="login-password">비밀번호</Label>
              <div className="relative">
                <Input
                  ref={passwordRef}
                  id="login-password"
                  className="h-11 pr-11"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="비밀번호를 입력하세요"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                {/* 아이콘 단독 버튼 — 상태는 aria-pressed, 이름은 aria-label(CM-DF-004 09절 · 44×44 타깃) */}
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-md text-muted-foreground transition-colors duration-200 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:outline-none"
                  aria-label="비밀번호 표시"
                  aria-pressed={showPassword}
                  aria-controls="login-password"
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

            <div className="flex min-h-11 items-center justify-between gap-3">
              <Label className="cursor-pointer text-[13px] font-normal text-foreground">
                <Checkbox checked={remember} onCheckedChange={(v) => setRemember(v === true)} />
                아이디 저장
              </Label>
              <button
                type="button"
                className="min-h-11 rounded-sm text-[13px] font-bold text-primary transition-colors duration-200 hover:text-accent-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:outline-none"
                onClick={() => setMode('reset')}
              >
                비밀번호 재설정
              </button>
            </div>

            <div>
              <Button
                type="submit"
                variant="primary"
                className="h-11 w-full"
                loading={submitting}
                disabled={!canSubmit}
                // 비활성 버튼은 왜 못 누르는지 함께 쓴다(CM-DF-001 03절 규칙 3). 두 문구 모두 기획서에 없어 프론트가 정했다
                disabledReason={
                  locked ? '임시 잠금이 풀린 뒤 다시 시도할 수 있습니다' : !canSubmit ? '아이디와 비밀번호를 입력해 주세요' : undefined
                }
              >
                {submitting ? '로그인 중…' : '로그인'}
              </Button>
            </div>

            {/* 안내 문구에는 아이콘을 달지 않는다 — 라벨마다 붙는 아이콘은 장식이다 */}
            <ul className="space-y-1.5 border-t border-border pt-4 text-xs leading-relaxed text-muted-foreground">
              <li>공용 기기에서는 아이디 저장을 사용하지 마세요.</li>
              <li>비밀번호 재설정은 가입 메일의 링크로 진행됩니다.</li>
              <li>5회 실패 시 10분간 제한됩니다.</li>
            </ul>
          </CardContent>
        </Card>
      </form>
    </LoginShell>
  )
}

/** 좌 브랜드 지면 + 우 인증 워크스페이스 2컬럼(1-1).
 * 보라 색면으로 화면 절반을 채우거나 장식 원호를 깔지 않는다 — 흰 지면 + 헤어라인 구획 + 활자만 쓴다. */
function LoginShell({ children }: { children: ReactNode }) {
  useEffect(() => {
    // 관리자 화면은 라이트 고정(tokens.css). 로그인은 AdminLayout 밖이라 여기서 따로 건다
    const root = document.documentElement
    const previous = root.dataset.theme
    root.dataset.theme = 'light'
    return () => {
      if (previous === undefined) delete root.dataset.theme
      else root.dataset.theme = previous
    }
  }, [])

  return (
    // 좌우 분할을 걷어냈다 — 한쪽이 비어 있는 2단 구성은 '미완성'으로 읽힌다.
    // 기관 도구답게 상단 식별 띠 + 단일 컬럼으로 세운다.
    <div className="flex min-h-full flex-col bg-background">
      <header className="reveal border-b border-border px-6 py-4 lg:px-10" style={revealAt(0)}>
        {/* 워드마크 락업 — 브랜드 700 / 나머지 300. 장식 도형 없이 활자만 */}
        <p className="text-[15px] tracking-tight">
          <span className="font-bold text-primary">예솜24</span>{' '}
          <span className="font-light text-muted-foreground">Admin</span>
        </p>
      </header>
      <main className="flex flex-1 items-start justify-center px-6 py-14 lg:py-20">
        <div className="w-full max-w-125">
          <div className="reveal mb-7" style={revealAt(1)}>
            <p className="text-2xl leading-snug text-foreground">
              <span className="font-bold">예솜24</span>{' '}
              <span className="font-light text-muted-foreground">관리자 페이지</span>
            </p>
          </div>
          {children}
        </div>
      </main>
      <footer className="border-t border-border px-6 py-4 text-xs text-muted-foreground lg:px-10">
        예금보험공사 · 관리자 전용 화면입니다.
      </footer>
    </div>
  )
}

interface FailureStateProps {
  failure: ApiRequestError
  onDismiss: () => void
  onRetry: () => void
  onOtherAccount: () => void
  onBack: () => void
}

/** 인증 상태 Case 1~3. 문구는 서버 user_message 그대로, 액션만 상태별로 다르다(1-3) */
function FailureState({ failure, onDismiss, onRetry, onOtherAccount, onBack }: FailureStateProps) {
  const { status } = failure
  // 색만으로 알리지 않는다 — 상태 이름을 제목 줄에 텍스트로 함께 쓴다(CM-DF-004 09절).
  // 기획서 1-3이 정의한 상태는 4종뿐이다. 서버 미도달(0)·서버 오류(5xx)는 자격 증명 문제가 아니므로
  // '로그인 실패'라고 단정하지 않고 중립 표기를 쓴다(검증 D030 · 문구는 기획서에 없어 프론트가 정함)
  const credentials = status === 401
  const caption = status === 423 ? '임시 잠금' : status === 403 ? '권한 없음' : credentials ? '로그인 실패' : '요청 실패'
  // 차단된 실패(danger) / 풀리면 다시 되는 잠금(warning) / 계정이 잘못 왔을 뿐인 권한 없음(info)
  const tone = status === 423 ? 'warning' : status === 403 ? 'info' : 'danger'

  return (
    <div role="alert">
      <Notice
        tone={tone}
        variant="block"
        title={caption}
        meta={failure.error.request_id && `요청 ID ${failure.error.request_id}`}
      >
        {failure.error.user_message}
        {/* 버튼이 최대 3개까지 늘어나 우측 action 슬롯에 넣으면 본문이 눌린다 — 본문 아래에 둔다 */}
        <div className="mt-2.5 flex flex-wrap gap-2">
          {status === 403 ? (
            <>
              <Button size="sm" onClick={onBack}>
                이전 화면
              </Button>
              {/* 목업은 `[다른 계정]`, Description 3은 `[다른 계정으로 로그인]` — 두 문구가 다르다(08 issue 9).
                  무엇을 하는 버튼인지가 분명한 Description 쪽을 택했다(report doc_fixes로 확정 요청) */}
              <Button size="sm" onClick={onOtherAccount}>
                다른 계정으로 로그인
              </Button>
            </>
          ) : (
            // 아이디·비밀번호가 잘못된 게 아닌 실패에는 [다시 입력]을 띄우지 않는다.
            // 재시도 수단은 retryable일 때의 [다시 시도]뿐이다(PRD-02 §3-b)
            (credentials || status === 423) && (
              <Button size="sm" onClick={onDismiss}>
                {status === 423 ? '확인' : '다시 입력'}
              </Button>
            )
          )}
          {/* retryable일 때만 [다시 시도] — 429·401은 자동·수동 재호출 대상이 아니다(PRD-02 §3-b) */}
          {failure.error.retryable && (
            <Button size="sm" onClick={onRetry}>
              다시 시도
            </Button>
          )}
        </div>
      </Notice>
    </div>
  )
}
