/** 답변 피드백 — CB-002 마커 8 · Case 3-1(사유 입력) · Case 3-2(등록 완료).
 *
 * 2단 플로우: 👍/👎는 누르는 즉시 `POST /api/feedback`으로 기록되고,
 * 사유 칩·자유 의견은 그 뒤 `PATCH /api/feedback/{feedback_id}`로 보완한다. 답변당 최종 1건(upsert).
 *
 * `FeedbackRequest.request_id`는 '피드백을 붙일 답변'의 id다. client.ts는 body에 request_id가
 * 이미 있으면 멱등키로 덮지 않으므로, 아래 body의 값이 그대로 서버에 도달한다 — 답변당 1건(upsert)의 키. */
import { useId, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { REASON_CODES, REASON_CODE_LABEL } from '../../lib/codes'
import type { ReasonCode } from '../../lib/codes'
import { FEEDBACK_FREETEXT_MAX } from '../../lib/constants'
import { apiRequest, isApiRequestError } from '../../lib/api/client'
import type { FeedbackResponse } from '../../lib/api/types'
import { Button, useToast } from '../ui'
import { Textarea } from '../shadcn/textarea'
import { cn } from '@/lib/utils'

export interface FeedbackWidgetProps {
  /** 피드백을 붙일 답변의 request_id */
  requestId: string
  sessionId: string
}

type Vote = 'up' | 'down'

/** 등록 완료 카드에 다시 보여줄 값 (CB-002 Case 3-2) */
interface Submitted {
  reason: ReasonCode | null
  comment: string
}

/** 사유 칩 — 알약 대신 각진 태그(4px). 선택 상태는 색이 아니라 aria-pressed·굵기·잉크 대비로 구분된다.
 *
 * 높이 36px + after 확장 4px = 터치 타깃 44px(CM-DF-004 09절).
 * 목업 26px을 그대로 쓰면 확장이 9px씩 필요하고, 두 줄이 겹치지 않으려면 행 간격이 20px이나
 * 벌어져 칩 사이가 텅 빈다(사용자 지적). 칩을 키워 확장을 줄이면 같은 44px을 지키면서
 * 행 간격을 8px까지 좁힐 수 있다 — 겹침 없이 정확히 맞물린다(4+4=8). */
const CHIP =
  "relative inline-flex min-h-9 items-center rounded border px-2.5 text-xs transition-colors duration-200 after:absolute after:-inset-x-0.5 after:-inset-y-1 after:content-[''] aria-pressed:border-foreground aria-pressed:bg-muted aria-pressed:font-bold aria-pressed:text-foreground"

/** 👍👎 투표 버튼 — 말풍선 **아래** 한 줄에 시각과 마주 보고 앉는다.
 * 그 자리에서는 테두리 없는 회색 글자가 부유물처럼 보여서, 말풍선 카드와 같은 언어(헤어라인 +
 * 흰 바탕 + 6px 라운드)로 세운다. 색은 쓰지 않는다 — 선택 상태는 잉크 대비와 굵기가 진다. */
const VOTE =
  "relative inline-flex min-h-8 items-center gap-1.5 rounded-md border border-border bg-card px-2.5 text-xs text-muted-foreground transition-colors duration-200 hover:border-foreground/30 hover:text-foreground after:absolute after:-inset-x-0.5 after:-inset-y-2 after:content-[''] aria-pressed:border-foreground aria-pressed:font-bold aria-pressed:text-foreground disabled:cursor-not-allowed disabled:opacity-60"

export function FeedbackWidget({ requestId, sessionId }: FeedbackWidgetProps) {
  const toast = useToast()
  const commentId = useId()
  const hintId = `${commentId}-hint`

  const [vote, setVote] = useState<Vote | null>(null)
  const [feedbackId, setFeedbackId] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [reason, setReason] = useState<ReasonCode | null>(null)
  const [comment, setComment] = useState('')
  const [submitted, setSubmitted] = useState<Submitted | null>(null)

  const voteMutation = useMutation({
    mutationFn: (next: Vote) =>
      apiRequest<FeedbackResponse>('/api/feedback', {
        method: 'POST',
        body: { answer_request_id: requestId, session_id: sessionId, vote: next },
      }),
  })

  const patchMutation = useMutation({
    mutationFn: (body: { reason_codes: ReasonCode[]; comment?: string }) =>
      apiRequest<FeedbackResponse>(`/api/feedback/${feedbackId ?? ''}`, { method: 'PATCH', body }),
  })

  /** 실패 문구는 서버 user_message 그대로 — FE가 오류 문구를 만들지 않는다(CB-002 공통 회색 박스) */
  const messageOf = (e: Error) => (isApiRequestError(e) ? e.error.user_message : e.message)

  function handleVote(next: Vote) {
    // 같은 값을 다시 누른 경우 — 👎면 기존 값이 채워진 폼을 다시 연다(CB-002 마커 8 "답변당 1건")
    if (vote === next) {
      if (next === 'down') setFormOpen(true)
      return
    }
    voteMutation.mutate(next, {
      onSuccess: (res) => {
        setFeedbackId(res.feedback_id)
        setVote(next)
        if (next === 'up') {
          // 👍는 추가 입력이 없다. 열려 있던 사유 폼·완료 카드는 접는다
          setFormOpen(false)
          setSubmitted(null)
          toast('의견이 접수되었어요')
        } else {
          setFormOpen(true)
        }
      },
      onError: (e: Error) => toast(messageOf(e)),
    })
  }

  function handleSubmit() {
    patchMutation.mutate(
      {
        reason_codes: reason === null ? [] : [reason],
        comment: comment.trim() === '' ? undefined : comment.trim(),
      },
      {
        onSuccess: () => {
          setSubmitted({ reason, comment: comment.trim() })
          setFormOpen(false)
        },
        // 등록 실패 시 입력 내용을 지우지 않고 폼을 유지한다 (CB-002 마커 8)
        onError: (e: Error) => toast(messageOf(e)),
      },
    )
  }

  // [등록]은 사유 칩 선택 또는 의견 입력이 하나라도 있을 때만 활성 (CB-002 Case 3-1 주석)
  const canSubmit = reason !== null || comment.trim() !== ''

  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-1.5">
        <button
          type="button"
          className={VOTE}
          aria-pressed={vote === 'up'}
          disabled={voteMutation.isPending}
          onClick={() => handleVote('up')}
        >
          <span aria-hidden="true">👍</span> 도움돼요
        </button>
        <button
          type="button"
          className={VOTE}
          aria-pressed={vote === 'down'}
          disabled={voteMutation.isPending}
          onClick={() => handleVote('down')}
        >
          <span aria-hidden="true">👎</span> 아쉬워요
        </button>
      </div>

      {formOpen && (
        <div className="rounded-md border bg-card p-4">
          <p className="mb-3 text-sm font-bold">
            어떤 점이 아쉬웠나요?{' '}
            <span className="text-xs font-normal text-muted-foreground">(선택 입력)</span>
          </p>

          {/* 단일 선택 · 재클릭 시 해제 (CB-002 Case 3-1 주석).
              gap-y-2(8px) = 위아래 칩의 확장 터치 영역(각 4px)이 딱 맞물리는 값 —
              이보다 좁히면 두 줄의 터치 영역이 겹쳐 오클릭이 난다 */}
          <div className="mb-3 flex flex-wrap gap-x-2 gap-y-2">
            {REASON_CODES.map((code) => (
              <button
                key={code}
                type="button"
                className={cn(CHIP, 'text-muted-foreground hover:border-muted-foreground hover:text-foreground')}
                aria-pressed={reason === code}
                onClick={() => setReason(reason === code ? null : code)}
              >
                {REASON_CODE_LABEL[code]}
              </button>
            ))}
          </div>

          <label className="sr-only" htmlFor={commentId}>
            자세한 의견 (선택 · {FEEDBACK_FREETEXT_MAX}자)
          </label>
          <Textarea
            id={commentId}
            className="min-h-16 resize-y bg-background text-sm"
            value={comment}
            // 질문 입력창과 같은 규칙으로 초과 입력을 막는다 (기획서 미정 — CB-002 §7-11)
            maxLength={FEEDBACK_FREETEXT_MAX}
            placeholder={`자세한 내용을 남겨 주시면 개선에 반영할게요 (선택 · ${FEEDBACK_FREETEXT_MAX}자)`}
            onChange={(e) => setComment(e.target.value)}
          />

          {/* 글자 수는 입력창 바로 아래 오른쪽 — 입력의 부속이라 버튼 줄로 끌어내리지 않는다 */}
          <p className="mt-1 text-right text-xs text-muted-foreground tabular-nums">
            {comment.length} / {FEEDBACK_FREETEXT_MAX}
          </p>

          {/* 한 줄에 안내(왼쪽) · 버튼(오른쪽)이 마주 본다.
              Button의 disabledReason으로 넘기면 안내가 [등록] **오른쪽**에 붙어 버튼을 왼쪽으로
              밀고 줄이 흐트러진다(사용자 지적). 위아래로 떼면 이번엔 세로 공백이 남는다.
              접근성은 aria-describedby가 잇는다 */}
          <div className="mt-3 flex flex-wrap items-center justify-end gap-x-3 gap-y-2">
            {!canSubmit && (
              <p className="mr-auto text-xs break-keep text-muted-foreground" id={hintId}>
                사유를 고르거나 의견을 적으면 등록할 수 있어요
              </p>
            )}
            <Button variant="secondary" size="sm" className="min-h-11" onClick={() => setFormOpen(false)}>
              취소
            </Button>
            <Button
              variant="primary"
              size="sm"
              className="min-h-11"
              disabled={!canSubmit}
              loading={patchMutation.isPending}
              aria-describedby={canSubmit ? undefined : hintId}
              onClick={handleSubmit}
            >
              등록
            </Button>
          </div>
        </div>
      )}

      {submitted !== null && !formOpen && (
        <div className="rounded-md border bg-muted/60 p-4">
          <p className="mb-2 text-sm font-bold">🙏 의견 감사합니다. 개선에 반영할게요!</p>
          {submitted.reason !== null && (
            <p className="mb-2 inline-block rounded border bg-card px-2.5 py-0.5 text-xs text-foreground">
              <span aria-hidden="true">👎</span> {REASON_CODE_LABEL[submitted.reason]}
            </p>
          )}
          {submitted.comment !== '' && (
            <p className="mb-2 text-sm text-foreground/80">&ldquo;{submitted.comment}&rdquo;</p>
          )}
          {/* 등록 후에도 값을 고칠 수 있다(답변당 1건 유지) */}
          <button
            type="button"
            className="py-1 text-sm font-medium text-primary underline underline-offset-2 transition-colors duration-200 hover:text-accent-foreground"
            onClick={() => setFormOpen(true)}
          >
            의견 수정
          </button>
        </div>
      )}
    </div>
  )
}
