/** MSW 워커 — 백엔드(FastAPI)가 생기기 전까지 프론트 혼자 돌게 하는 목 서버.
 *
 * 켜고 끄기는 `VITE_ENABLE_MSW`(기본 켜짐). 끄는 법·진짜 API로 갈아타는 법은 mocks/README.md.
 * main.tsx에서 아래처럼 부트 전에 한 번 await 한다:
 *
 *   await enableMocking()
 *   createRoot(...).render(...)
 */
import { setupWorker } from 'msw/browser'
import { adminHandlers } from './handlers/admin'
import { chatHandlers } from './handlers/chat'
// 화면별 추가 핸들러 — CM-DF-003 04절 표에 없어 화면 담당자가 정의한 엔드포인트다.
// (대시보드 집계·활동 로그·지식베이스 상세·파이프라인 이력·평가·프롬프트/운영 정책)
// 백엔드가 실제 경로를 확정하면 여기 목록과 mocks/README.md §6을 함께 고친다.
import { adAuthHandlers } from './handlers/extra/ad-auth'
import { adDashActivityHandlers } from './handlers/extra/ad-dash-activity'
import { adEvalRagHandlers } from './handlers/extra/ad-eval-rag'
import { adKnowledgeHandlers } from './handlers/extra/ad-knowledge'
import { adPipelineLogsHandlers } from './handlers/extra/ad-pipeline-logs'
import { adPromptOpsHandlers } from './handlers/extra/ad-prompt-ops'

// 화면별 핸들러를 앞에 둔다 — 같은 경로를 잡으면 더 구체적인 쪽이 이겨야 한다(msw는 선착순).
export const handlers = [
  ...adAuthHandlers,
  ...adDashActivityHandlers,
  ...adKnowledgeHandlers,
  ...adPipelineLogsHandlers,
  ...adEvalRagHandlers,
  ...adPromptOpsHandlers,
  ...chatHandlers,
  ...adminHandlers,
]

export const worker = setupWorker(...handlers)

/** 목이 켜져 있으면 워커를 등록한다. 꺼져 있으면 아무것도 하지 않는다.
 * 목이 붙지 않은 요청은 그대로 네트워크로 나간다(onUnhandledRequest: 'bypass') —
 * 정적 파일·소스맵까지 경고가 뜨면 콘솔이 못 쓰게 된다. */
export async function enableMocking(): Promise<void> {
  if (import.meta.env.VITE_ENABLE_MSW === 'false') return
  await worker.start({
    onUnhandledRequest: 'bypass',
    serviceWorker: { url: `${import.meta.env.BASE_URL}mockServiceWorker.js` },
  })
}
