/** AD-000 로그인 화면 자체 점검 — 기획서 고정 문구와 상태별 액션이 그대로인지 본다.
 *
 * 프레임워크를 새로 깔지 않으려고 assert + react-dom/server만 쓴다. routes/chat/selfcheck.tsx와 같은 방식:
 *
 *   cd web && node -e "import('vite').then(async v=>{const s=await v.createServer({server:{middlewareMode:true},appType:'custom'});await s.ssrLoadModule('/src/routes/admin/login/selfcheck.tsx');await s.close()})"
 *
 * 통과하면 "ad-auth login selfcheck: 통과"가 찍힌다. 여기가 깨지면 로그인 카드 문구가 바뀐 것이다. */
/// <reference types="node" />
// ↑ tsconfig.app.json의 types는 vite/client뿐이다. 이 파일만 node에서 도는 스크립트라 여기서만 끌어온다.
import assert from 'node:assert/strict'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router'

// 아이디 저장이 localStorage를 읽는다 — node에는 없으므로 먼저 심고 화면을 불러온다(그래서 동적 import)
Object.defineProperty(globalThis, 'localStorage', {
  value: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  writable: true,
})
const { LoginPage } = await import('../LoginPage')
const { PasswordResetPanel } = await import('./PasswordResetPanel')
const { PasswordChangeModal } = await import('./PasswordChangeModal')

const at = (path: string) =>
  renderToStaticMarkup(
    <MemoryRouter initialEntries={[path]}>
      <LoginPage />
    </MemoryRouter>,
  )

// 1. 로그인 카드 고정 문구 — 토씨 하나 바뀌면 안 된다(AD-000 1-2)
{
  const html = at('/admin/login')
  assert.ok(html.includes('관리자 로그인'))
  assert.ok(html.includes('등록된 관리자 계정으로 로그인해 주세요.'))
  assert.ok(html.includes('아이디 또는 이메일'))
  assert.ok(html.includes('admin@example.com'))
  assert.ok(html.includes('비밀번호를 입력하세요'))
  assert.ok(html.includes('아이디 저장'))
  assert.ok(html.includes('비밀번호 재설정'))
  assert.ok(html.includes('공용 기기에서는 아이디 저장을 사용하지 마세요.'))
  assert.ok(html.includes('5회 실패 시 10분간 제한됩니다.'))
  // 입력 미완료면 [로그인] 비활성 + 사유 표기(1-3)
  assert.ok(html.includes('disabled'))
  assert.ok(html.includes('아이디와 비밀번호를 입력해 주세요'))
  // 인증 전에는 셸을 그리지 않는다 — GNB 메뉴가 새어 나오면 안 된다
  assert.ok(!html.includes('지식베이스'))
}

// 2. Case 4 세션 만료 — 보호된 URL에서 넘어왔을 때만 안내한다(1-3)
{
  const withReturn = at('/admin/login?returnTo=%2Fadmin%2Fsettings%2Faccess')
  assert.ok(withReturn.includes('안전한 이용을 위해 세션이 종료되었습니다. 다시 로그인하면 이전 화면으로 돌아갑니다.'))
  assert.ok(withReturn.includes('다시 로그인'))
  assert.ok(!at('/admin/login').includes('세션이 종료되었습니다'), '직접 진입에는 만료 안내를 띄우지 않는다')
}

// 3. 메일 링크(?reset_token=)로 들어오면 ③ 새 비밀번호 설정부터 시작한다(1-4 ③)
{
  const html = at('/admin/login?reset_token=abc')
  assert.ok(html.includes('새 비밀번호 확인'))
  assert.ok(html.includes('10자 이상 · 영문/숫자/특수문자 조합 · 아이디 포함 불가'))
  assert.ok(html.includes('저장 시 이 계정의 다른 세션을 모두 종료하고 로그인 화면으로 이동합니다'))
  assert.ok(!html.includes('등록된 관리자 계정으로 로그인해 주세요.'), '로그인 폼과 동시에 그리지 않는다')
}

// 4. ① 재설정 요청 — 계정 탐색 차단 안내와 되돌아가기
{
  const html = renderToStaticMarkup(<PasswordResetPanel token={null} onBackToLogin={() => {}} />)
  assert.ok(html.includes('가입된 이메일'))
  assert.ok(html.includes('재설정 링크 보내기'))
  assert.ok(html.includes('계정 존재 여부와 무관하게 같은 완료 안내를 표시합니다 (계정 탐색 · 등록 여부 확인 차단)'))
  assert.ok(html.includes('← 로그인으로 돌아가기'))
  assert.ok(!html.includes('재설정 링크를 보냈습니다'), '②는 조작 후 상태다')
}

// 5. 비밀번호 변경 모달(1-5) — 3필드 · 규칙 안내 원문 · 푸터 `취소`/`변경`. 입력 전에는 [변경] 비활성
{
  const html = renderToStaticMarkup(<PasswordChangeModal open onClose={() => {}} />)
  assert.ok(html.includes('비밀번호 변경'))
  assert.ok(html.includes('현재 비밀번호'))
  assert.ok(html.includes('새 비밀번호 확인'))
  assert.ok(html.includes('10자 이상 · 영문/숫자/특수문자 조합 · 최근 사용한 비밀번호 재사용 불가'))
  assert.ok(html.includes('취소'))
  assert.ok(html.includes('변경'))
  assert.ok(html.includes('현재 비밀번호와 새 비밀번호를 입력해 주세요'), '비활성 사유를 함께 쓴다')
  // 재설정 ③ 규칙 문구와 섞이지 않는다(기획서가 화면마다 다른 규칙을 적었다)
  assert.ok(!html.includes('아이디 포함 불가'))
  // 위험 작업 재확인(30분)도 변경 사유도 거치지 않는다 — 공통 모달의 사유·재인증 필드가 없어야 한다
  assert.ok(!html.includes('confirm-field'))
}

console.log('ad-auth login selfcheck: 통과')
