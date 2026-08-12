export type Direction = 'support' | 'conflict' | 'neutral'
export type Strength = 'high' | 'medium' | 'low'
export type ConfirmationState = 'pending' | 'confirmed' | 'rejected' | 'deactivated'
export type Priority = 'high' | 'medium' | 'low'

export interface ValidationItem {
  code: string
  label: string
  status: 'passed' | 'warning' | 'failed'
  message: string
}

export interface EvidenceFeedItem {
  evidenceId: string
  relationId: string
  securityId: string
  securityName: string
  thesisId: string
  thesisTitle: string
  hypothesisId: string
  hypothesisStatement: string
  sourceDocumentTitle: string
  factExcerpt: string
  disclosedAt: string
  occurredAt?: string
  sourceUrl: string
  direction: Direction
  strength: Strength
  aiConfidence: number
  confirmationStatus: ConfirmationState
  priority: Priority
  canManage: boolean
  validationItems: ValidationItem[]
}

export interface PageResult<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface EvidenceDetail {
  evidenceId: string
  securityId: string
  factExcerpt: string
  sourceDocumentTitle: string
  disclosedAt: string
  occurredAt?: string
  sourceUrl: string
  direction: Direction
  strength: Strength
  aiConfidence: number
  aiStatus: string
  modelVersion: string
  promptVersion: string
  confirmationStatus: ConfirmationState
  sourceDocumentId: string
  evidenceLocator: string
}

export interface ThesisSummary {
  thesisId: string
  securityId: string
  title: string
  owner: string
  status: string
  direction?: string
}

export interface ThesisDetail extends ThesisSummary {
  direction: string
  coreView: string
  version: number
  establishedOn: string
  horizonEndOn?: string
  nextReviewAt?: string
  hypotheses: Array<{ hypothesisId: string; statement: string; importance: string; status: string }>
}

export interface Relation {
  relationId: string
  thesisId: string
  hypothesisId: string
  direction: Direction
  strength: Strength
  status: ConfirmationState
  reason: string
  createdBy: string
  reviewedBy?: string
  reviewedAt?: string
  deactivatedBy?: string
  deactivatedAt?: string
  canManage: boolean
}

export interface PendingItem {
  kind: string
  thesisId: string
  title: string
  objectId: string
  summary: string
}

export interface WorkbenchData {
  statusCounts: Record<string, number>
  pendingEvidence: PendingItem[]
  pendingSuggestions: PendingItem[]
  reviewDue: PendingItem[]
}

export interface Suggestion {
  suggestionId: number
  currentStatus: string
  suggestedStatus: string
  reasons: string[]
  triggeredHypotheses: string[]
  ruleVersion: string
  humanAction?: string
}

export interface Trend {
  hypothesisId: string
  statement: string
  metricId: string
  unit: string
  direction: string
  points: Array<{ period: string; value: string }>
}

export interface AuditItem {
  action: string
  actor: string
  occurredAt?: string
  detail?: Record<string, unknown>
}

export interface JobAccepted {
  jobId: string
  documentId: string
  status: string
}

export interface JobStatus {
  jobId: string
  status: string
  success?: boolean
  result?: Record<string, unknown>
  enqueueTime?: string
  startTime?: string
  finishTime?: string
}

export interface ReviewTask {
  taskId: string
  thesisId: string
  trigger: string
  priority: string
  assignee: string
  state: string
  detail?: Record<string, unknown>
  resolution?: string
  createdAt?: string
  resolvedAt?: string
}

export interface Adjudication {
  eventId: string
  company: string
  title: string
  category: string
  annotatorAHypothesis: string
  annotatorADirection: string
  annotatorBHypothesis: string
  annotatorBDirection: string
  disagreement: string
  resolved: boolean
  decidedHypothesis?: string
  decidedDirection?: string
  decisionReason?: string
}

export interface DocumentSegment {
  documentId: string
  title?: string
  locator: string
  ordinal: number
  page?: number
  content: string
  previousLocator?: string
  nextLocator?: string
}
