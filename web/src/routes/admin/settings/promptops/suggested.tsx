/** AD-009 ⑤ 추천 질문 관리 (기획서 13절 §7 · CM-DF-004 07절 REQ-OPS-004).
 *
 * 상단 [저장]의 초안 대상이 아니라 행 단위 즉시 반영이다(13절 H-1 제안 채택).
 * 저장 시 두 가지를 검증한다: 6대 업무 균형(경고 · 저장 가능) / 금칙어(차단).
 * 목록은 PUT으로 통째로 교체하는 계약이라(handlers/admin.ts) 조작마다 전체 목록을 보낸다. */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ArrowUp, MessageCircleQuestion } from 'lucide-react'
import {
  Button, ConfirmModal, DataTable, EmptyState, InfoHint, Loading, Notice, Select, TextField,
} from '../../../../components/ui'
import type { Column } from '../../../../components/ui'
import { Switch } from '../../../../components/shadcn/switch'
import { BUSINESS_FUNCTIONS } from '../../../../lib/codes'
import type { BusinessFunction } from '../../../../lib/codes'
import { Card, EditDialog, SectionError, linkClass } from './common'
import type { SuggestedQuestion } from './api'
import { fetchSuggestedQuestions, opsKeys, saveSuggestedQuestions, validateSuggestion } from './api'

/** CM-DF-004 부록 A — 등록 최대 15 · 활성 최대 10 (constants.ts에 없어 여기 둔다) */
const REGISTERED_MAX = 15
const ACTIVE_MAX = 10
/** 같은 업무가 이만큼 쌓이면 균형 경고(저장은 가능) */
const BALANCE_WARN = 3
/** 추가 모달 입력 상한 — placeholder 원문의 '최대 40자' */
const TEXT_MAX = 40

const OPTIONS = BUSINESS_FUNCTIONS.map((b) => ({ value: b, label: b }))

/** 상태 열 ⓘ 본문의 id — 상한에 걸려 잠긴 스위치가 aria-describedby로 가리킨다 */
const STATE_HINT_ID = 'suggested-state-hint'

interface FormState {
  id: string | null
  text: string
  business_function: BusinessFunction
}

export interface SuggestedQuestionsCardProps {
  canEdit: boolean
}

export function SuggestedQuestionsCard({ canEdit }: SuggestedQuestionsCardProps) {
  const qc = useQueryClient()
  const [collapsed, setCollapsed] = useState(false)
  const [form, setForm] = useState<FormState | null>(null)
  const [formError, setFormError] = useState('')
  const [checking, setChecking] = useState(false)
  const [removing, setRemoving] = useState<SuggestedQuestion | null>(null)

  const query = useQuery({ queryKey: opsKeys.suggestions, queryFn: fetchSuggestedQuestions })
  const save = useMutation({
    mutationFn: (input: { items: SuggestedQuestion[]; reason: string }) =>
      saveSuggestedQuestions(input.items, input.reason),
    onSuccess: (page) => {
      qc.setQueryData(opsKeys.suggestions, page)
      setForm(null)
      setRemoving(null)
    },
  })

  if (query.isPending) {
    return (
      <Card title="추천 질문" icon={<MessageCircleQuestion />} wide>
        <Loading />
      </Card>
    )
  }
  if (query.isError) {
    return (
      <Card title="추천 질문" icon={<MessageCircleQuestion />} wide>
        <SectionError error={query.error} onRetry={() => void query.refetch()} />
      </Card>
    )
  }

  const items = query.data.items
  const actives = items.filter((i) => i.active).sort((a, b) => a.order - b.order)
  const inactives = items.filter((i) => !i.active)
  const rows = [...actives, ...inactives]
  const activeFull = actives.length >= ACTIVE_MAX
  const registeredFull = items.length >= REGISTERED_MAX

  // 6대 업무 균형 — 활성 기준으로 같은 업무가 3건 이상이면 경고(저장은 가능)
  const perFunction = new Map<BusinessFunction, number>()
  for (const a of actives) perFunction.set(a.business_function, (perFunction.get(a.business_function) ?? 0) + 1)
  const overweight = [...perFunction.entries()].filter(([, n]) => n >= BALANCE_WARN)

  const commit = (next: SuggestedQuestion[], reason: string) => save.mutate({ items: next, reason })

  /** 활성 목록 안에서 순서를 옮긴다(드래그 대신 키보드로도 되는 버튼) */
  function move(item: SuggestedQuestion, delta: number) {
    const index = actives.findIndex((a) => a.id === item.id)
    const target = index + delta
    if (index < 0 || target < 0 || target >= actives.length) return
    const next = [...actives]
    next.splice(target, 0, next.splice(index, 1)[0])
    commit(
      [...next.map((a, i) => ({ ...a, order: i + 1 })), ...inactives],
      `추천 질문 순서 변경 : ${item.text}`,
    )
  }

  function toggleActive(item: SuggestedQuestion) {
    if (!item.active && activeFull) return
    commit(
      items.map((i) => (i.id === item.id ? { ...i, active: !i.active } : i)),
      `추천 질문 ${item.active ? '비활성' : '활성'} 전환 : ${item.text}`,
    )
  }

  async function submitForm() {
    if (!form) return
    setFormError('')
    setChecking(true)
    try {
      // 금칙어 미통과는 저장 차단(CM-DF-004 07절)
      const result = await validateSuggestion(form.text.trim(), form.business_function)
      if (!result.passed) {
        setFormError(result.message)
        return
      }
    } catch {
      setFormError('검증에 실패해 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.')
      return
    } finally {
      setChecking(false)
    }

    if (form.id) {
      commit(
        items.map((i) =>
          i.id === form.id ? { ...i, text: form.text.trim(), business_function: form.business_function } : i,
        ),
        `추천 질문 수정 : ${form.text.trim()}`,
      )
      return
    }
    // 활성 10개가 차 있으면 비활성으로 등록한다(13절 H-6)
    const created: SuggestedQuestion = {
      id: `sq_${Date.now()}`,
      text: form.text.trim(),
      business_function: form.business_function,
      active: !activeFull,
      order: actives.length + 1,
      click_count: 0,
    }
    commit([...items, created], `추천 질문 추가 : ${created.text}`)
  }

  const columns: Column<SuggestedQuestion>[] = [
    {
      key: 'no',
      header: '#',
      width: '40px',
      render: (q) => (q.active ? actives.findIndex((a) => a.id === q.id) + 1 : '—'),
    },
    { key: 'text', header: '문구', render: (q) => <span className="block max-w-85 truncate">{q.text}</span> },
    { key: 'business', header: '업무', width: '150px', render: (q) => q.business_function },
    {
      key: 'click',
      header: '최근 7일 클릭',
      width: '110px',
      align: 'right',
      // 백엔드는 7일 집계 경로가 없어 click_count 를 null 로 내린다(admin_ops.py:401) — 목은 0을 주므로 실백엔드에서만 터졌다
      render: (q) => (q.active ? (q.click_count?.toLocaleString() ?? '—') : '—'),
    },
    {
      key: 'state',
      header: (
        <span className="inline-flex items-center gap-0.5">
          상태
          {/* 활성 상한은 행마다 다른 사실이 아니라 화면 전체에 걸린 규칙이다. 행 안에 문장으로
              펼쳐 두면 상한에 걸린 행만 높아져 표가 들쭉날쭉해지고 셀이 넓어져 표가 밀린다 —
              열 이름 옆으로 접는다(사용자 지시) */}
          <InfoHint id={STATE_HINT_ID} label="활성 규칙 설명" size="sm">
            활성 질문만 챗봇 첫 화면에 노출됩니다(PC 세로 목록 최대 {ACTIVE_MAX}개, 모바일 상위 3개
            + [더보기]). 토글은 노출만 멈출 뿐 목록에서 지우지 않습니다. 활성은 최대 {ACTIVE_MAX}개라
            상한에 걸리면 비활성 질문을 켤 수 없고, 새로 추가한 질문도 비활성으로 등록됩니다.
          </InfoHint>
        </span>
      ),
      width: '112px',
      // 토글은 '조치'(편집·삭제)가 아니라 이 열에 둔다 — 값과 그 값을 바꾸는 스위치가 표 반대편으로
      // 떨어져 있으면 무엇을 켜고 끄는 건지 읽히지 않는다(사용자 지적).
      // 활성 여부는 색이 아니라 글자와 굵기로 알린다.
      render: (q) => (
        <span className="inline-flex items-center gap-2">
          <Switch
            checked={q.active}
            disabled={!canEdit || (!q.active && activeFull)}
            aria-label={`${q.text} ${q.active ? '비활성' : '활성'} 전환`}
            // 접혀 있어도 "왜 못 켜는지"는 읽혀야 한다 — 열 헤더 ⓘ의 본문을 가리킨다
            aria-describedby={!q.active && activeFull ? STATE_HINT_ID : undefined}
            onCheckedChange={() => toggleActive(q)}
          />
          {q.active ? <strong className="font-medium text-foreground">활성</strong> : '비활성'}
        </span>
      ),
    },
  ]

  return (
    <Card
      title="추천 질문"
      icon={<MessageCircleQuestion />}
      wide
      // 값만 남긴다 — 괄호 안 상한은 상태 열 ⓘ와 [+ 추가] 비활성 사유가 이미 말하는 규칙이라
      // 헤더까지 세 번 반복하면 제목·메타·버튼이 한 줄을 다투다 두 줄로 접힌다
      meta={`${items.length}개 등록 · 활성 ${actives.length}`}
      actions={
        <>
          <button type="button" className={linkClass} onClick={() => setCollapsed((v) => !v)}>
            {collapsed ? '펼치기 ▾' : '접기 ▴'}
          </button>
          <Button
            size="sm"
            disabled={!canEdit || registeredFull}
            disabledReason={
              !canEdit
                ? '편집자(EDITOR) 이상만 추가할 수 있습니다'
                : registeredFull
                  ? `등록은 최대 ${REGISTERED_MAX}개입니다. 기존 질문을 정리해 주세요`
                  : undefined
            }
            onClick={() => {
              setForm({ id: null, text: '', business_function: BUSINESS_FUNCTIONS[0] })
              setFormError('')
            }}
          >
            + 추가
          </Button>
        </>
      }
    >
      {!collapsed && (
        <>
          {overweight.length > 0 && (
            // 경고 UI가 기획서에 없어(13절 H-5) 그 절의 제안 문구를 그대로 썼다.
            // 저장을 막지 않는 카드 안 참고성 안내라 한 줄(inline)로 둔다
            <Notice tone="warning" variant="inline" className="mb-3">
              {overweight.map(([name, n]) => `${name} ${n}건`).join(' · ')}으로 편중되었습니다. 저장은
              가능하지만 업무를 고루 노출하는 것을 권장합니다
            </Notice>
          )}

          <SectionError error={save.error} />

          <DataTable
            caption="추천 질문 목록"
            columns={columns}
            rows={rows}
            rowKey={(q) => q.id}
            rowState={(q) => (q.active ? 'default' : 'disabled')}
            empty={<EmptyState title="등록된 추천 질문이 없습니다. [+ 추가]로 등록해 주세요" />}
            actionsHeader={
              <span className="inline-flex items-center gap-0.5">
                조치
                <InfoHint label="조작 방법 설명" size="sm">
                  순서는 [↑][↓] 버튼으로 바꿉니다. [삭제]는 확인 모달을 거쳐 목록에서
                  제거합니다.
                </InfoHint>
              </span>
            }
            actions={(q) => (
              <div className="flex items-center gap-1.5">
                <Button
                  size="sm"
                  disabled={!canEdit || !q.active || actives[0]?.id === q.id}
                  aria-label={`${q.text} 위로 이동`}
                  onClick={() => move(q, -1)}
                >
                  <ArrowUp aria-hidden="true" />
                </Button>
                <Button
                  size="sm"
                  disabled={!canEdit || !q.active || actives[actives.length - 1]?.id === q.id}
                  aria-label={`${q.text} 아래로 이동`}
                  onClick={() => move(q, 1)}
                >
                  <ArrowDown aria-hidden="true" />
                </Button>
                <Button
                  size="sm"
                  disabled={!canEdit}
                  onClick={() => {
                    setForm({ id: q.id, text: q.text, business_function: q.business_function })
                    setFormError('')
                  }}
                >
                  편집
                </Button>
                <Button size="sm" disabled={!canEdit} onClick={() => setRemoving(q)}>
                  삭제
                </Button>
              </div>
            )}
          />

        </>
      )}

      {form && (
        <EditDialog
          open
          title={form.id ? '추천 질문 편집' : '추천 질문 추가'}
          footer={
            <>
              <Button variant="secondary" onClick={() => setForm(null)} disabled={save.isPending}>
                취소
              </Button>
              <Button
                variant="primary"
                loading={checking || save.isPending}
                disabled={form.text.trim() === ''}
                disabledReason={form.text.trim() === '' ? '문구를 입력해 주세요' : undefined}
                onClick={() => void submitForm()}
              >
                {!form.id && activeFull ? '비활성으로 등록' : '저장'}
              </Button>
            </>
          }
          onClose={() => setForm(null)}
        >
          <TextField
            label="문구"
          grow
            value={form.text}
            maxLength={TEXT_MAX}
            placeholder="칩에 표시할 문구를 입력하세요 (권장 20자 이내 · 최대 40자)"
            onChange={(text) => setForm({ ...form, text })}
          />
          <Select
            label="업무"
            value={form.business_function}
            options={OPTIONS}
            onChange={(v) => setForm({ ...form, business_function: v as BusinessFunction })}
          />
          {/* 경고가 아니라 [비활성으로 등록] 버튼 라벨이 바뀐 이유를 설명하는 도우미 문구다 —
              폼 필드 바로 아래·푸터 버튼 옆에 붙여 원인과 결과를 잇는다 */}
          {!form.id && activeFull && (
            <Notice tone="warning" variant="inline" className="mt-2">
              활성 질문이 {ACTIVE_MAX}개로 가득 찼습니다. 비활성으로 등록됩니다
            </Notice>
          )}
          {formError && (
            <div className="mt-2" role="alert">
              <Notice tone="danger" variant="block">
                {formError}
              </Notice>
            </div>
          )}
          {/* 저장 실패는 모달 안에도 남긴다 — 뒤 카드의 오류는 모달에 가려 보이지 않는다 */}
          <SectionError error={save.error} />
        </EditDialog>
      )}

      <ConfirmModal
        open={removing !== null}
        variant="danger"
        title="이 추천 질문을 삭제할까요?"
        impact={
          removing
            ? `'${removing.text}'을(를) 목록에서 제거합니다. 복구하려면 다시 등록해야 합니다.`
            : ''
        }
        reason="required"
        confirmLabel="삭제"
        pending={save.isPending}
        onConfirm={({ reason }) => {
          if (removing) {
            commit(
              items.filter((i) => i.id !== removing.id),
              reason ?? '',
            )
          }
        }}
        onCancel={() => setRemoving(null)}
      />
    </Card>
  )
}
