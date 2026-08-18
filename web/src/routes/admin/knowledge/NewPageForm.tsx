/** AD-003 신규 URL 추가 · 적재 미리보기 — **AD-002 목록 화면 안에 인라인으로 열리는 블록.**
 *
 * 원래는 `/admin/knowledge/new` 별도 라우트였다. [+ 신규 URL 추가]를 누르면 화면이 통째로
 * 바뀌어, 방금 보던 목록·필터·스크롤 위치를 잃고 뒤로가기로 돌아와야 했다. 입력 중인 값도
 * 화면을 뜨는 순간 사라진다. AD-006 [+ 문항 추가]와 같은 인라인 편집기 방식으로 통일했다
 * (2026-08-04 사용자 요청).
 *
 * 구성(A-2) : URL 입력 줄 → 메타 폼 → ⓘ 각주 3줄 → 파이프라인 카드 → 미리보기 결과 → 액션 줄.
 *
 * 폼은 사람 입력 8키(page_id·source_url·business_function·sub_category·page_title·required·note·summary)다.
 * "자동 수집값(수집일 · 본문 · 서식/이동 링크 · 이미지 · 해시)은 폼에 없습니다"(ⓘ 각주 3).
 * 미리보기는 운영에 영향 없는 앞 4단계까지만 실행하고, 5·6단계는 [적재] 뒤에 이어서 보여준다(A-5·A-8). */
import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import {
  Button,
  ConfirmModal,
  InfoHint,
  Loading,
  Notice,
  PipelineSteps,
  SectionError,
  Select,
  TextField,
  useToast,
} from '../../../components/ui'
import type { SelectOption, StepState } from '../../../components/ui'
import { useSession } from '../../../app/session'
import { apiRequest } from '../../../lib/api/client'
import type { Page } from '../../../lib/api/types'
import { BUSINESS_FUNCTIONS, hasRole } from '../../../lib/codes'
import type { BusinessFunction } from '../../../lib/codes'
import type {
  ChangeRequestView,
  JobStep,
  KbPage,
  NewPageRecord,
  PipelineJobView,
  PreviewResponse,
} from './types'

/** 진행 중 작업을 따라가는 주기. 관리자 job 구독 계약이 없어(10 issue G-9) 3초 폴링으로 정했다 */
const JOB_POLL_MS = 3_000

/** 6단계 중 앞 4단계만 실행된 상태 — 미리보기가 준비된 직후 (A-5) */
const PREVIEW_STEPS: StepState[] = ['done', 'done', 'done', 'done', 'waiting', 'waiting']

const STEP_STATE: Record<JobStep['status'], StepState> = {
  QUEUED: 'waiting',
  RUNNING: 'running',
  SUCCESS: 'done',
  FAILED: 'failed',
  SKIPPED: 'waiting',
}

const BUSINESS_OPTIONS: SelectOption[] = [
  { value: '', label: '업무 선택' },
  ...BUSINESS_FUNCTIONS.map((b) => ({ value: b, label: b })),
]

/** '구분'은 값 2종. 기본값은 '필수'(Description ⓿ "구분(기본값 '필수')") */
const REQUIRED_OPTIONS: SelectOption[] = [
  { value: 'true', label: '필수' },
  { value: 'false', label: '분석필요' },
]

interface FormState {
  source_url: string
  business_function: string
  required: boolean
  page_title: string
  page_id: string
  sub_category: string
  note: string
  summary: string
  /** 담당 — 신규는 로그인 계정, 후보 진입은 등록값 (A-4 '자동 생성') */
  owner: string
}

const EMPTY_FORM: FormState = {
  source_url: '',
  business_function: '',
  required: true,
  page_title: '',
  page_id: '',
  sub_category: '',
  note: '',
  summary: '',
  owner: '',
}

/** 구획 공통 — 그림자로 띄우지 않고 헤어라인으로만 가둔다.
 * 입력(URL·메타 폼)은 회색 인셋 위에 그대로 두고, 이 흰 카드는 실행 **결과**에만 쓴다 —
 * 인셋 안에 또 카드를 깔면 액자 속 액자가 된다 */
const CARD = 'rounded-md border bg-card p-5'
const CARD_TITLE = 'mb-3 text-[13px] font-semibold tracking-[-0.01em] text-foreground'

/** 자동 생성 필드 — 점선 테두리로 수동 입력 필드와 구분한다 (A-4 '필드 시각 구분').
 * 색이 아니라 선 종류가 구분을 진다(라벨 문구에 이미 '자동'이 있다).
 * 공통 Field/Input에 클래스 주입구가 없어 하위 선택자로 덧칠한다 — 수동 필드는 공통 규격 그대로 */
function AutoField({ children }: { children: ReactNode }) {
  return <div className="[&_input]:border-dashed [&_select]:border-dashed">{children}</div>
}

export interface NewPageFormProps {
  /** 수집 대상 탭의 '후보' 행에서 열었으면 그 page_id — 폼을 프리필한다 (Screen Path Case 2) */
  candidateId?: string | null
  onClose: () => void
}

export function NewPageForm({ candidateId = null, onClose }: NewPageFormProps) {
  const showToast = useToast()
  const queryClient = useQueryClient()
  // 표 아래쪽 행의 [수집 실행]으로 열면 이 블록이 화면 밖(표 위)에 생긴다 — 눌러도 아무 일도
  // 일어나지 않은 것처럼 보이므로 열자마자 시야로 끌어온다. block:'nearest'라 이미 보이면 안 움직인다
  const box = useRef<HTMLElement>(null)
  useEffect(() => {
    box.current?.scrollIntoView({ block: 'nearest' })
  }, [])
  const { session } = useSession()
  const role = session?.role
  // 미리보기·변경 요청·적재는 EDITOR, 재색인 작업 생성은 OPERATOR (목 admin.ts 권한 표)
  const canEdit = hasRole(role, 'EDITOR')
  // 요청/승인 2단계를 없앴다(팀 결정 2026-08-04) — 편집 권한자가 바로 적재한다.
  // 사전 차단은 URL 사전 검증·필수 입력이, 사후 추적은 활동 로그(AD-011)가 맡는다

  // 진입 2종 (Screen Path) — Case 1 빈 폼 / Case 2 수집 대상 '후보' 행의 [수집 실행]

  // 신규 진입의 담당 기본값은 로그인 계정이다 (A-4 '담당 : 신규=로그인 계정')
  const [form, setForm] = useState<FormState>(() => ({ ...EMPTY_FORM, owner: session?.email ?? '' }))
  const [preview, setPreview] = useState<PreviewResponse | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<'approve' | 'reject' | null>(null)

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  // ---- Case 2 : 후보 레코드를 읽어 폼을 채운다 (프리필 8종 · AD-002 B-10) ----
  const candidate = useQuery({
    queryKey: ['kb-candidate', candidateId],
    enabled: candidateId !== null,
    queryFn: () =>
      apiRequest<Page<KbPage>>(
        `/api/admin/knowledge/pages?tab=targets&q=${encodeURIComponent(candidateId!)}&size=1`,
      ),
  })
  const candidateRow = candidate.data?.items.find((p) => p.page_id === candidateId) ?? null
  const [prefilled, setPrefilled] = useState(false)

  useEffect(() => {
    if (candidateRow === null || prefilled) return
    setPrefilled(true) // 한 번만 채운다 — 관리자가 고친 값을 재조회가 덮으면 안 된다
    setForm({
      source_url: candidateRow.source_url,
      business_function: candidateRow.business_function,
      required: candidateRow.required,
      page_title: candidateRow.page_title,
      page_id: candidateRow.page_id,
      sub_category: candidateRow.sub_category,
      note: candidateRow.note,
      summary: candidateRow.summary,
      owner: candidateRow.owner,
    })
  }, [candidateRow, prefilled])

  // ---- 수집 실행 : 앞 4단계를 1건 실행한다 ----
  const collect = useMutation({
    mutationFn: () =>
      // 사람이 적은 값도 함께 보낸다 — 수집 근거는 거버넌스 기록이고, 나머지는 자동 추출이
      // 덮지 않아야 할 입력값이다 (A-4 "두 화면의 필드는 같은 레코드")
      apiRequest<PreviewResponse>('/api/admin/previews', {
        method: 'POST',
        body: {
          url: form.source_url.trim(),
          business_function: form.business_function,
          required: form.required,
          page_title: form.page_title.trim(),
          sub_category: form.sub_category.trim(),
          note: form.note.trim(),
          summary: form.summary.trim(),
        },
      }),
    onSuccess: (res) => {
      setPreview(res)
      // 자동 추출값은 비어 있는 칸만 채운다 — 관리자가 이미 적은 값을 덮어쓰지 않는다
      setForm((prev) => ({
        ...prev,
        page_id: prev.page_id || res.extracted.page_id,
        page_title: prev.page_title || res.extracted.page_title,
        sub_category: prev.sub_category || res.extracted.sub_category,
        summary: prev.summary || res.extracted.summary,
        business_function: prev.business_function || res.extracted.business_function,
      }))
    },
  })

  // ---- 적재 : 변경 요청(감사 기록) → 확정 → 재색인 작업 생성 (Description ❸) ----
  const approve = useMutation({
    mutationFn: async (reason: string) => {
      // 적재하면 이 레코드 그대로 수집 대상 목록(AD-002)에 등록된다 → 폼 8키 + 담당을 전부 싣는다(A-4)
      const record: NewPageRecord = {
        page_id: form.page_id.trim(),
        source_url: form.source_url.trim(),
        business_function: form.business_function as BusinessFunction,
        sub_category: form.sub_category.trim(),
        page_title: form.page_title.trim(),
        required: form.required,
        note: form.note.trim(),
        summary: form.summary.trim(),
        owner: form.owner.trim(),
      }
      const created = await apiRequest<ChangeRequestView>('/api/admin/change-requests', {
        method: 'POST',
        body: {
          action: 'ADD',
          target_page_id: record.page_id,
          target_title: record.page_title,
          business_function: record.business_function,
          page: record,
        },
        reason,
      })
      // 변경 요청은 감사 기록으로 남기되 곧바로 확정한다 — 별도 승인자를 기다리지 않는다
      await apiRequest(`/api/admin/change-requests/${created.id}/approve`, { method: 'POST', reason })
      const job = await apiRequest<PipelineJobView>('/api/admin/jobs', {
        method: 'POST',
        body: { type: 'REINDEX', targets: [form.page_id.trim()] },
        reason,
      })
      return { job }
    },
    onSuccess: ({ job }) => {
      setJobId(job.id)
      showToast('적재를 시작했습니다')
      // 같은 화면 아래에 목록이 있다 — 적재한 행이 바로 보이도록 다시 읽는다
      void queryClient.invalidateQueries({ queryKey: ['kb-pages'] })
    },
  })

  // ---- 버리기 : 사유 필수 · 임시 자료는 하루 뒤 삭제 (Description ❷).
  //      승인자가 따로 없어 '반려'가 아니라 내 미리보기를 버리는 동작이다 (엔드포인트는 그대로) ----
  const reject = useMutation({
    mutationFn: (reason: string) =>
      apiRequest(`/api/admin/previews/${preview!.preview_id}/reject`, { method: 'POST', reason }),
    onSuccess: () => {
      setPreview(null)
      showToast('미리보기를 버렸습니다')
    },
  })

  // ---- 승인 후 5·6단계 진행 (A-8). 화면을 떠났다 와도 job_id로 같은 상태를 복원한다 ----
  const jobQuery = useQuery({
    queryKey: ['ingest-job', jobId],
    enabled: jobId !== null,
    queryFn: () => apiRequest<PipelineJobView>(`/api/admin/jobs/${jobId}`, { isPoll: true }),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'QUEUED' || status === 'RUNNING' ? JOB_POLL_MS : false
    },
  })
  const job = jobQuery.data ?? null
  const jobRunning = job !== null && (job.status === 'QUEUED' || job.status === 'RUNNING')

  // 프론트는 URL 형식만 본다. 허용 도메인·중복·차단 판정은 서버가 하고, 실패 문구는 서버가 준다(10 issue G-5)
  const urlValid = /^https?:\/\/\S+$/.test(form.source_url.trim())
  const collectBlocked =
    !urlValid || !form.business_function || form.note.trim() === ''
      ? 'URL · 업무 · 수집 근거를 입력해야 실행할 수 있습니다'
      : undefined

  // 하위분류는 자동 추출 실패 시에만 필수로 승격되고, 입력 전까지 [적재 승인]이 잠긴다(ⓘ 각주 2)
  const subCategoryMissing =
    preview?.sub_category_extraction_failed === true && form.sub_category.trim() === ''
  const approveBlocked = !preview
    ? '수집 실행을 먼저 해 주세요'
    : subCategoryMissing
      ? '하위분류를 입력해야 승인할 수 있습니다'
      : form.page_id.trim() === ''
        ? '페이지 ID를 입력해야 승인할 수 있습니다'
        : undefined

  const done = jobId !== null

  /** 승인자가 따로 없으니 '승인'이 아니라 지금 무슨 일이 일어나는지를 쓴다(03절 버튼 규칙) */
  const approveLabel = '적재'
  const titleId = `new-page-${candidateId ?? 'blank'}`

  return (
    // AD-006 [+ 문항 추가]와 같은 인셋 — '지금 이 목록에 무언가를 더하는 중'이라는 상태를
    // 색면이 아니라 회색 인셋 + 헤어라인이 진다(보라는 Primary·링크·포커스 몫)
    <section
      className="mb-4 flex flex-col gap-5 rounded-md border bg-muted/60 p-4"
      aria-labelledby={titleId}
      ref={box}
    >
      <div className="flex items-start justify-between gap-4">
        <h2 className="inline-flex items-center gap-0.5 text-[13px] font-semibold" id={titleId}>
          {candidateId ? '수집 실행 · 적재 미리보기' : '신규 URL 추가 · 적재 미리보기'}
          <InfoHint label="적재 절차 설명" size="sm">
            [수집 실행]은 운영에 영향이 없는 앞 4단계(수집·변환·청킹·검증)만 돌려 결과를 보여줍니다.
            여기서 확인한 뒤 [적재]해야 목록에 등록되고 재색인이 시작됩니다.
          </InfoHint>
        </h2>
        <button
          type="button"
          className="-my-1 -mr-1.5 inline-flex size-9 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors duration-200 hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          aria-label="신규 URL 추가 닫기"
          onClick={onClose}
        >
          <X className="size-4" aria-hidden="true" />
        </button>
      </div>

      {/* R1 — URL 입력 줄. URL만 넓게 (목업 입력 696) */}
      <div className="flex flex-wrap items-center gap-3 [&_input]:w-[560px] [&_input]:max-w-full">
        <TextField
          label="URL"
          grow
          value={form.source_url}
          onChange={(v) => set('source_url', v)}
          placeholder="https://www.kdic.or.kr/protect/new_page.do"
          disabled={preview !== null}
        />
        {canEdit && (
          <Button
            variant="primary"
            onClick={() => collect.mutate()}
            loading={collect.isPending}
            disabled={collectBlocked !== undefined || preview !== null}
            disabledReason={preview !== null ? '이미 수집한 URL입니다' : collectBlocked}
          >
            수집 실행
          </Button>
        )}
      </div>

      <SectionError error={collect.error} onRetry={() => collect.mutate()} />
      {/* 후보 조회가 실패하면 폼이 빈 채로 열린다 — 왜 안 채워졌는지 화면에 남긴다 */}
      <SectionError error={candidate.error} onRetry={() => void candidate.refetch()} />

      {/* R2 — 메타 폼 8필드 2열 그리드. 자동 생성 3종(구분·페이지 ID·담당)은 AutoField로 감싸 시각 구분한다 */}
      {/* Field 라벨 트랙이 160px 고정이라 1024에서 2열을 유지하면 입력창 자리가 160px도 안 남는다 */}
      <div className="grid grid-cols-1 gap-x-8 gap-y-1 xl:grid-cols-2">
        <Select
          label="업무 (필수)"
          value={form.business_function}
          onChange={(v) => set('business_function', v)}
          options={BUSINESS_OPTIONS}
        />
        <AutoField>
          <Select
            label="자동 · 구분"
            value={String(form.required)}
            onChange={(v) => set('required', v === 'true')}
            options={REQUIRED_OPTIONS}
          />
        </AutoField>
        <TextField
          label="제목 (선택 · 비우면 원문 제목)"
          grow
          value={form.page_title}
          onChange={(v) => set('page_title', v)}
        />
        <AutoField>
          <TextField
            label="자동 · 페이지 ID (수정 가능)"
            value={form.page_id}
            onChange={(v) => set('page_id', v)}
            placeholder="예: dp_protlmts"
          />
        </AutoField>
        <TextField
          label="하위분류"
          hint="사용자 답변의 출처 카드에 경로로 노출되는 값입니다. [수집 실행] 시 원문에서 자동 추출하고, 추출에 실패했을 때만 필수 입력이 되어 [적재]가 잠깁니다 — 적재 시점에는 항상 값이 보장됩니다."
          grow
          value={form.sub_category}
          onChange={(v) => set('sub_category', v)}
          error={subCategoryMissing ? '자동 추출에 실패했습니다. 직접 입력해 주세요' : undefined}
        />
        <TextField grow label="수집 근거 (필수)" value={form.note} onChange={(v) => set('note', v)} />
        <AutoField>
          <TextField
            label="담당 (자동)"
            value={form.owner}
            onChange={(v) => set('owner', v)}
            // 목업 값 `dy (후보 등록값)` — 값과 출처 표기를 나눠 출처는 컨트롤 옆 회색으로 둔다
            unit={prefilled ? '(후보 등록값)' : undefined}
          />
        </AutoField>
        <TextField
          label="요약 (선택 · 관리 참고용)"
          multiline
          value={form.summary}
          onChange={(v) => set('summary', v)}
        />
      </div>


      {collect.isPending && <Loading text="수집·변환·청킹·검증을 실행하는 중…" />}

      {preview && (
        <>
          {/* R4 — 파이프라인 카드. 스텝 표시는 공통 PipelineSteps 재사용 */}
          <section className={CARD} aria-label="파이프라인">
            <h2 className={`${CARD_TITLE} inline-flex items-center gap-0.5`}>
              파이프라인
              {/* 단계 규칙은 한 번 알면 되는 설명이고, 스텝 그림 아래 3줄로 깔면 그 아래
                  '승인 후 상태 줄'과 버튼이 밀린다 — 제목 옆으로 접는다 */}
              <InfoHint label="파이프라인 단계 설명" size="sm">
                {jobId === null
                  ? '미리보기는 운영에 영향이 없는 앞 4단계까지만 실행합니다. 5·6단계는 [적재] 전까지 비활성(○)이고, 적재하면 활성화되어 진행이 이어서 표시됩니다. 단계 구성과 기호는 파이프라인 화면(AD-004)과 같습니다.'
                  : '6단계까지 모두 통과하면 인덱스를 한 번에 교체합니다. 실패하면 기존 인덱스를 그대로 유지하고, 성공하면 캐시를 비웁니다.'}
              </InfoHint>
            </h2>
            <PipelineSteps states={job ? job.steps.map((s) => STEP_STATE[s.status]) : PREVIEW_STEPS} />

            {/* 승인 후 상태 줄 (A-8). '예상 약 N분'은 응답에 없어 뺐다 */}
            {job && (
              <p className="mt-2 text-xs text-muted-foreground" role="status">
                {jobRunning ? (
                  <>
                    {/* 실행 중 상태 점 — 텍스트('진행 중')와 병기. 색은 잉크(보라는 Primary·링크 몫) */}
                    <span
                      className="pulse-dot mr-1.5 inline-block size-1.5 rounded-full bg-foreground/70 align-middle"
                      aria-hidden="true"
                    />
                    재색인 작업 {job.id} 진행 중. 완료되면 AD-002 목록에 '최신'으로 강조되고, 같은 작업이
                    파이프라인(AD-004) 실행 이력에도 기록됩니다
                  </>
                ) : job.status === 'SUCCESS' ? (
                  // 목록이 바로 아래에 있다 — 다른 화면으로 보내지 않고 닫기만 안내한다
                  <>재색인 작업 {job.id}이 끝났습니다. 닫으면 아래 목록에서 확인할 수 있습니다</>
                ) : (
                  <>
                    재색인 작업 {job.id}이 끝나지 않았습니다.{' '}
                    <Link className="text-primary hover:underline" to="/admin/pipeline">
                      파이프라인에서 상태 확인 →
                    </Link>
                  </>
                )}
              </p>
            )}
          </section>

          {/* R5 — 미리보기 결과 (3. 청킹 결과) */}
          <section className={CARD} aria-label="미리보기 결과">
            <h2 className={CARD_TITLE}>미리보기 결과</h2>
            {preview.warnings.map((warning) => (
              <Notice className="mb-2" key={warning} tone="warning">
                {warning}
              </Notice>
            ))}
            {/* 청크가 수십 개일 수 있어 패널 안에서 스크롤한다(A-6) */}
            <ul className="flex max-h-90 flex-col gap-2 overflow-y-auto">
              {preview.chunks.map((chunk) => (
                <li className="rounded bg-muted/50 px-3 py-2.5" key={chunk.chunk_id}>
                  {/* 메타 포맷: `chunk #{index} · {글자수}자 · {분할 규칙 설명}` (A-6) */}
                  <p className="text-[13px] font-bold text-foreground">
                    chunk #{chunk.seq} · {chunk.chars}자 · {preview.split_rule}
                  </p>
                  <p className="mt-1 line-clamp-2 text-sm text-foreground/80">{chunk.preview}</p>
                </li>
              ))}
            </ul>
            {preview.chunks.length === 0 && (
              <Notice className="mb-2" tone="warning">
                만들어진 청크가 없습니다. 원문 주소를 다시 확인해 주세요.
              </Notice>
            )}
          </section>

          {/* 승인·반려는 [다시 시도]를 붙이지 않는다 — 같은 요청을 또 보내면 변경 요청이 두 건 생긴다 */}
          <SectionError error={approve.error ?? reject.error} />

          {/* R6 — 액션 줄. 승인(primary)·반려(secondary) 위계 */}
          {canEdit && !done && (
            <div className="flex justify-end gap-3">
              <Button onClick={() => setConfirm('reject')} loading={reject.isPending}>
                버리기
              </Button>
              <Button
                variant="primary"
                onClick={() => setConfirm('approve')}
                loading={approve.isPending}
                disabled={approveBlocked !== undefined}
                disabledReason={approveBlocked}
              >
                {approveLabel}
              </Button>
            </div>
          )}

        </>
      )}

      <ConfirmModal
        open={confirm === 'approve'}
        title="이 페이지를 적재할까요?"
        impact={
          <>
            <p>지식베이스 목록에 등록되고 재색인 작업이 만들어집니다.</p>
            <p>· 적재가 곧 서비스 반영은 아닙니다. 게이트(홀드아웃 평가)를 통과해야 색인·반영합니다</p>
            <p>· 게이트 미달이면 이 페이지는 색인되지 않고 수집 대상 탭에 남습니다 — 실패 뒤에는 그 탭에서 확인합니다</p>
            <p>· 실패·취소·검증 미달이면 기존 인덱스를 유지합니다</p>
          </>
        }
        reason="required"
        reasonPlaceholder="예: 신규 안내 페이지 적재 (2026-08-03)"
        confirmLabel={approveLabel}
        pending={approve.isPending}
        onConfirm={({ reason }) => {
          setConfirm(null)
          approve.mutate(reason ?? '')
        }}
        onCancel={() => setConfirm(null)}
      />

      <ConfirmModal
        open={confirm === 'reject'}
        title="이 미리보기를 버릴까요?"
        impact={
          <>
            <p>버리면 이 미리보기는 적재되지 않습니다.</p>
            <p>· 임시 자료는 하루 뒤 삭제됩니다</p>
            <p>· 모든 행위는 활동 로그(AD-011)에 남습니다</p>
          </>
        }
        reason="required"
        reasonPlaceholder="예: 본문이 안내문뿐이라 적재 불필요"
        confirmLabel="버리기"
        pending={reject.isPending}
        onConfirm={({ reason }) => {
          setConfirm(null)
          reject.mutate(reason ?? '')
        }}
        onCancel={() => setConfirm(null)}
      />
    </section>
  )
}
