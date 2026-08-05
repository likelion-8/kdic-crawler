/** 라우트 정의.
 *
 * 챗봇(공개): 대화는 화면 전환 없이 갱신되므로 페이지는 하나뿐이다(CM-DF-003 01절).
 *   `/chat/:sessionId`는 24시간 이내 대화를 복원하는 진입점이다(GET /api/sessions/{session_id}).
 * 관리자: 인증 필요 + PC WEB 전용(≥1024px). AD-000 로그인만 셸 밖에 둔다
 *   — "인증 전에는 관리자 GNB와 운영 데이터를 노출하지 않습니다"(AD-000 Description 0).
 *
 * 화면 모듈은 lazy로 나눈다. 관리자 12화면을 챗봇 사용자에게 내려보낼 이유가 없다. */
import { Navigate, createBrowserRouter } from 'react-router'
import { AdminLayout } from './AdminLayout'
import { RequireAuth } from './RequireAuth'

export const router = createBrowserRouter([
  {
    path: '/',
    lazy: async () => ({ Component: (await import('../routes/chat/ChatPage')).ChatPage }),
  },
  {
    path: '/chat/:sessionId',
    lazy: async () => ({ Component: (await import('../routes/chat/ChatPage')).ChatPage }),
  },
  {
    path: '/admin/login',
    lazy: async () => ({ Component: (await import('../routes/admin/LoginPage')).LoginPage }),
  },
  {
    path: '/admin',
    element: (
      <RequireAuth>
        <AdminLayout />
      </RequireAuth>
    ),
    children: [
      {
        index: true,
        lazy: async () => ({ Component: (await import('../routes/admin/Dashboard')).Dashboard }),
      },
      {
        path: 'knowledge/pages',
        lazy: async () => ({
          Component: (await import('../routes/admin/KnowledgePages')).KnowledgePages,
        }),
      },
      {
        // AD-003은 별도 화면이 아니라 AD-002 안의 인라인 블록이 됐다(P-12).
        // 옛 경로로 들어온 북마크·활동 로그 링크는 목록으로 보내며 그 블록을 연다
        path: 'knowledge/new',
        element: <Navigate replace to="/admin/knowledge/pages?new=1" />,
      },
      {
        path: 'pipeline',
        lazy: async () => ({ Component: (await import('../routes/admin/Pipeline')).Pipeline }),
      },
      {
        path: 'logs',
        lazy: async () => ({
          Component: (await import('../routes/admin/ConversationLogs')).ConversationLogs,
        }),
      },
      {
        path: 'evaluation',
        lazy: async () => ({ Component: (await import('../routes/admin/Evaluation')).Evaluation }),
      },
      // 설정 진입 기본값은 RAG (CM-DF-004 · AD-010 공통 주석 "기본은 RAG, 권한별 노출")
      { path: 'settings', element: <Navigate to="/admin/settings/rag" replace /> },
      {
        path: 'settings/rag',
        lazy: async () => ({
          Component: (await import('../routes/admin/settings/RagParams')).RagParams,
        }),
      },
      {
        path: 'settings/prompt',
        lazy: async () => ({
          Component: (await import('../routes/admin/settings/PromptGuardrail')).PromptGuardrail,
        }),
      },
      {
        path: 'settings/ops',
        lazy: async () => ({
          Component: (await import('../routes/admin/settings/OpsPolicy')).OpsPolicy,
        }),
      },
      {
        path: 'settings/access',
        lazy: async () => ({
          Component: (await import('../routes/admin/settings/AccessControl')).AccessControl,
        }),
      },
      {
        path: 'settings/activity',
        lazy: async () => ({
          Component: (await import('../routes/admin/settings/ActivityLog')).ActivityLog,
        }),
      },
    ],
  },
  {
    path: '*',
    lazy: async () => ({ Component: (await import('../routes/NotFound')).NotFound }),
  },
])
