/** AD-008 ① 시스템 프롬프트 · ② 버전 이력 · ③ 가드레일 규칙 카드와 편집 모달.
 * 문구는 기획서 12절 §2.4~§2.6 원문 그대로. ※로 시작하는 빨간 주석은 기획 주석이라 렌더하지 않는다. */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowDown, ArrowUp, FileText, GripVertical, History, Lock, MessageSquareQuote, Shield,
} from 'lucide-react'
import {
  Badge, Button, ColorText, ConfirmModal, DataTable, DirtyDot, EmptyState, InfoHint, Loading, Notice, Pagination,
  Toggle,
} from '../../../../components/ui'
import type { Column } from '../../../../components/ui'
import { DEFAULT_PAGE_SIZE } from '../../../../components/ui'
import { Input } from '../../../../components/shadcn/input'
import { formatDate } from '../../../../lib/format'
import { Card, EditDialog, SectionError, linkClass } from './common'
import type {
  BlocklistRule, FewshotExample, MaskingRule, PromptDraft, PromptPrinciple, PromptVersion,
} from './api'
import { fetchPromptVersions, promptKeys, validateMasking } from './api'

/** CM-DF-004 06절 입력 제한 — 시스템 프롬프트 최대 8,000자 (constants.ts에 없어 여기 둔다) */
const SYSTEM_PROMPT_MAX = 8000

/** 편집 모달 안 네이티브 select — 룩은 shadcn Input과 맞춘다 */
const selectClass =
  'h-8 cursor-pointer rounded-md border border-input bg-transparent px-2.5 text-sm shadow-xs transition-[color,box-shadow] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50'

// ---------------------------------------------------------------- ① 시스템 프롬프트

export interface SystemPromptCardProps {
  draft: PromptDraft
  canEdit: boolean
  /** 원칙 목록을 통째로 갱신한다 — 서버가 아니라 로컬 초안이라 즉시 반영된다(대기 상태 없음) */
  onChange: (principles: PromptPrinciple[]) => void
}

export function SystemPromptCard({ draft, canEdit, onChange }: SystemPromptCardProps) {
  const [editingId, setEditingId] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [preview, setPreview] = useState(false)
  const [dragFrom, setDragFrom] = useState<number | null>(null)
  /** 삭제를 물어볼 대상. 지운 글은 다시 칠 수밖에 없어 한 번 확인한다 */
  const [removing, setRemoving] = useState<PromptPrinciple | null>(null)

  const principles = draft.principles
  const modified = principles.filter((p) => p.dirty).length
  const notAllowed = canEdit ? undefined : '편집자(EDITOR) 이상만 수정할 수 있습니다'

  function move(from: number, to: number) {
    if (to < 0 || to >= principles.length || from === to) return
    const next = [...principles]
    const [row] = next.splice(from, 1)
    next.splice(to, 0, row)
    onChange(next)
  }

  function commit(id: string) {
    const value = text.trim()
    if (value === '') return
    onChange(principles.map((p) => (p.id === id ? { ...p, text: value } : p)))
    setEditingId(null)
  }

  /** 행 삭제 — 확인 모달을 거친다(2026-08-04 사용자 지시).
   * 초안에서만 빼는 것이고 [초기화]로 되돌릴 수 있지만, 되돌리면 **다른 편집분까지 함께** 날아간다.
   * 지운 원칙 한 줄만 살릴 방법이 없으니 지우기 전에 한 번 묻는다.
   * 사유는 받지 않는다 — 초안 편집 단계라 감사 기록은 [게시] 시점에 한 번에 남는다. */
  function removePrinciple(id: string) {
    onChange(principles.filter((p) => p.id !== id))
    if (editingId === id) setEditingId(null)
    setRemoving(null)
  }

  function addPrinciple() {
    // [+ 원칙 추가]는 맨 아래에 빈 행을 만든다(Description 1)
    const id = `p_new_${Date.now()}`
    onChange([...principles, { id, text: '새 원칙', dirty: true }])
    setEditingId(id)
    setText('')
  }

  return (
    <Card
      title="시스템 프롬프트"
      icon={<FileText />}
      dirty={draft.dirty.prompt}
      meta={
        <>
          {draft.base_version} 기준 · {formatDate(draft.base_updated_at)} · {principles.length}원칙
        </>
      }
    >
      <ol className="m-0 list-none p-0">
        {principles.map((p, i) => (
          <li
            key={p.id}
            className="flex min-h-10 items-center gap-2 border-b py-1.5"
            draggable={canEdit && editingId === null}
            onDragStart={() => setDragFrom(i)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => {
              if (dragFrom !== null) move(dragFrom, i)
              setDragFrom(null)
            }}
          >
            <GripVertical className="size-4 shrink-0 cursor-grab text-muted-foreground/50" aria-hidden="true" />
            <span className="text-sm text-muted-foreground">{i + 1}.</span>

            {editingId === p.id ? (
              <>
                <Input
                  className="h-8 min-w-0 flex-1"
                  type="text"
                  value={text}
                  autoFocus
                  aria-label={`원칙 ${i + 1} 내용`}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commit(p.id)
                    if (e.key === 'Escape') setEditingId(null)
                  }}
                />
                <Button size="sm" variant="primary" onClick={() => commit(p.id)}>
                  저장
                </Button>
                <Button size="sm" onClick={() => setEditingId(null)}>
                  취소
                </Button>
              </>
            ) : (
              <>
                <span className="min-w-0 flex-1 text-sm">{p.text}</span>
                {p.dirty && <DirtyDot label={`원칙 ${i + 1} 변경됨`} />}
                {/* 드래그 정렬은 마우스 전용이라 키보드용 위/아래 버튼을 함께 둔다(CM-DF-004 09절) */}
                <Button
                  size="sm"
                  onClick={() => move(i, i - 1)}
                  disabled={!canEdit || i === 0}
                  aria-label={`원칙 ${i + 1} 위로 이동`}
                >
                  <ArrowUp aria-hidden="true" />
                </Button>
                <Button
                  size="sm"
                  onClick={() => move(i, i + 1)}
                  disabled={!canEdit || i === principles.length - 1}
                  aria-label={`원칙 ${i + 1} 아래로 이동`}
                >
                  <ArrowDown aria-hidden="true" />
                </Button>
                <Button
                  size="sm"
                  disabled={!canEdit}
                  disabledReason={notAllowed}
                  onClick={() => {
                    setEditingId(p.id)
                    setText(p.text)
                  }}
                >
                  편집
                </Button>
                {/* [+ 원칙 추가]는 있는데 뺄 방법이 없었다(사용자 지적).
                    자리·크기·순서는 다른 목록의 조치 줄과 같게 맨 끝에 둔다 */}
                <Button
                  size="sm"
                  disabled={!canEdit}
                  disabledReason={notAllowed}
                  aria-label={`원칙 ${i + 1} 삭제`}
                  onClick={() => setRemoving(p)}
                >
                  삭제
                </Button>
              </>
            )}
          </li>
        ))}

        {/* 시스템 원칙은 항상 마지막 · 편집·드래그 불가(Description 1).
         *
         * ⚠ `locked_principle`은 **실제 시스템 프롬프트 본문**이다(아래 원문 미리보기에 그대로
         * 이어 붙고, 그대로 모델에 간다). '(편집 불가)' 같은 콘솔 사정은 이 값에 섞으면 안 된다 —
         * 목업 라벨이 데이터로 굳어 프롬프트에 실려 나가고 있었다(사용자 지적).
         * 잠금 표시는 자물쇠 아이콘과 이 회색 꼬리표가 맡는다. */}
        <li className="flex min-h-10 items-center gap-2 border-b py-1.5 text-muted-foreground">
          <Lock className="size-4 shrink-0" aria-hidden="true" />
          <span className="min-w-0 flex-1 text-sm">{draft.locked_principle}</span>
          <span className="shrink-0 text-xs">시스템 원칙 · 편집 불가</span>
        </li>
      </ol>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          원칙 {principles.length}개 · {draft.char_count}자 · 수정 {modified}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className={linkClass} onClick={() => setPreview((v) => !v)}>
            원문 미리보기
          </button>
          <Button size="sm" disabled={!canEdit} disabledReason={notAllowed} onClick={addPrinciple}>
            + 원칙 추가
          </Button>
        </div>
      </div>

      {draft.char_count > SYSTEM_PROMPT_MAX && (
        <div className="mt-2" role="alert">
          <Notice tone="danger" variant="block">
            시스템 프롬프트가 최대 {SYSTEM_PROMPT_MAX.toLocaleString()}자를 넘었습니다. 원칙을 줄여 주세요.
          </Notice>
        </div>
      )}

      {preview && (
        <pre
          className="mt-3 max-h-55 overflow-auto rounded-md border bg-muted p-3 font-sans text-xs leading-relaxed whitespace-pre-wrap text-foreground"
          aria-label="모델에 전달되는 시스템 프롬프트 원문"
        >
          {principles.map((p, i) => `${i + 1}. ${p.text}`).join('\n')}
          {`\n${draft.locked_principle}`}
        </pre>
      )}

      {/* 지운 원칙 한 줄만 되살릴 방법이 없다 — [초기화]는 다른 편집분까지 함께 되돌린다.
          사유는 받지 않는다(초안 편집 단계 · 감사 기록은 [게시] 시점에 남는다) */}
      <ConfirmModal
        open={removing !== null}
        variant="danger"
        title="이 원칙을 삭제할까요?"
        impact={
          removing && (
            <>
              <p className="font-medium text-foreground">{removing.text}</p>
              <p className="mt-1">초안에서 지웁니다. 게시 전까지 운영 중인 프롬프트는 그대로입니다.</p>
              <p>· [초기화]로 되돌릴 수 있지만 이 화면의 다른 편집분도 함께 사라집니다</p>
            </>
          )
        }
        confirmLabel="삭제"
        onConfirm={() => removing && removePrinciple(removing.id)}
        onCancel={() => setRemoving(null)}
      />
    </Card>
  )
}

// ---------------------------------------------------------------- 예시 답변(few-shot)

export interface FewshotCardProps {
  items: FewshotExample[]
  dirty: boolean
}

/** 기획서에 편집 화면이 없어(12절 G1) 조회만 제공한다 */
export function FewshotCard({ items, dirty }: FewshotCardProps) {
  return (
    <Card title="예시 답변" icon={<MessageSquareQuote />} dirty={dirty} meta={`${items.length}개`}>
      {items.length === 0 ? (
        <EmptyState title="등록된 예시 답변이 없습니다" />
      ) : (
        <ol className="m-0 space-y-2.5 p-0">
          {items.map((f) => (
            <li key={f.id}>
              <p className="text-sm font-semibold">Q. {f.question}</p>
              <p className="mt-0.5 text-sm text-muted-foreground">A. {f.answer}</p>
            </li>
          ))}
        </ol>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------- ② 버전 이력

export interface VersionHistoryCardProps {
  canEdit: boolean
  canAdmin: boolean
  onRollback: (version: PromptVersion) => void
  onEmergencyRollback: (version: PromptVersion) => void
}

export function VersionHistoryCard({
  canEdit,
  canAdmin,
  onRollback,
  onEmergencyRollback,
}: VersionHistoryCardProps) {
  const [page, setPage] = useState(1)
  const query = useQuery({
    queryKey: [...promptKeys.versions, page],
    queryFn: () => fetchPromptVersions(page, DEFAULT_PAGE_SIZE),
  })

  const columns: Column<PromptVersion>[] = [
    {
      key: 'version',
      header: '버전',
      width: '84px',
      // 현행 행은 '현행' 배지 + 선택 행 배경이 이미 알린다 — 버전 글자는 굵기만 준다
      render: (v) => (v.status === '현행' ? <strong>{v.version}</strong> : v.version),
    },
    // 목업 포맷은 `07-30` — 초 단위까지 붙이지 않는다(§2.5 표)
    { key: 'created_at', header: '시각', width: '96px', render: (v) => formatDate(v.created_at).slice(5) },
    // 사유는 게시할 때 받은 자유 입력이다. DataTable의 td는 whitespace-nowrap이라 그대로 두면
    // 이 좁은 카드(가용 431px)에서 표가 넘쳐 '긴급 롤백' 버튼이 잘렸다.
    // 잘라내는 대신 두 줄로 흘린다 — 왜 그 버전이 나왔는지가 이 표에서 제일 중요한 정보다
    {
      key: 'reason',
      header: '사유',
      render: (v) => <span className="block max-w-45 break-keep whitespace-normal">{v.reason}</span>,
    },
  ]

  return (
    <Card title="버전 이력" icon={<History />} meta="작성자 · 시각 · 사유 기록">
      {query.isPending ? (
        <Loading />
      ) : query.isError ? (
        <SectionError error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <DataTable
            caption="프롬프트 버전 이력"
            columns={columns}
            rows={query.data.items}
            rowKey={(v) => v.version}
            rowState={(v) => (v.status === '현행' ? 'selected' : 'default')}
            empty={<EmptyState title="게시된 버전이 없습니다" />}
            actions={(v) =>
              v.status === '현행' ? (
                <Badge tone="green" kind="status">
                  현행
                </Badge>
              ) : (
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    disabled={!canEdit}
                    disabledReason={canEdit ? undefined : '편집자(EDITOR) 이상만 되돌릴 수 있습니다'}
                    onClick={() => onRollback(v)}
                  >
                    롤백
                  </Button>
                  {/* 긴급 롤백은 직전 정상 버전 하나에만 — 게이트 예외(REQ-OPS-003) */}
                  {v.emergency_candidate && canAdmin && (
                    <Button size="sm" onClick={() => onEmergencyRollback(v)}>
                      긴급 롤백
                    </Button>
                  )}
                </div>
              )
            }
          />
          {query.data.total > DEFAULT_PAGE_SIZE && (
            <Pagination page={page} total={query.data.total} onPageChange={setPage} />
          )}
        </>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------- ③ 가드레일 규칙(요약)

export interface GuardrailCardProps {
  draft: PromptDraft
  canEdit: boolean
  onToggleBlocklist: (active: boolean) => void
  onToggleMasking: (active: boolean) => void
  onEditBlocklist: () => void
  onEditMasking: () => void
}

export function GuardrailCard({
  draft,
  canEdit,
  onToggleBlocklist,
  onToggleMasking,
  onEditBlocklist,
  onEditMasking,
}: GuardrailCardProps) {
  const notAllowed = canEdit ? undefined : '편집자(EDITOR) 이상만 수정할 수 있습니다'
  return (
    <Card title="가드레일 규칙" icon={<Shield />} dirty={draft.dirty.guardrail} meta="질문·답변 양방향 적용">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b py-2">
        <Toggle
          label="금칙어 목록"
          unit={`${draft.blocklist.items.length}건`}
          checked={draft.blocklist.active}
          onChange={onToggleBlocklist}
          onLabel="활성"
          offLabel="비활성"
          disabled={!canEdit}
          disabledReason={notAllowed}
        />
        <Button size="sm" onClick={onEditBlocklist}>
          편집
        </Button>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b py-2">
        <Toggle
          label="개인정보 마스킹 규칙"
          unit={`${draft.masking.items.length}규칙`}
          checked={draft.masking.active}
          onChange={onToggleMasking}
          onLabel="활성"
          offLabel="비활성"
          disabled={!canEdit}
          disabledReason={notAllowed}
        />
        <Button size="sm" onClick={onEditMasking}>
          편집
        </Button>
      </div>
    </Card>
  )
}

// ---------------------------------------------------------------- 가드레일 규칙(탭 상세)

export interface GuardrailListCardProps {
  draft: PromptDraft
  onEditBlocklist: () => void
  onEditMasking: () => void
}

/** 탭 라벨의 건수(금칙어+마스킹)에 대응하는 목록. 편집은 모달에서만 한다(§2.6) */
export function GuardrailListCard({ draft, onEditBlocklist, onEditMasking }: GuardrailListCardProps) {
  const blockColumns: Column<BlocklistRule>[] = [
    { key: 'pattern', header: '단어 · 패턴', render: (r) => r.pattern },
    { key: 'type', header: '유형', width: '72px', render: (r) => r.type },
    { key: 'scope', header: '적용 범위', width: '92px', render: (r) => r.scope },
    {
      key: 'active',
      header: '활성',
      width: '60px',
      render: (r) => (r.active ? <ColorText tone="green">ON</ColorText> : <ColorText tone="red">OFF</ColorText>),
    },
  ]
  const maskColumns: Column<MaskingRule>[] = [
    { key: 'name', header: '규칙명', width: '110px', render: (r) => r.name },
    { key: 'pattern', header: '패턴 (정규식)', render: (r) => r.pattern },
    { key: 'replacement', header: '대체 형식', width: '130px', render: (r) => r.replacement },
    {
      key: 'active',
      header: '활성',
      width: '60px',
      render: (r) => (r.active ? <ColorText tone="green">ON</ColorText> : <ColorText tone="red">OFF</ColorText>),
    },
  ]
  return (
    <Card
      title="가드레일 규칙"
      icon={<Shield />}
      dirty={draft.dirty.guardrail}
      meta="질문·답변 양방향 적용"
      actions={
        <>
          <Button size="sm" onClick={onEditBlocklist}>
            금칙어 편집
          </Button>
          <Button size="sm" onClick={onEditMasking}>
            마스킹 편집
          </Button>
        </>
      }
    >
      <p className="text-xs text-muted-foreground">금칙어 목록 {draft.blocklist.items.length}건</p>
      <DataTable
        caption="금칙어 목록"
        columns={blockColumns}
        rows={draft.blocklist.items}
        rowKey={(r) => r.id}
        rowState={(r) => (r.active ? 'default' : 'disabled')}
        empty={<EmptyState title="등록된 금칙어가 없습니다" />}
      />
      <p className="mt-3 text-xs text-muted-foreground">
        개인정보 마스킹 규칙 {draft.masking.items.length}규칙
      </p>
      <DataTable
        caption="개인정보 마스킹 규칙"
        columns={maskColumns}
        rows={draft.masking.items}
        rowKey={(r) => r.id}
        rowState={(r) => (r.active ? 'default' : 'disabled')}
        empty={<EmptyState title="등록된 마스킹 규칙이 없습니다" />}
      />
    </Card>
  )
}

// ---------------------------------------------------------------- 금칙어 편집 모달

const BLOCK_TYPES: BlocklistRule['type'][] = ['단어', '정규식', '사전']
const BLOCK_SCOPES: BlocklistRule['scope'][] = ['질문', '답변', '질문 + 답변']

/**
 * 동작은 입력받지 않고 적용 범위에서 파생한다(2026-08-14). 종전에는 자유 입력칸이었는데,
 * 여기 적은 문구는 백엔드가 읽지 않아(차단 안내 문구는 서버 상수) LLM 프롬프트나 대체
 * 문구로 오해하게 만드는 거짓 입력칸이었다. 실제 동작은 규칙 적중 → 고정 안내 문구뿐이라
 * 관리자가 고를 수 있는 것은 '어느 방향을 검사할지'까지다.
 */
const BLOCK_ACTION_BY_SCOPE: Record<BlocklistRule['scope'], string> = {
  질문: '질문 접수 차단 → 안전 문구 응답',
  답변: '답변 생성 차단 → 안전 문구로 대체',
  '질문 + 답변': '질문·답변 차단 → 안전 문구로 대체',
}

export interface BlocklistDialogProps {
  open: boolean
  items: BlocklistRule[]
  canEdit: boolean
  /** [저장]은 로컬 초안에 얹기만 한다 — 서버 왕복이 없어 대기·실패 상태가 없다 */
  onSave: (items: BlocklistRule[]) => void
  onClose: () => void
}

export function BlocklistDialog({ open, items, canEdit, onSave, onClose }: BlocklistDialogProps) {
  const [rows, setRows] = useState<BlocklistRule[]>(items)
  const [keyword, setKeyword] = useState('')
  const [adding, setAdding] = useState(false)
  const [form, setForm] = useState({ pattern: '', type: '단어' as BlocklistRule['type'], scope: '답변' as BlocklistRule['scope'] })

  const visible = keyword.trim() ? rows.filter((r) => r.pattern.includes(keyword.trim())) : rows
  /** 제외를 물어볼 행 — 지운 규칙은 다시 입력할 수밖에 없다 */
  const [removing, setRemoving] = useState<BlocklistRule | null>(null)

  const columns: Column<BlocklistRule>[] = [
    { key: 'pattern', header: '단어 · 패턴', render: (r) => r.pattern },
    { key: 'type', header: '유형', width: '76px', render: (r) => r.type },
    { key: 'scope', header: '적용 범위', width: '96px', render: (r) => r.scope },
    { key: 'action', header: '동작', render: (r) => r.action },
    {
      key: 'active',
      header: '활성',
      width: '64px',
      render: (r) =>
        r.active ? <ColorText tone="green">ON</ColorText> : <ColorText tone="red">OFF</ColorText>,
    },
  ]

  return (
    <EditDialog
      open={open}
      title={`금칙어 목록 편집 · ${rows.length}건 · 적용 : 질문 + 답변`}
      tools={
        <>
          <Input
            className="h-8 w-55"
            type="search"
            value={keyword}
            placeholder="예: 계좌번호"
            aria-label="단어 · 패턴 검색"
            onChange={(e) => setKeyword(e.target.value)}
          />
          <Button
            size="sm"
            variant="primary"
            disabled={!canEdit}
            disabledReason={canEdit ? undefined : '편집자(EDITOR) 이상만 추가할 수 있습니다'}
            onClick={() => setAdding(true)}
          >
            + 금칙어 추가
          </Button>
        </>
      }
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            취소
          </Button>
          <Button variant="primary" disabled={!canEdit} onClick={() => onSave(rows)}>
            저장
          </Button>
        </>
      }
      onClose={onClose}
    >
      {adding && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border bg-muted/50 p-3">
          <Input
            className="h-8 w-auto min-w-45 flex-1"
            type="text"
            value={form.pattern}
            placeholder="예: 수익 보장"
            aria-label="단어 · 패턴"
            onChange={(e) => setForm({ ...form, pattern: e.target.value })}
          />
          <select
            className={selectClass}
            value={form.type}
            aria-label="유형"
            onChange={(e) => setForm({ ...form, type: e.target.value as BlocklistRule['type'] })}
          >
            {BLOCK_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <select
            className={selectClass}
            value={form.scope}
            aria-label="적용 범위"
            onChange={(e) => setForm({ ...form, scope: e.target.value as BlocklistRule['scope'] })}
          >
            {BLOCK_SCOPES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
          {/* 동작은 적용 범위에서 자동으로 정해진다 — 안내 문구는 서버 고정이라 여기서
              바꿀 수 없다(BLOCK_ACTION_BY_SCOPE 주석). 입력칸으로 두면 프롬프트로 오해한다 */}
          <span aria-label="동작(자동)" className="text-[13px] text-muted-foreground">
            {BLOCK_ACTION_BY_SCOPE[form.scope]} <span className="text-xs">(안내 문구는 고정)</span>
          </span>
          <Button
            size="sm"
            variant="primary"
            disabled={form.pattern.trim() === ''}
            disabledReason={form.pattern.trim() === '' ? '단어 · 패턴을 입력해 주세요' : undefined}
            onClick={() => {
              setRows([...rows, { id: `bw_new_${Date.now()}`, ...form, action: BLOCK_ACTION_BY_SCOPE[form.scope], pattern: form.pattern.trim(), active: true }])
              setForm({ ...form, pattern: '' })
              setAdding(false)
            }}
          >
            추가
          </Button>
          <Button size="sm" onClick={() => setAdding(false)}>
            취소
          </Button>
        </div>
      )}

      <DataTable
        caption="금칙어 목록"
        columns={columns}
        rows={visible}
        rowKey={(r) => r.id}
        rowState={(r) => (r.active ? 'default' : 'disabled')}
        empty={<EmptyState title="조건에 맞는 금칙어가 없습니다" />}
        /* flex-wrap을 두면 조치 열(74px)에서 버튼 둘이 세로로 쌓인다 — 셀은 이미
           whitespace-nowrap이라 감싸지 않으면 표가 이 열에 필요한 폭을 내준다 */
        actions={(r) => (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={!canEdit}
              onClick={() => setRows(rows.map((x) => (x.id === r.id ? { ...x, active: !x.active } : x)))}
            >
              {r.active ? '중지' : '사용'}
            </Button>
            <Button
              size="sm"
              disabled={!canEdit}
              aria-label={`${r.pattern} 제외`}
              onClick={() => setRemoving(r)}
            >
              제외
            </Button>
          </div>
        )}
      />

      {/* 지운 규칙은 다시 입력할 수밖에 없다 — [취소]로 통째로 버릴 수는 있어도
          이 한 줄만 살릴 방법은 없으므로 지우기 전에 묻는다(2026-08-04 사용자 지시).
          사유는 받지 않는다 — 저장 시점(가드레일 게시)에 한 번에 남는다 */}
      <ConfirmModal
        open={removing !== null}
        variant="danger"
        title="이 금칙어를 목록에서 뺄까요?"
        impact={
          removing && (
            <>
              <p className="font-medium text-foreground">{removing.pattern}</p>
              <p className="mt-1">편집 중인 목록에서만 빠집니다. [저장]을 눌러야 가드레일에 반영됩니다.</p>
            </>
          )
        }
        confirmLabel="제외"
        onConfirm={() => {
          if (removing) setRows(rows.filter((x) => x.id !== removing.id))
          setRemoving(null)
        }}
        onCancel={() => setRemoving(null)}
      />
    </EditDialog>
  )
}

// ---------------------------------------------------------------- 마스킹 편집 모달

export interface MaskingDialogProps {
  open: boolean
  items: MaskingRule[]
  canEdit: boolean
  /** BlocklistDialog와 같다 — 로컬 초안 갱신이라 대기·실패 상태가 없다 */
  onSave: (items: MaskingRule[]) => void
  onClose: () => void
}

export function MaskingDialog({ open, items, canEdit, onSave, onClose }: MaskingDialogProps) {
  const [rows, setRows] = useState<MaskingRule[]>(items)
  const [checking, setChecking] = useState<string | null>(null)
  const [message, setMessage] = useState('')

  const unvalidated = rows.filter((r) => !r.validated)
  /** 제외를 물어볼 행 — 금칙어 목록과 같은 규칙이다 */
  const [removing, setRemoving] = useState<MaskingRule | null>(null)

  function patch(id: string, next: Partial<MaskingRule>) {
    // 패턴·대체 형식을 고치면 검증이 풀린다 — 통과 전에는 저장할 수 없다(§2.11)
    setRows(rows.map((r) => (r.id === id ? { ...r, ...next, validated: false } : r)))
  }

  async function check(rule: MaskingRule) {
    setChecking(rule.id)
    setMessage('')
    try {
      const result = await validateMasking(rule.pattern, rule.replacement)
      setMessage(result.message)
      if (result.passed) {
        setRows(rows.map((r) => (r.id === rule.id ? { ...r, validated: true, sample_count: result.sample_count ?? 0 } : r)))
      }
    } catch (e) {
      // 검증 호출 자체가 실패한 경우 — 문구는 서버 user_message를 그대로 쓴다(PRD-02 §3)
      setMessage(e instanceof Error ? e.message : '검증에 실패했습니다.')
    } finally {
      setChecking(null)
    }
  }

  const columns: Column<MaskingRule>[] = [
    {
      key: 'name',
      header: '규칙명',
      width: '120px',
      render: (r) => (
        <Input
          className="h-8"
          type="text"
          value={r.name}
          aria-label={`${r.name} 규칙명`}
          disabled={!canEdit}
          onChange={(e) => patch(r.id, { name: e.target.value })}
        />
      ),
    },
    {
      key: 'pattern',
      header: '패턴 (정규식)',
      render: (r) => (
        <Input
          className="h-8 min-w-45"
          type="text"
          value={r.pattern}
          aria-label={`${r.name} 패턴`}
          disabled={!canEdit}
          onChange={(e) => patch(r.id, { pattern: e.target.value })}
        />
      ),
    },
    {
      key: 'replacement',
      header: '대체 형식',
      width: '140px',
      render: (r) => (
        <Input
          className="h-8"
          type="text"
          value={r.replacement}
          aria-label={`${r.name} 대체 형식`}
          disabled={!canEdit}
          onChange={(e) => patch(r.id, { replacement: e.target.value })}
        />
      ),
    },
    {
      key: 'validated',
      header: (
        <span className="inline-flex items-center gap-0.5">
          검증
          {/* 모달 본문은 max-h 56vh 스크롤 영역이라 표 아래 2줄 안내가 규칙 행을 가린다.
              같은 조건을 [저장] 버튼의 비활성 사유가 이미 말하고 있어 열 이름 옆으로 접는다 */}
          <InfoHint label="패턴 검증 규칙 설명" size="sm">
            패턴을 고치면 저장하기 전에 샘플 대화로 검증합니다. 매칭 결과 미리보기가 통과해야 [저장]이
            활성화됩니다 — 과대 매칭·과소 매칭을 막기 위한 절차입니다.
          </InfoHint>
        </span>
      ),
      width: '150px',
      render: (r) =>
        r.validated ? (
          <ColorText tone="green">샘플 {r.sample_count}건 통과 ✓</ColorText>
        ) : (
          <Button size="sm" loading={checking === r.id} disabled={!canEdit} onClick={() => void check(r)}>
            샘플 검증
          </Button>
        ),
    },
    {
      key: 'active',
      header: '활성',
      width: '64px',
      render: (r) =>
        r.active ? <ColorText tone="green">ON</ColorText> : <ColorText tone="red">OFF</ColorText>,
    },
  ]

  return (
    <EditDialog
      open={open}
      title={`개인정보 마스킹 규칙 편집 · ${rows.length}건 · 적용 : 로그 저장 시점`}
      tools={
        <Button
          size="sm"
          variant="primary"
          disabled={!canEdit}
          onClick={() =>
            setRows([
              ...rows,
              { id: `mk_new_${Date.now()}`, name: '새 규칙', pattern: '', replacement: '', validated: false, sample_count: 0, active: true },
            ])
          }
        >
          + 규칙 추가
        </Button>
      }
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            취소
          </Button>
          <Button
            variant="primary"
            disabled={!canEdit || unvalidated.length > 0}
            disabledReason={
              unvalidated.length > 0 ? '패턴이 샘플 검증을 통과해야 저장할 수 있습니다' : undefined
            }
            onClick={() => onSave(rows)}
          >
            저장
          </Button>
        </>
      }
      onClose={onClose}
    >
      <DataTable
        caption="개인정보 마스킹 규칙"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.id}
        empty={<EmptyState title="등록된 마스킹 규칙이 없습니다" />}
        /* flex-wrap을 두면 조치 열(74px)에서 버튼 둘이 세로로 쌓인다 — 셀은 이미
           whitespace-nowrap이라 감싸지 않으면 표가 이 열에 필요한 폭을 내준다 */
        actions={(r) => (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={!canEdit}
              onClick={() => setRows(rows.map((x) => (x.id === r.id ? { ...x, active: !x.active } : x)))}
            >
              {r.active ? '중지' : '사용'}
            </Button>
            <Button
              size="sm"
              disabled={!canEdit}
              aria-label={`${r.name} 제외`}
              onClick={() => setRemoving(r)}
            >
              제외
            </Button>
          </div>
        )}
      />

      {/* 지운 규칙은 다시 입력할 수밖에 없다 — [취소]로 통째로 버릴 수는 있어도
          이 한 줄만 살릴 방법은 없으므로 지우기 전에 묻는다(2026-08-04 사용자 지시).
          사유는 받지 않는다 — 저장 시점(가드레일 게시)에 한 번에 남는다 */}
      <ConfirmModal
        open={removing !== null}
        variant="danger"
        title="이 마스킹 규칙을 목록에서 뺄까요?"
        impact={
          removing && (
            <>
              <p className="font-medium text-foreground">{removing.name}</p>
              <p className="mt-1">편집 중인 목록에서만 빠집니다. [저장]을 눌러야 가드레일에 반영됩니다.</p>
            </>
          )
        }
        confirmLabel="제외"
        onConfirm={() => {
          if (removing) setRows(rows.filter((x) => x.id !== removing.id))
          setRemoving(null)
        }}
        onCancel={() => setRemoving(null)}
      />
      {message && <p className="mt-1 text-xs text-muted-foreground">{message}</p>}
    </EditDialog>
  )
}
