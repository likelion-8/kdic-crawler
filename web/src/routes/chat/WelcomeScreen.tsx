/** CB-001 웰컴 화면 (KDIC-CB-PG-001) — 대화 이력이 없을 때만 보이는 상태.
 *
 * 구성(위→아래): ① 72px 웰컴 아이콘 · ② 웰컴 텍스트 · ⑤ 자주 묻는 질문 카드.
 * 입력창(③④)과 고지 문구는 대화 중에도 같은 자리에 있어야 해서 ChatPage가 그린다.
 *
 * 문구는 전부 기획서 원문 그대로다(CB-001 §2.3·§2.4). */
import { useState } from 'react'
import type { CSSProperties } from 'react'
import { ChevronRight } from 'lucide-react'
import { Button } from '../../components/ui'
import { cn } from '@/lib/utils'
import { BUSINESS_FUNCTIONS } from '../../lib/codes'
import { Avatar } from '../../components/chat/Avatar'
import { AVATARS } from '../../components/chat/avatars'

/** 업무 칸을 눌렀을 때 보낼 질문.
 *
 * 업무명에 '안내'·'신청'·'신고'가 섞여 있어(BUSINESS_FUNCTIONS) 어미를 붙이는 방식은 다 어색해진다
 * ('예금보험금 안내 안내해 주세요'). 목적어로 받는 이 형태가 6종 모두에서 자연스럽다.
 * 업무별 추천 질문을 필터로 보여주는 방식은 쓰지 않았다 — 활성 질문이 착오송금에 몰려 있어
 * 나머지 업무에서 빈 목록이 된다(목 데이터 실측: 10건 중 9건이 착오송금·미수령금). */
const askAbout = (business: string) => `${business}에 대해 알려주세요`

/** 진입 스태거 순서(global.css .reveal) — n × 60ms 지연 */
const revealAt = (i: number) => ({ '--reveal-i': i }) as CSSProperties

/** GET /api/suggestions 실패 시 폴백 — CB-001 §2.4 FAQ TOP 10 원문.
 * 운영자가 AD-009에서 바꾼 목록을 못 받은 상태이므로 어디까지나 최후 수단이다. */
export const FALLBACK_SUGGESTIONS: string[] = [
  '착오송금 반환까지 얼마나 걸리나요?',
  '반환지원 대상이 아닌 경우는 어떤 경우인가요?',
  '반환지원 대상 금액은 얼마까지인가요?',
  '어떤 금융회사·앱이 반환지원 대상인가요?',
  '방문 신청도 가능한가요?',
  '상속인 금융거래 조회 기간은 어떻게 되나요?',
  '보이스피싱 피해도 신청할 수 있나요?',
  '토스·카카오페이 간편송금도 지원되나요?',
  '착오송금 후 언제까지 신청해야 하나요?',
  '은행 반환절차 없이 바로 신청할 수 있나요?',
]

export interface WelcomeScreenProps {
  /** 활성 추천 질문(최대 10). 빈 배열이면 카드를 통째로 감춘다 */
  questions: string[]
  /** 행 클릭 = 그 질문을 즉시 전송 (CB-001 Desc ⑤ "행을 누르면 그 질문이 바로 전송되며") */
  onPick(question: string): void
  /** 질문을 받을 수 없는 상태(점검·준비 실패)면 행도 누를 수 없다 — 무반응 클릭을 남기지 않는다 */
  disabled?: boolean
}

export function WelcomeScreen({ questions, onPick, disabled = false }: WelcomeScreenProps) {
  // 처음에는 3개만 보인다. 10개를 다 펼쳐 두면 첫 화면이 목록으로 꽉 차 아이콘·인사말과
  // 균형이 깨진다(사용자 지적) — 모바일 규칙(CM-DF-004 09절 상위 3개 + [더보기])을 전 폭에 적용한다.
  // 행 자체는 모두 렌더하고 CSS로 감춘다 — 접었다 펴도 상태를 다시 맞출 필요가 없다
  const [expanded, setExpanded] = useState(false)

  return (
    // 세로 가운데 정렬은 부모(ChatPage 스크롤 안쪽)가 진다 — 여기서는 위아래 숨통만 확보한다.
    // 위에 붙여 두면 카드 아래가 입력창까지 휑하게 비었다(사용자 지적)
    <div className="flex flex-col items-center py-10 text-center max-md:py-6">
      {/* 웰컴 아이콘 72px 원형(CM-DF-003 02절) — 말풍선 아바타와 같은 마스코트를 쓴다.
          로드에 실패하면 Avatar가 이모지로 떨어뜨린다(Desc ① "불러오지 못하면 이모지로 대체").
          장식은 헤어라인 원 하나뿐 — 후광(ring)은 템플릿 냄새라 쓰지 않는다 */}
      <Avatar
        {...AVATARS.bot}
        label="예솜24"
        className="reveal size-(--chat-welcome-icon) text-4xl"
        style={revealAt(0)}
      />

      <h1 className="reveal mt-5 text-[22px] font-bold tracking-tight" style={revealAt(1)}>
        {/* 서비스명에만 포인트 컬러 (CB-001 Desc ②) */}
        AI챗봇 <span className="text-primary">예솜24</span>에 오신 걸 환영해요
      </h1>

      {/* 무엇을 물어볼 수 있는 챗봇인지 알린다 — 범위를 모르면 답할 수 없는 질문을 던지고
          '범위 외' 답변을 받게 된다. 업무 6종은 검색 범위 그 자체(BUSINESS_FUNCTIONS)라
          문자열을 새로 쓰지 않고 코드값을 그대로 쓴다.
          한 줄로 이어 붙였더니 560px에서 감기며 꼬리 한 조각만 둘째 줄에 남았다(사용자 지적) —
          6개는 균등한 항목이니 3×2 격자로 세운다. 아래 FAQ 카드와 같은 폭이라 왼쪽 끝이 맞고,
          카드는 테두리가 있고 이쪽은 없어 '조용한 목록 → 카드' 순으로 무게가 붙는다 */}
      <div className="reveal mt-4 w-full max-w-[560px]" style={revealAt(2)}>
        <p className="text-[13px] font-medium text-foreground/70">이런 업무를 안내해 드려요</p>
        {/* 누르면 그 업무를 묻는 질문이 바로 전송된다 — FAQ 행과 같은 동작이다.
            쉬고 있을 때도 눌리는 것으로 보여야 하므로(사용자 지적) 공통 Button을 그대로 쓴다 —
            같은 화면의 [더보기]와 같은 규격(Secondary 아웃라인)이라 낱개로 만든 룩이 늘지 않는다 */}
        <ul className="mt-2 grid grid-cols-3 gap-2 max-md:grid-cols-2">
          {BUSINESS_FUNCTIONS.map((name) => (
            <li key={name}>
              <Button
                data-slot="welcome-business"
                className="h-auto min-h-11 w-full px-2 text-[13px] break-keep whitespace-normal"
                disabled={disabled}
                onClick={() => onPick(askAbout(name))}
              >
                {name}
              </Button>
            </li>
          ))}
        </ul>
      </div>

      {questions.length > 0 && (
        // 흰 지면 + 헤어라인 보더. 그림자로 띄우지 않는다 — 랜드마크 의미(aria-labelledby)는 section이 진다
        <section
          className="reveal mt-6 w-full max-w-[560px] rounded-md border bg-card text-left text-card-foreground"
          style={revealAt(3)}
          aria-labelledby="faq-title"
        >
          {/* 기획서 원문은 `자주 묻는 질문 TOP 10` + 우측 `누르면 바로 질문돼요`(CB-001 §2.4)지만
              둘 다 뺐다(사용자 지시). 개수는 운영자가 AD-009에서 바꿀 수 있어 `TOP 10` 고정이
              애초에 사실과 어긋났고(정독본 C5), 누를 수 있다는 것은 행 hover·화살표가 이미 말한다 */}
          <div className="flex min-h-11 items-center justify-between gap-2 border-b px-5 py-2">
            <h2 className="text-[15px] font-semibold" id="faq-title">
              자주 묻는 질문
            </h2>
            {/* 목록 아래에 두면 접을 때마다 버튼이 위아래로 움직인다 — 제목 줄에 고정한다 */}
            {questions.length > 3 && (
              <Button
                size="sm"
                className="-mr-1"
                aria-expanded={expanded}
                aria-controls="faq-list"
                onClick={() => setExpanded((v) => !v)}
              >
                {expanded ? '접기' : '더보기'}
              </Button>
            )}
          </div>

          {/* 구분선은 행 사이에만 (§2.4: 첫 행 위·마지막 행 아래에는 없음) */}
          <ol
            className={cn('px-2 py-1 [&>li+li]:border-t', !expanded && '[&>li:nth-child(n+4)]:hidden')}
            id="faq-list"
          >
            {questions.map((q, i) => (
              <li key={q} className="reveal" style={revealAt(4 + i)}>
                <button
                  type="button"
                  data-slot="welcome-row"
                  className="group flex min-h-11 w-full items-center gap-2.5 rounded px-3 py-1 text-left text-sm transition-colors duration-200 hover:bg-muted disabled:cursor-not-allowed disabled:text-muted-foreground disabled:hover:bg-transparent"
                  disabled={disabled}
                  onClick={() => onPick(q)}
                >
                  {/* 배지 대신 유령 숫자. 400 굵기 큰 숫자가 조용히 깔려 있다가 hover에서 잉크로 짙어진다
                      (색으로 튀지 않는다 — Noto Sans KR 400/500/700만 사용) */}
                  <span
                    className="w-8 shrink-0 text-right text-2xl leading-none font-normal text-muted-foreground/50 tabular-nums transition-colors duration-200 group-hover:text-foreground group-disabled:opacity-50"
                    aria-hidden="true"
                  >
                    {i + 1}
                  </span>
                  <span className="min-w-0 flex-1 font-medium">{q}</span>
                  <ChevronRight
                    className="size-4 shrink-0 text-muted-foreground opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-visible:opacity-100 group-disabled:opacity-0"
                    aria-hidden="true"
                  />
                </button>
              </li>
            ))}
          </ol>

        </section>
      )}
    </div>
  )
}
