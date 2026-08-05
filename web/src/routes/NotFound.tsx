/** 정의되지 않은 경로. 기획서에 404 화면 설계가 없어 자리표시자만 둔다. */
import { ScreenStub } from '../app/ScreenStub'

export function NotFound() {
  return <ScreenStub id="—" title="페이지를 찾을 수 없습니다" />
}
