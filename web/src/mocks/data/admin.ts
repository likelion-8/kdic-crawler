/** 관리자 목 데이터 — AD-001~AD-011.
 *
 * 페이지·청크는 실제 코퍼스에서 뽑은 pages.ts / chunks.ts를 쓰고, 여기에는 코퍼스에 없는
 * 운영 데이터(승인 요청·파이프라인 작업·평가 실행·활동 로그)만 둔다.
 * 이 타입들은 CM-DF-003 04절에 필드 정의가 없어 프론트가 정한 것이다(기획서 역기재 대상). */
import type {
  ActivityResult, BusinessFunction, JobErrorCode, JobStatus, JobType, PendingAction, Role, TriageStatus,
} from '../../lib/codes'

// ---------------------------------------------------------------- 인증 · 권한

export interface AdminAccount {
  id: string
  email: string
  name: string
  role: Role
  status: '활성' | '잠김' | '초대 대기'
  last_login_at: string | null
}

export const MOCK_ACCOUNTS: AdminAccount[] = [
  { id: 'acc_001', email: 'admin@demo', name: '관리자', role: 'ADMIN', status: '활성', last_login_at: '2026-08-03T09:12:00+09:00' },
  { id: 'acc_002', email: 'editor@demo', name: '편집자', role: 'EDITOR', status: '활성', last_login_at: '2026-08-02T17:40:00+09:00' },
  { id: 'acc_003', email: 'ops@demo', name: '운영자', role: 'OPERATOR', status: '활성', last_login_at: '2026-08-01T11:05:00+09:00' },
  { id: 'acc_004', email: 'viewer@demo', name: '조회자', role: 'VIEWER', status: '잠김', last_login_at: null },
  { id: 'acc_005', email: 'invited@demo', name: '초대중', role: 'VIEWER', status: '초대 대기', last_login_at: null },
]

/** GET /api/admin/roles — 누적형 역할 설명(CM-DF-002 06절) */
export interface RoleDefinition {
  role: Role
  label: string
  description: string
}
export const MOCK_ROLES: RoleDefinition[] = [
  { role: 'VIEWER', label: '조회자', description: '모든 화면 조회. 쓰기 동작 없음' },
  { role: 'OPERATOR', label: '운영자', description: '조회 + 파이프라인 실행·재시도·취소' },
  { role: 'EDITOR', label: '편집자', description: '운영자 + 지식베이스·평가셋·초안 수정 · 게시·적재' },
  { role: 'ADMIN', label: '관리자', description: '편집자 + 전체 캐시·롤백·계정 관리·내보내기' },
]

/** GET /api/admin/me/permissions — 화면이 버튼을 숨기지 않고 '왜 못 누르는지'를 쓰기 위한 목록 */
export interface MyPermissions {
  role: Role
  /** 허용된 동작 키. 없는 키는 403 */
  allowed: string[]
}

// ---------------------------------------------------------------- 변경 요청(승인)

export interface ChangeRequest {
  id: string
  /** 무엇을 하려는 요청인가 — PendingAction과 같은 값 집합 */
  action: PendingAction
  target_page_id: string
  target_title: string
  business_function: BusinessFunction
  /** 위험 작업은 사유가 필수다(CM-DF-004 · AD-011) */
  reason: string
  requested_by: string
  requested_at: string
  status: 'PENDING' | 'APPROVED' | 'REJECTED'
  decided_by?: string
  decided_at?: string
  decision_reason?: string
}

export const MOCK_CHANGE_REQUESTS: ChangeRequest[] = [
  {
    id: 'cr_001', action: 'DELETE', target_page_id: 'ha_ilgl_intro', target_title: '불법재산 신고 안내',
    business_function: '은닉재산 신고', reason: '원본 페이지가 폐지되어 검색에서 제외 필요',
    requested_by: 'editor@demo', requested_at: '2026-08-02T14:20:00+09:00', status: 'PENDING',
  },
  {
    id: 'cr_002', action: 'UPDATE', target_page_id: 'kmrs_apply_mthd', target_title: '착오송금 신청방법',
    business_function: '착오송금 반환 신청', reason: '방문 신청 주소 변경 반영',
    requested_by: 'editor@demo', requested_at: '2026-08-03T10:05:00+09:00', status: 'PENDING',
  },
  {
    id: 'cr_003', action: 'ADD', target_page_id: 'dr_debt_cert', target_title: '채무증명서 발급',
    business_function: '채무조정 안내', reason: '신규 수집 대상 승인 요청',
    requested_by: 'ops@demo', requested_at: '2026-07-30T09:00:00+09:00', status: 'APPROVED',
    decided_by: 'admin@demo', decided_at: '2026-07-30T11:12:00+09:00', decision_reason: '수집 허용 목록에 포함된 URL 확인',
  },
  {
    id: 'cr_004', action: 'EXCLUDE', target_page_id: 'uc_bkrp_mng', target_title: '파산재단 관리 목록',
    business_function: '고객 미수령금 신청', reason: '표 데이터라 답변 품질 저하',
    requested_by: 'ops@demo', requested_at: '2026-07-28T16:30:00+09:00', status: 'REJECTED',
    decided_by: 'admin@demo', decided_at: '2026-07-29T09:40:00+09:00', decision_reason: '검색 커버리지 손실이 커 보류',
  },
]

// ---------------------------------------------------------------- 파이프라인 작업

export interface JobStep {
  /** PIPELINE_STEPS(수집·변환·청킹·검증·게이트·색인·반영) 중 하나 */
  name: string
  status: 'QUEUED' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'SKIPPED'
  /** 진행 중이면 undefined */
  elapsed_ms?: number
}

export interface PipelineJob {
  id: string
  type: JobType
  status: JobStatus
  targets: string[]
  reason: string
  created_by: string
  created_at: string
  /** 진행 계산 기준 시각(epoch ms). 목이 경과 시간으로 단계를 진행시킨다 */
  started_at_ms: number
  steps: JobStep[]
  error?: { code: JobErrorCode; stage: string; detail: string }
  /** 롤백으로 되돌릴 수 있는 직전 성공 작업 */
  rollback_of?: string
}

/** 실행 이력(완료된 것들). 진행 중 작업은 POST /api/admin/jobs로 만들어진다. */
export const MOCK_JOBS: PipelineJob[] = [
  {
    id: 'job_20260729_0300', type: 'FULL_RECRAWL', status: 'SUCCESS', targets: [], reason: '정기 전체 재수집',
    created_by: 'ops@demo', created_at: '2026-07-29T03:00:00+09:00', started_at_ms: 0,
    steps: [
      { name: '수집', status: 'SUCCESS', elapsed_ms: 184_000 },
      { name: '변환', status: 'SUCCESS', elapsed_ms: 21_000 },
      { name: '청킹', status: 'SUCCESS', elapsed_ms: 9_400 },
      { name: '검증', status: 'SUCCESS', elapsed_ms: 3_100 },
      { name: '색인', status: 'SUCCESS', elapsed_ms: 62_000 },
      { name: '반영', status: 'SUCCESS', elapsed_ms: 1_200 },
    ],
  },
  {
    id: 'job_20260801_1130', type: 'SELECTED_RECRAWL', status: 'FAILED',
    targets: ['sender_docs', 'receiver_docs'], reason: '서식 링크 변경 확인',
    created_by: 'ops@demo', created_at: '2026-08-01T11:30:00+09:00', started_at_ms: 0,
    steps: [
      { name: '수집', status: 'FAILED', elapsed_ms: 47_000 },
      { name: '변환', status: 'SKIPPED' },
      { name: '청킹', status: 'SKIPPED' },
      { name: '검증', status: 'SKIPPED' },
      { name: '색인', status: 'SKIPPED' },
      { name: '반영', status: 'SKIPPED' },
    ],
    // JOB_ERROR_RETRY[SOURCE_ERROR] === 1 → 화면에 [재시도]가 뜬다
    error: { code: 'SOURCE_ERROR', stage: '수집', detail: 'fins.kdic.or.kr 응답 없음 (연결 시간 초과 3회)' },
  },
  {
    id: 'job_20260802_2000', type: 'REINDEX', status: 'CANCELLED', targets: [], reason: '임베딩 모델 교체 검토 중 중단',
    created_by: 'admin@demo', created_at: '2026-08-02T20:00:00+09:00', started_at_ms: 0,
    steps: [
      { name: '수집', status: 'SKIPPED' },
      { name: '변환', status: 'SKIPPED' },
      { name: '청킹', status: 'SUCCESS', elapsed_ms: 8_800 },
      { name: '검증', status: 'SUCCESS', elapsed_ms: 2_900 },
      { name: '색인', status: 'FAILED' },
      { name: '반영', status: 'SKIPPED' },
    ],
  },
]

// ---------------------------------------------------------------- 활동 로그(AD-011)

export interface ActivityEvent {
  id: string
  occurred_at: string
  actor: string
  actor_role: Role
  /** CM-DF-002 07절 이벤트 사전의 행위명 */
  action: string
  target: string
  result: ActivityResult
  /** 위험 작업은 사유가 필수라 항상 있다 */
  reason?: string
  request_id: string
  ip: string
  triage: TriageStatus
}

export const MOCK_ACTIVITY_EVENTS: ActivityEvent[] = [
  { id: 'ev_001', occurred_at: '2026-08-03T10:05:12+09:00', actor: 'editor@demo', actor_role: 'EDITOR', action: '페이지 삭제 요청', target: 'ha_ilgl_intro', result: '성공', reason: '원본 페이지 폐지', request_id: 'req_a1', ip: '10.0.3.21', triage: 'NONE' },
  { id: 'ev_002', occurred_at: '2026-08-03T09:12:44+09:00', actor: 'admin@demo', actor_role: 'ADMIN', action: '로그인', target: 'admin@demo', result: '성공', request_id: 'req_a2', ip: '10.0.3.10', triage: 'NONE' },
  { id: 'ev_003', occurred_at: '2026-08-02T20:01:03+09:00', actor: 'admin@demo', actor_role: 'ADMIN', action: '파이프라인 작업 취소', target: 'job_20260802_2000', result: '성공', reason: '임베딩 모델 교체 검토', request_id: 'req_a3', ip: '10.0.3.10', triage: 'RESOLVED' },
  { id: 'ev_004', occurred_at: '2026-08-02T18:31:20+09:00', actor: 'editor@demo', actor_role: 'EDITOR', action: '프롬프트 게시', target: 'prompt v12', result: '성공', reason: '회귀 게이트 미통과 상태로 게시(경고)', request_id: 'req_a4', ip: '10.0.3.21', triage: 'NONE' },
  { id: 'ev_005', occurred_at: '2026-08-01T11:31:47+09:00', actor: 'ops@demo', actor_role: 'OPERATOR', action: '선택 재수집 실행', target: 'sender_docs, receiver_docs', result: '실패', reason: '서식 링크 변경 확인', request_id: 'req_a5', ip: '10.0.3.33', triage: 'NONE' },
  { id: 'ev_006', occurred_at: '2026-08-01T09:02:10+09:00', actor: 'viewer@demo', actor_role: 'VIEWER', action: '대화 로그 내보내기', target: 'logs 2026-07', result: '거부됨', request_id: 'req_a6', ip: '10.0.3.44', triage: 'NONE' },
  { id: 'ev_007', occurred_at: '2026-07-31T15:44:02+09:00', actor: 'admin@demo', actor_role: 'ADMIN', action: 'RAG 파라미터 반영', target: 'top_k 5 → 6', result: '성공', reason: 'Recall 개선 실험 반영', request_id: 'req_a7', ip: '10.0.3.10', triage: 'RESOLVED' },
  { id: 'ev_008', occurred_at: '2026-07-30T11:12:33+09:00', actor: 'admin@demo', actor_role: 'ADMIN', action: '변경 요청 승인', target: 'cr_003', result: '성공', reason: '수집 허용 목록 확인', request_id: 'req_a8', ip: '10.0.3.10', triage: 'NONE' },
]

// ---------------------------------------------------------------- 추천 질문(AD-009)

export interface SuggestedQuestion {
  id: string
  text: string
  business_function: BusinessFunction
  active: boolean
  /** 노출 순서. 활성 최대 10 */
  order: number
  click_count: number
}

/** 활성 10개는 **기획서 CB-001 §2.4 「자주 묻는 질문 TOP 10」 리스트 원문 그대로**다(순서 포함).
 * 착오송금에 크게 편중돼 있는데 이는 오타가 아니라 목업 그대로다 — AD-009 추천 질문 관리의
 * '업무 균형 경고' 상태를 그 화면에서 실제로 보여주기 위한 예시다(기획서 v4.7 결정).
 * 비활성 2건은 등록(최대 15) > 활성(최대 10) 관계와 토글 상태를 함께 보여주려고 남겨둔다. */
export const MOCK_SUGGESTED_QUESTIONS: SuggestedQuestion[] = [
  { id: 'sq_01', text: '착오송금 반환까지 얼마나 걸리나요?', business_function: '착오송금 반환 신청', active: true, order: 1, click_count: 412 },
  { id: 'sq_02', text: '반환지원 대상이 아닌 경우는 어떤 경우인가요?', business_function: '착오송금 반환 신청', active: true, order: 2, click_count: 388 },
  { id: 'sq_03', text: '반환지원 대상 금액은 얼마까지인가요?', business_function: '착오송금 반환 신청', active: true, order: 3, click_count: 331 },
  { id: 'sq_04', text: '어떤 금융회사·앱이 반환지원 대상인가요?', business_function: '착오송금 반환 신청', active: true, order: 4, click_count: 287 },
  { id: 'sq_05', text: '방문 신청도 가능한가요?', business_function: '착오송금 반환 신청', active: true, order: 5, click_count: 244 },
  { id: 'sq_06', text: '상속인 금융거래 조회 기간은 어떻게 되나요?', business_function: '고객 미수령금 신청', active: true, order: 6, click_count: 201 },
  { id: 'sq_07', text: '보이스피싱 피해도 신청할 수 있나요?', business_function: '착오송금 반환 신청', active: true, order: 7, click_count: 178 },
  { id: 'sq_08', text: '토스·카카오페이 간편송금도 지원되나요?', business_function: '착오송금 반환 신청', active: true, order: 8, click_count: 156 },
  { id: 'sq_09', text: '착오송금 후 언제까지 신청해야 하나요?', business_function: '착오송금 반환 신청', active: true, order: 9, click_count: 134 },
  { id: 'sq_10', text: '은행 반환절차 없이 바로 신청할 수 있나요?', business_function: '착오송금 반환 신청', active: true, order: 10, click_count: 118 },
  { id: 'sq_11', text: '예금자보호 한도가 얼마인가요?', business_function: '예금자보호제도', active: false, order: 11, click_count: 0 },
  { id: 'sq_12', text: '보호되지 않는 금융상품은 무엇인가요?', business_function: '예금자보호제도', active: false, order: 12, click_count: 0 },
]
