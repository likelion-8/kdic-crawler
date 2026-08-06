/** 챗봇 화면 자체 점검 — 기획서 고정 문구와 Enter 전송 규칙이 그대로인지 본다.
 *
 * 프레임워크를 새로 깔지 않으려고 assert + react-dom/server만 쓴다. app/selfcheck.ts와 같은 방식:
 *
 *   cd web && node -e "import('vite').then(async v=>{const s=await v.createServer({server:{middlewareMode:true},appType:'custom'});await s.ssrLoadModule('/src/routes/chat/selfcheck.tsx');await s.close()})"
 *
 * 통과하면 "chat-page selfcheck: 통과"가 찍힌다. 여기가 깨지면 웰컴 문구가 바뀌었거나
 * 한글 조합 중 Enter로 질문이 날아가는 상태다. */
/// <reference types="node" />
// ↑ tsconfig.app.json의 types는 vite/client뿐이다. 이 파일만 node에서 도는 스크립트라 여기서만 끌어온다.
import assert from 'node:assert/strict'
import { renderToStaticMarkup } from 'react-dom/server'
import { ToastProvider } from '../../components/ui'
import { needsNewChatConfirm, newChatLoss } from './ChatPage'
import { isSubmitKey } from './Composer'
import { RetryExhaustedPanel } from './RetryExhaustedPanel'
import { FALLBACK_SUGGESTIONS, WelcomeScreen } from './WelcomeScreen'

// 1. Enter 전송 규칙 — IME 조합 중에는 절대 전송하지 않는다(한글 입력)
{
  assert.equal(isSubmitKey({ key: 'Enter', shiftKey: false, isComposing: false }), true)
  assert.equal(isSubmitKey({ key: 'Enter', shiftKey: false, isComposing: true }), false, '조합 중 Enter = 조합 확정')
  assert.equal(isSubmitKey({ key: 'Enter', shiftKey: true, isComposing: false }), false, 'Shift+Enter = 줄바꿈')
  assert.equal(isSubmitKey({ key: 'a', shiftKey: false, isComposing: false }), false)
}

// 2. 웰컴 화면 고정 문구 — 토씨 하나 바뀌면 안 된다(CB-001 §2.3)
{
  const html = renderToStaticMarkup(
    <WelcomeScreen questions={FALLBACK_SUGGESTIONS} onPick={() => {}} />,
  )
  assert.ok(/AI챗봇 <span[^>]*>예솜24<\/span>에 오신 걸 환영해요/.test(html), '웰컴 문구 원문 + 서비스명 포인트 컬러')
  // 기획서 원문 `자주 묻는 질문 TOP 10` + `누르면 바로 질문돼요`는 뺐다(사용자 지시) —
  // 개수는 운영자가 바꿀 수 있어 TOP 10 고정이 사실과 어긋났고, 우측 문구는 화살표가 대신한다
  assert.ok(html.includes('자주 묻는 질문'))
  assert.ok(!html.includes('TOP 10'), '개수 고정 표기는 쓰지 않는다')
  assert.ok(!html.includes('누르면 바로 질문돼요'))
  assert.ok(html.includes('착오송금 반환까지 얼마나 걸리나요?'))
  // 행은 키보드·스크린리더에서 버튼으로 인식돼야 한다 (CB-001 Desc ⑤).
  // 4번째부터는 CSS로만 감춘다 — 10개 전부 DOM에 남아 접힌 상태에서도 읽힌다
  assert.equal(html.match(/data-slot="welcome-row"/g)?.length, 10)
  assert.equal(FALLBACK_SUGGESTIONS.length, 10)
  // 6개 업무 칸도 누르면 질문이 나가는 버튼이다(FAQ 행과 같은 동작)
  assert.equal(html.match(/data-slot="welcome-business"/g)?.length, 6, '업무 6종이 모두 버튼')
  assert.ok(html.includes('예금자보호제도'), '업무명은 BUSINESS_FUNCTIONS 코드값 그대로')
  // 첫 화면은 3개만 — 나머지는 [더보기]로 편다
  // JSX가 class 속성의 `>`를 `&gt;`로 이스케이프하므로 그 형태로 찾는다
  assert.ok(html.includes('nth-child(n+4)]:hidden'), '기본은 3개까지만 보인다')
  assert.ok(html.includes('더보기'), '나머지는 [더보기]로 편다')
}

// 2-1. 점검·준비 실패 중에는 FAQ 행도 누를 수 없다 — 무반응 클릭 금지(CB-004 Case 6)
{
  const html = renderToStaticMarkup(
    <WelcomeScreen questions={FALLBACK_SUGGESTIONS} onPick={() => {}} disabled />,
  )
  assert.equal(html.match(/data-slot="welcome-row"[^>]*\bdisabled/g)?.length, 10)
  // 속성 순서에 기대지 않는다 — 공통 Button은 disabled를 data-slot보다 먼저 렌더한다
  const businessTags = html.match(/<button[^>]*welcome-business[^>]*>/g) ?? []
  assert.equal(businessTags.filter((t) => t.includes('disabled')).length, 6, '업무 칸도 함께 잠긴다')
}

// 3. 추천 질문이 0건이면 카드를 통째로 감춘다 — 빈 상태 문구를 만들지 않는다(CB-DF-003 6절)
{
  const html = renderToStaticMarkup(<WelcomeScreen questions={[]} onPick={() => {}} />)
  assert.ok(!html.includes('자주 묻는 질문'))
  assert.ok(html.includes('예솜24'), '카드가 없어도 웰컴 자체는 남는다')
}

// 4. 재시도 2회 소진 패널 — 요청 ID를 문의용으로 함께 보여준다(CB-004 Case 5)
{
  const html = renderToStaticMarkup(
    <ToastProvider>
      <RetryExhaustedPanel requestId="req_8f2c41ab" />
    </ToastProvider>,
  )
  assert.ok(html.includes('두 번 다시 시도했지만 답변을 만들지 못했어요.'))
  assert.ok(html.includes('공식 문의 안내'))
  assert.ok(html.includes('요청 ID 복사'))
  assert.ok(html.includes('req_8f2c41ab'))
  assert.ok(!html.includes('다시 시도<'), '재시도는 더 이상 유도하지 않는다')
}

// 5. 요청 ID가 없는 오류(서버 미도달)면 ID 자리를 빈 채로 그리지 않는다
{
  const html = renderToStaticMarkup(
    <ToastProvider>
      <RetryExhaustedPanel requestId="" />
    </ToastProvider>,
  )
  assert.ok(!html.includes('요청 ID <'), '빈 ID 자리를 남기지 않는다')
  assert.ok(html.includes('운영 시간과 준비 정보는 문의 안내에서 확인'))
  // 복사할 것이 없으면 버튼도 두지 않는다 — 사용자 화면에 '요청 ID가 없습니다'를 띄우지 않는다
  assert.ok(!html.includes('요청 ID 복사'), 'ID가 없으면 복사 버튼을 그리지 않는다')
}

// 6. [새 대화] 확인 조건 — "작성 중인 입력이나 열린 피드백 폼이 있으면"(CB-002 Desc ⑦).
//    입력만 보던 시절에는 사유를 적다가 [새 대화]를 누르면 경고 없이 날아갔다.
{
  assert.equal(needsNewChatConfirm('', 0), false, '잃을 게 없으면 묻지 않는다')
  assert.equal(needsNewChatConfirm('   ', 0), false, '공백만 있는 입력은 작성 중이 아니다')
  assert.equal(needsNewChatConfirm('착오송금', 0), true)
  assert.equal(needsNewChatConfirm('', 1), true, '피드백 폼만 열려 있어도 확인을 받는다')

  // 모달 문구는 실제로 열려 있는 것만 말한다 — 없는 것이 사라진다고 쓰지 않는다
  assert.equal(newChatLoss('', 0), '')
  assert.equal(newChatLoss('', 1), '작성 중인 피드백이 사라지고 ')
  assert.equal(newChatLoss('착오송금', 0), '작성 중인 질문이 사라지고 ')
  assert.equal(newChatLoss('착오송금', 2), '작성 중인 질문과 작성 중인 피드백이 사라지고 ')
}

console.log('chat-page selfcheck: 통과')
