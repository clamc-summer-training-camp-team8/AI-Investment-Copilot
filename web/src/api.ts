import { demoEvidence, demoEvidenceFeed, demoThesis } from './mocks'
import type {
  AuditItem, ConfirmationState, Direction, EvidenceDetail, EvidenceFeedItem,
  Adjudication, DocumentSegment, IngestionReview, JobAccepted, JobStatus, PageResult, ProcessingJob, Relation,
  ReviewTask, Security, Strength, Suggestion, ThesisDetail, Trend, ValidationItem, WorkbenchData,
  MetricDefinition, MetricMapping, PublishReadiness,
  AssetInventory, AssetSearchHit,
  ThesisRevision, ThesisRevisionDiff,
} from './types'

export const useMock = import.meta.env.VITE_USE_MOCK === 'true'

function toDirection(value: unknown): Direction {
  return value === '支持' ? 'support' : value === '冲突' ? 'conflict' : 'neutral'
}

function toStrength(value: unknown): Strength {
  return value === '高' ? 'high' : value === '低' ? 'low' : 'medium'
}

function toStatus(value: unknown): ConfirmationState {
  return value === '已确认' ? 'confirmed' : value === '已驳回' ? 'rejected' : value === '已解除' ? 'deactivated' : 'pending'
}

/** 浏览器只走 Vite 代理；身份头由开发代理或生产网关注入。 */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData
  const response = await fetch(path, {
    ...init,
    headers: { ...(isForm ? {} : { 'Content-Type': 'application/json' }), ...(init?.headers ?? {}) },
  })
  if (response.status === 401) throw new Error('身份服务不可用，请刷新页面或联系管理员。')
  if (response.status === 403) throw new Error('当前账户可查看该对象，但没有此操作权限。')
  if (response.status === 404) throw new Error('对象不存在、已解除关联或无访问权限。')
  if (!response.ok) {
    const detail = await response.json().catch(() => null) as { detail?: unknown } | null
    throw new Error(typeof detail?.detail === 'string' ? detail.detail : `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}

function toThesis(item: Record<string, unknown>): ThesisDetail {
  return {
    thesisId: String(item.thesis_id), securityId: String(item.security_id),
    title: String(item.title), owner: String(item.owner), status: String(item.status),
    direction: String(item.direction), coreView: String(item.core_view), version: Number(item.version),
    establishedOn: String(item.established_on),
    horizonEndOn: item.horizon_end_on ? String(item.horizon_end_on) : undefined,
    nextReviewAt: item.next_review_at ? String(item.next_review_at) : undefined,
    hypotheses: ((item.hypotheses ?? []) as Array<Record<string, unknown>>).map((h) => ({
      hypothesisId: String(h.hypothesis_id), statement: String(h.statement),
      hypothesisType: String(h.hypothesis_type), importance: String(h.importance), status: String(h.status),
      observationWindow: h.observation_window ? String(h.observation_window) : undefined,
      invalidationRule: h.invalidation_rule ? String(h.invalidation_rule) : undefined,
      metricSuggestions: (h.metric_suggestions ?? []) as Array<Record<string, unknown>>,
      mappings: ((h.mappings ?? []) as Array<Record<string, unknown>>).map(toMapping),
    })),
    riskSuggestions: (item.risk_suggestions ?? []) as Array<Record<string, unknown>>,
    invalidationSuggestions: (item.invalidation_suggestions ?? []) as Array<Record<string, unknown>>,
  }
}

function toMapping(item: Record<string, unknown>): MetricMapping {
  return {
    mappingId: String(item.mapping_id), metricId: String(item.metric_id), metricVersion: String(item.metric_version),
    expectedDirection: String(item.expected_direction), expectedValue: item.expected_value == null ? undefined : String(item.expected_value),
    invalidationThreshold: item.invalidation_threshold == null ? undefined : String(item.invalidation_threshold),
    invalidationConsecutivePeriods: item.invalidation_consecutive_periods == null ? undefined : Number(item.invalidation_consecutive_periods),
    expectationSource: String(item.expectation_source), confirmationStatus: String(item.confirmation_status),
  }
}

function toFeedItem(item: Record<string, unknown>): EvidenceFeedItem {
  return {
    evidenceId: String(item.evidence_id), relationId: String(item.relation_id),
    securityId: String(item.security_id), securityName: String(item.security_name),
    thesisId: String(item.thesis_id), thesisTitle: String(item.thesis_title),
    hypothesisId: String(item.hypothesis_id), hypothesisStatement: String(item.hypothesis_statement),
    sourceDocumentTitle: String(item.source_document_title), factExcerpt: String(item.fact_excerpt),
    disclosedAt: String(item.disclosed_at), occurredAt: item.occurred_at ? String(item.occurred_at) : undefined,
    sourceUrl: String(item.source_url), direction: toDirection(item.direction),
    strength: toStrength(item.strength), aiConfidence: Number(item.ai_confidence ?? 0),
    confirmationStatus: toStatus(item.confirmation_status), priority: item.priority as EvidenceFeedItem['priority'],
    canManage: Boolean(item.can_manage), validationItems: (item.validation_items as Array<Record<string, unknown>>).map((v) => ({
      code: String(v.code), label: String(v.label), status: v.status as ValidationItem['status'], message: String(v.message),
    })),
  }
}

function toPage<T>(page: { items: T[]; page: { total: number; limit: number; offset: number } }): PageResult<T> {
  return { items: page.items, total: page.page.total, limit: page.page.limit, offset: page.page.offset }
}

export async function getEvidence(evidenceId: string): Promise<EvidenceDetail> {
  if (useMock) return { ...demoEvidence, evidenceId, aiStatus: '候选', promptVersion: 'demo', sourceDocumentId: 'DOC-DEMO', evidenceLocator: 'DOC-DEMO#paragraph-1' }
  const item = await request<Record<string, unknown>>(`/api/evidence/${evidenceId}`)
  return {
    evidenceId: String(item.evidence_id), securityId: String(item.security_id),
    factExcerpt: String(item.fact_excerpt), sourceDocumentTitle: String(item.source_document_title),
    disclosedAt: String(item.disclosed_at), occurredAt: item.occurred_at ? String(item.occurred_at) : undefined,
    sourceUrl: String(item.source_url), direction: toDirection(item.direction), strength: toStrength(item.strength),
    aiConfidence: Number(item.ai_confidence ?? 0), aiStatus: String(item.ai_status ?? '候选'),
    modelVersion: String(item.model_version ?? '-'), promptVersion: String(item.prompt_version ?? '-'),
    confirmationStatus: toStatus(item.confirmation_status), sourceDocumentId: String(item.source_document_id),
    evidenceLocator: String(item.evidence_locator),
  }
}

export async function getRelations(evidenceId: string): Promise<Relation[]> {
  if (useMock) return []
  const items = await request<Array<Record<string, unknown>>>(`/api/evidence/${evidenceId}/relations`)
  return items.map((item) => ({
    relationId: String(item.relation_id), thesisId: String(item.thesis_id), hypothesisId: String(item.hypothesis_id),
    direction: toDirection(item.direction), strength: toStrength(item.strength), status: toStatus(item.status),
    reason: String(item.reason ?? ''), createdBy: String(item.created_by),
    reviewedBy: item.reviewed_by ? String(item.reviewed_by) : undefined,
    reviewedAt: item.reviewed_at ? String(item.reviewed_at) : undefined,
    deactivatedBy: item.deactivated_by ? String(item.deactivated_by) : undefined,
    deactivatedAt: item.deactivated_at ? String(item.deactivated_at) : undefined,
    canManage: Boolean(item.can_manage),
  }))
}

export async function getThesis(thesisId: string): Promise<ThesisDetail> {
  if (useMock) return { ...demoThesis, direction: '观察', coreView: '受控演示数据', version: 1, establishedOn: '2026-01-01', hypotheses: [], riskSuggestions: [], invalidationSuggestions: [] }
  return toThesis(await request<Record<string, unknown>>(`/api/theses/${thesisId}`))
}

export async function listTheses(securityId?: string, manageable = false): Promise<ThesisDetail[]> {
  if (useMock) return [demoThesis]
  const page = await request<{ items: Array<Record<string, unknown>> }>(`/api/theses?limit=50${securityId ? `&security_id=${encodeURIComponent(securityId)}` : ''}${manageable ? '&manageable=true' : ''}`)
  return page.items.map(toThesis)
}

export async function listSecurities(): Promise<Security[]> {
  if (useMock) return [{ securityId: 'DEMO001', name: '华夏储能科技（虚拟）' }]
  const items = await request<Array<Record<string, unknown>>>('/api/securities?limit=200')
  return items.map((item) => ({
    securityId: String(item.security_id), name: String(item.name),
    ticker: item.ticker ? String(item.ticker) : undefined,
    industry: item.industry ? String(item.industry) : undefined,
  }))
}

export async function createSecurity(payload: { securityId: string; name: string; industry?: string }): Promise<Security> {
  const item = await request<Record<string, unknown>>('/api/securities', {
    method: 'POST',
    body: JSON.stringify({ security_id: payload.securityId, name: payload.name, ticker: payload.securityId, industry: payload.industry || null }),
  })
  return {
    securityId: String(item.security_id), name: String(item.name),
    ticker: item.ticker ? String(item.ticker) : undefined,
    industry: item.industry ? String(item.industry) : undefined,
  }
}

async function getFeed(path: string): Promise<PageResult<EvidenceFeedItem>> {
  const page = await request<{ items: Array<Record<string, unknown>>; page: { total: number; limit: number; offset: number } }>(path)
  return toPage({ ...page, items: page.items.map(toFeedItem) })
}

export function getWorkbenchTasks(limit = 20): Promise<PageResult<EvidenceFeedItem>> {
  if (useMock) return Promise.resolve({ items: [demoEvidenceFeed], total: 1, limit, offset: 0 })
  return getFeed(`/api/workbench/tasks?limit=${limit}`)
}

export function getRadarEvidence(thesisId: string, filters: { status?: string; direction?: string } = {}): Promise<PageResult<EvidenceFeedItem>> {
  if (useMock) return Promise.resolve({ items: [demoEvidenceFeed], total: 1, limit: 50, offset: 0 })
  const params = new URLSearchParams({ thesis_id: thesisId, limit: '50' })
  if (filters.status) params.append('status', filters.status)
  if (filters.direction) params.set('direction', filters.direction)
  return getFeed(`/api/radar/evidence?${params}`)
}

export function getThesisEvidenceFeed(thesisId: string): Promise<PageResult<EvidenceFeedItem>> {
  if (useMock) return Promise.resolve({ items: [demoEvidenceFeed], total: 1, limit: 100, offset: 0 })
  return getFeed(`/api/theses/${thesisId}/evidence-feed?limit=100`)
}

export async function getSuggestions(thesisId: string): Promise<Suggestion[]> {
  if (useMock) return []
  const items = await request<Array<Record<string, unknown>>>(`/api/theses/${thesisId}/suggestions`)
  return items.map((item) => ({ suggestionId: Number(item.suggestion_id), currentStatus: String(item.current_status), suggestedStatus: String(item.suggested_status), reasons: item.reasons as string[], triggeredHypotheses: (item.triggered_hypotheses ?? []) as string[], ruleVersion: String(item.rule_version), humanAction: item.human_action ? String(item.human_action) : undefined }))
}

export async function getTrends(thesisId: string): Promise<Trend[]> {
  if (useMock) return []
  const items = await request<Array<Record<string, unknown>>>(`/api/theses/${thesisId}/trends`)
  return items.map((item) => ({ hypothesisId: String(item.hypothesis_id), statement: String(item.statement), metricId: String(item.metric_id), unit: String(item.unit), direction: String(item.direction), points: (item.points as Array<Record<string, unknown>>).map((p) => ({ period: String(p.period), value: String(p.value) })) }))
}

export async function getAudit(thesisId: string): Promise<AuditItem[]> {
  if (useMock) return []
  const page = await request<{ items: Array<Record<string, unknown>> }>(`/api/theses/${thesisId}/audit`)
  return page.items.map((item) => ({ action: String(item.action), actor: String(item.actor), occurredAt: item.occurred_at ? String(item.occurred_at) : undefined, detail: item.detail as Record<string, unknown> | undefined }))
}

export async function getWorkbench(): Promise<WorkbenchData> {
  if (useMock) return { statusCounts: { 验证中: 1 }, pendingEvidence: [], pendingSuggestions: [], reviewDue: [] }
  const item = await request<Record<string, unknown>>('/api/workbench')
  const items = (key: string) => ((item[key] ?? []) as Array<Record<string, unknown>>).map((x) => ({ kind: String(x.kind), thesisId: String(x.thesis_id), title: String(x.title), objectId: String(x.object_id), summary: String(x.summary) }))
  return { statusCounts: item.status_counts as Record<string, number>, pendingEvidence: items('pending_evidence'), pendingSuggestions: items('pending_suggestions'), reviewDue: items('review_due') }
}

export async function createRelation(evidenceId: string, payload: { thesisId: string; hypothesisId: string; direction: string; strength: string; reason: string }): Promise<void> {
  await request(`/api/evidence/${evidenceId}/relations`, { method: 'POST', body: JSON.stringify({ thesis_id: payload.thesisId, hypothesis_id: payload.hypothesisId, direction: payload.direction, strength: payload.strength, reason: payload.reason }) })
}

export async function updateRelation(evidenceId: string, relationId: string, payload: { thesisId: string; hypothesisId: string; direction: string; strength: string; reason: string }): Promise<void> {
  await request(`/api/evidence/${evidenceId}/relations/${relationId}`, { method: 'PATCH', body: JSON.stringify({ thesis_id: payload.thesisId, hypothesis_id: payload.hypothesisId, direction: payload.direction, strength: payload.strength, reason: payload.reason }) })
}

export async function reviewRelation(evidenceId: string, relationId: string, action: string, reason?: string): Promise<void> {
  await request(`/api/evidence/${evidenceId}/relations/${relationId}/review`, { method: 'POST', body: JSON.stringify({ action, reason }) })
}

export async function deactivateRelation(evidenceId: string, relationId: string, reason: string): Promise<void> {
  await request(`/api/evidence/${evidenceId}/relations/${relationId}/deactivate`, { method: 'POST', body: JSON.stringify({ reason }) })
}

export async function decideStatus(thesisId: string, payload: { suggestionId: number; action: string; reason: string; targetStatus?: string }): Promise<void> {
  await request(`/api/theses/${thesisId}/status`, { method: 'POST', body: JSON.stringify({ suggestion_id: payload.suggestionId, action: payload.action, reason: payload.reason, target_status: payload.targetStatus }) })
}

export async function createDraft(payload: { securityId: string; view: string; useRag?: boolean }): Promise<ThesisDetail> {
  return toThesis(await request<Record<string, unknown>>('/api/theses/drafts', { method: 'POST', body: JSON.stringify({ security_id: payload.securityId, view: payload.view, use_rag: Boolean(payload.useRag) }) }))
}

export async function publishThesis(thesisId: string, payload: { direction: string; horizonEndOn: string; nextReviewAt: string }): Promise<ThesisDetail> {
  return toThesis(await request<Record<string, unknown>>(`/api/theses/${thesisId}/publish`, { method: 'POST', body: JSON.stringify({ direction: payload.direction, horizon_end_on: payload.horizonEndOn, next_review_at: payload.nextReviewAt }) }))
}

export async function getPublishReadiness(thesisId: string, payload: { direction: string; horizonEndOn: string; nextReviewAt: string }): Promise<PublishReadiness> {
  const item = await request<{ ready: boolean; items: Array<Record<string, unknown>> }>(`/api/theses/${thesisId}/publish-readiness`, { method: 'POST', body: JSON.stringify({ direction: payload.direction, horizon_end_on: payload.horizonEndOn, next_review_at: payload.nextReviewAt }) })
  return { ready: item.ready, items: item.items.map((row) => ({ code: String(row.code), label: String(row.label), passed: Boolean(row.passed), message: String(row.message) })) }
}

export async function updateHypothesis(thesisId: string, hypothesisId: string, payload: { statement: string; hypothesisType: string; importance: string; observationWindow?: string; invalidationRule?: string }): Promise<ThesisDetail> {
  return toThesis(await request<Record<string, unknown>>(`/api/theses/${thesisId}/hypotheses/${hypothesisId}`, { method: 'PATCH', body: JSON.stringify({ statement: payload.statement, hypothesis_type: payload.hypothesisType, importance: payload.importance, observation_window: payload.observationWindow || null, invalidation_rule: payload.invalidationRule || null }) }))
}

export async function listMetrics(keyword = ''): Promise<MetricDefinition[]> {
  const items = await request<Array<Record<string, unknown>>>(`/api/metrics?limit=100${keyword ? `&keyword=${encodeURIComponent(keyword)}` : ''}`)
  return items.map((item) => ({ metricId: String(item.metric_id), version: String(item.version), name: String(item.name), unit: String(item.unit), category: item.category ? String(item.category) : undefined, definition: item.definition ? String(item.definition) : undefined, frequency: item.frequency ? String(item.frequency) : undefined, expectedDirection: item.expected_direction ? String(item.expected_direction) : undefined, status: String(item.status) }))
}

export async function saveMetricMapping(thesisId: string, hypothesisId: string, payload: { mappingId?: string; metricId: string; metricVersion: string; expectedDirection: string; expectedValue?: string; invalidationThreshold?: string; invalidationConsecutivePeriods?: number; expectationSource: string }): Promise<MetricMapping> {
  const item = await request<Record<string, unknown>>(`/api/theses/${thesisId}/hypotheses/${hypothesisId}/mappings`, { method: 'POST', body: JSON.stringify({ mapping_id: payload.mappingId || null, metric_id: payload.metricId, metric_version: payload.metricVersion, expected_direction: payload.expectedDirection, expected_value: payload.expectedValue || null, invalidation_threshold: payload.invalidationThreshold || null, invalidation_consecutive_periods: payload.invalidationConsecutivePeriods || null, expectation_source: payload.expectationSource }) })
  return toMapping(item)
}

export async function getAdjudications(): Promise<Array<Record<string, unknown>>> {
  if (useMock) return []
  const page = await request<{ items: Array<Record<string, unknown>> }>('/api/reviews/adjudications?limit=100')
  return page.items
}

export async function listAdjudications(): Promise<Adjudication[]> {
  const items = await getAdjudications()
  return items.map((item) => ({
    eventId: String(item.event_id), company: String(item.company), title: String(item.title),
    category: String(item.category), annotatorAHypothesis: String(item.annotator_a_hypothesis),
    annotatorADirection: String(item.annotator_a_direction), annotatorBHypothesis: String(item.annotator_b_hypothesis),
    annotatorBDirection: String(item.annotator_b_direction), disagreement: String(item.disagreement),
    resolved: Boolean(item.resolved), decidedHypothesis: item.decided_hypothesis ? String(item.decided_hypothesis) : undefined,
    decidedDirection: item.decided_direction ? String(item.decided_direction) : undefined,
    decisionReason: item.decision_reason ? String(item.decision_reason) : undefined,
  }))
}

export async function decideAdjudication(eventId: string, payload: { hypothesis: string; direction: string; reason: string }): Promise<void> {
  await request(`/api/reviews/adjudications/${encodeURIComponent(eventId)}`, { method: 'POST', body: JSON.stringify(payload) })
}

export async function uploadDocument(payload: { file: File; publishedAt: string; thesisId?: string; securityId?: string; view?: string }): Promise<JobAccepted> {
  if (useMock) return { jobId: 'JOB-DEMO-UPLOAD', documentId: 'DOC-DEMO-UPLOAD', status: 'queued' }
  const form = new FormData()
  form.append('file', payload.file)
  form.append('published_at', new Date(payload.publishedAt).toISOString())
  if (payload.securityId) form.append('security_id', payload.securityId)
  if (payload.thesisId) form.append('thesis_id', payload.thesisId)
  if (payload.view) form.append('view', payload.view)
  const item = await request<Record<string, unknown>>('/api/jobs/documents', { method: 'POST', body: form })
  return { jobId: String(item.job_id), documentId: String(item.document_id), status: String(item.status) }
}

export async function getJob(jobId: string): Promise<JobStatus> {
  if (useMock) return { jobId, status: 'complete', success: true, result: { persisted_document_id: 'DOC-DEMO-UPLOAD', duplicate: false, segment_count: 3, fact_count: 2 } }
  const item = await request<Record<string, unknown>>(`/api/jobs/${encodeURIComponent(jobId)}`)
  return { jobId: String(item.job_id), status: String(item.status), success: item.success == null ? undefined : Boolean(item.success), result: item.result as Record<string, unknown> | undefined, enqueueTime: item.enqueue_time ? String(item.enqueue_time) : undefined, startTime: item.start_time ? String(item.start_time) : undefined, finishTime: item.finish_time ? String(item.finish_time) : undefined }
}

export async function listProcessingJobs(): Promise<ProcessingJob[]> {
  if (useMock) return []
  const items = await request<Array<Record<string, unknown>>>('/api/jobs?limit=100')
  return items.map((item) => ({
    jobId: String(item.job_id), documentId: String(item.document_id), sourceFilename: String(item.source_filename),
    securityId: item.security_id ? String(item.security_id) : undefined, status: String(item.status),
    attemptCount: Number(item.attempt_count), maxAttempts: Number(item.max_attempts),
    result: item.result as Record<string, unknown> | undefined, lastError: item.last_error ? String(item.last_error) : undefined,
    createdAt: item.created_at ? String(item.created_at) : undefined, startedAt: item.started_at ? String(item.started_at) : undefined,
    finishedAt: item.finished_at ? String(item.finished_at) : undefined,
  }))
}

export async function replayProcessingJob(jobId: string): Promise<JobAccepted> {
  const item = await request<Record<string, unknown>>(`/api/jobs/${encodeURIComponent(jobId)}/replay`, { method: 'POST' })
  return { jobId: String(item.job_id), documentId: String(item.document_id), status: String(item.status) }
}

export async function listIngestionReviews(): Promise<IngestionReview[]> {
  if (useMock) return []
  const items = await request<Array<Record<string, unknown>>>('/api/reviews/ingestion?limit=100')
  return items.map((item) => ({
    reviewId: String(item.review_id), reviewType: String(item.review_type), documentId: String(item.document_id),
    jobId: item.job_id ? String(item.job_id) : undefined, eventId: item.event_id ? String(item.event_id) : undefined,
    reason: String(item.reason), status: String(item.status), payload: (item.payload ?? {}) as Record<string, unknown>,
    securityCandidates: ((item.security_candidates ?? []) as Array<Record<string, unknown>>).map((candidate) => ({
      securityId: String(candidate.security_id), name: String(candidate.name), score: Number(candidate.score),
      matchedTerms: (candidate.matched_terms ?? []) as string[],
    })), resolution: item.resolution ? String(item.resolution) : undefined,
    createdAt: item.created_at ? String(item.created_at) : undefined, resolvedAt: item.resolved_at ? String(item.resolved_at) : undefined,
  }))
}

export async function resolveIngestionReview(reviewId: string, payload: { resolution: string; securityId?: string }): Promise<void> {
  await request(`/api/reviews/ingestion/${encodeURIComponent(reviewId)}/resolve`, {
    method: 'POST', body: JSON.stringify({ resolution: payload.resolution, security_id: payload.securityId || null }),
  })
}

export async function listReviewTasks(): Promise<ReviewTask[]> {
  if (useMock) return []
  const items = await request<Array<Record<string, unknown>>>('/api/reviews?limit=100')
  return items.map((item) => ({ taskId: String(item.task_id), thesisId: String(item.thesis_id), trigger: String(item.trigger), priority: String(item.priority), assignee: String(item.assignee), state: String(item.state), detail: item.detail as Record<string, unknown> | undefined, resolution: item.resolution ? String(item.resolution) : undefined, createdAt: item.created_at ? String(item.created_at) : undefined, resolvedAt: item.resolved_at ? String(item.resolved_at) : undefined }))
}

export async function resolveReviewTask(taskId: string, resolution: string): Promise<void> {
  await request(`/api/reviews/${encodeURIComponent(taskId)}/resolve`, { method: 'POST', body: JSON.stringify({ resolution }) })
}

export async function getDocumentSegment(locator: string): Promise<DocumentSegment> {
  const matched = locator.match(/^(.+)#paragraph-(\d+)$/)
  if (!matched) throw new Error('原文定位格式无效。')
  if (useMock) return { documentId: matched[1], title: '演示公告正文', locator, ordinal: Number(matched[2]), content: demoEvidence.factExcerpt, contentKind: 'paragraph', extractionMethod: 'native' }
  const item = await request<Record<string, unknown>>(`/api/documents/${encodeURIComponent(matched[1])}/segments/${matched[2]}`)
  return { documentId: String(item.document_id), title: item.title ? String(item.title) : undefined, locator: String(item.locator), ordinal: Number(item.ordinal), page: item.page == null ? undefined : Number(item.page), content: String(item.content), contentKind: String(item.content_kind ?? 'paragraph'), extractionMethod: String(item.extraction_method ?? 'native'), tableIndex: item.table_index == null ? undefined : Number(item.table_index), rowIndex: item.row_index == null ? undefined : Number(item.row_index), cellRange: item.cell_range ? String(item.cell_range) : undefined, confidence: item.confidence == null ? undefined : Number(item.confidence), previousLocator: item.previous_locator ? String(item.previous_locator) : undefined, nextLocator: item.next_locator ? String(item.next_locator) : undefined }
}

export async function getAssetInventory(): Promise<AssetInventory> {
  if (useMock) return { documents: 3789, revisions: 3789, ingestionRuns: 7578, segments: 3789, facts: 0, singleSegmentDocuments: 3789, pendingAuthorization: 3789, missingObjectArchive: 3789, semanticRuns: 3789, artifactSegments: 7578, artifactFacts: 0, artifactEvents: 3788 }
  const item = await request<Record<string, unknown>>('/api/assets/inventory')
  return {
    documents: Number(item.documents), revisions: Number(item.revisions),
    ingestionRuns: Number(item.ingestion_runs), segments: Number(item.segments),
    facts: Number(item.facts), singleSegmentDocuments: Number(item.single_segment_documents),
    pendingAuthorization: Number(item.pending_authorization),
    missingObjectArchive: Number(item.missing_object_archive),
    semanticRuns: Number(item.semantic_runs), artifactSegments: Number(item.artifact_segments),
    artifactFacts: Number(item.artifact_facts), artifactEvents: Number(item.artifact_events),
  }
}

export async function rebuildAssetSearchIndex(): Promise<number> {
  if (useMock) return 3789
  const item = await request<Record<string, unknown>>('/api/assets/search-index/rebuild', { method: 'POST' })
  return Number(item.indexed_segments)
}

export async function searchAssets(query: string): Promise<AssetSearchHit[]> {
  if (useMock) return []
  const items = await request<Array<Record<string, unknown>>>(`/api/assets/hybrid-search?q=${encodeURIComponent(query)}&limit=20`)
  return items.map((item) => ({
    documentId: String(item.document_id), locator: String(item.locator),
    content: String(item.content), visibilityLabel: String(item.visibility_label),
    rank: Number(item.rank),
    retrievalMode: String(item.retrieval_mode ?? 'keyword'),
    keywordRank: item.keyword_rank == null ? undefined : Number(item.keyword_rank),
    vectorRank: item.vector_rank == null ? undefined : Number(item.vector_rank),
    ingestionRunId: item.ingestion_run_id ? String(item.ingestion_run_id) : undefined,
    embeddingVersion: item.embedding_version ? String(item.embedding_version) : undefined,
  }))
}

function toThesisRevision(item: Record<string, unknown>): ThesisRevision {
  return {
    draftId: String(item.draft_id), thesisId: String(item.thesis_id),
    baseVersion: Number(item.base_version), revision: Number(item.revision),
    owner: String(item.owner), payload: item.payload as Record<string, unknown>,
    status: String(item.status),
  }
}

export async function createThesisRevision(thesisId: string): Promise<ThesisRevision> {
  return toThesisRevision(await request<Record<string, unknown>>(`/api/assets/theses/${encodeURIComponent(thesisId)}/revisions`, { method: 'POST' }))
}

export async function updateThesisRevision(draft: ThesisRevision, payload: Record<string, unknown>): Promise<ThesisRevision> {
  return toThesisRevision(await request<Record<string, unknown>>(`/api/assets/thesis-revisions/${encodeURIComponent(draft.draftId)}`, { method: 'PATCH', body: JSON.stringify({ expected_revision: draft.revision, payload }) }))
}

export async function getThesisRevisionDiff(draftId: string): Promise<ThesisRevisionDiff> {
  const item = await request<Record<string, unknown>>(`/api/assets/thesis-revisions/${encodeURIComponent(draftId)}/diff`)
  return { draftId: String(item.draft_id), baseVersion: Number(item.base_version), changes: item.changes as ThesisRevisionDiff['changes'] }
}

export async function publishThesisRevision(draft: ThesisRevision, reason: string): Promise<ThesisRevision> {
  return toThesisRevision(await request<Record<string, unknown>>(`/api/assets/thesis-revisions/${encodeURIComponent(draft.draftId)}/publish`, { method: 'POST', body: JSON.stringify({ expected_revision: draft.revision, reason }) }))
}
