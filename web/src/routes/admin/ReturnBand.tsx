/**
 * 되돌아가기 띠 — 대화 로그 상세의 [다음 조치]로 넘어온 화면 상단에 뜬다(2026-08-18).
 *
 * 관리자 유저플로우 설계에서 새로 만든 **유일한** 컴포넌트다. 화면은 관리 대상별로 나뉘고
 * 흐름은 작업별이라, 화면을 넘어갈 때 "어디서 왜 왔는지"가 사라진다. 이 띠가 그 맥락(바통)을
 * 목적지에 남기고, 여기서 [처리 완료]를 눌러도 원래 로그의 처리 상태가 바뀌어 대시보드
 * 할 일 건수가 줄어든다 — 돌아오지 않아도 루프가 닫힌다.
 *
 * `?from=log:{request_id}` 가 있을 때만 그린다. 바통은 URL 쿼리뿐이다 — 저장소 기반이면
 * 새 탭·링크 공유에서 끊긴다. AD-002 · AD-007 · AD-008 · AD-009 가 같은 것을 쓴다.
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router'
import { Button, ConfirmModal, Notice, useToast } from '../../components/ui'
import { setLogTriage } from './logs/api'

/** ?from=log:{id} 를 읽는다. 없으면 null — 띠를 그리지 않는다 */
export function useReturnFrom(): { requestId: string } | null {
  const [sp] = useSearchParams()
  const from = sp.get('from') ?? ''
  return from.startsWith('log:') && from.length > 4 ? { requestId: from.slice(4) } : null
}

export function ReturnBand({ note }: { note?: string }) {
  const from = useReturnFrom()
  const showToast = useToast()
  const [resolving, setResolving] = useState(false)
  const [done, setDone] = useState(false)
  const resolve = useMutation({
    mutationFn: (reason: string) => setLogTriage(from!.requestId, 'RESOLVED', reason),
    onSuccess: () => {
      setResolving(false)
      setDone(true)
      showToast('대화 로그를 처리 완료로 표시했습니다 · 대시보드 할 일에서 빠집니다')
    },
  })
  if (!from) return null
  const short = from.requestId.length > 12
    ? `${from.requestId.slice(0, 4)}…${from.requestId.slice(-4)}`
    : from.requestId
  return (
    <>
      <Notice
        tone="info"
        variant="inline"
        className="mb-3"
        action={
          <span className="flex items-center gap-2">
            {!done && (
              <Button size="sm" onClick={() => setResolving(true)}>
                처리 완료로 표시
              </Button>
            )}
            <Link className="text-[13px] underline" to={`/admin/logs?period=30d&request=${encodeURIComponent(from.requestId)}`}>
              로그로 돌아가기
            </Link>
          </span>
        }
      >
        대화 로그 <span className="font-mono">{short}</span> 에서 넘어왔습니다
        {done ? ' · 처리 완료' : ''}
        {note ? ` · ${note}` : ''}
      </Notice>
      <ConfirmModal
        open={resolving}
        title="이 대화를 처리 완료로 표시할까요?"
        impact="원래 대화 로그의 처리 상태가 '처리 완료'로 바뀌고 대시보드 미처리 건수에서 빠집니다. 되돌리려면 로그 상세에서 상태를 다시 바꿉니다."
        reason="required"
        reasonPlaceholder="예: 검색 설정 조정 반영 · 답변 매핑 등록"
        confirmLabel="처리 완료"
        pending={resolve.isPending}
        onConfirm={({ reason }) => resolve.mutate(reason ?? '')}
        onCancel={() => setResolving(false)}
      />
    </>
  )
}
