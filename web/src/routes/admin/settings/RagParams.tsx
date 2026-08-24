/** AD-007 RAG 파라미터 설정 · A/B 비교 (`KDIC-AD-PG-007`).
 *
 * 흐름은 하나뿐이다(Desc 0): ① 초안 편집 → ② 초안 평가 → ③ 운영 반영.
 *  - 이 화면의 설정은 전부 런타임 설정(검색·답변 생성)이라 예외 분기가 없다
 *  - 최신 평가가 게이트를 통과해야 [운영 반영]이 활성화되고, 무중단 즉시 적용된다
 *  - 평가 이후 초안을 수정하면 평가가 무효화되어 ②부터 다시 밟는다
 *  - 적재 설정(청킹·임베딩)은 이 화면에 없다. AD-004 [재적재] 실행 설정에서 다룬다
 *
 * 파라미터 현행값·반영 시점의 정본은 CM-DF-003 05절 표이며 **서버 응답으로 렌더**한다(화면 하드코딩 금지).
 * 리랭킹·업무 필터는 관리 대상이 아니라 아예 노출하지 않는다(§1.8 각주).
 * 셸(GNB·헤더·설정 서브탭)은 app/AdminLayout.tsx가 그린다 — 여기서 다시 그리지 않는다. */
import { useEffect, useState } from 'react'
import { ReturnBand } from '../ReturnBand'
import type { ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { History, MessageSquareText, Search } from 'lucide-react'
import {
  Badge, Button, ColorText, ConfirmModal, DataTable, DraftStatusBar, Loading, Notice, ReadOnlyNotice, Select, Slider,
  Stepper, Toggle, useToast,
} from '../../../components/ui'
import type { Column } from '../../../components/ui'
import { hasRole } from '../../../lib/codes'
import { useSession } from '../../../app/session'
import { formatShortKst } from '../evaluation/kst'
import { Card, SectionError, modalError } from './promptops/common'
import { AbCompare } from './rag/AbCompare'
import {
  applyDraft, evaluateDraft, fetchHistory, fetchParams, ragKeys, resetDraft, rollbackTo,
} from './rag/api'
import type { ParamValue, RagHistoryEntry, RagParam, RagParamsResponse } from './rag/api'

type Values = Record<string, ParamValue>

/** 화면에 찍는 표시값 — 토글은 On/Off 글자로 남긴다(색만으로 알리지 않는다) */
function display(param: RagParam, value: ParamValue): string {
  if (param.control === 'toggle') return value ? 'On' : 'Off'
  return String(value)
}

/** 값이 바뀐 파라미터만 추린다. [운영 반영 (N)]의 N이 이 개수다 */
function changedParams(params: RagParam[], draft: Values, current: Values): RagParam[] {
  return params.filter((p) => String(draft[p.key]) !== String(current[p.key]))
}

/** 반영 시점 배지 — 경고색은 '재적재 필요'만 쓴다.
 * 무중단은 기본 상태라 중립 태그(Badge purple 톤 = 중립)로 낮춘다 — 색이 의미를 잃지 않게 */
function TimingBadge({ timing }: { timing: RagParam['apply_timing'] }) {
  return timing === '무중단' ? (
    <Badge tone="purple" kind="status">{timing}</Badge>
  ) : (
    <Badge tone="orange" kind="warning">{timing}</Badge>
  )
}

export function RagParams() {
  const { session } = useSession()
  const canEdit = hasRole(session?.role, 'EDITOR')
  const showToast = useToast()
  const queryClient = useQueryClient()

  const params = useQuery({ queryKey: ragKeys.params, queryFn: fetchParams })
  const history = useQuery({ queryKey: ragKeys.history, queryFn: fetchHistory })

  const [draft, setDraft] = useState<Values | null>(null)
  /** 마지막 [초안 평가]에 실은 값 스냅샷. 서버 시그니처는 opaque 토큰(실서버는 sha256 해시,
   *  admin_rag_params.py:156)이라 프론트가 포맷을 해석하면 안 된다 — JSON.stringify 와 비교하던
   *  종전 코드는 실백엔드에서 영구 stale 이었다(2026-08-13 실측). 값 비교로 판정한다 */
  const [evaluated, setEvaluated] = useState<Values | null>(null)
  const [applyOpen, setApplyOpen] = useState(false)
  const [resetOpen, setResetOpen] = useState(false)
  const [rollbackTarget, setRollbackTarget] = useState<RagHistoryEntry | null>(null)
  /** A/B 비교 결과를 비우기 위한 remount 열쇠 — 초기화가 누른 뒤 옛 초안 결과가 남지 않게 */
  const [abSeq, setAbSeq] = useState(0)

  const server = params.data
  // 서버가 준 초안(없으면 현행)을 편집 시작점으로 삼는다. 재조회로 초안을 덮어쓰지 않는다
  useEffect(() => {
    if (server && draft === null) {
      setDraft({ ...(server.draft ?? server.current) })
      // 서버가 초안+게이트를 갖고 있으면 그 초안이 곧 '평가된 초안'이다(_stored_gate) — 새로고침 복원
      if (server.gate.draft_signature !== null && server.draft) setEvaluated({ ...server.draft })
    }
  }, [server, draft])

  const evaluate = useMutation({
    mutationFn: (values: Values) => evaluateDraft(values),
    onSuccess: (gate, values) => {
      setEvaluated({ ...values })
      queryClient.setQueryData<RagParamsResponse>(ragKeys.params, (prev) =>
        prev ? { ...prev, gate } : prev,
      )
    },
  })

  const apply = useMutation({
    mutationFn: ({ values, reason }: { values: Values; reason: string }) => applyDraft(values, reason),
    onSuccess: (res) => {
      queryClient.setQueryData(ragKeys.params, res)
      void queryClient.invalidateQueries({ queryKey: ragKeys.history })
      setDraft({ ...res.current })
      setEvaluated(null)
      setApplyOpen(false)
      showToast('설정을 운영에 반영했습니다')
    },
  })

  /** [초기화] — 서버의 초안 행까지 버린다. 로컬 draft 만 되돌리면 게이트 배지·정량 비교가
   *  그대로 남고, 새로고침하면 서버 초안이 되살아나 초기화가 되지 않는다 */
  const reset = useMutation({
    mutationFn: () => resetDraft(),
    onSuccess: (res) => {
      queryClient.setQueryData(ragKeys.params, res)
      setDraft({ ...res.current })
      setEvaluated(null)
      setResetOpen(false)
      // A/B 결과는 버린 초안(B)으로 낸 것이라 함께 지운다 — remount 로 비운다
      setAbSeq((n) => n + 1)
      showToast('초안을 버리고 현행 운영값으로 되돌렸습니다')
    },
  })

  const rollback = useMutation({
    mutationFn: (entry: RagHistoryEntry) => rollbackTo(entry.id),
    onSuccess: (res) => {
      setDraft({ ...res.draft })
      setRollbackTarget(null)
      // [롤백]은 초안만 되돌린다. 실제 적용은 [운영 반영]이 한다(§1.7)
      showToast('그 시점 값으로 초안을 복원했습니다 · [운영 반영]해야 실제 적용됩니다')
    },
  })

  if (params.isPending || draft === null) return <Loading text="설정을 불러오는 중…" />
  if (params.isError) {
    return <SectionError error={params.error} onRetry={() => void params.refetch()} />
  }
  if (!server) return null

  const { current, gate } = server
  const changed = changedParams(server.params, draft, current)
  const timings = changed.map((p) => p.apply_timing)
  const seamless = timings.filter((t) => t === '무중단').length
  const reindex = timings.filter((t) => t === '재적재 필요').length
  /** 평가 이후 초안을 수정하면 평가가 무효화된다(Desc 0) — 평가 시점 스냅샷과 값 비교 */
  const stale = gate.draft_signature !== null &&
    (evaluated === null || changedParams(server.params, draft, evaluated).length > 0)
  const gateReady = gate.passed && !stale
  /** 게이트·평가 상태는 반영을 막지 않고 경고로만 알린다(2026-08-19 정책 변경).
   *  AD-008 publishBlocked와 같은 형태 — 두 화면이 같은 상태에서 같게 행동해야 한다 */
  const gateWarning = stale
    ? '초안이 바뀌어 평가가 무효화되었습니다 — 재평가 없이 반영하면 결과를 보증할 수 없습니다'
    : (gate.warning_reason ? `${gate.warning_reason} — 이 상태로도 반영은 가능합니다` : undefined)
  const applyBlocked = !canEdit
    ? '편집자(EDITOR) 이상만 운영에 반영할 수 있습니다'
    : undefined

  function set(key: string, value: ParamValue) {
    setDraft((prev) => ({ ...(prev ?? {}), [key]: value }))
  }

  function renderControl(p: RagParam) {
    const value = draft![p.key]
    const baseline = current[p.key]
    const disabledReason = canEdit ? undefined : '수정하려면 EDITOR 권한이 필요합니다'
    // 최종 근거 수는 1차 후보 수를 넘을 수 없다(후보 컷 뒤에서 고르므로) — 기획서에 없는 상호 제약
    const max = p.key === 'k_final' ? Number(draft!['k_candidates']) : p.max

    switch (p.control) {
      case 'stepper':
        return (
          <Stepper
            label={p.label} hint={p.note} value={Number(value)} baseline={Number(baseline)}
            min={p.min} max={max} step={p.step} disabled={!canEdit} disabledReason={disabledReason}
            onChange={(v) => set(p.key, v)}
          />
        )
      case 'toggle':
        return (
          <Toggle
            label={p.label} hint={p.note} checked={Boolean(value)} baseline={baseline ? 'On' : 'Off'}
            disabled={!canEdit} disabledReason={disabledReason}
            onChange={(v) => set(p.key, v)}
          />
        )
      case 'slider':
        return (
          <Slider
            label={p.label} hint={p.note} value={Number(value)} baseline={Number(baseline)}
            min={p.min} max={p.max} step={p.step}
            scaleStart={p.scale_start} scaleEnd={p.scale_end}
            disabled={!canEdit} disabledReason={disabledReason}
            onChange={(v) => set(p.key, v)}
          />
        )
      case 'select':
        return (
          <Select
            label={p.label} hint={p.note} value={String(value)} baseline={String(baseline)}
            options={(p.options ?? []).map((o) => ({ value: o, label: o }))}
            disabled={!canEdit} disabledReason={disabledReason}
            onChange={(v) => set(p.key, v)}
          />
        )
    }
  }

  function card(group: RagParam['group'], title: string, icon: ReactNode) {
    return (
      // 카드 헤더 배지 = 이 카드 항목이 전부 무중단이라는 정적 표기(§1.3·§1.4)
      <Card title={title} icon={icon} meta={<TimingBadge timing="무중단" />}>
        <div className="divide-y">
          {server!.params
            .filter((p) => p.group === group)
            .map((p) => (
              <div className="py-1 first:pt-0 last:pb-0" key={p.key}>
                {renderControl(p)}
                {/* note는 '이 파라미터가 언제 쓰이나'라는 규칙이다. 행 아래 한 줄로 깔면 그 행만
                    높아져 divide-y로 맞춰 둔 행 높이가 들쭉날쭉해진다 — 라벨 옆 ⓘ로 접는다
                    (renderControl 안에서 Field 라벨 옆에 붙인다) */}
              </div>
            ))}
        </div>
      </Card>
    )
  }

  /** 확인 모달 ③ 변경 대비 — 표는 공통 DataTable로만 그린다(CM-DF-001 10절 매핑표) */
  const diffColumns: Column<RagParam>[] = [
    { key: 'label', header: '항목', render: (p) => p.label, width: '34%' },
    { key: 'current', header: '현행', render: (p) => display(p, current[p.key]), width: '20%' },
    {
      key: 'next',
      header: '변경',
      width: '22%',
      render: (p) => <ColorText tone="orange">→ {display(p, draft![p.key])}</ColorText>,
    },
    {
      key: 'timing',
      header: '반영 시점',
      width: '24%',
      render: (p) => <TimingBadge timing={p.apply_timing} />,
    },
  ]

  const historyColumns: Column<RagHistoryEntry>[] = [
    { key: 'changed_at', header: '일시', render: (r) => formatShortKst(r.changed_at), width: '18%' },
    { key: 'summary', header: '변경 내용', render: (r) => <strong>{r.summary}</strong>, width: '38%' },
    { key: 'actor', header: '변경자', render: (r) => r.actor, width: '12%' },
    { key: 'reason', header: '사유', render: (r) => <span className="text-muted-foreground">{r.reason}</span> },
  ]
  const historyRows = history.data?.items ?? []

  return (
    <div className="flex flex-col gap-4">
      {/* 대화 로그 [다음 조치]로 넘어온 경우의 되돌아가기 띠(2026-08-18). 한 건의 A/B 결과로
          반영을 결정하지 않는다는 경고를 함께 — 판정은 게이트가 한다 */}
      <ReturnBand note="이 한 건의 결과로 반영을 결정하지 않습니다 — 홀드아웃 게이트 판정은 경고로 함께 표시됩니다" />
      {/* ---------------- ⓪ 초안 상태 바 — 화면 최상단 sticky ---------------- */}
      {/* 상태 바는 권한과 무관하게 항상 그린다. 통째로 숨기면 VIEWER가 이 화면에서만 다른 세계를
          보게 되고(AD-008은 항상 그리고 사유로 막는다), '왜 못 바꾸나'를 알 길도 사라진다 —
          03절 규칙 3(비활성은 숨기지 말고 사유 표기)도 같은 방향이다 */}
      {/* 배경은 지면과 같은 흰색 — 스크롤 내용이 비쳐 보이지 않게 막기만 한다(회색 띠를 만들지 않는다) */}
      <div className="sticky top-0 z-20 -mx-6 -mt-6 bg-background px-6 pt-6 pb-1">
          <DraftStatusBar
            changeCount={changed.length}
            chips={
              <>
                <Badge tone="purple" kind="count">
                  {reindex === 0 && changed.length > 0 ? '전부 무중단' : `무중단 ${seamless}`}
                </Badge>
                {reindex > 0 && (
                  <Badge tone="orange" kind="warning">재적재 필요 {reindex}</Badge>
                )}
                {/* 미달과 미평가는 다른 상태다 — 평가한 적이 없는데 '미통과'라고 쓰면 무언가
                    떨어진 것처럼 읽힌다. 바꾼 것이 없으면 게이트를 논할 대상 자체가 없다 */}
                {changed.length === 0 ? null : gateReady ? (
                  <Badge tone="green" kind="status">게이트 통과</Badge>
                ) : gate.draft_signature === null || stale ? (
                  <Badge tone="orange" kind="warning">미평가</Badge>
                ) : (
                  <Badge tone="orange" kind="warning">게이트 미통과</Badge>
                )}
              </>
            }
            hint="① 편집 → ② 초안 평가 → ③ 운영 반영 순서로 진행합니다. 게이트 미달·미평가는 경고로만 표시되며 반영을 막지 않습니다."
            primaryLabel={`운영 반영 (${changed.length})`}
            pending={apply.isPending}
            // 눌러 봐야 사유가 뜨는 방식을 버리고 AD-008과 같이 선언형으로 막는다 —
            // 두 화면이 같은 상태에서 같게 행동해야 한다
            primaryDisabled={applyBlocked !== undefined}
            primaryDisabledReason={applyBlocked}
            // ②단계 액션도 상태 바에 둔다 — ① 편집 → ② 초안 평가 → ③ 운영 반영이 한 줄이다(§1.2)
            secondaryLabel="초안 평가"
            onSecondary={() => evaluate.mutate(draft!)}
            onReset={() => setResetOpen(true)}
            onPrimary={() => setApplyOpen(true)}
          />
      </div>

      {/* 권한 안내는 화면에서 한 번만 한다 — 컨트롤마다 같은 문장을 달면 그 말로 화면이 뒤덮인다.
          상태바(sticky)는 -mt-6로 위를 덮으므로 반드시 그 **아래**에 둔다(실측: 문구 절반이 잘렸다) */}
      {!canEdit && <ReadOnlyNotice need="편집자(EDITOR) 이상" action="파라미터를 바꾸려면" />}

      {/* 경고는 반영을 막지 않는다(2026-08-19) — 인지용 색면 인셋으로만 세운다.
          AD-008과 같은 자리·같은 톤 */}
      {canEdit && changed.length > 0 && !gateReady && gateWarning && (
        <Notice tone="warning" variant="block">
          {gateWarning}
        </Notice>
      )}

      {/* ---------------- ① ② 파라미터 2컬럼 ---------------- */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {card('retrieval', '검색 시점 파라미터', <Search />)}
        {card('generation', '답변 생성 설정', <MessageSquareText />)}
      </div>

      {/* ---------------- ③ ④ A/B 비교 · 정량 비교 ---------------- */}
      <AbCompare
        key={abSeq}
        draft={draft}
        gate={gate}
        evaluating={evaluate.isPending}
        evaluateError={evaluate.error}
      />

      {/* ---------------- ⑤ 설정 이력 ---------------- */}
      <Card
        title="설정 이력"
        icon={<History />}
        meta="[운영 반영] 시 자동 기록"
        // 표에 '사유' 열이 이미 있어 '사유를 확인하라'는 지시는 표를 보면 저절로 따라온다.
        // 헤더 meta 아래 같은 성격의 문단을 한 겹 더 쌓지 않는다
        hint="현재 값이 왜 이 상태인지의 근거입니다. 되돌리기 전에 변경 사유를 먼저 확인하세요."
      >

        {history.isPending ? (
          <Loading text="설정 이력을 불러오는 중…" />
        ) : history.isError ? (
          <SectionError error={history.error} onRetry={() => void history.refetch()} />
        ) : (
          <DataTable
            caption="RAG 파라미터 설정 이력"
            columns={historyColumns}
            rows={historyRows}
            rowKey={(r) => r.id}
            // 가장 최근 건을 강조한다(§1.7)
            rowState={(r) => (r.id === historyRows[0]?.id ? 'selected' : 'default')}
            actions={
              canEdit
                ? (r) => (
                    <Button size="sm" onClick={() => setRollbackTarget(r)}>
                      롤백
                    </Button>
                  )
                : undefined
            }
          />
        )}
      </Card>

      {/* ---------------- 확인 모달 3종 ---------------- */}
      <ConfirmModal
        open={applyOpen}
        title="이 설정을 운영에 반영할까요?"
        impact={
          <>
            <p>
              변경 {changed.length}건 · 무중단 {seamless}
              {reindex > 0 && ` · 재적재 필요 ${reindex}`} — 반영은 전부 무중단 즉시 적용이며 실패 시 이전 버전을
              유지합니다.
            </p>
            {/* 마지막 인지 지점 — 경고 상태로 반영하려는 참이면 모달 안에서 한 번 더 알린다(2026-08-19) */}
            {!gateReady && gateWarning && (
              <p className="mt-1 font-medium"><ColorText tone="orange">⚠ {gateWarning}</ColorText></p>
            )}
          </>
        }
        diff={
          <>
            <DataTable
              caption="운영 반영 변경 대비"
              columns={diffColumns}
              rows={changed}
              rowKey={(p) => p.key}
            />
            {gate.quantitative && (
              <p className="mt-2 text-xs leading-relaxed">
                정량 비교{' '}
                {gate.quantitative.metrics
                  .map((m) => `${m.label} ${m.a.toFixed(3)} → ${m.b.toFixed(3)}`)
                  .join(' · ')}
              </p>
            )}
            {/* 게이트는 통과했지만 현행보다 낮은 지표가 있을 때의 경고 — 서버 문구 그대로 */}
            {gate.warning && (
              <Notice tone="warning" variant="inline" className="mt-2">
                {gate.warning}
              </Notice>
            )}
          </>
        }
        reason="required"
        reasonPlaceholder="예: 링크 안내 질의 검색 개선 시도, 1주 모니터링 후 재평가 예정"
        error={modalError(apply.error)}
        confirmLabel="운영 반영"
        pending={apply.isPending}
        onConfirm={({ reason }) => apply.mutate({ values: draft, reason: reason ?? '' })}
        onCancel={() => setApplyOpen(false)}
      />

      <ConfirmModal
        open={resetOpen}
        title="편집 중인 초안을 버릴까요?"
        impact={<p>변경 {changed.length}건이 사라지고 현행 운영값으로 돌아갑니다. 운영 설정은 바뀌지 않습니다.</p>}
        confirmLabel="초기화"
        pending={reset.isPending}
        onConfirm={() => reset.mutate()}
        onCancel={() => setResetOpen(false)}
      />

      <ConfirmModal
        open={rollbackTarget !== null}
        title="이 시점 값으로 초안을 복원할까요?"
        impact={
          <p>
            {rollbackTarget?.summary} · 사유 : {rollbackTarget?.reason} — 초안만 복원합니다. [운영 반영]을 해야
            실제로 적용됩니다.
          </p>
        }
        error={modalError(rollback.error)}
        confirmLabel="롤백"
        pending={rollback.isPending}
        onConfirm={() => rollbackTarget && rollback.mutate(rollbackTarget)}
        onCancel={() => setRollbackTarget(null)}
      />
    </div>
  )
}
