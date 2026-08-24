/** AD-008 프롬프트 · 가드레일 관리 (KDIC-AD-PG-008).
 *
 * 3단계 골격은 기획서 12절 §2 그대로: ① 초안 편집 → ② 평가·회귀 → ③ 게시.
 * - 초안 수정은 서버에 쌓지 않는다. 로컬 상태 + localStorage에만 쌓이고(useLocalDraft),
 *   서버 쓰기는 [게시]·[게시 요청] 때뿐이다. 수정하는 순간 직전 평가가 무효화된다(§2.2).
 * - 게시는 회귀 게이트 3항목이 모두 ✓여야 열린다. EDITOR는 [게시 요청] → ADMIN 승인,
 *   ADMIN은 요청 없이 바로 [게시]('단독 게시'로 활동 로그에 기록, §2.9).
 * - 셸(GNB·헤더·설정 서브탭)은 AdminLayout이 그린다. 여기서 다시 그리지 않는다.
 * - ※로 시작하는 빨간 주석은 기획 주석이라 렌더하지 않는다(00-meta NOTATION). */
import { useState } from 'react'
import { ReturnBand } from '../ReturnBand'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CARD_COLUMN, CARD_COLUMNS, ConfirmModal, DirtyDot, DraftStatusBar, Loading, Notice, ReadOnlyNotice, useToast,
} from '../../../components/ui'
import { cn } from '@/lib/utils'
import { hasRole } from '../../../lib/codes'
import { useSession } from '../../../app/session'
import { Card, SectionError, modalError } from './promptops/common'
import {
  BlocklistDialog, FewshotCard, GuardrailCard, GuardrailListCard, MaskingDialog, SystemPromptCard,
  VersionHistoryCard,
} from './promptops/prompt-cards'
import { BeforeAfterCard } from './promptops/prompt-compare'
import { EvalPickerDialog } from './eval-picker'
import type {
  BlocklistRule, MaskingRule, PromptDraft, PromptDraftContent, PromptEvaluation,
  PromptPrinciple, PromptVersion,
} from './promptops/api'
import {
  EVAL_PICK_MAX, emergencyRollback, evaluatePrompt, fetchPromptDraft, promptKeys, publishPrompt,
  reauthenticate, rollbackVersion,
} from './promptops/api'
import { contentOf, deriveDraft, useLocalDraft } from './promptops/useLocalDraft'

type TabKey = 'prompt' | 'fewshot' | 'guardrail'
type DialogKey = 'blocklist' | 'masking'

/** 확인 모달은 한 번에 하나만 열리므로 종류 + 대상만 들고 있으면 된다 */
type Ask =
  | { kind: 'reset' }
  | { kind: 'publish' }
  | { kind: 'rollback'; version: PromptVersion }
  | { kind: 'emergency'; version: PromptVersion }

/** 게시는 사유와 함께 로컬 초안을 통째로 실어 보낸다(서버에 초안이 없기 때문) */
interface PublishInput {
  reason: string
  content: PromptDraftContent
  gate: boolean
}

export function PromptGuardrail() {
  const { session } = useSession()
  const role = session?.role ?? 'VIEWER'
  const canEdit = hasRole(role, 'EDITOR')
  const canAdmin = hasRole(role, 'ADMIN')
  const qc = useQueryClient()
  const showToast = useToast()

  const [tab, setTab] = useState<TabKey>('prompt')
  const [dialog, setDialog] = useState<DialogKey | null>(null)
  const [ask, setAsk] = useState<Ask | null>(null)
  /** 평가는 일시적이다 — 서버가 들고 있지 않으므로 화면이 보관했다가 게시 때 게이트 결과만 실어 보낸다 */
  const [evaluation, setEvaluation] = useState<PromptEvaluation | null>(null)

  const draftQuery = useQuery({ queryKey: promptKeys.draft, queryFn: fetchPromptDraft })
  /** 서버 초안 대신 로컬 초안. 기준값(base_version)이 그대로일 때만 복구된다 */
  const local = useLocalDraft(draftQuery.data?.base_version)

  const putDraft = (next: PromptDraft) => qc.setQueryData(promptKeys.draft, next)
  /** 닫을 때 직전 실패를 지운다 — 다음에 연 모달에 남의 오류가 남지 않도록 */
  const closeAsk = () => {
    setAsk(null)
    publish.reset()
    rollback.reset()
    emergency.reset()
  }
  const refetchAll = () => {
    void qc.invalidateQueries({ queryKey: promptKeys.draft })
    void qc.invalidateQueries({ queryKey: promptKeys.versions })
  }

  /** [초안 평가]는 문항 고르기 모달을 먼저 연다 — 무엇으로 재는지 보고 고른 뒤 실행한다.
   *  고른 id 는 다음에 열 때의 시작점으로만 남기고, 프롬프트 초안과 섞지 않는다(문항은
   *  프롬프트 내용이 아니라 평가 설정이라 게시 payload·변경 건수에 들어가면 안 된다). */
  const [pickerOpen, setPickerOpen] = useState(false)
  const [lastIds, setLastIds] = useState<string[]>([])

  /** [초안 평가] — 로컬 초안을 실어 보내는 일시 평가. 서버 초안을 만들지도 바꾸지도 않는다 */
  const evaluate = useMutation({
    mutationFn: evaluatePrompt,
    onSuccess: (result) => setEvaluation(result),
  })

  const publish = useMutation({
    mutationFn: (input: PublishInput) => publishPrompt(input.reason, input.content, input.gate),
    onSuccess: (result) => {
      // 서버에 저장된 순간 로컬 초안은 소임을 다했다 — 비우고 새 기준값을 다시 받는다
      local.clear()
      setEvaluation(null)
      closeAsk()
      refetchAll()
      showToast(`${result.version}을(를) 게시했습니다`)
    },
  })

  const rollback = useMutation({
    mutationFn: (input: { version: string; reason: string }) => rollbackVersion(input.version, input.reason),
    onSuccess: (next) => {
      putDraft(next)
      // 롤백이 새 기준값을 준다 — 그 위에 얹혀 있던 로컬 편집분은 복원 결과를 가리므로 함께 버린다
      local.clear()
      setEvaluation(null)
      closeAsk()
      showToast('선택한 버전을 초안으로 복원했습니다')
    },
  })

  /** 긴급 롤백 — 비밀번호 재확인을 먼저 통과해야 실행한다(REQ-OPS-003) */
  const emergency = useMutation({
    mutationFn: async (input: { version: string; reason: string; password: string }) => {
      await reauthenticate(input.password)
      return emergencyRollback(input.version, input.reason)
    },
    onSuccess: (version) => {
      closeAsk()
      refetchAll()
      showToast(`${version.version}(으)로 즉시 되돌렸습니다`)
    },
  })

  if (draftQuery.isPending) return <Loading />
  if (draftQuery.isError) {
    return <SectionError error={draftQuery.error} onRetry={() => void draftQuery.refetch()} />
  }

  // 서버 기준값 + 로컬 편집분. change_count·dirty·char_count는 이 자리에서 계산된다
  const draft = deriveDraft(draftQuery.data, local.content, evaluation)
  const gatePassed = draft.evaluation?.gate.passed === true
  const editable = canEdit
  /** [게시]를 막는 조건은 권한뿐이다(2026-08-19 정책 변경) — 회귀 게이트는 경고로만
   *  알린다. 요청/승인 2단계를 없앤 팀 결정(2026-08-04)에 이어 게이트 차단도 해제했다 */
  const publishBlocked = !canEdit
    ? '편집자(EDITOR) 이상만 게시할 수 있습니다'
    : undefined

  const tabs: { key: TabKey; label: string; dirty: boolean }[] = [
    { key: 'prompt', label: '시스템 프롬프트', dirty: draft.dirty.prompt },
    { key: 'fewshot', label: `예시 답변 (${draft.fewshots.length})`, dirty: draft.dirty.fewshot },
    {
      key: 'guardrail',
      label: `가드레일 규칙 (${draft.blocklist.items.length + draft.masking.items.length})`,
      dirty: draft.dirty.guardrail,
    },
  ]

  /** 카드 편집 확정 — 서버 PUT이 아니라 로컬 초안 갱신 + localStorage 기록이다.
   *  수정하면 직전 평가는 그 자리에서 무효가 된다(§2.2 "평가 이후 초안을 수정하면 ②부터 다시") */
  const edit = (patch: Partial<PromptDraftContent>) => {
    local.save({ ...contentOf(draft), ...patch })
    setEvaluation(null)
    setDialog(null)
  }
  const onPrincipleChange = (principles: PromptPrinciple[]) => edit({ principles })
  const onBlocklist = (items: BlocklistRule[], active = draft.blocklist.active) =>
    edit({ blocklist: { active, items } })
  const onMasking = (items: MaskingRule[], active = draft.masking.active) =>
    edit({ masking: { active, items } })

  return (
    <div className="flex flex-col gap-4">
      <ReturnBand />
      {/* 상태 바는 화면 최상단 sticky — 스크롤해도 ①편집→②평가→③게시 한 줄이 남는다 */}
      <div className="sticky top-0 z-20 -mx-6 -mt-6 bg-background px-6 pt-6 pb-1">
        <DraftStatusBar
          changeCount={draft.change_count}
          hint="수정한 영역에 빨간 점이 붙습니다. ① 편집 → ② 초안 평가 → ③ 게시 순서를 권장하며, 회귀 게이트 미통과는 경고로만 표시되고 게시를 막지 않습니다."
          // 요청/승인 2단계를 없애 라벨이 하나다(팀 결정 2026-08-04) — 권한별로 갈리지 않는다
          primaryLabel={`게시 (${draft.change_count})`}
          pending={publish.isPending}
          primaryDisabled={publishBlocked !== undefined}
          primaryDisabledReason={publishBlocked}
          onPrimary={() => setAsk({ kind: 'publish' })}
          // §0.4 취소 액션은 [초안 취소]가 원문이지만, 되돌리기가 로컬 편집분만 버리는 작업이 되어
          // AD-007·AD-009와 같은 기본 라벨 [초기화]로 통일한다(기획서 반영 대상)
          onReset={() => {
            if (editable && draft.change_count > 0) setAsk({ kind: 'reset' })
          }}
          // ②단계 액션도 상태 바에 둔다 — ① 편집 → ② 초안 평가 → ③ 게시가 한 줄이다(§2.2).
          //
          // ⚠ 기획서 이탈: §0.4 차이 표는 AD-008만 [전후 비교]라 적었지만, 이 버튼이 하는 일은
          // AD-007 [초안 평가]와 같다 — 초안을 평가해 게이트를 열고 현행과 비교한다.
          // 다른 건 '무엇을 비교하는가'(지표 vs 답변)뿐이고 그건 아래 카드 제목이 이미 말한다
          // (`초안 평가 : A/B 검색 비교` / `초안 평가 : 전후 답변 비교`).
          // 같은 동작에 두 이름을 붙이면 두 화면이 다른 물건처럼 보인다(사용자 지적).
          secondaryLabel="초안 평가"
          onSecondary={() => setPickerOpen(true)}
        />
      </div>

      {/* 권한 안내는 화면에서 한 번만 한다 — 컨트롤마다 같은 문장을 달면 그 말로 화면이 뒤덮인다.
          상태바(sticky)는 -mt-6로 위를 덮으므로 반드시 그 **아래**에 둔다(실측: 문구 절반이 잘렸다) */}
      {!canEdit && <ReadOnlyNotice need="편집자(EDITOR) 이상" action="프롬프트·가드레일을 바꾸려면" />}

      {/* 내가 편집하는 사이 다른 관리자가 게시했다 — 낡은 기준 위의 편집분은 되살리지 않고 버린다.
          조치(다시 편집)가 필요한 상태라 옅은 색면 인셋(block)으로 세운다 */}
      {local.discarded && (
        <Notice tone="warning" variant="block">
          그 사이 {draft.base_version}이 게시되어 편집 중이던 초안을 버렸습니다. 새 기준으로 다시 편집해
          주세요
        </Notice>
      )}

      {/* 게이트는 게시를 막지 않는다(2026-08-19) — 인지용 경고 인셋만 세운다 */}
      {draft.change_count > 0 && !gatePassed && (
        <Notice tone="warning" variant="block">
          회귀 게이트를 통과하지 않은 초안입니다 — 이대로도 게시는 가능하지만 [초안 평가]로 회귀 여부를 먼저
          확인하는 것을 권장합니다
        </Notice>
      )}


      {/* 알약 탭 대신 밑줄 탭 — 현재 위치는 색면이 아니라 글자색+굵기+2px 밑줄로 알린다 */}
      <div className="flex flex-wrap gap-1 border-b" role="tablist" aria-label="프롬프트 편집 영역">
        {tabs.map((t, i) => (
          <button
            key={t.key}
            type="button"
            className={cn(
              'relative -mb-px inline-flex h-10 cursor-pointer items-center gap-1 border-b-2 border-transparent px-3 text-sm text-muted-foreground transition-colors duration-200 outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
              'aria-selected:border-b-primary aria-selected:font-semibold aria-selected:text-primary',
            )}
            role="tab"
            id={`ptab-${t.key}`}
            aria-selected={tab === t.key}
            // 패널은 선택된 탭 하나만 존재한다 — 비선택 탭이 없는 id를 가리키지 않게 한다
            aria-controls={tab === t.key ? `ppanel-${t.key}` : undefined}
            // roving tabindex — 탭 묶음에 Tab 한 번, 좌우 화살표로 이동(WAI-ARIA tabs)
            tabIndex={tab === t.key ? 0 : -1}
            onClick={() => setTab(t.key)}
            onKeyDown={(e) => {
              if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
              const next = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length]
              setTab(next.key)
              document.getElementById(`ptab-${next.key}`)?.focus()
            }}
          >
            {t.label}
            {t.dirty && <DirtyDot label={`${t.label} 변경됨`} />}
          </button>
        ))}
      </div>

      <div className={CARD_COLUMNS}>
        <div
          className={CARD_COLUMN}
          role="tabpanel"
          id={`ppanel-${tab}`}
          aria-labelledby={`ptab-${tab}`}
        >
          {tab === 'prompt' && (
            <SystemPromptCard draft={draft} canEdit={editable} onChange={onPrincipleChange} />
          )}
          {tab === 'fewshot' && <FewshotCard items={draft.fewshots} dirty={draft.dirty.fewshot} />}
          {tab === 'guardrail' && (
            <GuardrailListCard
              draft={draft}
              onEditBlocklist={() => setDialog('blocklist')}
              onEditMasking={() => setDialog('masking')}
            />
          )}
        </div>

        <div className={CARD_COLUMN}>
          <VersionHistoryCard
            canEdit={editable}
            canAdmin={canAdmin}
            onRollback={(version) => setAsk({ kind: 'rollback', version })}
            onEmergencyRollback={(version) => setAsk({ kind: 'emergency', version })}
          />
          {/* 가드레일 탭을 보고 있으면 왼쪽 목록 카드와 제목·건수·[편집]이 겹친다 — 한 곳에서만 그린다 */}
          {tab !== 'guardrail' && (
          <GuardrailCard
            draft={draft}
            canEdit={editable}
            onToggleBlocklist={(active) => onBlocklist(draft.blocklist.items, active)}
            onToggleMasking={(active) => onMasking(draft.masking.items, active)}
            onEditBlocklist={() => setDialog('blocklist')}
            onEditMasking={() => setDialog('masking')}
          />
          )}
        </div>
      </div>

      <BeforeAfterCard
        evaluation={draft.evaluation}
        baseVersion={draft.base_version}
        running={evaluate.isPending}
        error={evaluate.error}
        onRun={() => setPickerOpen(true)}
      />

      <EvalPickerDialog
        open={pickerOpen}
        maxPicks={EVAL_PICK_MAX}
        costHint={(n) =>
          `문항당 현행·초안 두 벌을 생성하므로 답변 생성은 ${n * 2}회입니다`}
        initialIds={lastIds}
        running={evaluate.isPending}
        onClose={() => setPickerOpen(false)}
        onRun={(ids) => {
          setLastIds(ids)
          setPickerOpen(false)
          evaluate.mutate({ draft: contentOf(draft), questionIds: ids })
        }}
      />

      {/* 편집 모달은 열 때마다 새로 마운트해 현재 초안 값으로 초기화한다 */}
      {dialog === 'blocklist' && (
        <BlocklistDialog
          open
          items={draft.blocklist.items}
          canEdit={editable}
          onSave={(items) => onBlocklist(items)}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === 'masking' && (
        <MaskingDialog
          open
          items={draft.masking.items}
          canEdit={editable}
          onSave={(items) => onMasking(items)}
          onClose={() => setDialog(null)}
        />
      )}

      {/* [초기화] — 서버를 건드리지 않고 로컬 편집분만 버린다(AD-007·AD-009의 같은 버튼과 형태를 맞췄다).
          사유를 받지 않는 이유: 운영에 반영된 적 없는 로컬 편집이라 감사 대상이 아니다 */}
      <ConfirmModal
        open={ask?.kind === 'reset'}
        title="편집 중인 초안을 버릴까요?"
        impact={`변경 ${draft.change_count}건이 사라지고 현행 운영값으로 돌아갑니다. 운영 설정은 바뀌지 않습니다.`}
        confirmLabel="초기화"
        onConfirm={() => {
          local.clear()
          // 버린 초안을 대상으로 낸 판정이라 평가 결과도 함께 버린다
          setEvaluation(null)
          closeAsk()
        }}
        onCancel={closeAsk}
      />

      <ConfirmModal
        open={ask?.kind === 'publish'}
        title="이 초안을 게시할까요?"
        // 문항 수를 쓰지 않는다 — 게시 '전'이라 결과가 없고, 프론트가 박아 둔 숫자는 서버가
        impact={`게시하면 ${draft.draft_version}이 곧바로 현행으로 전환됩니다. 문제가 있으면 [롤백]·[긴급 롤백]으로 되돌립니다.${gatePassed ? '' : ' ⚠ 회귀 게이트를 통과하지 않은 초안입니다.'}`}
        diff={<PublishDiff draft={draft} />}
        reason="required"
        error={modalError(publish.error)}
        confirmLabel="게시"
        pending={publish.isPending}
        onConfirm={({ reason }) =>
          publish.mutate({ reason: reason ?? '', content: contentOf(draft), gate: gatePassed })
        }
        onCancel={closeAsk}
      />

      <ConfirmModal
        open={ask?.kind === 'rollback'}
        title={ask?.kind === 'rollback' ? `${ask.version.version} 버전으로 되돌릴까요?` : ''}
        impact="선택한 버전을 새 초안으로 복원할 뿐 즉시 반영하지 않습니다. [게시]를 해야 현행이 됩니다."
        reason="required"
        error={modalError(rollback.error)}
        confirmLabel="롤백"
        pending={rollback.isPending}
        onConfirm={({ reason }) => {
          if (ask?.kind === 'rollback') rollback.mutate({ version: ask.version.version, reason: reason ?? '' })
        }}
        onCancel={closeAsk}
      />

      <ConfirmModal
        open={ask?.kind === 'emergency'}
        variant="danger"
        title={ask?.kind === 'emergency' ? `${ask.version.version}(으)로 즉시 되돌릴까요?` : ''}
        impact="회귀 평가를 기다리지 않고 현행 버전을 즉시 교체합니다. 되돌린 뒤 24시간 안에 회귀 평가를 사후 실행해 결과를 기록해야 합니다."
        reason="required"
        reauth
        error={modalError(emergency.error)}
        confirmLabel="긴급 롤백"
        pending={emergency.isPending}
        onConfirm={({ reason, password }) => {
          if (ask?.kind === 'emergency') {
            emergency.mutate({ version: ask.version.version, reason: reason ?? '', password: password ?? '' })
          }
        }}
        onCancel={closeAsk}
      />
    </div>
  )
}

/** 확인 모달 ③ 변경 대비 슬롯 — 무엇이 바뀌어 게시되는지 */
function PublishDiff({ draft }: { draft: PromptDraft }) {
  const changedPrinciples = draft.principles.filter((p) => p.dirty).length
  return (
    <Card title="변경 대비" wide>
      <ul className="space-y-1 text-xs text-muted-foreground">
        <li>
          시스템 프롬프트 : 원칙 {changedPrinciples}행 수정 · {draft.char_count}자
        </li>
        <li>
          가드레일 : 금칙어 {draft.blocklist.items.length}건 · 마스킹 {draft.masking.items.length}규칙
          {draft.dirty.guardrail ? ' (변경 있음)' : ' (변경 없음)'}
        </li>
        <li>
          버전 : {draft.base_version} → {draft.draft_version}
        </li>
      </ul>
    </Card>
  )
}
