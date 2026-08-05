/** AD-004 B-8 — 실행 이력의 실패 행을 열었을 때의 상세 패널 (Description ❸).
 * "실패 상세는 멈춘 지점을 '6단계 중 5번째'처럼 글로만 알려 같은 그림을 두 번 그리지 않습니다" (❷)
 *  → 여기서는 PipelineSteps(그림)를 쓰지 않고 PipelineStepText만 쓴다.
 * "화면에는 정해진 문구만 노출하고 예외 원문은 보여주지 않습니다" (❸)
 *  → error.detail(예외 원문)은 렌더하지 않고 CM-DF-002 06절 JOB_ERROR_MESSAGE만 쓴다. */
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { Copy, History, RotateCcw } from 'lucide-react'
import { Button, Notice, PipelineStepText } from '../../../components/ui'
import { JOB_ERROR_MESSAGE, JOB_ERROR_RETRY } from '../../../lib/codes'
import { PIPELINE_STEPS } from '../../../lib/constants'
import {
  JOB_TYPE_LABEL,
  formatMonthDayTime,
  jobElapsedText,
  jobTargetCount,
  stageNumber,
  stageWithIndex,
} from './api'
import type { PipelineJob } from './api'

/** '인덱스 영향' 정본 문구 — 인덱스 교체(마지막 '반영' 단계) 전에 멈춘 실패에만 쓸 수 있다 */
const INDEX_IMPACT = '없음(교체 전 실패라 기존 인덱스로 정상 서비스 중)'

/** 교체 이후(또는 실패 단계를 모를 때)는 단언하지 않는다 — 서버가 index_impact를 주면 그 값이 우선 */
const INDEX_IMPACT_UNKNOWN = '확인할 수 없음'

/** 인덱스를 실제로 교체하는 단계 — PIPELINE_STEPS의 마지막('반영') */
const SWAP_STEP = PIPELINE_STEPS[PIPELINE_STEPS.length - 1]

/** 클립보드 거부(비보안 컨텍스트·권한 거부) 시 화면에 남길 문구 — 기획서에 없어 프론트가 썼다 */
const COPY_FAILED = '오류 로그를 복사하지 못했습니다'

export interface JobFailureDetailProps {
  job: PipelineJob
  /** [재시도] — 확인 모달은 부모가 연다 */
  onRetry: (job: PipelineJob) => void
  /** OPERATOR 미만이면 [재시도]를 숨긴다 */
  canRun: boolean
  /** 활동 로그(AD-011) 조회 권한은 ADMIN */
  canViewActivity: boolean
  onCopied: () => void
}

export function JobFailureDetail({
  job,
  onRetry,
  canRun,
  canViewActivity,
  onCopied,
}: JobFailureDetailProps) {
  const navigate = useNavigate()
  const [copyFailed, setCopyFailed] = useState(false)
  const code = job.error?.code ?? 'INTERNAL'
  const stage = job.error?.stage ?? job.steps.find((s) => s.status === 'FAILED')?.name ?? ''
  // {단계} 자리 치환 — STAGE_TIMEOUT만 자리표시자를 가진다
  const reasonText = JOB_ERROR_MESSAGE[code].replace('{단계}', stage)
  const autoRetryText = JOB_ERROR_RETRY[code]
    ? '1회 자동으로 다시 시도했으나 실패했습니다'
    : `없음(${code}은 재시도 대상이 아님)`
  // `수집 58 · 변환 58 · 청킹 494 · 색인 단계에서 중단` — 건수는 서버가 줄 때만 붙인다(B-8)
  const doneStages = job.steps
    .filter((s) => s.status === 'SUCCESS')
    .map((s) => (s.count === undefined ? s.name : `${s.name} ${s.count}`))
  const progressText = [...doneStages, `${stage} 단계에서 중단`].join(' · ')
  const indexImpact =
    job.index_impact ?? (stage !== '' && stage !== SWAP_STEP ? INDEX_IMPACT : INDEX_IMPACT_UNKNOWN)

  const rows: [string, string, boolean][] = [
    ['실패 단계', stageWithIndex(stage), true],
    ['오류 코드', code, true],
    ['오류 사유', reasonText, false],
    ['자동 재시도', autoRetryText, false],
    ['인덱스 영향', indexImpact, false],
    ['처리 실적', progressText, false],
  ]

  async function copyLog() {
    try {
      await navigator.clipboard.writeText(
        [`job_id : ${job.id}`, ...rows.map(([label, value]) => `${label} : ${value}`)].join('\n'),
      )
      setCopyFailed(false)
      onCopied()
    } catch {
      // 실패는 토스트가 아니라 화면 안에 남긴다(CM-DF-001 07.4절)
      setCopyFailed(true)
    }
  }

  return (
    // 제목·job_id·소요는 DetailModal 헤더가, [닫기]는 모달 우상단 ✕가 맡는다.
    // 실패라는 사실은 부제의 '실패' 라벨과 아래 오류 정보 표가 글로 말한다
    <div aria-label="실패 상세">
      <h4 className="mb-2 text-[13px] font-semibold">오류 정보</h4>
      <dl className="divide-y border-y">
        {rows.map(([label, value, strong]) => (
          <div className="grid grid-cols-[150px_1fr] gap-3 py-2 text-[13px]" key={label}>
            <dt className="text-muted-foreground">{label}</dt>
            {/* 실패 단계·오류 코드는 목업에서 빨강 bold. 색만으로 알리지 않도록 라벨이 항상 붙어 있다 */}
            <dd className={strong ? 'font-semibold text-danger-fg' : undefined}>
              {value}
              {label === '실패 단계' && (
                <span className="font-normal text-muted-foreground">
                  {' ('}
                  <PipelineStepText step={stageNumber(stage)} />
                  {')'}
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>

      <h4 className="mt-5 mb-2 text-[13px] font-semibold">조치</h4>
      <div className="flex flex-wrap items-center gap-2">
        {canRun && (
          <Button size="sm" onClick={() => onRetry(job)}>
            <RotateCcw aria-hidden="true" />
            재시도
          </Button>
        )}
        <Button size="sm" onClick={() => void copyLog()}>
          <Copy aria-hidden="true" />
          오류 로그 복사
        </Button>
        {/* 조치 버튼 3개는 같은 규격(아웃라인)이다(B-8) — 링크가 아니라 버튼으로 이동한다 */}
        {canViewActivity && (
          <Button
            size="sm"
            onClick={() => void navigate(`/admin/settings/activity?q=${encodeURIComponent(job.id)}`)}
          >
            <History aria-hidden="true" />
            작업 기록 보기
          </Button>
        )}
      </div>
      {copyFailed && (
        // 복사 실패는 화면 안에 남긴다(07.4절). 조치 버튼 3개는 위 자리를 지키고, 결과만 여기 붙는다
        <div className="mt-3" role="alert">
          <Notice tone="danger" variant="block">
            {COPY_FAILED}
          </Notice>
        </div>
      )}
    </div>
  )
}

/** 모달 헤더용 제목·부제.
 *  포맷 `{시각} · {유형} (대상 {N}건)` — 건수를 모르면 괄호를 붙이지 않는다(B-8) */
export const jobFailureTitle = (job: PipelineJob) => {
  const count = jobTargetCount(job)
  return `${formatMonthDayTime(job.created_at)} · ${JOB_TYPE_LABEL[job.type]}${
    count !== undefined ? ` (대상 ${count}건)` : ''
  }`
}
export const jobFailureMeta = (job: PipelineJob) =>
  `실패 · job_id ${job.id} · 실행자 ${job.created_by} · 소요 ${jobElapsedText(job) ?? '—'}`
