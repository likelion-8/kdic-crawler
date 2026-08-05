/** AD-006 §2.5 — [+ 문항 추가] 인라인 입력 행. 기존 행 클릭 시에도 같은 편집기가 열린다(§2.5 각주).
 *
 * 검증은 저장 시 서버가 한다(기대 출처 존재 · 중복 질문 · 개인정보). 걸린 필드만 붉게 칠하고
 * 통과 전에는 [저장]을 비활성으로 둔다 — 문구는 서버 message를 그대로 쓴다. */
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Button, InfoHint, Select, TextField } from '../../../components/ui'
import { Input } from '../../../components/shadcn/input'
import { BUSINESS_FUNCTIONS, INTENT_LABEL, QUESTION_TYPE_LABEL } from '../../../lib/codes'
import type { BusinessFunction, Intent, QuestionType } from '../../../lib/codes'
import { evalKeys, searchCorpus, validateItem } from './api'
import type { EvalFieldError, EvalItem, EvalItemField, EvalItemInput } from './api'

const BUSINESS_OPTIONS = BUSINESS_FUNCTIONS.map((b) => ({ value: b, label: b }))
/** 평가셋 문항 유형은 4종뿐이다 — §2.5 입력 필드 표 「사실 확인 / FAQ / 표 조회 / 링크 안내」.
 * '서식 받기'·'범위 외'는 답변 유형 코드값이지 평가셋 문항 유형이 아니다(검증 D100) */
const ITEM_TYPES: QuestionType[] = ['fact', 'faq', 'table_lookup', 'link_guide']
const TYPE_OPTIONS = ITEM_TYPES.map((value) => ({ value, label: QUESTION_TYPE_LABEL[value] }))
const INTENT_OPTIONS = Object.entries(INTENT_LABEL).map(([value, label]) => ({ value, label }))

/** 코퍼스 검색은 2자 이상에서만 — 목록 전체를 훑는 호출을 막는다 */
const SEARCH_MIN = 2

export interface ItemEditorProps {
  /** 기존 행 편집이면 원본 문항. 없으면 신규 추가 */
  item?: EvalItem
  onSave: (input: EvalItemInput, saved: EvalItem) => void
  onCancel: () => void
}

export function ItemEditor({ item, onSave, onCancel }: ItemEditorProps) {
  const [business, setBusiness] = useState<BusinessFunction>(item?.business_function ?? BUSINESS_FUNCTIONS[0])
  const [type, setType] = useState<QuestionType>(item?.question_type ?? 'fact')
  const [intent, setIntent] = useState<Intent>(item?.intent ?? 'informational')
  const [question, setQuestion] = useState(item?.question ?? '')
  const [sourceId, setSourceId] = useState(item?.expected_source.doc_id ?? '')
  const [itemId, setItemId] = useState(item?.item_id ?? '')
  /** 사용자가 문항 ID를 직접 고치면 자동 생성이 멈춘다("자동 생성 · 수정 가능") */
  const [idTouched, setIdTouched] = useState(Boolean(item))
  const [errors, setErrors] = useState<EvalFieldError[]>([])

  const corpus = useQuery({
    queryKey: evalKeys.corpus(sourceId),
    queryFn: () => searchCorpus(sourceId),
    enabled: sourceId.trim().length >= SEARCH_MIN,
  })

  const save = useMutation({
    // 기존 행 편집이면 중복 질문 검사에서 자기 자신을 뺀다
    mutationFn: (input: EvalItemInput) => validateItem(input, item?.item_id),
    onSuccess: (res, input) => {
      if (res.ok && res.item) onSave(input, res.item)
      else setErrors(res.errors)
    },
  })

  const errorOf = (field: EvalItemField) => errors.find((e) => e.field === field)?.message

  /** 값이 바뀌면 이전 검증 결과를 버린다 — 고친 필드가 계속 붉게 남지 않도록 */
  function edit(run: () => void) {
    setErrors([])
    save.reset()
    run()
  }

  const generatedId = sourceId ? `${sourceId}_pl1` : ''
  const effectiveId = idTouched ? itemId : generatedId

  const input: EvalItemInput = {
    item_id: effectiveId,
    question,
    business_function: business,
    question_type: type,
    intent,
    expected_source_id: sourceId,
  }

  const blocked = errors.length > 0
  const listId = `corpus-${item?.item_id ?? 'new'}`
  const groupId = `${listId}-group`

  return (
    // §2.5는 보라 테두리 + 보라기 배경이지만, 보라는 Primary·링크·포커스·현재 위치에만 쓴다.
    // 편집 중이라는 구분은 색면 대신 인셋 회색 + 헤어라인이 진다
    <div
      className="mb-3 rounded-md border bg-muted/60 p-4"
      role="group"
      aria-labelledby={groupId}
    >
      <p className="mb-2 inline-flex items-center gap-0.5 text-[13px] font-semibold" id={groupId}>
        {item ? '문항 편집' : '문항 추가'}
        {/* 저장 후 무슨 일이 벌어지는지는 한 번 알면 되는 규칙이다. 버튼 줄 아래 3줄로 두면
            편집기가 그만큼 길어지고, 이 상자가 표 위에 끼어들어 목록이 화면 밖으로 밀린다 */}
        <InfoHint label="저장 후 처리 설명" size="sm">
          [저장]하면 행 검증을 통과한 문항이 목록 맨 위에 &lsquo;추가됨 (반영 전)&rsquo; 상태로
          들어갑니다. 이 시점에는 버전이 오르지도, 재측정이 돌지도 않습니다. 이어서 다음 문항을 계속
          추가할 수 있습니다.
        </InfoHint>
      </p>
      {/* 1줄: 업무 · 유형 · 성격 · 문항 ID (§2.5 목업 배치) */}
      <div className="mb-2 flex flex-wrap items-start gap-x-4 gap-y-2">
        <Select label="업무" value={business} options={BUSINESS_OPTIONS}
          onChange={(v) => edit(() => setBusiness(v as BusinessFunction))} />
        <Select label="유형" value={type} options={TYPE_OPTIONS}
          onChange={(v) => edit(() => setType(v as QuestionType))} />
        <Select label="성격" value={intent} options={INTENT_OPTIONS}
          onChange={(v) => edit(() => setIntent(v as Intent))} />
        <div className="flex items-baseline gap-1.5">
          {/* 기존 행 편집에서는 ID를 잠근다 — 편집 묶음이 ID로 대상을 찾으므로 바뀌면 짝이 어긋난다 */}
          <TextField label="문항 ID" value={effectiveId} error={errorOf('item_id')}
            placeholder="예: kmrs_fee_pl1"
            disabled={Boolean(item)}
            disabledReason={item ? '저장된 문항의 ID는 바꿀 수 없습니다' : undefined}
            hint={
              item
                ? '저장된 문항의 ID는 바꿀 수 없습니다. 편집 묶음이 이 ID로 대상을 찾기 때문입니다.'
                : '업무·주제로 자동 생성되며, 필요하면 직접 고칠 수 있습니다.'
            }
            onChange={(v) => edit(() => { setIdTouched(true); setItemId(v) })} />
        </div>
      </div>

      <div className="mb-2 flex flex-wrap items-start gap-x-4 gap-y-2">
        <TextField label="질문"
          grow value={question} error={errorOf('question')}
          placeholder="예: 반환지원 수수료는 얼마인가요?"
          onChange={(v) => edit(() => setQuestion(v))} />
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-2">
        {/* 기대 출처는 코퍼스에서 검색해 고른다. 네이티브 datalist라 키보드 조작이 그대로 동작한다 */}
        <label className="inline-flex min-w-15 items-center gap-0.5 text-sm text-foreground" htmlFor={listId + '-input'}>
          기대 출처
          <InfoHint label="기대 출처 입력 방법 설명" size="sm">
            코퍼스에서 검색해 고릅니다. 문서 ID를 입력하면 후보가 자동완성으로 뜹니다.
          </InfoHint>
        </label>
        <Input
          id={listId + '-input'}
          className="h-8 w-65"
          list={listId}
          value={sourceId}
          placeholder="예: kmrs_apply_mthd"
          aria-invalid={errorOf('expected_source') ? true : undefined}
          aria-describedby={errorOf('expected_source') ? listId + '-error' : undefined}
          onChange={(e) => edit(() => setSourceId(e.target.value))}
        />
        <datalist id={listId}>
          {(corpus.data?.items ?? []).map((d) => (
            <option key={d.doc_id} value={d.doc_id} label={d.title} />
          ))}
        </datalist>
        {errorOf('expected_source') && (
          <p className="mt-1 basis-full text-xs text-destructive" id={listId + '-error'}>
            ✗ {errorOf('expected_source')}
          </p>
        )}
      </div>

      {/* 저장 호출 자체가 실패한 경우 — 서버 문구를 화면 안에 남긴다(토스트로 흘리지 않는다) */}
      {save.isError && (
        <p className="mt-1 text-xs text-destructive" role="alert">
          {save.error.message}
        </p>
      )}

      <div className="flex justify-end gap-2">
        <Button variant="secondary" size="sm" onClick={onCancel}>
          취소
        </Button>
        <Button
          variant="primary"
          size="sm"
          loading={save.isPending}
          disabled={blocked}
          disabledReason={blocked ? '검증에 걸린 항목을 고쳐야 저장할 수 있습니다' : undefined}
          onClick={() => save.mutate(input)}
        >
          저장
        </Button>
      </div>

    </div>
  )
}
