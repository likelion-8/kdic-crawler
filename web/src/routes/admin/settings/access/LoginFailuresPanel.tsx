/** AD-010 2-6 [내역 보기] 펼침 — 오늘 로그인 실패 내역(최근 4건).
 *
 * "사용자 화면에는 계정 존재 여부를 드러내지 않는 공통 오류 문구만 보여주고, 구분은 이 내역에만 남깁니다"(2-6 주석)
 * — '등록되지 않은 계정'은 이 표에서만 보인다. IP는 마스킹 상태로 서버가 준다(CM-DF-004 08절 30일 보관). */
import { useQuery } from '@tanstack/react-query'
import { ArrowRight } from 'lucide-react'
import { Link } from 'react-router'
import { DataTable, EmptyState, Loading } from '../../../../components/ui'
import type { Column } from '../../../../components/ui'
import { LOGIN_FAIL_LOCK_COUNT } from '../../../../lib/constants'
import { formatTime } from '../../../../lib/format'
import { ApiErrorBlock } from './ApiErrorBlock'
import { accessKeys, fetchLoginFailures } from './api'
import type { LoginFailure } from './api'

const columns: Column<LoginFailure>[] = [
  { key: 'time', header: '시각', render: (r) => formatTime(r.occurred_at) },
  { key: 'email', header: '시도 계정', render: (r) => r.email },
  { key: 'ip', header: 'IP', render: (r) => r.ip },
  { key: 'reason', header: '실패 사유', render: (r) => r.reason },
  {
    key: 'result',
    header: '결과',
    // 목업 문구 `5회 연속 → 임시 잠금 (09:47 해제)` — 5는 정책 상수, 시각은 KST 포맷터로 찍는다
    // 잠금 행은 rowState='danger'로 이미 구분된다 — 결과 문구에 색을 겹치지 않고 굵기로만 세운다
    render: (r) =>
      r.result === 'LOCKED' ? (
        <span className="font-medium">
          {LOGIN_FAIL_LOCK_COUNT}회 연속 → 임시 잠금{r.unlock_at ? ` (${formatTime(r.unlock_at)} 해제)` : ''}
        </span>
      ) : (
        '—'
      ),
  },
]

export function LoginFailuresPanel() {
  const failures = useQuery({ queryKey: accessKeys.failures, queryFn: fetchLoginFailures })

  if (failures.isPending) return <Loading />
  if (failures.isError) return <ApiErrorBlock error={failures.error} onRetry={() => void failures.refetch()} />

  return (
    <div className="mt-2">
      <DataTable
        caption="오늘 로그인 실패 내역 — 시각 · 시도 계정 · IP · 실패 사유 · 결과"
        columns={columns}
        rows={failures.data.items}
        rowKey={(r) => r.id}
        // 실패는 조치가 필요한 행이다. 잠금 건은 배경만이 아니라 결과 문구로도 알린다
        rowState={(r) => (r.result === 'LOCKED' ? 'danger' : 'default')}
        empty={<EmptyState title="오늘 기록된 로그인 실패가 없습니다" />}
      />
      {/* 이 표는 최근 4건만 준다 — 나머지는 활동 로그로 보낸다(문구는 기획서에 없어 프론트가 정함) */}
      <Link
        className="mt-2 inline-flex min-h-11 items-center gap-1 rounded-sm text-[13px] font-bold text-primary no-underline transition-colors duration-200 hover:text-accent-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:outline-none"
        to="/admin/settings/activity"
      >
        전체 내역 보기
        <ArrowRight className="size-3.5" aria-hidden="true" />
      </Link>
    </div>
  )
}
