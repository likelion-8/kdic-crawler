/** 초안 변경 표식 — CM-DF-001 02절.
 * "수정된 영역·항목 이름 오른쪽 위에 빨간 점(6px)을 함께 표시" — 문서 명시값.
 * 색만으로 알리지 않도록 스크린리더용 '변경됨'을 함께 넣는다(CM-DF-004 09절). */

export interface DirtyDotProps {
  /** 기본 '변경됨'. 항목명을 붙이고 싶으면 '보존기간 변경됨'처럼 넘긴다 */
  label?: string
}

export function DirtyDot({ label = '변경됨' }: DirtyDotProps) {
  return (
    // 6px(size-1.5) 빨간 점. 항목 이름 오른쪽 위 — 부모에 position이 없어도 되도록 super 정렬로 띄운다
    <span className="ml-0.5 inline-block size-1.5 rounded-full bg-destructive align-super">
      <span className="sr-only">{label}</span>
    </span>
  )
}
