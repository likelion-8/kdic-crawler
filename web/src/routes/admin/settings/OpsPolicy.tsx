/** AD-009 운영 정책 : 사용량 제한 · 질의 캐시 · 추천 질문 (KDIC-AD-PG-009).
 *
 * 상태 관리는 기획서 13절 H-1 제안대로 둘로 나눈다.
 *  - 초안(상단 [저장] 대상) : 사용량 제한값 · 초과 안내 문구 · 자동 비우기 토글
 *  - 즉시 반영 : 추천 질문 CRUD·활성 전환·순서, 캐시 비우기, 차단 해제
 * 위험 작업은 확인 모달(영향 고지 + 변경 대비 + 사유)을 거치고, 전체 캐시 비우기는
 * ADMIN 권한 + 비밀번호 재확인이 필요하다(§5 · CM-DF-004 03절).
 * 셸(GNB·헤더·설정 서브탭)은 AdminLayout이 그린다. ※ 빨간 주석은 렌더하지 않는다. */
import { useState } from 'react'
import { ReturnBand } from '@/components/admin/ReturnBand'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CARD_COLUMN, CARD_COLUMNS, ConfirmModal, DraftStatusBar, InfoHint, Loading, ReadOnlyNotice, useToast,
} from '../../../components/ui'
import { hasRole } from '../../../lib/codes'
import { QUERY_CACHE_TTL_H } from '../../../lib/constants'
import { needsReauth, useSession } from '../../../app/session'
import { Card, SectionError, modalError } from './promptops/common'
import {
  BlockImpact, BlockListCard, CacheEntriesCard, CachePurgeCard, CacheStatsCard, UsageLimitCard,
} from './promptops/ops-cards'
import { SuggestedQuestionsCard } from './promptops/suggested'
import type { BlockEntry, CacheEntry, OpsPolicy as OpsPolicyValue } from './promptops/api'
import {
  fetchCacheStats, fetchOpsPolicy, opsKeys, purgeCache, reauthenticate, releaseBlock, saveOpsPolicy,
} from './promptops/api'

/** 초안으로 관리하는 필드 — 상태 바의 '변경 N건'이 세는 대상 */
const DRAFT_FIELDS = ['ip_per_min', 'ip_per_day', 'session_per_30min', 'over_limit_message', 'auto_purge'] as const
type DraftField = (typeof DRAFT_FIELDS)[number]

const FIELD_LABEL: Record<DraftField, string> = {
  ip_per_min: 'IP별 분당 요청',
  ip_per_day: 'IP별 일일 요청',
  session_per_30min: '세션별 30분 요청',
  over_limit_message: '초과 안내 문구',
  auto_purge: '자동 비우기',
}

type Ask =
  | { kind: 'save' }
  | { kind: 'reset' }
  | { kind: 'purge-query' }
  | { kind: 'purge-all' }
  | { kind: 'release'; block: BlockEntry }

export function OpsPolicy() {
  const { session } = useSession()
  const role = session?.role ?? 'VIEWER'
  const canAdmin = hasRole(role, 'ADMIN')
  const canOperate = hasRole(role, 'OPERATOR')
  const canEditContent = hasRole(role, 'EDITOR')
  const qc = useQueryClient()
  const showToast = useToast()

  /** 서버 현행값 위에 덮어쓰는 초안. [초기화]는 이걸 비우기만 하면 된다(서버 호출 없음) */
  const [edits, setEdits] = useState<Partial<OpsPolicyValue>>({})
  const [ask, setAsk] = useState<Ask | null>(null)
  /** 캐시 항목 카드에서 고른 비우기 대상. 질의 원문을 확인 모달이 그대로 보여준다 */
  const [selectedEntries, setSelectedEntries] = useState<CacheEntry[]>([])

  const policyQuery = useQuery({ queryKey: opsKeys.policy, queryFn: fetchOpsPolicy })
  const cacheQuery = useQuery({ queryKey: opsKeys.cache, queryFn: fetchCacheStats })

  /** 닫을 때 직전 실패를 지운다 — 다음에 연 모달에 남의 오류가 남지 않도록 */
  const closeAsk = () => {
    setAsk(null)
    save.reset()
    purge.reset()
    release.reset()
  }

  const save = useMutation({
    // 제한값·자동 비우기 정책은 ADMIN + 비밀번호 재확인이 필수다(§2 Description 0)
    mutationFn: async (input: { patch: Partial<OpsPolicyValue>; reason: string; password?: string }) => {
      if (input.password) await reauthenticate(input.password)
      return saveOpsPolicy(input.patch, input.reason)
    },
    onSuccess: (next) => {
      qc.setQueryData(opsKeys.policy, next)
      setEdits({})
      closeAsk()
      showToast(`운영 정책을 저장했습니다 · ${next.version}`)
    },
  })

  const purge = useMutation({
    mutationFn: async (input: {
      scope: 'query' | 'all'
      reason: string
      cacheKeys?: string[]
      password?: string
    }) => {
      // 전체 비우기는 ADMIN + 비밀번호 재확인이 필수다(§5)
      if (input.password) await reauthenticate(input.password)
      return purgeCache(input.scope, input.reason, input.cacheKeys)
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: opsKeys.cache })
      // 목록도 함께 무효화하지 않으면 방금 지운 행이 표에 남는다
      void qc.invalidateQueries({ queryKey: opsKeys.cacheEntries })
      setSelectedEntries([])
      closeAsk()
      showToast('질의 캐시를 비웠습니다')
    },
  })

  const release = useMutation({
    mutationFn: (input: { id: string; reason: string }) => releaseBlock(input.id, input.reason),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: opsKeys.blocks })
      closeAsk()
      showToast('차단을 해제했습니다')
    },
  })

  if (policyQuery.isPending || cacheQuery.isPending) return <Loading />
  if (policyQuery.isError) {
    return <SectionError error={policyQuery.error} onRetry={() => void policyQuery.refetch()} />
  }
  if (cacheQuery.isError) {
    return <SectionError error={cacheQuery.error} onRetry={() => void cacheQuery.refetch()} />
  }

  const baseline = policyQuery.data
  const stats = cacheQuery.data
  const value: OpsPolicyValue = { ...baseline, ...edits }
  const changedFields = DRAFT_FIELDS.filter((f) => value[f] !== baseline[f])

  const onChange = (patch: Partial<OpsPolicyValue>) => setEdits({ ...edits, ...patch })

  return (
    <div className="flex flex-col gap-4">
      <ReturnBand />
      {/* 상태 바는 화면 최상단 sticky — 스크롤해도 변경 요약과 [저장]이 남는다 */}
      <div className="sticky top-0 z-20 -mx-6 -mt-6 bg-background px-6 pt-6 pb-1">
        <DraftStatusBar
          label={`운영 정책 ${baseline.version}`}
          changeCount={changedFields.length}
          hint="수정한 항목 이름 오른쪽 위에 빨간 점이 붙습니다. [저장]을 누르면 서버 검증을 거쳐 적용됩니다."
          primaryLabel="저장"
          pending={save.isPending}
          onPrimary={() => {
            if (canAdmin && changedFields.length > 0) setAsk({ kind: 'save' })
          }}
          // 편집분이 있으면 확인을 받는다 — 같은 [초기화]인데 AD-007만 확인하고
          // 여기선 여러 항목이 경고 없이 날아가던 불일치를 맞췄다
          onReset={() => {
            if (changedFields.length > 0) setAsk({ kind: 'reset' })
          }}
        />
      </div>

      {/* 권한 안내는 화면에서 한 번만 한다 — 컨트롤마다 같은 문장을 달면 그 말로 화면이 뒤덮인다.
          상태바(sticky)는 -mt-6로 위를 덮으므로 반드시 그 **아래**에 둔다(실측: 문구 절반이 잘렸다) */}
      {!canOperate && <ReadOnlyNotice need="운영자(OPERATOR) 이상" action="이 화면의 값을 바꾸려면" />}


      <div className={CARD_COLUMNS}>
        <div className={CARD_COLUMN}>
          <UsageLimitCard value={value} baseline={baseline} canEdit={canAdmin} onChange={onChange} />
        </div>
        <div className={CARD_COLUMN}>
          <CacheStatsCard stats={stats} />
          <CachePurgeCard
            stats={stats}
            autoPurge={value.auto_purge}
            autoPurgeBaseline={baseline.auto_purge}
            canEditPolicy={canAdmin}
            canPurgeAll={canAdmin}
            onToggleAuto={(auto_purge) => onChange({ auto_purge })}
            onPurgeAll={() => setAsk({ kind: 'purge-all' })}
          />
        </div>
      </div>

      <CacheEntriesCard
        selected={selectedEntries}
        onSelectedChange={setSelectedEntries}
        canSelect={canOperate}
        onPurgeSelected={() => setAsk({ kind: 'purge-query' })}
      />

      <BlockListCard canRelease={canOperate} onRelease={(block) => setAsk({ kind: 'release', block })} />

      <SuggestedQuestionsCard canEdit={canEditContent} />

      {/* 앞부분 수치는 바로 위 '사용량 제한 정책' 카드의 값과 같은 것을 되풀이한 것이고, 뒤는
          보관 정책 부연이다. 어느 카드 설명인지도 읽히지 않은 채 화면 끝만 늘렸다 —
          운영에 떠 있는 현행값은 각 필드의 '현행 N' 표기가 이미 말한다. 보관 정책만 남겨 접는다 */}
      <p className="text-xs text-muted-foreground">
        정책 버전 {baseline.version}
        <InfoHint label="정책 변경 이력 보관 설명" size="sm">
          제한값을 바꾸면 변경자·사유·결과가 관리자 활동 로그(AD-011)에 90일간 보관됩니다.
        </InfoHint>
      </p>

      {/* [초기화] — 서버를 건드리지 않고 편집분만 버린다. AD-007의 같은 버튼과 문구·구조를 맞췄다.
          사유는 받지 않는다: 운영에 반영되지 않은 로컬 편집이라 감사 대상이 아니다 */}
      <ConfirmModal
        open={ask?.kind === 'reset'}
        title="편집 중인 초안을 버릴까요?"
        impact={
          <p>
            변경 {changedFields.length}건이 사라지고 현행 운영값으로 돌아갑니다. 운영 설정은 바뀌지
            않습니다.
          </p>
        }
        confirmLabel="초기화"
        onConfirm={() => {
          setEdits({})
          closeAsk()
        }}
        onCancel={closeAsk}
      />

      <ConfirmModal
        open={ask?.kind === 'save'}
        title="운영 정책을 저장할까요?"
        impact="서버 검증을 거쳐 순차 적용되며 정책 버전이 올라갑니다. 실패하면 이전 정책이 그대로 유지됩니다."
        diff={
          <Card title="변경 대비" wide>
            <ul className="space-y-1 text-xs text-muted-foreground">
              {changedFields.map((f) => (
                <li key={f}>
                  {FIELD_LABEL[f]} : {String(baseline[f])} → {String(value[f])}
                </li>
              ))}
            </ul>
          </Card>
        }
        reason="required"
        reauth={session ? needsReauth(session) : false}
        error={modalError(save.error)}
        confirmLabel="저장"
        pending={save.isPending}
        onConfirm={({ reason, password }) => {
          const patch: Partial<OpsPolicyValue> = {}
          for (const f of changedFields) Object.assign(patch, { [f]: value[f] })
          save.mutate({ patch, reason: reason ?? '', password })
        }}
        onCancel={closeAsk}
      />

      <ConfirmModal
        open={ask?.kind === 'purge-query'}
        title={`선택한 질의 ${selectedEntries.length}건의 캐시를 비울까요?`}
        // 대상은 [캐시 항목] 카드에서 고른다(2026-08-20 §4 신설 — 종전에는 여기서 질의를 손으로
        // 받아써서, 캐시에 없는 문장을 적어도 0건 삭제가 성공으로 보였다)
        impact={
          <>
            비운 질의는 다음 요청부터 답변을 새로 생성합니다. 보관 기간은 {QUERY_CACHE_TTL_H}시간입니다.
            <ul className="mt-2 max-h-40 space-y-1 overflow-auto text-xs text-muted-foreground">
              {selectedEntries.map((entry) => (
                <li key={entry.cache_key}>
                  {entry.question} · 적중 {entry.hit_count}회
                </li>
              ))}
            </ul>
          </>
        }
        reason="required"
        // 대상 확인 + 사유 필수(§5 Description 3) — 대상이 비면 실행 자체를 막는다
        confirmDisabled={selectedEntries.length === 0}
        confirmDisabledReason="비울 캐시 항목을 선택해 주세요"
        error={modalError(purge.error)}
        confirmLabel="비우기"
        pending={purge.isPending}
        onConfirm={({ reason }) =>
          purge.mutate({
            scope: 'query',
            reason: reason ?? '',
            cacheKeys: selectedEntries.map((entry) => entry.cache_key),
          })
        }
        onCancel={closeAsk}
      />

      <ConfirmModal
        open={ask?.kind === 'purge-all'}
        variant="danger"
        title="질의 캐시를 전부 비울까요?"
        impact={`캐시 항목 ${stats.entries.toLocaleString()}건이 모두 사라집니다. 되돌릴 수 없고, 다시 채워질 때까지 생성 호출과 응답시간이 늘어납니다(최근 7일 적중률 ${Math.round(stats.hit_rate * 100)}% · 절감한 생성 호출 ${stats.saved_generations.toLocaleString()}회 기준).`}
        reason="required"
        reauth
        error={modalError(purge.error)}
        confirmLabel="전체 비우기"
        pending={purge.isPending}
        onConfirm={({ reason, password }) =>
          purge.mutate({ scope: 'all', reason: reason ?? '', password: password ?? '' })
        }
        onCancel={closeAsk}
      />

      <ConfirmModal
        open={ask?.kind === 'release'}
        title="이 차단을 해제할까요?"
        impact={ask?.kind === 'release' ? <BlockImpact block={ask.block} /> : ''}
        reason="required"
        error={modalError(release.error)}
        confirmLabel="해제"
        pending={release.isPending}
        onConfirm={({ reason }) => {
          if (ask?.kind === 'release') release.mutate({ id: ask.block.id, reason: reason ?? '' })
        }}
        onCancel={closeAsk}
      />
    </div>
  )
}
