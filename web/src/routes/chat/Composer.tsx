/** 질문 입력창 — CB-001 Description ③④ · CB-DF-003 02절(질문 입력창·전송 버튼 상태 정의).
 *
 * 고정 문구는 기획서 원문 그대로 쓴다.
 *  - placeholder(웰컴) `예솜24가 어떤 일을 도와드릴까요?` / (대화 중) `질문을 입력해 주세요...`
 *  - 글자 수는 입력창 오른쪽 아래 `128 / 500` 형식 상시 표시, 500자 도달 시 붉게 강조(CB-002 Desc ⑥)
 *
 * Enter 전송 · Shift+Enter 줄바꿈 · 전송 중 잠금(중복 제출 차단).
 * 한글 IME 조합 중의 Enter는 '조합 확정'이지 전송이 아니다 — isComposing을 반드시 본다. */
import { useEffect, useRef } from 'react'
import type { CompositionEvent, KeyboardEvent } from 'react'
import { Send } from 'lucide-react'
import { Button } from '../../components/ui'
import { cn } from '@/lib/utils'

/** 입력 최대 길이 — CM-DF-004 부록 A `INPUT_MAX = 500` · CB-001 Desc ③ "최대 500자, 초과 입력 차단" */
export const INPUT_MAX = 500

/** 여러 줄 입력 시 입력창이 자라는 상한(px). 기획서에 값이 없어 4줄 남짓으로 정했다 */
const MAX_GROW_PX = 140

/** 이 Enter가 '전송'인가. Shift+Enter는 줄바꿈이고, IME 조합 중 Enter는 조합 확정이라 전송이 아니다.
 * (한글 입력에서 이 판정을 빼먹으면 첫 글자가 조합되자마자 질문이 날아간다) */
export function isSubmitKey(e: { key: string; shiftKey: boolean; isComposing: boolean }): boolean {
  return e.key === 'Enter' && !e.shiftKey && !e.isComposing
}

export interface ComposerProps {
  value: string
  onChange(next: string): void
  /** 전송 — 앞뒤 공백을 뗀 문자열을 넘긴다 */
  onSubmit(text: string): void
  /** 웰컴 화면이면 placeholder가 다르다 (CB-DF-003 02절 표 1행) */
  welcome?: boolean
  /** 답변 생성 중 · 점검 중이면 입력을 잠근다 (CB-004 Case 1·Case 6) */
  disabled?: boolean
}

export function Composer({ value, onChange, onSubmit, welcome = false, disabled = false }: ComposerProps) {
  const areaRef = useRef<HTMLTextAreaElement>(null)
  // onKeyDown이 조합 종료 직후에도 들어오는 브라우저가 있어 상태를 따로 들고 본다
  const composingRef = useRef(false)

  // 줄바꿈(Shift+Enter)한 만큼 입력창이 자란다. 상한을 넘을 때만 내부 스크롤.
  //
  // overflow를 직접 껐다 켜는 이유: 줄높이가 소수(15px × 1.625 = 24.375px)라 scrollHeight가
  // 정수로 내려가고, 그 값을 height로 넣으면 실제 내용이 1px 남짓 넘쳐 한 줄짜리 빈 입력창에도
  // 스크롤바가 뜬다. 상한 미만이면 넘칠 일이 없으므로 hidden으로 둔다.
  useEffect(() => {
    const el = areaRef.current
    if (!el) return
    el.style.height = 'auto'
    const full = el.scrollHeight // height가 auto인 동안 재야 실제 내용 높이가 나온다
    el.style.height = `${Math.min(full, MAX_GROW_PX)}px`
    el.style.overflowY = full > MAX_GROW_PX ? 'auto' : 'hidden'
  }, [value])

  const trimmed = value.trim()
  // 빈값·공백만이면 전송 비활성 (CB-001 Desc ③④)
  const canSend = trimmed.length > 0 && !disabled

  const submit = () => {
    if (!canSend) return
    onSubmit(trimmed)
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // onKeyDown이 조합 종료 직후에도 들어오는 브라우저가 있어 isComposing을 두 경로로 본다
    const isComposing = e.nativeEvent.isComposing || composingRef.current
    if (!isSubmitKey({ key: e.key, shiftKey: e.shiftKey, isComposing })) return
    e.preventDefault()
    submit()
  }

  const handleComposition = (e: CompositionEvent<HTMLTextAreaElement>) => {
    composingRef.current = e.type === 'compositionstart'
  }

  const atMax = value.length >= INPUT_MAX

  return (
    <div className="mx-auto w-full max-w-(--chat-input-max)">
      {/* 입력 바 — 큰 라운드(18px)는 말풍선과 짝이라 유지한다(기획서 고정 규격).
          포커스는 테두리 색 전환만 (CB-DF-003 02절 "텍스트 입력 중") — 보라 후광(ring)은 두지 않는다 */}
      <div
        className={cn(
          'flex min-h-14 items-end gap-2 rounded-[18px] border-2 bg-card p-1.5 pl-4 transition-colors duration-200 focus-within:border-primary max-md:pl-3.5',
          disabled && 'bg-muted',
        )}
      >
        <label className="sr-only" htmlFor="chat-input">
          질문 입력
        </label>
        <textarea
          id="chat-input"
          ref={areaRef}
          className="max-h-[140px] min-w-0 flex-1 resize-none self-center border-0 bg-transparent py-2 text-[15px] leading-relaxed outline-none placeholder:text-muted-foreground focus-visible:outline-none disabled:cursor-not-allowed"
          rows={1}
          value={value}
          // maxLength로 초과 입력 자체를 막는다(붙여넣기 포함) — CB-001 Desc ③
          maxLength={INPUT_MAX}
          disabled={disabled}
          placeholder={welcome ? '예솜24가 어떤 일을 도와드릴까요?' : '질문을 입력해 주세요...'}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          onCompositionStart={handleComposition}
          onCompositionEnd={handleComposition}
        />
        {/* 전송 버튼 — 기획서 §2.5는 40×40 · radius ≈10의 '둥근 사각형'이다(원형이 아니다).
            크기만 44×44로 올린다(터치 타깃 44 이상, CM-DF-004 09절 — 기획서 40보다 우선).
            반경 12px = 바깥 18px − 안쪽 여백 6px(p-1.5). 동심원 규칙이라 두 모서리가 나란히 돈다.
            입력이 생기면 회색에서 보라로 차오른다(기본 opacity-50 대신 명시적 회색) */}
        <Button
          variant="primary"
          className="size-11 shrink-0 rounded-[12px] p-0 disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100"
          disabled={!canSend}
          onClick={submit}
          aria-label="전송"
          title="전송"
        >
          <Send className="size-5" aria-hidden="true" />
        </Button>
      </div>
      {/* 글자 수는 상시 표시. 색만으로 알리지 않도록 500자 도달 시 텍스트도 함께 바뀐다(CM-DF-004 09절) */}
      <p
        className={cn(
          'mx-1.5 mt-1.5 text-right text-xs',
          atMax ? 'font-medium text-destructive' : 'text-muted-foreground',
        )}
      >
        {value.length} / {INPUT_MAX}
        {atMax && <span className="font-normal"> · 최대 글자 수에 도달했어요</span>}
      </p>
    </div>
  )
}
