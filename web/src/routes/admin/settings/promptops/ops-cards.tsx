/** AD-009 ① 사용량 제한 정책 · ② 질의 캐시 현황 · ③ 캐시 비우기 · ④ 차단 현황.
 * 문구는 기획서 13절 §3~§6 원문 그대로. ※로 시작하는 빨간 주석은 렌더하지 않는다(00-meta NOTATION). */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Ban, Database, Eraser, Gauge, ListChecks } from 'lucide-react'
import {
  Badge, Button, ColorText, DataTable, EmptyState, Loading, Pagination, Stepper, TextField, Toggle,
} from '../../../../components/ui'
import type { Column } from '../../../../components/ui'
import { DEFAULT_PAGE_SIZE } from '../../../../components/ui'
import { Checkbox } from '@/components/shadcn/checkbox'
import { cn } from '@/lib/utils'
import { formatDateTime, formatMonthDayTime, formatRemaining } from '../../../../lib/format'
import { QUERY_CACHE_TTL_H } from '../../../../lib/constants'
import { Card, SectionError } from './common'
import type { BlockEntry, CacheEntry, CacheStats, OpsPolicy } from './api'
import { fetchBlocks, fetchCacheEntries, opsKeys } from './api'

/** 기획서에 min/max/step이 없다(13절 M-9). 서버 검증 문구를 그대로 받으려면 상한을 넉넉히 둔다 */
const LIMIT_MIN = 1
const IP_MIN_MAX = 600
const IP_DAY_MAX = 100_000
const SESSION_MAX = 1_000
/** 초과 안내 문구 최대 길이 — 기획서 미정, 13절 M-9 제안값 60자 */
const OVER_LIMIT_MESSAGE_MAX = 60

// ---------------------------------------------------------------- ① 사용량 제한 정책

export interface UsageLimitCardProps {
  value: OpsPolicy
  /** 서버 현행값. 다르면 '현행 A → B' 대비 표기 + 빨간 점 */
  baseline: OpsPolicy
  canEdit: boolean
  onChange: (patch: Partial<OpsPolicy>) => void
}

export function UsageLimitCard({ value, baseline, canEdit, onChange }: UsageLimitCardProps) {
  const dirty =
    value.ip_per_min !== baseline.ip_per_min ||
    value.ip_per_day !== baseline.ip_per_day ||
    value.session_per_30min !== baseline.session_per_30min ||
    value.over_limit_message !== baseline.over_limit_message
  const notAllowed = canEdit ? undefined : '관리자(ADMIN)만 제한값을 바꿀 수 있습니다'

  return (
    <Card
      title="사용량 제한 정책"
      icon={<Gauge />}
      dirty={dirty}
      meta={<ColorText tone="green">승인 후 적용</ColorText>}
      // 편집 필드가 없는 값(burst)과 권한 조건은 규칙이다 — 카드 안에 문단으로 깔지 않는다.
      // burst는 서버 고정값이라 필드 자체를 두지 않는다(13절 H-4)
      hint={
        <>
          순간 요청(10초) {value.burst_per_10s}회는 서버 고정값이라 여기서 바꿀 수 없습니다. 사용량
          제한값과 자동 비우기 정책은 관리자(ADMIN)만 바꿀 수 있습니다.
        </>
      }
    >
      <div className="divide-y">
        <Stepper
          label="IP별 분당 요청"
          unit="회"
          value={value.ip_per_min}
          baseline={baseline.ip_per_min}
          min={LIMIT_MIN}
          max={IP_MIN_MAX}
          disabled={!canEdit}
          disabledReason={notAllowed}
          onChange={(ip_per_min) => onChange({ ip_per_min })}
        />
        <Stepper
          label="IP별 일일 요청"
          unit="회"
          value={value.ip_per_day}
          baseline={baseline.ip_per_day}
          min={LIMIT_MIN}
          max={IP_DAY_MAX}
          disabled={!canEdit}
          disabledReason={notAllowed}
          error={
            value.ip_per_day < value.ip_per_min ? '일일 요청은 분당 요청보다 크거나 같아야 합니다' : undefined
          }
          onChange={(ip_per_day) => onChange({ ip_per_day })}
        />
        <Stepper
          label="세션별 30분 요청"
          unit="회"
          value={value.session_per_30min}
          baseline={baseline.session_per_30min}
          min={LIMIT_MIN}
          max={SESSION_MAX}
          disabled={!canEdit}
          disabledReason={notAllowed}
          onChange={(session_per_30min) => onChange({ session_per_30min })}
        />
        <TextField
          label="초과 안내 문구"
          multiline
          value={value.over_limit_message}
          baseline={baseline.over_limit_message}
          maxLength={OVER_LIMIT_MESSAGE_MAX}
          placeholder="예: 잠시 후 다시 시도해 주세요."
          disabled={!canEdit}
          disabledReason={notAllowed}
          onChange={(over_limit_message) => onChange({ over_limit_message })}
        />
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------- ② 질의 캐시 현황

export function CacheStatsCard({ stats }: { stats: CacheStats }) {
  const percent = Math.round(stats.hit_rate * 100)
  return (
    <Card
      title="질의 캐시 현황"
      icon={<Database />}
      meta="동일 질의 매칭 (1차)"
      // '무엇이 캐시되는가'는 지금 수치가 아니라 규칙이다 — 카드에 문단으로 깔지 않고 ⓘ로 접는다.
      // 문구 근거는 서버 적재 조건(api/rag/sse.py 5-2)과 무효화 규칙(api/rag/answer.py _cache_versions)
      hint={
        <>
          아래 조건을 모두 만족한 답변만 {QUERY_CACHE_TTL_H}시간 저장합니다 — 하위 질문으로 나뉘지
          않은 단일 질문 · 정보성 질문(민원 처리 제외) · 오류 없이 생성된 답변 · 안내 범위 안 ·
          되묻기가 아닌 답변. 질문은 공백·말줄임·영문 대소문자를 맞춰 같은 질문으로 봅니다.
          색인·RAG 파라미터·프롬프트·모델 버전이 바뀌면 해당 캐시는 자동으로 무효화됩니다.
        </>
      }
    >
      {/* 숫자가 주인공 — 색이 아니라 크기·굵기로 세운다 */}
      <p className="mb-2 flex items-baseline gap-2">
        <strong className="text-2xl leading-tight font-bold tracking-tight tabular-nums">{percent}%</strong>
        <span className="text-xs text-muted-foreground">적중률 (최근 7일)</span>
      </p>
      {/* 값은 옆의 텍스트가 이미 읽히므로 막대는 장식으로 둔다 */}
      <div className="h-1.5 overflow-hidden rounded-[2px] bg-muted" aria-hidden="true">
        <span className="block h-full bg-primary" style={{ width: `${percent}%` }} />
      </div>
      <dl className="mt-4 grid grid-cols-3 gap-2">
        <div>
          <dt className="text-xs text-muted-foreground">절감한 생성 호출</dt>
          <dd className="mt-0.5 text-sm font-semibold tabular-nums">
            {stats.saved_generations.toLocaleString()}회
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">캐시 항목</dt>
          <dd className="mt-0.5 text-sm font-semibold tabular-nums">{stats.entries.toLocaleString()}건</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">확장 옵션</dt>
          {/* 시맨틱 캐시는 범위 밖이라 실측 지표와 같은 무게로 보이지 않게 회색 처리(13절 M-2) */}
          <dd
            className={cn(
              'mt-0.5 text-sm font-semibold',
              !stats.extension_applied && 'font-normal text-muted-foreground',
            )}
          >
            {stats.extension}
          </dd>
        </div>
      </dl>
    </Card>
  )
}

// ------------------------------------------------------- ②-2 캐시 항목 목록 (2026-08-20 신설)

export interface CacheEntriesCardProps {
  /** 비우기 대상. 페이지를 넘겨도 유지되도록 키가 아니라 항목 자체를 들고 있는다 */
  selected: CacheEntry[]
  onSelectedChange: (next: CacheEntry[]) => void
  canSelect: boolean
  onPurgeSelected: () => void
}

/** 무엇이 캐시돼 있는지 보여주고, 비울 것을 고르게 한다.
 * 종전에는 목록이 없어 '질의별 비우기'가 질의를 손으로 받아썼다 — 캐시에 없는 문장을 적어도
 * 화면은 성공으로 보였다(정규화가 어긋나면 0건 삭제). 고르는 대상을 눈으로 보게 바꿨다. */
export function CacheEntriesCard({
  selected, onSelectedChange, canSelect, onPurgeSelected,
}: CacheEntriesCardProps) {
  const [page, setPage] = useState(1)
  const query = useQuery({
    queryKey: [...opsKeys.cacheEntries, page],
    queryFn: () => fetchCacheEntries(page, DEFAULT_PAGE_SIZE),
  })

  const rows = query.data?.items ?? []
  const isSelected = (entry: CacheEntry) => selected.some((s) => s.cache_key === entry.cache_key)
  const toggle = (entry: CacheEntry) =>
    onSelectedChange(
      isSelected(entry)
        ? selected.filter((s) => s.cache_key !== entry.cache_key)
        : [...selected, entry],
    )
  // 전체 선택은 '보이는 페이지'까지만 — 안 보이는 행까지 지우는 조작은 [전체 비우기]가 따로 있다
  const allOnPage = rows.length > 0 && rows.every(isSelected)
  const toggleAll = () =>
    onSelectedChange(
      allOnPage
        ? selected.filter((s) => !rows.some((r) => r.cache_key === s.cache_key))
        : [...selected.filter((s) => !rows.some((r) => r.cache_key === s.cache_key)), ...rows],
    )

  const columns: Column<CacheEntry>[] = [
    {
      key: 'select',
      header: (
        <Checkbox
          checked={allOnPage}
          disabled={!canSelect || rows.length === 0}
          aria-label="이 페이지 전체 선택"
          onCheckedChange={toggleAll}
        />
      ),
      width: '44px',
      render: (entry) => (
        <Checkbox
          checked={isSelected(entry)}
          disabled={!canSelect}
          aria-label={`${entry.question} 선택`}
          onCheckedChange={() => toggle(entry)}
        />
      ),
    },
    { key: 'question', header: '질의', render: (entry) => entry.question },
    {
      key: 'hit_count',
      header: '적중',
      width: '80px',
      align: 'right',
      render: (entry) => <span className="nums">{entry.hit_count}회</span>,
    },
    {
      key: 'created_at',
      header: '저장',
      width: '110px',
      render: (entry) => <span className="nums">{formatMonthDayTime(entry.created_at)}</span>,
    },
    {
      key: 'expires_at',
      header: '남은 보관',
      width: '110px',
      // 만료 시각보다 '얼마나 남았나'가 비울지 말지를 가른다 — 곧 사라질 항목은 비울 필요가 없다
      render: (entry) =>
        entry.expires_at
          ? formatRemaining(new Date(entry.expires_at).getTime() - Date.now())
          : '만료 없음',
    },
  ]

  return (
    <Card
      title="캐시 항목"
      icon={<ListChecks />}
      wide
      meta={query.data ? `총 ${query.data.total.toLocaleString()}건` : undefined}
      // 대상을 고르는 표와 같은 카드에 둔다 — 고른 것과 지우는 버튼이 한눈에 들어와야 한다
      actions={
        <Button
          size="sm"
          disabled={!canSelect || selected.length === 0}
          disabledReason={
            !canSelect
              ? '운영자(OPERATOR) 이상만 비울 수 있습니다'
              : '표에서 비울 질의를 선택해 주세요'
          }
          onClick={onPurgeSelected}
        >
          질의별 비우기{selected.length > 0 && ` (${selected.length})`}
        </Button>
      }
    >
      {query.isPending ? (
        <Loading />
      ) : query.isError ? (
        <SectionError error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <DataTable
            caption="캐시된 질의 목록"
            columns={columns}
            rows={rows}
            rowKey={(entry) => entry.cache_key}
            rowState={(entry) => (isSelected(entry) ? 'selected' : 'default')}
            empty={<EmptyState title="캐시된 질의가 없습니다" />}
          />
          {query.data.total > DEFAULT_PAGE_SIZE && (
            <Pagination page={page} total={query.data.total} onPageChange={setPage} />
          )}
        </>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------- ③ 캐시 비우기

export interface CachePurgeCardProps {
  stats: CacheStats
  autoPurge: boolean
  autoPurgeBaseline: boolean
  canEditPolicy: boolean
  canPurgeAll: boolean
  onToggleAuto: (active: boolean) => void
  onPurgeAll: () => void
}

export function CachePurgeCard({
  stats,
  autoPurge,
  autoPurgeBaseline,
  canEditPolicy,
  canPurgeAll,
  onToggleAuto,
  onPurgeAll,
}: CachePurgeCardProps) {
  return (
    <Card title="캐시 비우기" icon={<Eraser />}>
      <Toggle
        label="자동 비우기"
        checked={autoPurge}
        baseline={autoPurgeBaseline ? 'On' : 'Off'}
        disabled={!canEditPolicy}
        disabledReason={canEditPolicy ? undefined : '관리자(ADMIN)만 바꿀 수 있습니다'}
        // '언제 자동으로 비우나'는 지금 상태(On/Off)가 아니라 규칙이다. 좁은 오른쪽 칸에서
        // 2~3줄로 감겨 토글과 아래 버튼 줄 사이를 벌린다 — 라벨 옆으로 접는다
        hint="인덱스·RAG·프롬프트·가드레일·모델 버전이 바뀌면 관련 캐시를 자동으로 비웁니다. Smoke 테스트를 통과한 뒤 새 캐시를 활성화합니다."
        onChange={onToggleAuto}
      />
      <p className="my-3 flex flex-wrap items-baseline gap-2 text-sm">
        <span className="text-xs text-muted-foreground">최근 비우기</span>
        <span>
          {formatDateTime(stats.last_purged_at)} ({stats.last_purge_reason})
        </span>
      </p>
      {/* Danger 버튼은 확인 모달 안에서만 쓴다(CM-DF-001 03절) — 여기서는 Secondary.
          [질의별 비우기]는 대상을 고르는 [캐시 항목] 카드로 옮겼다(2026-08-20) — 버튼과 대상이
          다른 카드에 떨어져 있으면 무엇이 지워질지 모른 채 누르게 된다 */}
      <Button
        size="sm"
        disabled={!canPurgeAll}
        disabledReason={canPurgeAll ? undefined : '관리자(ADMIN)만 전체를 비울 수 있습니다'}
        onClick={onPurgeAll}
      >
        전체 비우기
      </Button>
    </Card>
  )
}

// ---------------------------------------------------------------- ④ 차단 현황

export interface BlockListCardProps {
  canRelease: boolean
  onRelease: (block: BlockEntry) => void
}

export function BlockListCard({ canRelease, onRelease }: BlockListCardProps) {
  const [page, setPage] = useState(1)
  const query = useQuery({
    queryKey: [...opsKeys.blocks, page],
    queryFn: () => fetchBlocks(page, DEFAULT_PAGE_SIZE),
  })

  const columns: Column<BlockEntry>[] = [
    {
      key: 'subject',
      header: 'IP / 세션',
      width: '200px',
      render: (b) => (b.kind === '세션' ? `세션 ${b.subject}` : b.subject),
    },
    { key: 'reason', header: '사유', width: '150px', render: (b) => b.reason },
    { key: 'blocked_at', header: '차단 일시', width: '110px', render: (b) => <span className="nums">{formatMonthDayTime(b.blocked_at)}</span> },
    {
      key: 'count',
      header: '누적 차단',
      width: '100px',
      // 색만으로 알리지 않도록 누적 2회 이상은 글자로도 표시한다(CM-DF-004 09절)
      render: (b) =>
        b.count >= 2 ? <ColorText tone="red">{b.count}회 (반복)</ColorText> : `${b.count}회`,
    },
  ]

  return (
    <Card
      title="차단 현황"
      icon={<Ban />}
      wide
      meta={
        query.data ? (
          <Badge tone="red" kind="count">
            현재 {query.data.total}건
          </Badge>
        ) : undefined
      }
    >
      {query.isPending ? (
        <Loading />
      ) : query.isError ? (
        <SectionError error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <DataTable
            caption="임시 차단된 IP · 세션"
            columns={columns}
            rows={query.data.items}
            rowKey={(b) => b.id}
            rowState={(b) => (b.count >= 2 ? 'danger' : 'default')}
            empty={<EmptyState title="현재 차단된 IP·세션이 없습니다" />}
            actions={(b) => {
              const expired = new Date(b.expires_at).getTime() <= Date.now()
              return (
                <Button
                  size="sm"
                  disabled={!canRelease || expired}
                  disabledReason={
                    !canRelease
                      ? '운영자(OPERATOR) 이상만 해제할 수 있습니다'
                      : expired
                        ? '차단 시간이 끝나 해제할 필요가 없습니다'
                        : undefined
                  }
                  onClick={() => onRelease(b)}
                >
                  해제
                </Button>
              )
            }}
          />
          {query.data.total > DEFAULT_PAGE_SIZE && (
            <Pagination page={page} total={query.data.total} onPageChange={setPage} />
          )}
        </>
      )}
    </Card>
  )
}

/** 차단 해제 확인 모달의 영향 고지 — 대상·남은 시간·영향을 함께 보여준다(Description 4) */
export function BlockImpact({ block }: { block: BlockEntry }) {
  const remaining = new Date(block.expires_at).getTime() - Date.now()
  return (
    <>
      대상 {block.kind === '세션' ? `세션 ${block.subject}` : block.subject} · 사유 {block.reason} · 누적{' '}
      {block.count}회
      <br />
      {remaining > 0
        ? `남은 차단 시간 ${formatRemaining(remaining)}. 해제하면 이 대상의 요청이 곧바로 다시 허용됩니다.`
        : '이미 차단 시간이 끝난 항목입니다.'}
    </>
  )
}
