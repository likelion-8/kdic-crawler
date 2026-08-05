/** AD-010 관리자 인증 · 권한 (Figma 446:944). `설정 > 보안·권한` 서브탭 · ADMIN 조회.
 *
 * 셸(GNB·헤더·서브탭)은 AdminLayout이 그린다 — 여기서 다시 그리지 않는다.
 * 카드 3개: ❶ 계정 · 세션 현황 ❷ 역할별 권한 매트릭스 ❸ 위험 작업 기록.
 * [계정 보기] · [내역 보기] 펼침은 '조작 후 상태' 목업이라 기본은 접어 둔다(Description 1).
 *
 * 목업 안 숫자(3명 · 6회 · 오늘 3건)는 예시다. 전부 API 응답으로 렌더한다. */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { Link } from 'react-router'
import { Badge, Button, buttonVariants, DataTable, EmptyState, Loading } from '../../../components/ui'
import type { Column } from '../../../components/ui'
import { cn } from '@/lib/utils'
import { formatTarget, formatTime } from '../../../lib/format'
import { useSession } from '../../../app/session'
import { AccountAddModal } from './access/AccountAddModal'
import { AccountsPanel } from './access/AccountsPanel'
import { ApiErrorBlock } from './access/ApiErrorBlock'
import { LoginFailuresPanel } from './access/LoginFailuresPanel'
import { accessKeys, fetchRiskyToday, fetchRoles, fetchSummary } from './access/api'
import type { RiskyOp, RoleDefinition } from './access/api'

export function AccessControl() {
  const { session } = useSession()
  // 계정 관리는 ADMIN 전용이다. 숨겨도 서버가 최종 판정이므로 403은 아래에서 그대로 처리한다
  const isAdmin = session?.role === 'ADMIN'
  const [accountsOpen, setAccountsOpen] = useState(false)
  const [failuresOpen, setFailuresOpen] = useState(false)
  const [addOpen, setAddOpen] = useState(false)

  const summary = useQuery({ queryKey: accessKeys.summary, queryFn: fetchSummary })
  const roles = useQuery({ queryKey: accessKeys.roles, queryFn: fetchRoles })
  const risky = useQuery({ queryKey: accessKeys.risky, queryFn: fetchRiskyToday })

  return (
    <div className="space-y-6">
      {/* ❶ 계정 · 세션 현황 */}
      <section className="rounded-md border bg-card p-5" aria-labelledby="access-sessions">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-[13px] font-semibold tracking-[-0.01em] text-foreground" id="access-sessions">
            계정 · 세션 현황
          </h2>
          {/* 모달은 roles 응답이 있어야 역할 셀렉트를 그린다(아래 `roles.data &&`).
              그 전에 눌리면 조용한 no-op이 되므로 사유와 함께 막는다 */}
          {isAdmin && (
            <Button
              size="sm"
              disabled={!roles.data}
              disabledReason={roles.data ? undefined : '역할 목록을 불러오는 중입니다'}
              onClick={() => setAddOpen(true)}
            >
              + 계정 추가
            </Button>
          )}
        </div>

        {summary.isPending && <Loading />}
        {summary.isError && <ApiErrorBlock error={summary.error} onRetry={() => void summary.refetch()} />}
        {summary.data && (
          <>
            {/* 펼치면 같은 바가 목록 머리가 된다 — 2-5 상태 바 `전체 계정 목록` / `3계정 · 접속 중 3` / `접기 ▴` */}
            <div className="mt-3 flex min-h-10 items-center gap-4 rounded-md bg-muted px-3 py-1">
              <span className="w-28 shrink-0 text-[13px] text-muted-foreground">
                {accountsOpen ? '전체 계정 목록' : '활성 세션'}
              </span>
              <span className="flex-1 text-sm font-medium text-foreground">
                {accountsOpen
                  ? `${summary.data.account_count}계정 · 접속 중 ${summary.data.active_sessions}`
                  : `${summary.data.active_sessions}명 접속 중`}
              </span>
              <PanelToggle
                open={accountsOpen}
                openLabel="계정 보기"
                // 접힘 상태에서는 대상 요소가 없다 — 끊긴 참조를 남기지 않는다
                controls="access-accounts"
                onToggle={() => setAccountsOpen((v) => !v)}
              />
            </div>
            {accountsOpen && (
              <div id="access-accounts">
                {roles.data ? <AccountsPanel roles={roles.data} /> : <Loading />}
              </div>
            )}

            {/* 실패·잠금은 주의 상태다. 색만이 아니라 라벨 문구로도 알린다 */}
            <div className="mt-3 flex min-h-10 items-center gap-4 rounded-md bg-warning-bg px-3 py-1">
              <span className="w-28 shrink-0 text-[13px] font-medium text-warning">오늘 로그인 실패</span>
              <span className="flex-1 text-sm font-medium text-warning">
                {failureSummaryText(summary.data.failures_today, summary.data.locked)}
              </span>
              <PanelToggle
                open={failuresOpen}
                openLabel="내역 보기"
                controls="access-failures"
                onToggle={() => setFailuresOpen((v) => !v)}
              />
            </div>
            {failuresOpen && (
              <div id="access-failures">
                <LoginFailuresPanel />
              </div>
            )}
          </>
        )}
      </section>

      {/* ❷ 역할별 권한 매트릭스 — 역할 코드값·설명은 서버(GET /api/admin/roles)가 정본이다 */}
      <section className="rounded-md border bg-card p-5" aria-labelledby="access-roles">
        <h2 className="mb-3 text-[13px] font-semibold tracking-[-0.01em] text-foreground" id="access-roles">
          역할별 권한 매트릭스
        </h2>
        {roles.isPending && <Loading />}
        {roles.isError && <ApiErrorBlock error={roles.error} onRetry={() => void roles.refetch()} />}
        {roles.data && <RoleMatrix roles={roles.data} myRole={session?.role} />}
      </section>

      {/* ❸ 위험 작업 기록 · 오늘 N건 */}
      <section className="rounded-md border bg-card p-5" aria-labelledby="access-risky">
        {/* 건수는 조회 결과다 — 로딩·실패 중에 '오늘 0건'이라고 단정하지 않는다 */}
        <h2 className="mb-3 text-[13px] font-semibold tracking-[-0.01em] text-foreground" id="access-risky">
          위험 작업 기록{risky.data ? ` · 오늘 ${risky.data.total}건` : ''}
        </h2>
        {risky.isPending && <Loading />}
        {risky.isError && <ApiErrorBlock error={risky.error} onRetry={() => void risky.refetch()} />}
        {risky.data && (
          <DataTable
            caption="오늘 실행된 위험 작업 — 시각 · 작업 · 대상 · 실행자 · 사유"
            columns={RISKY_COLUMNS}
            rows={risky.data.items}
            rowKey={(r) => r.id}
            actions={(r) => (
              // 이동이라 button이 아니라 Link다. 모양은 표 행 안 소형 Secondary 규칙을 따른다
              <Link
                className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'no-underline')}
                to={`/admin/settings/activity?event=${r.id}`}
              >
                상세
              </Link>
            )}
            empty={
              <EmptyState
                title="오늘 실행된 위험 작업이 없습니다"
                action={
                  <Link
                    className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'no-underline')}
                    to="/admin/settings/activity"
                  >
                    활동 로그 보기
                  </Link>
                }
              />
            }
          />
        )}
      </section>

      {roles.data && <AccountAddModal open={addOpen} roles={roles.data} onClose={() => setAddOpen(false)} />}
    </div>
  )
}

/** 상태 바 우측 펼침 토글 — 링크처럼 보이지만 동작은 버튼이다. 터치 타깃 44 이상(CM-DF-004 09절) */
function PanelToggle({
  open,
  openLabel,
  controls,
  onToggle,
}: {
  open: boolean
  openLabel: string
  controls: string
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      className="inline-flex min-h-11 items-center gap-1 rounded-sm px-1 text-[13px] font-bold text-primary transition-colors duration-200 hover:text-accent-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:outline-none"
      aria-expanded={open}
      aria-controls={open ? controls : undefined}
      onClick={onToggle}
    >
      {open ? '접기' : openLabel}
      {open ? (
        <ChevronUp className="size-3.5" aria-hidden="true" />
      ) : (
        <ChevronDown className="size-3.5" aria-hidden="true" />
      )}
    </button>
  )
}

/** 목업 문구 `6회 · 임시 잠금 1건 (operator@demo)` — 잠금이 없으면 회수만 쓴다 */
function failureSummaryText(count: number, locked: { email: string }[]): string {
  if (locked.length === 0) return `${count}회`
  return `${count}회 · 임시 잠금 ${locked.length}건 (${locked.map((l) => l.email).join(', ')})`
}

const RISKY_COLUMNS: Column<RiskyOp>[] = [
  { key: 'time', header: '시각', render: (r) => formatTime(r.occurred_at) },
  { key: 'action', header: '작업', render: (r) => r.action },
  // 대상은 '사람이 읽는 이름 + (ID)' — ID 단독 노출 금지(AD-011 Description 3)
  { key: 'target', header: '대상', render: (r) => (r.target_id ? formatTarget(r.target_name, r.target_id) : r.target_name) },
  { key: 'actor', header: '실행자', render: (r) => r.actor },
  // 사유는 확인 모달에서 받은 자유 입력(최대 200자)이다. DataTable의 td는 whitespace-nowrap이라
  // 길게 쓴 사유 하나가 표를 통째로 카드 밖으로 밀어낸다 — 목 데이터(11자)로는 안 보이는 결함이다.
  // 잘린 전문은 title로 남긴다(같은 리포 promptops/suggested.tsx와 동일 패턴)
  {
    key: 'reason',
    header: '사유',
    render: (r) => (
      <span className="block max-w-60 truncate" title={r.reason}>
        {r.reason}
      </span>
    ),
  },
]

/** 4역할 × 권한 설명. 내 역할 행은 보라 색면이 아니라 옅은 면 + 굵기로 강조하고(목업의 ADMIN 고정 강조 대체),
 * 색만으로 알리지 않도록 텍스트 배지로 함께 알린다(CM-DF-004 09절). */
function RoleMatrix({ roles, myRole }: { roles: RoleDefinition[]; myRole?: string }) {
  const columns: Column<RoleDefinition>[] = [
    {
      key: 'role',
      header: '역할',
      width: '18%',
      render: (r) => (
        <span className="inline-flex items-center gap-2">
          <b>{r.role}</b>
          {r.role === myRole && (
            <Badge tone="purple" kind="status">
              내 역할
            </Badge>
          )}
        </span>
      ),
    },
    { key: 'permission', header: '권한', render: (r) => r.description },
  ]
  return (
    <DataTable
      caption="역할별 권한 매트릭스 — 역할 · 권한"
      columns={columns}
      rows={roles}
      rowKey={(r) => r.role}
      rowState={(r) => (r.role === myRole ? 'selected' : 'default')}
    />
  )
}
