import {
  demoAssetHits, demoAudit, demoEvidence, demoEvidenceFeeds, demoIngestionReviews,
  demoMetrics, demoProcessingJobs, demoRelations, demoReviewTasks, demoSecurities,
  demoSuggestions, demoTheses, demoThesis, demoTrends, demoWorkbench,
} from './mocks'
import type {
  AuditItem, ConfirmationState, Direction, EvidenceDetail, EvidenceFeedItem, EvidenceRetrievalTrace, FullDocument, LogicChangeDigestDetail,
  Adjudication, DocumentSegment, IngestionReview, JobAccepted, JobStatus, PageResult, ProcessingJob, Relation,
  ReviewTask, ReviewDraftCandidate, Security, Strength, Suggestion, ThesisDetail, Trend, ValidationItem, WorkbenchData,
  MetricDefinition, MetricMapping, PublishReadiness, ThesisSummary,
  AssetInventory, AssetSearchHit,
  DataCenterDocument, DataCenterDocumentDetail, DataCenterDocumentPage, DataCenterOverview,
  DataCenterRevision, DataCenterRun, DataCenterSource,
  ThesisRevision, ThesisRevisionDiff,
  QuantBacktestRequest, QuantBacktestRun,
  PortfolioBacktestRequest, PortfolioBacktestRun, QuantCatalog, QuantFactorDefinition, QuantMarketDataset, QuantMarketDatasetDetail, QuantModelTemplate,
  QuantSignalSet, QuantSignalSetDetail,
  CompanyMetricCenter,
  GoldQualityReport,
  GlobalSearchResult, KnowledgeAnswer, KnowledgeAnswerRequest,
  CoverageUniverseCompany,
  CoverageUniverseIndustry,
  MaintainedCoverageIndustry,
  InvestodayCollectionRun, InvestodayCollectionStatus,
} from './types'

export const useMock = import.meta.env.VITE_USE_MOCK === 'true'

export interface AuthUser {
  userId: string
  teams: string[]
  mustChangePassword: boolean
}

export interface AuthSession {
  accessToken: string
  expiresIn: number
  user: AuthUser
}

export interface AuthConfig {
  loginRequired: boolean
  passwordChangeSupported: boolean
  globalSearchEnabled: boolean
  knowledgeQaEnabled: boolean
  retrospectiveCenterEnabled: boolean
  retrospectiveAiDraftEnabled: boolean
  quantResearchEnabled: boolean
}

const accessTokenKey = 'ai-investment-copilot.access-token'

export function getAccessToken() {
  return sessionStorage.getItem(accessTokenKey)
}

export function setAccessToken(token: string) {
  sessionStorage.setItem(accessTokenKey, token)
}

export function clearAccessToken() {
  sessionStorage.removeItem(accessTokenKey)
}

// 受控演示也保留最小交互状态，避免确认、复核、重放等操作提交后又恢复成初始画面。
const mockRelationStates = new Map<string, ConfirmationState>()
const mockResolvedIngestion = new Set<string>()
const mockResolvedReviews = new Set<string>()
const mockReplayedJobs = new Set<string>()

function toDirection(value: unknown): Direction {
  return value === '支持' ? 'support' : value === '冲突' ? 'conflict' : 'neutral'
}

function toThemeDirection(value: unknown): EvidenceFeedItem['themeDirection'] {
  return value === 'divergent' || value === 'mixed' ? value : value === 'support' || value === 'conflict' || value === 'neutral' ? value : undefined
}

function toStrength(value: unknown): Strength {
  return value === '高' ? 'high' : value === '低' ? 'low' : 'medium'
}

function toStatus(value: unknown): ConfirmationState {
  return value === '已确认' ? 'confirmed' : value === '已驳回' ? 'rejected' : value === '已解除' ? 'deactivated' : 'pending'
}

/** 浏览器只走 Vite 代理；身份头由开发代理或生产网关注入。 */
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData
  const token = getAccessToken()
  const response = await fetch(path, {
    ...init,
    headers: {
      ...(isForm ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  })
  if (response.status === 401) {
    if (token) {
      clearAccessToken()
      window.dispatchEvent(new Event('copilot:unauthorized'))
    }
    const detail = await response.json().catch(() => null) as { detail?: unknown } | null
    throw new Error(typeof detail?.detail === 'string' ? detail.detail : '登录已失效，请重新登录。')
  }
  if (response.status === 403) throw new Error('当前账户可查看该对象，但没有此操作权限。')
  if (response.status === 404) throw new Error('对象不存在、已解除关联或无访问权限。')
  if (!response.ok) {
    const detail = await response.json().catch(() => null) as { detail?: unknown } | null
    const structured = detail?.detail && typeof detail.detail === 'object' ? detail.detail as { message?: unknown } : null
    throw new Error(typeof detail?.detail === 'string' ? detail.detail : typeof structured?.message === 'string' ? structured.message : `请求失败（${response.status}）`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function requestBlob(path: string): Promise<Blob> {
  const token = getAccessToken()
  const response = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  })
  if (response.status === 401) {
    if (token) {
      clearAccessToken()
      window.dispatchEvent(new Event('copilot:unauthorized'))
    }
    throw new Error('登录已失效，请重新登录。')
  }
  if (response.status === 403) throw new Error('当前账户没有访问该原件的权限。')
  if (response.status === 404) throw new Error('原件不存在或无访问权限。')
  if (!response.ok) {
    const detail = await response.json().catch(() => null) as { detail?: unknown } | null
    throw new Error(typeof detail?.detail === 'string' ? detail.detail : `原件请求失败（${response.status}）`)
  }
  return response.blob()
}

export async function globalSearch(query: string, signal?: AbortSignal): Promise<GlobalSearchResult> {
  if (useMock) return {
    query,
    requestId: 'SEARCH-MOCK',
    groups: [
      { type: 'security', items: [{ id: demoThesis.securityId, title: '阳光电源', subtitle: `${demoThesis.securityId} · 电力设备`, matchKind: 'name', target: { kind: 'thesis', id: demoThesis.thesisId } }] },
      { type: 'thesis', items: [{ id: demoThesis.thesisId, title: demoThesis.title, subtitle: `阳光电源 · ${demoThesis.status}`, excerpt: demoThesis.coreView, matchKind: 'title', target: { kind: 'thesis', id: demoThesis.thesisId } }] },
      { type: 'document', items: demoAssetHits.slice(0, 3).map((item) => ({ id: item.locator, title: item.documentId, subtitle: item.contentStatus, excerpt: item.content, matchKind: 'hybrid', target: { kind: 'document_segment' as const, id: item.locator }, contentStatus: item.contentStatus, retrievalMode: item.retrievalMode })) },
    ],
  }
  const item = await request<{
    query: string
    request_id: string
    groups: Array<{ type: GlobalSearchResult['groups'][number]['type']; items: Array<Record<string, unknown>> }>
  }>(`/api/search?q=${encodeURIComponent(query)}&limit_per_type=5`, { signal })
  return {
    query: item.query,
    requestId: item.request_id,
    groups: item.groups.map((group) => ({
      type: group.type,
      items: group.items.map((raw) => {
        const target = raw.target as Record<string, unknown>
        return {
          id: String(raw.id), title: String(raw.title), subtitle: String(raw.subtitle ?? ''),
          excerpt: raw.excerpt ? String(raw.excerpt) : undefined, matchKind: String(raw.match_kind),
          target: { kind: String(target.kind) as GlobalSearchResult['groups'][number]['items'][number]['target']['kind'], id: String(target.id) },
          contentStatus: raw.content_status ? String(raw.content_status) : undefined,
          contentKind: raw.content_kind ? String(raw.content_kind) : undefined,
          retrievalMode: raw.retrieval_mode ? String(raw.retrieval_mode) : undefined,
          publishedAt: raw.published_at ? String(raw.published_at) : undefined,
        }
      }),
    })),
  }
}

export async function askKnowledge(requestValue: KnowledgeAnswerRequest, signal?: AbortSignal): Promise<KnowledgeAnswer> {
  if (useMock) {
    const citation = demoAssetHits[0]
    return {
      answerId: 'ANS-00000000000000000000000000000000', answerStatus: 'supported', aiStatus: '候选',
      answer: `根据当前可回查资料，${citation.content} [S1]`, inferences: [],
      citations: [{ ref: 'S1', locator: citation.locator, documentId: citation.documentId, title: citation.documentId, excerpt: citation.content, contentStatus: citation.contentStatus, contentKind: 'paragraph', retrievalMode: citation.retrievalMode ?? 'hybrid' }],
      modelVersion: 'mock', promptVersion: 'knowledge-answer-v2-intent-routed-grounding', retrievalVersion: 'mock-hybrid', generatedAt: new Date().toISOString(), requestId: 'QA-MOCK',
    }
  }
  const item = await request<Record<string, unknown>>('/api/assistant/answers', {
    method: 'POST', signal,
    body: JSON.stringify({
      question: requestValue.question,
      context: {
        thesis_id: requestValue.context?.thesisId,
        security_id: requestValue.context?.securityId,
        as_of: requestValue.context?.asOf,
      },
      history: requestValue.history ?? [],
    }),
  })
  return {
    answerId: String(item.answer_id), answerStatus: item.answer_status as KnowledgeAnswer['answerStatus'], aiStatus: String(item.ai_status),
    answer: String(item.answer), inferences: (item.inferences ?? []) as string[],
    citations: ((item.citations ?? []) as Array<Record<string, unknown>>).map((citation) => ({
      ref: String(citation.ref), locator: String(citation.locator), documentId: String(citation.document_id),
      title: String(citation.title), excerpt: String(citation.excerpt),
      publishedAt: citation.published_at ? String(citation.published_at) : undefined,
      contentStatus: String(citation.content_status), contentKind: String(citation.content_kind), retrievalMode: String(citation.retrieval_mode),
    })),
    modelVersion: String(item.model_version), promptVersion: String(item.prompt_version), retrievalVersion: String(item.retrieval_version),
    graphSnapshotId: item.graph_snapshot_id ? String(item.graph_snapshot_id) : undefined,
    generatedAt: String(item.generated_at), requestId: String(item.request_id),
  }
}

export async function submitAnswerFeedback(answerId: string, value: 'helpful' | 'not_helpful') {
  if (useMock) return
  await request<void>(`/api/assistant/answers/${encodeURIComponent(answerId)}/feedback`, {
    method: 'POST', body: JSON.stringify({ value }),
  })
}

function toAuthUser(value: { user_id: string; teams: string[]; must_change_password: boolean }): AuthUser {
  return {
    userId: value.user_id,
    teams: value.teams,
    mustChangePassword: value.must_change_password,
  }
}

export async function getAuthConfig(): Promise<AuthConfig> {
  if (useMock) return { loginRequired: false, passwordChangeSupported: false, globalSearchEnabled: true, knowledgeQaEnabled: true, retrospectiveCenterEnabled: true, retrospectiveAiDraftEnabled: false, quantResearchEnabled: true }
  const value = await request<{ login_required: boolean; password_change_supported: boolean; global_search_enabled: boolean; knowledge_qa_enabled: boolean; retrospective_center_enabled: boolean; retrospective_ai_draft_enabled: boolean; quant_research_enabled: boolean }>('/api/auth/config')
  return {
    loginRequired: value.login_required,
    passwordChangeSupported: value.password_change_supported,
    globalSearchEnabled: value.global_search_enabled,
    knowledgeQaEnabled: value.knowledge_qa_enabled,
    retrospectiveCenterEnabled: value.retrospective_center_enabled,
    retrospectiveAiDraftEnabled: value.retrospective_ai_draft_enabled,
    quantResearchEnabled: value.quant_research_enabled,
  }
}

export async function getCurrentUser(): Promise<AuthUser> {
  if (useMock) return { userId: 'analyst-mvp', teams: ['equity-research'], mustChangePassword: false }
  const value = await request<{ user_id: string; teams: string[]; must_change_password: boolean }>('/api/auth/me')
  return toAuthUser(value)
}

export async function login(userId: string, password: string): Promise<AuthSession> {
  if (useMock) return {
    accessToken: 'mock-session',
    expiresIn: 8 * 60 * 60,
    user: { userId: userId || 'analyst-mvp', teams: ['equity-research'], mustChangePassword: false },
  }
  const value = await request<{
    access_token: string
    expires_in: number
    user: { user_id: string; teams: string[]; must_change_password: boolean }
  }>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, password }),
  })
  return { accessToken: value.access_token, expiresIn: value.expires_in, user: toAuthUser(value.user) }
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<AuthSession> {
  if (useMock) return {
    accessToken: 'mock-session',
    expiresIn: 8 * 60 * 60,
    user: { userId: 'analyst-mvp', teams: ['equity-research'], mustChangePassword: false },
  }
  const value = await request<{
    access_token: string
    expires_in: number
    user: { user_id: string; teams: string[]; must_change_password: boolean }
  }>('/api/auth/change-password', {
    method: 'POST',
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  })
  return { accessToken: value.access_token, expiresIn: value.expires_in, user: toAuthUser(value.user) }
}

function toThesis(item: Record<string, unknown>): ThesisDetail {
  return {
    thesisId: String(item.thesis_id), securityId: String(item.security_id),
    title: String(item.title), owner: String(item.owner), status: String(item.status),
    direction: String(item.direction), coreView: String(item.core_view), version: Number(item.version),
    thesisKind: String(item.thesis_kind ?? 'canonical'),
    thesisSeriesId: item.thesis_series_id ? String(item.thesis_series_id) : undefined,
    establishedOn: String(item.established_on),
    horizonEndOn: item.horizon_end_on ? String(item.horizon_end_on) : undefined,
    nextReviewAt: item.next_review_at ? String(item.next_review_at) : undefined,
    investmentRating: item.investment_rating ? String(item.investment_rating) : undefined,
    targetPrice: item.target_price == null ? undefined : String(item.target_price),
    observationPeriod: item.observation_period ? String(item.observation_period) : undefined,
    hypotheses: ((item.hypotheses ?? []) as Array<Record<string, unknown>>).map((h) => ({
      hypothesisId: String(h.hypothesis_id), statement: String(h.statement),
      hypothesisType: String(h.hypothesis_type), importance: String(h.importance), status: String(h.status),
      observationWindow: h.observation_window ? String(h.observation_window) : undefined,
      invalidationRule: h.invalidation_rule ? String(h.invalidation_rule) : undefined,
      metricSuggestions: (h.metric_suggestions ?? []) as Array<Record<string, unknown>>,
      causalLevel: h.causal_level ? String(h.causal_level) : undefined,
      logicDimension: h.logic_dimension ? String(h.logic_dimension) : undefined,
      qualityWarning: h.quality_warning ? String(h.quality_warning) : undefined,
      mappings: ((h.mappings ?? []) as Array<Record<string, unknown>>).map(toMapping),
    })),
    catalystSuggestions: (item.catalyst_suggestions ?? []) as Array<Record<string, unknown>>,
    riskSuggestions: (item.risk_suggestions ?? []) as Array<Record<string, unknown>>,
    invalidationSuggestions: (item.invalidation_suggestions ?? []) as Array<Record<string, unknown>>,
  }
}

function toMapping(item: Record<string, unknown>): MetricMapping {
  return {
    mappingId: String(item.mapping_id), metricId: String(item.metric_id), metricName: item.metric_name ? String(item.metric_name) : undefined, metricVersion: String(item.metric_version),
    expectedDirection: String(item.expected_direction), expectedValue: item.expected_value == null ? undefined : String(item.expected_value),
    expectedLower: item.expected_lower == null ? undefined : String(item.expected_lower), expectedUpper: item.expected_upper == null ? undefined : String(item.expected_upper),
    invalidationThreshold: item.invalidation_threshold == null ? undefined : String(item.invalidation_threshold),
    invalidationConsecutivePeriods: item.invalidation_consecutive_periods == null ? undefined : Number(item.invalidation_consecutive_periods),
    expectationSource: String(item.expectation_source), confirmationStatus: String(item.confirmation_status),
  }
}

function toFeedItem(item: Record<string, unknown>): EvidenceFeedItem {
  return {
    evidenceId: String(item.evidence_id), relationId: String(item.relation_id),
    securityId: String(item.security_id), securityName: String(item.security_name),
    thesisId: String(item.thesis_id), thesisTitle: String(item.thesis_title), thesisCoreView: String(item.thesis_core_view ?? item.thesis_title),
    hypothesisId: String(item.hypothesis_id), hypothesisStatement: String(item.hypothesis_statement),
    sourceDocumentId: String(item.source_document_id ?? ''), sourceDocumentTitle: String(item.source_document_title), factExcerpt: String(item.fact_excerpt),
    evidenceLocator: item.evidence_locator ? String(item.evidence_locator) : undefined,
    disclosedAt: String(item.disclosed_at), ingestedAt: String(item.ingested_at ?? item.disclosed_at), occurredAt: item.occurred_at ? String(item.occurred_at) : undefined,
    sourceUrl: String(item.source_url), direction: toDirection(item.direction),
    strength: toStrength(item.strength), aiConfidence: Number(item.ai_confidence ?? 0),
    confirmationStatus: toStatus(item.confirmation_status), priority: item.priority as EvidenceFeedItem['priority'],
    canManage: Boolean(item.can_manage), validationItems: (item.validation_items as Array<Record<string, unknown>>).map((v) => ({
      code: String(v.code), label: String(v.label), status: v.status as ValidationItem['status'], message: String(v.message),
    })),
    aggregationSummary: item.aggregation_summary ? String(item.aggregation_summary) : undefined,
    atomicEvidenceCount: Number(item.atomic_evidence_count ?? 1),
    sourceDocumentCount: Number(item.source_document_count ?? 1),
    supportEvidenceCount: Number(item.support_evidence_count ?? 0),
    conflictEvidenceCount: Number(item.conflict_evidence_count ?? 0),
    affectedHypothesisCount: Number(item.affected_hypothesis_count ?? 1),
    secondaryHypotheses: Array.isArray(item.secondary_hypotheses) ? item.secondary_hypotheses.map(String) : [],
    themeImpacts: Array.isArray(item.theme_impacts) ? item.theme_impacts.map((impact) => {
      const value = impact as Record<string, unknown>
      return {
        hypothesisId: String(value.hypothesis_id), hypothesisStatement: String(value.hypothesis_statement),
        direction: toDirection(value.direction), evidenceCount: Number(value.evidence_count ?? 1),
        hasConflictingEvidence: Boolean(value.has_conflicting_evidence),
      }
    }) : [],
    themeDirection: toThemeDirection(item.theme_direction),
  }
}

function toPage<T>(page: { items: T[]; page: { total: number; limit: number; offset: number } }): PageResult<T> {
  return { items: page.items, total: page.page.total, limit: page.page.limit, offset: page.page.offset }
}

export async function getEvidence(evidenceId: string): Promise<EvidenceDetail> {
  if (useMock) return { ...demoEvidence, evidenceId, ingestedAt: demoEvidence.disclosedAt, aiStatus: '候选', promptVersion: 'demo', sourceDocumentId: 'DOC-DEMO', evidenceLocator: 'DOC-DEMO#paragraph-1' }
  const item = await request<Record<string, unknown>>(`/api/evidence/${evidenceId}`)
  return {
    evidenceId: String(item.evidence_id), securityId: String(item.security_id),
    factExcerpt: String(item.fact_excerpt), sourceDocumentTitle: String(item.source_document_title),
    disclosedAt: String(item.disclosed_at), occurredAt: item.occurred_at ? String(item.occurred_at) : undefined,
    ingestedAt: String(item.ingested_at),
    sourceUrl: String(item.source_url), direction: toDirection(item.direction), strength: toStrength(item.strength),
    aiConfidence: Number(item.ai_confidence ?? 0), aiStatus: String(item.ai_status ?? '候选'),
    modelVersion: String(item.model_version ?? '-'), promptVersion: String(item.prompt_version ?? '-'),
    confirmationStatus: toStatus(item.confirmation_status), sourceDocumentId: String(item.source_document_id),
    evidenceLocator: String(item.evidence_locator),
  }
}

export async function getLogicChangeDigest(securityId: string, thesisId: string, businessDate?: string): Promise<LogicChangeDigestDetail> {
  const query = businessDate ? `?business_day=${encodeURIComponent(businessDate)}` : ''
  const item = await request<Record<string, unknown>>(`/api/updates/logic-changes/${encodeURIComponent(securityId)}/${encodeURIComponent(thesisId)}${query}`)
  const direction = item.overall_direction === '支持' ? 'support' : item.overall_direction === '冲突' ? 'conflict' : item.overall_direction === '混合' ? 'mixed' : 'neutral'
  return {
    digestId: String(item.digest_id), securityId: String(item.security_id), securityName: String(item.security_name),
    thesisId: String(item.thesis_id), thesisTitle: String(item.thesis_title), thesisCoreView: String(item.thesis_core_view),
    businessDate: String(item.business_date), overallDirection: direction, summary: String(item.summary),
    confirmationStatus: toStatus(item.confirmation_status), candidateCount: Number(item.candidate_count),
    sourceDocumentCount: Number(item.source_document_count), confidence: item.confidence == null ? undefined : Number(item.confidence),
    openQuestions: Array.isArray(item.open_questions) ? item.open_questions.map(String) : [],
    modelVersion: item.model_version ? String(item.model_version) : undefined,
    promptVersion: item.prompt_version ? String(item.prompt_version) : undefined,
    hypothesisImpacts: Array.isArray(item.hypothesis_impacts) ? item.hypothesis_impacts.map((raw) => {
      const value = raw as Record<string, unknown>
      return {
        hypothesisId: String(value.hypothesis_id), statement: String(value.statement), direction: String(value.direction),
        strength: value.strength === '弱' || value.strength === '中' || value.strength === '强' ? value.strength : undefined,
        strengthReason: value.strength_reason ? String(value.strength_reason) : undefined,
        rationale: String(value.rationale), businessImpact: value.business_impact ? String(value.business_impact) : undefined,
        indicatorOutlook: value.indicator_outlook ? String(value.indicator_outlook) : undefined,
        impactLayer: value.impact_layer ? String(value.impact_layer) : undefined,
        directness: value.directness ? String(value.directness) : undefined,
        transmissionStatus: value.transmission_status ? String(value.transmission_status) : undefined,
        hypothesisEffect: value.hypothesis_effect ? String(value.hypothesis_effect) : undefined,
        presentation: value.presentation === '单一路径' || value.presentation === '双向分歧' || value.presentation === '背景信号' || value.presentation === '证据不足' ? value.presentation : undefined,
        paths: Array.isArray(value.paths) ? value.paths.filter((path): path is Record<string, unknown> => Boolean(path) && typeof path === 'object').map((path) => ({
          direction: String(path.direction ?? '中性'), label: String(path.label ?? '待核验传导路径'),
          mechanism: String(path.mechanism ?? '尚未形成可解释传导。'),
          evidenceIds: Array.isArray(path.evidence_ids) ? path.evidence_ids.map(String) : [],
        })) : [],
        relatedMetrics: Array.isArray(value.related_metrics) ? value.related_metrics.map(String) : [],
        evidenceIds: Array.isArray(value.evidence_ids) ? value.evidence_ids.map(String) : [],
      }
    }) : [],
    sourceDocuments: Array.isArray(item.source_documents) ? item.source_documents.map((raw) => {
      const value = raw as Record<string, unknown>
      return {
        documentId: String(value.document_id), title: String(value.title), docType: value.doc_type ? String(value.doc_type) : undefined,
        publishedAt: value.published_at ? String(value.published_at) : undefined, sourceUrl: value.source_url ? String(value.source_url) : undefined,
        facts: Array.isArray(value.facts) ? value.facts.map((factRaw) => {
          const fact = factRaw as Record<string, unknown>
          return { evidenceId: String(fact.evidence_id), factExcerpt: String(fact.fact_excerpt), evidenceLocator: String(fact.evidence_locator), hypothesisIds: Array.isArray(fact.hypothesis_ids) ? fact.hypothesis_ids.map(String) : [], directions: Array.isArray(fact.directions) ? fact.directions.map(String) : [], isKeyCitation: Boolean(fact.is_key_citation) }
        }) : [],
      }
    }) : [],
  }
}

export async function getEvidenceRetrievalTrace(evidenceId: string): Promise<EvidenceRetrievalTrace> {
  if (useMock) return {
    available: true, retrievalMode: 'text+graph', retrievalVersion: 'investment-graph-rag-v2-layered',
    locator: `DOC-SG-2025-AR#paragraph-184`, finalScore: .887,
    scoreComponents: { text: .742, graph: .965 },
    graphPaths: [{ score: .965, nodeIds: ['thesis:THS-SG-001', 'hypothesis:HYP-SG-001', 'variable:margin', 'metric:MET-GM-001', 'fact:FACT-SG-001', 'document:DOC-SG-2025-AR'], nodeKinds: ['投资逻辑', '投资假设', '业务变量', '指标', '事实', '文档'], layers: ['投资研究层', '投资研究层', '领域语义层', '领域语义层', '事实观测层', '原始证据层'], relations: ['包含假设', '依赖变量', '由指标衡量', '观测指标', '披露于'], provenanceLocators: ['DOC-SG-2025-AR#paragraph-184'], explanation: '盈利韧性逻辑 → 海外毛利率假设 → 盈利质量变量 → 海外业务毛利率 → 年报事实 → 原文段落' }],
    graphSnapshot: { snapshotId: 'graph-snapshot:demo-final-v3', schemaVersion: 'investment-knowledge-layers-v2', builderVersion: 'layered-corpus-builder-v1', vocabularyVersion: 'metric-aliases-v1', builtAt: '2026-08-26T08:00:00Z', asOf: '2026-08-26T08:00:00Z', thesisIds: ['THS-SG-001'], securityIds: ['300274'], layers: [{ layer: '投资研究层', nodeCount: 7, contentHash: 'demo-research' }, { layer: '领域语义层', nodeCount: 9, contentHash: 'demo-semantic' }, { layer: '事实观测层', nodeCount: 16, contentHash: 'demo-observation' }, { layer: '原始证据层', nodeCount: 24, contentHash: 'demo-source' }] },
  }
  const item = await request<Record<string, unknown>>(`/api/evidence/${evidenceId}/retrieval-trace`)
  const score = (item.score_components ?? {}) as Record<string, unknown>
  const snapshot = item.graph_snapshot as Record<string, unknown> | null
  return {
    available: Boolean(item.available), retrievalMode: String(item.retrieval_mode),
    retrievalVersion: String(item.retrieval_version), locator: String(item.locator),
    finalScore: Number(item.final_score ?? 0),
    scoreComponents: { text: Number(score.text ?? 0), graph: Number(score.graph ?? 0) },
    graphPaths: ((item.graph_paths ?? []) as Array<Record<string, unknown>>).map((path) => ({
      score: Number(path.score ?? 0), nodeIds: (path.node_ids ?? []) as string[],
      nodeKinds: (path.node_kinds ?? []) as string[], layers: (path.layers ?? []) as string[],
      relations: (path.relations ?? []) as string[],
      provenanceLocators: (path.provenance_locators ?? []) as string[],
      explanation: String(path.explanation ?? ''),
    })),
    graphSnapshot: snapshot ? {
      snapshotId: String(snapshot.snapshot_id), schemaVersion: String(snapshot.schema_version),
      builderVersion: String(snapshot.builder_version), vocabularyVersion: String(snapshot.vocabulary_version),
      builtAt: String(snapshot.built_at), asOf: snapshot.as_of ? String(snapshot.as_of) : undefined,
      thesisIds: (snapshot.thesis_ids ?? []) as string[], securityIds: (snapshot.security_ids ?? []) as string[],
      layers: ((snapshot.layers ?? []) as Array<Record<string, unknown>>).map((layer) => ({
        layer: String(layer.layer), nodeCount: Number(layer.node_count ?? 0), contentHash: String(layer.content_hash),
      })),
    } : undefined,
  }
}

export async function getRelations(evidenceId: string): Promise<Relation[]> {
  if (useMock) return demoRelations.map((item) => {
    const relationId = evidenceId === 'EVD-SG-001' ? item.relationId : `${item.relationId}-${evidenceId}`
    const status = mockRelationStates.get(relationId) ?? item.status
    return { ...item, relationId, status, reviewedBy: status !== 'pending' ? 'analyst-mvp' : undefined, reviewedAt: status !== 'pending' ? new Date().toISOString() : undefined }
  })
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
  if (useMock) return demoTheses.find((item) => item.thesisId === thesisId) ?? demoThesis
  return toThesis(await request<Record<string, unknown>>(`/api/theses/${thesisId}`))
}

export async function listTheses(securityId?: string, manageable = false, includeSnapshots = false, limit = 50): Promise<ThesisDetail[]> {
  if (useMock) return demoTheses.filter((item) => !securityId || item.securityId === securityId).map((item) => ({ ...item, owner: manageable ? 'analyst-mvp' : item.owner }))
  const page = await request<{ items: Array<Record<string, unknown>> }>(`/api/theses?limit=${limit}${securityId ? `&security_id=${encodeURIComponent(securityId)}` : ''}${manageable ? '&manageable=true' : ''}${includeSnapshots ? '&include_snapshots=true' : ''}`)
  return page.items.map(toThesis)
}

export async function listThesisSummaries(): Promise<ThesisSummary[]> {
  if (useMock) return demoTheses
  try {
    const page = await request<{ items: Array<Record<string, unknown>> }>('/api/theses/summaries?limit=100')
    return page.items.map((item) => ({
      thesisId: String(item.thesis_id),
      securityId: String(item.security_id),
      title: String(item.title),
      status: String(item.status),
      owner: String(item.owner),
      direction: String(item.direction),
      thesisKind: String(item.thesis_kind ?? 'canonical'),
      thesisSeriesId: item.thesis_series_id ? String(item.thesis_series_id) : undefined,
    }))
  } catch {
    // 开发后端尚未重启时保持兼容；重启后会自动使用轻量摘要接口。
    return listTheses(undefined, false, false, 100)
  }
}

export async function listSecurities(): Promise<Security[]> {
  if (useMock) return demoSecurities
  const items = await request<Array<Record<string, unknown>>>('/api/securities?limit=200')
  return items.map((item) => ({
    securityId: String(item.security_id), name: String(item.name),
    ticker: item.ticker ? String(item.ticker) : undefined,
    industry: item.industry ? String(item.industry) : undefined,
  }))
}

/**
 * 将数据源的正式行业分类映射为工作台使用的研究板块。
 *
 * 原始行业分类仍保留在 company.industry，用于公司名称下方的详细说明；
 * 这里仅负责导航分组，避免把“制造业-...”这类完整路径直接作为板块名称。
 */
function researchSector(industry?: string): string {
  const value = industry?.trim() ?? ''
  if (!value) return '未分类'
  if (value.includes('新能源汽车')) return '新能源汽车'
  if (value.includes('光伏') || value.includes('储能') || value.includes('电力设备') || value.includes('电气机械')) return '新能源与储能'
  if (value.includes('医药') || value.includes('医疗')) return '医药'
  if (value.includes('半导体') || value.includes('芯片')) return '芯片半导体'
  if (value.includes('汽车')) return '汽车'
  if (value.includes('酒') || value.includes('饮料') || value.includes('食品') || value.includes('消费')) return '大消费'
  if (value.includes('软件') || value.includes('计算机') || value.includes('通信') || value.includes('电子设备')) return '电子信息'
  return value.split('-')[0]?.trim() || value
}

/** 证券主数据中的维护公司，按研究板块分组，并合并已有投资逻辑状态。 */
export async function getMaintainedCoverage(): Promise<MaintainedCoverageIndustry[]> {
  const sectors = await getCoverageUniverse()
  return sectors
    .map((sector) => ({
      name: sector.name,
      companies: sector.companies
        .filter((company) => company.status !== '暂停覆盖')
        .map((company) => ({
          securityId: company.securityId,
          name: company.name,
          ticker: company.ticker,
          industry: company.industry,
          thesisId: company.thesisId,
          thesisTitle: company.thesisTitle,
          thesisStatus: company.thesisStatus ?? '未建立',
          hypothesisCount: company.hypothesisCount,
          configuredMetricCount: company.configuredMetricCount,
          updatedAt: company.updatedAt ?? '',
        })),
    }))
    .filter((sector) => sector.companies.length > 0)
}

/** 覆盖总览使用证券主数据作为全集，并按研究板块分组。 */
export async function getCoverageUniverse(query?: string): Promise<CoverageUniverseIndustry[]> {
  if (!useMock) {
    try {
      const items = await request<Array<Record<string, unknown>>>(`/api/coverage${query?.trim() ? `?query=${encodeURIComponent(query.trim())}` : ''}`)
      return items.map((sector) => ({
        sectorId: String(sector.sector_id),
        name: String(sector.name),
        code: sector.code ? String(sector.code) : undefined,
        description: sector.description ? String(sector.description) : undefined,
        status: sector.status ? String(sector.status) : undefined,
        companies: ((sector.companies ?? []) as Array<Record<string, unknown>>).map((company) => ({
          coverageCompanyId: company.coverage_company_id ? String(company.coverage_company_id) : undefined,
          sectorId: String(company.sector_id ?? sector.sector_id),
          securityId: String(company.security_id),
          name: String(company.name),
          ticker: company.ticker ? String(company.ticker) : undefined,
          industry: company.industry ? String(company.industry) : undefined,
          market: company.market ? String(company.market) : undefined,
          thesisId: company.thesis_id ? String(company.thesis_id) : undefined,
          thesisTitle: company.thesis_title ? String(company.thesis_title) : undefined,
          thesisStatus: company.thesis_status ? String(company.thesis_status) : undefined,
          thesisCount: Number(company.thesis_count ?? (company.thesis_id ? 1 : 0)),
          owner: company.owner ? String(company.owner) : undefined,
          hypothesisCount: Number(company.hypothesis_count ?? 0),
          configuredMetricCount: Number(company.configured_metric_count ?? 0),
          updatedAt: company.updated_at ? String(company.updated_at) : undefined,
          status: company.status ? String(company.status) : undefined,
        })),
      }))
    } catch {
      // 旧数据库可能尚未创建覆盖目录表，回退到证券主数据的只读视图。
    }
  }
  // /api/theses 的单页上限为 100；使用合法上限，避免行业总览因 422 无法加载。
  const [securities, theses] = await Promise.all([listSecurities(), listTheses(undefined, false, false, 100)])
  const thesisBySecurity = new Map(theses.map((thesis) => [thesis.securityId, thesis]))
  const groups = new Map<string, CoverageUniverseIndustry>()
  for (const security of securities) {
    const thesis = thesisBySecurity.get(security.securityId)
    const industry = researchSector(security.industry)
    const company: CoverageUniverseIndustry['companies'][number] = {
      securityId: security.securityId,
      name: security.name,
      ticker: security.ticker,
      industry: security.industry,
      thesisId: thesis?.thesisId,
      thesisTitle: thesis?.title,
      thesisStatus: thesis?.status,
      thesisCount: thesis ? 1 : 0,
      owner: thesis?.owner,
      hypothesisCount: thesis?.hypotheses.length ?? 0,
      configuredMetricCount: thesis?.hypotheses.reduce((total, item) => total + item.mappings.length, 0) ?? 0,
      updatedAt: thesis?.establishedOn,
    }
    const group = groups.get(industry) ?? { name: industry, companies: [] }
    group.companies.push(company)
    groups.set(industry, group)
  }
  const normalizedQuery = query?.trim().toLocaleLowerCase('zh-CN') ?? ''
  return [...groups.values()]
    .filter((group) => !normalizedQuery || group.name.toLocaleLowerCase('zh-CN').includes(normalizedQuery))
    .map((group) => ({ ...group, companies: group.companies.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN')) }))
    .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
}

export async function createCoverageSector(payload: { name: string; code?: string; description?: string }): Promise<CoverageUniverseIndustry> {
  const item = await request<Record<string, unknown>>('/api/coverage/sectors', {
    method: 'POST',
    body: JSON.stringify({ name: payload.name, code: payload.code || null, description: payload.description || null }),
  })
  return {
    sectorId: String(item.sector_id), name: String(item.name), code: item.code ? String(item.code) : undefined,
    description: item.description ? String(item.description) : undefined, status: String(item.status ?? 'active'), companies: [],
  }
}

export async function updateCoverageSector(sectorId: string, payload: { name: string }): Promise<CoverageUniverseIndustry> {
  const item = await request<Record<string, unknown>>(`/api/coverage/sectors/${encodeURIComponent(sectorId)}`, {
    method: 'PATCH', body: JSON.stringify({ name: payload.name }),
  })
  return {
    sectorId: String(item.sector_id), name: String(item.name), code: item.code ? String(item.code) : undefined,
    description: item.description ? String(item.description) : undefined, status: String(item.status ?? 'active'), companies: [],
  }
}

export async function createCoverageCompany(sectorId: string, payload: { securityId?: string; name?: string; ticker?: string; industry?: string; market?: string; owner?: string }): Promise<CoverageUniverseCompany> {
  const item = await request<Record<string, unknown>>(`/api/coverage/sectors/${encodeURIComponent(sectorId)}/companies`, {
    method: 'POST',
    body: JSON.stringify({ security_id: payload.securityId || null, name: payload.name || null, ticker: payload.ticker || null, industry: payload.industry || null, market: payload.market || null, owner: payload.owner || null }),
  })
  return {
    coverageCompanyId: String(item.coverage_company_id), sectorId: String(item.sector_id), securityId: String(item.security_id), name: String(item.name),
    ticker: item.ticker ? String(item.ticker) : undefined, industry: item.industry ? String(item.industry) : undefined,
    market: item.market ? String(item.market) : undefined, owner: String(item.owner ?? '待分配'), status: String(item.status ?? '待建档'),
    thesisCount: Number(item.thesis_count ?? 0),
    hypothesisCount: Number(item.hypothesis_count ?? 0), configuredMetricCount: Number(item.configured_metric_count ?? 0),
    updatedAt: item.updated_at ? String(item.updated_at) : undefined,
  }
}

export async function updateCoverageCompany(coverageCompanyId: string, payload: { status?: string; owner?: string }): Promise<CoverageUniverseCompany> {
  const item = await request<Record<string, unknown>>(`/api/coverage/companies/${encodeURIComponent(coverageCompanyId)}`, {
    method: 'PATCH', body: JSON.stringify({ status: payload.status, owner: payload.owner }),
  })
  return {
    coverageCompanyId: String(item.coverage_company_id), sectorId: String(item.sector_id), securityId: String(item.security_id), name: String(item.name),
    ticker: item.ticker ? String(item.ticker) : undefined, industry: item.industry ? String(item.industry) : undefined,
    market: item.market ? String(item.market) : undefined, owner: String(item.owner ?? '待分配'), status: String(item.status ?? '待建档'),
    thesisCount: Number(item.thesis_count ?? (item.thesis_id ? 1 : 0)),
    hypothesisCount: Number(item.hypothesis_count ?? 0), configuredMetricCount: Number(item.configured_metric_count ?? 0),
    updatedAt: item.updated_at ? String(item.updated_at) : undefined,
  }
}

export async function getSecurity(securityId: string): Promise<Security> {
  if (useMock) return demoSecurities.find((item) => item.securityId === securityId) ?? { securityId, name: securityId }
  const item = await request<Record<string, unknown>>(`/api/securities/${encodeURIComponent(securityId)}`)
  return { securityId: String(item.security_id), name: String(item.name), ticker: item.ticker ? String(item.ticker) : undefined, industry: item.industry ? String(item.industry) : undefined }
}

export async function getCompanyMetricCenter(securityId: string): Promise<CompanyMetricCenter> {
  if (useMock) return { securityId, metrics: [] }
  const data = await request<{ security_id: string; updated_at?: string; metrics: Array<Record<string, unknown>> }>(`/api/securities/${encodeURIComponent(securityId)}/metric-center`)
  const currency = (() => {
    const value = securityId.toUpperCase()
    return value.length === 5 && /^\d+$/.test(value) ? 'HKD' : 'CNY'
  })()
  const currencyMetricIds = new Set(['MKT-OPEN-D', 'MKT-HIGH-D', 'MKT-LOW-D', 'MKT-CLOSE-D', 'MKT-CHANGE-D', 'MKT-AMOUNT-D', 'TECH-MA5-D', 'TECH-MA20-D', 'TECH-MA60-D', 'VAL-MARKET-CAP-D'])
  return { securityId: data.security_id, updatedAt: data.updated_at, metrics: data.metrics.map((item) => ({
    metricId: String(item.metric_id), name: String(item.name), category: String(item.category), unit: currencyMetricIds.has(String(item.metric_id)) && ['交易币种', '元'].includes(String(item.unit ?? '')) ? currency : String(item.unit ?? ''), frequency: String(item.frequency), definition: String(item.definition), sourceId: String(item.source_id), latestValue: String(item.latest_value), latestPeriod: String(item.latest_period), latestDate: String(item.latest_date), previousValue: item.previous_value == null ? undefined : String(item.previous_value), changeValue: item.change_value == null ? undefined : String(item.change_value), changeRate: item.change_rate == null ? undefined : String(item.change_rate), observations: ((item.observations ?? []) as Array<Record<string, unknown>>).map((point) => ({ period: String(point.period), date: String(point.date), value: String(point.value) })),
  })) }
}

export async function refreshCompanyMetrics(securityId: string): Promise<{ fetched: number; inserted: number; errors: string[] }> {
  if (useMock) return { fetched: 0, inserted: 0, errors: [] }
  return request(`/api/securities/${encodeURIComponent(securityId)}/metric-center/refresh`, { method: 'POST' })
}

export async function lookupSecurities(query: string): Promise<Array<Security & { source: string }>> {
  if (useMock) return demoSecurities.filter((item) => `${item.securityId} ${item.name}`.toLowerCase().includes(query.toLowerCase())).map((item) => ({ ...item, source: 'database' }))
  const items = await request<Array<Record<string, unknown>>>(`/api/securities/resolve?query=${encodeURIComponent(query)}`)
  return items.map((item) => ({
    securityId: String(item.security_id), name: String(item.name),
    ticker: item.ticker ? String(item.ticker) : undefined,
    industry: item.industry ? String(item.industry) : undefined,
    source: String(item.source),
  }))
}

export async function createSecurity(payload: { securityId: string; name: string; ticker?: string; industry?: string }): Promise<Security> {
  if (useMock) return { ...payload, ticker: payload.securityId }
  const item = await request<Record<string, unknown>>('/api/securities', {
    method: 'POST',
    body: JSON.stringify({ security_id: payload.securityId, name: payload.name, ticker: payload.ticker || payload.securityId, industry: payload.industry || null }),
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
  if (useMock) return Promise.resolve({ items: demoEvidenceFeeds.slice(0, limit), total: demoEvidenceFeeds.length, limit, offset: 0 })
  return getFeed(`/api/workbench/tasks?limit=${limit}`)
}

export function getResearchUpdates(filters: { status?: string; direction?: string; priority?: string; recentDays?: number; todayOnly?: boolean; businessDay?: string } = {}): Promise<PageResult<EvidenceFeedItem>> {
  if (useMock) {
    const items = demoEvidenceFeeds.filter((item) =>
      (!filters.status || item.confirmationStatus === filters.status)
      && (!filters.direction || item.direction === filters.direction)
      && (!filters.priority || item.priority === filters.priority),
    )
    return Promise.resolve({ items, total: items.length, limit: 50, offset: 0 })
  }
  const params = new URLSearchParams({ limit: '50' })
  if (filters.status) params.append('status', filters.status)
  if (filters.direction) params.set('direction', filters.direction)
  if (filters.priority) params.append('priority', filters.priority)
  if (filters.recentDays) params.set('recent_days', String(filters.recentDays))
  if (filters.businessDay) params.set('business_day', filters.businessDay)
  if (filters.todayOnly) params.set('today_only', 'true')
  return getFeed(`/api/updates?${params}`)
}

export type TodayCompanyUpdate = {
  securityId: string
  securityName: string
  documentCount: number
  latestIngestedAt: string
  titles: string[]
}

export async function getTodayCompanyUpdates(): Promise<TodayCompanyUpdate[]> {
  if (useMock) return []
  const response = await request<{ items: Array<Record<string, unknown>> }>('/api/updates/today')
  return response.items.map((item) => ({
    securityId: String(item.security_id), securityName: String(item.security_name),
    documentCount: Number(item.document_count), latestIngestedAt: String(item.latest_ingested_at),
    titles: Array.isArray(item.titles) ? item.titles.map(String) : [],
  }))
}

/** Queues the two bounded provider jobs; results arrive through the normal evidence pipeline. */
export async function syncTodayResearch(): Promise<{ newsJobId: string; reportJobId: string }> {
  if (useMock) return { newsJobId: 'collect-demo-news', reportJobId: 'collect-demo-reports' }
  const [news, reports] = await Promise.all([
    request<Record<string, unknown>>('/api/collection/investoday/news/sync', { method: 'POST' }),
    request<Record<string, unknown>>('/api/collection/investoday/reports/sync', { method: 'POST' }),
  ])
  return { newsJobId: String(news.job_id), reportJobId: String(reports.job_id) }
}

function toCollectionRun(item: Record<string, unknown>): InvestodayCollectionRun {
  const statuses: InvestodayCollectionRun['status'][] = ['not_started', 'running', 'completed', 'failed', 'disabled', 'unavailable']
  const status = statuses.includes(item.status as InvestodayCollectionRun['status']) ? item.status as InvestodayCollectionRun['status'] : 'not_started'
  return {
    kind: item.kind === 'report' ? 'report' : 'news',
    status,
    businessDate: String(item.business_date ?? ''),
    isCurrent: Boolean(item.is_current),
    updatedAt: item.updated_at ? String(item.updated_at) : undefined,
    fetched: item.fetched == null ? undefined : Number(item.fetched),
    queued: item.queued == null ? undefined : Number(item.queued),
    queuedToday: item.queued_today == null ? undefined : Number(item.queued_today),
    skippedSeen: item.skipped_seen == null ? undefined : Number(item.skipped_seen),
  }
}

/** Today's automatic source-collection checkpoint; document analysis continues in the normal worker pipeline. */
export async function getInvestodayCollectionStatus(): Promise<InvestodayCollectionStatus> {
  if (useMock) {
    return {
      businessDate: new Date().toISOString().slice(0, 10), workerReady: true, overallStatus: 'completed',
      news: { kind: 'news', status: 'completed', businessDate: new Date().toISOString().slice(0, 10), isCurrent: true, fetched: 8, queued: 2 },
      reports: { kind: 'report', status: 'completed', businessDate: new Date().toISOString().slice(0, 10), isCurrent: true, fetched: 2, queued: 1 },
    }
  }
  const item = await request<Record<string, unknown>>('/api/collection/investoday/status')
  return {
    businessDate: String(item.business_date ?? ''),
    workerReady: Boolean(item.worker_ready),
    overallStatus: String(item.overall_status ?? 'not_started') as InvestodayCollectionRun['status'],
    news: toCollectionRun((item.news ?? {}) as Record<string, unknown>),
    reports: toCollectionRun((item.reports ?? {}) as Record<string, unknown>),
  }
}

export function getRadarEvidence(thesisId: string, filters: { status?: string; direction?: string } = {}): Promise<PageResult<EvidenceFeedItem>> {
  if (useMock) {
    const items = demoEvidenceFeeds.filter((item) => (!filters.status || item.confirmationStatus === filters.status) && (!filters.direction || item.direction === filters.direction))
    return Promise.resolve({ items, total: items.length, limit: 50, offset: 0 })
  }
  const params = new URLSearchParams({ thesis_id: thesisId, limit: '50' })
  if (filters.status) params.append('status', filters.status)
  if (filters.direction) params.set('direction', filters.direction)
  return getFeed(`/api/radar/evidence?${params}`)
}

export function getThesisEvidenceFeed(thesisId: string): Promise<PageResult<EvidenceFeedItem>> {
  if (useMock) return Promise.resolve({ items: demoEvidenceFeeds, total: demoEvidenceFeeds.length, limit: 100, offset: 0 })
  return getFeed(`/api/theses/${thesisId}/evidence-feed?limit=100`)
}

export async function getSuggestions(thesisId: string): Promise<Suggestion[]> {
  if (useMock) return demoSuggestions
  const items = await request<Array<Record<string, unknown>>>(`/api/theses/${thesisId}/suggestions`)
  return items.map((item) => ({ suggestionId: Number(item.suggestion_id), currentStatus: String(item.current_status), suggestedStatus: String(item.suggested_status), reasons: item.reasons as string[], triggeredHypotheses: (item.triggered_hypotheses ?? []) as string[], ruleVersion: String(item.rule_version), humanAction: item.human_action ? String(item.human_action) : undefined }))
}

export async function getTrends(thesisId: string): Promise<Trend[]> {
  if (useMock) return demoTrends
  const items = await request<Array<Record<string, unknown>>>(`/api/theses/${thesisId}/trends`)
  const names: Record<string, string> = { 'AUTO-SALES-M': '月度汽车销量', 'AUTO-EXPORT-SALES-M': '月度海外销量/出口量', 'AUTO-BATTERY-INSTALL-M': '月度动力电池装机量', 'FIN-REVENUE-Q': '单季度营业收入', 'FIN-REVENUE-YOY-Q': '单季度营业收入同比', 'FIN-GROSS-MARGIN-Q': '单季度毛利率' }
  return items.map((item) => ({ hypothesisId: String(item.hypothesis_id), statement: String(item.statement), metricId: String(item.metric_id), metricName: item.metric_name ? String(item.metric_name) : names[String(item.metric_id)] ?? String(item.metric_id), unit: String(item.unit), direction: String(item.direction), expectedValue: item.expected_value != null ? String(item.expected_value) : undefined, expectedLower: item.expected_lower != null ? String(item.expected_lower) : undefined, expectedUpper: item.expected_upper != null ? String(item.expected_upper) : undefined, invalidationThreshold: item.invalidation_threshold != null ? String(item.invalidation_threshold) : undefined, invalidationConsecutivePeriods: item.invalidation_consecutive_periods != null ? Number(item.invalidation_consecutive_periods) : undefined, invalidationRule: item.invalidation_rule ? String(item.invalidation_rule) : undefined, slope: item.slope != null ? String(item.slope) : undefined, verdict: item.verdict ? String(item.verdict) : undefined, note: item.note ? String(item.note) : undefined, points: (item.points as Array<Record<string, unknown>>).map((p) => ({ period: String(p.period), value: String(p.value), publishedOn: String(p.published_on), acquiredAt: p.acquired_at ? String(p.acquired_at) : undefined, sourceDocumentId: p.source_document_id ? String(p.source_document_id) : undefined, dataVersion: p.data_version ? String(p.data_version) : undefined, isValidationWindow: p.is_validation_window == null ? true : Boolean(p.is_validation_window) })) }))
}

export async function recheckThesisQuality(thesisId: string): Promise<ThesisDetail> {
  return toThesis(await request<Record<string, unknown>>(`/api/theses/${encodeURIComponent(thesisId)}/quality-check`, { method: 'POST', body: '{}' }))
}

export async function getAudit(thesisId: string): Promise<AuditItem[]> {
  if (useMock) return demoAudit
  const page = await request<{ items: Array<Record<string, unknown>> }>(`/api/theses/${thesisId}/audit`)
  return page.items.map((item) => ({ action: String(item.action), actor: String(item.actor), objectType: item.object_type ? String(item.object_type) : undefined, objectId: item.object_id ? String(item.object_id) : undefined, modelVersion: item.model_version ? String(item.model_version) : undefined, occurredAt: item.occurred_at ? String(item.occurred_at) : undefined, detail: item.detail as Record<string, unknown> | undefined }))
}

export async function getWorkbench(): Promise<WorkbenchData> {
  if (useMock) return demoWorkbench
  const item = await request<Record<string, unknown>>('/api/workbench')
  const items = (key: string) => ((item[key] ?? []) as Array<Record<string, unknown>>).map((x) => ({ kind: String(x.kind), thesisId: String(x.thesis_id), title: String(x.title), objectId: String(x.object_id), summary: String(x.summary) }))
  return { statusCounts: item.status_counts as Record<string, number>, pendingEvidence: items('pending_evidence'), pendingSuggestions: items('pending_suggestions'), reviewDue: items('review_due') }
}

export async function createRelation(evidenceId: string, payload: { thesisId: string; hypothesisId: string; direction: string; strength: string; reason: string }): Promise<void> {
  if (useMock) return
  await request(`/api/evidence/${evidenceId}/relations`, { method: 'POST', body: JSON.stringify({ thesis_id: payload.thesisId, hypothesis_id: payload.hypothesisId, direction: payload.direction, strength: payload.strength, reason: payload.reason }) })
}

export async function updateRelation(evidenceId: string, relationId: string, payload: { thesisId: string; hypothesisId: string; direction: string; strength: string; reason: string }): Promise<void> {
  if (useMock) return
  await request(`/api/evidence/${evidenceId}/relations/${relationId}`, { method: 'PATCH', body: JSON.stringify({ thesis_id: payload.thesisId, hypothesis_id: payload.hypothesisId, direction: payload.direction, strength: payload.strength, reason: payload.reason }) })
}

export async function reviewRelation(evidenceId: string, relationId: string, action: string, reason?: string): Promise<void> {
  if (useMock) {
    mockRelationStates.set(relationId, action === '确认' ? 'confirmed' : action === '驳回' ? 'rejected' : 'pending')
    return
  }
  await request(`/api/evidence/${evidenceId}/relations/${relationId}/review`, { method: 'POST', body: JSON.stringify({ action, reason }) })
}

export async function deactivateRelation(evidenceId: string, relationId: string, reason: string): Promise<void> {
  if (useMock) { mockRelationStates.set(relationId, 'deactivated'); return }
  await request(`/api/evidence/${evidenceId}/relations/${relationId}/deactivate`, { method: 'POST', body: JSON.stringify({ reason }) })
}

export async function decideStatus(thesisId: string, payload: { suggestionId: number; action: string; reason: string; targetStatus?: string }): Promise<void> {
  if (useMock) return
  await request(`/api/theses/${thesisId}/status`, { method: 'POST', body: JSON.stringify({ suggestion_id: payload.suggestionId, action: payload.action, reason: payload.reason, target_status: payload.targetStatus }) })
}

export async function createDraft(payload: { securityId: string; view: string; useRag?: boolean }): Promise<ThesisDetail> {
  if (useMock) return { ...demoThesis, thesisId: `THS-DEMO-${Date.now()}`, securityId: payload.securityId, title: `${payload.securityId}：AI 候选投资逻辑`, status: '草稿', direction: '观察', version: 1, coreView: payload.view }
  return toThesis(await request<Record<string, unknown>>('/api/theses/drafts', { method: 'POST', body: JSON.stringify({ security_id: payload.securityId, view: payload.view, use_rag: Boolean(payload.useRag) }) }))
}

export async function publishThesis(thesisId: string, payload: { direction: string; horizonEndOn: string; nextReviewAt: string }): Promise<ThesisDetail> {
  if (useMock) return { ...(demoTheses.find((item) => item.thesisId === thesisId) ?? demoThesis), status: '验证中', direction: payload.direction, horizonEndOn: payload.horizonEndOn, nextReviewAt: payload.nextReviewAt }
  return toThesis(await request<Record<string, unknown>>(`/api/theses/${thesisId}/publish`, { method: 'POST', body: JSON.stringify({ direction: payload.direction, horizon_end_on: payload.horizonEndOn, next_review_at: payload.nextReviewAt }) }))
}

export async function getPublishReadiness(thesisId: string, payload: { direction: string; horizonEndOn: string; nextReviewAt: string }): Promise<PublishReadiness> {
  if (useMock) return { ready: true, items: [{ code: 'core-view', label: '核心观点', passed: true, message: '核心观点已填写。' }, { code: 'hypotheses', label: '可证伪假设', passed: true, message: '3 条假设均有观察窗口和失效条件。' }, { code: 'metrics', label: '指标映射', passed: true, message: '核心假设已绑定受控指标。' }, { code: 'review-date', label: '复核日期', passed: true, message: `下次复核日 ${payload.nextReviewAt}。` }] }
  const item = await request<{ ready: boolean; items: Array<Record<string, unknown>> }>(`/api/theses/${thesisId}/publish-readiness`, { method: 'POST', body: JSON.stringify({ direction: payload.direction, horizon_end_on: payload.horizonEndOn, next_review_at: payload.nextReviewAt }) })
  return { ready: item.ready, items: item.items.map((row) => ({ code: String(row.code), label: String(row.label), passed: Boolean(row.passed), message: String(row.message) })) }
}

export async function updateHypothesis(thesisId: string, hypothesisId: string, payload: { statement: string; hypothesisType: string; importance: string; observationWindow?: string; invalidationRule?: string }): Promise<ThesisDetail> {
  if (useMock) {
    const thesis = demoTheses.find((item) => item.thesisId === thesisId) ?? demoThesis
    return { ...thesis, hypotheses: thesis.hypotheses.map((item) => item.hypothesisId === hypothesisId ? { ...item, ...payload } : item) }
  }
  return toThesis(await request<Record<string, unknown>>(`/api/theses/${thesisId}/hypotheses/${hypothesisId}`, { method: 'PATCH', body: JSON.stringify({ statement: payload.statement, hypothesis_type: payload.hypothesisType, importance: payload.importance, observation_window: payload.observationWindow || null, invalidation_rule: payload.invalidationRule || null }) }))
}

export async function createHypothesis(thesisId: string, payload: { statement: string; hypothesisType: string; importance: string; observationWindow?: string; invalidationRule?: string }): Promise<ThesisDetail> {
  if (useMock) {
    const thesis = demoTheses.find((item) => item.thesisId === thesisId) ?? demoThesis
    const hypothesisId = `${thesisId}-H${thesis.hypotheses.length + 1}`
    return {
      ...thesis,
      hypotheses: [...thesis.hypotheses, {
        hypothesisId,
        statement: payload.statement,
        hypothesisType: payload.hypothesisType,
        importance: payload.importance,
        observationWindow: payload.observationWindow,
        invalidationRule: payload.invalidationRule,
        status: '待验证',
        mappings: [],
        metricSuggestions: [],
      }],
    }
  }
  return toThesis(await request<Record<string, unknown>>(`/api/theses/${encodeURIComponent(thesisId)}/hypotheses`, {
    method: 'POST',
    body: JSON.stringify({
      statement: payload.statement,
      hypothesis_type: payload.hypothesisType,
      importance: payload.importance,
      observation_window: payload.observationWindow || null,
      invalidation_rule: payload.invalidationRule || null,
    }),
  }))
}

export async function updateThesisDraft(thesisId: string, payload: { title: string; coreView: string }): Promise<ThesisDetail> {
  if (useMock) return { ...(demoTheses.find((item) => item.thesisId === thesisId) ?? demoThesis), title: payload.title, coreView: payload.coreView }
  return toThesis(await request<Record<string, unknown>>(`/api/theses/${thesisId}`, { method: 'PATCH', body: JSON.stringify({ title: payload.title, core_view: payload.coreView }) }))
}

export type ThesisMaintenancePayload = {
  title: string; coreView: string; direction: string; investmentRating?: string; targetPrice?: string; observationPeriod?: string;
  horizonEndOn?: string; nextReviewAt?: string; reason: string;
  hypotheses: Array<{ hypothesisId: string; statement: string; hypothesisType: string; importance: string; observationWindow?: string; invalidationRule?: string }>;
  mappings: Array<{ hypothesisId: string; mappingId?: string; metricId: string; metricVersion: string; expectedDirection: string; expectedValue?: string; expectedLower?: string; expectedUpper?: string; invalidationThreshold?: string; invalidationConsecutivePeriods?: number; expectationSource: string }>;
}

export async function updateThesisMaintenance(thesisId: string, payload: ThesisMaintenancePayload): Promise<ThesisDetail> {
  if (useMock) return { ...(demoTheses.find((item) => item.thesisId === thesisId) ?? demoThesis), title: payload.title, coreView: payload.coreView, direction: payload.direction, investmentRating: payload.investmentRating || payload.direction, targetPrice: payload.targetPrice, observationPeriod: payload.observationPeriod }
  const numeric = (value?: string) => value?.replace(/[\s,，]/g, '').trim() || null
  const item = await request<Record<string, unknown>>(`/api/theses/${encodeURIComponent(thesisId)}/maintenance`, {
    method: 'PATCH',
    body: JSON.stringify({
      title: payload.title, core_view: payload.coreView, direction: payload.direction,
      investment_rating: payload.investmentRating || null, target_price: numeric(payload.targetPrice), observation_period: payload.observationPeriod || null,
      horizon_end_on: payload.horizonEndOn || null, next_review_at: payload.nextReviewAt || null, reason: payload.reason,
      hypotheses: payload.hypotheses.map((item) => ({ hypothesis_id: item.hypothesisId, statement: item.statement, hypothesis_type: item.hypothesisType, importance: item.importance, observation_window: item.observationWindow || null, invalidation_rule: item.invalidationRule || null })),
      mappings: payload.mappings.map((item) => ({ hypothesis_id: item.hypothesisId, mapping_id: item.mappingId || null, metric_id: item.metricId, metric_version: item.metricVersion, expected_direction: item.expectedDirection, expected_value: numeric(item.expectedValue), expected_lower: numeric(item.expectedLower), expected_upper: numeric(item.expectedUpper), invalidation_threshold: numeric(item.invalidationThreshold), invalidation_consecutive_periods: item.invalidationConsecutivePeriods || null, expectation_source: item.expectationSource })),
    }),
  })
  return toThesis(item)
}

export async function listMetrics(keyword = ''): Promise<MetricDefinition[]> {
  if (useMock) return demoMetrics.filter((item) => !keyword || item.name.includes(keyword) || item.metricId.includes(keyword))
  const items = await request<Array<Record<string, unknown>>>(`/api/metrics?limit=100${keyword ? `&keyword=${encodeURIComponent(keyword)}` : ''}`)
  return items.map((item) => ({ metricId: String(item.metric_id), version: String(item.version), name: String(item.name), unit: String(item.unit), category: item.category ? String(item.category) : undefined, definition: item.definition ? String(item.definition) : undefined, frequency: item.frequency ? String(item.frequency) : undefined, expectedDirection: item.expected_direction ? String(item.expected_direction) : undefined, status: String(item.status) }))
}

export async function saveMetricMapping(thesisId: string, hypothesisId: string, payload: { mappingId?: string; metricId: string; metricVersion: string; expectedDirection: string; expectedValue?: string; expectedLower?: string; expectedUpper?: string; invalidationThreshold?: string; invalidationConsecutivePeriods?: number; expectationSource: string }): Promise<MetricMapping> {
  if (useMock) return { ...payload, mappingId: payload.mappingId ?? `MAP-DEMO-${Date.now()}`, confirmationStatus: '已确认' }
  const numeric = (value?: string) => {
    const normalized = value?.replace(/[\s,，]/g, '').trim()
    return normalized || null
  }
  const item = await request<Record<string, unknown>>(`/api/theses/${thesisId}/hypotheses/${hypothesisId}/mappings`, { method: 'POST', body: JSON.stringify({ mapping_id: payload.mappingId || null, metric_id: payload.metricId, metric_version: payload.metricVersion, expected_direction: payload.expectedDirection, expected_value: numeric(payload.expectedValue), expected_lower: numeric(payload.expectedLower), expected_upper: numeric(payload.expectedUpper), invalidation_threshold: numeric(payload.invalidationThreshold), invalidation_consecutive_periods: payload.invalidationConsecutivePeriods || null, expectation_source: payload.expectationSource }) })
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
  if (useMock) return
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
  if (useMock) return { jobId, status: 'complete', success: true, result: { persisted_document_id: 'DOC-DEMO-UPLOAD', duplicate: false, segment_count: 18, fact_count: 7, event_count: 3, matched_thesis_count: 1, retrieval_mode: 'text+graph', candidate_evidence_count: 3, deferred_event_count: 1 } }
  const item = await request<Record<string, unknown>>(`/api/jobs/${encodeURIComponent(jobId)}`)
  return { jobId: String(item.job_id), status: String(item.status), success: item.success == null ? undefined : Boolean(item.success), result: item.result as Record<string, unknown> | undefined, enqueueTime: item.enqueue_time ? String(item.enqueue_time) : undefined, startTime: item.start_time ? String(item.start_time) : undefined, finishTime: item.finish_time ? String(item.finish_time) : undefined }
}

export async function listProcessingJobs(): Promise<ProcessingJob[]> {
  if (useMock) return demoProcessingJobs.map((item) => mockReplayedJobs.has(item.jobId) ? { ...item, status: 'queued', lastError: undefined } : item)
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
  if (useMock) { mockReplayedJobs.add(jobId); return { jobId, documentId: demoProcessingJobs.find((item) => item.jobId === jobId)?.documentId ?? 'DOC-DEMO', status: 'queued' } }
  const item = await request<Record<string, unknown>>(`/api/jobs/${encodeURIComponent(jobId)}/replay`, { method: 'POST' })
  return { jobId: String(item.job_id), documentId: String(item.document_id), status: String(item.status) }
}

export async function reanalyzeProcessingJob(jobId: string): Promise<JobAccepted> {
  const item = await request<Record<string, unknown>>(`/api/jobs/${encodeURIComponent(jobId)}/reanalyze`, { method: 'POST' })
  return { jobId: String(item.job_id), documentId: String(item.document_id), status: String(item.status) }
}

export async function listIngestionReviews(): Promise<IngestionReview[]> {
  if (useMock) return demoIngestionReviews.map((item) => mockResolvedIngestion.has(item.reviewId) ? { ...item, status: 'resolved', resolution: '已由研究员完成归属复核。', resolvedAt: new Date().toISOString() } : item)
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
  if (useMock) { mockResolvedIngestion.add(reviewId); return }
  await request(`/api/reviews/ingestion/${encodeURIComponent(reviewId)}/resolve`, {
    method: 'POST', body: JSON.stringify({ resolution: payload.resolution, security_id: payload.securityId || null }),
  })
}

export async function listReviewTasks(): Promise<ReviewTask[]> {
  if (useMock) return demoReviewTasks.map((item) => mockResolvedReviews.has(item.taskId) ? { ...item, state: '已完成', resolution: '已完成本轮复核。', resolvedAt: new Date().toISOString() } : item)
  const items = await request<Array<Record<string, unknown>>>('/api/reviews?limit=100')
  return items.map((item) => ({ taskId: String(item.task_id), thesisId: String(item.thesis_id), trigger: String(item.trigger), priority: String(item.priority), assignee: String(item.assignee), state: String(item.state), detail: item.detail as Record<string, unknown> | undefined, resolution: item.resolution ? String(item.resolution) : undefined, createdAt: item.created_at ? String(item.created_at) : undefined, resolvedAt: item.resolved_at ? String(item.resolved_at) : undefined }))
}

export async function resolveReviewTask(taskId: string, resolution: string): Promise<void> {
  if (useMock) { mockResolvedReviews.add(taskId); return }
  await request(`/api/reviews/${encodeURIComponent(taskId)}/resolve`, { method: 'POST', body: JSON.stringify({ resolution }) })
}

export async function createReviewDraft(thesisId: string, payload: { periodStart: string; periodEnd: string }): Promise<ReviewDraftCandidate> {
  const item = await request<Record<string, unknown>>(`/api/reviews/theses/${encodeURIComponent(thesisId)}/drafts`, {
    method: 'POST', body: JSON.stringify({ period_start: payload.periodStart, period_end: payload.periodEnd }),
  })
  return {
    runId: String(item.run_id), status: String(item.status),
    aiStatus: item.ai_status ? String(item.ai_status) : undefined,
    requiresHumanReview: Boolean(item.requires_human_review),
    payload: (item.payload ?? {}) as Record<string, unknown>, errors: (item.errors ?? []) as string[],
  }
}

export async function recommendHypothesisMetrics(thesisId: string, hypothesisId: string, topK = 8): Promise<ReviewDraftCandidate> {
  const item = await request<Record<string, unknown>>(`/api/agent/theses/${encodeURIComponent(thesisId)}/hypotheses/${encodeURIComponent(hypothesisId)}/metric-recommendations`, {
    method: 'POST', body: JSON.stringify({ top_k: topK }),
  })
  return {
    runId: String(item.run_id), status: String(item.status),
    aiStatus: item.ai_status ? String(item.ai_status) : undefined,
    requiresHumanReview: Boolean(item.requires_human_review),
    payload: (item.payload ?? {}) as Record<string, unknown>, errors: (item.errors ?? []) as string[],
  }
}

export async function getDocumentSegment(locator: string): Promise<DocumentSegment> {
  const matched = locator.match(/^(.+)#paragraph-(\d+)$/)
  if (!matched) throw new Error('原文定位格式无效。')
  if (useMock) return { documentId: matched[1], title: demoEvidence.sourceDocumentTitle, locator, ordinal: Number(matched[2]), page: 34, content: demoEvidence.factExcerpt, contentKind: 'table_row', extractionMethod: 'native', tableIndex: 8, rowIndex: 12, cellRange: 'B12:D12', confidence: .99 }
  const item = await request<Record<string, unknown>>(`/api/documents/${encodeURIComponent(matched[1])}/segments/${matched[2]}`)
  return { documentId: String(item.document_id), title: item.title ? String(item.title) : undefined, locator: String(item.locator), ordinal: Number(item.ordinal), page: item.page == null ? undefined : Number(item.page), content: String(item.content), contentKind: String(item.content_kind ?? 'paragraph'), extractionMethod: String(item.extraction_method ?? 'native'), tableIndex: item.table_index == null ? undefined : Number(item.table_index), rowIndex: item.row_index == null ? undefined : Number(item.row_index), cellRange: item.cell_range ? String(item.cell_range) : undefined, confidence: item.confidence == null ? undefined : Number(item.confidence), previousLocator: item.previous_locator ? String(item.previous_locator) : undefined, nextLocator: item.next_locator ? String(item.next_locator) : undefined }
}

export async function getFullDocument(documentId: string): Promise<FullDocument> {
  if (useMock) return {
    documentId, title: demoEvidence.sourceDocumentTitle, docType: '研究资料', publishedAt: demoEvidence.disclosedAt,
    parserVersion: 'demo-v1', segmentCount: 2,
    segments: [
      { locator: `${documentId}#paragraph-1`, ordinal: 1, content: demoEvidence.factExcerpt, contentKind: 'paragraph', extractionMethod: 'native' },
      { locator: `${documentId}#paragraph-2`, ordinal: 2, content: '演示环境仅提供示例正文。', contentKind: 'paragraph', extractionMethod: 'native' },
    ],
  }
  const item = await request<Record<string, unknown>>(`/api/documents/${encodeURIComponent(documentId)}`)
  return {
    documentId: String(item.document_id), title: item.title ? String(item.title) : undefined,
    docType: item.doc_type ? String(item.doc_type) : undefined, publishedAt: String(item.published_at),
    parserVersion: String(item.parser_version), segmentCount: Number(item.segment_count),
    segments: Array.isArray(item.segments) ? item.segments.map((raw) => {
      const segment = raw as Record<string, unknown>
      return {
        locator: String(segment.locator), ordinal: Number(segment.ordinal), page: segment.page == null ? undefined : Number(segment.page),
        content: String(segment.content), contentKind: String(segment.content_kind ?? 'paragraph'), extractionMethod: String(segment.extraction_method ?? 'native'),
      }
    }) : [],
  }
}

export async function getAssetInventory(): Promise<AssetInventory> {
  if (useMock) return { documents: 3792, revisions: 7582, ingestionRuns: 11373, segments: 4275, facts: 0, singleSegmentDocuments: 3790, pendingAuthorization: 0, missingObjectArchive: 0, semanticRuns: 3793, artifactSegments: 8275, artifactFacts: 1, artifactEvents: 7578, embeddings: 4275, titleIndexDocuments: 3784, archivedSourceDocuments: 3792, authorizationVerifiedDocuments: 3792 }
  const item = await request<Record<string, unknown>>('/api/assets/inventory')
  return {
    documents: Number(item.documents), revisions: Number(item.revisions),
    ingestionRuns: Number(item.ingestion_runs), segments: Number(item.segments),
    facts: Number(item.facts), singleSegmentDocuments: Number(item.single_segment_documents),
    pendingAuthorization: Number(item.pending_authorization),
    missingObjectArchive: Number(item.missing_object_archive),
    semanticRuns: Number(item.semantic_runs), artifactSegments: Number(item.artifact_segments),
    artifactFacts: Number(item.artifact_facts), artifactEvents: Number(item.artifact_events),
    embeddings: Number(item.embeddings),
    titleIndexDocuments: Number(item.title_index_documents),
    archivedSourceDocuments: Number(item.archived_source_documents),
    authorizationVerifiedDocuments: Number(item.authorization_verified_documents),
  }
}

export async function rebuildAssetSearchIndex(): Promise<number> {
  if (useMock) return 3789
  const item = await request<Record<string, unknown>>('/api/assets/search-index/rebuild', { method: 'POST' })
  return Number(item.indexed_segments)
}

export async function searchAssets(query: string): Promise<AssetSearchHit[]> {
  if (useMock) return demoAssetHits.filter((item) => item.content.includes(query) || '毛利率储能海外收入'.includes(query))
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
    contentStatus: String(item.content_status ?? '待核验'),
  }))
}

function toDataCenterRun(item: Record<string, unknown>): DataCenterRun {
  return {
    runId: String(item.run_id), revisionId: String(item.revision_id),
    documentId: String(item.document_id), documentTitle: String(item.document_title),
    sourceFilename: String(item.source_filename), parserVersion: String(item.parser_version),
    chunkerVersion: String(item.chunker_version), extractorVersion: String(item.extractor_version),
    embeddingVersion: item.embedding_version ? String(item.embedding_version) : undefined,
    status: String(item.status), segmentCount: Number(item.segment_count),
    factCount: Number(item.fact_count), eventCount: Number(item.event_count),
    qualitySummary: (item.quality_summary ?? {}) as Record<string, unknown>,
    error: item.error ? String(item.error) : undefined,
    startedAt: item.started_at ? String(item.started_at) : undefined,
    finishedAt: item.finished_at ? String(item.finished_at) : undefined,
    createdAt: item.created_at ? String(item.created_at) : undefined,
  }
}

function toDataCenterDocument(item: Record<string, unknown>): DataCenterDocument {
  return {
    documentId: String(item.document_id), title: String(item.title),
    sourceId: item.source_id ? String(item.source_id) : undefined,
    sourceName: String(item.source_name), docType: item.doc_type ? String(item.doc_type) : undefined,
    publishedAt: String(item.published_at), ingestedAt: item.ingested_at ? String(item.ingested_at) : undefined,
    contentStatus: String(item.content_status), visibilityLabel: String(item.visibility_label),
    isIllustrative: Boolean(item.is_illustrative), deletedAt: item.deleted_at ? String(item.deleted_at) : undefined,
    archived: Boolean(item.archived), authorizationStatus: String(item.authorization_status),
    revisionCount: Number(item.revision_count), segmentCount: Number(item.segment_count),
    latestRunStatus: item.latest_run_status ? String(item.latest_run_status) : undefined,
    latestRunAt: item.latest_run_at ? String(item.latest_run_at) : undefined,
    securityIds: (item.security_ids ?? []) as string[], securityNames: (item.security_names ?? []) as string[],
    industries: (item.industries ?? []) as string[],
  }
}

function toDataCenterRevision(item: Record<string, unknown>): DataCenterRevision {
  return {
    revisionId: String(item.revision_id), contentHash: String(item.content_hash),
    sourceFilename: String(item.source_filename), hasObject: Boolean(item.has_object),
    objectVersionId: item.object_version_id ? String(item.object_version_id) : undefined,
    mediaType: item.media_type ? String(item.media_type) : undefined,
    byteSize: item.byte_size == null ? undefined : Number(item.byte_size),
    sourceId: item.source_id ? String(item.source_id) : undefined,
    sourceHost: item.source_host ? String(item.source_host) : undefined,
    authorizationStatus: String(item.authorization_status),
    authorizationBasis: item.authorization_basis ? String(item.authorization_basis) : undefined,
    authorizationVerifiedBy: item.authorization_verified_by ? String(item.authorization_verified_by) : undefined,
    authorizationVerifiedAt: item.authorization_verified_at ? String(item.authorization_verified_at) : undefined,
    contentStatus: String(item.content_status), uploadedBy: String(item.uploaded_by),
    publishedAt: item.published_at ? String(item.published_at) : undefined,
    createdAt: item.created_at ? String(item.created_at) : undefined,
    tombstonedAt: item.tombstoned_at ? String(item.tombstoned_at) : undefined,
  }
}

function mockDataCenterDocuments(): DataCenterDocument[] {
  const now = new Date().toISOString()
  return demoAssetHits.map((item, index) => ({
    documentId: item.documentId, title: index === 0 ? '储能业务经营更新公告' : '公司公开披露资料',
    sourceId: 'SRC-DEMO', sourceName: '受控演示来源', docType: '公告', publishedAt: now,
    ingestedAt: now, contentStatus: item.contentStatus, visibilityLabel: item.visibilityLabel,
    isIllustrative: true, archived: true, authorizationStatus: '项目自有', revisionCount: 1,
    segmentCount: 1, latestRunStatus: 'succeeded', latestRunAt: now,
    securityIds: [demoThesis.securityId], securityNames: ['阳光电源'], industries: ['电力设备'],
  }))
}

function mockDataCenterRuns(): DataCenterRun[] {
  const now = new Date().toISOString()
  const document = mockDataCenterDocuments()[0]
  return [{
    runId: 'RUN-DEMO-INGEST-1', revisionId: `DREV-${document.documentId}`,
    documentId: document.documentId, documentTitle: document.title, sourceFilename: 'demo.txt',
    parserVersion: 'text-v1', chunkerVersion: 'semantic-v1', extractorVersion: 'rules-v1',
    embeddingVersion: 'hash-char-2gram-v1', status: 'succeeded', segmentCount: 1,
    factCount: 1, eventCount: 1, qualitySummary: { locator_coverage: 1 },
    startedAt: now, finishedAt: now, createdAt: now,
  }]
}

const mockMarketDataset: QuantMarketDataset = {
  datasetId: 'MDS-akshare-qfq-tuaremax10000-20260831-v3',
  dataVersion: 'akshare-qfq-tuaremax10000-20260831-v3',
  manifestSha256: '2d53632169f9fc7156feaaf91c002acea468217c9827917c48b30d0e9b2676db',
  authorizationStatus: '公开行情研究使用已核验', adjustment: '前复权',
  coverageStart: '2023-12-01', coverageEnd: '2026-08-28',
  securities: ['688981', '603986', '002371', '600276', '603259', '000538', '002594', '00175', '09868'],
  capabilities: {
    adjusted_close: true, trading_calendar: true, capacity_constraint: true,
    a_share_point_in_time_market_cap: true, point_in_time_market_cap: false,
    price_limit_status: false, structured_corporate_action_events: false,
  },
  limitations: ['港股点时市值未覆盖，市值中性仅限数据完整的纯 A 股组合。', 'A 股涨跌停参考仍缺 3 个证券日。', '未冻结 FX 时不得把 A/H 混币种超额解释为 Alpha。'], status: 'frozen',
  frozenBy: 'phase3-local-release', frozenAt: '2026-08-31T09:00:00+08:00',
}

const mockQuantSignalSet: QuantSignalSet = {
  signalSetId: 'QSS-DEMO-CONFIRMED-V1', name: '人工确认事件方向', version: 'confirmed-v1',
  contentSha256: 'b'.repeat(64), signalCount: 3, humanConfirmedOnly: true,
  evaluationTrack: 'alpha_validation', status: 'frozen',
  frozenBy: 'quant-reviewer', frozenAt: '2026-08-31T10:00:00+08:00',
}

export async function getDataCenterOverview(): Promise<DataCenterOverview> {
  if (useMock) {
    const documents = mockDataCenterDocuments()
    return {
      documents: documents.length, archivedDocuments: documents.length, missingArchiveDocuments: 0,
      authorizationVerifiedDocuments: documents.length, pendingAuthorizationDocuments: 0,
      titleIndexDocuments: documents.filter((item) => item.contentStatus === '标题索引').length,
      fullTextDocuments: documents.filter((item) => item.contentStatus === '完整正文').length,
      recentSucceededRuns: documents.length, recentFailedRuns: 0, marketDatasetCount: 1, signalSetCount: 1,
      defaultMarketDatasetId: mockMarketDataset.datasetId, defaultMarketDataVersion: mockMarketDataset.dataVersion,
      defaultMarketCoverageEnd: mockMarketDataset.coverageEnd,
      attention: [], recentRuns: mockDataCenterRuns(), asOf: new Date().toISOString(),
    }
  }
  const item = await request<Record<string, unknown>>('/api/assets/overview')
  return {
    documents: Number(item.documents), archivedDocuments: Number(item.archived_documents),
    missingArchiveDocuments: Number(item.missing_archive_documents),
    authorizationVerifiedDocuments: Number(item.authorization_verified_documents),
    pendingAuthorizationDocuments: Number(item.pending_authorization_documents),
    titleIndexDocuments: Number(item.title_index_documents), fullTextDocuments: Number(item.full_text_documents),
    recentSucceededRuns: Number(item.recent_succeeded_runs), recentFailedRuns: Number(item.recent_failed_runs),
    marketDatasetCount: Number(item.market_dataset_count), signalSetCount: Number(item.signal_set_count),
    defaultMarketDatasetId: item.default_market_dataset_id ? String(item.default_market_dataset_id) : undefined,
    defaultMarketDataVersion: item.default_market_data_version ? String(item.default_market_data_version) : undefined,
    defaultMarketCoverageEnd: item.default_market_coverage_end ? String(item.default_market_coverage_end) : undefined,
    attention: ((item.attention ?? []) as Array<Record<string, unknown>>).map((value) => ({
      code: String(value.code), label: String(value.label), count: Number(value.count),
      severity: String(value.severity), target: String(value.target),
    })),
    recentRuns: ((item.recent_runs ?? []) as Array<Record<string, unknown>>).map(toDataCenterRun),
    asOf: String(item.as_of),
  }
}

export async function listDataCenterDocuments(params: URLSearchParams): Promise<DataCenterDocumentPage> {
  if (useMock) {
    const q = (params.get('q') ?? '').toLowerCase()
    const contentStatus = params.get('content_status')
    const securityId = params.get('security_id')
    const direction = params.get('direction') === 'asc' ? 1 : -1
    const rows = mockDataCenterDocuments().filter((item) =>
      (!q || item.title.toLowerCase().includes(q) || item.documentId.toLowerCase().includes(q))
      && (!contentStatus || item.contentStatus === contentStatus)
      && (!securityId || item.securityIds.includes(securityId)))
      .sort((left, right) => left.publishedAt.localeCompare(right.publishedAt) * direction)
    const limit = Number(params.get('limit') ?? 20)
    const offset = Number(params.get('offset') ?? 0)
    return { items: rows.slice(offset, offset + limit), total: rows.length, limit, offset }
  }
  const item = await request<Record<string, unknown>>(`/api/assets/documents?${params.toString()}`)
  return {
    items: ((item.items ?? []) as Array<Record<string, unknown>>).map(toDataCenterDocument),
    total: Number(item.total), limit: Number(item.limit), offset: Number(item.offset),
  }
}

export async function getDataCenterDocument(documentId: string, includeDeleted = false): Promise<DataCenterDocumentDetail> {
  if (useMock) {
    const document = mockDataCenterDocuments().find((item) => item.documentId === documentId)
    if (!document) throw new Error('资料不存在')
    const now = new Date().toISOString()
    return {
      ...document, allowedActions: ['view_content', 'reprocess', 'change_visibility', 'delete', 'rebuild_index'],
      revisions: [{ revisionId: `DREV-${documentId}`, contentHash: 'a'.repeat(64), sourceFilename: 'demo.txt', hasObject: true, mediaType: 'text/plain', authorizationStatus: '项目自有', contentStatus: document.contentStatus, uploadedBy: 'demo', createdAt: now }],
      runs: mockDataCenterRuns().filter((item) => item.documentId === documentId),
    }
  }
  const suffix = includeDeleted ? '?include_deleted=true' : ''
  const item = await request<Record<string, unknown>>(`/api/assets/documents/${encodeURIComponent(documentId)}${suffix}`)
  return {
    ...toDataCenterDocument(item), allowedActions: (item.allowed_actions ?? []) as string[],
    revisions: ((item.revisions ?? []) as Array<Record<string, unknown>>).map(toDataCenterRevision),
    runs: ((item.runs ?? []) as Array<Record<string, unknown>>).map(toDataCenterRun),
  }
}

export async function listDataCenterSources(): Promise<DataCenterSource[]> {
  if (useMock) return [{ sourceId: 'SRC-DEMO', name: '受控演示来源', sourceType: 'project', authorizationStatus: '项目自有', active: true, documentCount: mockDataCenterDocuments().length }]
  const items = await request<Array<Record<string, unknown>>>('/api/assets/sources')
  return items.map((item) => ({
    sourceId: String(item.source_id), name: String(item.name), sourceType: String(item.source_type),
    authorizationStatus: String(item.authorization_status), licenseNote: item.license_note ? String(item.license_note) : undefined,
    authorizationBasis: item.authorization_basis ? String(item.authorization_basis) : undefined,
    authorizationVerifiedBy: item.authorization_verified_by ? String(item.authorization_verified_by) : undefined,
    authorizationVerifiedAt: item.authorization_verified_at ? String(item.authorization_verified_at) : undefined,
    active: Boolean(item.active), documentCount: Number(item.document_count),
    latestRunStatus: item.latest_run_status ? String(item.latest_run_status) : undefined,
    latestRunAt: item.latest_run_at ? String(item.latest_run_at) : undefined,
    baseHost: item.base_host ? String(item.base_host) : undefined,
  }))
}

export async function listDataCenterRuns(params: URLSearchParams): Promise<{ items: DataCenterRun[]; total: number; limit: number; offset: number }> {
  if (useMock) {
    const status = params.get('status')
    const documentId = params.get('document_id')
    const rows = mockDataCenterRuns().filter((item) =>
      (!status || item.status === status) && (!documentId || item.documentId === documentId))
    const limit = Number(params.get('limit') ?? 20)
    const offset = Number(params.get('offset') ?? 0)
    return { items: rows.slice(offset, offset + limit), total: rows.length, limit, offset }
  }
  const item = await request<Record<string, unknown>>(`/api/assets/ingestion-runs?${params.toString()}`)
  return {
    items: ((item.items ?? []) as Array<Record<string, unknown>>).map(toDataCenterRun),
    total: Number(item.total), limit: Number(item.limit), offset: Number(item.offset),
  }
}

export async function updateDataCenterVisibility(documentId: string, visibilityLabel: string): Promise<void> {
  if (useMock) return
  await request<void>(`/api/assets/documents/${encodeURIComponent(documentId)}/visibility`, {
    method: 'PATCH', body: JSON.stringify({ visibility_label: visibilityLabel }),
  })
}

export async function reprocessDataCenterDocument(documentId: string): Promise<{ jobId: string }> {
  if (useMock) return { jobId: `MOCK-${documentId}` }
  const item = await request<Record<string, unknown>>('/api/assets/ingestion-runs/reprocess', {
    method: 'POST', body: JSON.stringify({ document_id: documentId }),
  })
  return { jobId: String(item.job_id) }
}

export async function deleteDataCenterDocument(documentId: string): Promise<void> {
  if (useMock) return
  await request<void>(`/api/assets/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' })
}

export async function restoreDataCenterDocument(documentId: string, visibilityLabel = '内部受限'): Promise<number> {
  if (useMock) return 0
  const item = await request<Record<string, unknown>>(`/api/assets/documents/${encodeURIComponent(documentId)}/restore`, {
    method: 'POST', body: JSON.stringify({ visibility_label: visibilityLabel }),
  })
  return Number(item.indexed_segments)
}

export async function fetchDataCenterContent(documentId: string, download = false): Promise<Blob> {
  if (useMock) return new Blob(['受控演示原件'], { type: 'text/plain' })
  return requestBlob(`/api/assets/documents/${encodeURIComponent(documentId)}/content?download=${download}`)
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
  if (useMock) return { draftId: `DRAFT-${thesisId}`, thesisId, baseVersion: 3, revision: 1, owner: 'analyst-mvp', payload: { title: demoThesis.title, core_view: demoThesis.coreView }, status: 'draft' }
  return toThesisRevision(await request<Record<string, unknown>>(`/api/assets/theses/${encodeURIComponent(thesisId)}/revisions`, { method: 'POST' }))
}

export async function updateThesisRevision(draft: ThesisRevision, payload: Record<string, unknown>): Promise<ThesisRevision> {
  if (useMock) return { ...draft, revision: draft.revision + 1, payload }
  return toThesisRevision(await request<Record<string, unknown>>(`/api/assets/thesis-revisions/${encodeURIComponent(draft.draftId)}`, { method: 'PATCH', body: JSON.stringify({ expected_revision: draft.revision, payload }) }))
}

export async function getThesisRevisionDiff(draftId: string): Promise<ThesisRevisionDiff> {
  if (useMock) return { draftId, baseVersion: 3, changes: { core_view: { before: demoThesis.coreView, after: `${demoThesis.coreView}（已补充现金流验证条件）` } } }
  const item = await request<Record<string, unknown>>(`/api/assets/thesis-revisions/${encodeURIComponent(draftId)}/diff`)
  return { draftId: String(item.draft_id), baseVersion: Number(item.base_version), changes: item.changes as ThesisRevisionDiff['changes'] }
}

export async function publishThesisRevision(draft: ThesisRevision, reason: string): Promise<ThesisRevision> {
  if (useMock) return { ...draft, status: 'published', revision: draft.revision + 1 }
  return toThesisRevision(await request<Record<string, unknown>>(`/api/assets/thesis-revisions/${encodeURIComponent(draft.draftId)}/publish`, { method: 'POST', body: JSON.stringify({ expected_revision: draft.revision, reason }) }))
}

function mockQuantBacktest(payload: QuantBacktestRequest): QuantBacktestRun {
  const initial = payload.config.initialCapital
  const first = payload.bars[0]
  const friction = (payload.config.transactionCostBps + payload.config.slippageBps) / 10_000
  let peak = initial
  const equityCurve = payload.bars.map((bar, index) => {
    const equity = initial * (1 + (bar.close / first.close - 1) * .72 - (index > 0 ? friction * 2 : 0))
    const benchmarkEquity = initial * bar.benchmarkClose / first.benchmarkClose
    peak = Math.max(peak, equity)
    return { tradingDate: bar.tradingDate, equity, benchmarkEquity, drawdown: equity / peak - 1, position: index > 6 && index < 70 ? .72 : 0 }
  })
  const strength = { 高: 1, 中: .7, 低: .4 }
  const trades = payload.signals.flatMap((signal) => {
    const entryIndex = payload.bars.findIndex((bar) => bar.tradingDate > signal.generatedAt.slice(0, 10))
    if (entryIndex < 0 || signal.direction === '中性' || (signal.direction === '冲突' && !payload.config.allowShort)) return []
    const exitIndex = Math.min(payload.bars.length - 1, entryIndex + payload.config.holdingDays)
    const entry = payload.bars[entryIndex]
    const exit = payload.bars[exitIndex]
    const position = (signal.direction === '冲突' ? -1 : 1) * strength[signal.strength] * signal.confidence
    const grossReturn = (exit.close / entry.close - 1) * position
    return [{ signalId: signal.signalId, direction: position > 0 ? '做多' : '做空', entryDate: entry.tradingDate, exitDate: exit.tradingDate, entryPrice: entry.close, exitPrice: exit.close, position, grossReturn, netReturn: grossReturn - Math.abs(position) * friction * 2, holdingDays: exitIndex - entryIndex, exitReason: exitIndex === payload.bars.length - 1 ? '回测期结束' : '持有期结束' }]
  })
  const finalEquity = equityCurve.at(-1)?.equity ?? initial
  const benchmarkFinal = equityCurve.at(-1)?.benchmarkEquity ?? initial
  const totalReturn = finalEquity / initial - 1
  return {
    runId: 'QBT-CONTROLLED-MOCK', name: payload.name, generatedAt: new Date().toISOString(), methodologyVersion: 'event-backtest-v1',
    metrics: {
      initialCapital: initial, finalEquity, totalReturn, benchmarkReturn: benchmarkFinal / initial - 1,
      excessReturn: totalReturn - (benchmarkFinal / initial - 1), annualizedReturn: totalReturn * 3.1,
      annualizedVolatility: .132, sharpeRatio: totalReturn * 3.1 / .132,
      maxDrawdown: Math.min(...equityCurve.map((point) => point.drawdown)),
      winRate: trades.length ? trades.filter((trade) => trade.netReturn > 0).length / trades.length : undefined,
      turnover: trades.reduce((sum, trade) => sum + Math.abs(trade.position) * 2, 0), tradeCount: trades.length,
      averageExposure: equityCurve.reduce((sum, point) => sum + Math.abs(point.position), 0) / equityCurve.length,
    },
    equityCurve, trades,
    diagnostics: { inputSignalCount: payload.signals.length, acceptedSignalCount: payload.signals.length, skippedSignalCount: 0, skippedSignals: [], warnings: ['受控 Mock 仅用于界面演示，不构成交易、评级或调仓建议'] },
  }
}

export async function runQuantBacktest(payload: QuantBacktestRequest): Promise<QuantBacktestRun> {
  if (useMock) return mockQuantBacktest(payload)
  const requestBody = {
    name: payload.name,
    bars: payload.bars.map((item) => ({
      trading_date: item.tradingDate, close: item.close,
      benchmark_close: item.benchmarkClose, tradable: item.tradable ?? true,
    })),
    signals: payload.signals.map((item) => ({
      signal_id: item.signalId, disclosed_at: item.disclosedAt, generated_at: item.generatedAt,
      direction: item.direction, strength: item.strength, confidence: item.confidence,
    })),
    config: {
      initial_capital: payload.config.initialCapital, holding_days: payload.config.holdingDays,
      transaction_cost_bps: payload.config.transactionCostBps, slippage_bps: payload.config.slippageBps,
      allow_short: payload.config.allowShort,
    },
  }
  const item = await request<Record<string, unknown>>('/api/quant/backtests', {
    method: 'POST', body: JSON.stringify(requestBody),
  })
  const result = item.result as Record<string, unknown>
  const metrics = result.metrics as Record<string, unknown>
  const diagnostics = result.diagnostics as Record<string, unknown>
  return {
    runId: String(item.run_id), name: String(item.name), generatedAt: String(item.generated_at),
    methodologyVersion: String(result.methodology_version),
    metrics: {
      initialCapital: Number(metrics.initial_capital), finalEquity: Number(metrics.final_equity),
      totalReturn: Number(metrics.total_return), benchmarkReturn: Number(metrics.benchmark_return),
      excessReturn: Number(metrics.excess_return), annualizedReturn: Number(metrics.annualized_return),
      annualizedVolatility: Number(metrics.annualized_volatility),
      sharpeRatio: metrics.sharpe_ratio == null ? undefined : Number(metrics.sharpe_ratio),
      maxDrawdown: Number(metrics.max_drawdown), winRate: metrics.win_rate == null ? undefined : Number(metrics.win_rate),
      turnover: Number(metrics.turnover), tradeCount: Number(metrics.trade_count),
      averageExposure: Number(metrics.average_exposure),
    },
    equityCurve: ((result.equity_curve ?? []) as Array<Record<string, unknown>>).map((point) => ({
      tradingDate: String(point.trading_date), equity: Number(point.equity),
      benchmarkEquity: Number(point.benchmark_equity), drawdown: Number(point.drawdown),
      position: Number(point.position),
    })),
    trades: ((result.trades ?? []) as Array<Record<string, unknown>>).map((trade) => ({
      signalId: String(trade.signal_id), direction: String(trade.direction),
      entryDate: String(trade.entry_date), exitDate: String(trade.exit_date),
      entryPrice: Number(trade.entry_price), exitPrice: Number(trade.exit_price), position: Number(trade.position),
      grossReturn: Number(trade.gross_return), netReturn: Number(trade.net_return),
      holdingDays: Number(trade.holding_days), exitReason: String(trade.exit_reason),
    })),
    diagnostics: {
      inputSignalCount: Number(diagnostics.input_signal_count), acceptedSignalCount: Number(diagnostics.accepted_signal_count),
      skippedSignalCount: Number(diagnostics.skipped_signal_count),
      skippedSignals: (diagnostics.skipped_signals ?? []) as string[], warnings: (diagnostics.warnings ?? []) as string[],
    },
  }
}

function toMarketDataset(item: Record<string, unknown>): QuantMarketDataset {
  return {
    datasetId: String(item.dataset_id), dataVersion: String(item.data_version),
    manifestSha256: String(item.manifest_sha256), authorizationStatus: String(item.authorization_status),
    adjustment: String(item.adjustment), coverageStart: String(item.coverage_start),
    coverageEnd: String(item.coverage_end), securities: (item.securities ?? []) as string[],
    capabilities: (item.capabilities ?? {}) as Record<string, boolean>,
    limitations: (item.limitations ?? []) as string[], status: String(item.status),
    frozenBy: item.frozen_by ? String(item.frozen_by) : undefined,
    frozenAt: item.frozen_at ? String(item.frozen_at) : undefined,
  }
}

function toQuantSignalSet(item: Record<string, unknown>): QuantSignalSet {
  return {
    signalSetId: String(item.signal_set_id), name: String(item.name), version: String(item.version),
    contentSha256: String(item.content_sha256), signalCount: Number(item.signal_count),
    humanConfirmedOnly: Boolean(item.human_confirmed_only), evaluationTrack: String(item.evaluation_track),
    status: String(item.status), frozenBy: item.frozen_by ? String(item.frozen_by) : undefined,
    frozenAt: item.frozen_at ? String(item.frozen_at) : undefined,
  }
}

function toPortfolioRun(item: Record<string, unknown>): PortfolioBacktestRun {
  const raw = item.result as Record<string, unknown>
  const signalResearch = (raw.signal_research ?? {}) as Record<string, unknown>
  const risk = (raw.risk_attribution ?? {}) as Record<string, unknown>
  const diagnostics = (raw.diagnostics ?? {}) as Record<string, unknown>
  const validationQuality = raw.validation_quality as Record<string, unknown> | undefined
  return {
    runId: String(item.run_id), name: String(item.name), marketDatasetId: String(item.market_dataset_id),
    signalSetId: String(item.signal_set_id), methodologyVersion: String(item.methodology_version),
    evaluationTrack: String(item.evaluation_track), generatedAt: String(item.generated_at),
    parameters: (item.parameters ?? {}) as Record<string, unknown>,
    result: {
      metrics: (raw.metrics ?? {}) as Record<string, number | string | null>,
      equityCurve: (raw.equity_curve ?? []) as Array<Record<string, number | string>>,
      walkForward: (raw.walk_forward ?? []) as Array<Record<string, number | string>>,
      signalResearch: {
        observationCount: Number(signalResearch.observation_count ?? 0),
        ic: signalResearch.ic as number | string | null | undefined,
        rankIc: signalResearch.rank_ic as number | string | null | undefined,
        quantileReturns: (signalResearch.quantile_returns ?? {}) as Record<string, number | string>,
      },
      riskAttribution: {
        security: (risk.security ?? {}) as Record<string, number | string>,
        industry: (risk.industry ?? {}) as Record<string, number | string>,
        factorExposure: (risk.factor_exposure ?? {}) as Record<string, number | string>,
        residual: (risk.residual ?? 0) as number | string,
      },
      validationQuality: validationQuality ? {
        status: String(validationQuality.status), label: String(validationQuality.label),
        alphaClaimAllowed: Boolean(validationQuality.alpha_claim_allowed),
        reasons: (validationQuality.reasons ?? []) as string[],
        uniqueSecurityCount: Number(validationQuality.unique_security_count ?? 0),
        nonzeroSignalCount: Number(validationQuality.nonzero_signal_count ?? 0),
        observationCount: Number(validationQuality.observation_count ?? 0),
        activeTradingDays: Number(validationQuality.active_trading_days ?? 0),
      } : undefined,
      diagnostics: {
        acceptedSignalCount: Number(diagnostics.accepted_signal_count ?? 0),
        inputSignalCount: Number(diagnostics.input_signal_count ?? 0),
        skippedSignals: (diagnostics.skipped_signals ?? []) as string[],
        blockedTrades: (diagnostics.blocked_trades ?? []) as string[],
        warnings: (diagnostics.warnings ?? []) as string[],
      },
    },
  }
}

export async function getQuantCatalog(): Promise<QuantCatalog> {
  if (useMock) return {
    defaultMarketDatasetId: mockMarketDataset.datasetId,
    marketDatasets: [mockMarketDataset], signalSets: [mockQuantSignalSet],
    evaluationSeparation: {
      semanticEvaluation: 'gold_semantic_accuracy', retrievalEvaluation: 'retrieval_ranking_quality',
      alphaValidation: 'alpha_validation', hardRule: '回测收益不得替代金标准确率、检索门禁或人工确认',
    },
  }
  const body = await request<Record<string, unknown>>('/api/quant/catalog')
  const separation = body.evaluation_separation as Record<string, unknown>
  return {
    defaultMarketDatasetId: body.default_market_dataset_id == null ? null : String(body.default_market_dataset_id),
    marketDatasets: ((body.market_datasets ?? []) as Array<Record<string, unknown>>).map(toMarketDataset),
    signalSets: ((body.signal_sets ?? []) as Array<Record<string, unknown>>).map(toQuantSignalSet),
    evaluationSeparation: {
      semanticEvaluation: String(separation.semantic_evaluation),
      retrievalEvaluation: String(separation.retrieval_evaluation),
      alphaValidation: String(separation.alpha_validation), hardRule: String(separation.hard_rule),
    },
  }
}

export async function getQuantFactors(): Promise<QuantFactorDefinition[]> {
  if (useMock) return [
    {
      factorId: 'confirmed_event_direction_strength', name: '人工确认事件方向与强度',
      category: 'alpha_input', description: '将人工确认方向与强度映射为组合研究分数。',
      formula: 'direction_sign × strength_weight', frequency: '事件驱动',
      coverageScope: '已冻结且可追溯的人工确认信号', inputFields: ['direction', 'strength'],
      status: 'active', version: '1.0.0', methodologyVersion: 'portfolio-research-v3', owner: 'quant-research',
      publishedAt: '2026-09-01',
      enabledByDefault: true, limitations: ['AI 判断置信度不参与 Alpha 权重'],
    },
    {
      factorId: 'industry_neutralization', name: '行业中性约束', category: 'risk_control',
      description: '在每个有信号行业内去均值。', formula: 'score - mean(score within industry)',
      frequency: '每次再平衡', coverageScope: '所选证券的点时行业截面',
      inputFields: ['industry', 'signal_score'], status: 'gated',
      version: '1.0.0', methodologyVersion: 'portfolio-research-v3', owner: 'quant-research',
      publishedAt: '2026-09-01', enabledByDefault: false,
      limitations: ['每个有信号行业至少需要两只证券；单例行业将硬阻断'],
    },
    {
      factorId: 'momentum_20_60_120', name: '20/60/120 日动量', category: 'alpha_candidate',
      description: '检验事件信号与价格趋势的增量解释力。',
      formula: 'adjusted_close[t] / adjusted_close[t-window] - 1', frequency: '日频',
      coverageScope: '待扩大后的事前样本', inputFields: ['adjusted_close', 'trading_calendar'],
      status: 'planned', version: '1.0.0', methodologyVersion: 'portfolio-research-v3', owner: 'quant-research',
      publishedAt: '2026-09-01',
      enabledByDefault: false, limitations: ['尚未进入当前组合权重或结果宣称'],
    },
  ]
  const body = await request<Array<Record<string, unknown>>>('/api/quant/factors')
  return body.map((item) => ({
    factorId: String(item.factor_id), name: String(item.name), category: String(item.category),
    description: String(item.description), formula: String(item.formula),
    frequency: String(item.frequency), coverageScope: String(item.coverage_scope),
    inputFields: (item.input_fields ?? []) as string[], status: String(item.status),
    version: String(item.version), methodologyVersion: String(item.methodology_version), owner: String(item.owner),
    publishedAt: String(item.published_at),
    deprecatedAt: item.deprecated_at ? String(item.deprecated_at) : undefined,
    enabledByDefault: Boolean(item.enabled_by_default), limitations: (item.limitations ?? []) as string[],
  }))
}

function toPortfolioTemplateConfig(item: Record<string, unknown>): PortfolioBacktestRequest['config'] {
  return {
    initialCapital: Number(item.initial_capital), rollingWindowDays: Number(item.rolling_window_days),
    walkForwardDays: Number(item.walk_forward_days), rebalanceDays: Number(item.rebalance_days),
    transactionCostBps: Number(item.transaction_cost_bps), slippageBps: Number(item.slippage_bps),
    maxSecurityWeight: Number(item.max_security_weight), maxIndustryWeight: Number(item.max_industry_weight),
    capacityParticipationRate: Number(item.capacity_participation_rate),
    neutralizeIndustry: Boolean(item.neutralize_industry), neutralizeMarketCap: Boolean(item.neutralize_market_cap),
    enforceCapacity: Boolean(item.enforce_capacity), allowShort: Boolean(item.allow_short),
  }
}

export async function getQuantModelTemplates(): Promise<QuantModelTemplate[]> {
  if (useMock) return [
    {
      templateId: 'confirmed-event-research-v3', name: '人工确认事件研究', version: '3.0.0',
      status: 'active', description: '以人工确认的事件方向与强度构建组合。',
      methodologyVersion: 'portfolio-research-v3', alphaFactorIds: ['confirmed_event_direction_strength'],
      controlFactorIds: ['adv20_capacity', 'industry_neutralization'],
      defaultConfig: {
        initialCapital: 1_000_000, rollingWindowDays: 60, walkForwardDays: 20, rebalanceDays: 5,
        transactionCostBps: 10, slippageBps: 5, maxSecurityWeight: .2, maxIndustryWeight: .4,
        capacityParticipationRate: .1, neutralizeIndustry: false, neutralizeMarketCap: false,
        enforceCapacity: true, allowShort: true,
      },
      requiredConfig: {}, sampleGate: { minimumUniqueSecurities: 20, minimumObservations: 100, minimumActiveTradingDays: 60 },
      owner: 'quant-research', publishedAt: '2026-09-01', limitations: ['达到样本门槛前只用于工程验证'],
    },
  ]
  const body = await request<Array<Record<string, unknown>>>('/api/quant/model-templates')
  return body.map((item) => {
    const gate = item.sample_gate as Record<string, unknown>
    const required = item.required_config as Record<string, unknown>
    return {
      templateId: String(item.template_id), name: String(item.name), version: String(item.version),
      status: String(item.status), description: String(item.description),
      methodologyVersion: String(item.methodology_version),
      alphaFactorIds: (item.alpha_factor_ids ?? []) as string[],
      controlFactorIds: (item.control_factor_ids ?? []) as string[],
      defaultConfig: toPortfolioTemplateConfig(item.default_config as Record<string, unknown>),
      requiredConfig: {
        ...(required.neutralize_industry === undefined ? {} : { neutralizeIndustry: Boolean(required.neutralize_industry) }),
        ...(required.neutralize_market_cap === undefined ? {} : { neutralizeMarketCap: Boolean(required.neutralize_market_cap) }),
        ...(required.enforce_capacity === undefined ? {} : { enforceCapacity: Boolean(required.enforce_capacity) }),
        ...(required.allow_short === undefined ? {} : { allowShort: Boolean(required.allow_short) }),
      },
      sampleGate: {
        minimumUniqueSecurities: Number(gate.minimum_unique_securities),
        minimumObservations: Number(gate.minimum_observations),
        minimumActiveTradingDays: Number(gate.minimum_active_trading_days),
      },
      owner: String(item.owner), publishedAt: item.published_at ? String(item.published_at) : undefined,
      deprecatedAt: item.deprecated_at ? String(item.deprecated_at) : undefined,
      limitations: (item.limitations ?? []) as string[],
    }
  })
}

export async function getMarketDatasetDetail(datasetId: string): Promise<QuantMarketDatasetDetail> {
  if (useMock) {
    if (datasetId !== mockMarketDataset.datasetId) throw new Error('冻结行情数据集不存在')
    return {
      ...mockMarketDataset, isDefault: true, manifestVerified: true,
      assets: [
        { name: 'bars', path: 'bars.json', sha256: 'c'.repeat(64), byteSize: 2_580_000, verified: true },
        { name: 'calendar', path: 'calendar.json', sha256: 'd'.repeat(64), byteSize: 18_400, verified: true },
        { name: 'market_cap', path: 'market_cap.json', sha256: 'e'.repeat(64), byteSize: 940_000, verified: true },
      ],
      sourcePriority: ['Tushare（点时市值）', 'AkShare（前复权行情）'],
      authorizationScope: '公开行情研究与内部量化验证', timezone: 'Asia/Shanghai',
      adjustmentAnchorDate: '2026-08-28', availableSignalSets: [mockQuantSignalSet], backtestCount: 2,
      securityMetadata: mockMarketDataset.securities.map((securityId) => ({
        securityId,
        market: ['00175', '09868'].includes(securityId) ? '港股' : 'A股',
        currency: ['00175', '09868'].includes(securityId) ? 'HKD' : 'CNY',
        industry: ['688981', '603986', '002371'].includes(securityId) ? '芯片半导体' : ['600276', '603259', '000538'].includes(securityId) ? '医药' : '新能源汽车',
        benchmarkId: '000001', coverageStart: mockMarketDataset.coverageStart,
        coverageEnd: mockMarketDataset.coverageEnd, rowCount: 600,
        marketCapCount: ['00175', '09868'].includes(securityId) ? 0 : 600,
        marketCapComplete: !['00175', '09868'].includes(securityId),
      })),
    }
  }
  const item = await request<Record<string, unknown>>(`/api/quant/market-datasets/${encodeURIComponent(datasetId)}`)
  return {
    ...toMarketDataset(item), isDefault: Boolean(item.is_default),
    manifestVerified: Boolean(item.manifest_verified),
    assets: ((item.assets ?? []) as Array<Record<string, unknown>>).map((asset) => ({
      name: String(asset.name), path: String(asset.path), sha256: String(asset.sha256),
      byteSize: asset.byte_size == null ? undefined : Number(asset.byte_size), verified: Boolean(asset.verified),
    })),
    sourcePriority: (item.source_priority ?? []) as string[],
    authorizationScope: item.authorization_scope ? String(item.authorization_scope) : undefined,
    timezone: String(item.timezone),
    adjustmentAnchorDate: item.adjustment_anchor_date ? String(item.adjustment_anchor_date) : undefined,
    availableSignalSets: ((item.available_signal_sets ?? []) as Array<Record<string, unknown>>).map(toQuantSignalSet),
    backtestCount: Number(item.backtest_count),
    securityMetadata: ((item.security_metadata ?? []) as Array<Record<string, unknown>>).map((security) => ({
      securityId: String(security.security_id), market: String(security.market),
      currency: String(security.currency), industry: String(security.industry),
      benchmarkId: String(security.benchmark_id), coverageStart: String(security.coverage_start),
      coverageEnd: String(security.coverage_end), rowCount: Number(security.row_count),
      marketCapCount: Number(security.market_cap_count), marketCapComplete: Boolean(security.market_cap_complete),
    })),
  }
}

export async function getQuantSignalSetDetail(signalSetId: string): Promise<QuantSignalSetDetail> {
  if (useMock) return {
    ...mockQuantSignalSet,
    signalSetId,
    visibleSignalCount: 3,
    signals: ['688981', '603986', '002371'].map((securityId, index) => ({
      signalId: `SIG-${securityId}`, securityId,
      disclosedAt: '2026-08-20T18:00:00+08:00', generatedAt: '2026-08-20T18:05:00+08:00',
      direction: index === 2 ? '冲突' : '支持', strength: '高', confidence: .8,
      confidenceRole: 'ai_judgement_metadata_only', confidenceUsedForAlphaWeight: false,
      confirmationStatus: '已确认', sourceEvidenceId: `EVD-${securityId}`,
      sourceRelationId: `REL-${securityId}`, sourceRelationStatus: '已确认',
      thesisId: 'THS-QUANT', hypothesisId: 'HYP-QUANT',
      sourceLocator: `DOC-${securityId}#segment-1`, sourceDocumentId: `DOC-${securityId}`,
      sourceDocumentTitle: `${securityId} 公开披露资料`,
    })),
  }
  const item = await request<Record<string, unknown>>(`/api/quant/signal-sets/${encodeURIComponent(signalSetId)}`)
  return {
    ...toQuantSignalSet(item),
    visibleSignalCount: Number(item.visible_signal_count),
    signals: ((item.signals ?? []) as Array<Record<string, unknown>>).map((signal) => ({
      signalId: String(signal.signal_id), securityId: String(signal.security_id),
      disclosedAt: String(signal.disclosed_at), generatedAt: String(signal.generated_at),
      direction: String(signal.direction), strength: String(signal.strength),
      confidence: Number(signal.confidence), confirmationStatus: String(signal.confirmation_status),
      sourceEvidenceId: String(signal.source_evidence_id), sourceRelationId: String(signal.source_relation_id),
      sourceRelationStatus: String(signal.source_relation_status), thesisId: String(signal.thesis_id),
      hypothesisId: String(signal.hypothesis_id), sourceLocator: String(signal.source_locator),
      sourceDocumentId: signal.source_document_id ? String(signal.source_document_id) : undefined,
      sourceDocumentTitle: signal.source_document_title ? String(signal.source_document_title) : undefined,
      confidenceRole: signal.confidence_role ? String(signal.confidence_role) : undefined,
      confidenceUsedForAlphaWeight: Boolean(signal.confidence_used_for_alpha_weight),
    })),
  }
}

export async function registerDefaultMarketDataset(): Promise<QuantMarketDataset> {
  if (useMock) throw new Error('Mock 模式不登记真实行情')
  return toMarketDataset(await request<Record<string, unknown>>('/api/quant/market-datasets/register-default', { method: 'POST' }))
}

export async function runPortfolioBacktest(payload: PortfolioBacktestRequest): Promise<PortfolioBacktestRun> {
  if (useMock) throw new Error('Mock 模式不运行 Alpha 验证')
  const body = {
    name: payload.name, market_dataset_id: payload.marketDatasetId, signal_set_id: payload.signalSetId,
    model_template_id: payload.modelTemplateId,
    security_ids: payload.securityIds, start: payload.start, end: payload.end,
    config: {
      initial_capital: payload.config.initialCapital, rolling_window_days: payload.config.rollingWindowDays,
      walk_forward_days: payload.config.walkForwardDays, rebalance_days: payload.config.rebalanceDays,
      transaction_cost_bps: payload.config.transactionCostBps, slippage_bps: payload.config.slippageBps,
      max_security_weight: payload.config.maxSecurityWeight, max_industry_weight: payload.config.maxIndustryWeight,
      capacity_participation_rate: payload.config.capacityParticipationRate,
      neutralize_industry: payload.config.neutralizeIndustry,
      neutralize_market_cap: payload.config.neutralizeMarketCap,
      enforce_capacity: payload.config.enforceCapacity, allow_short: payload.config.allowShort,
    },
  }
  return toPortfolioRun(await request<Record<string, unknown>>('/api/quant/portfolio-backtests', { method: 'POST', body: JSON.stringify(body) }))
}

export async function listPortfolioBacktests(): Promise<PortfolioBacktestRun[]> {
  if (useMock) return []
  const body = await request<Array<Record<string, unknown>>>('/api/quant/portfolio-backtests')
  return body.map(toPortfolioRun)
}

export async function getPortfolioBacktest(runId: string): Promise<PortfolioBacktestRun> {
  if (useMock) {
    const run = (await listPortfolioBacktests()).find((item) => item.runId === runId)
    if (!run) throw new Error('组合回测不存在')
    return run
  }
  const item = await request<Record<string, unknown>>(`/api/quant/portfolio-backtests/${encodeURIComponent(runId)}`)
  return toPortfolioRun(item)
}

function mockGoldQuality(): GoldQualityReport {
  return {
    schemaVersion: 'gold-quality-v2', goldVersion: 'final-gold-v3-20260826',
    goldState: 'final', createdAt: '2026-08-26T16:37:32+08:00',
    sourcePackage: 'independent-gold-v3-20260826',
    summary: { totalSamples: 360, consensusSamples: 199, adjudicatedSamples: 161, goldSamples: 360, evaluationEligibleSamples: 358, pendingAdjudication: 0, consensusCoverage: .5528, goldCoverage: 1, evaluationReady: true, productionGoldReady: true, graphRagRolloutReady: false },
    tasks: [
      { task: 'event', label: '事件语义', total: 120, consensus: 73, adjudicated: 47, final: 120, evaluationEligible: 119, pending: 0, coverage: 1, coreFields: ['事件类别', '主要关联假设', '影响方向', '影响强度', '直接性'], file: 'final_event_gold_v3.csv' },
      { task: 'body_fact', label: '正文事实', total: 60, consensus: 31, adjudicated: 29, final: 60, evaluationEligible: 59, pending: 0, coverage: 1, coreFields: ['是否存在可抽取事实', '事实类型', '变化方向'], file: 'final_body_fact_gold_v3.csv' },
      { task: 'graph_relevance', label: 'Graph RAG 相关性', total: 180, consensus: 95, adjudicated: 85, final: 180, evaluationEligible: 180, pending: 0, coverage: 1, coreFields: ['相关性等级', '关系路径可成立'], file: 'final_graph_relevance_gold_v3.csv' },
    ],
    agreement: [
      { task: 'event', field: '影响方向', n: 120, agreement: .8917, cohenKappa: .8188 },
      { task: 'body_fact', field: '变化方向', n: 60, agreement: .6333, cohenKappa: .488 },
      { task: 'graph_relevance', field: '相关性等级', n: 180, agreement: .6389, cohenKappa: .5154 },
    ],
    gates: [
      { code: 'workbook_validation', label: '工作簿结构与字段契约', status: 'passed', current: true, target: true, message: 'A/B 两份回收工作簿均通过结构校验。' },
      { code: 'adjudication_complete', label: '分歧裁决完成', status: 'passed', current: 161, target: 161, message: '161 个分歧判断均已形成独立裁决。' },
      { code: 'final_gold_freeze', label: '最终硬金标冻结', status: 'passed', current: 360, target: 360, message: '三个任务均已冻结最终标签与文件哈希。' },
      { code: 'evaluation_eligibility', label: '离线评测可用样本', status: 'warning', current: 358, target: 360, message: '2 个原文不可提取样本保留审计但默认排除。' },
      { code: 'graph_rag_system_benchmark', label: 'Graph RAG 系统离线基准', status: 'blocked', current: false, target: true, message: '最终金标系统基准：Recall@5=0.7832，MRR=0.8367，Top-1=0.6667；权限/证券/未来泄漏=0/0/0。' },
    ],
    qualityExceptions: [
      { task: 'event', sampleId: 'G3-E061', reason: '正文不可提取、低置信度、关键证据原文缺失' },
      { task: 'body_fact', sampleId: 'G3-B053', reason: '正文不可提取、低置信度' },
    ],
    files: [],
    graphRagBenchmark: {
      benchmarkVersion: 'graph-rag-final-gold-v1', generatedAt: '2026-08-26T17:30:00Z',
      reportPath: 'analytics/experiments/20260826-graph-rag-final-gold-v3/graph_rag_benchmark.json', rolloutReady: false,
      evaluatedQueries: 27, positiveQueries: 25,
      textBaseline: { evaluatedQueries: 27, positiveQueries: 25, recallAtK: { '1': .2308, '3': .5283, '5': .7399, '10': .9489 }, hitRateAtK: { '1': .72, '3': .96, '5': .96, '10': 1 }, ndcgAtK: { '1': .6343, '3': .7361, '5': .7804, '10': .833 }, mrr: .8333, top1Correctness: .6667, unjudgedResultCount: 0 },
      graphRag: { evaluatedQueries: 27, positiveQueries: 25, recallAtK: { '1': .2308, '3': .5417, '5': .7832, '10': .9884 }, hitRateAtK: { '1': .72, '3': .96, '5': 1, '10': 1 }, ndcgAtK: { '1': .6343, '3': .7419, '5': .8088, '10': .8521 }, mrr: .8367, top1Correctness: .6667, unjudgedResultCount: 0 },
      safety: { permissionLeakageCount: 0, securityLeakageCount: 0, futureLeakageCount: 0, canaryContentLeakageCount: 0, adversarialCanaryCount: 81, pathProvenanceValid: 81, pathProvenanceRelevantHits: 81, pathProvenanceRate: 1 },
      gates: [
        { code: 'recall_at_5', current: .7832, target: .8, passed: false },
        { code: 'mrr', current: .8367, target: .65, passed: true },
        { code: 'top1_correctness', current: .6667, target: .7, passed: false },
        { code: 'permission_leakage', current: 0, target: 0, passed: true },
      ],
    },
  }
}

function toRankingMetrics(item: Record<string, unknown>) {
  return {
    evaluatedQueries: Number(item.evaluated_queries), positiveQueries: Number(item.positive_queries),
    recallAtK: (item.recall_at_k ?? {}) as Record<string, number>, hitRateAtK: (item.hit_rate_at_k ?? {}) as Record<string, number>,
    ndcgAtK: (item.ndcg_at_k ?? {}) as Record<string, number>, mrr: Number(item.mrr),
    top1Correctness: Number(item.top1_correctness), unjudgedResultCount: Number(item.unjudged_result_count),
  }
}

function toGraphRagBenchmark(item: Record<string, unknown>): NonNullable<GoldQualityReport['graphRagBenchmark']> {
  const safety = (item.safety ?? {}) as Record<string, unknown>
  return {
    benchmarkVersion: String(item.benchmark_version), generatedAt: String(item.generated_at), reportPath: String(item.report_path),
    rolloutReady: Boolean(item.rollout_ready), evaluatedQueries: Number(item.evaluated_queries), positiveQueries: Number(item.positive_queries),
    textBaseline: toRankingMetrics((item.text_baseline ?? {}) as Record<string, unknown>),
    graphRag: toRankingMetrics((item.graph_rag ?? {}) as Record<string, unknown>),
    safety: {
      permissionLeakageCount: Number(safety.permission_leakage_count), securityLeakageCount: Number(safety.security_leakage_count),
      futureLeakageCount: Number(safety.future_leakage_count), canaryContentLeakageCount: Number(safety.canary_content_leakage_count),
      adversarialCanaryCount: Number(safety.adversarial_canary_count), pathProvenanceValid: Number(safety.path_provenance_valid),
      pathProvenanceRelevantHits: Number(safety.path_provenance_relevant_hits), pathProvenanceRate: Number(safety.path_provenance_rate),
    },
    gates: ((item.gates ?? []) as Array<Record<string, unknown>>).map((gate) => ({ code: String(gate.code), current: gate.current as boolean | number, target: gate.target as boolean | number, passed: Boolean(gate.passed) })),
  }
}

export async function getGoldQuality(): Promise<GoldQualityReport> {
  if (useMock) return mockGoldQuality()
  const item = await request<Record<string, unknown>>('/api/evaluation/gold-quality')
  const summary = item.summary as Record<string, unknown>
  const systemBenchmarks = (item.system_benchmarks ?? {}) as Record<string, unknown>
  return {
    schemaVersion: String(item.schema_version), goldVersion: String(item.gold_version),
    goldState: item.gold_state as GoldQualityReport['goldState'], createdAt: String(item.created_at),
    sourcePackage: String(item.source_package),
    summary: {
      totalSamples: Number(summary.total_samples), consensusSamples: Number(summary.consensus_samples),
      adjudicatedSamples: Number(summary.adjudicated_samples ?? 0), goldSamples: Number(summary.gold_samples ?? summary.consensus_samples),
      evaluationEligibleSamples: Number(summary.evaluation_eligible_samples ?? summary.consensus_samples),
      pendingAdjudication: Number(summary.pending_adjudication), consensusCoverage: Number(summary.consensus_coverage),
      goldCoverage: Number(summary.gold_coverage ?? summary.consensus_coverage),
      evaluationReady: Boolean(summary.evaluation_ready), productionGoldReady: Boolean(summary.production_gold_ready),
      graphRagRolloutReady: Boolean(summary.graph_rag_rollout_ready),
    },
    tasks: ((item.tasks ?? []) as Array<Record<string, unknown>>).map((task) => ({
      task: String(task.task), label: String(task.label), total: Number(task.total),
      consensus: Number(task.consensus), adjudicated: Number(task.adjudicated ?? 0), final: Number(task.final ?? task.consensus),
      evaluationEligible: Number(task.evaluation_eligible ?? task.consensus), pending: Number(task.pending), coverage: Number(task.coverage),
      coreFields: (task.core_fields ?? []) as string[], file: String(task.file),
    })),
    agreement: ((item.agreement ?? []) as Array<Record<string, unknown>>).map((metric) => ({
      task: String(metric.task), field: String(metric.field), n: Number(metric.n), agreement: Number(metric.agreement),
      cohenKappa: metric.cohen_kappa == null ? undefined : Number(metric.cohen_kappa),
    })),
    gates: ((item.gates ?? []) as Array<Record<string, unknown>>).map((gate) => ({
      code: String(gate.code), label: String(gate.label), status: gate.status as GoldQualityReport['gates'][number]['status'],
      current: gate.current == null ? undefined : gate.current as boolean | number,
      target: gate.target == null ? undefined : gate.target as boolean | number, message: String(gate.message),
    })),
    qualityExceptions: ((item.quality_exceptions ?? []) as Array<Record<string, unknown>>).map((exception) => ({
      task: String(exception.task), sampleId: String(exception.sample_id), reason: String(exception.reason),
    })),
    files: ((item.files ?? []) as Array<Record<string, unknown>>).map((file) => ({
      path: String(file.path), rows: Number(file.rows), sha256: String(file.sha256),
    })),
    graphRagBenchmark: systemBenchmarks.graph_rag ? toGraphRagBenchmark(systemBenchmarks.graph_rag as Record<string, unknown>) : undefined,
  }
}
