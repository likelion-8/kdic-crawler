/** AD-002 · AD-003 목 핸들러 (지식베이스 화면 전용).
 *
 * mocks/handlers/admin.ts에는 목록·미리보기의 '적재 페이지' 경로만 있어서, 기획서가 요구하는
 * 아래 3가지를 여기서 채운다. browser.ts가 extra를 먼저 등록하므로 같은 경로는 이 파일이 이긴다.
 *
 * 1. 수집 대상 탭 (AD-002 B-9) — `?tab=targets`. 적재 전 후보·협의 중 행을 포함하고
 *    `collection_status`·`owner`를 함께 준다. 탭별 건수가 달라야 해서 tab이 목록 필터다.
 * 2. `담당`(owner) · `분할 방식`(split_rule) — 코퍼스에 없는 P3 확장 필드(AD-002 B-6·B-9).
 *    data/pages.ts가 list_state·index_status를 흩뿌린 것과 같은 성격의 목 값이다.
 * 3. 페이지 ID 자동 생성 (AD-003 A-4 "업무·주제 규칙으로 생성 · 수정 가능") — 미리보기 응답에 싣는다.
 *
 * ⚠ 역할 판정은 admin.ts 안의 모듈 변수(currentRole)라 여기서 볼 수 없다 →
 *    쓰기 공통 검증(request_id·reason)과 개발용 헤더(x-mock-role)만 본다. 권한 검사는 백엔드 몫. */
import { HttpResponse, delay, http } from 'msw'
import type { Page } from '../../../lib/api/types'
import type { BusinessFunction, CollectionStatus, Role } from '../../../lib/codes'
import { hasRole } from '../../../lib/codes'
import { MOCK_CHUNKS } from '../../data/chunks'
import { MOCK_PAGES } from '../../data/pages'
import type { KbPage } from '../../data/pages'

/** 목록 행에 실리는 P3 확장 필드까지 포함한 모양 (routes/admin/knowledge/types.ts KbPage와 같다) */
type KbPageRow = KbPage & {
  owner: string
  split_rule: string
  collection_status: CollectionStatus
}

let seq = 0
const nextId = (prefix: string) => `${prefix}_${Date.now().toString(36)}_${(seq += 1)}`

function fail(status: number, message: string) {
  return HttpResponse.json(
    {
      code: 'INTERNAL',
      user_message: message,
      retryable: false,
      fallback_sources: [],
      request_id: nextId('req'),
    },
    { status },
  )
}

/** 목록 공통 처리 — admin.ts envelope와 같은 계약(`sort=필드:방향` → 페이지 자르기) */
function envelope<T>(items: T[], url: URL): Page<T> {
  const sort = url.searchParams.get('sort')
  let rows = items
  if (sort) {
    const [field, dir] = sort.split(':')
    rows = [...items].sort((a, b) => {
      const av = (a as Record<string, unknown>)[field]
      const bv = (b as Record<string, unknown>)[field]
      const cmp = String(av ?? '').localeCompare(String(bv ?? ''), 'ko')
      return dir === 'desc' ? -cmp : cmp
    })
  }
  const page = Number(url.searchParams.get('page') ?? 1)
  const size = Number(url.searchParams.get('size') ?? 20)
  return { items: rows.slice((page - 1) * size, page * size), total: rows.length, page, size }
}

/** 담당(코퍼스에 없는 값) — 목업 값이 yj·jh·dy라 팀 크롤러 담당자 핸들을 돌려 쓴다 */
const OWNERS = ['yj', 'jh', 'dy', 'hw', 'jy']

/** 분할 방식 문구는 화면마다 원문이 다르다.
 * AD-002 B-6 : `분할 방식 : FAQ 질문·답변 쌍 (규칙 기반)` / AD-003 A-6 : `… · FAQ 질문·답변 쌍으로 분할` */
const splitRuleOf = (page: KbPage) =>
  page.page_id.includes('faq') || page.page_title.includes('FAQ')
    ? 'FAQ 질문·답변 쌍 (규칙 기반)'
    : '본문 구조 기준 분할 (규칙 기반)'

const previewSplitRuleOf = (page: KbPage) =>
  page.page_id.includes('faq') || page.page_title.includes('FAQ')
    ? 'FAQ 질문·답변 쌍으로 분할'
    : '본문 구조 기준으로 분할'

/** 적재 페이지 = 코퍼스에 들어간 행이므로 전부 LOADED다 */
const INDEXED_ROWS: KbPageRow[] = MOCK_PAGES.map((p, i) => ({
  ...p,
  owner: OWNERS[i % OWNERS.length],
  split_rule: splitRuleOf(p),
  collection_status: 'LOADED',
}))

/** 수집 대상 탭에만 있는 행 — AD-002 B-9 목업 4행 중 '후보'·'협의 중' 2행(원문 값 그대로).
 * 적재 전이라 수집일·해시·청크가 없다. 목록 3상태·인덱스 상태는 적재 페이지 탭에서만 쓰인다. */
const TARGET_ONLY_ROWS: KbPageRow[] = [
  {
    page_id: 'mtrs_board_faq',
    source_url: 'https://fins.kdic.or.kr/cm/bbs/selectBoardFaqList.do',
    business_function: '착오송금 반환 신청',
    sub_category: '고객센터 > 게시판 FAQ',
    page_title: '착오송금 게시판 FAQ',
    required: true,
    note: '게시판 수집 허용 확인 필요(D5) · 후보 id는 예시',
    summary: '',
    collected_at: '',
    content_sha256: '',
    chunk_count: 0,
    list_state: '적용 대기',
    index_status: 'PENDING',
    asset_counts: { links: 0, images: 0, videos: 0 },
    form_links: [],
    owner: 'jh',
    split_rule: 'FAQ 질문·답변 쌍 (규칙 기반)',
    collection_status: 'ROBOTS_BLOCKED',
  },
  {
    page_id: 'dp_extra01',
    // AD-003 목업의 URL 입력값과 같은 주소 — Case 2 진입 예시가 이어지도록 맞췄다
    source_url: 'https://www.kdic.or.kr/protect/new_page.do',
    business_function: '예금자보호제도',
    sub_category: '보호대상 › 추가 안내',
    page_title: '보호대상 추가 안내',
    required: false,
    note: '신규 발견 URL · 포함 여부 미확정 (후보 id는 예시)',
    summary:
      '보호대상 개요만으로 답하기 어려운 개별 상품·기관 확인 질의를 보완하는 추가 안내 페이지',
    collected_at: '',
    content_sha256: '',
    chunk_count: 0,
    list_state: '적용 대기',
    index_status: 'PENDING',
    asset_counts: { links: 0, images: 0, videos: 0 },
    form_links: [],
    owner: 'dy',
    split_rule: '본문 구조 기준 분할 (규칙 기반)',
    collection_status: 'CANDIDATE',
  },
]

/** 페이지 ID 자동 생성 규칙(목) — `{업무 접두어}_{주제}` (CM-DF-002 01절).
 * 실제 주제 추출 규칙은 백엔드가 정한다. 관리자가 고칠 수 있는 초안이라 대략치면 된다. */
const BUSINESS_PREFIX: Record<BusinessFunction, string> = {
  예금자보호제도: 'dp',
  '예금보험금 안내': 'ms',
  '고객 미수령금 신청': 'uc',
  '착오송금 반환 신청': 'kmrs',
  '채무조정 안내': 'dr',
  '은닉재산 신고': 'ha',
}

function generatePageId(url: string, business: string): string {
  const slug = (url.split('?')[0].split('/').filter(Boolean).at(-1) ?? '')
    .replace(/\.[a-z]+$/i, '')
    .replace(/[^A-Za-z0-9]/g, '')
    .toLowerCase()
    .slice(0, 12)
  const prefix = BUSINESS_PREFIX[business as BusinessFunction] ?? 'kb'
  return `${prefix}_${slug || 'new'}`
}

export const adKnowledgeHandlers = [
  // ---- 목록 (AD-002) — 적재 페이지 / 수집 대상 두 탭을 tab 파라미터로 가른다 ----
  http.get('/api/admin/knowledge/pages', ({ request }) => {
    const url = new URL(request.url)
    // tab 없음 = 적재 페이지(기본 탭). admin.ts 응답과 총계가 같게 유지한다
    const tab = url.searchParams.get('tab') ?? 'indexed'
    const q = (url.searchParams.get('q') ?? '').trim()
    const business = url.searchParams.get('business')
    const state = url.searchParams.get('state')

    let rows = tab === 'targets' ? [...INDEXED_ROWS, ...TARGET_ONLY_ROWS] : INDEXED_ROWS
    if (q) rows = rows.filter((p) => p.page_title.includes(q) || p.source_url.includes(q) || p.page_id.includes(q))
    if (business && business !== '전체') rows = rows.filter((p) => p.business_function === business)
    if (state && state !== '전체') rows = rows.filter((p) => p.list_state === state || p.index_status === state)
    return HttpResponse.json(envelope(rows, url))
  }),

  // ---- 신규 URL 사전 검증 · 미리보기 (AD-003) ----
  // admin.ts 버전과 같은 계약이되 extracted.page_id(자동 생성)와 split_rule을 더 준다.
  http.post('/api/admin/previews', async ({ request }) => {
    const role = request.headers.get('x-mock-role') as Role | null
    if (role && !hasRole(role, 'EDITOR')) {
      return fail(403, `이 작업에는 EDITOR 권한이 필요합니다. 현재 권한은 ${role}입니다.`)
    }
    const body = (await request.json()) as { request_id?: string; url?: string; business_function?: string }
    if (!body.request_id) return fail(400, 'request_id가 필요합니다.')
    if (!body.url) return fail(400, 'URL을 입력해 주세요.')
    // crawl_targets 밖의 URL은 수집 금지(PRD-01 B-1-c 삭제·수집 정책)
    if (!/^https:\/\/(www|fins)\.kdic\.or\.kr\//.test(body.url)) {
      return fail(400, '수집 허용 목록(kdic.or.kr)에 없는 주소입니다. 등록할 수 없습니다.')
    }
    await delay(700) // 1~4단계(수집·변환·청킹·검증)를 실제로 도는 시간
    const sample = MOCK_PAGES[0]
    return HttpResponse.json({
      preview_id: nextId('pv'),
      url: body.url,
      split_rule: previewSplitRuleOf(sample),
      // 자동 추출값 — 관리자가 검토 후 고칠 수 있는 초안이다
      extracted: {
        page_id: generatePageId(body.url, body.business_function ?? sample.business_function),
        page_title: sample.page_title,
        business_function: body.business_function ?? sample.business_function,
        sub_category: sample.sub_category,
        summary: sample.summary,
        content_sha256: sample.content_sha256,
      },
      chunks: MOCK_CHUNKS.filter((c) => c.page_id === sample.page_id),
      warnings: ['본문에서 표를 2개 발견했습니다. 청킹 결과를 확인해 주세요.'],
      sub_category_extraction_failed: false,
    })
  }),

  // ---- 미리보기 버리기 (AD-003 Description ❷ "사유 필수 · 임시 자료는 하루 뒤 삭제").
  //      승인자가 따로 없어 화면 라벨은 [버리기]다 — 엔드포인트·상태값은 계약이라 그대로 둔다 ----
  http.post('/api/admin/previews/:previewId/reject', async ({ params, request }) => {
    const body = (await request.json()) as { request_id?: string; reason?: string }
    if (!body?.request_id) return fail(400, 'request_id가 필요합니다.')
    if (!body?.reason?.trim()) return fail(400, '사유를 입력해 주세요.')
    return HttpResponse.json({
      preview_id: String(params.previewId),
      status: 'REJECTED',
      // 임시 자료는 하루 뒤 삭제 (AD-003 Description ❷)
      purge_at: new Date(Date.now() + 24 * 3600_000).toISOString(),
    })
  }),
]
