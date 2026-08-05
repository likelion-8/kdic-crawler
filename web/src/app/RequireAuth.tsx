/** 관리자 라우트 가드 (AD-000 Description 0).
 * "인증 전에는 관리자 GNB와 운영 데이터를 노출하지 않습니다 /
 *  보호된 URL로 직접 진입했다면 원래 목적지로 복귀합니다"
 *
 * 🔴 화면 숨김은 UX 편의일 뿐 보안 경계가 아니다. 권한 판정은 언제나 서버이고
 * 403은 숨긴 버튼에서도 온다(PRD-02 §3-d). 그래서 여기서 역할까지 막지 않는다 —
 * 역할별 메뉴 숨김은 AdminLayout, 최종 판정은 서버 403이다. */
import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router'
import { loadSession, useSession } from './session'

export interface RequireAuthProps {
  children: ReactNode
}

export function RequireAuth({ children }: RequireAuthProps) {
  const { status } = useSession()
  const location = useLocation()

  useEffect(() => {
    if (status === 'loading') void loadSession()
  }, [status])

  // 로딩 문구 원문 (CM-DF-001 8.3)
  if (status === 'loading') return <p className="screen-boot">불러오는 중…</p>

  if (status === 'anonymous') {
    const returnTo = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/admin/login?returnTo=${returnTo}`} replace />
  }

  return <>{children}</>
}
