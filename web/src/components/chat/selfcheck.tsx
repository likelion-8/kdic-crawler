/** 답변 렌더러 자체 점검 — CB-DF-003 01절 '답변 하단 섹션 노출 매트릭스'가 그대로 지켜지는지 본다.
 *
 * 프레임워크를 새로 깔지 않으려고 assert + react-dom/server만 쓴다. app/selfcheck.ts와 같은 방식:
 *
 *   cd web && node -e "import('vite').then(async v=>{const s=await v.createServer({server:{middlewareMode:true},appType:'custom'});await s.ssrLoadModule('/src/components/chat/selfcheck.tsx');await s.close()})"
 *
 * 통과하면 "chat selfcheck: 통과"가 찍힌다. 여기가 깨지면 빈 배열인데 헤딩이 남거나(금지),
 * 범위 외 답변에 출처가 붙거나, 마커가 사용자에게 보이는 것이다. */
/// <reference types="node" />
// ↑ tsconfig.app.json의 types는 vite/client뿐이다. 이 파일만 node에서 도는 스크립트라 여기서만 끌어온다.
import assert from 'node:assert/strict'
import { renderToStaticMarkup } from 'react-dom/server'
import type { ApiError, Attachment, Source, SubAnswer } from '../../lib/api/types'
import { formatClock } from '../../lib/format'
import { AnswerMessage } from './AnswerMessage'
import { ClarificationMessage } from './ClarificationMessage'
import { ErrorMessage } from './ErrorMessage'

const SOURCE: Source = {
  page_id: 'dp_protlmts',
  breadcrumb: '예금자보호제도 > 보호한도',
  title: '예금자보호 한도 안내',
  url: 'https://www.kdic.or.kr/protect/protection_limit.do',
}
const DOC: Attachment = { label: '착오송금 반환지원 신청서', url: 'https://kmrs.kdic.or.kr/form', kind: 'document' }
const LINK: Attachment = { label: '착오송금 반환지원 신청방법', url: 'https://kmrs.kdic.or.kr/apply', kind: 'link' }

// 0. 말풍선 시각 — KST 고정 `오후 N:NN`. 서버가 시각을 안 주면 아예 그리지 않는다
//    (복원된 대화에 '지금' 시각을 찍으면 90분 전 대화에 방금 시각이 붙어 거짓이 된다)
{
  const AT = '2026-08-04T15:24:00+09:00'
  assert.equal(formatClock(AT), '오후 3:24', 'KST 12시간 · 앞자리 0 없음')
  assert.equal(formatClock('2026-08-04T09:05:00+09:00'), '오전 9:05')
  assert.equal(formatClock('2026-08-04T00:07:00+09:00'), '오전 12:07', '자정은 오전 12시')

  const withTime = renderToStaticMarkup(<AnswerMessage answer="보호 한도는 1억원입니다." at={AT} />)
  assert.ok(withTime.includes('오후 3:24'), '시각이 있으면 말풍선에 찍는다')
  assert.ok(withTime.includes('<time'), '시각은 <time>으로 표기한다')

  const noTime = renderToStaticMarkup(<AnswerMessage answer="보호 한도는 1억원입니다." />)
  assert.ok(!noTime.includes('<time'), '시각이 없으면 지어내지 않는다')

  // LLM이 계약을 어기고 내보내는 `**볼드**`는 리터럴 별표 대신 <strong>으로 그린다(2026-08-10).
  // 그 외 마크다운은 계속 파싱하지 않는다(CM-DF-003 02절)
  const bold = renderToStaticMarkup(<AnswerMessage answer="1. **신청 자격 확인**: 1년 이내" />)
  assert.ok(bold.includes('<strong>신청 자격 확인</strong>'), '**…**는 굵게 렌더')
  assert.ok(!bold.includes('**'), '별표 리터럴을 남기지 않는다')
}

// 1. 정보성 + 근거 사용 → 본문 + 참고 출처 (서류·신청 페이지는 조합 자체가 없다)
{
  const html = renderToStaticMarkup(<AnswerMessage answer="보호 한도는 1억원입니다." sources={[SOURCE]} />)
  assert.ok(html.includes('참고 출처'))
  assert.ok(html.includes('예금자보호 한도 안내'))
  assert.ok(html.includes('예금자보호제도 &gt; 보호한도'), '브레드크럼을 부제로 보여준다')
  assert.ok(!html.includes('필요 서류'))
  assert.ok(!html.includes('신청 페이지'))
  assert.ok(html.includes('ⓘ AI가 생성한 답변입니다'), 'AI 고지는 모든 답변 하단에 상시')
}

// 2. 빈 배열 = 헤딩 포함 섹션 통째 미렌더. 빈 상태 문구를 넣는 것도 금지다
{
  const html = renderToStaticMarkup(<AnswerMessage answer="본문만 있습니다." sources={[]} attachments={[]} />)
  assert.ok(!html.includes('참고 출처'))
  assert.ok(!html.includes('필요 서류'))
  assert.ok(!html.includes('신청 페이지'))
}

// 3. out_of_scope = true → 부착 영역 전부 스킵. 오류가 아니므로 오류 스타일도 아니다
{
  const html = renderToStaticMarkup(
    <AnswerMessage answer="안녕하세요!" sources={[SOURCE]} attachments={[DOC, LINK]} outOfScope />,
  )
  assert.ok(!html.includes('참고 출처'))
  assert.ok(!html.includes('필요 서류'))
  assert.ok(!html.includes('신청 페이지'))
  assert.ok(!html.includes('data-variant="error"'))
}

// 4. 민원성 + 첨부 있음 → 절차 → 필요 서류 → 신청 페이지 순서 고정
{
  const html = renderToStaticMarkup(<AnswerMessage answer="① 신청 대상 확인" attachments={[DOC, LINK]} />)
  assert.ok(html.indexOf('필요 서류') < html.indexOf('신청 페이지'), '서류가 신청 페이지보다 먼저')
  assert.ok(html.includes('서식 다운로드 페이지로 이동'))
  // 2026-08-10: 도메인·새 탭 시각 힌트 제거(버튼 옆 어수선) — 새 탭 고지는 sr-only로만 남긴다
  assert.ok(!html.includes('· 새 탭'), '도메인·새 탭 시각 힌트는 그리지 않는다')
  assert.ok(html.includes('(새 탭에서 열림)'), '새 탭 고지는 스크린리더용으로 유지')
}

// 5. 민원성 + 첨부 없음 → '필요 서류'만 사라지고 신청 페이지는 남는다
{
  const html = renderToStaticMarkup(<AnswerMessage answer="절차 안내" attachments={[LINK]} />)
  assert.ok(!html.includes('필요 서류'))
  assert.ok(html.includes('신청 페이지'))
}

// 6. 스트리밍 중에는 섹션을 그리지 않는다(나중에 걷어내면 깜빡인다)
{
  const html = renderToStaticMarkup(<AnswerMessage answer="생성 중" sources={[SOURCE]} streaming />)
  assert.ok(!html.includes('참고 출처'))
  assert.ok(html.includes('aria-live="polite"'))
  // 델타마다 문단 전체가 다시 낭독되지 않도록 스트리밍 중에는 busy로 묶는다
  assert.ok(html.includes('aria-busy="true"'))
  const done = renderToStaticMarkup(<AnswerMessage answer="생성 완료" sources={[SOURCE]} />)
  assert.ok(done.includes('aria-busy="false"'), 'done 시점에 완성 본문을 한 번 고지한다')
}

// 7. 자기보고 마커가 새어 나와도 사용자에게 보이지 않는다 (BE가 떼는 것이 계약이지만 방어)
{
  for (const raw of ['[NO_SOURCE] 안녕하세요', '[SOURCE USED]\n보호 한도는 1억원', '[source_used] 소문자 변형']) {
    const html = renderToStaticMarkup(<AnswerMessage answer={raw} />)
    assert.ok(!html.includes('SOURCE'), `마커가 남았다: ${raw}`)
  }
  // 본문 중간의 대괄호 표기는 건드리지 않는다(첫 줄 선두만 제거)
  const kept = renderToStaticMarkup(<AnswerMessage answer="근거 표기는 [SOURCE_USED] 형식입니다" />)
  assert.ok(kept.includes('[SOURCE_USED]'))
}

// 8. 오류 — retryable일 때만 [다시 시도]. 문구는 서버 user_message 그대로
{
  const base: ApiError = {
    code: 'LLM_RATE_LIMIT',
    user_message: '요청이 많아 잠시 후 다시 시도해 주세요.',
    retryable: false,
    fallback_sources: [],
    request_id: 'req_8f2c41ab',
  }
  const noRetry = renderToStaticMarkup(<ErrorMessage error={base} onRetry={() => {}} />)
  assert.ok(noRetry.includes('요청이 많아 잠시 후 다시 시도해 주세요.'))
  assert.ok(!noRetry.includes('다시 시도</button>'), 'retryable=false면 버튼을 그리지 않는다')
  assert.ok(noRetry.includes('요청 ID req_8f2c41ab'), '문의용 요청 ID를 함께 표시')
  assert.ok(noRetry.includes('data-variant="error"'), '폴백이 없으면 오류 전용 테두리')

  // user_message에도 '다시 시도'가 들어 있어, 버튼 유무는 마크업 경계까지 붙여 확인한다
  const retry = renderToStaticMarkup(<ErrorMessage error={{ ...base, retryable: true }} onRetry={() => {}} />)
  assert.ok(retry.includes('다시 시도</button>'))

  // onRetry가 없으면(재시도 2회 소진) retryable이어도 버튼을 그리지 않는다
  const spent = renderToStaticMarkup(<ErrorMessage error={{ ...base, retryable: true }} />)
  assert.ok(!spent.includes('다시 시도</button>'))
}

// 9. 부분 실패 — 폴백 출처가 있으면 오류 테두리를 쓰지 않고 출처 카드를 같이 보여준다
{
  const err: ApiError = {
    code: 'LLM_TIMEOUT',
    user_message: '답변을 만드는 데 시간이 너무 오래 걸렸습니다.',
    retryable: true,
    fallback_sources: [SOURCE],
    request_id: 'req_1',
  }
  const html = renderToStaticMarkup(<ErrorMessage error={err} onRetry={() => {}} />)
  assert.ok(!html.includes('data-variant="error"'), '폴백이 있으면 일반 회색 말풍선')
  assert.ok(html.includes('대신 관련 자료를 찾아드렸어요'))
  assert.ok(html.includes('예금자보호 한도 안내'))
}

// 10. 역할 되묻기 — 선택지 2개는 프론트 상수, 출처는 붙지 않는다
{
  const html = renderToStaticMarkup(
    <ClarificationMessage
      question="어느 입장에서 궁금하신가요?"
      options={[{ label: '잘못 보낸 사람(송금인)' }, { label: '잘못 받은 사람(수취인)' }]}
      onSelect={() => {}}
    />,
  )
  assert.ok(html.includes('어느 입장에서 궁금하신가요?'))
  assert.ok(html.includes('잘못 보낸 사람(송금인)'))
  assert.ok(html.includes('잘못 받은 사람(수취인)'))
  assert.ok(!html.includes('참고 출처'))
}

// 11. AI 고지는 말풍선 '안' 맨 아래, 피드백·시각은 말풍선 '바깥' 아래 한 줄 (CB-002 마커 3/8)
//     — 고지가 밖에 있으면 다음 말풍선의 머리말처럼 읽힌다(사용자 지적)
{
  const html = renderToStaticMarkup(
    <AnswerMessage
      answer="본문"
      at="2026-08-04T15:24:00+09:00"
      sources={[SOURCE]}
      feedback={<span>피드백행</span>}
    />,
  )
  const noticeStart = html.indexOf('<p data-slot="ai-notice"')
  assert.ok(html.indexOf('참고 출처') < noticeStart, 'AI 고지는 참고 출처 아래')

  // 고지 → (닫는 태그들) → 피드백 순 = 고지는 말풍선 안 마지막, 피드백은 말풍선 바깥.
  // 정확한 중첩 문자열로 단언하면 래퍼(진입 스태거 div 등)가 붙을 때마다 깨지므로
  // "둘 사이에 여는 태그가 몇 개든 닫는 태그가 먼저 나온다"가 아니라 순서만 고정한다.
  const noticeEnd = html.indexOf('</p>', noticeStart)
  const fbStart = html.indexOf('피드백행')
  assert.ok(noticeEnd < fbStart, 'AI 고지가 피드백보다 위 = 고지는 말풍선 안')

  // 아래 한 줄은 왼쪽 피드백 · 오른쪽 시각
  assert.ok(fbStart < html.indexOf('오후 3:24'), '피드백이 시각보다 왼쪽')
}

// 12. CTA 보조 표기 — 시각 힌트 제거(2026-08-10) 후에도 잘못된 URL이 렌더를 죽이지 않는다
{
  // 스킴이 없는 값 — 과거 new URL이 던지던 실제 케이스
  const bad: Attachment = { label: '신청 페이지', url: 'kmrs.kdic.or.kr/apply', kind: 'link' }
  const html = renderToStaticMarkup(<AnswerMessage answer="절차 안내" attachments={[bad]} />)
  assert.ok(html.includes('신청 페이지'), '잘못된 URL이어도 CTA는 그려진다')
  assert.ok(!html.includes('· 새 탭'), '도메인·새 탭 시각 힌트는 그리지 않는다')
}

// 13. 복합 질문(Type 6) — 하위 질문마다 제목 → 답변 → 그 하위의 근거를 그린다.
//     하위 간 출처 중복 제거는 금지다(같은 페이지가 두 하위에 나오면 두 번 그린다).
{
  // url까지 바꿔야 아래 '두 번 그린다' 계수가 SOURCE만 센다
  const SOURCE2: Source = {
    ...SOURCE,
    page_id: 'dp_syst',
    title: '예금자보호제도 안내',
    url: 'https://www.kdic.or.kr/protect/protection_system.do',
  }
  const subs: SubAnswer[] = [
    { title: '신청 방법은?', answer: '온라인과 방문 두 가지입니다.', sources: [SOURCE], attachments: [LINK] },
    { title: '필요한 서류는?', answer: '공동인증서와 이체확인증이 필요합니다.', sources: [SOURCE, SOURCE2], attachments: [DOC] },
  ]
  // sub_answers가 있으면 최상위 sources·attachments는 빈 배열로 온다(백엔드 확정 2026-08-05)
  const html = renderToStaticMarkup(
    <AnswerMessage answer="신청 방법은?\n온라인과 방문 두 가지입니다." subAnswers={subs} sources={[]} attachments={[]} />,
  )

  assert.ok(html.includes('신청 방법은?'), '하위 질문 제목이 보인다')
  assert.ok(html.includes('필요한 서류는?'), '두 번째 하위 제목도 보인다')
  // 하위 순서는 서버가 준 순서 그대로
  assert.ok(html.indexOf('신청 방법은?') < html.indexOf('필요한 서류는?'), '하위 순서 유지')

  // 하위별 근거가 각자 붙는다 — 섹션 헤딩이 하위 수만큼 반복된다
  assert.equal(html.split('참고 출처').length - 1, 2, '참고 출처가 하위마다 하나씩')
  assert.ok(html.includes('신청 페이지') && html.includes('필요 서류'), '하위의 링크·서류 섹션도 그린다')

  // 중복 제거 금지 — 같은 page_id가 두 하위에 나오면 두 번 그려야 한다
  assert.equal(html.split(SOURCE.url).length - 1, 2, '같은 출처가 두 하위에 있으면 두 번 그린다')

  // 본문을 하위와 같이 그리면 답변이 두 벌로 보인다 — 하위로 대체돼야 한다
  assert.equal(html.split('온라인과 방문 두 가지입니다.').length - 1, 1, '본문은 하위로 대체된다')
}

// 14. 오류 말풍선의 요청 ID — 값이 없으면 라벨째 그리지 않는다.
//     백엔드가 SSE 오류에 request_id를 안 싣는 경로가 있어 null이 그대로 찍히면 안 된다
{
  const noId: ApiError = {
    code: 'INTERNAL',
    user_message: '일시적인 오류가 발생했습니다.',
    retryable: false,
    fallback_sources: [],
    // 백엔드가 값을 안 실어 보내는 경로가 실재한다(미들웨어 이전 예외)
    request_id: undefined as unknown as string,
  }
  const html = renderToStaticMarkup(<ErrorMessage error={noId} />)
  assert.ok(!html.includes('요청 ID'), '요청 ID가 없으면 라벨도 안 그린다')
}

console.log('chat selfcheck: 통과')
