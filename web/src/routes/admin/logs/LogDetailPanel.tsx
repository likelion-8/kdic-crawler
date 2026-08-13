/** AD-005 [2][3][4] — 우측 상세 패널.
 * 정상·범위 외 행 → 단계별 처리 추적(구획 5개) · 실패 행 → 오류 상세 (Desc 2 마지막 불렛).
 * 표시되는 질문·답변·의견은 전부 마스킹된 저장본이다. 원문 복호화 진입점은 두지 않는다(Desc 2). */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Button } from '../../../components/ui'
import { Separator } from '@/components/shadcn/separator'
import { INTENT_LABEL, QUESTION_TYPE_LABEL } from '../../../lib/codes'
import {
  FEEDBACK_LABEL,
  LOG_STATUS_LABEL,
  formatMonthDayTime,
} from './api'
import type { ConversationLogDetail, LangfuseTrace } from './api'
import { formatTime } from '../../../lib/format'

export interface LogDetailPanelProps {
  detail: ConversationLogDetail
  /** OPERATOR 이상 — 재실행·처리 완료 */
  canRun: boolean
  /** EDITOR 이상 — 테스트셋 보강 후보 등록 */
  canEdit: boolean
  onRerun: () => void
  onResolve: () => void
  onAddCandidate: () => void
  rerunPending: boolean
  candidatePending: boolean
}

/** 모달 헤더용 제목·부제 — 화면과 상세가 같은 문구를 쓰도록 여기서 만든다 */
export const logDetailTitle = (d: ConversationLogDetail) => `“${d.question_masked}”`
export const logDetailMeta = (d: ConversationLogDetail) =>
  `${formatMonthDayTime(d.occurred_at)} · 요청 ID ${d.request_id} · ${LOG_STATUS_LABEL[d.status]}${
    d.error ? '' : ` · 응답 ${d.latency_s ?? '—'}초`
  }`

export function LogDetailPanel(props: LogDetailPanelProps) {
  const { detail } = props
  return detail.error ? <ErrorPanel {...props} /> : <TracePanel {...props} />
}

/** 구획 제목 — 13px 세미볼드. 라벨마다 아이콘을 달지 않는다(아이콘은 내비·액션·상태에만) */
function SectionTitle({ children }: { children: ReactNode }) {
  return <h3 className="mb-2 text-[13px] font-semibold tracking-[-0.01em]">{children}</h3>
}

/** Langfuse 링크 — 정상 건과 실패 건이 같이 쓴다. 실패 건이야말로 추적이 필요하다.
 *  세 상태: 추적 없음 / id만 있고 URL 없음 / 완성 URL. URL은 서버가 만들어 준다(api.ts 주석) */
function TraceLink({ trace }: { trace: LangfuseTrace | null }) {
  if (trace === null) {
    return <p className="mt-1.5 text-xs text-muted-foreground">이 실행에는 추적 기록이 없습니다</p>
  }
  if (trace.url === null) {
    // URL 없이 id만 온 경우 — 링크를 지어내지 않고 값만 보여준다(Langfuse 호스트는 서버가 안다)
    return (
      <p className="mt-1.5 text-xs break-all text-muted-foreground">
        추적 ID <span className="font-mono">{trace.id}</span>
      </p>
    )
  }
  return (
    <a
      className="mt-1.5 inline-flex min-h-11 items-center gap-1 text-[13px] font-medium text-primary hover:underline"
      href={trace.url}
      target="_blank"
      rel="noreferrer"
    >
      Langfuse에서 검색 후보·단계별 소요 보기
      <span aria-hidden="true">↗</span>
      <span className="sr-only">새 창에서 열림</span>
    </a>
  )
}

/** [2][3] 단계별 처리 추적 */
function TracePanel({ detail, canEdit, onAddCandidate, candidatePending }: LogDetailPanelProps) {
  const [expanded, setExpanded] = useState(false)
  const { classification: c } = detail
  return (
    // 질문·시각·요청 ID는 DetailModal 헤더가 그린다 — 여기서 두 번 쓰지 않는다
    <section aria-label="처리 과정">
      <div>
        <SectionTitle>분류</SectionTitle>
        <p className="text-[13px]">
          {INTENT_LABEL[c.intent]}
          {c.business_function ? ` · ${c.business_function}` : ''} · {QUESTION_TYPE_LABEL[c.question_type]}
        </p>
        <p className="mt-1.5 grid grid-cols-[120px_1fr] gap-2.5 text-[13px]">
          <span className="text-muted-foreground">출처 판정</span>
          <span>
            {/* 백엔드가 원천 부재로 null 을 내린다(admin_logs.py:419-422) — '미사용' 단정은 거짓이 된다 */}
            {c.source_used === null ? '판정 원천 없음' : c.source_used ? '사용' : '미사용'}
            {c.marker === null ? '' : ` · 마커 [${c.marker}]`}
          </span>
        </p>
        {/* 마커가 어긋나 정규화로 보정한 건은 '표기 보정'으로 기록된다(Desc 2) */}
        {c.normalized && <p className="mt-1.5 text-xs text-muted-foreground">표기 보정</p>}
      </div>

      <Separator className="my-4" />

      {/* 검색 후보·단계별 소요는 Langfuse가 전담한다(2026-08-04 팀 결정 — api.ts LangfuseTrace 주석).
          여기서는 rag_runs가 실제로 가진 총 소요만 적고, 나머지는 추적으로 보낸다.
          목업대로 두 구획을 남겨 두면 실서버에서 영구히 빈 채로 뜨고, 그 빈 상태 문구가
          '검색 근거가 사용되지 않았습니다'라 운영자에게 거짓을 말하게 된다 */}
      <div>
        <SectionTitle>처리 추적</SectionTitle>
        <p className="text-[13px]">
          총 소요{' '}
          <span className="font-semibold tabular-nums">
            {detail.total_latency_ms === null ? '—' : `${(detail.total_latency_ms / 1000).toFixed(1)}초`}
          </span>
        </p>
        <TraceLink trace={detail.langfuse} />
      </div>

      <Separator className="my-4" />

      <div>
        <SectionTitle>답변 전문 (마스킹)</SectionTitle>
        <p className="text-[13px] leading-relaxed">
          {expanded ? detail.answer_masked_full : detail.answer_masked_preview}
        </p>
        {/* 전문이 응답에 이미 담겨 있어 펼치기는 클라이언트 토글이다(11 §L3 제안) */}
        <button
          type="button"
          className="mt-1 rounded-sm py-1 text-xs font-medium text-primary outline-none transition-colors duration-200 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? '접기▴' : '전체 펼치기▾'}
        </button>
      </div>

      {detail.feedback_detail && (
        // 사용자 피드백만 다른 표면 — 목업 연노랑 유지
        <div className="mt-4 flex flex-col items-start gap-2 rounded-md bg-warning-bg p-4">
          <p className="text-[13px]">
            사용자 피드백 : {FEEDBACK_LABEL[detail.feedback_detail.vote]} ·{' '}
            {formatTime(detail.feedback_detail.at)}
          </p>
          <p className="text-[13px]">
            사유 : {detail.feedback_detail.reason_label} · “{detail.feedback_detail.comment}”
          </p>
          {canEdit && (
            <Button size="sm" onClick={onAddCandidate} loading={candidatePending}>
              테스트셋 보강 후보로 등록
            </Button>
          )}
        </div>
      )}

      {/* 후보 등록은 실패·피드백 건 전용이 아니다 — 좋은 답변도 평가셋 보강 대상(CM-DF-002 07절) */}
      {canEdit && !detail.feedback_detail && (
        <div className="mt-4">
          <Button size="sm" onClick={onAddCandidate} loading={candidatePending}>
            테스트셋 보강 후보로 등록
          </Button>
        </div>
      )}
    </section>
  )
}


/** [4] 실패 건(붉은 행) 선택 시 : 오류 상세 패널 */
function ErrorPanel({
  detail,
  canRun,
  canEdit,
  onRerun,
  onResolve,
  onAddCandidate,
  rerunPending,
  candidatePending,
}: LogDetailPanelProps) {
  const error = detail.error!
  const rows: [string, string, boolean][] = [
    ['오류 코드', `${error.code} · ${error.meaning}`, true],
    ['사용자 노출 문구', `"${error.user_message}"`, false],
    ['서버 자동 재시도', error.auto_retry, false],
    ['대체 출처', error.fallback, false],
  ]

  return (
    <section aria-label="오류 상세">
      <div>
        <SectionTitle>오류 정보</SectionTitle>
        <dl className="space-y-1.5">
          {rows.map(([label, value, strong]) => (
            <div className="grid grid-cols-[120px_1fr] gap-2.5 text-[13px]" key={label}>
              <dt className="text-muted-foreground">{label}</dt>
              <dd className={strong ? 'font-semibold text-danger-fg' : undefined}>{value}</dd>
            </div>
          ))}
        </dl>
      </div>

      <Separator className="my-4" />

      {/* 단계별 소요는 Langfuse가 갖는다 — 여기서는 rag_runs가 가진 '어디서 멈췄나'만 적는다 */}
      <div>
        <SectionTitle>실패 지점</SectionTitle>
        <dl className="space-y-1 text-[13px]">
          <div className="grid grid-cols-[120px_1fr] gap-2.5">
            <dt className="text-muted-foreground">멈춘 단계</dt>
            {/* 기호만으로 알리지 않도록 상태 단어를 함께 읽힌다(CM-DF-004 09절) */}
            <dd className="font-semibold text-danger-fg">
              <span aria-hidden="true">✗</span>
              <span className="sr-only">실패</span> {error.failure_stage ?? '확인할 수 없음'}
            </dd>
          </div>
          {error.root_cause !== null && (
            <div className="grid grid-cols-[120px_1fr] gap-2.5">
              <dt className="text-muted-foreground">원인</dt>
              <dd className="break-keep">{error.root_cause}</dd>
            </div>
          )}
        </dl>
        <TraceLink trace={detail.langfuse} />
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {canRun && (
          <Button variant="primary" size="sm" onClick={onRerun} loading={rerunPending}>
            동일 질문 재실행
          </Button>
        )}
        {canEdit && (
          <Button size="sm" onClick={onAddCandidate} loading={candidatePending}>
            테스트셋 보강 후보 등록
          </Button>
        )}
        {canRun && (
          <Button size="sm" onClick={onResolve}>
            처리 완료 표시
          </Button>
        )}
      </div>
    </section>
  )
}
