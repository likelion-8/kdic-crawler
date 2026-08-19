/** AD-004 데이터 파이프라인 : 트리거 · 상태 (Figma 22:493).
 *
 * 구역 4개: R1 상단 안내 + 일괄 작업 버튼 / R2 변경 페이지 알림 / R3 실행 중 파이프라인 / R4 실행 이력.
 * 셸(GNB·헤더·세션)은 app/AdminLayout.tsx가 그린다 — 여기서 다시 그리지 않는다.
 *
 * 지켜야 할 것
 *  - 인덱스를 바꾸는 작업은 한 번에 하나(PIPELINE_CONCURRENCY=1). 실행 중에는 두 버튼이 비활성 + 사유 표기(Desc ⓿)
 *  - 진행 상태 폴링은 isPoll:true — 유휴 세션 타이머를 갱신하면 안 된다(PRD-01 §3)
 *  - 단계를 그림으로 보는 곳은 R3 카드 하나뿐. 실패 상세는 PipelineStepText로 글로만 알린다(Desc ❷)
 *  - 위험 작업은 확인 모달 → 변경 사유 필수 → (필요 시) 비밀번호 재확인 → 실행 (CM-DF-004 03절)
 *  - 실패는 토스트가 아니라 화면 안에 남긴다(CM-DF-001 07.4절) */
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { cn } from '../../lib/utils'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Layers, RefreshCw } from 'lucide-react'
import {
  Badge,
  Button,
  ConfirmModal,
  DEFAULT_PAGE_SIZE,
  DataTable,
  DetailModal,
  EmptyState,
  InfoHint,
  Loading,
  Notice,
  Pagination,
  PipelineSteps,
  Select,
  useToast,
} from '../../components/ui'
import type { Column, StepState } from '../../components/ui'
import { isApiRequestError } from '../../lib/api/client'
import type { ApiError } from '../../lib/api/types'
import type { JobType } from '../../lib/codes'
import { hasRole } from '../../lib/codes'
import { markReauthed, needsReauth, useSession } from '../../app/session'
import { ChangedPagesCard } from './pipeline/ChangedPagesCard'
import { JobFailureDetail, jobFailureMeta, jobFailureTitle } from './pipeline/JobFailureDetail'
import {
  JOB_STATUS_LABEL,
  JOB_STATUS_TONE,
  JOB_TYPE_LABEL,
  cancelJob,
  changesQueryKey,
  createJob,
  fetchEstimate,
  fetchJob,
  fetchJobs,
  formatMonthDayTime,
  isJobActive,
  jobElapsedText,
  jobTargetText,
  jobsQueryKey,
  reauth,
  retryJob,
  rollbackJob,
} from './pipeline/api'
import type { JobStep, PipelineJob } from './pipeline/api'

/** 카드 공통(R3 · R4) — 흰 지면 + 1px 헤어라인. 그림자로 띄우지 않는다 */
const CARD_CLASS = 'rounded-md border bg-card p-5'

/** 진행 상태 폴링 주기. 기획서에 계약이 없어(이슈 G-9 제안값) 3초로 정했다 */
const POLL_MS = 3000

/** 실행 중 버튼 비활성 사유 — 목업 정본 문구 */
const BUSY_REASON = '재색인 작업 실행 중(완료 후 가능)'

/** 확인 모달 안 '실행 중' 행 · 두 모달 공통 문구.
 *
 * 원래 목업 문구는 `기존 인덱스로 검색 계속(서비스 중단 없음)`이었는데 **사실이 아니다** —
 * 현 백엔드는 인덱스를 지우고 제자리에 다시 만든다(AD-004 Desc ❷가 스스로 그렇게 적어놨다).
 * 관리자에게 거짓 안내를 하면 재색인 중 검색이 비는 걸 장애로 오인해 다시 실행하게 된다.
 * 무중단 교체를 구현하면 이 문구를 되돌린다(A-16 확정 2026-08-05). */
const NO_DOWNTIME = '재색인 중에는 검색 결과가 일시적으로 빌 수 있습니다(무중단 교체 미구현)'

/** 사유 입력 아래 각주(모달 안 상시 노출) */
const REASON_NOTE = '※사유는 관리자 활동 로그에 그대로 기록됩니다. 비워두면 실행 버튼이 비활성'

/** 청킹 모드 4종 — src/crawler/chunking.build_units 의 mode 와 1:1(2026-08-18, 미구현 ④ 해소).
 * 서버(admin_pipeline.CHUNK_MODES)가 같은 집합으로 검증한다. 운영 기본은 all */
const CHUNK_MODES = [
  { value: 'all', label: 'all — FAQ·표 구조 인식(운영 기본)' },
  { value: 'page', label: 'page — 페이지 통째로 1청크' },
  { value: 'faq_atomic', label: 'faq_atomic — FAQ만 Q/A 쌍으로' },
  { value: 'table_row', label: 'table_row — 표만 행 묶음으로' },
]

const STEP_STATE: Record<JobStep['status'], StepState> = {
  QUEUED: 'waiting',
  RUNNING: 'running',
  SUCCESS: 'done',
  FAILED: 'failed',
  SKIPPED: 'waiting',
}

/** 확인 모달이 다루는 위험 작업 6종 */
type Confirming =
  | { kind: 'FULL_RECRAWL' }
  | { kind: 'REINDEX' }
  | { kind: 'SELECTED_RECRAWL'; pageIds: string[] }
  | { kind: 'CANCEL'; job: PipelineJob }
  | { kind: 'RETRY'; job: PipelineJob }
  | { kind: 'ROLLBACK'; job: PipelineJob }

const CREATE_KINDS = new Set(['FULL_RECRAWL', 'REINDEX', 'SELECTED_RECRAWL'])

export function Pipeline() {
  const { session } = useSession()
  const showToast = useToast()
  const queryClient = useQueryClient()

  const canRun = hasRole(session?.role, 'OPERATOR') // 파이프라인 실행·취소·재시도
  const canRollback = hasRole(session?.role, 'ADMIN') // 롤백은 ADMIN (CM-DF-004 03절)
  const canViewActivity = hasRole(session?.role, 'ADMIN') // AD-011 조회 권한

  const [page, setPage] = useState(1)
  const [confirming, setConfirming] = useState<Confirming | null>(null)
  const [chunkMode, setChunkMode] = useState('all')
  const [openDetailId, setOpenDetailId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<ApiError | null>(null)

  const jobs = useQuery({
    queryKey: [...jobsQueryKey, page],
    queryFn: () => fetchJobs(page, DEFAULT_PAGE_SIZE, false),
  })

  // 진행 중 작업은 이력 페이지 이동과 무관해야 한다(Desc ⓿ — 실행 중에는 두 버튼이 계속 비활성).
  // 동시 실행은 1개(PIPELINE_CONCURRENCY=1)이고 최신순 정렬이라 진행 중 작업은 항상 1페이지에 있다.
  // page=1이면 위 쿼리와 키가 같아 요청이 늘지 않는다
  const firstPage = useQuery({
    queryKey: [...jobsQueryKey, 1],
    queryFn: () => fetchJobs(1, DEFAULT_PAGE_SIZE, false),
  })

  const activeInList = firstPage.data?.items.find(isJobActive)

  // 진행 중 작업만 따로 폴링한다. 목록 전체를 3초마다 다시 부르면 조회가 활동 로그에 계속 쌓인다
  const activeJob = useQuery({
    queryKey: ['admin', 'pipeline', 'job', activeInList?.id],
    queryFn: () => fetchJob(activeInList!.id),
    enabled: activeInList !== undefined,
    refetchInterval: (query) => (query.state.data && !isJobActive(query.state.data) ? false : POLL_MS),
  })

  // 작업이 끝나면 이력 목록을 한 번 갱신해 상태 칩·소요를 맞춘다
  const finishedId = activeJob.data && !isJobActive(activeJob.data) ? activeJob.data.id : undefined
  useEffect(() => {
    if (!finishedId) return
    void queryClient.invalidateQueries({ queryKey: jobsQueryKey })
    // 변경 감지·재수집이 끝나면 변경 페이지 목록도 갱신 — 감지 결과(PENDING 표시)와
    // 재수집 후 해소된 항목이 카드에 반영되어야 관리자가 새로고침을 누르지 않는다
    void queryClient.invalidateQueries({ queryKey: changesQueryKey })
  }, [finishedId, queryClient])

  const running = activeJob.data ?? activeInList
  const busyReason = running ? BUSY_REASON : undefined

  // 모달을 연 뒤 대상 건수·예상 소요를 채운다(이슈 G-23)
  const estimateType = confirming && CREATE_KINDS.has(confirming.kind) ? (confirming.kind as JobType) : undefined
  const estimate = useQuery({
    queryKey: ['admin', 'pipeline', 'estimate', estimateType],
    queryFn: () => fetchEstimate(estimateType!),
    enabled: estimateType !== undefined,
  })

  const action = useMutation({
    mutationFn: async ({ reason, password }: { reason?: string; password?: string }) => {
      if (!confirming) return
      // 3단 플로우 ③ — 마지막 인증 후 30분이 지난 고위험 작업만 비밀번호를 다시 받는다
      if (password) {
        await reauth(password)
        markReauthed()
      }
      const why = reason ?? ''
      switch (confirming.kind) {
        case 'FULL_RECRAWL':
          return createJob({ type: 'FULL_RECRAWL', reason: why })
        case 'REINDEX':
          return createJob({ type: 'REINDEX', reason: why, chunk_mode: chunkMode })
        case 'SELECTED_RECRAWL':
          return createJob({ type: 'SELECTED_RECRAWL', targets: confirming.pageIds, reason: why })
        case 'CANCEL':
          return cancelJob(confirming.job.id, why)
        case 'RETRY':
          return retryJob(confirming.job.id, why)
        case 'ROLLBACK':
          return rollbackJob(confirming.job.id, why)
      }
    },
    onSuccess: () => {
      if (confirming) showToast(SUCCESS_TOAST[confirming.kind])
      setConfirming(null)
      setActionError(null)
      setOpenDetailId(null)
      void queryClient.invalidateQueries({ queryKey: jobsQueryKey })
      void queryClient.invalidateQueries({ queryKey: changesQueryKey })
    },
    onError: (error) => {
      // 권한을 숨겨도 403은 온다(PRD-02 §3-d). 문구는 서버 user_message 그대로.
      // 모달을 닫지 않는다 — 실패를 토스트로 흘리지 않고 사유 입력값과 함께 화면에 남긴다(07.4절)
      setActionError(
        isApiRequestError(error)
          ? error.error
          : {
              code: 'INTERNAL',
              user_message: '처리 중 오류가 발생했습니다.',
              retryable: false,
              fallback_sources: [],
              request_id: '',
            },
      )
    },
  })

  const openDetail = jobs.data?.items.find((j) => j.id === openDetailId)
  // 긴급 롤백은 '직전 정상 버전' 하나뿐이라 최신순 1페이지에서만 찾는다(REQ-OPS-003)
  const latestSuccessId = page === 1 ? jobs.data?.items.find((j) => j.status === 'SUCCESS')?.id : undefined

  const columns: Column<PipelineJob>[] = [
    {
      key: 'time',
      header: '시각',
      render: (j) => <span className="nums">{formatMonthDayTime(j.created_at)}</span>,
      width: '128px',
    },
    {
      key: 'type',
      header: '유형',
      width: '130px',
      render: (j) => (
        <span>
          {JOB_TYPE_LABEL[j.type]}
          {/* 적재 파라미터 — 운영 기본(all)이 아닐 때만 표기해 "어느 청킹으로 돌렸나"를 남긴다 */}
          {j.params?.chunk_mode && j.params.chunk_mode !== 'all' && (
            <span className="ml-1 text-xs text-muted-foreground">· {j.params.chunk_mode}</span>
          )}
        </span>
      ),
    },
    { key: 'target', header: '대상', render: (j) => jobTargetText(j) },
    {
      key: 'status',
      header: '상태',
      width: '110px',
      render: (j) => (
        <span className="inline-flex items-center gap-1.5">
          {/* 진행 중 행만 점이 숨쉰다 — 상태 라벨은 배지가 이미 텍스트로 알린다 */}
          {isJobActive(j) && (
            <span className="pulse-dot size-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
          )}
          <Badge tone={JOB_STATUS_TONE[j.status]} kind="status">
            {JOB_STATUS_LABEL[j.status]}
          </Badge>
        </span>
      ),
    },
    // 게이트 판정 — 완료 후에도 남는다. 실행 카드의 판정 줄은 진행 중에만 보여서, 관리자가
    // 자리를 비운 사이 끝나면 놓친다. 이력 행에서 통과/미달과 수치를 그대로 읽는다(2026-08-18)
    {
      key: 'gate',
      header: '게이트',
      width: '150px',
      render: (j) => {
        const v = j.steps.find((s) => s.name === '게이트')?.detail
        if (!v) return <span className="text-muted-foreground">—</span>
        return (
          <span
            className={cn('nums text-xs', v.passed ? '' : 'text-destructive')}
            title={v.summary}
          >
            {v.passed ? '통과' : '미달'} · R@5 {v.metrics['recall@5']} · MRR {v.metrics.mrr}
          </span>
        )
      },
    },
    // 진행 중은 소요가 확정되지 않아 '—' (목업 표기 그대로)
    {
      key: 'elapsed',
      header: '소요',
      render: (j) => <span className="nums">{jobElapsedText(j) ?? '—'}</span>,
      width: '96px',
    },
    { key: 'actor', header: '실행자', render: (j) => j.created_by, width: '120px' },
  ]

  return (
    <div className="flex flex-col gap-6">
      {/* R1 — 상단 안내 + 일괄 작업 버튼 */}
      <section className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        {/* 대상 범위 설명은 한 번 알면 되는 규칙인데 420px짜리 문단으로 두면 좁은 폭에서
            버튼 묶음이 아래로 튕겨 justify-between이 무력해진다 — 버튼 줄 안 ⓘ로 접는다.
            기획서 원문(`일괄 작업 : 전체 대상 · 고비용, 실행 전 확인 모달 | …`)은 '확인 모달' 같은
            화면 규격이 섞여 있어 문장으로 고쳤다(기획서 정정 대상) */}
        {canRun && (
          <div className="ml-auto flex items-center gap-2">
            <InfoHint label="일괄 작업 대상 범위 설명">
              아래 버튼은 지식베이스 전체를 대상으로 합니다. 페이지 하나만 다시 받으려면
              지식베이스 상세에서 [재수집]을 쓰세요.
            </InfoHint>
            <Button
              onClick={() => setConfirming({ kind: 'FULL_RECRAWL' })}
              disabled={busyReason !== undefined}
              disabledReason={busyReason}
            >
              <RefreshCw aria-hidden="true" />
              전체 재수집
            </Button>
            <Button
              onClick={() => setConfirming({ kind: 'REINDEX' })}
              disabled={busyReason !== undefined}
              disabledReason={busyReason}
            >
              <Layers aria-hidden="true" />
              재적재
            </Button>
          </div>
        )}
      </section>

      {/* R2 — 변경 페이지 알림 */}
      <ChangedPagesCard
        canRun={canRun}
        disabledReason={busyReason}
        onRecrawl={(pageIds) => setConfirming({ kind: 'SELECTED_RECRAWL', pageIds })}
      />

      {/* R3 — 실행 중 파이프라인 (단계를 그림으로 보는 유일한 곳) */}
      <section className={CARD_CLASS} aria-labelledby="pipeline-run-title">
        <h2 className="mb-4 text-[13px] font-semibold tracking-[-0.01em]" id="pipeline-run-title">
          파이프라인
        </h2>
        {running ? (
          <>
            {/* 실행 중에는 단계 그림이 이 카드의 주인공 — 색면 대신 위아래 헤어라인으로 구획한다 */}
            <div className="border-y py-3.5">
              <PipelineSteps states={running.steps.map((s) => STEP_STATE[s.status])} />
            </div>
            <GateVerdictLine job={running} />
            <p className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
              {/* 실행 중 상태 점 — 카드가 살아있음을 알린다. 색만이 아니라 이 캡션 텍스트와 병기 */}
              <span className="pulse-dot size-1.5 shrink-0 rounded-full bg-primary" aria-hidden="true" />
              {/* CM-DF-002 06절: QUEUED=대기 · RUNNING=진행 중. 워커가 죽어도 '실행 중'으로 읽히던 오표기 수정 */}
              {running.status === 'RUNNING' ? '실행 중' : '대기 중 (실행 시작 대기)'}
              {/* 교체·실패 정책은 지금 상태가 아니라 규칙이라 접는다 */}
              <InfoHint label="인덱스 교체 정책 설명" size="sm">
                6단계까지 모두 통과하면 인덱스를 한 번에 교체합니다. 실패하면 기존 인덱스를 그대로
                유지하고, 성공하면 캐시를 비웁니다.
              </InfoHint>
            </p>
            {canRun && isJobActive(running) && (
              <div className="mt-3 flex justify-end">
                <Button size="sm" onClick={() => setConfirming({ kind: 'CANCEL', job: running })}>
                  취소
                </Button>
              </div>
            )}
          </>
        ) : (
          // 진행 중 작업이 없어도 **단계 그림을 기본으로 보여준다**(2026-08-04 사용자 요청).
          // 회색 빈 상자만 뜨면 이 화면의 주인공(6단계 파이프라인)이 평소엔 아예 안 보이고,
          // 무엇이 어떤 순서로 도는지도 실행 중에만 알 수 있었다. 전부 '대기'로 그린다.
          // 진행 중 작업이 없을 때의 카피는 기획서에 없어 프론트가 썼다
          <>
            <div className="border-y py-3.5">
              {/* states를 비우면 PipelineSteps가 6단계를 전부 '대기'로 그린다 */}
              <PipelineSteps states={[]} />
            </div>
            <p className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
              진행 중인 작업이 없습니다
              <InfoHint label="인덱스 교체 정책 설명" size="sm">
                6단계까지 모두 통과하면 인덱스를 한 번에 교체합니다. 실패하면 기존 인덱스를 그대로
                유지하고, 성공하면 캐시를 비웁니다.
              </InfoHint>
            </p>
          </>
        )}
      </section>

      {/* R4 — 실행 이력 */}
      <section className={CARD_CLASS} aria-labelledby="pipeline-history-title">
        <h2 className="mb-4 text-[13px] font-semibold tracking-[-0.01em]" id="pipeline-history-title">
          실행 이력
        </h2>
        {jobs.isPending ? (
          <Loading text="실행 이력을 불러오는 중…" />
        ) : jobs.isError ? (
          // 실패는 화면 안에 남긴다(07.4절) — 색은 아이콘에만, 본문은 잉크
          <div role="alert">
            <Notice
              tone="danger"
              variant="block"
              action={
                // 다시 눌러도 결과가 같은 오류(403·409 등)에는 재시도를 권하지 않는다(client.ts 규약)
                isApiRequestError(jobs.error) && jobs.error.error.retryable ? (
                  <Button size="sm" onClick={() => void jobs.refetch()}>
                    다시 시도
                  </Button>
                ) : undefined
              }
            >
              {isApiRequestError(jobs.error)
                ? jobs.error.error.user_message
                : '실행 이력을 불러오지 못했습니다.'}
            </Notice>
          </div>
        ) : (
          <>
            <DataTable
              caption="파이프라인 실행 이력 — 시각 · 유형 · 대상 · 상태 · 소요 · 실행자"
              columns={columns}
              rows={jobs.data.items}
              rowKey={(j) => j.id}
              rowState={(j) =>
                j.id === openDetailId ? 'selected' : j.status === 'FAILED' ? 'danger' : 'default'
              }
              onRowClick={(j) => j.status === 'FAILED' && setOpenDetailId(j.id)}
              // 실패 행만 열린다 — 이 prop을 안 넘기면 모든 행에 클릭 커서가 떠
              // 눌러도 아무 일이 없는 행을 누르게 된다 (B-42 확정 2026-08-05)
              rowClickable={(j) => j.status === 'FAILED'}
              empty={<EmptyState title="실행 이력이 없습니다" />}
              actions={(j) => (
                <span className="inline-flex gap-1.5">
                  {j.status === 'FAILED' && (
                    <Button size="sm" onClick={() => setOpenDetailId(j.id)}>
                      상세
                    </Button>
                  )}
                  {canRun && isJobActive(j) && (
                    <Button size="sm" onClick={() => setConfirming({ kind: 'CANCEL', job: j })}>
                      취소
                    </Button>
                  )}
                  {/* 긴급 롤백은 '직전 정상 버전' 하나에만 허용된다(REQ-OPS-003) */}
                  {canRollback && j.id === latestSuccessId && (
                    <Button size="sm" onClick={() => setConfirming({ kind: 'ROLLBACK', job: j })}>
                      롤백
                    </Button>
                  )}
                </span>
              )}
            />
            <div className="mt-4 flex justify-center">
              <Pagination page={page} total={jobs.data.total} pageSize={jobs.data.size} onPageChange={setPage} />
            </div>
          </>
        )}
      </section>

      {/* 실패 상세도 다른 화면과 같이 모달로 뜬다 — 이력 표 아래에 두면 [상세]를 눌러도
          화면 밖이라 아무 일도 안 일어난 것처럼 보인다(사유는 DetailModal 주석) */}
      <DetailModal
        open={openDetail !== undefined}
        title={openDetail ? jobFailureTitle(openDetail) : '실패 상세'}
        meta={openDetail ? jobFailureMeta(openDetail) : undefined}
        onClose={() => setOpenDetailId(null)}
      >
        {openDetail && (
          <JobFailureDetail
            job={openDetail}
            canRun={canRun}
            canViewActivity={canViewActivity}
            onRetry={(job) => setConfirming({ kind: 'RETRY', job })}
            onCopied={() => showToast('오류 로그를 복사했습니다')}
          />
        )}
      </DetailModal>

      {confirming && (
        <ConfirmModal
          open
          variant={confirming.kind === 'ROLLBACK' ? 'danger' : 'normal'}
          title={MODAL_TITLE[confirming.kind]}
          reason="required"
          reasonPlaceholder={MODAL_PLACEHOLDER[confirming.kind]}
          reasonNote={REASON_NOTE}
          reauth={confirming.kind === 'ROLLBACK' && session !== null && needsReauth(session)}
          confirmLabel={MODAL_CONFIRM[confirming.kind]}
          pending={action.isPending}
          onCancel={() => {
            setConfirming(null)
            setActionError(null)
          }}
          onConfirm={(payload) => {
            setActionError(null)
            action.mutate(payload)
          }}
          impact={
            <ModalImpact
              confirming={confirming}
              error={actionError}
              targetCount={estimate.data?.target_count}
              minutes={estimate.data?.estimated_minutes}
              loading={estimate.isPending}
              failed={estimate.isError}
              chunkMode={chunkMode}
              onChunkModeChange={setChunkMode}
            />
          }
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------- 모달 문구

/** 목업에 제목이 있는 건 전체 재수집·재적재 2종뿐. 나머지 4종은 같은 어투로 프론트가 썼다 */
const MODAL_TITLE: Record<Confirming['kind'], string> = {
  FULL_RECRAWL: '전체 재수집을 실행할까요?',
  REINDEX: '재적재를 실행할까요?',
  SELECTED_RECRAWL: '선택한 페이지를 재수집할까요?',
  CANCEL: '실행 중인 작업을 취소할까요?',
  RETRY: '같은 조건으로 다시 실행할까요?',
  ROLLBACK: '직전 정상 버전으로 되돌릴까요?',
}

const MODAL_CONFIRM: Record<Confirming['kind'], string> = {
  FULL_RECRAWL: '전체 재수집 실행',
  REINDEX: '재적재 실행',
  SELECTED_RECRAWL: '선택 재수집 실행',
  CANCEL: '작업 취소',
  RETRY: '재시도 실행',
  ROLLBACK: '긴급 롤백 실행',
}

const MODAL_PLACEHOLDER: Record<Confirming['kind'], string> = {
  FULL_RECRAWL: '예: 분기 정기 재수집',
  REINDEX: '예: 청킹 모드 변경 반영',
  SELECTED_RECRAWL: '예: 원본 본문 변경 반영',
  CANCEL: '예: 잘못된 대상으로 실행함',
  RETRY: '예: 원본 사이트 복구 확인 후 재실행',
  ROLLBACK: '예: 운영 중 답변 품질 급락 확인',
}

const SUCCESS_TOAST: Record<Confirming['kind'], string> = {
  FULL_RECRAWL: '전체 재수집을 시작했습니다',
  REINDEX: '재적재를 시작했습니다',
  SELECTED_RECRAWL: '선택 재수집을 시작했습니다',
  CANCEL: '작업을 취소했습니다',
  RETRY: '재시도를 시작했습니다',
  ROLLBACK: '긴급 롤백을 시작했습니다',
}

interface ModalImpactProps {
  confirming: Confirming
  /** 실행 실패. 모달을 닫지 않고 여기에 남긴다 */
  error: ApiError | null
  targetCount?: number
  minutes?: number
  loading: boolean
  failed: boolean
  chunkMode: string
  onChunkModeChange: (value: string) => void
}

/** 확인 모달 ②영향 고지 슬롯 — 요약 KV 표 + 흐름 줄 + 사유 각주 (B-6 · B-7) */
function ModalImpact({
  confirming,
  error,
  targetCount,
  minutes,
  loading,
  failed,
  chunkMode,
  onChunkModeChange,
}: ModalImpactProps) {
  // 실행 실패는 모달을 닫지 않고 여기 남긴다(07.4절). 문구는 서버 user_message 그대로
  const errorLine = error && (
    <div role="alert">
      <Notice tone="danger" variant="block">
        {error.user_message}
      </Notice>
    </div>
  )

  if (confirming.kind === 'CANCEL') {
    return (
      <div className="space-y-3">
        {errorLine}
        <p className="text-[13px]">
          대기 중 작업은 즉시, 실행 중 작업은 인덱스 교체 전까지 취소할 수 있습니다.
        </p>
      </div>
    )
  }
  if (confirming.kind === 'RETRY') {
    return (
      <div className="space-y-3">
        {errorLine}
        <p className="text-[13px]">같은 조건으로 새 작업을 만들어 즉시 다시 실행합니다.</p>
      </div>
    )
  }
  if (confirming.kind === 'ROLLBACK') {
    return (
      <div className="space-y-3">
        {errorLine}
        <p className="text-[13px]">
          긴급 롤백은 회귀·Smoke 없이 직전 정상 버전 하나로 되돌립니다. 되돌린 뒤 24시간 안에 회귀·Smoke를
          사후 실행해 결과를 기록합니다. (REQ-OPS-003)
        </p>
      </div>
    )
  }

  // 서버 값이 오기 전/실패했을 때의 표기가 기획서에 없어(이슈 G-23) 프론트가 정했다
  const count = loading ? '확인 중…' : failed || targetCount === undefined ? '확인할 수 없음' : targetCount
  const eta = loading ? '확인 중…' : failed || minutes === undefined ? '확인할 수 없음' : `약 ${minutes}분`

  return (
    <div className="space-y-3">
      {errorLine}
      {/* 회색 색면 대신 헤어라인으로 나뉜 스펙 시트 한 장 */}
      <dl className="divide-y border-y">
        <div className="grid grid-cols-[72px_1fr] gap-3 py-2 text-[13px]">
          <dt className="text-muted-foreground">대상</dt>
          <dd>
            {confirming.kind === 'FULL_RECRAWL' && `수집 대상 ${count}페이지 전체(본문이 같은 페이지는 건너뜀)`}
            {confirming.kind === 'REINDEX' && `현재 문서 ${count}건(재크롤링 없이 청킹 · 임베딩부터 다시)`}
            {confirming.kind === 'SELECTED_RECRAWL' &&
              `변경 감지 ${confirming.pageIds.length}페이지(선택한 항목만 재수집)`}
          </dd>
        </div>

        {confirming.kind === 'REINDEX' && (
          <div className="grid grid-cols-[72px_1fr] gap-3 py-2 text-[13px]">
            <dt className="text-muted-foreground">적재 설정</dt>
            <dd className="flex flex-wrap items-center gap-3">
              <Select
                label="청킹 모드"
                value={chunkMode}
                options={CHUNK_MODES}
                // 청킹이 규칙 기반이라 글자 수를 지정할 수 없다(CM-DF-003 05절).
                // 560px 모달 안에서 이 한 줄이 셀렉트를 밀어 두 줄로 접히게 했다
                hint="청크 크기는 규칙에 따라 자동으로 정해져 여기서 바꿀 수 없습니다. 비워 두면 현행 설정을 그대로 씁니다."
                onChange={onChunkModeChange}
              />
            </dd>
          </div>
        )}

        <div className="grid grid-cols-[72px_1fr] gap-3 py-2 text-[13px]">
          <dt className="text-muted-foreground">예상 소요</dt>
          <dd>{confirming.kind === 'REINDEX' ? `${eta} + 홀드아웃 평가` : eta}</dd>
        </div>
        <div className="grid grid-cols-[72px_1fr] gap-3 py-2 text-[13px]">
          <dt className="text-muted-foreground">실행 중</dt>
          <dd>{NO_DOWNTIME}</dd>
        </div>
      </dl>

      {/* 흐름 줄의 강조는 색이 아니라 굵기로 — 보라는 Primary·링크·포커스·현재 위치·차트 주계열에만 */}
      <p className="text-xs text-muted-foreground">
        {confirming.kind === 'REINDEX' ? (
          <>
            {/* 게이트는 색인을 막지 않는다(2026-08-19 정책 변경) — 판정은 경고로만 남는다.
                임시 색인은 만들지 않고 메모리 채점(src/index_gate.py)한다 */}
            청킹 → 검증 → <span className="font-medium text-foreground">게이트(홀드아웃 평가)</span>{' '}
            → 색인·반영 · 캐시 무효화 (게이트 미달은 경고로만 표시)
          </>
        ) : (
          <>
            수집 → 변환 → 청킹 → 검증 →{' '}
            <span className="font-medium text-foreground">게이트(홀드아웃 평가)</span> → 색인·반영(교체 · 캐시
            무효화 · 게이트 미달은 경고로만 표시)
          </>
        )}
      </p>
    </div>
  )
}

/**
 * 게이트 판정 줄 — 실행 카드 안에서 통과/미달과 수치를 그대로 보여준다(2026-08-18).
 * 판정은 워커가 게이트 단계의 detail 로 남긴다(src/worker.py _gate). 미달이어도 색인은
 * 진행된다(2026-08-19 정책 변경) — 경고를 명시해 회귀 가능성을 인지시킨다. 상세는 AD-006 으로.
 */
function GateVerdictLine({ job }: { job: PipelineJob }) {
  const gate = job.steps.find((s) => s.name === '게이트')
  const v = gate?.detail
  if (!v) return null
  return (
    <p className={cn('mt-3 text-[13px]', v.passed ? 'text-foreground' : 'text-destructive')}>
      게이트 {v.passed ? '통과' : '미달'} · {v.summary}
      {!v.passed && ' — ⚠ 미달 상태로 색인이 반영되었습니다. 회귀 여부를 확인하세요'}
      {' · '}
      <Link className="underline" to="/admin/evaluation">
        평가 화면에서 판정 상세 →
      </Link>
    </p>
  )
}
