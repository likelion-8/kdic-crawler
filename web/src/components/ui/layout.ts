/** 화면 골격에 쓰는 레이아웃 규칙. 화면마다 다시 정하면 같은 결함이 화면 수만큼 재발한다. */


/** 설정 화면의 카드 2열 골격(AD-008 프롬프트·가드레일 · AD-009 운영 정책).
 *
 * `items-start`를 쓰면 짧은 열이 자기 높이만큼만 서고 그 아래에 빈 단이 남는다 —
 * 카드 경계가 서로 다른 높이에서 끊겨 화면에 단차가 생긴다(사용자 지적).
 * 기본 stretch로 둬서 두 열의 아래 끝을 맞추고, 남는 높이는 CARD_COLUMN이 흡수한다.
 *
 * ⚠ 표에는 쓰지 말 것 — 표는 전체 폭을 쓰고 상세는 모달로 뜬다(DetailModal 주석 참조). */
export const CARD_COLUMNS = 'grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,426fr)_minmax(0,410fr)]'

/** 카드 2열 중 한 열. 남는 높이는 **마지막 카드**가 먹는다 —
 * 카드가 하나뿐인 열에서는 그 카드가 열 전체를 채워 옆 열과 아래 끝이 맞는다. */
export const CARD_COLUMN = 'flex min-w-0 flex-col gap-4 [&>*:last-child]:flex-1'
