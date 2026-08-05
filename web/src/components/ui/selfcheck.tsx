/** 공통 컴포넌트 자체 점검 — '비활성 사유를 어떻게 알리는가' 규칙을 고정한다.
 *
 * 이 규칙은 화면 42곳이 공유한다. 한 곳에서 되돌리면 전 화면이 같이 되돌아가므로 여기서 막는다.
 *  · 버튼 옆에 사유를 **글자로 상시 노출하지 않는다** — 버튼이 밀리고 줄이 접힌다(2026-08-04 사용자 지적)
 *  · 대신 툴팁 + `aria-describedby`로 묶인 sr-only 문장을 둔다(툴팁을 안 열어도 읽힌다)
 *  · 폼 컨트롤(Field)도 같다. 권한으로 화면이 잠기면 ReadOnlyNotice가 위에서 한 번만 말한다
 *  · `loading` 중에는 사유를 쓰지 않는다 — 그때 못 누르는 이유는 '보내는 중'이다
 *
 * 실행: `pnpm check` */
/// <reference types="node" />
import assert from 'node:assert/strict'
import { renderToStaticMarkup } from 'react-dom/server'
import { Button } from './Button'
import { ReadOnlyNotice } from './ReadOnlyNotice'
import { RefreshBar } from './RefreshBar'
import { SectionError } from './SectionError'
import { TextField } from './form/TextField'
import { ApiRequestError } from '../../lib/api/client'

const REASON = '편집자(EDITOR) 이상만 바꿀 수 있습니다'

/** 화면에 글자로 보이는 부분만 남긴다 — sr-only span과 태그를 걷어낸 것 */
function visibleText(html: string): string {
  return html.replace(/<span class="sr-only"[^>]*>.*?<\/span>/g, '').replace(/<[^>]+>/g, '')
}

// 1. 비활성 + 사유 — 보이는 캡션은 없고, sr-only 문장이 aria-describedby로 묶인다
{
  const html = renderToStaticMarkup(
    <Button disabled disabledReason={REASON}>
      저장
    </Button>,
  )
  assert.ok(!visibleText(html).includes(REASON), '사유를 버튼 옆 글자로 상시 노출하지 않는다')
  assert.ok(html.includes(REASON), '사유 자체는 sr-only로 남아 있어야 한다')

  const described = /aria-describedby="([^"]+)"/.exec(html)
  assert.ok(described, '버튼에 aria-describedby가 붙는다')
  assert.ok(
    html.includes(`id="${described[1]}"`),
    'aria-describedby가 가리키는 id가 실제로 있어야 한다(끊긴 참조 금지)',
  )
}

// 2. 제출 중 — 사유를 달지 않는다. 붙이면 '저장 중'인데 '권한이 없다'가 뜬다
{
  const html = renderToStaticMarkup(
    <Button loading disabledReason={REASON}>
      저장
    </Button>,
  )
  assert.ok(!html.includes(REASON), 'loading 중에는 비활성 사유를 쓰지 않는다')
  assert.ok(html.includes('aria-busy="true"'))
}

// 3. 누를 수 있으면 사유를 붙이지 않는다(래퍼도 만들지 않는다)
{
  const html = renderToStaticMarkup(<Button disabledReason={REASON}>저장</Button>)
  assert.ok(!html.includes(REASON))
  assert.ok(html.startsWith('<button'), '멀쩡한 버튼은 감싸지 않는다')
}

// 4. 폼 컨트롤도 같은 규칙 — 컨트롤 옆에 사유를 글자로 두지 않는다
//    (권한 문장이 행마다 되풀이돼 화면이 그 말로 뒤덮였다)
{
  const html = renderToStaticMarkup(
    <TextField label="문항 ID" value="kmrs_fee_pl1" disabled disabledReason={REASON} onChange={() => {}} />,
  )
  assert.ok(!visibleText(html).includes(REASON), '컨트롤 옆 캡션 금지')
  assert.ok(html.includes(REASON), '사유는 sr-only로 남긴다')
}

// 5. 사람이 볼 안내는 화면에서 한 번 — ReadOnlyNotice
{
  const html = renderToStaticMarkup(<ReadOnlyNotice need="편집자(EDITOR) 이상" action="파라미터를 바꾸려면" />)
  const text = visibleText(html)
  assert.ok(text.includes('보기 전용'))
  assert.ok(text.includes('파라미터를 바꾸려면 편집자(EDITOR) 이상 권한이 필요합니다'))
  assert.ok(html.includes('role="status"'), '조치가 아니라 상태다 — alert가 아니라 status')
}

// 6. 실패 패널 — 문의할 때 댈 **요청 ID**를 반드시 함께 보여준다.
//    사본이 셋으로 갈라졌을 때 그중 하나(지식베이스 FailurePanel)가 이걸 빠뜨리고 있었다
{
  const err = new ApiRequestError(500, {
    code: 'INTERNAL',
    user_message: '처리하지 못했습니다.',
    retryable: true,
    fallback_sources: [],
    request_id: 'req_9f2a',
  })
  const html = renderToStaticMarkup(<SectionError error={err} onRetry={() => {}} />)
  assert.ok(html.includes('처리하지 못했습니다.'), '문구는 서버 user_message 그대로')
  assert.ok(html.includes('요청 ID req_9f2a'), '요청 ID를 빠뜨리지 않는다')
  assert.ok(html.includes('다시 시도'), 'retryable이면 재시도를 그린다')
  assert.ok(html.includes('role="alert"'))

  // retryable=false면 재시도를 그리지 않는다 — 같은 요청을 또 보내게 두지 않는다
  const fixed = new ApiRequestError(403, { ...err.error, retryable: false })
  assert.ok(!renderToStaticMarkup(<SectionError error={fixed} onRetry={() => {}} />).includes('다시 시도'))

  // 오류가 없으면 자리를 만들지 않는다
  assert.equal(renderToStaticMarkup(<SectionError error={null} />), '')
}

// 7. 갱신 줄 — 시각이 없으면 지어내지 않는다(복원된 화면에 '방금'을 찍으면 거짓말이 된다)
{
  const html = renderToStaticMarkup(<RefreshBar at="2026-08-04T19:06:00+09:00" onRefresh={() => {}} />)
  assert.ok(html.includes('마지막 갱신 08-04 19:06'), '기본 라벨은 갱신 · 시각은 MM-DD HH:mm')

  const recheck = renderToStaticMarkup(
    <RefreshBar at={null} label="확인" action="지금 확인" onRefresh={() => {}} />,
  )
  assert.ok(!recheck.includes('마지막'), '시각이 없으면 시각 줄 자체를 그리지 않는다')
  assert.ok(recheck.includes('지금 확인'), '동작 이름은 화면마다 다를 수 있다(갱신 ≠ 서버 재검사)')
}

console.log('ui 비활성 사유 selfcheck: 통과')
