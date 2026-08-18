/** AD-009 답변 매핑 — 미리 작성한 답변에 질문 문구들을 매핑한다(2026-08-14 신설).
 *
 * 추천 질문 카드와 같은 계약(전량 교체 PUT · 행 단위 즉시 반영)이다. 정규화 키가 정확히
 * 일치하는 첫 턴 질문에 LLM 없이 이 답변이 그대로 나간다 — 추천 질문 문구를 그대로
 * 매핑해 두면 웰컴 클릭 경로가 100% 적중한다. 유사도 자동 매칭은 하지 않는다(팀 결정 —
 * 역할축 질문에 반대 답변이 서빙될 위험). 출처는 page_id 로 입력하고 서버가 확정한다
 * (출처 없는 답변은 서버가 거절 — 민원 리스크 불변식). */
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookmarkCheck } from 'lucide-react'
import { Button, ConfirmModal, DataTable, EmptyState, Loading, TextField } from '../../../../components/ui'
import type { Column } from '../../../../components/ui'
import { Switch } from '../../../../components/shadcn/switch'
import { Card, EditDialog, SectionError } from './common'
import type { CuratedAnswer, CuratedAnswerInput } from './api'
import { fetchCuratedAnswers, opsKeys, saveCuratedAnswers } from './api'

/** admin_ops.CURATED_MAX 와 동일 — 전량 교체·전량 스캔 전제의 상한 */
const REGISTERED_MAX = 50

interface FormState {
  id: string | null
  /** 줄당 문구 1개로 편집한다 — 배열 입력 UI 중 가장 단순한 형태 */
  questionsText: string
  answer: string
  /** 쉼표·공백 구분 page_id — 확정(제목·URL)은 서버 몫이라 여기선 문자열로만 다룬다 */
  pageIdsText: string
}

const toInput = (a: CuratedAnswer): CuratedAnswerInput => ({
  id: a.id, questions: a.questions, answer: a.answer, active: a.active, order: a.order,
  source_page_ids: a.sources.map((s) => s.page_id),
})

export function CuratedAnswersCard({ canEdit }: { canEdit: boolean }) {
  const qc = useQueryClient()
  const [form, setForm] = useState<FormState | null>(null)
  const [formError, setFormError] = useState('')
  const [removing, setRemoving] = useState<CuratedAnswer | null>(null)

  const query = useQuery({ queryKey: opsKeys.curated, queryFn: fetchCuratedAnswers })
  const save = useMutation({
    mutationFn: (input: { items: CuratedAnswerInput[]; reason: string }) =>
      saveCuratedAnswers(input.items, input.reason),
    onSuccess: (page) => {
      qc.setQueryData(opsKeys.curated, page)
      setForm(null)
      setRemoving(null)
      setFormError('')
    },
    // 서버 검증(출처 누락·없는 page_id·문구 중복)은 400 메시지가 곧 안내문이다
    onError: (e) => setFormError(e instanceof Error ? e.message : '저장에 실패했습니다.'),
  })

  if (query.isPending) {
    return (
      <Card title="답변 매핑" icon={<BookmarkCheck />} wide>
        <Loading />
      </Card>
    )
  }
  if (query.isError) {
    return (
      <Card title="답변 매핑" icon={<BookmarkCheck />} wide>
        <SectionError error={query.error} onRetry={() => void query.refetch()} />
      </Card>
    )
  }

  const items = query.data.items
  const commit = (next: CuratedAnswerInput[], reason: string) =>
    save.mutate({ items: next.map((a, i) => ({ ...a, order: i + 1 })), reason })

  function submitForm() {
    if (!form) return
    const questions = form.questionsText.split('\n').map((q) => q.trim()).filter(Boolean)
    const pageIds = form.pageIdsText.split(/[\s,]+/).map((x) => x.trim()).filter(Boolean)
    const entry: CuratedAnswerInput = {
      id: form.id ?? `ca_${Date.now()}`,
      questions,
      answer: form.answer.trim(),
      source_page_ids: pageIds,
      active: form.id ? (items.find((i) => i.id === form.id)?.active ?? true) : true,
      order: 0, // commit 이 재부여
    }
    const rest = items.filter((i) => i.id !== form.id).map(toInput)
    const label = questions[0] ?? entry.id
    commit(
      form.id ? [...rest.slice(0, items.findIndex((i) => i.id === form.id)), entry,
                 ...rest.slice(items.findIndex((i) => i.id === form.id))]
              : [...rest, entry],
      `답변 매핑 ${form.id ? '수정' : '추가'} : ${label}`,
    )
  }

  const columns: Column<CuratedAnswer>[] = [
    {
      key: 'questions',
      header: '질문 문구',
      render: (a) => (
        <span>
          {a.questions[0]}
          {a.questions.length > 1 && (
            <span className="ml-1 text-xs text-muted-foreground">외 {a.questions.length - 1}건</span>
          )}
        </span>
      ),
    },
    {
      key: 'answer',
      header: '답변 미리보기',
      render: (a) => <span className="line-clamp-1">{a.answer}</span>,
    },
    {
      key: 'sources',
      header: '출처',
      width: '90px',
      render: (a) => `${a.sources.length}건`,
    },
    {
      key: 'state',
      header: '상태',
      width: '112px',
      render: (a) => (
        <span className="inline-flex items-center gap-2">
          <Switch
            checked={a.active}
            disabled={!canEdit}
            aria-label={`${a.questions[0]} ${a.active ? '비활성' : '활성'} 전환`}
            onCheckedChange={() =>
              commit(
                items.map((i) => (i.id === a.id ? { ...toInput(i), active: !i.active } : toInput(i))),
                `답변 매핑 ${a.active ? '비활성' : '활성'} 전환 : ${a.questions[0]}`,
              )
            }
          />
          {a.active ? <strong className="font-medium text-foreground">활성</strong> : '비활성'}
        </span>
      ),
    },
  ]

  return (
    <Card
      title="답변 매핑"
      icon={<BookmarkCheck />}
      wide
      meta={`${items.length}개 등록 · 활성 ${items.filter((i) => i.active).length} — 일치 질문은 생성 없이 이 답변으로 응답`}
      actions={
        <Button
          size="sm"
          disabled={!canEdit || items.length >= REGISTERED_MAX}
          disabledReason={
            !canEdit
              ? '편집자(EDITOR) 이상만 추가할 수 있습니다'
              : items.length >= REGISTERED_MAX
                ? `등록은 최대 ${REGISTERED_MAX}개입니다`
                : undefined
          }
          onClick={() => {
            setForm({ id: null, questionsText: '', answer: '', pageIdsText: '' })
            setFormError('')
          }}
        >
          + 추가
        </Button>
      }
    >
      <DataTable
        caption="답변 매핑 목록"
        columns={columns}
        rows={items}
        rowKey={(a) => a.id}
        rowState={(a) => (a.active ? 'default' : 'disabled')}
        empty={
          <EmptyState title="등록된 답변 매핑이 없습니다 — 답변을 미리 작성해 두면 같은 질문에 생성 없이 즉시·동일하게 답합니다" />
        }
        actions={(a) => (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={!canEdit}
              onClick={() => {
                setForm({
                  id: a.id,
                  questionsText: a.questions.join('\n'),
                  answer: a.answer,
                  pageIdsText: a.sources.map((s) => s.page_id).join(', '),
                })
                setFormError('')
              }}
            >
              편집
            </Button>
            <Button size="sm" disabled={!canEdit} onClick={() => setRemoving(a)}>
              삭제
            </Button>
          </div>
        )}
      />

      <EditDialog
        open={form !== null}
        title={form?.id ? '답변 매핑 편집' : '답변 매핑 추가'}
        footer={
          <>
            <Button variant="secondary" onClick={() => setForm(null)}>
              취소
            </Button>
            <Button
              variant="primary"
              disabled={!form || form.questionsText.trim() === '' || form.answer.trim() === '' || form.pageIdsText.trim() === '' || save.isPending}
              disabledReason="질문 문구·답변·출처 page_id 가 모두 필요합니다"
              onClick={submitForm}
            >
              저장
            </Button>
          </>
        }
        onClose={() => setForm(null)}
      >
        {form && (
          <div className="flex flex-col gap-3">
            <TextField
              label="질문 문구 (줄당 1개 — 이 문구와 정확히 일치할 때만 응답)"
              multiline
              grow
              value={form.questionsText}
              placeholder={'예금자보호 한도가 얼마인가요?\n보호 한도 알려줘'}
              onChange={(v) => setForm({ ...form, questionsText: v })}
            />
            <TextField
              label="답변 (작성한 그대로 나갑니다)"
              multiline
              grow
              value={form.answer}
              onChange={(v) => setForm({ ...form, answer: v })}
            />
            <TextField
              label="출처 page_id (쉼표 구분 · 지식베이스의 페이지 ID)"
              value={form.pageIdsText}
              placeholder="dp_protlmts, dp_faq_page"
              onChange={(v) => setForm({ ...form, pageIdsText: v })}
            />
            {formError && <p className="text-[13px] text-destructive">{formError}</p>}
          </div>
        )}
      </EditDialog>

      <ConfirmModal
        open={removing !== null}
        title="답변 매핑을 삭제할까요?"
        impact={`'${removing?.questions[0] ?? ''}' 매핑이 삭제되고, 해당 질문은 다시 생성 경로로 답합니다. 지운 내용은 다시 입력할 수밖에 없습니다.`}
        confirmLabel="삭제"
        onConfirm={() => {
          if (removing) commit(items.filter((i) => i.id !== removing.id).map(toInput),
                               `답변 매핑 삭제 : ${removing.questions[0]}`)
        }}
        onCancel={() => setRemoving(null)}
      />
    </Card>
  )
}
