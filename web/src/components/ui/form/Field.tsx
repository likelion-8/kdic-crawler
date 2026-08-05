/** 폼 컨트롤 공통 껍데기 — CM-DF-001 04절 공통 규칙.
 * · 라벨은 좌측 정렬, 컨트롤은 같은 x축에 정렬한다
 * · 단위(회·건·초)는 컨트롤 우측에 회색으로
 * 비활성은 숨기지 말고 사유를 옆에 표기(04절 '비활성(필드)' 캡션).
 *
 * ⚠ 기획서 이탈 1건: 04절은 `현행 0.4 → 0.6` 대비 표기를 요구하지만 입력창이 이미 그 값을
 * 보여주고 있어 중복이다. 바뀐 항목의 baseline만 남겼다(아래 주석 참조) — 기획서 수정 대상. */
import type { ReactNode } from 'react'
import { DirtyDot } from '../DirtyDot'
import { InfoHint } from '../InfoHint'

/** 각 컨트롤이 공통으로 받는 옵션 */
export interface FieldOptions {
  label: string
  /** 컨트롤 우측 회색 단위 표기 (회·건·초) */
  unit?: string
  /** 현행값. 현재 값과 다르면 '현행 A → B' 대비 표기 + 초안 변경 점(6px)이 붙는다 */
  baseline?: string | number
  /** 인라인 유효성 오류 — 기획서에 규격 없어 프론트에서 정함(12절 이슈 8): 빨강 12px, 필드 하단 */
  error?: string
  /** 왜 못 바꾸는지 (03절 규칙 3과 동일 원칙) */
  disabledReason?: string
  /** 라벨 옆 ⓘ — '이 값이 언제 쓰이나' 같은 규칙 설명을 접어 둔다.
   * 필드 아래·옆에 문장으로 펼치면 그 항목만 높아지거나 넓어져 폼 정렬이 흐트러진다.
   * 지금 값·단위·오류는 여기 넣지 말 것(항상 보여야 한다). */
  hint?: ReactNode
  /** 배치 — 'row'(기본)는 설정 폼용 라벨 160px 고정 열, 'stack'은 필터바용 라벨-위.
   *
   * 필터바에 'row'를 쓰면 필터 하나가 160+140=300px을 차지해 5개가 한 줄에 못 들어가고,
   * 줄바꿈된 뒤로는 라벨 x좌표가 줄마다 어긋난다. 게다가 `기간 ⋯⋯⋯ 오늘`처럼 라벨과
   * 컨트롤 사이가 텅 빈다. 필터는 컨트롤 폭(140px)이 곧 열 폭이라 라벨을 위로 올리면
   * 저절로 정렬된다. */
  layout?: 'row' | 'stack'
}

export interface FieldProps extends FieldOptions {
  id: string
  /** 대비 표기용 현재 값(표시 문자열) */
  value: string | number
  /** 여러 줄 컨트롤(textarea)이면 라벨을 첫 줄에 맞춰 위로 정렬한다 */
  alignTop?: boolean
  children: ReactNode
}

export function Field({
  id,
  label,
  value,
  unit,
  baseline,
  error,
  disabledReason,
  alignTop = false,
  layout = 'row',
  hint,
  children,
}: FieldProps) {
  const changed = baseline !== undefined && String(baseline) !== String(value)
  const stack = layout === 'stack'
  return (
    // 라벨 좌측 정렬 · 컨트롤은 같은 x축(라벨 폭 고정) — 04절 공통 규칙 2
    <div
      className={
        stack
          ? 'flex flex-col gap-1'
          : `grid grid-cols-[160px_1fr] gap-x-3 gap-y-1 py-1.5 ${alignTop ? 'items-start' : 'items-center'}`
      }
    >
      {/* min-w-0 : grid 자식 기본값(min-width:auto)이면 라벨이 감기지 않고 160px 트랙을 넘어가,
          뒤따르는 ⓘ만 다음 줄로 밀려 홀로 떠 보인다(예: '융합 비중 (키워드 검색 쪽)').
          감기게 두면 ⓘ가 라벨 마지막 줄 끝에 붙는다 */}
      <label
        className={`min-w-0 text-sm text-foreground ${stack ? 'text-xs text-muted-foreground' : ''} ${alignTop ? 'pt-2' : ''}`}
        htmlFor={id}
      >
        {label}
        {changed && <DirtyDot label={`${label} 변경됨`} />}
        {hint && <InfoHint label={`${label} 설명`} size="sm">{hint}</InfoHint>}
      </label>
      {/* min-w-0 : 라벨과 같은 이유다. 이게 없으면 grid 자식 기본값(min-width:auto) 때문에
          컨트롤 칸이 1fr 트랙을 넘어 모달·카드 밖으로 삐져나가고 가로 스크롤이 생긴다
          (긴 옵션 라벨 `VIEWER (조회 전용)`에서 실제로 터졌다 — 2026-08-05) */}
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        {children}
        {/* 단위는 회색, 컨트롤 우측 */}
        {unit && <span className="text-xs text-muted-foreground">{unit}</span>}
        {/* 바뀐 항목만, 그것도 '운영에 반영돼 있는 값'만 보여준다.
         *
         * 기획서 04절은 `현행 0.4 → 0.6` 대비 표기를 요구하지만 그대로 두면 중복이 두 겹이다:
         *  · 안 바꾼 항목의 `현행 20`은 옆 입력창이 이미 20을 보여주므로 같은 숫자를 두 번 쓰는 꼴
         *  · 바꾼 항목의 `→ 0.6`도 입력창에 이미 들어 있는 값
         * 새 정보는 '운영에 뭐가 떠 있나(baseline)'뿐이라 그것만 남긴다.
         * 변경됐다는 신호는 라벨의 빨간 점(DirtyDot, 02절 규정)이 이미 지므로 색까지 쓰지 않는다.
         * '이전'이 아니라 '현행'인 이유: 초안을 편집하는 중이라 baseline은 지금도 운영에 떠 있는 값이다. */}
        {changed && <span className="text-xs text-muted-foreground">현행 {baseline}</span>}
        {/* 비활성 사유는 sr-only다. 눈에 보이는 캡션으로 두면 권한이 없는 계정에서
            '수정하려면 EDITOR 권한이 필요합니다'가 화면의 모든 행 옆에 되풀이된다(사용자 지적).
            사람이 볼 안내는 화면 위 '보기 전용' 배너가 한 번만 진다 — 여기서 되풀이하지 않는다 */}
        {disabledReason && <span className="sr-only">{disabledReason}</span>}
      </div>
      {error && (
        <p className={`text-xs text-destructive ${stack ? '' : 'col-start-2'}`} id={`${id}-error`}>
          {error}
        </p>
      )}
    </div>
  )
}
