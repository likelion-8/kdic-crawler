/** 정보 아이콘 — 눌러야 열리는 보조 설명.
 *
 * 왜 있는가: 규칙·제약을 설명하는 문장을 표 셀이나 카드에 상시 펼쳐 두면 화면이 어수선해진다.
 * 행마다 문구가 있다 없다 하면 행 높이가 들쭉날쭉해지고, 표가 넓어져 밀리기까지 한다
 * (실제로 '활성은 최대 10개입니다'가 추천 질문 표를 카드 밖으로 밀어냈다).
 * 한 번 알면 되는 내용은 라벨 옆 ⓘ 뒤로 접고, 궁금할 때 눌러 보게 한다.
 *
 * ⚠ 접으면 안 되는 것 — 오류·경고·실패 메시지, 되돌릴 수 없는 조작의 영향 고지, 빈 상태 안내,
 * 값 그 자체. 숨겨서 생기는 사고가 어수선함보다 비싸다.
 *
 * 접근성
 *  - hover 툴팁이 아니라 **클릭 팝오버**다. 터치 기기에는 hover가 없고, disabled 요소는
 *    hover 이벤트 자체가 뜨지 않는다.
 *  - 내용은 항상 DOM에 남긴다(`sr-only` 사본). 접혀 있어도 `aria-describedby`로 가리킬 수 있어야
 *    "왜 이 스위치가 잠겼나"를 스크린리더가 읽는다.
 *  - 트리거는 44px 터치 타깃(CM-DF-004 09절). 아이콘만 14px로 두고 여백으로 넓힌다.
 *
 * 포털 위치: 기본은 body 인데, 네이티브 `<dialog showModal()>` 안에서는 그러면 안 된다 —
 * 모달은 top layer 로 올라가고 body 로 나간 팝오버는 그 아래에 깔려 **아예 안 보인다**.
 * 그래서 트리거의 가장 가까운 <dialog> 를 찾아 그 안으로 포털한다(없으면 body 그대로).
 */
import { useEffect, useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Info } from 'lucide-react'
import { Popover } from 'radix-ui'

export interface InfoHintProps {
  /** 무엇에 대한 설명인지 — 스크린리더가 읽는 버튼 이름이 된다 ('활성 규칙 설명') */
  label: string
  /** 접어 둘 내용 */
  children: ReactNode
  /** 설명 본문의 id — 잠긴 컨트롤에서 `aria-describedby`로 가리킬 때 쓴다 */
  id?: string
  /** 아이콘 크기를 라벨에 맞춘다. 표 헤더(11px)는 sm */
  size?: 'sm' | 'md'
}

export function InfoHint({ label, children, id, size = 'md' }: InfoHintProps) {
  const auto = useId()
  const bodyId = id ?? auto
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [container, setContainer] = useState<HTMLElement | null>(null)
  // 마운트 뒤에야 DOM 위치를 알 수 있다. dialog 밖이면 null → Portal 기본값(body)
  useEffect(() => setContainer(triggerRef.current?.closest('dialog') ?? null), [])

  return (
    <>
      {/* 접혀 있어도 읽히는 사본 — aria-describedby의 실제 대상 */}
      <span className="sr-only" id={bodyId}>
        {children}
      </span>
      <Popover.Root>
        <Popover.Trigger
          ref={triggerRef}
          type="button"
          aria-label={label}
          className="-my-2.5 -mx-1.5 inline-flex size-8 cursor-pointer items-center justify-center rounded-sm align-middle text-muted-foreground/70 transition-colors duration-200 hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
        >
          <Info className={size === 'sm' ? 'size-3.5' : 'size-4'} aria-hidden="true" />
        </Popover.Trigger>
        <Popover.Portal container={container ?? undefined}>
          <Popover.Content
            side="bottom"
            align="start"
            sideOffset={4}
            collisionPadding={12}
            // 잉크 색면 — 툴팁과 같은 계열로 두어 '떠 있는 보조 정보'임을 색으로도 알린다
            className="z-50 max-w-70 rounded-md bg-foreground px-3 py-2 text-xs leading-relaxed break-keep text-background shadow-md"
          >
            {children}
            <Popover.Arrow className="size-2.5 -translate-y-[calc(50%+1px)] rotate-45 rounded-[2px] bg-foreground fill-foreground" />
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </>
  )
}
