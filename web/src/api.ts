import { demoEvidence, demoThesis } from './mocks'
import type {
  AuditItem, ConfirmationState, Direction, EvidenceDetail, EvidenceFeedItem,
  PageResult, Relation, Strength, Suggestion, ThesisDetail, Trend,
  ValidationItem, WorkbenchData,
} from './types'

export const useMock = import.meta.env.VITE_USE_MOCK !== 'false'

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
  const response = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
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
      importance: String(h.importance), status: String(h.status),
    })),
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
  if (useMock) return { ...demoThesis, direction: '观察', coreView: '受控演示数据', version: 1, establishedOn: '2026-01-01', hypotheses: [] }
  return toThesis(await request<Record<string, unknown>>(`/api/theses/${thesisId}`))
}

export async function listTheses(securityId?: string, manageable = false): Promise<ThesisDetail[]> {
  if (useMock) return [demoThesis]
  const page = await request<{ items: Array<Record<string, unknown>> }>(`/api/theses?limit=50${securityId ? `&security_id=${encodeURIComponent(securityId)}` : ''}${manageable ? '&manageable=true' : ''}`)
  return page.items.map(toThesis)
}

async function getFeed(path: string): Promise<PageResult<EvidenceFeedItem>> {
  const page = await request<{ items: Array<Record<string, unknown>>; page: { total: number; limit: number; offset: number } }>(path)
  return toPage({ ...page, items: page.items.map(toFeedItem) })
}

export function getWorkbenchTasks(limit = 20): Promise<PageResult<EvidenceFeedItem>> {
  return getFeed(`/api/workbench/tasks?limit=${limit}`)
}

export function getRadarEvidence(thesisId: string, filters: { status?: string; direction?: string } = {}): Promise<PageResult<EvidenceFeedItem>> {
  const params = new URLSearchParams({ thesis_id: thesisId, limit: '50' })
  if (filters.status) params.append('status', filters.status)
  if (filters.direction) params.set('direction', filters.direction)
  return getFeed(`/api/radar/evidence?${params}`)
}

export function getThesisEvidenceFeed(thesisId: string): Promise<PageResult<EvidenceFeedItem>> {
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

export async function createDraft(payload: { securityId: string; view: string }): Promise<ThesisDetail> {
  return toThesis(await request<Record<string, unknown>>('/api/theses/drafts', { method: 'POST', body: JSON.stringify({ security_id: payload.securityId, view: payload.view }) }))
}

export async function publishThesis(thesisId: string, payload: { direction: string; horizonEndOn: string; nextReviewAt: string }): Promise<ThesisDetail> {
  return toThesis(await request<Record<string, unknown>>(`/api/theses/${thesisId}/publish`, { method: 'POST', body: JSON.stringify({ direction: payload.direction, horizon_end_on: payload.horizonEndOn, next_review_at: payload.nextReviewAt }) }))
}

export async function getAdjudications(): Promise<Array<Record<string, unknown>>> {
  if (useMock) return []
  const page = await request<{ items: Array<Record<string, unknown>> }>('/api/reviews/adjudications')
  return page.items
}
