/** 공통 UI 컴포넌트 라이브러리 — CM-DF-001 10절 매핑표 그대로.
 * 개별 화면에서 임의로 변형하지 말고 여기 정의를 가져다 쓴다(문서 머리말). */

export { Button, buttonVariants } from './Button'
export type { ButtonProps } from './Button'

export { Badge } from './Badge'
export type { BadgeProps } from './Badge'

export { ColorText } from './ColorText'
export type { ColorTextProps } from './ColorText'

export { ConfirmModal, REASON_MAX_LENGTH } from './ConfirmModal'
export type { ConfirmModalProps } from './ConfirmModal'

export { DetailModal } from './DetailModal'
export type { DetailModalProps } from './DetailModal'

export { DraftStatusBar } from './DraftStatusBar'
export type { DraftStatusBarProps } from './DraftStatusBar'

export { DirtyDot } from './DirtyDot'
export type { DirtyDotProps } from './DirtyDot'

export { Notice } from './Notice'

/** 요청 실패를 화면 안에 남기는 공통 패널 (Dashboard·설정·지식베이스가 함께 쓴다) */
export { SectionError } from './SectionError'
export type { SectionErrorProps } from './SectionError'

/** `마지막 갱신 … · [새로고침]` 한 줄 */
export { RefreshBar } from './RefreshBar'

/** 권한으로 화면이 잠겼을 때 한 번만 쓰는 '보기 전용' 안내 */
export { ReadOnlyNotice } from './ReadOnlyNotice'
export type { NoticeProps, NoticeTone, NoticeVariant } from './Notice'

export { InfoHint } from './InfoHint'
export type { InfoHintProps } from './InfoHint'

export { EmptyState } from './EmptyState'
export type { EmptyStateProps } from './EmptyState'

export { Loading, LoadingText, Skeleton, Spinner } from './Loading'
export type { LoadingProps, LoadingTextProps, SpinnerProps } from './Loading'

export { Toast, ToastProvider, useToast } from './Toast'
export type { ToastAction, ToastProps } from './Toast'

export { PipelineSteps, PipelineStepText } from './PipelineSteps'
export type { PipelineStepsProps, PipelineStepTextProps, StepState } from './PipelineSteps'

// --- 폼 컨트롤 (04절) ---
export { Field } from './form/Field'
export type { FieldOptions, FieldProps } from './form/Field'
export { Stepper } from './form/Stepper'
export type { StepperProps } from './form/Stepper'
export { Toggle } from './form/Toggle'
export type { ToggleProps } from './form/Toggle'
export { Slider } from './form/Slider'
export type { SliderProps } from './form/Slider'
export { Select } from './form/Select'
export type { SelectOption, SelectProps } from './form/Select'
export { TextField } from './form/TextField'
export type { TextFieldProps } from './form/TextField'

// --- 표 (06절) ---
export { DataTable } from './table/DataTable'
export type { Column, DataTableProps, RowState, SortState } from './table/DataTable'
export { Pagination, DEFAULT_PAGE_SIZE } from './table/Pagination'
export type { PaginationProps } from './table/Pagination'

// --- 레이아웃 규칙 ---
export { CARD_COLUMN, CARD_COLUMNS } from './layout'
