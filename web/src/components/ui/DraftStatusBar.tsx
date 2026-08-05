/** 상태 바 (초안 · 변경 요약) — CM-DF-001 02절.
 * 사용 화면: AD-007 [운영 반영] · AD-008 [게시] · AD-009 [저장].
 * (요청/승인 2단계는 없앴다 — 팀 결정 2026-08-04. 편집 권한자가 바로 반영한다)
 * 좌측 = 무엇이 달라졌나 / 우측 = 액션. 변경 0건이면 주 액션 비활성.
 *
 * ⚠ 이 바는 화면 제목 바로 아래 sticky로 붙는다. 그래서 두 가지를 지킨다.
 *  1. **제목처럼 읽히는 문구를 두지 않는다.** 02절 목업의 상태 라벨 '초안 편집 중'을 상시
 *     띄우면 아무것도 안 고친 상태에서도 제목 자리에 '초안 편집 중'이 박혀 사실과 어긋난다
 *     (사용자 지적). 좌측은 값 — `변경 없음` / `변경 3건` — 으로 시작한다.
 *  2. **버튼 자리는 고정이다.** 비활성 사유를 버튼 옆 캡션으로 그리면 사유가 생길 때마다
 *     버튼이 왼쪽으로 밀린다(사용자 지적). 사유는 sr-only로만 두고 `aria-describedby`로 묶는다 —
 *     눈에 보이는 설명은 칩(`게이트 미통과`)과 화면 본문의 Notice가 맡는다. */
import { useId } from 'react'
import type { ReactNode } from 'react'
import { Button } from './Button'
import { InfoHint } from './InfoHint'

export interface DraftStatusBarProps {
  /** 앞머리 라벨. **상태를 지어내지 말 것** — 버전처럼 사실인 값만 쓴다(AD-009 `운영 정책 v1.0`).
   * 없으면 좌측은 변경 집계로 시작한다(AD-007·AD-008). */
  label?: string
  changeCount: number
  /** 집계 칩 — <Badge tone="green" kind="count">무중단 2</Badge> 같은 걸 그대로 넘긴다 */
  chips?: ReactNode
  /** 변경 집계 문구를 덮어쓴다 — **값만** 쓸 것.
   * ⚠ 절차·범례·규칙을 여기 넣지 말 것: 좌측 그룹이 flex-wrap이라 문장이 감기면 바가 2~3줄로
   * 부풀고, sticky라 부푼 만큼 스크롤 내내 본문을 덮는다. 설명은 `hint`로 접는다. */
  description?: ReactNode
  /** 변경 집계 옆 ⓘ — 편집→평가→반영 절차나 빨간 점 범례처럼 한 번 알면 되는 설명 */
  hint?: ReactNode
  /** 주 액션 라벨은 화면마다 다름: '운영 반영 (N)' / '게시 (N)' / '저장' */
  primaryLabel: string
  onPrimary: () => void
  onReset: () => void
  /** 취소 버튼 라벨. AD-008은 '초안 취소'가 원문이다 (검증 D015) */
  resetLabel?: string
  /** 보조 액션 — 두 화면 모두 [초안 평가]. 상태 바가 ①편집→②평가→③반영 한 줄이다 */
  secondaryLabel?: string
  onSecondary?: () => void
  /** 변경 0건 외의 추가 비활성 조건 — 예: 회귀 게이트 미통과·권한 없음 (검증 D016).
   * 조용한 no-op을 남기지 말고 여기로 막는다. */
  primaryDisabled?: boolean
  /** 왜 못 누르는지. 바에는 그리지 않고(버튼이 밀린다) 스크린리더에만 전한다 —
   * 눈에 보이는 안내는 화면이 칩·Notice로 따로 세운다. */
  primaryDisabledReason?: string
  /** 제출 중 — 중복 클릭 방지 */
  pending?: boolean
}

export function DraftStatusBar({
  label,
  changeCount,
  chips,
  description,
  hint = (
    // 02절 원문 — 기본 안내는 ⓘ 뒤로. 바에는 값(변경 N건)만 남긴다
    <>
      수정된 영역·항목 이름 오른쪽 위에 빨간 점(6px)이 함께 표시되며, [반영] 전까지 서비스에
      적용되지 않습니다.
    </>
  ),
  primaryLabel,
  onPrimary,
  onReset,
  resetLabel = '초기화',
  secondaryLabel,
  onSecondary,
  primaryDisabled = false,
  primaryDisabledReason,
  pending = false,
}: DraftStatusBarProps) {
  const reasonId = useId()
  const noChange = changeCount === 0
  const disabled = noChange || primaryDisabled
  // 변경 0건은 좌측이 '변경 없음'으로 이미 말한다 — 같은 줄에서 두 번 말하지 않는다
  const blockReason = noChange ? undefined : primaryDisabled ? primaryDisabledReason : undefined

  return (
    // 목업은 1000×56 고정폭이지만 관리자 SPA는 ≥1024 가변이라 콘텐츠 폭 100%로 둔다
    // (CM-DF-001 12절 이슈 10 — 기획서에 가변 규칙 없음)
    // 보라 색면 카드 대신 흰 지면 + 상하 헤어라인 띠
    <div
      className="flex min-h-14 items-center justify-between gap-4 border-y border-border bg-background py-3"
      role="region"
      aria-label="초안 상태"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
        {label && <p className="text-sm font-semibold text-primary">{label}</p>}
        {/* 고친 게 있을 때만 무게를 준다 — 0건에 굵은 글씨를 쓰면 '뭔가 진행 중'으로 읽힌다 */}
        <p
          className={`inline-flex items-center gap-0.5 text-sm ${
            noChange ? 'text-muted-foreground' : 'font-semibold text-foreground'
          }`}
        >
          {description ?? (noChange ? '변경 없음' : `변경 ${changeCount}건`)}
          {hint && (
            <InfoHint label="초안 안내" size="sm">
              {hint}
            </InfoHint>
          )}
        </p>
        {chips && <div className="flex items-center gap-1.5">{chips}</div>}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {/* 사유는 폭을 차지하지 않는다 — 이게 버튼 자리를 고정하는 핵심이다 */}
        {blockReason && (
          <span className="sr-only" id={reasonId}>
            {blockReason}
          </span>
        )}
        <Button variant="secondary" onClick={onReset} disabled={pending}>
          {resetLabel}
        </Button>
        {secondaryLabel && onSecondary && (
          <Button variant="secondary" onClick={onSecondary} disabled={pending}>
            {secondaryLabel}
          </Button>
        )}
        <Button
          variant="primary"
          onClick={onPrimary}
          loading={pending}
          disabled={disabled}
          aria-describedby={blockReason ? reasonId : undefined}
        >
          {primaryLabel}
        </Button>
      </div>
    </div>
  )
}
