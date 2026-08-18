/** AD-004 R2 — 변경 페이지 알림 카드 (Description ❶).
 * "원본 사이트 내용이 바뀐 페이지 N건" 형태의 일상 언어 카드 · 항목은 제목 중심 세로 리스트.
 * 체크박스는 기본 전체 선택 · [지금 확인 ↻]으로 수동 재검사.
 * 버튼 라벨은 Description의 `[선택 N건 재수집]`으로 통일했다(목업 라벨 '재수집'과 불일치 — 이슈 G-10). */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { Button, EmptyState, InfoHint, Loading, Notice, RefreshBar } from '../../../components/ui'
import { Checkbox } from '@/components/shadcn/checkbox'
import { isApiRequestError } from '../../../lib/api/client'
import { formatTarget } from '../../../lib/format'
import { changesQueryKey, fetchChanges, formatMonthDay, recheckChanges } from './api'
import type { ChangedPagesResponse } from './api'

const CARD_CLASS = 'rounded-md border bg-card p-5'

export interface ChangedPagesCardProps {
  /** 선택한 페이지들로 재수집을 시작한다. 확인 모달은 부모가 연다(위험 작업 3단 플로우) */
  onRecrawl: (pageIds: string[]) => void
  /** 동시 실행 1개 — 실행 중이면 사유와 함께 비활성 (PIPELINE_CONCURRENCY) */
  disabledReason?: string
  /** OPERATOR 미만이면 실행 버튼을 숨긴다. 서버가 최종 판정이므로 403도 따로 처리한다 */
  canRun: boolean
}

export function ChangedPagesCard({ onRecrawl, disabledReason, canRun }: ChangedPagesCardProps) {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string[]>([])

  const changes = useQuery({ queryKey: changesQueryKey, queryFn: fetchChanges })

  // 체크박스 기본 전체 선택(Description ❶). 목록이 바뀌면 다시 전체 선택으로 돌린다
  useEffect(() => {
    if (changes.data) setSelected(changes.data.items.map((i) => i.page_id))
  }, [changes.data])

  const recheck = useMutation({
    mutationFn: recheckChanges,
    onSuccess: (data: ChangedPagesResponse) => queryClient.setQueryData(changesQueryKey, data),
  })

  if (changes.isPending) {
    return (
      <section className={CARD_CLASS} aria-busy="true">
        <Loading text="변경 페이지를 확인하는 중…" />
      </section>
    )
  }

  // 실패는 토스트가 아니라 화면 안에 남긴다(CM-DF-001 07.4절). 문구는 서버 user_message 그대로
  if (changes.isError) {
    const err = changes.error
    return (
      <section role="alert">
        <Notice
          tone="danger"
          variant="block"
          action={
            isApiRequestError(err) && err.error.retryable ? (
              <Button size="sm" onClick={() => void changes.refetch()}>
                다시 시도
              </Button>
            ) : undefined
          }
        >
          {isApiRequestError(err) ? err.error.user_message : '변경 페이지를 불러오지 못했습니다.'}
        </Notice>
      </section>
    )
  }

  const { last_checked_at, items } = changes.data
  const toggle = (pageId: string) =>
    setSelected((prev) => (prev.includes(pageId) ? prev.filter((p) => p !== pageId) : [...prev, pageId]))

  return (
    <section className={CARD_CLASS} aria-labelledby="changes-title">
      <header className="flex flex-wrap items-baseline justify-between gap-4">
        <h2 className="text-[13px] font-semibold tracking-[-0.01em]" id="changes-title">
          <RefreshCw className="mr-1.5 inline size-3.5 align-[-2px] text-muted-foreground" aria-hidden="true" />
          원본 사이트 내용이 바뀐 페이지 ({items.length}건)
          {/* '무엇을 변경으로 보는가'는 목록 어느 행과도 무관한 판정 규칙이다. footer에 문단으로
              두면 [선택 N건 재수집] 버튼과 한 줄을 다투다 좁아질 때 버튼이 아래로 튕긴다 */}
          <InfoHint label="변경 판정 기준 설명" size="sm">
            변경 여부는 페이지 본문 텍스트를 기준으로 판단합니다. 디자인·메뉴만 바뀐 것은 변경으로
            보지 않습니다.
          </InfoHint>
        </h2>
        {/* 대시보드 [새로고침]과 같은 UI다 — 같은 일(지금 최신으로 만들기)이므로 생김새를 맞춘다 */}
        <RefreshBar
          at={last_checked_at}
          label="확인"
          action="지금 확인"
          pending={recheck.isPending}
          onRefresh={() => recheck.mutate()}
        />
      </header>
      {/* [지금 확인]은 변경 감지 잡을 만든다(2026-08-18, src/change_detect.py). 워커가 정적
          페이지를 다시 읽어 본문 해시를 대조하고 바뀐 것만 표시한다 — 저장·색인은 안 한다.
          결과는 파이프라인 카드에서 진행을 보고, 끝나면 이 목록이 갱신된다 */}
      {recheck.data?.job_queued && (
        <p className="mt-2 text-xs text-muted-foreground" role="status">
          변경 감지를 시작했습니다 — 정적 페이지를 다시 읽어 본문을 대조합니다(30초 안팎). 끝나면
          이 목록이 갱신됩니다
        </p>
      )}
      {recheck.data && recheck.data.job_queued === false && (
        <p className="mt-2 text-xs text-muted-foreground" role="status">
          다른 작업이 진행 중이라 지금은 감지를 시작할 수 없습니다 — 끝난 뒤 다시 확인해 주세요
        </p>
      )}

      {recheck.isError && (
        <div className="mt-3" role="alert">
          <Notice tone="danger" variant="block">
            {isApiRequestError(recheck.error)
              ? recheck.error.error.user_message
              : '다시 확인하지 못했습니다.'}
          </Notice>
        </div>
      )}

      {items.length === 0 ? (
        // 0건 카피가 기획서에 없어(이슈 G-6) 07절 빈 상태 규칙대로 프론트가 썼다
        <EmptyState
          title="원본 사이트에서 바뀐 페이지가 없습니다"
          action={
            <Button size="sm" onClick={() => recheck.mutate()} loading={recheck.isPending}>
              {/* ↻ 유니코드 글리프 대신 아이콘 세트를 쓴다 — 폰트마다 모양·두께가 제각각이다 */}
              <RefreshCw aria-hidden="true" />
              지금 확인
            </Button>
          }
        />
      ) : (
        // 항목마다 회색 카드를 깔지 않는다 — 헤어라인으로만 나눈 목록
        <ul className="mt-4 divide-y border-y">
          {items.map((item) => (
            <li key={item.page_id}>
              {/* 터치 타깃 44×44 이상 (CM-DF-004 09절) — 라벨 전체가 클릭 영역이다 */}
              <label className="flex min-h-11 cursor-pointer items-center gap-3 px-1 py-1.5 transition-colors duration-200 hover:bg-muted/50">
                <Checkbox
                  checked={selected.includes(item.page_id)}
                  onCheckedChange={() => toggle(item.page_id)}
                />
                <span className="flex min-w-0 flex-col">
                  <span className="text-sm text-foreground">{item.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {/* 대상 표기는 '이름 (ID)' 고정 (PRD-02 §3-f) */}
                    {formatTarget(item.source_title, item.page_id)} : 본문 변경 감지 ·{' '}
                    {formatMonthDay(item.detected_at)}
                  </span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}

      <footer className="mt-4 flex flex-wrap items-center justify-end gap-4">
        {canRun && items.length > 0 && (
          <Button
            variant="primary"
            onClick={() => onRecrawl(selected)}
            disabled={selected.length === 0 || disabledReason !== undefined}
            disabledReason={
              disabledReason ?? (selected.length === 0 ? '재수집할 페이지를 선택해 주세요' : undefined)
            }
          >
            <RefreshCw aria-hidden="true" />
            선택 {selected.length}건 재수집
          </Button>
        )}
      </footer>
    </section>
  )
}
