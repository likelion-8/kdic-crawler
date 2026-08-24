/** API 계약 — CM-DF-003 03·04절이 정본.
 *
 * 백엔드 팀 참고: 이 파일이 프론트가 기대하는 스키마 전부다. FastAPI Pydantic 모델을
 * 여기에 맞추면 목(mock)을 끄는 것만으로 붙는다. 자세한 대응은 docs/frontend-handoff.md. */

import type { BusinessFunction, ErrorCode, Intent, ResponseType } from '../codes'

// ---------------------------------------------------------------- 공통

/** 오류 응답 — CM-DF-003 03절 / PRD-02 §3에서 유일하게 필드 단위로 확정된 스키마.
 * 🔴 FE는 user_message를 그대로 노출한다. 문구를 만들거나 의역하지 않는다. */
export interface ApiError {
  code: ErrorCode
  /** 사용자에게 그대로 보여줄 문구 */
  user_message: string
  /** true일 때만 [다시 시도] 노출 */
  retryable: boolean
  /** 원소 스키마는 sources와 동일 (CB-004 Case 4 "동일 컴포넌트 재사용") */
  fallback_sources: Source[]
  request_id: string
}

/** 목록 응답 공통 봉투. CM-DF-003에 명시가 없어 프론트가 정의했다(기획서 역기재 대상). */
export interface Page<T> {
  items: T[]
  total: number
  page: number
  size: number
}

// ---------------------------------------------------------------- 챗봇

/** 출처 카드 1건. 코드 쪽 원천은 src/citation.py `format_citation()`. */
export interface Source {
  page_id: string
  /** "업무 > 대분류 > ..." 경로 (코드에서는 sub_category) */
  breadcrumb: string
  title: string
  url: string
}

/** 민원처리 답변에 붙는 서류·신청 페이지. 코드 원천은 src/civil_petition.py. */
export interface Attachment {
  label: string
  url: string
  kind: 'document' | 'link'
}

/** 되묻기 (CB-005). **선택지까지 서버가 준다** — B-01.
 *
 * 선택지를 프론트 상수로 박아두면 서버가 다른 축으로 되물을 때 질문만 바뀌고 버튼은
 * 그대로 남는다. `options`가 비면 버튼을 그리지 않는다 — 하드코딩으로 되돌아가지 않기
 * 위한 규칙이다. 현재 서버가 내려주는 축은 업무 5종(src/clarify.py). */
export interface Clarification {
  question: string
  options: ClarificationOption[]
}

export interface ClarificationOption {
  /** 화면에 그리고, 선택 시 그대로 일반 메시지로 전송된다(요청 스키마를 늘리지 않는다) */
  label: string
  /** 서버가 자기 라우팅·집계에 쓰는 값. 프론트는 읽지 않는다 */
  value?: string
}

/** 복합 질문(멀티쿼리)의 하위 답변 1건 — 하위마다 검색·근거·출처가 독립이다.
 *
 * 🔴 `sub_answers`가 비어 있지 않으면 **최상위 `sources`·`attachments`는 빈 배열**이고
 * 근거는 전부 하위로 내려온다(백엔드 확정 2026-08-05 · backend-structure #26).
 * 하위 간 출처 중복 제거는 하지 않는다 — 같은 페이지가 두 하위에 나와도 각각 그린다. */
export interface SubAnswer {
  /** 분해된 하위 질문. 화면에는 이 답변 묶음의 제목으로 그린다 */
  title: string
  answer: string
  sources: Source[]
  attachments: Attachment[]
}

/** POST /api/chat 확정 응답. SSE `done` 이벤트가 이 객체 전문을 싣는다. */
export interface ChatResponse {
  answer: string
  sources: Source[]
  attachments: Attachment[]
  /** 복합 질문일 때만 채워진다. 비어 있으면 단일 질문이라 `answer`+`sources`를 그대로 쓴다 */
  sub_answers?: SubAnswer[]
  /** true면 출처·서류·신청 페이지 섹션을 전부 렌더하지 않는다 */
  out_of_scope: boolean
  session_id: string
  request_id: string
  /** 화면은 쓰지 않는다(로깅·분석용). 백엔드 ChatResponse에 아직 없어 선택으로 둔다 */
  latency_ms?: number
  error?: ApiError
  /** 로깅·분석용. 렌더 분기는 이 값이 아니라 필드 존재 검사로 한다 */
  response_type?: ResponseType
  clarification?: Clarification
  intent?: Intent
  business_function?: BusinessFunction
}

export interface ChatRequest {
  message: string
  session_id?: string
}

/** SSE 이벤트 — CM-DF-003 03절 "실시간 출력(SSE)" 4종.
 * 순서: accepted → answer_delta* → done | error
 *
 * `sources`·`attachments` 이벤트는 2026-08-05 폐지됐다 — 근거 사용 판정이 스트리밍이 끝난
 * 뒤에 확정돼 어차피 `done`과 같은 시점에 나갔다(`api/rag/sse.py`). 출처는 `done`의
 * `sources`·`attachments`(복합 질문이면 `sub_answers` 안의 것)로 그린다. */
export type ChatStreamEvent =
  | { event: 'accepted'; data: { request_id: string; session_id: string } }
  | { event: 'answer_delta'; data: { text: string } }
  | { event: 'done'; data: ChatResponse }
  | { event: 'error'; data: ApiError }

// ---------------------------------------------------------------- 피드백

export interface FeedbackRequest {
  /** 피드백을 붙일 **답변**의 id. 쓰기 멱등키인 `request_id`와 뜻이 달라 이름을 나눴다 —
   *  한 이름이 두 뜻이면 백엔드가 둘 중 하나로 잘못 구현한다 (B-07 확정 2026-08-05) */
  answer_request_id: string
  session_id: string
  /** 👍 / 👎 */
  vote: 'up' | 'down'
}

export interface FeedbackResponse {
  feedback_id: string
}

/** 사유 보완 — PATCH /api/feedback/{feedback_id} */
export interface FeedbackPatch {
  reason_codes: string[]
  /** 마스킹 후 저장 · 최대 200자 */
  comment?: string
}

// ---------------------------------------------------------------- 대화 복원

/** GET /api/sessions/{session_id} 의 메시지 1건.
 *
 * 이 타입은 화면(ChatPage)과 목(mocks/handlers/chat.ts) 두 곳이 쓴다. 전에는 각자 복사해
 * 갖고 있어서 한쪽만 고치면 조용히 어긋났다 — 여기 하나만 둔다. */
export interface RestoredMessage {
  role: 'user' | 'assistant'
  text: string
  /** 이 메시지의 시각(ISO8601 · KST) — 말풍선에 찍는다. 없으면 시각을 그리지 않는다.
   *  복원된 대화에 '지금' 시각을 찍으면 90분 전 대화에 방금 시각이 붙어 거짓이 된다 */
  at?: string
  request_id?: string
  /** 답변 말풍선 복원용. 사용자 메시지는 비어 있다.
   *
   *  🔴 `sub_answers`가 빠지면 복합 질문이 복원될 때 근거가 통째로 사라진다 — 그 경우
   *  최상위 `sources`·`attachments`는 규약상 빈 배열이고 근거가 전부 하위에 있기 때문이다
   *  (SubAnswer 주석 참고). 본문만 남고 출처가 하나도 없는 말풍선이 된다. */
  response?: Pick<ChatResponse, 'sources' | 'attachments' | 'sub_answers' | 'out_of_scope'>
}

export interface RestoredSession {
  session_id: string
  /** ISO8601 · KST. 이 시각이 24시간(CONVERSATION_RESTORE_WINDOW_H)보다 오래되면 서버가 404를 준다 */
  last_activity_at: string
  messages: RestoredMessage[]
}

// ---------------------------------------------------------------- 상태 점검

/** GET /api/health — 점검·기능 비활성 시 전면 안내(CB-004 Case 6).
 * FE는 health만 호출한다. /api/ready는 인프라 전용. */
export interface HealthResponse {
  status: 'ok' | 'maintenance' | 'degraded'
  maintenance: boolean
  disabled_features: string[]
  /** 점검 중일 때 화면에 그대로 노출할 문구 (FE가 만들지 않는다) */
  user_message?: string
}

/** GET /api/suggestions — CB-001 자주 묻는 질문. 활성 최대 10. */
export interface Suggestion {
  id: string
  text: string
  business_function?: BusinessFunction
}
