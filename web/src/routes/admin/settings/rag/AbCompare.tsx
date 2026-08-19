/** AD-007 ③ 초안 평가 : A/B 검색 비교 + ④ 정량 비교 결과.
 *
 * A = 현행 운영값 · B = 편집 중인 초안. 별도 비교군이 아니라 '내가 바꾼 값'이 B다(§1.5).
 * 결과를 저장해 두지 않고 그때그때 검색하므로 같은 질문도 점수가 미세하게 다를 수 있다.
 * 게이트 기준·목표값은 CM-DF-004 05절이 정본이라 여기서 고칠 수 없다(§1.6). */
import { useState } from 'react'
import { useSearchParams } from 'react-router'
import { useMutation } from '@tanstack/react-query'
import { BarChart3, FlaskConical } from 'lucide-react'
import { Button, ColorText, DataTable, InfoHint, Loading } from '../../../../components/ui'
import type { Column } from '../../../../components/ui'
import { Input } from '../../../../components/shadcn/input'
import { cn } from '@/lib/utils'
import { Card, SectionError } from '../promptops/common'
import { abSearch } from './api'
import type { AbColumn, AbHit, ParamValue, RagGate } from './api'

const HIT_COLUMNS: Column<AbHit>[] = [
  { key: 'rank', header: '순위', render: (h) => h.rank, width: '14%' },
  {
    key: 'doc',
    header: '문서',
    render: (h) =>
      h.is_answer ? (
        // 정답 포함 여부는 색이 아니라 ✓ 기호와 함께 알린다(CM-DF-004 09절)
        <ColorText tone="green">
          <strong>
            ✓ {h.title} ({h.doc_id})
          </strong>
        </ColorText>
      ) : (
        <span>
          {h.title} ({h.doc_id})
        </span>
      ),
  },
  { key: 'score', header: '점수', render: (h) => h.score.toFixed(2), align: 'right', width: '18%' },
]

/** `(−0.015)` — 증감은 부호를 글자로 남긴다 */
function delta(a: number, b: number): string {
  const diff = b - a
  const sign = diff < 0 ? '−' : '+'
  return `(${sign}${Math.abs(diff).toFixed(3)})`
}

function ResultColumn({ column, highlight }: { column: AbColumn; highlight: boolean }) {
  return (
    <div
      className={cn(
        // 색면으로 A·B를 가르지 않는다 — 현행은 인셋 회색, 초안은 지면색. 구획은 헤어라인
        'min-w-0 rounded-md border p-3',
        highlight ? 'bg-card' : 'bg-muted/40',
      )}
    >
      <h4 className={cn('mb-2 text-sm font-semibold', !highlight && 'text-muted-foreground')}>
        {column.label}
      </h4>
      <ul className="mb-2 flex flex-wrap gap-1.5">
        {column.chips.map((chip) => (
          <li
            key={chip}
            className={cn(
              'rounded-[3px] border px-1.5 py-0.5 text-[11px] text-muted-foreground',
              // B에서 바뀐 칩만 주황 강조 (§1.5)
              column.changed_chips.includes(chip) && 'border-warning/35 font-semibold text-warning',
            )}
          >
            {chip}
            {column.changed_chips.includes(chip) && <span className="sr-only"> 변경됨</span>}
          </li>
        ))}
      </ul>
      <DataTable
        caption={`${column.label} 검색 상위 ${column.hits.length}건`}
        columns={HIT_COLUMNS}
        rows={column.hits}
        rowKey={(h) => `${column.label}-${h.doc_id}`}
      />
    </div>
  )
}

export interface AbCompareProps {
  draft: Record<string, ParamValue>
  gate: RagGate
  /** [초안 평가] 실행 중 — 버튼은 상태 바가 갖는다(§1.2 우측 버튼 3개) */
  evaluating: boolean
  /** 평가 실패. 화면 안에 남긴다(문구는 서버 user_message) */
  evaluateError: unknown
}

export function AbCompare({ draft, gate, evaluating, evaluateError }: AbCompareProps) {
  // ?q= 프리필 — 대화 로그 [검색 설정 비교하기]가 그 질문을 들고 온다(바통). 관리자가 실험 질의를 지어내지 않는다
  const [searchParams] = useSearchParams()
  const [query, setQuery] = useState(searchParams.get('q') ?? '')
  const search = useMutation({ mutationFn: () => abSearch(query, draft) })
  const quant = gate.quantitative

  return (
    <Card
      // 단계 번호는 상태 바 ⓘ가 이미 말한다. 기획서도 이 카드를 ②(§1.5 제목)와 ③(레이아웃 마커)
      // 두 가지로 세고 있어 번호를 붙일수록 어긋난다 — AD-008 대응 카드와 같은 무번호 형식으로 맞춘다
      title="초안 평가 : A/B 검색 비교"
      icon={<FlaskConical />}
      wide
      // A·B가 무엇인지는 아래 결과 열 머리('A. 현행 운영값' / 'B. 초안')가 이미 말한다.
      // 남는 건 한 번 알면 되는 범위·성격 설명뿐이라 제목 옆으로 접는다
      hint={
        <>
          A = 현행 운영값, B = 편집 중인 초안입니다. 같은 질문을 두 설정으로 동시에 검색해 비교합니다.
          검색·생성 설정 전용이며, 적재 설정 평가는 [재적재로 반영] 작업 안에서 새 인덱스로 수행합니다.
          결과를 캐시하지 않고 매번 실제로 검색하므로 같은 질의도 점수가 조금씩 다를 수 있습니다.
        </>
      }
    >

      <div className="mb-3 flex flex-wrap items-center gap-2.5">
        <label className="sr-only" htmlFor="ab-query">
          비교할 질의
        </label>
        <Input
          id="ab-query"
          type="search"
          className="h-9 min-w-0 flex-1 basis-80"
          value={query}
          placeholder="착오송금 수수료 얼마인가요?"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && query.trim()) search.mutate()
          }}
        />
        <Button
          variant="primary"
          loading={search.isPending}
          disabled={!query.trim()}
          disabledReason={!query.trim() ? '비교할 질의를 입력해 주세요' : undefined}
          onClick={() => search.mutate()}
        >
          비교 실행
        </Button>
      </div>

      {search.isPending && <Loading text="두 설정으로 검색하는 중…" />}

      <SectionError error={search.error} onRetry={() => search.mutate()} />

      {search.data && (
        <div className="grid grid-cols-2 gap-4">
          <ResultColumn column={search.data.a} highlight={false} />
          <ResultColumn column={search.data.b} highlight />
        </div>
      )}

      {/* ---------------- ④ 정량 비교 결과 ---------------- */}
      <div className="mt-4 border-t pt-3">
        <h3 className="mb-1.5 inline-flex items-center gap-1.5 text-sm font-semibold">
          <BarChart3 className="size-4 text-muted-foreground" aria-hidden="true" />
          정량 비교 결과
          {/* 모수를 왜 그렇게 잡았는지는 계산 근거다 — 지표 줄 위에 깔아 두면 정작 봐야 할
              'A → B (+0.0xx)'와 게이트 판정이 밀린다. 소제목 옆으로 접는다 */}
          {quant && <InfoHint label="정량 비교 기준 설명" size="sm">{quant.basis}</InfoHint>}
        </h3>
        {evaluating && <Loading text="홀드아웃 문항을 평가하는 중…" detail="평가에는 시간이 걸립니다" />}
        <SectionError error={evaluateError} />
        {!evaluating && !quant && (
          <p className="text-sm text-muted-foreground">
            아직 초안 평가를 실행하지 않았습니다. [초안 평가]를 눌러 현행과 비교해 주세요
          </p>
        )}
        {quant && (
          <>
            <p className="flex flex-wrap gap-x-5 gap-y-1.5">
              {quant.metrics.map((m) => (
                <span key={m.label} className="text-sm text-foreground tabular-nums">
                  {m.label} A {m.a.toFixed(3)} → B {m.b.toFixed(3)} {delta(m.a, m.b)}
                </span>
              ))}
              <span className="text-sm text-foreground tabular-nums">
                개선 {quant.improved}문항 · 악화 {quant.regressed}문항
              </span>
              <ColorText tone="orange">
                <strong>{quant.recommendation}</strong>
              </ColorText>
            </p>
            {/* 게이트 결과는 색이 아니라 글자로도 남긴다 */}
            <p className="mt-2 text-sm">
              게이트 : 홀드아웃 {gate.holdout_passed}/{gate.holdout_total} · Smoke {gate.smoke_passed}/
              {gate.smoke_total} ·{' '}
              {gate.passed ? (
                <ColorText tone="green">통과 ✓</ColorText>
              ) : (
                <ColorText tone="red">미달 ✗</ColorText>
              )}
            </p>
          </>
        )}
      </div>
    </Card>
  )
}
