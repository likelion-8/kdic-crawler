/** 챗봇 답변 말풍선 — CB-DF-003 01절 '답변 하단 섹션 노출 매트릭스'가 이 파일의 정본.
 *
 * 렌더 순서(CB-DF-004 5-2 고정): 답변 본문 → 필요 서류 → 신청 페이지 → 참고 출처 → 피드백 → AI 고지.
 * 이 중 AI 고지만 말풍선 바깥이다(CB-002 마커 3 "본문 + 참고 출처 + 피드백을 한 말풍선 안에").
 * 분기는 response_type이 아니라 필드 존재 검사로 한다 — 빈 배열이면 헤딩까지 통째로 미렌더가 규칙이고,
 * 빈 상태 문구("등록된 서류가 없습니다" 등)를 넣는 것은 금지다(CB-DF-004 §6).
 *
 * 답변 Type 6(복합 질문 분해, CB-DF-002 Type 6)은 `subAnswers`로 그린다. 하위마다 검색·근거가
 * 독립이라 출처도 하위에 붙는다 — 이때 최상위 sources·attachments는 빈 배열로 온다.
 * 제목을 answer 안 `**…**` 마크다운으로 받는 방식은 "마크다운 파싱 불필요"(CB-DF-002) 규칙과
 * 충돌해 쓰지 않는다. */
import { useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import type { Attachment, Source, SubAnswer } from '../../lib/api/types'
import { Bubble, BubbleText } from './Bubble'
import { ApplyCta, SourceCard } from './SourceCard'
import { useTypewriter } from './useTypewriter'

export interface AnswerMessageProps {
  answer: string
  /** 보낸/받은 시각 — 없으면 시각을 그리지 않는다 */
  at?: string | number
  sources?: Source[]
  attachments?: Attachment[]
  /** 복합 질문의 하위 답변. 비어 있지 않으면 본문 대신 하위 묶음으로 그린다 */
  subAnswers?: SubAnswer[]
  /** 근거 미사용 판정 — 출처·서류·신청 페이지 섹션을 전부 그리지 않는다 (CB-DF-001 2-5) */
  outOfScope?: boolean
  /** 스트리밍 중이면 커서 표시, 섹션은 아직 그리지 않는다 */
  streaming?: boolean
  /** 피드백 행 — 본문·참고 출처와 같은 말풍선 **안**에 들어간다 (CB-002 마커 3/마커 8).
   * 말풍선 바깥 아래는 AI 고지 전용이다 (CB-002 마커 96,428). */
  feedback?: ReactNode
}

/** 모든 답변 하단에 상시 노출 (CB-002 마커 8). ⓘ로 시작하는 회색 문구 = 구현 대상(00-meta NOTATION) */
const AI_NOTICE = 'ⓘ AI가 생성한 답변입니다 · 금액·기한 등 중요한 사항은 출처 원문에서 꼭 확인해 주세요'

/** 자기보고 마커는 BE가 스트리밍 전에 떼는 것이 계약이다(CM-DF-003 06절).
 * 새면 사용자에게 `[NO_SOURCE]`가 그대로 보이므로 렌더 시 1회만 방어한다 — 버퍼링은 하지 않는다. */
function stripMarker(text: string): string {
  return text.replace(/^\[(SOURCE[_ ]USED|NO[_ ]SOURCE)\]\s*/i, '')
}

/** 섹션 헤딩 — 라벨마다 아이콘을 붙이지 않는다. 위계는 굵기와 여백이 진다 */
const HEADING = 'mb-2 text-[13px] font-bold'
const LIST = 'flex flex-col gap-2'

/** 근거 섹션 3종을 순서 고정으로 만든다 (필요 서류 → 신청 페이지 → 참고 출처, CB-DF-004 5-2).
 * 단일 질문은 최상위 배열로, 복합 질문은 하위 답변마다 한 번씩 부른다 — 그리는 규칙이 같아서다.
 * 빈 배열이면 헤딩째 그리지 않는다(빈 상태 문구 금지, CB-DF-004 §6). */
function sections(sources: Source[], attachments: Attachment[], prefix: string): ReactNode[] {
  const documents = attachments.filter((a) => a.kind === 'document')
  const links = attachments.filter((a) => a.kind === 'link')
  const out: ReactNode[] = []
  if (documents.length > 0) {
    out.push(
      <section className="reveal mt-4" key={`${prefix}-documents`}>
        <h3 className={HEADING}>필요 서류</h3>
        <ol className={LIST}>
          {documents.map((d) => (
            <li key={`${d.url}-${d.label}`}>
              {/* 부제는 목업 원문 고정 — 서식 직링크가 POST 전용이라 페이지로 보낸다(CB-003 마커 2) */}
              <SourceCard title={d.label} subtitle="서식 다운로드 페이지로 이동" url={d.url} />
            </li>
          ))}
        </ol>
      </section>,
    )
  }
  if (links.length > 0) {
    out.push(
      <section className="reveal mt-4" key={`${prefix}-links`}>
        <h3 className={HEADING}>신청 페이지</h3>
        {links.map((l) => (
          <ApplyCta key={`${l.url}-${l.label}`} label={l.label} url={l.url} />
        ))}
      </section>,
    )
  }
  if (sources.length > 0) {
    out.push(
      <section className="reveal mt-4" key={`${prefix}-sources`}>
        <h3 className={HEADING}>참고 출처</h3>
        {/* 중복 제거·정렬은 서버가 끝낸 상태로 온다 — 복합 질문은 하위별 중복 제거 금지라
            프론트가 손대면 규칙이 반대로 뒤집힌다(CB-DF-002 Type 6) */}
        <ol className={LIST}>
          {sources.map((s, i) => (
            <li key={`${s.page_id}-${i}`}>
              <SourceCard title={s.title} subtitle={s.breadcrumb} url={s.url} />
            </li>
          ))}
        </ol>
      </section>,
    )
  }
  return out
}

/** 하단 블록을 한 박자씩 **붙여 나간다**.
 *
 * CSS 지연(animation-delay)으로 하면 자리는 처음부터 잡히고 내용만 늦게 떠서, 답변이 끝나는 순간
 * 말풍선이 먼저 커지고 그 안이 잠시 비어 보인다(실측: 빈 구간 최대 0.7초 · 사용자 지적).
 * 마운트 자체를 늦추면 높이가 내용과 함께 자라 빈 칸이 생기지 않는다.
 *
 * SSR(selfcheck·정적 렌더)에서는 effect가 돌지 않으므로 처음부터 전부 보여 준다 —
 * 안 그러면 '참고 출처가 렌더된다'는 검사가 마운트 타이밍 때문에 실패한다. */
function useStagger(total: number, stepMs = 70): number {
  const [shown, setShown] = useState(() => (typeof window === 'undefined' ? Number.MAX_SAFE_INTEGER : 0))
  useEffect(() => {
    if (shown >= total) return
    const timer = setTimeout(() => setShown((n) => n + 1), shown === 0 ? 0 : stepMs)
    return () => clearTimeout(timer)
  }, [shown, total])
  return shown
}

export function AnswerMessage({
  answer,
  at,
  sources = [],
  attachments = [],
  subAnswers = [],
  outOfScope = false,
  streaming = false,
  feedback,
}: AnswerMessageProps) {
  // 서버가 몇 자씩 끊어 보내든 화면에는 고른 속도로 흘린다(끊김 방지).
  // 스트리밍이 끝나도 남은 글자를 마저 흘리고, 다 흘린 뒤(typed.done)에 하단 섹션을 연다.
  const typed = useTypewriter(stripMarker(answer), streaming)
  // 스트리밍 중에는 부착 영역을 그리지 않는다 — 나중에 걷어내면 깜빡임이 생긴다(CB-DF-004 §7 I-10)
  const showSections = typed.done && !outOfScope
  // 복합 질문은 본문을 하위 묶음으로 대체한다. 스트리밍 중에는 아직 하위 구조를 모르므로
  // 평문으로 흘리다가 done에서 한 번 바뀐다 — 섹션이 열리는 것과 같은 시점이라 튀지 않는다
  const composite = typed.done && subAnswers.length > 0

  // 하단 블록 — 순서 고정(필요 서류 → 신청 페이지 → 참고 출처 → AI 고지, CB-DF-004 5-2)
  const blocks: ReactNode[] = []
  if (showSections && !composite) blocks.push(...sections(sources, attachments, 'top'))
  // AI 고지는 말풍선 **안** 맨 아래다(CB-002 마커 8) — 답변과 같은 지면에 있어야
  // '이 답변에 대한 고지'로 읽힌다. 밖에 두면 다음 말풍선의 머리말처럼 보인다.
  // 스트리밍 중에는 그리지 않는다 — 아직 답변이 아니다
  if (typed.done) {
    blocks.push(
      <p
        data-slot="ai-notice"
        className="reveal mt-4 border-t pt-3 text-xs leading-relaxed text-muted-foreground"
        key="notice"
      >
        {AI_NOTICE}
      </p>,
    )
  }
  const shown = useStagger(blocks.length)

  return (
    <Bubble
      variant="bot"
      // 스트리밍 중에는 시각을 감춘다 — 다 받기도 전에 '받은 시각'을 찍을 수 없다
      at={typed.done ? at : undefined}
      // 말풍선 아래 왼쪽 자리는 피드백이 쓴다 — 오른쪽 시각과 한 줄로 마주 본다
      footer={feedback}
    >
      {/* 스트리밍으로 갱신되는 영역 — 스크린리더가 갱신을 읽도록 한다.
          단 델타마다 문단 전체가 교체되므로 스트리밍 중에는 aria-busy로 고지를 보류시키고,
          done 시점(busy=false)에 완성 본문을 한 번만 읽게 한다. 대화 목록 <ol>에는 live 영역을
          두지 않는다 — 중첩되면 같은 답변이 두 번 읽힌다(CB-DF-004 §7 I-17). */}
      <div aria-live="polite" aria-busy={streaming}>
        {composite ? (
          // 하위 질문마다 제목 → 답변 → 그 하위의 근거. 최상위 sources는 규약상 비어 있다
          subAnswers.map((sub, i) => (
            <section className={i === 0 ? undefined : 'mt-5 border-t pt-4'} key={`${sub.title}-${i}`}>
              <h3 className="mb-2 text-sm font-bold">{sub.title}</h3>
              <BubbleText text={stripMarker(sub.answer)} />
              {showSections && sections(sub.sources, sub.attachments, `sub${i}`)}
            </section>
          ))
        ) : (
          /* 커서는 BubbleText가 마지막 문단 안에 그린다 — 글 끝을 따라다녀야 한다.
             스트리밍이 끝나도 아직 흘릴 글자가 남아 있으면 커서를 유지한다 */
          <BubbleText text={typed.text} caret={!typed.done} />
        )}
      </div>

      {/* 블록을 배열로 모아 마운트 순서를 제어한다 — 조건에 따라 개수가 달라지므로
          '몇 번째'가 아니라 '앞에서 몇 개까지'로 센다 */}
      {blocks.slice(0, shown)}
    </Bubble>
  )
}
