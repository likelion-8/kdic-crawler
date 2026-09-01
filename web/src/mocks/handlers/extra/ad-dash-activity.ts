/** AD-001 대시보드 · AD-011 활동 로그 보조 목 — 기존 handlers/admin.ts에 없는 엔드포인트만 채운다.
 *
 * 기획서(CM-DF-003 04절)에 대시보드 API가 하나도 없고(09 issue D절), 활동 로그도
 * 현황 집계·필터 선택지 API가 없다(08 issue 14). 아래 4개는 프론트가 제안하는 계약이다.
 *
 * 표시 문자열(`*_text`)을 서버가 내려주는 이유: 임계치·단위·통화 표기를 프론트가 지어내면
 * 기획서에 없는 문구가 화면에 생긴다. 화면은 서버가 준 문자열을 그대로 렌더한다. */
import { HttpResponse, http } from 'msw'
import { MOCK_ACTIVITY_EVENTS } from '../../data/admin'
import { MOCK_CHUNKS } from '../../data/chunks'
import { MOCK_PAGES } from '../../data/pages'

/** 기간 선택 3종 (AD-001 A-3 `기간 : 7일 | 30일 | 90일`) */
const RANGES = [7, 30, 90]
const rangeOf = (url: URL) => {
  const n = Number(url.searchParams.get('range') ?? 7)
  return RANGES.includes(n) ? n : 7
}

/** 날짜 시드 난수 — 새로고침해도 같은 그래프가 나와야 눈으로 회귀를 볼 수 있다 */
function seeded(i: number, base: number, spread: number) {
  return Math.round(base + Math.sin(i * 2.3) * spread)
}

const dayIso = (daysAgo: number) => {
  const d = new Date('2026-08-03T00:00:00+09:00')
  d.setDate(d.getDate() - daysAgo)
  return d.toISOString().slice(0, 10)
}

const seriesDates = (range: number) => Array.from({ length: range }, (_, i) => dayIso(range - 1 - i))

export const adDashActivityHandlers = [
  // ---- AD-001 대시보드 ----

  /** 상태 칩 + KPI 4종 + 상시 지표 5종(CM-DF-004 10절) + 분포 + 단계별 응답시간.
   * 파라미터가 없는 블록은 한 번에 준다 — 화면 진입 시 왕복을 줄인다. */
  http.get('/api/admin/dashboard/summary', () =>
    HttpResponse.json({
      // 할 일 — 대시보드를 시작점으로 만드는 값. 0건 항목도 지우지 않는 것이 계약이다
      // ('없는 것'과 '못 센 것'의 구분). 서버 정본은 admin_dashboard.dashboard_summary.
      todos: [
        { key: 'FEEDBACK_DOWN', label: '미처리 나쁨 평가', count: 3,
          target: { screen: 'logs', filter: { feedback: 'down', period: '30d', triage: 'OPEN' } } },
        { key: 'PIPELINE_OPEN', label: '대기·진행·실패한 작업', count: 0,
          target: { screen: 'pipeline', filter: {} } },
        { key: 'GATE_FAILED', label: '최근 평가 게이트 미통과', count: 1,
          target: { screen: 'evaluations', filter: {} } },
      ],
      generated_at: new Date().toISOString(),
      // level=ERROR면 화면이 경고형 칩으로 교체한다. cause가 [실패 건 보기 →]의 목적지를 정한다
      service: { level: 'OK', error_count: 0, cause: null },
      kpi: {
        pages: MOCK_PAGES.length,
        chunks: MOCK_CHUNKS.length,
        questions_today: 132,
        avg_latency_ms: 5_400,
        pipeline: { status: '정상', last_run_at: '2026-07-29T03:00:00+09:00' },
      },
      // 상시 확인 지표 5종(CM-DF-004 10절)은 응답에서 뺐다 — 임계치가 정해지지 않았고
      // '요청 제한 초과'·'링크 점검 실패'는 백엔드에 원천이 없다(2026-08-04 팀 결정, P-11).
      // 임계치가 확정되면 `indicators: [{key,label,value_text,threshold_text,exceeded}]`로 되살린다.
      distribution: {
        intent: { informational: 68, civil_petition: 32 },
        // 라벨은 서버가 documents.business_function 을 그대로 보낸다 = codes.ts
        // BUSINESS_FUNCTIONS 값. 줄여 쓰면 목만 짧은 이름이라 화면 폭이 실제와 달라진다
        business: [
          { label: '예금자보호제도', ratio: 38 },
          { label: '착오송금 반환 신청', ratio: 31 },
          { label: '고객 미수령금 신청', ratio: 17 },
          { label: '채무조정 안내', ratio: 14 },
        ],
      },
    }),
  ),

  /** 단계별 평균 응답시간 — 기간 선택 즉시 갱신.
   * summary 에서 떼어낸 이유는 기간 때문이다(summary 는 오늘 고정).
   * 웹 요청이 도는 순서 (CM-DF-003 05절 · AD-001 A-5). 순서를 바꾸지 않는다.
   * 길이는 고정이 아니다 — 서버는 실제로 잰 단계만 싣는다(admin_dashboard.build_stage_latency).
   * 값은 2026-09-01 실측 평균이며, 모수는 기간에 비례해 늘어난다. */
  http.get('/api/admin/dashboard/latency', ({ request }) => {
    const range = rangeOf(new URL(request.url))
    return HttpResponse.json({
      range,
      sample_count: range * 73,
      avg_total_ms: 11_480,
      stages: [
        { name: '질문 정리', avg_ms: 2_048 },
        { name: '게이트', avg_ms: 35 },
        { name: '캐시 조회', avg_ms: 40 },
        { name: '질의 계획', avg_ms: 2_268 },
        { name: '검색', avg_ms: 920 },
        { name: '답변 생성', avg_ms: 3_250 },
        { name: '출처 판정', avg_ms: 2_486 },
      ],
    })
  }),

  /** 일별 질문 수 추이 — 기간 선택 즉시 갱신 */
  http.get('/api/admin/dashboard/trend', ({ request }) => {
    const range = rangeOf(new URL(request.url))
    return HttpResponse.json({
      range,
      points: seriesDates(range).map((date, i) => ({ date, count: seeded(i, 120, 45) })),
    })
  }),

  /** 리소스·사용량 — 운영 지표 / 비용 분석 두 뷰가 같은 응답을 나눠 쓴다 */
  http.get('/api/admin/dashboard/resources', ({ request }) => {
    const range = rangeOf(new URL(request.url))
    const dates = seriesDates(range)
    return HttpResponse.json({
      range,
      tokens: dates.map((date, i) => ({ date, input: seeded(i, 900_000, 250_000), output: seeded(i, 380_000, 90_000) })),
      // 통화는 USD 다 — 원천(Langfuse)이 USD 로 주고 환율은 아무도 정하지 않았다.
      cost: dates.map((date, i) => ({ date, usd: seeded(i, 102, 26) / 10_000 })),
      cost_caption: `최근 ${range}일 · 일 평균 $0.0102`,
      today: {
        tokens_text: '입력 1.2M · 출력 0.4M',
        cost_text: '$0.0124',
        // 동시 요청·GPU 는 백엔드에 원천이 없다(서버도 N/A 를 준다)
        concurrency_text: 'N/A',
        gpu_text: 'N/A',
      },
      cost_breakdown: [
        // 단계 순서는 토큰 많은 순이다(금액 순이 아니다 — 요금표에 없는 모델이 섞일 수 있다).
        // share: null 이면 그 모델이 요금표(MODEL_PRICE_USD_PER_1M)에 없어 금액을 못 매긴
        // 경우다. amount_text 가 토큰 수 + 그 사실을 적는다.
        { label: '답변 생성 (HyperCLOVA X)', amount_text: '$0.0344', share: 62 },
        // 2026-08-29 추가 — 재생성 HCX 가 집계에 들어오면서 별도 항목이 된다(발동률 실측 30%).
        { label: '답변 재생성 (HyperCLOVA X)', amount_text: '$0.0077', share: 14 },
        { label: '출처 판정', amount_text: '$0.0051', share: 9 },
        { label: '질문 정리·되묻기 판정', amount_text: '$0.0046', share: 8 },
        { label: '질문 분해·의도 판단', amount_text: '$0.0027', share: 7 },
      ],
    })
  }),

  // ---- AD-011 활동 로그 ----

  /** 현황 3값 + 필터 선택지. 행위·실행자 목록은 기록된 값에서 뽑는다(08 issue 14) */
  http.get('/api/admin/activity/overview', () => {
    const today = '2026-08-03'
    return HttpResponse.json({
      today_count: MOCK_ACTIVITY_EVENTS.filter((e) => e.occurred_at.startsWith(today)).length,
      last_recorded_at: MOCK_ACTIVITY_EVENTS[0]?.occurred_at ?? null,
      purge_due_this_week: 340,
      actions: [...new Set(MOCK_ACTIVITY_EVENTS.map((e) => e.action))],
      actors: [...new Set(MOCK_ACTIVITY_EVENTS.map((e) => e.actor))],
    })
  }),
]
