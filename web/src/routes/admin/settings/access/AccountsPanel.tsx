/** AD-010 2-5 [계정 보기] 펼침 — 전체 계정 목록 + 행 액션([역할 변경] · [비활성화]).
 *
 * "초대됨 · 비활성 계정도 이 목록에 표시되며, 모든 변경은 AD-011에 기록됩니다"(2-5 주석).
 * 안전 규칙(자기 강등 금지 · 마지막 ADMIN 보호)은 버튼을 숨기지 않고 비활성 + 사유로 알린다
 * (CM-DF-001 03절 규칙 3 · 08 issue 17). */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Button,
  ConfirmModal,
  DataTable,
  DEFAULT_PAGE_SIZE,
  InfoHint,
  Loading,
  Pagination,
  Select,
  useToast,
} from '../../../../components/ui'
import type { Column } from '../../../../components/ui'
import type { Role } from '../../../../lib/codes'
import { formatDate, formatTarget, formatTime } from '../../../../lib/format'
import { needsReauth, useSession } from '../../../../app/session'
import { ApiErrorBlock } from './ApiErrorBlock'
import { accessKeys, fetchAccounts, patchAccount, runRisky } from './api'
import type { AccountRow, RoleDefinition } from './api'

export interface AccountsPanelProps {
  /** GET /api/admin/roles 결과 — 역할 셀렉트 라벨을 여기서 가져온다(화면이 코드값을 지어내지 않는다) */
  roles: RoleDefinition[]
}

type Pending = { row: AccountRow; mode: 'role' | 'disable' }

export function AccountsPanel({ roles }: AccountsPanelProps) {
  const { session } = useSession()
  const queryClient = useQueryClient()
  const showToast = useToast()
  const [page, setPage] = useState(1)
  const [pending, setPending] = useState<Pending | null>(null)
  const [nextRole, setNextRole] = useState<Role>('VIEWER')

  const accounts = useQuery({
    queryKey: [...accessKeys.accounts, page],
    queryFn: () => fetchAccounts(page),
  })

  const change = useMutation({
    mutationFn: ({ row, mode, reason, password }: Pending & { reason: string; password?: string }) =>
      // 역할 변경 · 비활성화 모두 '권한 변경' 이벤트로 AD-011에 남는다(2-7 주석)
      runRisky(password, () =>
        patchAccount(row.id, mode === 'role' ? { role: nextRole } : { status: '비활성' }, reason),
      ),
    onSuccess: (_data, variables) => {
      showToast(variables.mode === 'role' ? '역할을 변경했습니다' : '계정을 비활성화했습니다')
      setPending(null)
      void queryClient.invalidateQueries({ queryKey: accessKeys.accounts })
      void queryClient.invalidateQueries({ queryKey: accessKeys.summary })
    },
  })

  if (accounts.isPending) return <Loading />
  if (accounts.isError)
    return <ApiErrorBlock error={accounts.error} onRetry={() => void accounts.refetch()} />

  const rows = accounts.data.items
  const openRoleChange = (row: AccountRow) => {
    // 셀렉트에서 현재 역할을 빼면 '바꾸지 않고 실행'이 아예 불가능해진다
    setNextRole(roles.find((r) => r.role !== row.role)?.role ?? 'VIEWER')
    change.reset()
    setPending({ row, mode: 'role' })
  }

  const columns: Column<AccountRow>[] = [
    // 대상 표기는 '사람이 읽는 이름 + (ID)' — ID 단독 노출 금지(PRD-02 §3-f)
    {
      key: 'account',
      header: '계정',
      render: (r) => <b>{formatTarget(r.name, r.email)}</b>,
    },
    // 역할은 데이터지 상태가 아니다 — 색을 입히지 않는다(보라는 Primary·링크·포커스·현재 위치에만)
    { key: 'role', header: '역할', render: (r) => r.role },
    {
      key: 'login',
      header: '로그인',
      render: (r) => (r.last_login_at ? formatTime(r.last_login_at) : '—'),
    },
    // '마지막 활동'은 목업 값이 `방금 전`·`3분 전`·`21분 전`인 상대 시각이다 — 시:분으로 찍으면
    // 바로 왼쪽 '로그인' 열과 같은 모양이 돼 '얼마나 지났나'가 사라진다(검증 D025)
    {
      key: 'activity',
      header: '마지막 활동',
      render: (r) => (r.last_activity_at ? sinceText(r.last_activity_at) : '—'),
    },
    { key: 'status', header: '상태', render: (r) => statusCell(r) },
  ]

  return (
    <div className="mt-2">
      <DataTable
        caption="전체 계정 목록 — 계정 · 역할 · 로그인 · 마지막 활동 · 상태 · 조치"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        actionsHeader={
          <span className="inline-flex items-center gap-0.5">
            조치
            {/* 잠금 규칙 3종은 어느 행에도 매인 사실이 아니다. 행 안에 문장으로 펼치면 사유가
                붙은 행만 2~3줄로 부풀고 250px짜리 문장이 열을 넓혀 표를 밀어낸다.
                내 계정 행은 항상 목록에 있어 이 깨짐이 상시였다 — 열 이름 옆으로 접는다 */}
            <InfoHint label="조치 잠금 규칙 설명" size="sm">
              내 계정은 스스로 강등·비활성화할 수 없고, 마지막 남은 ADMIN도 마찬가지입니다. 이미
              비활성인 계정은 다시 비활성화할 수 없습니다.
            </InfoHint>
          </span>
        }
        actions={(r) => {
          const blocked = blockedReason(r)
          const disabledFor = blocked ?? (r.status === '비활성' ? '이미 비활성 계정입니다' : undefined)
          // 규칙은 열 헤더 ⓘ에 접었지만, **어느 행이 왜 잠겼는지**는 행마다 다르다.
          // 화면에는 두지 않고 sr-only로만 남겨 두 버튼이 aria-describedby로 가리킨다(검증 D075).
          // 레이아웃을 차지하지 않으므로 표가 다시 밀리지 않는다.
          const reasonId = `acc-reason-${r.id}`
          return (
            <span className="inline-flex items-center gap-1.5">
              {disabledFor && (
                <span className="sr-only" id={reasonId}>
                  {disabledFor}
                </span>
              )}
              <Button
                size="sm"
                disabled={blocked !== undefined}
                aria-describedby={blocked ? reasonId : undefined}
                onClick={() => openRoleChange(r)}
              >
                역할 변경
              </Button>
              <Button
                size="sm"
                disabled={blocked !== undefined || r.status === '비활성'}
                aria-describedby={disabledFor ? reasonId : undefined}
                onClick={() => {
                  change.reset()
                  setPending({ row: r, mode: 'disable' })
                }}
              >
                비활성화
              </Button>
            </span>
          )
        }}
      />

      {accounts.data.total > DEFAULT_PAGE_SIZE && (
        <Pagination page={page} total={accounts.data.total} onPageChange={setPage} />
      )}

      {pending && (
        <ConfirmModal
          open
          variant={pending.mode === 'disable' ? 'danger' : 'normal'}
          title={pending.mode === 'role' ? '역할을 변경할까요?' : '계정을 비활성화할까요?'}
          impact={
            <div className="space-y-3">
              <p className="font-bold text-foreground">
                대상 {formatTarget(pending.row.name, pending.row.email)}
              </p>
              {/* Description 2 안전 규칙 원문 */}
              <p>
                변경이 반영되는 즉시 대상 계정의 활성 세션을 종료해, 이전 권한으로 계속 작업하지 못하게
                합니다.
              </p>
              {pending.mode === 'role' && (
                <Select
                  label="역할"
                  value={nextRole}
                  onChange={(v) => setNextRole(v as Role)}
                  options={roles
                    .filter((r) => r.role !== pending.row.role)
                    .map((r) => ({
                      value: r.role,
                      label: `${r.role} (${r.label})`,
                    }))}
                />
              )}
              {change.isError && <ApiErrorBlock error={change.error} />}
            </div>
          }
          diff={
            pending.mode === 'role' ? (
              <p>
                현행 {pending.row.role} → {nextRole}
              </p>
            ) : (
              <p>현행 {pending.row.status} → 비활성</p>
            )
          }
          reason="required"
          reasonPlaceholder="예: 담당 교체"
          // 마지막 인증 후 30분이 지났으면 비밀번호를 다시 확인한다 — 헤더 [연장]으로는 면제되지 않는다(2-3 주석)
          reauth={session ? needsReauth(session) : true}
          confirmLabel={pending.mode === 'role' ? '역할 변경' : '비활성화'}
          pending={change.isPending}
          onConfirm={({ reason, password }) =>
            change.mutate({
              row: pending.row,
              mode: pending.mode,
              reason: reason ?? '',
              password,
            })
          }
          onCancel={() => setPending(null)}
        />
      )}
    </div>
  )
}

/** `방금 전` / `3분 전` / `21분 전` — 2-5 '마지막 활동' 열 표기.
 * lib/format.ts에는 상대 시각 포맷터가 없고 쓰는 화면도 여기뿐이라 이 화면에 둔다.
 * 하루를 넘기면 상대 표기가 오히려 안 읽혀 날짜로 떨어뜨린다(기획서에 없는 구간 — 프론트가 정함). */
function sinceText(iso: string): string {
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000)
  if (!Number.isFinite(min) || min < 0) return formatTime(iso)
  if (min < 1) return '방금 전'
  if (min < 60) return `${min}분 전`
  if (min < 24 * 60) return `${Math.floor(min / 60)}시간 전`
  return formatDate(iso)
}

/** 계정 상태와 세션 상태를 한 칸에 섞지 않는다 — 계정 상태가 있으면 그걸 먼저 쓴다(08 issue 18).
 * 색만으로 알리지 않도록 항상 텍스트로 쓴다(CM-DF-004 09절). */
function statusCell(row: AccountRow) {
  if (row.session === 'CURRENT') return <span className="font-medium text-foreground">현재 내 세션</span>
  if (row.status !== '활성') return row.status
  if (row.session === 'ACTIVE' && row.session_idle_expires_in_s !== null) {
    return <span className="nums">유휴 만료 {Math.ceil(row.session_idle_expires_in_s / 60)}분 전</span>
  }
  return '—'
}

/** 왜 못 바꾸는지. 문구는 기획서에 없어(08 issue 17) 안전 규칙 원문을 줄여 썼다 */
function blockedReason(row: AccountRow): string | undefined {
  if (row.is_self) return '자기 자신은 강등·비활성화할 수 없습니다'
  if (row.is_last_admin) return '마지막 남은 ADMIN은 강등·비활성화할 수 없습니다'
  return undefined
}
