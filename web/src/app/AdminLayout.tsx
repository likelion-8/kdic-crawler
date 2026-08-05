/** 관리자 셸 — 전 관리자 화면 공통 (AD-010 2-1 · AD-001/002 0.1 목업 실측).
 * "좌측 GNB(대시보드/지식베이스/파이프라인/대화 로그/평가/설정) +
 *  상단 헤더(관리자 계정 · 세션 만료까지 남은 시간 · [연장]) 구성은 전 화면 동일"
 *
 * 설정 하위 5종은 목업에선 본문 상단 가로 서브탭이지만, 여기서는 좌측 GNB의 2뎁스로 둔다
 * (라우트가 5개로 나뉘어 있어 키보드만으로 직접 이동할 수 있는 편이 낫다 — decisions 참조).
 * 화면 쪽에서 같은 서브탭을 또 그리지 말 것.
 *
 * 관리자 화면은 라이트 고정이다(tokens.css 다크 팔레트 주석) → 마운트 동안 data-theme을 고정한다. */
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import {
  ClipboardCheck,
  Database,
  History,
  KeyRound,
  LayoutDashboard,
  MessagesSquare,
  ScrollText,
  Settings2,
  Shield,
  SlidersHorizontal,
  TriangleAlert,
  Workflow,
  type LucideIcon,
} from 'lucide-react'
import type { Role } from '../lib/codes'
import { hasRole } from '../lib/codes'
import { formatRemaining } from '../lib/format'
import { isApiRequestError } from '../lib/api/client'
import { cn } from '../lib/utils'
import { Badge } from '../components/shadcn/badge'
import { Button } from '../components/shadcn/button'
import { extendSession, logout, useSession, useSessionCountdown } from './session'
import { InfoHint, useToast } from '../components/ui'
import { PasswordChangeModal } from '../routes/admin/login/PasswordChangeModal'
import './AdminLayout.css'

export interface AdminNavItem {
  /** 그룹 헤더(설정·보안·감사)는 자기 경로가 없다 */
  path?: string
  /** GNB 라벨 */
  label: string
  /** 상단 헤더 제목 — 목업 실측 원문 */
  title: string
  /** 기획서 화면 ID */
  screenId: string
  /** 이 역할 미만이면 메뉴를 숨긴다. 서버가 최종 판정이므로 숨김은 UX 편의일 뿐이다 */
  minRole?: Role
  /** 메뉴에 노출하지 않는 화면(다른 화면에서 진입). 제목만 필요하다 */
  hidden?: boolean
  children?: AdminNavItem[]
}

/** GNB 6메뉴 — 순서 고정 (AD-DF-002 IA 01절) */
export const ADMIN_NAV: AdminNavItem[] = [
  { path: '/admin', label: '대시보드', title: '대시보드', screenId: 'AD-001' },
  {
    path: '/admin/knowledge/pages',
    label: '지식베이스',
    title: '지식베이스 관리 : 페이지·청크 목록',
    screenId: 'AD-002',
  },
  {
    path: '/admin/pipeline',
    label: '파이프라인',
    title: '데이터 파이프라인 : 트리거 · 상태',
    screenId: 'AD-004',
  },
  { path: '/admin/logs', label: '대화 로그', title: '대화 로그 · 모니터링', screenId: 'AD-005' },
  { path: '/admin/evaluation', label: '평가', title: '평가셋 · 평가 결과', screenId: 'AD-006' },
  {
    label: '설정·보안·감사',
    title: '설정·보안·감사',
    screenId: 'AD-007~011',
    children: [
      { path: '/admin/settings/rag', label: 'RAG 파라미터', title: 'RAG 파라미터', screenId: 'AD-007' },
      {
        path: '/admin/settings/prompt',
        label: '프롬프트·가드레일',
        title: '프롬프트 · 가드레일',
        screenId: 'AD-008',
      },
      { path: '/admin/settings/ops', label: '운영 정책', title: '운영 정책', screenId: 'AD-009' },
      // AD-010·AD-011은 ADMIN 조회 (CM-DF-004 10절 "조회 권한은 ADMIN")
      { path: '/admin/settings/access', label: '보안·권한', title: '보안 · 권한', screenId: 'AD-010', minRole: 'ADMIN' },
      { path: '/admin/settings/activity', label: '활동 로그', title: '활동 로그', screenId: 'AD-011', minRole: 'ADMIN' },
    ],
  },
]

/** '연장 불가' 사유 ⓘ의 id — 잠긴 [연장] 버튼이 aria-describedby로 가리킨다 */
const EXTEND_HINT_ID = 'admin-extend-hint'

/** 메뉴 아이콘 — 데이터(ADMIN_NAV)는 화면 정의라 시각 속성을 섞지 않고 여기서만 맵핑한다 */
const NAV_ICONS: Record<string, LucideIcon> = {
  'AD-001': LayoutDashboard,
  'AD-002': Database,
  'AD-004': Workflow,
  'AD-005': MessagesSquare,
  'AD-006': ClipboardCheck,
  'AD-007~011': Shield,
  'AD-007': SlidersHorizontal,
  'AD-008': ScrollText,
  'AD-009': Settings2,
  'AD-010': KeyRound,
  'AD-011': History,
}

function findScreen(pathname: string): AdminNavItem | undefined {
  for (const item of ADMIN_NAV) {
    if (item.path === pathname) return item
    const child = item.children?.find((c) => c.path === pathname)
    if (child) return child
  }
  return undefined
}

/** GNB 항목 공통 룩 — 활성이면 옅은 면 + 잉크 글자·굵기. 좌측 액센트 바는 쓰지 않는다.
 * NavLink가 aria-current="page"를 붙여 주므로 색만이 아니라 스크린리더에도 현재 위치가 전달된다 (CM-DF-004 09절) */
function navLinkClass(isActive: boolean, sub = false) {
  return cn(
    'flex min-h-10 items-center gap-2.5 rounded-md px-3 text-muted-foreground transition-colors duration-200 hover:bg-muted hover:text-foreground',
    sub ? 'text-[13px]' : 'text-sm',
    isActive && 'bg-muted font-medium text-foreground',
  )
}

export function AdminLayout() {
  const { session } = useSession()
  const countdown = useSessionCountdown()
  const { pathname } = useLocation()
  const showToast = useToast()
  const [passwordOpen, setPasswordOpen] = useState(false)

  useEffect(() => {
    const root = document.documentElement
    const previous = root.dataset.theme
    root.dataset.theme = 'light'
    return () => {
      if (previous === undefined) delete root.dataset.theme
      else root.dataset.theme = previous
    }
  }, [])

  if (!session) return null // RequireAuth가 이미 걸러 준다

  const screen = findScreen(pathname)
  const role = session.role

  async function onExtend() {
    try {
      await extendSession()
      showToast('세션을 연장했습니다')
    } catch (e) {
      // 401이면 세션이 이미 끊겨 로그인으로 넘어간다. 그 밖의 실패만 알린다
      if (isApiRequestError(e) && e.status !== 401) showToast(e.error.user_message)
    }
  }

  return (
    <div className="grid min-h-full min-w-[1024px] grid-cols-[240px_1fr] bg-background">
      {/* 키보드 사용자가 GNB 11개를 건너뛰고 본문으로 갈 수 있어야 한다 (CM-DF-004 09절) */}
      <a
        className="absolute top-2 -left-[9999px] z-50 rounded-md border bg-background px-3 py-2 text-sm font-medium focus:left-2"
        href="#admin-main"
      >
        본문 바로가기
      </a>

      <nav className="border-r border-border/60 bg-sidebar px-3 py-4" aria-label="관리자 주 메뉴">
        {/* 워드마크 락업 — 브랜드(700)와 콘솔(300)의 굵기 대비 */}
        <p className="mb-4 px-3 text-lg tracking-tight">
          <span className="font-bold text-primary">예솜24</span>{' '}
          <span className="font-light text-muted-foreground">Admin</span>
        </p>
        <ul className="space-y-0.5">
          {ADMIN_NAV.filter((item) => !item.hidden && hasRole(role, item.minRole ?? 'VIEWER')).map(
            (item) => {
              const Icon = NAV_ICONS[item.screenId]
              return (
                <li key={item.path ?? item.label}>
                  {item.path === undefined ? (
                    <p
                      className="mt-4 mb-1 flex items-center gap-2.5 px-3 text-xs font-semibold text-muted-foreground"
                      id={`gnb-${item.screenId}`}
                    >
                      {Icon && <Icon className="size-4 shrink-0" aria-hidden="true" />}
                      {item.label}
                    </p>
                  ) : (
                    <NavLink
                      className={({ isActive }) => navLinkClass(isActive)}
                      to={item.path}
                      end={item.path === '/admin'}
                    >
                      {Icon && <Icon className="size-4 shrink-0" aria-hidden="true" />}
                      {item.label}
                    </NavLink>
                  )}
                  {/* 2뎁스는 세로 레일 없이 들여쓰기로만 구분한다 — 좌측 라인은 쓰지 않는다 */}
                  {item.children && (
                    <ul className="mt-1 space-y-0.5 pl-4" aria-labelledby={`gnb-${item.screenId}`}>
                      {item.children
                        .filter((child) => hasRole(role, child.minRole ?? 'VIEWER'))
                        .map((child) => {
                          const ChildIcon = NAV_ICONS[child.screenId]
                          return (
                            <li key={child.path}>
                              <NavLink
                                className={({ isActive }) => navLinkClass(isActive, true)}
                                to={child.path ?? ''}
                              >
                                {ChildIcon && (
                                  <ChildIcon className="size-4 shrink-0" aria-hidden="true" />
                                )}
                                {child.label}
                              </NavLink>
                            </li>
                          )
                        })}
                    </ul>
                  )}
                </li>
              )
            },
          )}
        </ul>
      </nav>

      <div className="flex min-w-0 flex-col">
        <header className="flex h-14 items-center justify-between gap-4 border-b border-border/60 bg-background px-6">
          <div className="flex min-w-0 items-center gap-2.5">
            <h1 className="truncate text-lg font-semibold">{screen?.title ?? ''}</h1>
            {/* 기획서 화면 ID 태그 — 화면↔문서를 즉시 대조하는 기능적 디테일 */}
            {screen && (
              <span className="nums shrink-0 rounded border border-border/60 px-1.5 py-0.5 text-[11px] tracking-wide text-muted-foreground">
                {screen.screenId}
              </span>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-3">
            {countdown && (
              <>
                {/* 알약 배지 대신 선행 점 + 평문 — 색만이 아니라 문구로도 남은 시간을 알린다 */}
                <p
                  className={cn(
                    'nums flex items-center gap-2 text-xs',
                    countdown.warning ? 'font-medium text-warning' : 'text-muted-foreground',
                  )}
                >
                  <span
                    className={cn(
                      'size-1.5 shrink-0 rounded-full',
                      countdown.warning ? 'bg-warning' : 'bg-muted-foreground/60',
                    )}
                    aria-hidden="true"
                  />
                  세션 만료까지 {formatRemaining(countdown.remainingMs)}
                </p>
                {/* 29자 문장(≈290px)을 그대로 두면 1024에서 헤더가 가용 폭을 넘긴다.
                    `hidden xl:inline`으로 감췄더니 이번엔 1024~1279에서 [연장]이 왜 잠겼는지
                    설명이 아예 사라졌다 — 폭을 먹지 않으면서 모든 화면에서 읽히도록 ⓘ로 접는다 */}
                {!countdown.extendable && (
                  <InfoHint id={EXTEND_HINT_ID} label="연장 불가 사유" size="sm">
                    이용 가능 시간이 끝나 갑니다. 계속 사용하려면 다시 로그인해 주세요.
                  </InfoHint>
                )}
              </>
            )}
            <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
              {session.email}
              {/* 역할은 색이 아니라 글자로 알린다 (CM-DF-004 09절) — 알약이 아니라 사각 태그 */}
              <Badge variant="outline" className="rounded-[3px]">
                {role}
              </Badge>
            </p>
            {countdown && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void onExtend()}
                disabled={!countdown.extendable}
                // 잠긴 이유는 옆 ⓘ에 접혀 있다 — 접혀 있어도 읽히도록 가리킨다
                aria-describedby={countdown.extendable ? undefined : EXTEND_HINT_ID}
              >
                연장
              </Button>
            )}
            {/* AD-000 1-5의 진입점. 컴포넌트는 있었는데 어느 화면도 열지 않아 도달 불가였다 */}
            <Button type="button" variant="ghost" size="sm" onClick={() => setPasswordOpen(true)}>
              비밀번호 변경
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={() => void logout()}>
              로그아웃
            </Button>
          </div>
        </header>

        {/* 종료 2분 전 경고. 문구는 기획서에 없어 프론트가 정했다(08 issues 4) */}
        {countdown?.warning && (
          <p
            className="flex items-center gap-3 border-b border-warning/40 bg-warning-bg px-6 py-2.5 text-[13px] text-warning"
            role="alert"
          >
            <TriangleAlert className="size-4 shrink-0" aria-hidden="true" />
            잠시 후 자동으로 로그아웃됩니다. 계속 사용하려면 연장을 눌러 주세요.
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-7"
              onClick={() => void onExtend()}
              disabled={!countdown.extendable}
            >
              연장
            </Button>
          </p>
        )}

        <main className="flex-1 bg-background p-6" id="admin-main">
          {/* 본문 최대폭은 셸이 한 번만 정한다. 화면마다 따로 두었더니 1076·1080·1100·무제한이
              섞여, 메뉴를 옮길 때마다 카드 오른쪽 끝이 들쭉날쭉했다 */}
          <div className="mx-auto w-full max-w-[1400px]">
            <Outlet />
          </div>
        </main>
      </div>

      <PasswordChangeModal open={passwordOpen} onClose={() => setPasswordOpen(false)} />
    </div>
  )
}
