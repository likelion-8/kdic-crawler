/** 출처·서류 카드와 신청 CTA — 링크 표시 규격은 CM-DF-003 02절.
 * "링크는 항상 새 탭 · 화면에는 URL 원문을 노출하지 않음(제목·서류명만 표시)".
 * 참고 출처(CB-002 마커 5) · 필요 서류(CB-003 마커 2) · 폴백 출처(CB-004 Case 4)가 같은 컴포넌트를 쓴다. */
import { ExternalLink } from 'lucide-react'
import { buttonVariants } from '../shadcn/button'
import { cn } from '@/lib/utils'

export interface SourceCardProps {
  title: string
  /** 카테고리 경로(참고 출처) 또는 행동 안내(필요 서류 = '서식 다운로드 페이지로 이동') */
  subtitle: string
  url: string
}

export function SourceCard({ title, subtitle, url }: SourceCardProps) {
  return (
    // 흰 지면 + 헤어라인. hover는 테두리 색만 짙어진다 — 그림자로 띄우지 않는다
    <a
      className="flex min-h-11 items-center gap-3 rounded-md border bg-card px-3.5 py-2.5 transition-colors duration-200 hover:border-muted-foreground"
      href={url}
      target="_blank"
      rel="noreferrer"
    >
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-sm font-semibold text-foreground">
          {title}
          {/* 새 탭 이동을 미리 알린다 (CB-002 Desc 3 "'새 탭'을 알린 뒤 엽니다") */}
          <span className="sr-only"> (새 탭에서 열림)</span>
        </span>
        <span className="text-xs text-muted-foreground">{subtitle}</span>
      </span>
      <ExternalLink className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
    </a>
  )
}

export interface ApplyCtaProps {
  label: string
  url: string
}

/** 신청 페이지 CTA — CB-003 마커 3 "실제 공식 신청 URL만 CTA로 제공하고 기관/도메인·새 탭 이동을 함께 알립니다". */
export function ApplyCta({ label, url }: ApplyCtaProps) {
  const host = hostOf(url)
  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* 라벨은 서버가 주는 페이지 제목이라 길이를 화면이 통제할 수 없다. nowrap이면
          좁은 말풍선(모바일) 밖으로 버튼이 삐져나온다 — 줄바꿈을 허용해 안에 가둔다 */}
      <a
        className={cn(
          buttonVariants({ size: 'lg' }),
          'h-auto max-w-full min-h-11 px-5 py-2 text-left font-bold whitespace-normal',
        )}
        href={url}
        target="_blank"
        rel="noreferrer"
      >
        {label}
        <ExternalLink aria-hidden="true" />
      </a>
      {/* 목업 원문 `kmrs.kdic.or.kr · 새 탭` — 도메인만 노출하고 URL 원문은 감춘다.
          도메인을 못 뽑으면 구분점 없이 '새 탭'만 남긴다 */}
      <span className="text-xs text-muted-foreground">{host === '' ? '새 탭' : `${host} · 새 탭`}</span>
    </div>
  )
}

/** 도메인만 뽑는다. 잘못된 URL이면 빈 문자열 — 힌트 한 줄 때문에 렌더가 죽으면 안 된다 */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname
  } catch {
    return ''
  }
}
