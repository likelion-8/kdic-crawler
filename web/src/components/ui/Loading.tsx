/** 로딩 — CM-DF-001 07.3절.
 * "5초 이상 걸리면 무엇을 하는 중인지 문구로 안내(예: '답변 생성 중')" */
import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'

/** 화면들이 로딩 골격에 쓰는 shadcn Skeleton 재노출 */
export { Skeleton } from '../shadcn/skeleton'

export interface SpinnerProps {
  /** 스피너 자체는 장식. 문구는 LoadingText가 읽어준다 */
  size?: number
}

export function Spinner({ size = 20 }: SpinnerProps) {
  // 잉크 톤 — 보라는 Primary·링크·포커스·현재 위치에만 쓴다. 진행 상태는 옆 문구가 읽어준다
  return (
    <Loader2 className="animate-spin text-muted-foreground" style={{ width: size, height: size }} aria-hidden="true" />
  )
}

export interface LoadingTextProps {
  /** 목업 문구 */
  text?: string
  /** 5초 경과 후 교체할 상세 문구 (예: '답변 생성 중') */
  detail?: string
  delayMs?: number
}

export function LoadingText({ text = '불러오는 중…', detail, delayMs = 5000 }: LoadingTextProps) {
  const [long, setLong] = useState(false)
  useEffect(() => {
    if (!detail) return
    const t = setTimeout(() => setLong(true), delayMs)
    return () => clearTimeout(t)
  }, [detail, delayMs])
  return (
    <span className="text-sm text-muted-foreground" role="status">
      {long && detail ? detail : text}
    </span>
  )
}

export type LoadingProps = LoadingTextProps

/** 스피너 + 문구 한 줄 — 화면마다 같은 마크업을 반복하지 않으려고 묶어둔 것 */
export function Loading(props: LoadingProps) {
  return (
    <span className="inline-flex items-center gap-2">
      <Spinner />
      <LoadingText {...props} />
    </span>
  )
}
