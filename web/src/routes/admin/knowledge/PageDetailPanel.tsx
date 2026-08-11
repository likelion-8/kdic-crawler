/** AD-002 상세 패널 (B-6) — 선택한 행의 기본 / 수집·점검 / 청크 목록 / 행 동작.
 *
 * "선택한 행은 목록에서 보라색으로 강조되고, 패널 제목은 '제목 + (페이지 ID)',
 *  부제는 상태 · 마지막 수집일입니다" (B-6 Description 1)
 * "[재수집]은 중립, [삭제]는 위험 스타일입니다 … 결과 0건이면 상세도 빈 상태입니다" (B-6 Description 6) */
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { Button, EmptyState, InfoHint, Loading } from '../../../components/ui'
import { Separator } from '../../../components/shadcn/separator'
import { apiRequest, isApiRequestError } from '../../../lib/api/client'
import type { Page } from '../../../lib/api/types'
import { INDEX_STATUS_BADGE } from '../../../lib/codes'
import { formatDate, formatTarget } from '../../../lib/format'
import type { KbChunk, KbPage } from './types'

/** 청크는 한 페이지 최대 165개(uc_bkrp_mng 실측)라 한 번에 받고 패널 안에서 스크롤한다 */
const CHUNK_FETCH_SIZE = 300
/** 목업이 카드 3장을 보여주고 나머지는 '… 외 N개 · 스크롤'로 알린다 (B-6 (5)) */
const CHUNK_PREVIEW_COUNT = 3

/** 패널 겉면 — 떠 있는 카드가 아니라 헤어라인으로 가둔 지면 */
const PANEL = 'flex flex-col gap-3 rounded-md border bg-card p-5'
/** 섹션 제목 — 12px 유지하되 색은 잉크로. 보라는 링크·Primary·포커스·현재 위치에만 쓴다 */
const SECTION_TITLE = 'text-xs font-semibold tracking-[-0.01em] text-foreground'
/** dt/dd에 클래스를 달지 않는다(selfcheck가 `<dt>담당</dt><dd>dy</dd>` 원문을 단언) — 부모 선택자로 칠한다 */
const ROW =
  'grid min-h-[18px] grid-cols-[72px_1fr] gap-2 [&>dt]:text-muted-foreground [&>dd]:text-foreground/80 [&>dd]:[overflow-wrap:anywhere]'
const LINK = 'text-primary hover:underline'

/** 모달 안에서만 그려지므로 page는 항상 있다 — 열려 있지 않으면 렌더 자체를 하지 않는다 */
export interface PageDetailPanelProps {
  page: KbPage
}

/** 모달 푸터의 행 동작에 필요한 것들 */
export interface PageDetailActionProps {
  page: KbPage
  /** 재수집은 파이프라인 작업이라 OPERATOR 이상 */
  canRecrawl: boolean
  /** 삭제는 지식베이스 변경이라 EDITOR 이상 */
  canDelete: boolean
  /** 재수집은 확인 모달 없이 바로 실행돼서(B-7 중립 버튼) 진행 표시가 버튼에 붙는다 */
  recrawlPending?: boolean
  onRecrawl: (page: KbPage) => void
  onDelete: (page: KbPage) => void
  onCancelDelete: (page: KbPage) => void
}

export function PageDetailPanel({ page }: PageDetailPanelProps) {
  const chunks = useQuery({
    queryKey: ['kb-chunks', page.page_id],
    queryFn: () =>
      apiRequest<Page<KbChunk>>(
        `/api/admin/knowledge/chunks?page_id=${encodeURIComponent(page.page_id)}&size=${CHUNK_FETCH_SIZE}`,
      ),
  })

  const items = chunks.data?.items ?? []
  const total = chunks.data?.total ?? page.chunk_count
  const rest = total - CHUNK_PREVIEW_COUNT

  return (
    // 제목·상태 부제는 DetailModal 헤더가, 행 동작은 모달 푸터가 그린다
    <div className={PANEL} aria-label="페이지 상세">
      <section>
        <h3 className={`${SECTION_TITLE} mb-2`}>기본</h3>
        <dl className="flex flex-col gap-1.5 text-xs">
          <div className={ROW}>
            <dt>출처</dt>
            <dd>
              {/* URL은 공백이 없어 기본 규칙으로는 줄바꿈되지 않는다 — 패널 밖으로 삐져나가던
                  문제(사용자 지적)를 wrap-anywhere로 막는다. truncate는 쓰지 않는다:
                  주소를 눈으로 확인해야 하는 화면이라 잘라 버리면 용도가 사라진다 */}
              <a className={`${LINK} [overflow-wrap:anywhere]`} href={page.source_url} target="_blank" rel="noreferrer">
                {page.source_url}
                <span aria-hidden="true"> ↗</span>
                <span className="sr-only">새 창에서 열림</span>
              </a>
            </dd>
          </div>
          <div className={ROW}>
            <dt>분류</dt>
            <dd>{page.sub_category}</dd>
          </div>
          <div className={ROW}>
            <dt>구분</dt>
            {/* AD-002 B-9 '구분' 값 2종 — required=false는 '분석필요' */}
            <dd>{page.required ? '필수' : '분석필요'}</dd>
          </div>
          <div className={ROW}>
            <dt>요약</dt>
            {/* 요약은 2줄까지만 (B-6 (2) '2줄 랩') */}
            <dd className="line-clamp-2">{page.summary}</dd>
          </div>
          {page.form_links.length > 0 && (
            <div className={ROW}>
              <dt>서식 링크</dt>
              <dd>
                <ul className="flex flex-col gap-0.5">
                  {page.form_links.map((link) => (
                    <li key={`${link.label}${link.url}`}>
                      <a className={LINK} href={link.url} target="_blank" rel="noreferrer">
                        {link.label}
                        <span aria-hidden="true"> ↗</span>
                        <span className="sr-only">새 창에서 열림</span>
                      </a>
                    </li>
                  ))}
                </ul>
              </dd>
            </div>
          )}
          <div className={ROW}>
            <dt>추출 자산</dt>
            <dd>
              이동 링크 {page.asset_counts.links} · 이미지 {page.asset_counts.images} · 영상{' '}
              {page.asset_counts.videos}
            </dd>
          </div>
          <div className={ROW}>
            <dt>담당</dt>
            <dd>{page.owner}</dd>
          </div>
          <div className={ROW}>
            <dt>수집 근거</dt>
            <dd>{page.note}</dd>
          </div>
        </dl>
      </section>

      <Separator />

      {/* B-6 (3). '수집 허용 · 링크 점검 · 최초 적재'는 Description이 스스로 "현 스키마에 없는
          P3 확장 필드"라고 밝힌 값이라 응답에 없다 → 받을 수 있는 두 줄만 그린다(report backend_notes) */}
      <section>
        <h3 className={`${SECTION_TITLE} mb-2`}>수집 · 점검</h3>
        <dl className="flex flex-col gap-1.5 text-xs">
          <div className={ROW}>
            <dt>적재·수집</dt>
            <dd>수집 {formatDate(page.collected_at)}</dd>
          </div>
          <div className={ROW}>
            <dt>변경 감지</dt>
            <dd>{page.list_state === '변경 감지' ? '있음' : '없음'}</dd>
          </div>
        </dl>
      </section>

      {/* 활동 로그(AD-011)를 이 페이지 대상 필터로 연다 (B-6 Description 4) */}
      <Link
        className={`${LINK} text-xs font-medium`}
        to={`/admin/settings/activity?q=${encodeURIComponent(page.page_id)}`}
      >
        페이지 이력 보기 (AD-011) →
      </Link>

      <Separator />

      <section className="flex min-h-0 flex-col gap-2">
        <h3 className={`${SECTION_TITLE} inline-flex items-center gap-0.5`}>
          청크 목록 ({total})
          <InfoHint label="청크 설명" size="sm">
            청크는 검색에 쓰이는 단위입니다. 질문과 맞춰 보는 대상이 페이지 전체가 아니라 이 조각들입니다.
          </InfoHint>
        </h3>
        {/* 분할 방식은 목록 위에 1회만 표기한다 (B-6 (5)) */}
        <p className="text-xs text-muted-foreground">분할 방식 : {page.split_rule}</p>
        {/* 목록 뷰포트는 카드 3장 높이라 잔여 수 = 전체 - 3이 그대로 '접힌 개수'다 */}
        {rest > 0 && <p className="text-xs text-muted-foreground">… 외 {rest}개 · 스크롤로 전체 확인</p>}

        {chunks.isPending && <Loading text="청크를 불러오는 중…" />}
        {/* 실패는 토스트가 아니라 화면 안에 남긴다(07.4절). 문구는 서버 user_message 그대로 */}
        {chunks.isError && isApiRequestError(chunks.error) && (
          <p className="text-xs text-danger-fg" role="alert">
            {chunks.error.error.user_message}
          </p>
        )}
        {chunks.isSuccess && items.length === 0 && <EmptyState title="이 페이지에는 청크가 없습니다" />}

        {/* 카드 1장 높이 76px 고정 — '보이는 3장 / 접힌 N개'가 화면과 문구에서 어긋나지 않게
            뷰포트 = 카드 3장 + 사이 간격 2개(248px). CHUNK_PREVIEW_COUNT와 같은 3장 */}
        <ul className="flex max-h-[248px] flex-col gap-2.5 overflow-y-auto">
          {items.map((chunk) => (
            <li className="h-[76px] flex-none overflow-hidden rounded bg-muted/50 px-3 py-2" key={chunk.chunk_id}>
              <p className="truncate text-xs font-bold text-foreground">
                #{chunk.seq} · {chunk.title} ({chunk.chars}자)
              </p>
              <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{chunk.preview}</p>
            </li>
          ))}
        </ul>
      </section>

    </div>
  )
}

/** 모달 헤더용 제목·부제 */
export const pageDetailTitle = (p: KbPage) => formatTarget(p.page_title, p.page_id)
/** 부제 원문은 'faq_msdr_apply · 상태 최신 · 마지막 수집 07-13'. 페이지 ID는 제목에서 이미
 *  쓰므로 빼고, 목록 3상태와 index_status 배지 문구를 함께 적는다(색 단독 의존 금지) */
export const pageDetailMeta = (p: KbPage) =>
  `상태 ${p.list_state} · 인덱스 ${INDEX_STATUS_BADGE[p.index_status]} · 마지막 수집 ${formatDate(p.collected_at)}`

/** 모달 푸터의 행 동작 — 권한이 없으면 숨긴다.
 *  서버가 최종 판정이라 403은 목록 화면에서 따로 처리한다 */
export function PageDetailActions({
  page, canRecrawl, canDelete, recrawlPending = false, onRecrawl, onDelete, onCancelDelete,
}: PageDetailActionProps) {
  const deletePending = page.pending_change_action === 'DELETE' && page.pending_change_request_id
  return (
    <>
      {canRecrawl && (
        <Button loading={recrawlPending} onClick={() => onRecrawl(page)}>
          재수집
        </Button>
      )}
      {canDelete &&
        (deletePending ? (
          <Button onClick={() => onCancelDelete(page)}>삭제 신청 취소</Button>
        ) : (
          <Button onClick={() => onDelete(page)}>삭제</Button>
        ))}
    </>
  )
}
