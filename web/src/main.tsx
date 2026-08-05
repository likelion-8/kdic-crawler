/** 앱 진입점.
 * 백엔드가 아직 없어 목(MSW)이 기본 켜짐이다. 켜고 끄기는 mocks/browser.ts의 enableMocking()이
 * VITE_ENABLE_MSW로 판단한다 — 여기서 다시 분기하지 않는다.
 * 목이 뜨기 전에 렌더하면 첫 요청이 실서버로 새므로 start()를 기다린 뒤 렌더한다.
 * 워커 등록이 실패해도 화면은 띄운다(빈 화면보다 실패한 요청이 낫다). */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router'
import './styles/global.css'
import { router } from './app/router'
import { queryClient } from './app/queryClient'
import { ToastProvider } from './components/ui'

/** 목 서버는 동적 import — 꺼진 빌드에는 msw와 목 데이터가 아예 들어가지 않는다.
 * 켜고 끄는 판단 자체는 mocks/browser.ts의 enableMocking()이 하고, 여기 조건은 '내려받을지'만 정한다. */
async function startMocks(): Promise<void> {
  if (import.meta.env.VITE_ENABLE_MSW === 'false') return
  const { enableMocking } = await import('./mocks/browser')
  await enableMocking()
}

function render() {
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <RouterProvider router={router} />
        </ToastProvider>
      </QueryClientProvider>
    </StrictMode>,
  )
}

startMocks()
  .catch((e: unknown) => console.error('[msw] 목 서버를 띄우지 못했다 — 요청이 실서버로 나간다', e))
  .finally(render)
