/**
 * AI Investment Copilot 前端接口门面。
 *
 * 使用方式：复制到新前端的 api 目录，或直接作为 workspace 源文件引用。
 * 所有 Decimal 均保持 string，避免浏览器浮点精度损失。
 * Agent 接口只生成候选；正式绑定、复核和状态变更必须调用人工闸门接口。
 */

export type DecimalString = string
export type IsoDate = string
export type IsoDateTime = string

export interface ApiClientOptions {
  baseUrl?: string
  token?: string
  /** 仅供本地 trusted_headers 模式使用，必须为 ASCII。 */
  userId?: string
  /** 仅供本地 trusted_headers 模式使用。 */
  teams?: string[]
  fetchImpl?: typeof fetch
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: unknown,
  ) {
    super(typeof detail === 'string' ? detail : `请求失败 (${status})`)
    this.name = 'ApiError'
  }
}

export interface MetricMapping {
  mapping_id: string
  hypothesis_id: string
  metric_id: string
  metric_name: string
  metric_unit: string
  metric_version: string
  expected_direction: '越高越好' | '越低越好' | '不低于阈值' | '不高于阈值'
  expected_value: DecimalString | null
  invalidation_threshold: DecimalString | null
  invalidation_consecutive_periods: number | null
  expectation_source: string
  confirmation_status: string
}

export interface Hypothesis {
  hypothesis_id: string
  statement: string
  hypothesis_type: string
  importance: '核心' | '辅助'
  status: string
  observation_window: string | null
  invalidation_rule: string | null
  causal_level: string | null
  logic_dimension: string | null
  quality_warning: string | null
  metric_suggestions: Record<string, unknown>[]
  mappings: MetricMapping[]
}

export interface Thesis {
  thesis_id: string
  security_id: string
  title: string
  direction: string
  core_view: string
  status: string
  owner: string
  visibility: string
  version: number
  established_on: IsoDate
  horizon_end_on: IsoDate | null
  next_review_at: IsoDate | null
  thesis_kind: string
  thesis_series_id: string | null
  hypotheses: Hypothesis[]
  risk_suggestions: Record<string, unknown>[]
  invalidation_suggestions: Record<string, unknown>[]
}

export interface MetricDefinition {
  metric_id: string
  version: string
  name: string
  unit: string
  category: string
  definition: string
  frequency: string
  period_type: string
  source_id: string
  expected_direction: string | null
  status: string
}

export interface AgentCandidate<TPayload = Record<string, unknown>> {
  run_id: string
  task: string
  status: string
  ai_status: string | null
  requires_human_review: boolean
  payload: TPayload
  errors: string[]
}

export interface Evidence {
  evidence_id: string
  thesis_id: string
  hypothesis_id: string
  evidence_type: string
  direction: string
  evidence_locator: string
  confirmation_status: string
  ai_status: string | null
  model_version: string | null
  prompt_version: string | null
  strength: string | null
  strength_score: DecimalString | null
  ai_confidence: DecimalString | null
  confirmed_by: string | null
  confirmed_at: IsoDateTime | null
}

export interface EvidenceFeedPage {
  items: Record<string, unknown>[]
  next_cursor: string | null
}

export type JobStage =
  | 'queued'
  | 'parsing'
  | 'indexed'
  | 'analysis_queued'
  | 'analysis_started'
  | 'extracting_events'
  | 'matching_hypotheses'
  | 'completed'
  | 'analysis_timeout'
  | 'analysis_failed'
  | string

export interface DocumentJobResult {
  ok?: boolean
  stage?: JobStage
  parsed?: boolean
  reason?: string
  document_id?: string
  segment_count?: number
  fact_count?: number
  event_count?: number
  candidate_evidence_count?: number
  matched_thesis_ids?: string[]
  duplicate?: boolean
  manual_review?: boolean
  [key: string]: unknown
}

export interface JobAccepted {
  job_id: string
  document_id: string
  status: string
}

export interface JobStatus {
  job_id: string
  status: string
  success: boolean | null
  result: DocumentJobResult | null
  enqueue_time: IsoDateTime | null
  start_time: IsoDateTime | null
  finish_time: IsoDateTime | null
}

export interface UploadDocumentInput {
  file: File
  securityId?: string
  thesisId?: string
  publishedAt?: IsoDateTime
  view?: string
}

export interface PollOptions {
  intervalMs?: number
  timeoutMs?: number
  signal?: AbortSignal
  onProgress?: (job: JobStatus) => void
}

export interface MetricMappingInput {
  mapping_id?: string
  metric_id: string
  metric_version?: string
  expected_direction: MetricMapping['expected_direction']
  expected_value?: DecimalString | null
  invalidation_threshold?: DecimalString | null
  invalidation_consecutive_periods?: number | null
  expectation_source: string
}

export class InvestmentCopilotApi {
  private readonly baseUrl: string
  private readonly fetcher: typeof fetch
  private readonly headers: Record<string, string>

  constructor(options: ApiClientOptions = {}) {
    this.baseUrl = (options.baseUrl ?? '/api').replace(/\/$/, '')
    this.fetcher = options.fetchImpl ?? fetch
    this.headers = {}
    if (options.token) this.headers.Authorization = `Bearer ${options.token}`
    if (options.userId) this.headers['X-User-Id'] = options.userId
    if (options.teams?.length) this.headers['X-User-Teams'] = options.teams.join(',')
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await this.fetcher(`${this.baseUrl}${path}`, {
      ...init,
      headers: { ...this.headers, ...init.headers },
    })
    if (response.status === 204) return undefined as T
    const contentType = response.headers.get('content-type') ?? ''
    const body = contentType.includes('application/json')
      ? await response.json()
      : await response.text()
    if (!response.ok) {
      const detail = body && typeof body === 'object' && 'detail' in body
        ? (body as { detail: unknown }).detail
        : body
      throw new ApiError(response.status, detail)
    }
    return body as T
  }

  // 逻辑草稿：RAG + LogicDraftAgent，只产生待人工确认草稿。
  createThesisDraft(input: { security_id: string; view?: string; document_id?: string; use_rag?: boolean }) {
    return this.request<Thesis>('/theses/drafts', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ use_rag: true, view: '', ...input }),
    })
  }

  listTheses(params: { status?: string[]; security_id?: string[]; owner?: string; keyword?: string; limit?: number; cursor?: string } = {}) {
    const query = new URLSearchParams()
    Object.entries(params).forEach(([key, value]) => {
      if (Array.isArray(value)) value.forEach((item) => query.append(key, item))
      else if (value != null && value !== '') query.set(key, String(value))
    })
    return this.request<{ items: Thesis[]; next_cursor: string | null }>(`/theses?${query}`)
  }

  getThesis(thesisId: string) {
    return this.request<Thesis>(`/theses/${encodeURIComponent(thesisId)}`)
  }

  checkHypothesisQuality(thesisId: string) {
    return this.request<Thesis>(`/theses/${encodeURIComponent(thesisId)}/quality-check`, { method: 'POST' })
  }

  updateHypothesis(thesisId: string, hypothesisId: string, input: {
    statement: string
    hypothesis_type?: string
    importance: '核心' | '辅助'
    observation_window?: string | null
    invalidation_rule?: string | null
  }) {
    return this.request<Thesis>(`/theses/${encodeURIComponent(thesisId)}/hypotheses/${encodeURIComponent(hypothesisId)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
    })
  }

  listMetrics(keyword = '', limit = 50) {
    const query = new URLSearchParams({ keyword, limit: String(limit) })
    return this.request<MetricDefinition[]>(`/metrics?${query}`)
  }

  recommendMetrics(thesisId: string, hypothesisId: string, input: { top_k?: number; as_of?: IsoDate | null } = {}) {
    return this.request<AgentCandidate>(`/agent/theses/${encodeURIComponent(thesisId)}/hypotheses/${encodeURIComponent(hypothesisId)}/metric-recommendations`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ top_k: 8, ...input }),
    })
  }

  explainMetrics(thesisId: string, hypothesisId: string) {
    return this.request<AgentCandidate>(`/agent/theses/${encodeURIComponent(thesisId)}/hypotheses/${encodeURIComponent(hypothesisId)}/metric-explanations`, { method: 'POST' })
  }

  confirmMetricMapping(thesisId: string, hypothesisId: string, input: MetricMappingInput) {
    return this.request<MetricMapping>(`/theses/${encodeURIComponent(thesisId)}/hypotheses/${encodeURIComponent(hypothesisId)}/mappings`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ metric_version: 'v1.0', ...input }),
    })
  }

  publishThesis(thesisId: string, input: { direction: '看多' | '看空' | '观察'; horizon_end_on: IsoDate; next_review_at: IsoDate; invalidation_require_all?: boolean }) {
    return this.request<Thesis>(`/theses/${encodeURIComponent(thesisId)}/publish`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ invalidation_require_all: true, ...input }),
    })
  }

  async uploadDocument(input: UploadDocumentInput) {
    if (input.thesisId && !input.securityId) throw new Error('关联逻辑时必须同时提供 securityId')
    const form = new FormData()
    form.append('file', input.file)
    if (input.securityId) form.append('security_id', input.securityId)
    if (input.thesisId) form.append('thesis_id', input.thesisId)
    if (input.publishedAt) form.append('published_at', input.publishedAt)
    if (input.view) form.append('view', input.view)
    return this.request<JobAccepted>('/jobs/documents', { method: 'POST', body: form })
  }

  getJob(jobId: string) {
    return this.request<JobStatus>(`/jobs/${encodeURIComponent(jobId)}`)
  }

  reanalyzeJob(jobId: string) {
    return this.request<JobAccepted>(`/jobs/${encodeURIComponent(jobId)}/reanalyze`, { method: 'POST' })
  }

  async waitForJob(jobId: string, options: PollOptions = {}): Promise<JobStatus> {
    const intervalMs = options.intervalMs ?? 800
    const deadline = Date.now() + (options.timeoutMs ?? 180_000)
    while (Date.now() < deadline) {
      if (options.signal?.aborted) throw new DOMException('任务轮询已取消', 'AbortError')
      const job = await this.getJob(jobId)
      options.onProgress?.(job)
      if (job.status === 'complete' || job.status === 'succeeded') return job
      if (job.status === 'failed' || job.status === 'dead_letter') {
        throw new ApiError(422, job.result?.reason ?? '资料处理失败')
      }
      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(resolve, intervalMs)
        options.signal?.addEventListener('abort', () => {
          clearTimeout(timer)
          reject(new DOMException('任务轮询已取消', 'AbortError'))
        }, { once: true })
      })
    }
    throw new ApiError(408, '资料处理超时；可调用 reanalyzeJob，仅重跑 AI 阶段')
  }

  listEvidence(thesisId: string) {
    return this.request<Evidence[]>(`/theses/${encodeURIComponent(thesisId)}/evidence`)
  }

  getEvidenceFeed(thesisId: string, limit = 50, cursor?: string) {
    const query = new URLSearchParams({ limit: String(limit) })
    if (cursor) query.set('cursor', cursor)
    return this.request<EvidenceFeedPage>(`/theses/${encodeURIComponent(thesisId)}/evidence-feed?${query}`)
  }

  reviewEvidenceRelation(evidenceId: string, relationId: string, input: { action: '确认' | '驳回' | '暂不判断'; reason: string }) {
    return this.request<Record<string, unknown>>(`/evidence/${encodeURIComponent(evidenceId)}/relations/${encodeURIComponent(relationId)}/review`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
    })
  }

  createReviewDraft(thesisId: string, input: { period_start: IsoDate; period_end: IsoDate }) {
    return this.request<AgentCandidate>(`/agent/theses/${encodeURIComponent(thesisId)}/review-drafts`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
    })
  }

  createRevisionDraft(thesisId: string) {
    return this.request<{ execution: AgentCandidate; revision: Record<string, unknown> }>(`/agent/theses/${encodeURIComponent(thesisId)}/revision-drafts`, { method: 'POST' })
  }

  getSuggestions(thesisId: string) {
    return this.request<Record<string, unknown>[]>(`/theses/${encodeURIComponent(thesisId)}/suggestions`)
  }

  decideStatus(thesisId: string, input: { suggestion_id: number; action: '接受' | '拒绝' | '修改'; reason: string; target_status?: string | null }) {
    return this.request<Thesis>(`/theses/${encodeURIComponent(thesisId)}/status`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
    })
  }
}

