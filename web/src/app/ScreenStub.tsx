/** 미구현 화면 자리표시자. 라우팅·셸을 먼저 붙여 두고 화면은 담당자가 이어서 채운다.
 * 화면이 구현되면 이 컴포넌트 호출을 지운다 — 남아 있으면 미구현이라는 뜻이다. */
import { Construction } from 'lucide-react'

export interface ScreenStubProps {
  /** 기획서 화면 ID (예: `AD-001`) */
  id: string
  /** 기획서 화면 제목 */
  title: string
}

export function ScreenStub({ id, title }: ScreenStubProps) {
  return (
    <section className="flex flex-col items-center gap-1 rounded-md border border-dashed bg-muted/40 px-6 py-12 text-center">
      <Construction className="mb-2 size-8 text-muted-foreground" aria-hidden="true" />
      <p className="nums text-xs font-semibold text-muted-foreground">{id}</p>
      <h2 className="text-base font-semibold">{title}</h2>
      <p className="text-[13px] text-muted-foreground">이 화면은 아직 구현되지 않았습니다.</p>
    </section>
  )
}
