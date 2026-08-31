/** 대화 아바타 소스 — 화자별 이미지와 폴백 이모지를 한곳에서 정한다.
 *
 * 챗봇은 팀 마스코트(원본은 src/assets/avatar-chatbot.png 하나만 둔다 — data/ 의 사본은 2026-08-31 정리로 삭제), 사용자는 팀에서 받은 아기 사자 사진이다.
 * 교체할 때는 `src/assets/`의 파일만 바꾸면 말풍선·웰컴에 한 번에 반영된다. */
import chatbotAvatar from '@/assets/avatar-chatbot.png'
import userAvatar from '@/assets/avatar-user.png'

export interface AvatarSource {
  src?: string
  emoji: string
  label: string
}

/** 이모지 폴백값은 CB-005 3.6 목업 기준(사용자 🦁 · 챗봇 🤖).
 * ⚠ CM-DF-003 02절은 😀·🤖로 적어 두 곳이 어긋난다 — 기획서 정정 대상. */
export const AVATARS = {
  user: { src: userAvatar, emoji: '🦁', label: '사용자' } satisfies AvatarSource,
  bot: { src: chatbotAvatar, emoji: '🤖', label: '챗봇 예솜24' } satisfies AvatarSource,
} as const
