/** AD-002 상세 패널 자체 점검 — 권한별 위험 버튼 노출과 기획서 표기 규칙이 그대로인지 본다.
 *
 * 프레임워크를 새로 깔지 않으려고 assert + react-dom/server만 쓴다. components/chat/selfcheck.tsx와 같은 방식:
 *
 *   cd web && node -e "import('vite').then(async v=>{const s=await v.createServer({server:{middlewareMode:true},appType:'custom'});await s.ssrLoadModule('/src/routes/admin/knowledge/selfcheck.tsx');await s.close()})"
 *
 * 통과하면 "ad-knowledge selfcheck: 통과"가 찍힌다. 여기가 깨지면 권한 없는 계정에 위험 버튼이 보이거나,
 * 대상 표기('이름 (ID)')·상태 병기가 깨진 것이다.
 *
 * ⚠ 화면 컴포넌트(KnowledgePages·NewPageForm) 자체는 여기서 렌더하지 못한다 —
 *   app/session.ts의 useSyncExternalStore에 getServerSnapshot이 없어 SSR이 막힌다(report shared_needed). */
/// <reference types="node" />
// ↑ tsconfig.app.json의 types는 vite/client뿐이다. 이 파일만 node에서 도는 스크립트라 여기서만 끌어온다.
import assert from 'node:assert/strict'
import type { ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  PageDetailActions,
  PageDetailPanel,
  pageDetailMeta,
  pageDetailTitle,
} from './PageDetailPanel'
import type { KbPage } from './types'

const PAGE: KbPage = {
  page_id: 'dp_extra01',
  source_url: 'https://www.kdic.or.kr/sp/dpstrprot/ProtSystProtLmts/selectScrn.do',
  business_function: '예금자보호제도',
  sub_category: '예금자보호제도 > 보호대상 > 추가 안내',
  page_title: '보호대상 추가 안내',
  required: false,
  note: '신규 발견 URL · 포함 여부 미확정',
  summary: '보호대상 개요만으로 답하기 어려운 개별 상품·기관 확인 질의를 보완하는 추가 안내 페이지',
  collected_at: '2026-07-13',
  content_sha256: '80ae7ac40cf6',
  chunk_count: 11,
  list_state: '변경 감지',
  index_status: 'PENDING',
  asset_counts: { links: 4, images: 2, videos: 0 },
  form_links: [{ label: '반환지원 신청서', url: 'https://fins.kdic.or.kr/form' }],
  owner: 'dy',
  split_rule: 'FAQ 질문·답변 쌍 (규칙 기반)',
  collection_status: 'LOADED',
}

/** 패널이 기대하는 셸(라우터·쿼리)만 씌운다. 서버가 없으니 청크 목록은 로딩 상태로 렌더된다 */
function render(node: ReactNode): string {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return renderToStaticMarkup(
    <MemoryRouter>
      <QueryClientProvider client={client}>{node}</QueryClientProvider>
    </MemoryRouter>,
  )
}

// 1. 상세 모달 헤더 — 제목은 '제목 + (페이지 ID)', 부제는 상태를 글자로 알린다 (B-6 Description 1)
//    상세는 모달이라 '선택 없음' 상태에서는 아예 렌더되지 않는다 — 빈 상태 패널이 없어졌다
{
  assert.equal(pageDetailTitle(PAGE), '보호대상 추가 안내 (dp_extra01)', '제목 = 제목 + (페이지 ID)')
  const meta = pageDetailMeta(PAGE)
  assert.ok(meta.includes('상태 변경 감지'), '상태는 색이 아니라 글자로도 알린다')
  assert.ok(meta.includes('적용 대기'), 'index_status 배지 문구는 CM-DF-002 05절 정본')
}

// 2. 상세 본문 — 구분·추출 자산은 응답 값으로 렌더
{
  const html = render(<PageDetailPanel page={PAGE} />)
  assert.ok(html.includes('분석필요'), 'required=false → 구분 분석필요')
  assert.ok(html.includes('이동 링크 4 · 이미지 2 · 영상 0'))
  assert.ok(html.includes('<dt>담당</dt><dd>dy</dd>'), '기본 카드 8행에 담당이 있다(B-6)')
  assert.ok(html.includes('청크 목록 (11)'), '청크 수는 제목에 그대로 보인다')
  // '검색에 쓰이는 단위'라는 설명은 제목 옆 ⓘ로 접었다. 접혀 있어도 DOM에는 남아야 한다
  // (InfoHint가 sr-only 사본을 두므로 aria-describedby로 가리킬 수 있다)
  assert.ok(html.includes('검색에 쓰이는 단위'), '설명은 접혀도 DOM에 남는다')
  assert.ok(html.includes('분할 방식 : FAQ 질문·답변 쌍 (규칙 기반)'), '분할 방식은 목록 위 1회 표기')
  assert.ok(html.includes('… 외 8개 · 스크롤로 전체 확인'), '3장 넘으면 잔여 개수를 알린다')
  assert.ok(html.includes('페이지 이력 보기 (AD-011) →'))
  assert.ok(html.includes('/admin/settings/activity?q=dp_extra01'), '이력은 이 페이지 대상 필터로 연다')
}

// 3. 모달 푸터 행 동작 — 권한이 있으면 둘 다, 없으면 숨긴다 (403은 목록 화면이 따로 처리)
{
  const on = render(
    <PageDetailActions page={PAGE} canRecrawl canDelete onRecrawl={() => {}} onDelete={() => {}} onCancelDelete={() => {}} />,
  )
  assert.ok(on.includes('재수집') && on.includes('삭제'))

  const off = render(
    <PageDetailActions
      page={PAGE}
      canRecrawl={false}
      canDelete={false}
      onRecrawl={() => {}}
      onDelete={() => {}}
      onCancelDelete={() => {}}
    />,
  )
  assert.ok(!off.includes('>재수집<'))
  assert.ok(!off.includes('>삭제<'))
}

// 4. 상세 본문 — 서식 링크·출처는 항상 새 탭으로 열고, 그 사실을 글로도 알린다(09절)
{
  const html = render(<PageDetailPanel page={PAGE} />)
  assert.equal((html.match(/target="_blank"/g) ?? []).length, 2, '출처 1 + 서식 링크 1')
  assert.ok(html.includes('새 창에서 열림'))
  assert.ok(html.includes('rel="noreferrer"'))
}

console.log('ad-knowledge selfcheck: 통과')
