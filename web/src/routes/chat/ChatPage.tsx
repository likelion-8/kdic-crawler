/** CB-001~005 챗봇 단일 페이지.
 *
 * SPA라 화면 전환이 없다 — 웰컴(CB-001)·대화(CB-002/003)·되묻기(CB-005)·응답 상태(CB-004)를
 * 한 페이지가 상태로 표현한다(CM-DF-003 01절 "화면 전환 없이 대화가 갱신됨").
 * `/chat/:sessionId`는 24시간 이내 대화 복원 진입점이고, 대화가 시작되면 주소만 replaceState로 바꾼다.
 *
 * 말풍선·출처·피드백 렌더는 components/chat(담당 chat-render)을 가져다 쓴다. 여기서 만들지 않는다.
 * 오류 문구는 서버 user_message 그대로 — 이 파일은 오류 문구를 만들지 않는다. */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { useParams } from 'react-router'
import { useQuery } from '@tanstack/react-query'
import { ArrowDown, CircleAlert, Plus, RefreshCw, Wrench, X } from 'lucide-react'
import {
  AnswerMessage,
  ClarificationMessage,
  ErrorMessage,
  FeedbackWidget,
  TypingIndicator,
  UserMessage,
} from '../../components/chat'
import { Button, ConfirmModal, Loading } from '../../components/ui'
import { streamChat } from '../../lib/api/chat'
import { apiRequest } from '../../lib/api/client'
import type {
  ApiError,
  Attachment,
  HealthResponse,
  RestoredSession,
  Source,
  SubAnswer,
  Suggestion,
} from '../../lib/api/types'
import type { BusinessFunction } from '../../lib/codes'
import type { ClarificationOption } from '../../lib/api/types'
import { Composer } from './Composer'
import { RetryExhaustedPanel } from './RetryExhaustedPanel'
import { FALLBACK_SUGGESTIONS, WelcomeScreen } from './WelcomeScreen'
import { cn } from '@/lib/utils'
import logoKdic from '../../assets/logo-kdic.png'

/** 같은 질문의 사용자 재시도 상한 (CM-DF-004 02절 "사용자 재시도 최대 2회" · CB-004 Case 5) */
const USER_RETRY_MAX = 2

/** 복원 응답의 시각(ISO) → epoch ms. 값이 없거나 못 읽으면 undefined —
 *  그 자리에 지금 시각을 찍으면 90분 전 대화에 방금 시각이 붙어 거짓이 된다 */
function msAt(iso?: string): number | undefined {
  if (!iso) return undefined
  const ms = new Date(iso).getTime()
  return Number.isNaN(ms) ? undefined : ms
}
/** [새 대화]가 확인 모달을 띄워야 하는가 — "작성 중인 입력이나 열린 피드백 폼이 있으면 먼저
 * 확인을 받습니다"(CB-002 Desc ⑦). 잃을 게 없으면 묻지 않고 바로 시작한다.
 * 컴포넌트 밖 순수 함수로 둬야 selfcheck가 조건을 직접 잡는다. */
export function needsNewChatConfirm(draft: string, openFeedbackForms: number): boolean {
  return draft.trim() !== '' || openFeedbackForms > 0
}

/** 확인 모달이 알릴 '잃는 것' 머리말. 실제로 열려 있는 것만 말한다. */
export function newChatLoss(draft: string, openFeedbackForms: number): string {
  const lost = [
    ...(draft.trim() !== '' ? ['작성 중인 질문'] : []),
    ...(openFeedbackForms > 0 ? ['작성 중인 피드백'] : []),
  ]
  return lost.length === 0 ? '' : `${lost.join('과 ')}이 사라지고 `
}

/** 역할(입장) 초기화 무응답 시간 (CM-DF-004 02절 "30분 미활동 시 역할을 초기화") */
const ROLE_IDLE_RESET_MS = 30 * 60_000
/** 점검 해제를 감지하는 폴링 주기. 기획서에 주기 값이 없어(CB-004 D-3 15) 30초로 정했다 */
const HEALTH_POLL_MS = 30_000
/** '맨 아래 추종' 판정 여유. 기획서 미정의(CB-002 §7-17) */
const NEAR_BOTTOM_PX = 80

/** Case 6 배너 본문 폴백 — 서버가 user_message를 안 줄 때만. 문구는 목업 원문 그대로 */
const MAINTENANCE_FALLBACK =
  '답변 기능을 잠시 쉬어가고 있어요. 예금보험공사 공식 누리집(kdic.or.kr)에서 필요한 정보를 확인하실 수 있습니다.'

/** 30초 무응답 = 타임아웃. "30초가 지나도 답이 없으면 [다시 시도] 안내로 전환합니다"(CB-004 A-2).
 * 서버가 아무것도 못 보낸 상태라 user_message가 없다 — A-1 함의 1이 허용한 '최후 폴백' 문구이고,
 * 문구는 Case 3 목업 원문(`답변 생성이 지연되어 중단되었어요.` / `다시 시도해 주세요.`) 그대로다. */
const TIMEOUT_ERROR: ApiError = {
  code: 'LLM_TIMEOUT',
  user_message: '답변 생성이 지연되어 중단되었어요.\n다시 시도해 주세요.',
  retryable: true,
  fallback_sources: [],
  request_id: '',
}

/** 시스템 준비 실패 안내 — 문구·UI가 기획서 미정의(CB-001 G6)라 최소로 쓴다.
 * health 자체가 실패한 상태라 서버 문구를 받을 수 없다. */
const NOT_READY_FALLBACK = '잠시 후 [다시 시도]를 눌러 주세요. 준비가 끝나면 이어서 질문할 수 있어요.'

/** Case 6·준비 실패 공용 배너 카드 (warning 톤) */
const BANNER =
  'mx-auto mb-2 flex w-full max-w-(--chat-content-max) items-start gap-3 rounded-md border border-warning/30 bg-warning-bg px-4 py-3 text-warning'

interface AnswerItem {
  kind: 'answer'
  id: string
  /** 말풍선에 찍는 시각(epoch ms). 복원된 대화는 서버가 준 시각을 그대로 쓴다 */
  at?: number
  text: string
  requestId: string
  sources: Source[]
  attachments: Attachment[]
  /** 복합 질문이면 하위 답변이 채워지고, 이때 최상위 sources는 규약상 빈 배열이다 */
  subAnswers: SubAnswer[]
  outOfScope: boolean
  /** 스트리밍 중이면 섹션을 그리지 않고 커서만 보인다 */
  streaming: boolean
}

type ChatItem =
  | { kind: 'user'; id: string; text: string; at?: number }
  | AnswerItem
  | {
      kind: 'clarification'
      id: string
      question: string
      /** 서버가 준 역할 선택지 (B-01) — 프론트가 만들어내지 않는다 */
      options: ClarificationOption[]
      businessFunction?: BusinessFunction
      at?: number
    }
  /** question·retries = 같은 질문의 재시도 카운터(CB-004 Case 5) */
  | { kind: 'error'; id: string; error: ApiError; question: string; retries: number; at?: number }

interface PendingTurn {
  question: string
  retries: number
  userItemId: string
  answerItemId: string
}

interface RoleContext {
  /** 사용자가 고른 역할 라벨 그대로 (예: `잘못 보낸 사람(송금인)`) */
  label: string
  /** 주제 변경 판정 기준 — 후속 답변의 business_function이 달라지면 초기화 */
  businessFunction?: BusinessFunction
}

const newId = () => crypto.randomUUID()

export function ChatPage() {
  const { sessionId: routeSessionId } = useParams()

  const [items, setItems] = useState<ChatItem[]>([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<PendingTurn | null>(null)
  const [role, setRole] = useState<RoleContext | null>(null)
  const [lastActivityAt, setLastActivityAt] = useState(() => Date.now())
  const [confirmNewChat, setConfirmNewChat] = useState(false)
  /** 열려 있는 피드백 사유 폼 수. 답변마다 위젯이 따로 있어 여러 개가 동시에 열릴 수 있다 */
  const [openFeedbackForms, setOpenFeedbackForms] = useState(0)
  const [hasNewBelow, setHasNewBelow] = useState(false)

  const sessionIdRef = useRef<string | undefined>(routeSessionId)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  /** 사용자가 위로 스크롤 중이면 새 메시지를 따라가지 않는다 */
  const followRef = useRef(true)
  const restoredRef = useRef<string | null>(null)

  // --- 상태 점검 (CB-004 Case 6). 해제되면 자동 원복해야 해서 주기 폴링한다 ---
  const health = useQuery({
    queryKey: ['health'],
    queryFn: () => apiRequest<HealthResponse>('/api/health', { isPoll: true }),
    refetchInterval: HEALTH_POLL_MS,
    retry: false,
  })
  const maintenance = health.data?.maintenance === true || health.data?.status === 'maintenance'
  /** 시스템 준비 실패 → 입력 잠금 + 재시도 안내 (CB-001 §2.2 Num 0 · §2.6 상태표).
   * 판정은 health 조회 실패 또는 답변 기능 비활성. `status === 'degraded'`는 제외한다 —
   * degraded는 일부 기능(예: 피드백)만 꺼진 상태라 질문 자체는 계속 받는다. */
  const notReady = health.isError || health.data?.disabled_features.includes('chat') === true

  // --- 추천 질문 (CB-001 ⑤). 실패해도 입력창 사용에는 영향이 없다 ---
  const suggestions = useQuery({
    queryKey: ['suggestions'],
    queryFn: () => apiRequest<Suggestion[]>('/api/suggestions'),
    retry: false,
  })
  const questions = suggestions.data
    ? suggestions.data.map((s) => s.text)
    : suggestions.isError
      ? FALLBACK_SUGGESTIONS
      : []

  // --- 대화 복원 (24시간 이내). 만료·실패면 웰컴에서 새로 시작한다 ---
  const restore = useQuery({
    queryKey: ['session', routeSessionId],
    enabled: Boolean(routeSessionId),
    queryFn: () => apiRequest<RestoredSession>(`/api/sessions/${routeSessionId}`),
    retry: false,
  })

  /** 복원이 끝나면 목록을 통째로 교체하므로 그 전에 보낸 질문은 사라진다 — 복원 중에는 입력을 잠근다 */
  const restoring = Boolean(routeSessionId) && restore.isPending
  /** 질문을 받을 수 없는 상태 전부 (점검 · 준비 실패 · 복원 중) */
  const inputLocked = maintenance || notReady || restoring

  // 복원 실패(24시간 초과·없는 세션)는 웰컴에서 새로 시작한다. 만료된 session_id를 다음 질문에 붙이지 않는다
  useEffect(() => {
    if (!restore.isError) return
    sessionIdRef.current = undefined
    window.history.replaceState(null, '', '/')
  }, [restore.isError])

  useEffect(() => {
    const data = restore.data
    if (!data || restoredRef.current === data.session_id) return
    restoredRef.current = data.session_id
    sessionIdRef.current = data.session_id
    setItems(
      data.messages.map((m, i): ChatItem =>
        m.role === 'user'
          ? { kind: 'user', id: `restored-${i}`, text: m.text, at: msAt(m.at) }
          : {
              kind: 'answer',
              id: `restored-${i}`,
              text: m.text,
              at: msAt(m.at),
              requestId: m.request_id ?? '',
              sources: m.response?.sources ?? [],
              attachments: m.response?.attachments ?? [],
              // 복합 질문은 근거가 전부 하위에 있다 — 여기서 버리면 최상위가 규약상 빈 배열이라
              // 본문만 남고 출처가 하나도 없는 말풍선이 복원된다
              subAnswers: m.response?.sub_answers ?? [],
              outOfScope: m.response?.out_of_scope ?? false,
              streaming: false,
            },
      ),
    )
  }, [restore.data])

  // 새 메시지가 오면 아래로 따라간다. 위로 올려 읽는 중이면 '새 메시지' 버튼만 띄운다
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    if (followRef.current) el.scrollTop = el.scrollHeight
    else setHasNewBelow(true)
  }, [items, pending])

  // 30분 무응답이면 선택한 입장을 버린다 (CB-005 §3.5)
  useEffect(() => {
    if (!role) return
    const t = setTimeout(() => setRole(null), ROLE_IDLE_RESET_MS)
    return () => clearTimeout(t)
  }, [role, lastActivityAt])

  // 페이지를 떠날 때 열려 있는 스트림을 끊는다
  useEffect(() => () => abortRef.current?.abort(), [])

  /** 대화가 시작되면 주소만 바꾼다 — 페이지 이동이 아니다(CM-DF-003 01절) */
  const adoptSession = (id: string) => {
    if (!id || sessionIdRef.current === id) return
    sessionIdRef.current = id
    window.history.replaceState(null, '', `/chat/${id}`)
  }

  const send = (raw: string, opts: { retries?: number; echoUser?: boolean } = {}) => {
    const text = raw.trim()
    if (!text || pending || inputLocked) return

    const retries = opts.retries ?? 0
    const userItemId = newId()
    const answerItemId = newId()
    /** accepted에서 받는 요청 ID — 타임아웃 오류에도 문의용으로 실어 보낸다 (CB-004 Desc 3행) */
    let acceptedRequestId = ''

    if (opts.echoUser !== false) {
      setItems((list) => [...list, { kind: 'user', id: userItemId, text, at: Date.now() }])
    }
    setDraft('')
    setLastActivityAt(Date.now())
    setPending({ question: text, retries, userItemId, answerItemId })

    const controller = new AbortController()
    abortRef.current = controller

    void streamChat(
      { message: text, session_id: sessionIdRef.current },
      {
        onAccepted: ({ request_id, session_id }) => {
          acceptedRequestId = request_id
          adoptSession(session_id)
        },

        onDelta: (chunk) =>
          setItems((list) => {
            const idx = list.findIndex((i) => i.id === answerItemId)
            if (idx === -1) {
              return [
                ...list,
                {
                  kind: 'answer',
                  at: Date.now(),
                  id: answerItemId,
                  text: chunk,
                  requestId: '',
                  sources: [],
                  attachments: [],
                  subAnswers: [],
                  outOfScope: false,
                  streaming: true,
                },
              ]
            }
            const next = [...list]
            const cur = next[idx] as AnswerItem
            next[idx] = { ...cur, text: cur.text + chunk }
            return next
          }),

        // ponytail: sources·attachments 이벤트는 따로 받지 않는다 —
        // done 페이로드가 확정 응답 전문이라(CM-DF-003 03절) 완료 시 통째로 교체하면 된다

        // 30초 무응답 = 타임아웃. 스트림을 닫고 Case 3([다시 시도]) 안내로 전환한다(CB-004 A-2).
        // 여기서 끊지 않으면 done이 영영 안 올 때 입력창이 영구 잠금으로 남는다.
        onFallback: () => {
          controller.abort()
          setItems((list) => [
            ...list.filter((i) => i.id !== answerItemId),
            {
              kind: 'error',
              at: Date.now(),
              id: answerItemId,
              error: { ...TIMEOUT_ERROR, request_id: acceptedRequestId },
              question: text,
              retries,
            },
          ])
        },

        onDone: (res) => {
          adoptSession(res.session_id)
          setItems((list) => {
            const rest = list.filter((i) => i.id !== answerItemId)
            if (res.error) {
              return [
                ...rest,
                { kind: 'error', id: answerItemId, error: res.error, question: text, retries, at: Date.now() },
              ]
            }
            // 되묻기 — 역할을 고르기 전에는 추측 답변을 그리지 않는다(CB-005 Desc 0)
            if (res.clarification) {
              return [
                ...rest,
                {
                  kind: 'clarification',
                  at: Date.now(),
                  id: answerItemId,
                  question: res.clarification.question,
                  options: res.clarification.options ?? [],
                  businessFunction: res.business_function,
                },
              ]
            }
            return [
              ...rest,
              {
                kind: 'answer',
                // 답변을 다 받은 시각이다 — 스트리밍 첫 조각이 아니라 여기서 찍는다
                at: Date.now(),
                id: answerItemId,
                text: res.answer,
                requestId: res.request_id,
                sources: res.sources,
                attachments: res.attachments,
                subAnswers: res.sub_answers ?? [],
                outOfScope: res.out_of_scope,
                streaming: false,
              },
            ]
          })
          // 주제가 바뀌면 역할 초기화, 아직 주제를 모르면 이번 업무로 고정 (CB-005 §3.5)
          setRole((prev) => {
            if (!prev || !res.business_function) return prev
            if (!prev.businessFunction) return { ...prev, businessFunction: res.business_function }
            return prev.businessFunction === res.business_function ? prev : null
          })
          setLastActivityAt(Date.now())
        },

        onError: (error) =>
          setItems((list) => [
            ...list.filter((i) => i.id !== answerItemId),
            { kind: 'error', id: answerItemId, error, question: text, retries, at: Date.now() },
          ]),
      },
      controller.signal,
    ).finally(() => {
      abortRef.current = null
      setPending(null)
    })
  }

  /** [중단] — 생성을 멈추고 부분 출력은 버리며 입력하던 질문을 되돌려준다 (CB-004 Case 1 ※) */
  const stop = () => {
    if (!pending) return
    abortRef.current?.abort()
    setItems((list) =>
      list.filter((i) => i.id !== pending.userItemId && i.id !== pending.answerItemId),
    )
    setDraft(pending.question)
    setPending(null)
  }

  /** [다시 시도] — 같은 질문을 다시 보낸다. 사용자 말풍선은 이미 있으니 다시 그리지 않는다 */
  const retry = (item: Extract<ChatItem, { kind: 'error' }>) => {
    setItems((list) => list.filter((i) => i.id !== item.id))
    send(item.question, { retries: item.retries + 1, echoUser: false })
  }

  /** 되묻기 버튼 클릭 = 그 라벨을 일반 메시지로 전송 (CB-005 §3.7-1).
   *
   * 입장 배지는 역할 되묻기(businessFunction 있음 — 업무가 정해진 상태에서 예금자 본인/
   * 상속인 등을 고르는 턴)에만 단다. 업무 선택 되묻기는 businessFunction 이 없고(업무를
   * 몰라서 묻는 턴이므로) 1회성 질문 선택이라 배지를 남기면 "입장 · 미수령금 찾기" 같은
   * 어색한 고정이 생긴다(2026-08-20 실사용 보고). */
  const selectRole = (label: string, businessFunction?: BusinessFunction) => {
    if (businessFunction) setRole({ label, businessFunction })
    send(label)
  }

  const startNewChat = () => {
    abortRef.current?.abort()
    setConfirmNewChat(false)
    setItems([])
    setPending(null)
    setDraft('')
    setRole(null) // 새 대화는 세션과 역할을 함께 초기화 (CM-DF-004 02절)
    restoredRef.current = null
    sessionIdRef.current = undefined
    window.history.replaceState(null, '', '/')
  }

  const requestNewChat = () =>
    needsNewChatConfirm(draft, openFeedbackForms) ? setConfirmNewChat(true) : startNewChat()

  /** 참조가 고정돼야 위젯의 effect가 매 렌더 다시 돌지 않는다 — 다시 돌면 false→true가
   *  반복돼 셈이 튄다. 그래서 setState는 함수형으로 쓰고 의존성을 비운다. */
  const handleFeedbackFormOpen = useCallback(
    (open: boolean) => setOpenFeedbackForms((n) => (open ? n + 1 : n - 1)),
    [],
  )

  const handleScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX
    followRef.current = near
    if (near) setHasNewBelow(false)
  }

  const jumpToBottom = () => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
    followRef.current = true
    setHasNewBelow(false)
  }

  const isWelcome = items.length === 0 && !pending && !restoring
  const streamingStarted = pending !== null && items.some((i) => i.id === pending.answerItemId)

  return (
    // .paper — 종이 톤 + 미세 그레인만. 색면이 아니라 질감이라 대화 중에도 읽기를 방해하지 않는다
    <div className="paper flex h-full flex-col">
      {/* 대화 중에만 서는 상단 블록 — 좌: 서비스명 / 우: [새 대화].
          웰컴에는 서비스명이 화면 한가운데 크게 있으므로 이 블록을 세우지 않는다(두 번 쓰는 꼴).
          아래 헤어라인으로 대화 지면과 경계를 그어 '블록'임을 알린다 */}
      {items.length > 0 && (
        <header className="shrink-0 border-b border-border bg-background/80 backdrop-blur-sm">
          <div className="mx-auto flex min-h-14 w-full max-w-(--chat-content-max) items-center justify-between gap-3 px-4 py-2 max-md:px-3">
            {/* 기관 마크 + 서비스 워드마크 락업.
                대민 화면이라 '누가 운영하는 서비스인가'가 먼저 보여야 신뢰가 선다 — 기관 마크를
                왼쪽에 두고 헤어라인으로 끊은 뒤 서비스 이름을 붙인다.
                워드마크는 관리자 셸(`예솜24 Admin`)과 같은 규칙이다: 브랜드는 크고 굵게 포인트
                컬러, 수식어는 작고 연하게. 웰컴 h1처럼 둘을 같은 크기·굵기로 두면 로고가 아니라
                문장 한 조각으로 읽힌다(사용자 지적 — 프로토타입 같다).
                수식어를 400으로 쓰는 이유: 웹폰트가 400/500/700만 받아 300은 브라우저가
                합성하거나 400으로 떨어진다(global.css) — 없는 굵기를 선언하지 않는다 */}
            <div className="flex min-w-0 items-center gap-2.5">
              {/* 다크에서는 흰 플레이트를 깐다 — 기관 마크가 남색(#143275)이라 다크 지면(#141417)에
                  그대로 얹으면 묻힌다. 색을 반전·보정하면 기관 CI를 훼손하므로 바탕을 준다 */}
              <span className="inline-flex shrink-0 items-center rounded-[3px] dark:bg-white dark:px-1.5 dark:py-1">
                <img className="h-7 w-auto" src={logoKdic} alt="예금보험공사" width={90} height={72} />
              </span>
              <span className="h-5 w-px shrink-0 bg-border" aria-hidden="true" />
              {/* 서비스명은 기관 CI 남색으로 — 로고와 같은 색이라 마크와 워드마크가 한 덩어리로 읽힌다.
                  수식어는 오른쪽 남색 칩. 칩 높이(h-6)와 서비스명 줄높이(leading-6)를 같은 값으로
                  묶어 두 요소의 위아래 끝이 정확히 맞는다 — items-center로 눈대중하지 않는다 */}
              <p className="flex items-center gap-1.5 tracking-tight">
                <span className="text-[19px] leading-6 font-bold text-kdic">예솜24</span>
                <span className="flex h-6 items-center rounded bg-kdic px-2 text-[14px] font-bold tracking-wide text-kdic-fg">
                  AI
                  {/* 글자를 'AI'로 줄이면서 사라진 뜻은 낭독에만 남긴다 —
                      헤더가 '예솜24 AI 챗봇'으로 읽혀 무엇인지 그대로 전달된다.
                      부모의 tracking-tight를 tracking-wide로 되돌린다: 두 글자짜리 칩은
                      자간이 좁으면 한 덩어리로 뭉쳐 읽힌다 */}
                  <span className="sr-only"> 챗봇</span>
                </span>
              </p>
            </div>
            <Button size="sm" className="min-h-11 shrink-0" onClick={requestNewChat}>
              <Plus aria-hidden="true" /> 새 대화
            </Button>
          </div>
        </header>
      )}

      {maintenance ? (
        // Case 6 서비스 점검 배너 — 상시 노출. 크림 #FFF8F0은 다크 대응값이 없어 warning 토큰을 쓴다
        <div className={BANNER} role="status">
          <Wrench className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div className="min-w-0">
            <p className="font-bold">지금은 서비스 점검 중입니다</p>
            <p className="mt-1 text-[13px]">{health.data?.user_message ?? MAINTENANCE_FALLBACK}</p>
          </div>
        </div>
      ) : (
        // 점검(Case 6)은 재시도를 유도하지 않는다 — 준비 실패일 때만 재조회 버튼을 준다
        notReady && (
          <div className={BANNER} role="status">
            <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            <div className="min-w-0">
              <p className="font-bold">지금은 질문을 받을 수 없어요</p>
              <p className="mt-1 text-[13px]">{health.data?.user_message ?? NOT_READY_FALLBACK}</p>
              <div className="mt-2">
                <Button
                  size="sm"
                  className="min-h-11"
                  loading={health.isFetching}
                  onClick={() => void health.refetch()}
                >
                  <RefreshCw aria-hidden="true" /> 다시 시도
                </Button>
              </div>
            </div>
          </div>
        )
      )}

      <div className="flex-1 overflow-y-auto overscroll-contain" ref={scrollRef} onScroll={handleScroll}>
        {/* 웰컴은 세로 가운데에 놓는다. 중앙 정렬을 **이 요소**가 져야 한다 —
            자식에 min-h-full을 걸면 부모 높이가 auto라 백분율이 풀리지 않아 무력화된다(실측).
            대화 중에는 위에서부터 쌓여야 하므로 그때는 걸지 않는다 */}
        <div
          className={cn(
            'mx-auto max-w-(--chat-content-max) px-4 pt-2 pb-6 max-md:px-3',
            isWelcome && 'flex min-h-full flex-col justify-center',
          )}
        >
          {restoring ? (
            <p className="my-10 text-center">
              <Loading text="이전 대화를 불러오는 중…" />
            </p>
          ) : isWelcome ? (
            <WelcomeScreen questions={questions} onPick={(q) => send(q)} disabled={inputLocked} />
          ) : (
            // aria-live는 스트리밍 답변(AnswerMessage) 한 곳에만 둔다 — 목록에 걸면 라이브 영역이
            // 중첩돼 사용자 자신의 말풍선까지 낭독되고 답변이 두 번 읽힌다. 오류는 Bubble이 role="alert".
            <ol className="flex flex-col gap-6" aria-busy={pending !== null}>
              {items.map((item) => {
                if (item.kind === 'user') {
                  return (
                    <li className="min-w-0" key={item.id}>
                      <UserMessage text={item.text} at={item.at} />
                    </li>
                  )
                }
                if (item.kind === 'clarification') {
                  return (
                    <li className="min-w-0" key={item.id}>
                      <ClarificationMessage
                        question={item.question}
                        options={item.options}
                        at={item.at}
                        onSelect={(label) => selectRole(label, item.businessFunction)}
                      />
                    </li>
                  )
                }
                if (item.kind === 'error') {
                  // 점검·준비 실패 중에는 재시도를 유도하지 않는다 (CB-004 Case 6)
                  const canRetry =
                    item.error.retryable &&
                    item.retries < USER_RETRY_MAX &&
                    !inputLocked &&
                    !pending
                  // 렌더 결정 트리(CB-004 A-8)는 배타 분기다: 폴백 출처 있음(Case 4) > 2회 소진(Case 5) > Case 3.
                  // Case 5는 오류 말풍선을 '대체'하지 병렬로 붙지 않는다.
                  const exhausted =
                    item.retries >= USER_RETRY_MAX && item.error.fallback_sources.length === 0
                  return (
                    <li className="min-w-0" key={item.id}>
                      {exhausted ? (
                        <RetryExhaustedPanel requestId={item.error.request_id} />
                      ) : (
                        <ErrorMessage
                          error={item.error}
                          at={item.at}
                          onRetry={canRetry ? () => retry(item) : undefined}
                        />
                      )}
                    </li>
                  )
                }
                return (
                  <li className="min-w-0" key={item.id}>
                    <AnswerMessage
                      answer={item.text}
                      at={item.at}
                      sources={item.sources}
                      attachments={item.attachments}
                      subAnswers={item.subAnswers}
                      outOfScope={item.outOfScope}
                      streaming={item.streaming}
                      // 말풍선 아래 왼쪽 — 오른쪽 시각과 한 줄로 마주 본다.
                      // 밖에 따로 그리면 말풍선보다 넓게 퍼져 폭이 어긋난다
                      feedback={
                        !item.streaming && item.requestId ? (
                          <FeedbackWidget
                            requestId={item.requestId}
                            sessionId={sessionIdRef.current ?? ''}
                            onFormOpenChange={handleFeedbackFormOpen}
                          />
                        ) : undefined
                      }
                    />
                    {/* 범위 외 응답은 출처 대신 추천 질문 칩으로 다음 행동을 제시한다 (CB-004 A-3).
                        개수는 목업(`19:278`)의 2개 — 반응형 규칙의 3개+[더보기]와 어긋나 있다(A D-2 6).
                        말풍선 왼쪽 끝에 맞춰 아바타 폭만큼 들여쓴다 */}
                    {/* 칩 문구는 FAQ 원문(최장 19자)이라 좁은 화면에서 한 줄에 안 들어간다.
                        shadcn buttonVariants 기본값이 whitespace-nowrap이라 풀어 줘야 대화 영역에
                        가로 스크롤이 생기지 않는다(ClarificationMessage와 같은 처리) */}
                    {item.outOfScope && questions.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-2 pl-[calc(var(--chat-avatar)+12px)]">
                        {questions.slice(0, 2).map((q) => (
                          <Button
                            key={q}
                            size="sm"
                            className="h-auto min-h-11 px-4 py-2 text-left whitespace-normal"
                            disabled={inputLocked || pending !== null}
                            onClick={() => send(q)}
                          >
                            {q}
                          </Button>
                        ))}
                      </div>
                    )}
                  </li>
                )
              })}

              {/* 답변 생성 중 행 — 타이핑 인디케이터. [중단]은 별도 버튼 대신 입력창의
                  전송 버튼이 중단 아이콘으로 바뀌는 방식이다(2026-08-10 변경, Composer.onStop) */}
              {pending && !streamingStarted && (
                <li>
                  <TypingIndicator />
                </li>
              )}
            </ol>
          )}
        </div>
      </div>

      {/* 진입 안무의 마지막 박자 — 마스코트(0)→타이틀(1)→FAQ 카드(2)→행(3~12) 뒤에 입력창.
          인덱스는 고정값이다 — 추천 질문이 늦게 도착해 개수로 delay가 흔들리면 재생 중 안무가 튄다 */}
      <div
        className={cn(
          'relative border-t px-4 pt-3 pb-4 max-md:px-3 max-md:pt-2 max-md:pb-3',
          isWelcome && 'reveal',
        )}
        style={isWelcome ? ({ '--reveal-i': 13 } as CSSProperties) : undefined}
      >
        {/* '새 메시지' — 사용자가 위로 스크롤 중일 때만. 입력창 바로 위에 뜬다 */}
        {hasNewBelow && (
          // -top-6(24px)은 버튼 높이 44px의 절반뿐이라 아래쪽 20px이 입력창 위로 겹쳤다
          <div className="absolute -top-13 left-0 z-10 flex w-full justify-center">
            {/* 대화 위에 실제로 떠 있는 요소라 그림자를 남긴다 — 카드가 아니라 오버레이다 */}
            <Button size="sm" className="min-h-11 bg-card px-4 shadow-md" onClick={jumpToBottom}>
              <ArrowDown aria-hidden="true" /> 새 메시지
            </Button>
          </div>
        )}

        {/* 역할 칩 — 위치·형태가 기획서 미정의(CB-005 G4)라 입력창 바로 위 + 해제 버튼으로 정했다 */}
        {role && (
          <div className="mx-auto mb-2 flex min-h-11 w-fit max-w-(--chat-input-max) items-center gap-1 rounded-md border bg-card pr-0.5 pl-3.5">
            <span className="text-[13px] text-foreground">입장 · {role.label}</span>
            {/* 터치 타깃 44×44 이상 (CM-DF-004 09절) */}
            <button
              type="button"
              className="flex size-11 items-center justify-center rounded-md text-muted-foreground transition-colors duration-200 hover:bg-muted hover:text-foreground"
              onClick={() => setRole(null)}
              aria-label={`선택한 입장 ${role.label} 해제`}
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          </div>
        )}

        <Composer
          value={draft}
          onChange={setDraft}
          onSubmit={(text) => send(text)}
          welcome={isWelcome}
          disabled={pending !== null || inputLocked}
          onStop={pending !== null ? stop : undefined}
        />

        {/* 첫 진입 고지 — 입력창 바로 아래 (CB-001 Desc 0). 답변별 고지는 답변 말풍선이 담당한다 */}
        {isWelcome && (
          <p className="mx-auto mt-2 max-w-(--chat-input-max) text-xs text-muted-foreground">
            ⓘ AI가 생성한 답변입니다. 주민등록번호·계좌번호 등 개인정보는 입력하지 마세요. 중요한
            내용은 출처 원문에서 확인해 주세요.
          </p>
        )}

      </div>

      <ConfirmModal
        open={confirmNewChat}
        title="새 대화를 시작할까요?"
        // 없는 것이 사라진다고 쓰지 않는다 — 피드백 폼만 열려 있는데 '작성 중인 질문'을 말하면 거짓이다
        impact={`${newChatLoss(draft, openFeedbackForms)}지금까지의 대화와 선택한 입장(역할)이 초기화됩니다.`}
        confirmLabel="새 대화"
        onConfirm={startNewChat}
        onCancel={() => setConfirmNewChat(false)}
      />
    </div>
  )
}
