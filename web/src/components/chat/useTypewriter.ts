/** 스트리밍 본문을 고른 속도로 흘려보내는 훅.
 *
 * 왜 필요한가: SSE `answer_delta`는 서버가 끊어 주는 대로 온다. 한 번에 여러 글자가 오거나
 * 간격이 들쭉날쭉하면 화면이 뚝뚝 끊겨 보인다(사용자 지적). 서버 청킹은 백엔드 몫이라
 * 프론트에서 제어할 수 없으므로, **받은 것을 버퍼에 쌓고 화면에는 일정 속도로 푼다.**
 *
 * 규칙
 * - 프레임마다 경과 시간만큼 글자를 푼다(rAF). 프레임 드랍이 나도 속도가 유지된다.
 * - 버퍼가 많이 밀리면 가속한다 — 답변이 다 왔는데 화면만 한참 뒤처지면 답답하다.
 * - **스트리밍이 끝나도 남은 글자를 마저 흘린다.** 여기서 전문으로 끊어 맞추면 글자가 순간
 *   이동하고 곧바로 하단 섹션까지 튀어나와 두 번 덜컥거린다. 대신 `done`을 내보내
 *   화면이 "본문이 끝난 뒤"에 섹션을 열도록 한다.
 * - 흘린 적 없이 완성본으로 들어온 답변(대화 복원·과거 말풍선)은 즉시 전문으로 보여준다.
 * - `prefers-reduced-motion`이면 애니메이션 없이 즉시 전문(CM-DF-004 09절).
 *
 * ⚠ 구현 주의: 루프를 **컴포넌트 수명 동안 하나만** 돌린다. 델타마다 effect를 다시 걸어
 * rAF를 취소·재등록하면 그때마다 기준 시각(last)이 리셋돼 그 사이 흐른 시간이 통째로
 * 버려진다. 델타가 20~30ms마다 오는 상황에서는 진행이 거의 멈춘 것처럼 느려진다.
 * 그래서 target·streaming은 ref로 읽고, effect는 "루프가 돌고 있는지"만 보장한다.
 */
import { useEffect, useRef, useState } from 'react'

/** 기본 속도(글자/초). 한글 기준으로 읽히는 속도에 맞춘 값 */
const CHARS_PER_SEC = 90
/** 밀린 글자가 이보다 많으면 가속해서 따라잡는다 */
const CATCH_UP_AT = 60
const CATCH_UP_FACTOR = 4

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export interface Typed {
  /** 지금까지 화면에 보여줄 본문 */
  text: string
  /** 흘릴 것이 남지 않았는가 — 하단 섹션을 여는 신호 */
  done: boolean
}

export function useTypewriter(target: string, streaming: boolean): Typed {
  // 한 번이라도 스트리밍이었으면 그 뒤로도 흘린다. 처음부터 완성본이면 흘리지 않는다
  const everStreamed = useRef(streaming)
  if (streaming) everStreamed.current = true
  const animate = everStreamed.current && !prefersReducedMotion()

  const [shown, setShown] = useState(animate ? '' : target)

  // 루프가 매 프레임 읽는 최신 값들 — 이걸 ref로 두어야 effect를 다시 걸지 않는다
  const targetRef = useRef(target)
  const streamingRef = useRef(streaming)
  targetRef.current = target
  streamingRef.current = streaming

  // 소수점 진행도를 유지해야 프레임마다 반올림으로 속도가 튀지 않는다
  const progress = useRef(animate ? 0 : target.length)
  const frame = useRef<number | undefined>(undefined)

  useEffect(() => {
    if (!animate) {
      progress.current = targetRef.current.length
      setShown(targetRef.current)
      return
    }
    // 이미 돌고 있으면 그대로 둔다 — 다시 걸면 기준 시각이 리셋된다
    if (frame.current !== undefined) return

    let last = performance.now()
    const tick = (now: number) => {
      const dt = (now - last) / 1000
      last = now
      const text = targetRef.current
      // 본문이 교체되거나 짧아졌으면 진행도를 되감는다(새 답변·재시도)
      if (progress.current > text.length) progress.current = 0

      const behind = text.length - progress.current
      if (behind > 0) {
        const speed = CHARS_PER_SEC * (behind > CATCH_UP_AT ? CATCH_UP_FACTOR : 1)
        progress.current = Math.min(text.length, progress.current + speed * dt)
        setShown(text.slice(0, Math.floor(progress.current)))
      } else if (!streamingRef.current) {
        // 다 흘렸고 서버도 끝났다 — 루프를 멈춘다(불필요한 rAF를 남기지 않는다)
        frame.current = undefined
        return
      }
      frame.current = requestAnimationFrame(tick)
    }
    frame.current = requestAnimationFrame(tick)
    return () => {
      if (frame.current !== undefined) cancelAnimationFrame(frame.current)
      frame.current = undefined
    }
    // target·streaming은 ref로 읽는다. 다만 루프가 멈춘 뒤 새 델타가 오면 다시 켜야 하므로
    // 두 값을 의존성에 남겨 "돌고 있는지" 검사를 다시 태운다(위 early-return이 중복 실행을 막는다)
  }, [animate, target, streaming])

  return { text: shown, done: !streaming && shown.length >= target.length }
}
