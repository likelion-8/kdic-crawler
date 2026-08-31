/** 기획서에 박힌 고정 상수. 출처 = PRD-01/02 · CM-DF-003/004.
 * 값을 바꾸려면 기획서를 먼저 고친다(SYNC RULE). */

// --- 챗봇 ---
/** 델타 수신 간격이 이만큼 끊기면 '완료 후 일괄 표시'로 폴백 (PRD-02 §2) */
export const CHAT_IDLE_TIMEOUT_MS = 30_000
/** 마지막 활동 기준 대화 복원 창 (PRD-02 §2) */
export const CONVERSATION_RESTORE_WINDOW_H = 24
/** 피드백 자유 의견 최대 길이 (PRD-02 §1 feedback) */
export const FEEDBACK_FREETEXT_MAX = 200

// --- 관리자 세션 3타이머 (PRD-01 §3) ---
export const ADMIN_SESSION_IDLE_MIN = 30 // 유휴 — [연장]·인증된 API·초안 자동저장으로만 갱신(폴링 제외)
export const ADMIN_REAUTH_WINDOW_MIN = 30 // 위험 작업 전 비밀번호 재확인 유효 시간

// --- 관리자 로그인 보호 (PRD-01 §3) ---
export const LOGIN_FAIL_LOCK_COUNT = 5
export const LOGIN_LOCK_MIN = 10
export const RESET_TOKEN_MIN = 30

// --- 운영 (PRD-02 §1) ---
export const RATE_BLOCK_MIN = 10
export const QUERY_CACHE_TTL_H = 24
export const PIPELINE_CONCURRENCY = 1 // 동시 실행 1개 → 실행 버튼 disabled 조건

/**
 * 파이프라인 7단계 — 이름·순서 고정 (CM-DF-001 진행 스텝). src/worker.py 의 STEPS 와 같아야 한다.
 * '게이트'는 2026-08-14 신설 — 새 청크를 메모리 인덱스로 올려 홀드아웃으로 채점한다.
 * 2026-08-19 정책 변경: 미달이어도 색인은 진행하고 판정은 경고로만 표시한다(차단 없음).
 * 롤백 잡에서는 SKIPPED 다 — 직전에 통과했던 스냅샷이라 다시 재는 의미가 없다.
 */
export const PIPELINE_STEPS = ['수집', '변환', '청킹', '검증', '게이트', '색인', '반영'] as const

/** 초안 자동 저장 주기 (CM-DF-003 04절) */
export const DRAFT_AUTOSAVE_MS = 10_000

/** 모든 시각은 브라우저 타임존과 무관하게 KST 고정 표기 (PRD-02 §3-f) */
export const TIMEZONE = 'Asia/Seoul'
