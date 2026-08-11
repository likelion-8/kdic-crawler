/** AD-002·AD-003이 주고받는 응답 스키마.
 *
 * lib/api/types.ts에는 챗봇 계약만 있고 관리자 지식베이스 스키마가 없다(기획서 역기재 대상).
 * 그래서 목(mocks/data/pages.ts · chunks.ts · handlers/admin.ts)이 실제로 돌려주는 모양을
 * 그대로 옮겨 둔다 — ChatPage가 RestoredSession을 다루는 방식과 같다.
 * 백엔드가 붙으면 이 파일을 lib/api/types.ts로 올린다(report shared_needed). */
import type {
  BusinessFunction,
  CollectionStatus,
  IndexStatus,
  JobStatus,
  KbListState,
} from '../../../lib/codes'

/** 서식 직링크가 아니라 '다운로드 버튼이 있는 페이지' URL */
export interface KbFormLink {
  label: string
  url: string
}

/** GET /api/admin/knowledge/pages 의 items 원소.
 * 사람 입력 8키(page_id·source_url·business_function·sub_category·page_title·required·note·summary) +
 * 크롤링이 만드는 값(collected_at·content_sha256·chunk_count·asset_counts·form_links) +
 * P3 확장 필드(list_state·index_status) 구성이다. */
export interface KbPage {
  page_id: string
  source_url: string
  business_function: BusinessFunction
  /** "업무 > 대분류 > ..." 브레드크럼 */
  sub_category: string
  page_title: string
  /** true=필수 / false=분석필요 (AD-002 B-9 '구분' 값 2종) */
  required: boolean
  /** 수집 근거 */
  note: string
  summary: string
  /** YYYY-MM-DD */
  collected_at: string
  content_sha256: string
  chunk_count: number
  /** 목록 3상태 파생값 (CM-DF-002 05절: 적용 대기 > 변경 감지 > 최신) */
  list_state: KbListState
  index_status: IndexStatus
  asset_counts: { links: number; images: number; videos: number }
  form_links: KbFormLink[]
  /** 담당 — 코퍼스에 없는 P3 확장 필드. 상세 '기본' 8행과 수집 대상 표 7열에 필요하다(B-6·B-9) */
  owner: string
  /** 청크 분할 방식 1줄. 상세 패널 청크 목록 위에 1회 표기한다 (B-6 (5)) */
  split_rule: string
  /** 적재·협의 상태 3종의 원천 (B-9). 적재 페이지 탭 행은 항상 LOADED */
  collection_status: CollectionStatus
  /** 적용 대기 변경을 취소할 때 호출할 change_requests 행 */
  pending_change_request_id?: string | null
  pending_change_action?: 'ADD' | 'UPDATE' | 'DELETE' | 'EXCLUDE' | null
}

/** POST /api/admin/change-requests (action='ADD') 본문 중 새 페이지 레코드 부분.
 * "[적재 승인] 시 이 값 그대로 수집 대상 목록(AD-002)에 등록된다. 두 화면의 필드는 같은 레코드"(A-4)
 * → 폼의 사람 입력 8키 + 담당을 전부 실어 보낸다. 백엔드 계약에 이 필드들을 받는 자리가 필요하다. */
export interface NewPageRecord {
  page_id: string
  source_url: string
  business_function: BusinessFunction
  sub_category: string
  page_title: string
  required: boolean
  note: string
  summary: string
  owner: string
}

/** GET /api/admin/knowledge/chunks 의 items 원소 */
export interface KbChunk {
  chunk_id: string
  page_id: string
  /** 페이지 안 순번. 단일 청크는 0 */
  seq: number
  title: string
  /** 본문 글자 수 — "#0 · 신청 대상 (412자)" 표기용 */
  chars: number
  preview: string
}

/** POST /api/admin/previews 응답 — 앞 4단계(수집·변환·청킹·검증)를 1건 실행한 결과 (AD-003 A-5) */
export interface PreviewResponse {
  preview_id: string
  url: string
  /** 자동 추출값. 관리자가 승인 전에 고칠 수 있는 초안이다 */
  extracted: {
    /** 업무·주제 규칙으로 만든 페이지 ID 초안 — 관리자가 수정할 수 있다 (A-4 '자동 생성') */
    page_id: string
    page_title: string
    business_function: BusinessFunction
    sub_category: string
    summary: string
    content_sha256: string
  }
  /** 청크 메타 줄 끝에 붙는 분할 규칙 설명 (A-6 `chunk #{index} · {글자수}자 · {분할 규칙 설명}`) */
  split_rule: string
  chunks: KbChunk[]
  warnings: string[]
  /** true면 원문에서 하위분류를 찾지 못했으므로 적재 전에 사람이 입력해야 한다 */
  sub_category_extraction_failed: boolean
}

export interface JobStep {
  /** PIPELINE_STEPS(수집·변환·청킹·검증·색인·반영) 중 하나 */
  name: string
  status: 'QUEUED' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'SKIPPED'
}

/** POST /api/admin/jobs · GET /api/admin/jobs/{id} 중 이 두 화면이 쓰는 부분만 */
export interface PipelineJobView {
  id: string
  status: JobStatus
  steps: JobStep[]
}

/** POST /api/admin/change-requests 응답 중 쓰는 부분만 */
export interface ChangeRequestView {
  id: string
  status: string
}
