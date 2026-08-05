/** CB-004 Case 5 — 같은 질문의 [다시 시도] 2회를 소진했을 때의 공식 문의 전환 패널.
 *
 * 말풍선이 아니라 대화 폭을 쓰는 카드다(목업 865×170).
 * 문구는 기획서 원문 그대로. 실시간 상담원 연결 UI는 범위 밖이라 만들지 않는다. */
import { Copy } from 'lucide-react'
import { Button, buttonVariants, useToast } from '../../components/ui'
import { cn } from '@/lib/utils'

/** [공식 문의 안내] 목적지. 기획서에 URL이 없어 Case 6 배너가 안내하는 공식 누리집을 쓴다 */
const OFFICIAL_SITE = 'https://www.kdic.or.kr/'

export interface RetryExhaustedPanelProps {
  /** 문의 시 상황을 특정하는 요청 ID (`req_8f2c41ab` 형식) */
  requestId: string
}

export function RetryExhaustedPanel({ requestId }: RetryExhaustedPanelProps) {
  const toast = useToast()

  const copy = () => {
    // 복사 성공·실패 피드백 문구는 기획서 미정의(CB-004 D-3 14) — 토스트 어투에 맞춰 프론트가 씀
    navigator.clipboard
      .writeText(requestId)
      .then(() => toast('요청 ID를 복사했어요'))
      .catch(() => toast('요청 ID를 복사하지 못했어요'))
  }

  return (
    <section className="mt-2 rounded-md border bg-card p-5" aria-label="공식 문의 안내">
      <h3 className="text-base font-bold">두 번 다시 시도했지만 답변을 만들지 못했어요.</h3>
      <p className="mt-2 text-[13px] text-muted-foreground">
        공식 문의처를 이용해 주세요. 문의 시 요청 ID를 알려주시면 확인에 도움이 됩니다.
      </p>
      <p className="mt-1 text-[13px] text-muted-foreground">
        {/* 서버에 닿지도 못한 오류는 요청 ID가 없다 — 빈 값이면 ID 자리를 통째로 뺀다.
            null·undefined로 오는 경로도 있어 truthy 검사로 받는다 */}
        {requestId && (
          <>
            요청 ID <span className="font-mono text-foreground">{requestId}</span> ·{' '}
          </>
        )}
        운영 시간과 준비 정보는 문의 안내에서 확인
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {/* 새 탭 이동은 미리 알린다 (CB-002 Desc ③ "'새 탭'을 알린 뒤 엽니다").
            링크라 <button>을 못 쓰지만 룩은 buttonVariants(primary)를 그대로 입힌다 */}
        <a
          className={cn(buttonVariants(), 'min-h-11 px-5')}
          href={OFFICIAL_SITE}
          target="_blank"
          rel="noreferrer noopener"
        >
          공식 문의 안내
          <span className="text-xs font-normal opacity-90"> (kdic.or.kr · 새 탭)</span>
        </a>
        {/* 복사할 것이 없으면 버튼을 두지 않는다 — 사용자 화면에서 '요청 ID가 없습니다'는
            설명이 아니라 내부 사정이다(관리자 화면과 달리 여기서는 숨기는 편이 맞다) */}
        {requestId && (
          <Button className="min-h-11" onClick={copy}>
            <Copy aria-hidden="true" /> 요청 ID 복사
          </Button>
        )}
      </div>
    </section>
  )
}
