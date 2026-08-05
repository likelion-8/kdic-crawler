/** AD-010 2-7 [+ 계정 추가] — 관리자 계정 생성 (ADMIN 전용 · 사유 필수).
 *
 * 목업은 전용 모달이지만 위험 작업 3단 플로우(영향 고지 → 사유 필수 → 필요 시 비밀번호 재확인)가
 * 그대로 필요해 공통 ConfirmModal의 슬롯에 폼을 얹었다. 새 모달을 만들지 않는다(CM-DF-001 머리말).
 * 사유 라벨은 화면별 원문이 다르므로 공통 모달의 reasonLabel로 넘긴다(목업 `생성 사유 (필수)`). */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ConfirmModal, Select, TextField, useToast } from '../../../../components/ui'
import type { Role } from '../../../../lib/codes'
import { RESET_TOKEN_MIN } from '../../../../lib/constants'
import { needsReauth, useSession } from '../../../../app/session'
import { ApiErrorBlock } from './ApiErrorBlock'
import { accessKeys, createAccount, runRisky } from './api'
import type { RoleDefinition } from './api'

export interface AccountAddModalProps {
  open: boolean
  roles: RoleDefinition[]
  onClose: () => void
}

export function AccountAddModal({ open, roles, onClose }: AccountAddModalProps) {
  const { session } = useSession()
  const queryClient = useQueryClient()
  const showToast = useToast()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  // 역할은 생성 시 1개를 지정하며 기본값은 최소 권한이다(2-7 목업 기본값 `VIEWER (조회 전용)`)
  const [role, setRole] = useState<Role>('VIEWER')

  const create = useMutation({
    mutationFn: ({ reason, password }: { reason: string; password?: string }) =>
      runRisky(password, () => createAccount({ name: name.trim(), email: email.trim(), role }, reason)),
    onSuccess: () => {
      showToast('계정을 생성했습니다')
      void queryClient.invalidateQueries({ queryKey: accessKeys.accounts })
      void queryClient.invalidateQueries({ queryKey: accessKeys.summary })
      close()
    },
  })

  /** 성공이든 취소든 닫을 때 폼을 비운다 — 사유·비밀번호는 공통 모달이 열 때마다 지우므로 기준을 맞춘다 */
  function close() {
    setName('')
    setEmail('')
    setRole('VIEWER')
    create.reset()
    onClose()
  }

  // "입력 미완료는 버튼 비활성"(1-3 · 전 인증 화면 공통 원칙) — 빈 폼을 보내 서버 400을 받게 두지 않는다.
  // 이메일 형식 검증 문구는 기획서 미정(08 issue 3)이라 공백만 막고 형식은 서버 판정에 맡긴다
  const incomplete = name.trim() === '' || email.trim() === ''

  return (
    <ConfirmModal
      open={open}
      title="관리자 계정 생성"
      impact={
        <div className="space-y-1">
          <TextField grow label="이름" value={name} onChange={setName} placeholder="홍길동" />
          <TextField
            grow
            label="이메일 (로그인 계정)"
            value={email}
            onChange={setEmail}
            placeholder="gildong@kdic.or.kr"
          />
          <Select
            label="역할"
            value={role}
            onChange={(v) => setRole(v as Role)}
            options={roles.map((r) => ({ value: r.role, label: `${r.role} (${r.label})` }))}
          />
          {/* 목업 안내 2줄 원문(회색 문구 = 노출 대상). 링크 유효 시간은 상수에서 가져온다.
              '72시간 내 미설정 시 초대 만료'는 빨간 ※ 주석이라 화면에 넣지 않는다 */}
          <p className="pt-1 text-xs text-muted-foreground">
            비밀번호는 여기서 정하지 않습니다. 생성 시 초기 설정 메일이 발송되어 본인이 직접 설정합니다 (링크{' '}
            {RESET_TOKEN_MIN}분 · 1회)
          </p>
          {create.isError && <ApiErrorBlock error={create.error} />}
        </div>
      }
      reason="required"
      reasonLabel="생성 사유"
      reasonPlaceholder="예: 운영 인력 합류, 대화 로그 모니터링 담당"
      confirmDisabled={incomplete}
      confirmDisabledReason="이름과 이메일을 입력해 주세요"
      // ADMIN 전용 · 마지막 인증 후 30분이 지났으면 비밀번호 재확인(2-7 주석)
      reauth={session ? needsReauth(session) : true}
      confirmLabel="생성"
      pending={create.isPending}
      onConfirm={({ reason, password }) => create.mutate({ reason: reason ?? '', password })}
      onCancel={close}
    />
  )
}
