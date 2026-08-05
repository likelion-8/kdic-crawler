/** 보기 전용 안내 — 권한이 없어 화면(또는 카드) 전체가 잠겼을 때 **한 번만** 쓴다.
 *
 * 왜 컨트롤마다 쓰지 않나: 예전에는 잠긴 컨트롤 옆마다 `disabledReason` 캡션을 달았다.
 * 그 결과 VIEWER가 RAG 파라미터 화면을 열면 '수정하려면 EDITOR 권한이 필요합니다'가
 * 열두 행 옆에 그대로 열두 번 반복됐다(사용자 지적). 같은 말을 반복하는 대신 화면 위에서
 * 한 번 말하고, 컨트롤 쪽 사유는 sr-only로만 남긴다(Field·Button 주석 참고).
 *
 * 톤은 info다 — 권한이 없는 것은 오류도 경고도 아니다. 조치 없이 읽고 지나가는 상태다. */
import { Notice } from './Notice'

export interface ReadOnlyNoticeProps {
  /** 무엇이 있어야 바꿀 수 있는지 — 예: `편집자(EDITOR) 이상` */
  need: string
  /** 이 화면에서 무엇을 못 하는지 — 예: `파라미터를 바꾸려면`. 생략하면 '수정하려면' */
  action?: string
}

export function ReadOnlyNotice({ need, action = '수정하려면' }: ReadOnlyNoticeProps) {
  return (
    <div role="status">
      <Notice tone="info" variant="inline">
        <strong className="font-semibold">보기 전용</strong> · {action} {need} 권한이 필요합니다
      </Notice>
    </div>
  )
}
