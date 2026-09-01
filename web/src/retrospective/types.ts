export type RetrospectiveState = '草稿' | '待评审' | '已发布' | '已归档'
export type RetrospectiveType = '周期' | '结项' | '专题' | '人工'
export type HypothesisResult = '成立' | '部分成立' | '不成立' | '证据不足' | '尚未到期'

export interface RetrospectiveRecord {
  retrospective_id: string
  thesis_id: string
  thesis_title: string
  security_id: string
  retrospective_type: RetrospectiveType
  title: string
  period_start: string
  period_end: string
  data_cutoff_at: string
  owner: string
  reviewer?: string
  state: RetrospectiveState
  visibility: string
  team?: string
  source_fingerprint: string
  source_count: number
  completeness_completed: number
  completeness_applicable: number
  completeness_score: number
  current_version: number
  lock_version: number
  ai_status: string
  hypothesis_result_counts: Record<string, number>
  strong_conflicts_handled: number
  strong_conflicts_total: number
  created_at?: string
  updated_at?: string
  submitted_at?: string
  published_at?: string
  archived_at?: string
}

export interface RetrospectiveSource {
  source_id: string
  source_type: string
  object_id: string
  object_version?: string
  locator?: string
  content_hash?: string
  summary: string
  direction?: string
  strength?: string
  hypothesis_id?: string
  disclosed_at?: string
  confirmed_at?: string
  visibility_label: string
  metadata: Record<string, unknown>
}

export interface RetrospectiveVersion {
  retrospective_id: string
  version: number
  content: RetrospectiveContent
  source_fingerprint: string
  published_by: string
  publish_reason: string
  ai_run_id?: string
  model_version?: string
  prompt_version?: string
  schema_version?: string
  created_at?: string
}

export interface HypothesisAssessment {
  hypothesis_id: string
  statement: string
  result: HypothesisResult
  rationale: string
  source_ids: string[]
}

export interface RetrospectiveContent {
  summary?: string
  original_judgement?: string
  key_changes?: string[]
  hypothesis_assessments?: HypothesisAssessment[]
  errors_and_omissions?: string
  conflict_resolution?: string
  limitations?: string
  next_actions?: string
  citations?: string[]
  review_feedback?: string
  revision_reason?: string
  [key: string]: unknown
}

export interface RetrospectiveDetail {
  retrospective: RetrospectiveRecord
  content: RetrospectiveContent
  ai_candidate?: Record<string, unknown>
  sources: RetrospectiveSource[]
  versions: RetrospectiveVersion[]
  allowed_actions: string[]
}

export interface RetrospectiveOverview {
  as_of?: string
  total: number
  state_counts: Record<string, number>
  logic_changes: number
  validated_hypotheses: number
  pending_hypotheses: number
  strong_conflicts_handled: number
  strong_conflicts_total: number
  average_completeness: number
  pending_reports: number
  is_truncated: boolean
  definitions: Record<string, string>
}

export interface RetrospectivePage {
  items: RetrospectiveRecord[]
  total: number
  limit: number
  offset: number
}

export interface SourcePreview {
  thesis_id: string
  thesis_title: string
  security_id: string
  owner: string
  source_fingerprint: string
  source_count: number
  completeness_completed: number
  completeness_applicable: number
  completeness_score: number
  missing_items: string[]
  excluded_counts: Record<string, number>
  hypotheses: Array<{ hypothesis_id: string; name?: string; statement: string; status: string }>
  sources: RetrospectiveSource[]
}

export interface TimelineItem {
  source_id: string
  source_type: string
  title: string
  summary: string
  occurred_at?: string
  disclosed_at?: string
  confirmed_at?: string
  direction?: string
  strength?: string
  hypothesis_id?: string
  locator?: string
  object_id: string
  object_version?: string
  metadata: Record<string, unknown>
}

export interface AiDraftResult {
  run_id: string
  status: 'completed' | 'failed'
  requires_human_review: true
  candidate?: Record<string, unknown>
  errors: string[]
  lock_version: number
}
