/** 대시보드 차트 자체 점검 — 눈금·비중·호버가 조용히 어긋나는 것을 막는다.
 *
 * 차트는 틀려도 "그럴듯하게" 보인다. 막대 높이가 5% 어긋나거나 축이 최댓값에 붙어도
 * 화면만 봐서는 모른다. 여기서 지키는 것은 세 가지다.
 *  1. 축 눈금이 실측 최댓값이 아니라 올림한 값이다(막대가 늘 천장에 닿지 않는다)
 *  2. 비중 막대는 100% 기준이다 — 최댓값 기준으로 늘이면 31%와 27%가 같은 길이가 된다
 *  3. 0건·단일 점처럼 나눗셈이 깨지는 입력에서 NaN 스타일이 나오지 않는다
 *
 * 실행: `pnpm check` (scripts/selfcheck.mjs가 이 파일을 SSR 로더로 돌린다) */
/// <reference types="node" />
import assert from 'node:assert/strict'
import { renderToStaticMarkup } from 'react-dom/server'
import { CostLine, RatioBars, StageBars, TokenStack, TrendBars } from './Charts'

/** 렌더 결과에 NaN/Infinity가 섞인 style이 없는지 — 0으로 나눈 흔적을 잡는다 */
function assertNoBadStyle(html: string, where: string) {
  assert.ok(!/NaN|Infinity/.test(html), `${where}: 계산이 깨진 style이 있다`)
}

// 1. 축 눈금은 올림한 값 — 최댓값 162면 천장은 200이고 막대는 81%에서 멈춘다
{
  const html = renderToStaticMarkup(
    <TrendBars
      points={[
        { date: '2026-07-27', count: 81 },
        { date: '2026-07-28', count: 162 },
      ]}
    />,
  )
  assert.ok(html.includes('>200<'), '눈금 최댓값을 1·1.5·2·3·5 배수로 올린다')
  assert.ok(html.includes('>100<'), '가운데 눈금은 절반')
  assert.ok(html.includes('height:81%'), '막대는 올림한 천장 기준으로 그린다')
  assert.ok(!html.includes('height:100%;'), '가장 큰 막대가 천장에 닿지 않는다')
  // 수치는 그림 바깥 sr-only 목록이 읽는다(role="img" 안쪽은 접근성 트리에서 지워진다)
  assert.ok(html.includes('07-28 162건'))
  assertNoBadStyle(html, 'TrendBars')
}

// 2. 0건 — 축도 막대도 그리지 않고 안내 문구만 남긴다
{
  const html = renderToStaticMarkup(<TrendBars points={[]} />)
  assert.ok(html.includes('이 기간에 기록된 질문이 없습니다'))
  assert.ok(!html.includes('role="img"'), '데이터가 없으면 그림 자체를 그리지 않는다')
}

// 3. 비중 막대는 100% 기준 — 31%는 31% 길이여야 한다(최댓값 기준이면 100%가 된다)
{
  const html = renderToStaticMarkup(
    <RatioBars
      items={[
        { label: '착오송금', ratio: 31 },
        { label: '예금자보호', ratio: 27 },
      ]}
    />,
  )
  assert.ok(html.includes('width:31%'), '최댓값이 아니라 전체(100%) 기준')
  assert.ok(html.includes('width:27%'))
}

// 4. 단계 비중은 서버가 준 총 응답시간 기준 — 단계 합으로 나누면 미계측 구간이 사라진다
{
  const html = renderToStaticMarkup(
    <StageBars stages={[{ name: '답변 생성', avg_ms: 2400 }]} total={5195} sampleCount={17} />,
  )
  assert.ok(html.includes('46%'), '2400/5195 = 46% (단계 합 기준이면 100%가 된다)')
  assert.ok(html.includes('5,195ms'), '평균 총 응답시간을 따로 적는다')
  assert.ok(html.includes('17건'), '몇 건짜리 평균인지 총계 줄에 함께 적는다')
}

// 5. 무트래픽 날(입력·출력 0) — flexBasis가 NaN%가 되지 않는다
{
  const html = renderToStaticMarkup(
    <TokenStack
      points={[
        { date: '2026-07-27', input: 0, output: 0 },
        { date: '2026-07-28', input: 900_000, output: 300_000 },
      ]}
    />,
  )
  assertNoBadStyle(html, 'TokenStack')
  // 합계 1.2M → 천장 1.5M, 절반 750k. 자릿수가 섞이지 않게 M/k로 줄인다
  assert.ok(html.includes('1.5M'), '눈금은 짧은 수로 줄인다')
  assert.ok(html.includes('750k'))
}

// 6. 점이 하나뿐인 선 — (i / (n-1))이 0으로 나뉘지 않는다
{
  const html = renderToStaticMarkup(<CostLine points={[{ date: '2026-07-27', usd: 0.0098 }]} caption="1일" />)
  assertNoBadStyle(html, 'CostLine')
  assert.ok(html.includes('50,'), '점이 하나면 가운데에 놓는다')
  // 선은 0 기준이다 — 최저값을 바닥으로 삼으면 잔변동이 절벽처럼 보인다
  assert.ok(html.includes('50,100'), '면적은 선의 양 끝에서 바닥(0)으로 내린다')
}

// 7. 점의 x는 막대와 같은 '열의 가운데' — 양 끝을 0·100에 붙이면 x축 라벨과 반 칸 어긋난다
{
  const html = renderToStaticMarkup(
    <CostLine
      points={[
        { date: '2026-07-27', usd: 0.008 },
        { date: '2026-07-28', usd: 0.01 },
      ]}
      caption="2일"
    />,
  )
  assert.ok(html.includes('points="25,'), '2점이면 25%·75% (0%·100%가 아니다)')
  assert.ok(html.includes('75,'), '마지막 점도 열 가운데')
}

console.log('dashboard charts selfcheck: 통과')
