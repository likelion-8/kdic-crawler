/** 대화 아바타 — CM-DF-003 02절 "아바타 38px 원형 · 아이콘 로드 실패 시 이모지로 대체".
 *
 * CB-002 마커 2가 요구한 폴백 순서를 그대로 구현한다: **등록된 이미지 → 이모지**.
 * (기획서는 '기본 아이콘' 단계를 하나 더 두지만 별도 기본 아이콘 에셋이 없어 두 단계로 접었다.
 *  기본 아이콘이 납품되면 img 하나를 사이에 끼우면 된다 — 문서 수정 대상.)
 *
 * 이미지가 있어도 로드에 실패하면(경로 오류·네트워크) onError로 이모지로 떨어진다.
 * 대체 텍스트는 어느 단계든 같은 값을 유지해 스크린리더 경험이 흔들리지 않게 한다. */
import { useState } from 'react'
import type { CSSProperties } from 'react'
import { cn } from '@/lib/utils'

export interface AvatarProps {
  /** 등록된 프로필 이미지. 없으면 곧바로 이모지 단계 */
  src?: string
  /** 이미지가 없거나 로드에 실패했을 때 (CM-DF-003 02절) */
  emoji: string
  /** 스크린리더용 이름 — 이미지·이모지 어느 쪽이 그려져도 동일 */
  label: string
  /** 웰컴 아이콘(72px)처럼 크기가 다른 자리에서 덮어쓴다 */
  className?: string
  /** 진입 안무 순서(--reveal-i) 주입용 */
  style?: CSSProperties
}

export function Avatar({ src, emoji, label, className, style }: AvatarProps) {
  const [failed, setFailed] = useState(false)
  const showImage = src !== undefined && !failed

  return (
    <span
      role="img"
      aria-label={label}
      style={style}
      // 헤어라인 원 — 색면·그림자 없이 위치와 그림으로만 화자를 구분한다
      className={cn(
        'flex size-(--chat-avatar) shrink-0 items-center justify-center overflow-hidden rounded-full border bg-card text-xl leading-none',
        className,
      )}
    >
      {showImage ? (
        <img
          className="size-full object-cover"
          src={src}
          alt=""
          // 부모 span이 role=img + aria-label을 이미 지므로 이미지 자체는 장식으로 둔다
          aria-hidden="true"
          draggable={false}
          onError={() => setFailed(true)}
        />
      ) : (
        emoji
      )}
    </span>
  )
}
