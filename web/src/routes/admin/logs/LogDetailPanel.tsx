/** AD-005 [2][3][4] — 우측 상세 패널.
 * 정상·범위 외 행 → 단계별 처리 추적(구획 5개) · 실패 행 → 오류 상세 (Desc 2 마지막 불렛).
 * 표시되는 질문·답변·의견은 전부 마스킹된 저장본이다. 원문 복호화 진입점은 두지 않는다(Desc 2). */
import { useState } from 'react'
import type { ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { Button, InfoHint } from '../../../components/ui'
import { Separator } from '@/components/shadcn/separator'
import { INTENT_LABEL, QUESTION_TYPE_LABEL } from '../../../lib/codes'
import {
  FEEDBACK_LABEL,
  LOG_STATUS_LABEL,
  formatMonthDayTime,
} from './api'
import type {
  AnswerComposition,
  ConversationLogDetail,
  LangfuseTrace,
  ObservedSub,
  RunObservation,
  ServedFrom,
} from './api'
import { formatTime } from '../../../lib/format'
import { QUERY_CACHE_TTL_H } from '../../../lib/constants'

export interface LogDetailPanelProps {
  detail: ConversationLogDetail
  /** OPERATOR 이상 — 처리 완료 · 되돌리기 */
  canRun: boolean
  onResolve: () => void
  onReopen: () => void
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

/** 근거가 빈 하위 질문 한 줄 설명. '검색이 아무것도 못 찾음(지식베이스 공백 후보)'과
 *  'Gate3가 관련도 낮다고 판정해 스스로 멈춤(질문 표현 문제일 수도 있음)'은 관리자가 다음에
 *  할 일이 다르다(전자는 AD-002 지식베이스 점검, 후자는 질문 표현·임계값 점검) — 뭉뚱그려
 *  "지식베이스 점검 대상"이라 하면 후자를 잘못된 곳으로 보낸다(2026-08-25 Gate3 도입 때 발견). */
function EmptyEvidenceNote({ sub }: { sub: ObservedSub }) {
  if (sub.exit_at === 'gate3' && sub.gate3_reason === 'low_retrieval_relevance') {
    const score = sub.retrieval_top1_score?.toFixed(3) ?? '—'
    const threshold = sub.retrieval_threshold?.toFixed(2) ?? '—'
    return (
      <p className="text-muted-foreground">
        검색은 됐지만 관련도가 낮아(top-1 {score} ≤ 임계값 {threshold}) Gate3가 생성 전에
        멈췄습니다 — 지식베이스 공백일 수도, 질문 표현 문제일 수도 있습니다
      </p>
    )
  }
  // gate3 + no_candidates, 또는 gate3 이전 대화(무관질문 게이트가 근거를 비운 경우)는
  // 검색이 문자 그대로 후보를 하나도 못 찾은 것이라 종전 문구가 그대로 맞다.
  return <p className="text-muted-foreground">검색된 근거 없음 — 지식베이스(AD-002) 점검 대상</p>
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
      <h4 className="mb-2 text-xs font-semibold text-muted-foreground">근거</h4>
      <ul className="space-y-3">
        {observation.subs.map((sub, i) => (
          <li key={i} className="text-[13px]">
            {observation.subs.length > 1 && (
              <p className="mb-1 font-medium">{sub.question}</p>
            )}
            {sub.top.length === 0 ? (
              <EmptyEvidenceNote sub={sub} />
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
          </li>
        ))}
      </ul>
    </div>
  )
}

/** 출처 카드 목록 — 챗봇의 '참고 출처'와 같은 것을 관리자 화면 밀도로 줄여 그린다 */
function SourceList({ items }: { items: AnswerComposition['sources'] }) {
  if (items.length === 0) return null
  return (
    <div className="mt-2">
      <p className="text-xs font-medium text-muted-foreground">참고 출처 {items.length}건</p>
      <ul className="mt-1 space-y-1">
        {items.map((src) => (
          <li key={src.page_id} className="text-[13px] leading-snug">
            <span className="text-muted-foreground">{src.breadcrumb} · </span>
            <a className="text-primary hover:underline" href={src.url} target="_blank" rel="noreferrer">
              {src.title}
              <span className="sr-only">새 창에서 열림</span>
            </a>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** 필요 서류(document)와 신청 페이지(link) — 챗봇이 본문 뒤에 붙이는 두 섹션 그대로다 */
function AttachmentList({ items }: { items: AnswerComposition['attachments'] }) {
  const docs = items.filter((a) => a.kind === 'document')
  const links = items.filter((a) => a.kind === 'link')
  return (
    <>
      {[
        { title: '필요 서류', rows: docs },
        { title: '신청 페이지', rows: links },
      ].map(({ title, rows }) =>
        // 값이 비면 섹션 자체를 그리지 않는다 — 챗봇과 같은 규칙(CB-DF-003)
        rows.length === 0 ? null : (
          <div key={title} className="mt-2">
            <p className="text-xs font-medium text-muted-foreground">
              {title} {rows.length}건
            </p>
            <ul className="mt-1 space-y-1">
              {rows.map((a) => (
                <li key={a.url} className="text-[13px] leading-snug">
                  <a className="text-primary hover:underline" href={a.url} target="_blank" rel="noreferrer">
                    {a.label}
                    <span className="sr-only">새 창에서 열림</span>
                  </a>
                </li>
              ))}
            </ul>
          </div>
        ),
      )}
    </>
  )
}

/**
 * 답변 구성 — 사용자가 챗봇에서 실제로 본 그대로.
 *
 * 종전에는 본문 텍스트 하나만 보여줘서, 민원이 "링크가 틀렸다"·"서류가 빠졌다"일 때 관리자가
 * 확인할 방법이 없었다(본문에는 URL 이 없다 — 출처·서류는 시스템이 본문 뒤에 따로 붙인다).
 * 복합 질문이면 하위 답변마다 근거가 따로 붙으므로 하위 단위로 나눠 그린다.
 */
function AnswerCompositionView({ comp }: { comp: AnswerComposition }) {
  if (comp.sub_answers.length > 0) {
    return (
      <ol className="mt-3 space-y-3">
        {comp.sub_answers.map((sub, i) => (
          <li key={i} className="rounded-md border border-border p-3">
            <p className="text-[13px] font-semibold">{sub.title}</p>
            <p className="mt-1 text-[13px] leading-relaxed whitespace-pre-line">{sub.answer}</p>
            <AttachmentList items={sub.attachments} />
            <SourceList items={sub.sources} />
          </li>
        ))}
      </ol>
    )
  }
  return (
    <>
      <AttachmentList items={comp.attachments} />
      <SourceList items={comp.sources} />
    </>
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

/** 답변을 낸 경로 6종. gate3만 검색은 실제로 돌고 생성만 건너뛴다 — 나머지 다섯은 검색·생성
 *  둘 다 안 타 성격·유형·근거가 없다(분류가 비는 이유). */
const SERVED_FROM_LABEL: Record<ServedFrom, string> = {
  cache: '캐시 응답',
  guardrail: '가드레일 차단',
  gate1: '범위 판정 (Gate 1)',
  gate2: '범위 판정 (Gate 2)',
  gate3: '검색 관련도 판정 (Gate 3)',
  clarify: '업무 되묻기',
}

/** 왜 그 경로로 끝났는지 한 줄. 관리자가 '검색이 안 됐나'로 잘못 읽지 않게 한다 */
const SERVED_FROM_NOTE: Record<ServedFrom, string> = {
  cache: `저장해 둔 답변을 그대로 돌려준 건입니다 — 검색·생성을 거치지 않아 근거가 남지 않습니다. 캐시는 ${QUERY_CACHE_TTL_H}시간 보관되며 운영 정책(AD-009)에서 비웁니다`,
  guardrail: '게시된 금칙어(AD-008)에 걸려 고정 문구로 거절한 건입니다 — 검색·생성을 거치지 않습니다',
  gate1: '규칙 필터가 인사·노이즈·타 분야로 판정해 고정 문구로 답한 건입니다 — LLM을 부르지 않습니다',
  gate2: '임베딩 유사도 판정이 안내 범위 밖으로 보고 고정 문구로 답한 건입니다 — LLM을 부르지 않습니다',
  gate3: '검색은 했지만 최상위 결과의 관련도가 임계값 이하라 생성 전에 멈춘 건입니다 — 아래 근거 항목에 실제 점수가 남습니다',
  clarify: '어느 업무에 대한 질문인지 정해지지 않아 업무 선택지로 되물은 건입니다 — 검색·생성을 거치지 않아 근거가 없습니다. 사용자가 업무를 고르면 그 답변은 다음 행에 남습니다',
}

/** Gate 1 규칙 이름. 모르는 값은 지어내지 않고 원본 식별자를 그대로 보여준다(STAGE_LABEL 과 같은 규약) */
const GATE1_RULE_LABEL: Record<string, string> = {
  FIXED_GREETING: '인사',
  FIXED_THANKS: '감사',
  FIXED_NOISE: '노이즈',
  FIXED_BOT_INTRO: '정체성 질문',
  FIXED_BOT_HELP: '도움말 요청',
  SECURITY_BLOCK: '보안 우회 시도',
  CAPABILITY_UNAVAILABLE: '미지원 기능',
  OUT_OF_DOMAIN_RULE: '타 분야',
}

/** 경로만('범위 판정 (Gate 1)')과 규칙까지('… · 인사') 두 벌. 세 줄이 같은 문구를 되풀이하지
 *  않도록 분류 줄만 규칙을 달고, 처리 추적은 경로만 적는다 */
function servedPath(detail: ConversationLogDetail): string | null {
  return detail.served_from === null ? null : SERVED_FROM_LABEL[detail.served_from]
}

function servedPathWithRule(detail: ConversationLogDetail): string | null {
  const path = servedPath(detail)
  if (path === null) return null
  const rule = detail.served_label
  return path + (rule ? ` · ${GATE1_RULE_LABEL[rule] ?? rule}` : '')
}

/** rag_runs.failure_stage 는 파이프라인 내부 식별자다 — 화면에는 사람이 읽는 단계명으로 적는다.
 *  모르는 값은 지어내지 않고 원본을 그대로 보여준다(단계가 늘어나도 화면이 거짓말하지 않는다). */
const STAGE_LABEL: Record<string, string> = {
  retrieval: '검색',
  llm: '답변 생성',
}
const stageLabel = (stage: string | null) =>
  stage === null ? '확인할 수 없음' : (STAGE_LABEL[stage] ?? stage)

/** 처리 상태 꼬리 — 미처리면 [처리 완료 표시], 처리했으면 그때 남긴 조치 사유와 되돌리기.
 *
 * 사유는 활동 로그(AD-011)에도 쌓이지만 거기까지 찾아가야 보였다. 조치를 한 화면에서
 * 바로 읽히는 게 맞다. 정상 건과 실패 건이 같은 꼬리를 쓴다.
 * 되돌리기가 없으면 잘못 누른 완료를 풀 길이 없어 대시보드 할 일 건수가 거짓이 된다. */
function TriageFooter({ detail, canRun, onResolve, onReopen }: LogDetailPanelProps) {
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
        {canRun && (
          <Button className="mt-3" size="sm" variant="secondary" onClick={onReopen}>
            처리 완료 취소
          </Button>
        )}
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
function TracePanel({ detail, canRun, onResolve, onReopen }: LogDetailPanelProps) {
  const [expanded, setExpanded] = useState(false)
  const { classification: c } = detail
  const served = servedPathWithRule(detail)
  const path = servedPath(detail)
  const subs = detail.observation?.subs ?? []
  // 하위 질문마다 판정이 갈릴 수 있다. 최상위 source_used 는 그 OR 이라(observation.summarize)
  // 복합 질문에서 '사용'만 적으면 안 쓴 하위가 가려진다 — 갈리면 '일부 사용'으로 적는다.
  const usedFlags = subs.map((s) => s.used_source).filter((v): v is boolean => v !== null)
  const usedCount = usedFlags.filter(Boolean).length
  const mixedUse = usedFlags.length > 1 && usedCount > 0 && usedCount < usedFlags.length
  // 답변 구성 기준의 복합 여부 — 관측(subs)이 아니라 실제로 하위 답변이 저장됐는지를 본다.
  // 관측은 있는데 하위 답변이 없는 건(대화 저장 이전)에서 본문을 잃지 않기 위해서다.
  const composite = (detail.answer_composition?.sub_answers.length ?? 0) > 0
  // 분류로 읽히는 값 전부. 복합 질문은 성격·업무와 같은 줄에 선다 — 종전에는 하위가 몇 개로
  // 나뉘었는지가 분류 어디에도 없어, 근거 구획을 펼쳐 보고서야 복합인 줄 알 수 있었다.
  const labels = [
    c.intent === null ? null : INTENT_LABEL[c.intent],
    c.business_function,
    c.question_type === null ? null : QUESTION_TYPE_LABEL[c.question_type],
    subs.length > 1 ? `복합 질문 ${subs.length}개` : null,
  ].filter(Boolean)
  return (
    // 질문·시각·요청 ID는 DetailModal 헤더가 그린다 — 여기서 두 번 쓰지 않는다
    <section aria-label="처리 과정">
      <div>
        <SectionTitle>
          분류
          <InfoHint label="분류 값 설명" size="sm">
            성격은 정보성 / 민원성 2값(쿼리 플래너 판정)입니다. 업무는 분류기가 코드에서 꺼져 있어
            저장되지 않고, 유형도 웹 경로에는 원천이 없습니다. 하위 질문이 둘 이상으로 나뉘면 「복합
            질문 N개」가 함께 섭니다. 검색·생성을 타지 않고 끝난 건은 성격이 저장되지 않아, 대신 그
            경로(캐시 응답 · 가드레일 차단 · 범위 판정 Gate 1·2·3 · 업무 되묻기)를 적습니다.
          </InfoHint>
        </SectionTitle>
        {/* 값이 있는 것만 이어 붙인다 — 성격·유형이 null 인 건에서 구분점만 남으면 '·' 한 글자가
            찍힌다. 하나도 없으면 **어느 경로로 끝나 분류가 없는지**를 그 자리에 적는다 */}
        <p className="text-[13px]">{labels.join(' · ') || served || '분류 기록 없음'}</p>
        <p className="mt-1.5 grid grid-cols-[120px_1fr] gap-2.5 text-[13px]">
          <span className="text-muted-foreground">출처 판정</span>
          <span>
            {/* 백엔드가 원천 부재로 null 을 내린다(admin_logs.py) — '미사용' 단정은 거짓이 된다 */}
            {c.source_used === null
              ? '판정 원천 없음'
              : mixedUse
                ? `일부 사용 (하위 ${usedFlags.length}개 중 ${usedCount}개)`
                : c.source_used
                  ? '사용'
                  : '미사용'}
            {/* 서버가 이미 '[SOURCE_USED]' 형태로 내려준다 — 여기서 또 감싸면 [[…]] 가 된다 */}
            {c.marker === null ? '' : ` · 마커 ${c.marker}`}
          </span>
        </p>
        {/* 사후검증이 환각·동문서답을 잡아 본문을 표준 안내로 갈아끼운 건 */}
        {c.normalized && <p className="mt-1.5 text-xs text-muted-foreground">본문 교체</p>}
        {/* 근거는 출처 판정의 하위다 — 무엇을 근거로 삼았고 그래서 썼는지/안 썼는지가 한 덩어리다.
            들여쓰기와 왼쪽 선으로 종속을 보인다(별도 구획으로 떼면 두 판정이 남남처럼 읽힌다) */}
        {detail.observation && (
          <div className="mt-3 border-l-2 border-border pl-3">
            <EvidencePanel observation={detail.observation} />
          </div>
        )}
      </div>

      {detail.observation && (
        <>
          <Separator className="my-4" />
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
          {/* 이 경로들은 총 소요가 1초대로 뚝 떨어지고 근거 구획이 통째로 비는데, 그 이유가
              화면 어디에도 없었다 — 관리자가 '검색이 안 됐나'로 잘못 읽는다(2026-08-20) */}
          {path !== null && ` · ${path}`}
        </p>
        {/* ⓘ로 접지 않는다 — 이 패널은 네이티브 <dialog showModal()> 안이라 body로 포털되는
            팝오버가 top layer 아래에 깔려 아예 안 보인다(2026-08-20 실측). 한 줄로 편다 */}
        {detail.served_from !== null && (
          <p className="mt-1 text-xs text-muted-foreground">
            {SERVED_FROM_NOTE[detail.served_from]}
          </p>
        )}
        <TraceLink trace={detail.langfuse} />
      </div>

      <Separator className="my-4" />

      <div>
        <SectionTitle>
          답변 전문 (마스킹)
          <InfoHint label="답변 전문 설명" size="sm">
            사용자가 챗봇에서 본 것과 같은 구성입니다 — 본문 뒤에 필요 서류 · 신청 페이지 · 참고
            출처가 순서대로 붙습니다. 값이 없는 섹션은 그리지 않습니다. 복합 질문은 하위 답변이
            곧 본문이라 하위 단위로만 그립니다. 본문·하위 답변은 마스킹된 저장본이며 원문 복원
            진입점은 없습니다.
          </InfoHint>
        </SectionTitle>
        {/* 복합 질문의 rag_runs.answer 는 하위 답변을 이어붙인 것이다 — 그 본문을 그리고 하위
            카드를 또 그리면 같은 글이 두 번 나온다. 하위가 있으면 하위만 그린다(챗봇도 그렇다) */}
        {composite ? (
          <AnswerCompositionView comp={detail.answer_composition!} />
        ) : (
          <>
            <p className="text-[13px] leading-relaxed whitespace-pre-line">
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
            {/* 서버가 구성을 안 내려주는 배포에서는 undefined — 그때는 본문만 그리고 없는 것을
                지어내지 않는다(원천은 chat_messages, api.ts AnswerComposition 주석 참고) */}
            {detail.answer_composition && (
              <AnswerCompositionView comp={detail.answer_composition} />
            )}
          </>
        )}
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
      <TriageFooter detail={detail} canRun={canRun} onResolve={onResolve} onReopen={onReopen} />
    </section>
  )
}


/** [4] 실패 건(붉은 행) 선택 시 : 오류 상세 패널 */
function ErrorPanel({ detail, canRun, onResolve, onReopen }: LogDetailPanelProps) {
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

      <TriageFooter detail={detail} canRun={canRun} onResolve={onResolve} onReopen={onReopen} />
    </section>
  )
}
