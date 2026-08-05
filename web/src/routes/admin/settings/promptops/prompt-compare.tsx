/** AD-008 ④ 초안 평가 : 전후 답변 비교 + 회귀 게이트.
 * 기획서 12절 §2.7. 전후 비교는 요약·텍스트 diff가 아니라 '사용자가 보게 될 모습'이라
 * 챗봇 답변 컴포넌트(components/chat)를 그대로 재사용한다(Description 4). */
import { useState } from 'react'
import { GitCompareArrows } from 'lucide-react'
import { AnswerMessage } from '../../../../components/chat'
import { Badge, ColorText, EmptyState, Loading, Toggle } from '../../../../components/ui'
import { cn } from '@/lib/utils'
import { Card, SectionError, linkClass } from './common'
import type { EvalVerdict, PromptEvaluation } from './api'

/** 판정 표기 — Description 4 "유지 ✓ / 개선 △ / 회귀 ✗" 원문 */
const VERDICT: Record<EvalVerdict, { label: string; tone: 'green' | 'orange' | 'red' }> = {
  KEEP: { label: '✓ 유지', tone: 'green' },
  IMPROVED: { label: '△ 개선', tone: 'orange' },
  REGRESSED: { label: '✗ 회귀', tone: 'red' },
}

export interface BeforeAfterCardProps {
  evaluation: PromptEvaluation | null
  baseVersion: string
  running: boolean
  error: unknown
  /** 실패 후 재시도 전용 — 실행 버튼([초안 평가])은 상태 바가 갖는다(§2.2 우측 버튼 3개) */
  onRun: () => void
}

export function BeforeAfterCard({ evaluation, baseVersion, running, error, onRun }: BeforeAfterCardProps) {
  const [changedOnly, setChangedOnly] = useState(true)
  const [open, setOpen] = useState<string[]>([])

  if (!evaluation) {
    return (
      <Card title="초안 평가 : 전후 답변 비교" icon={<GitCompareArrows />} wide>
        {running ? (
          <Loading text="초안 평가를 실행하는 중…" detail="대표 질의 6건의 답변을 생성하는 중…" />
        ) : (
          <EmptyState title="아직 초안 평가를 실행하지 않았습니다. 상태 바의 [초안 평가]로 실행합니다" />
        )}
        <SectionError error={error} onRetry={onRun} />
      </Card>
    )
  }

  const { summary, items, gate } = evaluation
  // 회귀(✗)가 있으면 목록 맨 위로 올린다(Description 4)
  const ordered = [...items].sort((a, b) => Number(b.verdict === 'REGRESSED') - Number(a.verdict === 'REGRESSED'))
  const shown = changedOnly ? ordered.filter((i) => i.verdict !== 'KEEP') : ordered
  const hidden = ordered.length - shown.length

  function toggleRow(id: string) {
    setOpen((list) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]))
  }

  /** 실패(✗) 항목을 누르면 해당 문항이 열린다(§2.7 각주) */
  function openRegressed() {
    setChangedOnly(false)
    setOpen(items.filter((i) => i.verdict === 'REGRESSED').map((i) => i.id))
  }

  return (
    <Card title="초안 평가 : 전후 답변 비교" icon={<GitCompareArrows />} wide>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          대표 질의 {summary.total}건 · 유지 {summary.keep} · 개선 {summary.improved} · 회귀{' '}
          {summary.regressed}
        </p>
        <Toggle label="바뀐 답변만 보기" checked={changedOnly} onChange={setChangedOnly} />
      </div>

      <ul className="m-0 list-none p-0">
        {shown.map((item) => {
          const expanded = open.includes(item.id)
          const verdict = VERDICT[item.verdict]
          return (
            <li
              key={item.id}
              className={cn(
                'border-b py-2.5 last:border-b-0',
                // 회귀 행은 맨 위로 올리고 옅은 붉은 행 배경으로 표시한다(Description 4) — 표 안이라
                // 안내 블록은 과하다. 판정 글자(✗ 회귀)가 이미 색+텍스트를 병기한다
                item.verdict === 'REGRESSED' && 'mt-3 rounded-md bg-danger-soft/70 px-3',
              )}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="m-0 min-w-0 flex-1 text-sm font-medium">{item.question}</p>
                <ColorText tone={verdict.tone}>{verdict.label}</ColorText>
                <button
                  type="button"
                  className={linkClass}
                  aria-expanded={expanded}
                  onClick={() => toggleRow(item.id)}
                >
                  {expanded ? '전후 접기 ▴' : '전후 보기 ▾'}
                </button>
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{item.note}</p>

              {expanded && (
                <div className="mt-2.5 grid grid-cols-2 gap-4">
                  {/* 전후 2열은 색면이 아니라 인셋 배경 + 헤어라인으로 가른다 */}
                  <div className="min-w-0 rounded-md border bg-muted/40 p-3">
                    <p className="mb-2 text-xs font-semibold text-muted-foreground">현행 {baseVersion}</p>
                    <div className="max-h-65 overflow-auto">
                      <AnswerMessage answer={item.before.answer} sources={item.before.sources} />
                    </div>
                  </div>
                  <div className="min-w-0 rounded-md border bg-card p-3">
                    <p className="mb-2 text-xs font-semibold text-foreground">초안 (편집 중)</p>
                    <div className="max-h-65 overflow-auto">
                      <AnswerMessage answer={item.after.answer} sources={item.after.sources} />
                    </div>
                  </div>
                </div>
              )}
            </li>
          )
        })}
      </ul>

      {hidden > 0 && (
        <p className="mt-2 text-xs text-muted-foreground">
          그 외 {hidden}건 모두 유지 · '바뀐 답변만 보기'를 끄면 펼쳐집니다
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-3 border-t pt-3 text-sm">
        <span className="font-semibold">회귀 게이트</span>
        <GateCheck
          passed={gate.source_attached.passed}
          label={`출처 부착 유지 ${gate.source_attached.count}/${gate.source_attached.total}`}
          onOpenFailed={openRegressed}
        />
        <GateCheck
          passed={gate.out_of_scope.passed}
          label={`범위 외 동작 ${gate.out_of_scope.count}/${gate.out_of_scope.total}`}
          onOpenFailed={openRegressed}
        />
        <GateCheck passed={gate.guardrail.passed} label="금칙어·마스킹 통과" onOpenFailed={openRegressed} />
        {/* 게이트 종합 배지 — 색 + 글자를 함께 쓴다(CM-DF-004 09절). 공통 Badge(사각 태그)로 통일 */}
        <Badge tone={gate.passed ? 'green' : 'red'} kind="status">
          {gate.passed ? '통과 · [게시] 활성화' : '미통과 · [게시] 비활성'}
        </Badge>
      </div>

      <SectionError error={error} onRetry={onRun} />
    </Card>
  )
}

interface GateCheckProps {
  passed: boolean
  label: string
  onOpenFailed: () => void
}

function GateCheck({ passed, label, onOpenFailed }: GateCheckProps) {
  if (passed) return <ColorText tone="green">✓ {label}</ColorText>
  return (
    <button
      type="button"
      className={cn(linkClass, 'font-semibold text-danger-fg')}
      onClick={onOpenFailed}
    >
      ✗ {label}
    </button>
  )
}
