/** 코드값·식별자 — CM-DF-002(Figma 397:2)가 정본. 값을 바꾸려면 기획서를 먼저 고친다.
 *
 * ⚠ `FAILED`는 collection_status·index_status·job status 세 enum에,
 * `INTERNAL`은 error.code·job_error 두 enum에 중복 존재한다.
 * 라벨 매핑을 하나로 합치면 깨지므로 enum별 Record를 따로 둔다. */

// --- 01. 식별자 ---
/** `{업무 접두어}_{주제}` */
export type PageId = string
/** `PageId` 또는 `${PageId}#${number}` — 단일 청크는 `#0`을 붙이지 않는다 */
export type ChunkId = string

// --- 02. 업무 (한글 문자열 자체가 코드값) ---
export const BUSINESS_FUNCTIONS = [
  '예금자보호제도',
  '예금보험금 안내',
  '고객 미수령금 신청',
  '착오송금 반환 신청',
  '채무조정 안내',
  '은닉재산 신고',
] as const
export type BusinessFunction = (typeof BUSINESS_FUNCTIONS)[number]

// --- 03. 질문 분류 ---
export type Intent = 'informational' | 'civil_petition'
export const INTENT_LABEL: Record<Intent, string> = {
  informational: '정보성',
  civil_petition: '민원성',
}

export type QuestionType = 'fact' | 'faq' | 'table_lookup' | 'link_guide' | 'file_download' | 'out_of_scope'
export const QUESTION_TYPE_LABEL: Record<QuestionType, string> = {
  fact: '사실 확인',
  faq: 'FAQ',
  table_lookup: '표 조회',
  link_guide: '링크 안내',
  file_download: '서식 받기',
  out_of_scope: '범위 외',
}

// --- 04. 응답 · 오류 · 피드백 ---
export type ResponseType = 'ANSWER' | 'CLARIFICATION' | 'FALLBACK' | 'ERROR'
export type ErrorCode = 'LLM_TIMEOUT' | 'LLM_RATE_LIMIT' | 'LLM_ERROR' | 'RETRIEVAL_ERROR' | 'INTERNAL'
/** true면 오류 응답에 fallback_sources가 함께 온다 */
export const ERROR_HAS_FALLBACK: Record<ErrorCode, boolean> = {
  LLM_TIMEOUT: true,
  LLM_RATE_LIMIT: true,
  LLM_ERROR: true,
  RETRIEVAL_ERROR: false,
  INTERNAL: false,
}

export type ReasonCode = 'INACCURATE' | 'IRRELEVANT' | 'SOURCE_UNCLEAR' | 'HARD_TO_UNDERSTAND' | 'OTHER'
export const REASON_CODE_LABEL: Record<ReasonCode, string> = {
  INACCURATE: '내용이 부정확해요',
  IRRELEVANT: '질문과 관계없어요',
  SOURCE_UNCLEAR: '출처를 찾기 어려워요',
  HARD_TO_UNDERSTAND: '설명이 어려워요',
  OTHER: '기타',
}
export const REASON_CODES = Object.keys(REASON_CODE_LABEL) as ReasonCode[]

// --- 05. 지식베이스 상태 ---
export type CollectionStatus = 'CANDIDATE' | 'LOADED' | 'ROBOTS_BLOCKED' | 'SKIPPED' | 'FAILED'
export type IndexStatus = 'INDEXED' | 'PENDING' | 'REINDEXING' | 'FAILED' | 'EXCLUDED'
export const INDEX_STATUS_BADGE: Record<IndexStatus, string> = {
  INDEXED: '반영 완료',
  PENDING: '적용 대기',
  REINDEXING: '재적재 중',
  FAILED: '재적재 실패',
  EXCLUDED: '검색 제외',
}
export type PendingAction = 'NONE' | 'ADD' | 'UPDATE' | 'DELETE' | 'EXCLUDE'
/** 목록 행에서 파생 계산되는 3상태 */
export type KbListState = '적용 대기' | '변경 감지' | '최신'

// --- 06. 작업 · 권한 ---
export type JobType = 'FULL_RECRAWL' | 'SELECTED_RECRAWL' | 'REINDEX' | 'RECHUNK' | 'REEMBED' | 'SMOKE_EVAL' | 'CHANGE_DETECT'
export type JobStatus = 'QUEUED' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'CANCELLED'
export type TriageStatus = 'NONE' | 'RESOLVED'

/** 누적형 — 상위 역할은 하위 권한을 포함한다 */
export type Role = 'VIEWER' | 'OPERATOR' | 'EDITOR' | 'ADMIN'
export const ROLE_RANK: Record<Role, number> = { VIEWER: 0, OPERATOR: 1, EDITOR: 2, ADMIN: 3 }
export const hasRole = (mine: Role | undefined, need: Role) =>
  mine !== undefined && ROLE_RANK[mine] >= ROLE_RANK[need]

export type JobErrorCode = 'STAGE_TIMEOUT' | 'JOB_TIMEOUT' | 'SOURCE_ERROR' | 'RESOURCE_ERROR' | 'INTERNAL'
export const JOB_ERROR_MESSAGE: Record<JobErrorCode, string> = {
  STAGE_TIMEOUT: '{단계} 처리 중 5분간 진행이 없어 중단했습니다',
  JOB_TIMEOUT: '허용 시간을 넘겨 중단했습니다',
  SOURCE_ERROR: '원본 사이트에 접근하지 못했습니다',
  RESOURCE_ERROR: '처리에 필요한 자원이 부족했습니다',
  INTERNAL: '처리 중 오류가 발생했습니다',
}
/** 1이면 [재시도] 노출 */
export const JOB_ERROR_RETRY: Record<JobErrorCode, 0 | 1> = {
  STAGE_TIMEOUT: 0,
  JOB_TIMEOUT: 0,
  SOURCE_ERROR: 1,
  RESOURCE_ERROR: 1,
  INTERNAL: 0,
}

// --- 07. 활동 로그 ---
export type ActivityResult = '성공' | '실패' | '거부됨'
