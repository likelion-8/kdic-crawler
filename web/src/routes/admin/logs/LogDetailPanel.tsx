/** AD-005 [2][3][4] — 우측 상세 패널.
 * 정상·범위 외 행 → 단계별 처리 추적(구획 5개) · 실패 행 → 오류 상세 (Desc 2 마지막 불렛).
 * 표시되는 질문·답변·의견은 전부 마스킹된 저장본이다. 원문 복호화 진입점은 두지 않는다(Desc 2). */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { Button } from '../../../components/ui'
import { Separator } from '@/components/shadcn/separator'
import { INTENT_LABEL, QUESTION_TYPE_LABEL } from '../../../lib/codes'
import {
  FEEDBACK_LABEL,
  LOG_STATUS_LABEL,
  formatMonthDayTime,
} from './api'
import type { ConversationLogDetail, LangfuseTrace, RunObservation } from './api'
import { formatTime } from '../../../lib/format'

export interface LogDetailPanelProps {
  detail: ConversationLogDetail
  /** OPERATOR 이상 — 처리 완료 */
  canRun: boolean
  onResolve: () => void
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

/**
 * 답변이 무엇을 근거로 삼았는지 — 민원 대응의 첫 단추다.
 *
 * 이게 없으면 관리자는 "답변이 이상하다"는 민원을 받아도 **검색이 잘못됐는지 · 프롬프트가
 * 잘못됐는지 · 데이터가 아예 없는지**를 가릴 수 없어 다음 화면(AD-007/AD-008/AD-002)을
 * 고르지 못한다. 근거 페이지가 엉뚱하면 검색 문제, 근거는 맞는데 답이 틀리면 프롬프트 문제,
 * 근거가 비었으면 데이터 문제 — 이 세 갈래가 여기서 갈린다.
 *
 * 검색 후보 전체와 단계별 소요는 Langfuse 전담이다(2026-08-04 팀 결정). 여기 두는 것은
 * '근거로 실제 쓴 페이지'까지이고, 그 이상은 추적 링크로 보낸다.
 */
function EvidencePanel({ observation }: { observation: RunObservation }) {
  return (
    <div>
      <SectionTitle>근거</SectionTitle>
      <ul className="space-y-3">
        {observation.subs.map((sub, i) => (
          <li key={i} className="text-[13px]">
            {observation.subs.length > 1 && (
              <p className="mb-1 font-medium">{sub.question}</p>
            )}
            {sub.top.length === 0 ? (
              // 근거가 비었다 = 검색이 아무것도 못 찾았거나 무관질문 게이트가 잘랐다.
              // '데이터 없음' 갈래의 신호라 회색 문구로 죽이지 않고 명시한다.
              <p className="text-muted-foreground">검색된 근거 없음 — 지식베이스(AD-002) 점검 대상</p>
            ) : (
              <ul className="space-y-0.5">
                {sub.top.map((t) => (
                  <li key={t.chunk_id} className="grid grid-cols-[1fr_auto] gap-2">
                    <span className="truncate font-mono text-xs">{t.page_id}</span>
                    <span className="tabular-nums text-xs text-muted-foreground">
                      {t.score.toFixed(3)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {/* 판정 null 은 '판정 안 함'이지 '아니오'가 아니다 — 단정 문구를 쓰지 않는다 */}
            {sub.used_source === false && (
              <p className="mt-1 text-xs text-muted-foreground">이 근거를 답변에 쓰지 않음</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * [다음 조치] — 근거 구획이 가른 갈래를 **누를 수 있게** 만든다(2026-08-18).
 *
 * 관측(observation)이 판정한 상태로 하나만 primary 로 강조한다. 강조는 힌트지 판정이
 * 아니다 — 남은 버튼을 다 보여준다. 감추면 강조가 틀렸을 때 관리자가 갇힌다.
 * [지식베이스에서 찾아보기]는 2026-08-19 제거했다 — 질문 문구로 페이지를 훑는 것뿐이라
 * 검색·프롬프트 조치처럼 원인을 좁혀 주지 못했다. 근거가 비어 hint 가 'data' 인 경우엔
 * 아무 버튼도 강조되지 않는데, 남은 둘 중 어느 쪽도 답이 아니므로 그게 맞다.
 * 목적지에는 ?from=log:{request_id} 와 프리필 값을 넘긴다. 목적지 상단 되돌아가기 띠에서
 * [처리 완료]를 눌러도 이 로그의 처리 상태가 바뀌어 루프가 닫힌다(돌아오지 않아도 된다).
 */
function NextActions({ detail }: { detail: ConversationLogDetail }) {
  const navigate = useNavigate()
  const subs = detail.observation?.subs ?? []
  const anyTop = subs.some((s) => s.top.length > 0)
  const anyUsed = subs.some((s) => s.used_source === true)
  // 근거 없음 → 데이터 / 근거 있으나 미사용 → 검색(엉뚱한 근거) / 근거 사용했는데 나쁨 → 프롬프트
  const hint: 'data' | 'search' | 'prompt' = !anyTop ? 'data' : !anyUsed ? 'search' : 'prompt'
  const from = `from=log:${encodeURIComponent(detail.request_id)}`
  const q = encodeURIComponent(detail.question_masked)
  const v = (k: typeof hint) => (hint === k ? 'primary' : 'secondary')
  return (
    <div className="mt-3">
      <SectionTitle>다음 조치</SectionTitle>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant={v('search')} onClick={() => navigate(`/admin/settings/rag?q=${q}&${from}`)}>
          검색 설정 비교하기
        </Button>
        <Button size="sm" variant={v('prompt')} onClick={() => navigate(`/admin/settings/prompt?${from}`)}>
          답변 규칙 고치기
        </Button>
      </div>
    </div>
  )
}

/** rag_runs.failure_stage 는 파이프라인 내부 식별자다 — 화면에는 사람이 읽는 단계명으로 적는다.
 *  모르는 값은 지어내지 않고 원본을 그대로 보여준다(단계가 늘어나도 화면이 거짓말하지 않는다). */
const STAGE_LABEL: Record<string, string> = {
  retrieval: '검색',
  llm: '답변 생성',
}
const stageLabel = (stage: string | null) =>
  stage === null ? '확인할 수 없음' : (STAGE_LABEL[stage] ?? stage)

/** 처리 상태 꼬리 — 미처리면 [처리 완료 표시], 처리했으면 그때 남긴 조치 사유.
 *
 * 사유는 활동 로그(AD-011)에도 쌓이지만 거기까지 찾아가야 보였다. 조치를 한 화면에서
 * 바로 읽히는 게 맞다. 정상 건과 실패 건이 같은 꼬리를 쓴다. */
function TriageFooter({ detail, canRun, onResolve }: LogDetailPanelProps) {
  if (detail.triage === 'RESOLVED') {
    return (
      <div className="mt-4 rounded-md border border-border p-3">
        <SectionTitle>조치 내역</SectionTitle>
        <dl className="space-y-1 text-[13px]">
          <div className="grid grid-cols-[120px_1fr] gap-2.5">
            <dt className="text-muted-foreground">조치 사유</dt>
            {/* 관측 이전에 처리한 건은 사유가 남아 있지 않다 — 없다고 말하지 지어내지 않는다 */}
            <dd className="break-keep">{detail.triage_reason ?? '기록되지 않았습니다'}</dd>
          </div>
          {/* null 만 막으면 부족하다 — 서버가 이 필드를 아직 안 내려주는 배포에서는 undefined 가
              와서 '처리 · —' 같은 빈 행이 그려진다. 값이 있을 때만 그린다 */}
          {detail.triaged_by && (
            <div className="grid grid-cols-[120px_1fr] gap-2.5">
              <dt className="text-muted-foreground">처리</dt>
              <dd>
                {detail.triaged_by}
                {detail.triaged_at ? ` · ${formatMonthDayTime(detail.triaged_at)}` : ''}
              </dd>
            </div>
          )}
        </dl>
      </div>
    )
  }
  if (!canRun) return null
  return (
    <div className="mt-4">
      <Button size="sm" onClick={onResolve}>
        처리 완료 표시
      </Button>
    </div>
  )
}


/** [2][3] 단계별 처리 추적 */
function TracePanel({ detail, canRun, onResolve }: LogDetailPanelProps) {
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

      {detail.observation && (
        <>
          <Separator className="my-4" />
          <EvidencePanel observation={detail.observation} />
          <NextActions detail={detail} />
        </>
      )}

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
        </div>
      )}

      {/* 처리 완료 — 실패 건 전용이던 것을 전체 건으로(2026-08-18). 나쁨 평가 대응은 정상 건이
          대부분이라, 여기 없으면 조치를 끝내고도 대시보드 할 일 건수가 영원히 안 줄어든다 */}
      <TriageFooter detail={detail} canRun={canRun} onResolve={onResolve} />
    </section>
  )
}


/** [4] 실패 건(붉은 행) 선택 시 : 오류 상세 패널 */
function ErrorPanel({ detail, canRun, onResolve }: LogDetailPanelProps) {
  const error = detail.error!
  // 4행은 서버가 error_code 하나에서 파생한다. 그 컬럼(2026-08-19) 이전 실패는 전부 null 이라
  // 행을 그리지 않는다 — 종전에는 빈 문자열을 그려 '오류 코드 ·' 같은 껍데기가 보였다.
  const rows: [string, string, boolean][] =
    error.code === null
      ? []
      : [
          ['오류 코드', `${error.code} · ${error.meaning}`, true],
          ['사용자 노출 문구', `"${error.user_message}"`, false],
          ['서버 자동 재시도', error.auto_retry ?? '—', false],
          ['대체 출처', error.fallback ?? '—', false],
        ]

  return (
    <section aria-label="오류 상세">
      <div>
        <SectionTitle>오류 정보</SectionTitle>
        {rows.length === 0 && (
          <p className="text-[13px] text-muted-foreground">
            이 실행에는 오류 분류 기록이 없습니다 — 아래 실패 지점으로 확인합니다
          </p>
        )}
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
              <span className="sr-only">실패</span> {stageLabel(error.failure_stage)}
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

      <TriageFooter detail={detail} canRun={canRun} onResolve={onResolve} />
    </section>
  )
}
