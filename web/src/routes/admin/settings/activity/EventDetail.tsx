/** AD-011 ❹ 이벤트 상세 — 기록 시점 스냅샷을 그대로 보여주는 읽기 전용 패널.
 *
 * "데이터가 있는 블록만 렌더합니다 : 기본 정보(항상) / 변경 내용(전후값 있는 변경만) /
 *  승인(승인 절차 거친 게시·반영만). 로그인·조회는 기본 정보만, 거부 건은 + 거부 사유"
 * 추가 전용 원장이므로 이 패널에는 수정·삭제 조작을 두지 않는다. */
import { Link } from 'react-router'
import type { ActivityResult, Role } from '../../../../lib/codes'
import { formatKst } from '../../../../lib/format'

/** GET /api/admin/activity/events 행. 목(mocks/data/admin.ts ActivityEvent)이 주는 모양 그대로다 */
export interface ActivityEventRow {
  id: string
  occurred_at: string
  actor: string
  actor_role: Role
  action: string
  target: string
  result: ActivityResult
  reason?: string
  request_id: string
  ip: string
}

/** GET /api/admin/activity/events/{id} — 행 + 스냅샷 */
export interface ActivityEventDetailData extends ActivityEventRow {
  /** 바뀐 항목만 담긴 전후값 스냅샷 */
  snapshot?: { before: Record<string, unknown>; after: Record<string, unknown> }
  /** 승인 절차를 거친 건에만 있다 */
  approval?: { requested_by?: string; approved_by?: string; reauthed_at?: string }
}

/** [연결 보기] 이동처는 행위 유형이 결정한다(CM-DF-002 07절).
 * 사전이 행위를 묶음으로만 적어 두어 키워드로 매칭한다. 위에서부터 처음 맞는 것 하나. */
const LINKS: { match: RegExp; to: string; label: string }[] = [
  { match: /URL 적재/, to: '/admin/knowledge/pages?new=1', label: '적재 미리보기(AD-003)' },
  // 사전 07절: 전체·선택 재수집과 작업 취소·재시도는 AD-004, 페이지 단위 '재수집 실행'만 AD-002.
  // 그래서 파이프라인 규칙이 페이지 규칙보다 먼저 와야 한다
  {
    match: /전체 재수집|선택 재수집|재색인|재적재|파이프라인|작업/,
    to: '/admin/pipeline',
    label: '파이프라인 작업(AD-004)',
  },
  { match: /페이지|재수집/, to: '/admin/knowledge/pages', label: '지식베이스 페이지 목록(AD-002)' },
  { match: /대화 로그/, to: '/admin/logs', label: '대화 로그(AD-005)' },
  { match: /RAG/, to: '/admin/settings/rag', label: 'RAG 파라미터 설정 이력(AD-007)' },
  { match: /프롬프트|가드레일/, to: '/admin/settings/prompt', label: '프롬프트 버전 이력(AD-008)' },
  { match: /사용량 제한|캐시|차단/, to: '/admin/settings/ops', label: '운영 정책(AD-009)' },
  { match: /권한|계정/, to: '/admin/settings/access', label: '전체 계정 목록(AD-010)' },
]

/** 이동처가 없는 행위 — 로그인 계열과 활동 로그 자체 조회·내보내기(사전 "연결 없음") */
const NO_LINK = /^로그인|^로그아웃|로그인 실패|임시 잠금|^로그 조회|^로그 내보내기|^활동 로그/

function linkOf(action: string) {
  if (NO_LINK.test(action)) return null
  return LINKS.find((l) => l.match.test(action)) ?? null
}

/** 접속 IP는 마스킹 표시한다(AD-011 Description 4). 서버가 이미 마스킹해 주면 그대로 통과시킨다.
 * 목업 예시 `10.**.**.24` 형식 — 첫·마지막 옥텟만 남긴다. */
function maskIp(ip: string): string {
  const parts = ip.split('.')
  if (parts.length !== 4) return ip
  return `${parts[0]}.**.**.${parts[3]}`
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    // 라벨 트랙이 고정 72px이면 '변경 내용' 블록의 스냅샷 키(list_state 같은 영문 식별자)가
    // 트랙을 넘어 값과 겹친다 — 최소 72px을 지키되 긴 라벨은 트랙이 늘어나게 둔다
    <div className="grid grid-cols-[minmax(72px,auto)_1fr] gap-2 text-xs">
      <dt className="break-all text-muted-foreground">{label}</dt>
      <dd className="break-words">{value}</dd>
    </div>
  )
}

/** 모달 헤더용 제목·부제 — 화면과 상세가 같은 문구를 쓰도록 여기서 만든다 */
export const eventDetailTitle = (e: ActivityEventDetailData) => `${e.action} · ${e.result}`
export const eventDetailMeta = (e: ActivityEventDetailData) => `${e.id} · ${formatKst(e.occurred_at)}`

export function EventDetail({ event }: { event: ActivityEventDetailData }) {
  const link = linkOf(event.action)
  const changed = event.snapshot ? Object.keys(event.snapshot.after) : []

  return (
    // 제목·식별자는 DetailModal 헤더가 그린다 — 여기서 두 번 쓰지 않는다
    <article className="flex flex-col gap-4">
      <section>
        <h4 className="mb-2 text-xs font-semibold text-foreground">기본 정보</h4>
        <dl className="flex flex-col gap-1.5">
          <Row label="실행자" value={`${event.actor} (${event.actor_role})`} />
          <Row label="접속 IP" value={maskIp(event.ip)} />
          <Row label="대상" value={event.target} />
          {/* 거부 건은 같은 값을 '거부 사유'로 읽는다 (Description 4) */}
          {event.reason && <Row label={event.result === '거부됨' ? '거부 사유' : '사유'} value={event.reason} />}
          <Row label="연결 작업" value={event.request_id} />
        </dl>
      </section>

      {changed.length > 0 && event.snapshot && (
        // 스냅샷 전후값은 코드 블록이라 회색 인셋이 정당한 자리다
        <section className="rounded-md bg-muted p-3">
          <h4 className="mb-2 text-xs font-semibold text-foreground">변경 내용</h4>
          {/* 기록 시점 스냅샷 전후값 — 코드 블록 표기(font-mono) */}
          <dl className="flex flex-col gap-1.5 font-mono text-xs">
            {changed.map((key) => (
              <Row
                key={key}
                label={key}
                value={`${String(event.snapshot?.before[key] ?? '—')} → ${String(event.snapshot?.after[key] ?? '—')}`}
              />
            ))}
          </dl>
        </section>
      )}

      {event.approval && (
        <section className="border-t pt-3">
          <h4 className="mb-2 text-xs font-semibold text-foreground">승인</h4>
          <dl className="flex flex-col gap-1.5">
            {event.approval.requested_by && <Row label="요청" value={event.approval.requested_by} />}
            {event.approval.approved_by && <Row label="승인" value={event.approval.approved_by} />}
            {event.approval.reauthed_at && <Row label="재인증" value={formatKst(event.approval.reauthed_at)} />}
          </dl>
        </section>
      )}

      {link && (
        <Link
          className="inline-flex w-fit items-center gap-1 rounded-sm text-xs font-medium text-primary outline-none transition-colors duration-200 hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
          to={link.to}
        >
          {link.label}에서 보기 →
        </Link>
      )}
    </article>
  )
}
