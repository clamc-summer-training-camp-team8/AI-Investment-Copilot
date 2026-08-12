export type SourceKind = 'fact' | 'ai' | 'computed' | 'human'
export type Direction = 'support' | 'conflict' | 'neutral'
export type RelationStatus = 'pending' | 'confirmed' | 'rejected'
export type DecisionAction = '接受' | '拒绝' | '修改'

export interface HypothesisHealth {
  hypothesisId: string
  statement: string
  importance: string
  supportConfirmed: number
  conflictConfirmed: number
  pending: number
  health: string
  healthReason: string
  metric: { name: string; value: string; trend: string }
  invalidation: string
}

export interface ThesisDetail {
  thesisId: string
  securityId: string
  securityName: string
  title: string
  coreView: string
  status: string
  direction: string
  owner: string
  version: number
  establishedOn: string
  hypotheses: HypothesisHealth[]
}

export interface EvidenceAnalysis {
  evidenceId: string
  relationId: string
  documentId: string
  documentTitle: string
  disclosedAt: string
  factExcerpt: string
  hypothesisId: string
  hypothesisStatement: string
  affectedHypotheses: {
    hypothesisId: string
    statement: string
    metricName: string
    actualValue: string
    invalidationThreshold: string
    direction: Direction
  }[]
  direction: Direction
  strength: 'high' | 'medium' | 'low'
  transmissionPath: string
  aiConfidence: string
  modelVersion: string
  promptVersion: string
  evidenceLocator: string
  resultSource: 'preset_ai_result'
  relationStatus: RelationStatus
  canManage: boolean
  reviewReason?: string
}

export interface CitationContext {
  documentTitle: string
  documentType: string
  disclosedAt: string
  locator: string
  page?: number
  previous?: string
  target: string
  next?: string
  sourceUrl?: string
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

export type TimelineDimension =
  | 'material'
  | 'ai_analysis'
  | 'human_review'
  | 'hypothesis_health'
  | 'logic_decision'

export interface TimelineEvent {
  eventId: string
  dimension: TimelineDimension
  occurredAt: string
  actorType: 'human' | 'system' | 'preset_ai'
  actorName: string
  summary: string
  reason?: string
  before?: Record<string, string | number>
  after?: Record<string, string | number>
  detailUrl?: string
}

export interface ScenarioUploadResult {
  documentId: string
  evidenceIds: string[]
  relationIds: string[]
  resultSource: 'preset_ai_result'
  duplicate: boolean
  nextUrl: string
}

export interface ApiErrorShape {
  status: number
  code?: string
  message: string
  retryable: boolean
}
