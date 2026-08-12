import type {
  CitationContext,
  DecisionAction,
  EvidenceAnalysis,
  ScenarioUploadResult,
  Suggestion,
  ThesisDetail,
  TimelineEvent,
} from './types'

export interface ScenarioAdapter {
  readonly mode: 'real' | 'controlled-mock'
  getThesis(id: string): Promise<ThesisDetail>
  uploadMaterial(id: string, file: File): Promise<ScenarioUploadResult>
  getAnalysis(evidenceId: string, relationId: string): Promise<EvidenceAnalysis>
  getCitation(documentId: string, locator: string): Promise<CitationContext>
  getSuggestions(id: string): Promise<Suggestion[]>
  getTimeline(id: string): Promise<TimelineEvent[]>
  reviewRelation(
    evidenceId: string,
    relationId: string,
    action: '确认' | '驳回' | '暂不判断',
    reason: string,
  ): Promise<EvidenceAnalysis>
  decideStatus(
    id: string,
    suggestionId: number,
    action: DecisionAction,
    reason: string,
    targetStatus?: string,
  ): Promise<ThesisDetail>
}

const wait = (ms = 320) => new Promise((resolve) => window.setTimeout(resolve, ms))

let mockThesis: ThesisDetail = {
  thesisId: 'THS-SG-001',
  securityId: '300274',
  securityName: '阳光电源',
  title: '全球光储龙头的盈利韧性与结构性增长',
  coreView:
    '逆变器全球份额与储能系统集成能力构成双重护城河。核心验证点是海外毛利率韧性、储能交付质量与经营现金流的同步性。',
  status: '验证中',
  direction: '看多',
  owner: '徐研究员',
  version: 3,
  establishedOn: '2026-07-18',
  hypotheses: [
    {
      hypothesisId: 'HYP-SG-01',
      statement: '海外逆变器份额提升能够抵消价格竞争，维持盈利韧性',
      importance: '核心',
      supportConfirmed: 3,
      conflictConfirmed: 0,
      pending: 1,
      health: '待验证',
      healthReason: '新增毛利率证据尚待负责人确认',
      metric: { name: '海外业务毛利率', value: '38.4%', trend: 'QoQ +2.1pct' },
      invalidation: '连续两个季度海外毛利率低于 30%',
    },
    {
      hypothesisId: 'HYP-SG-02',
      statement: '储能业务规模增长可转化为稳定现金回报，而非单纯收入扩张',
      importance: '重要',
      supportConfirmed: 2,
      conflictConfirmed: 1,
      pending: 0,
      health: '有分歧',
      healthReason: '收入增速与现金转换效率出现背离',
      metric: { name: '经营现金净额', value: '¥ 48.7 亿', trend: 'YoY +18.6%' },
      invalidation: '应收账款增速连续两期显著高于收入增速',
    },
    {
      hypothesisId: 'HYP-SG-03',
      statement: '研发投入和渠道密度能够保持产品迭代领先',
      importance: '观察',
      supportConfirmed: 1,
      conflictConfirmed: 0,
      pending: 0,
      health: '稳定',
      healthReason: '研发强度与新品发布节奏保持稳定',
      metric: { name: '研发费用率', value: '6.8%', trend: 'YoY +0.4pct' },
      invalidation: '核心市场新品迭代落后主要竞争对手两个周期',
    },
  ],
}

let mockAnalysis: EvidenceAnalysis = {
  evidenceId: 'EVD-SG-DEMO-01',
  relationId: 'REL-SG-DEMO-01',
  documentId: 'DOC-SG-2025-AR',
  documentTitle: '阳光电源 2025 年年度报告',
  disclosedAt: '2026-04-18',
  factExcerpt:
    '储能行业营业收入 372.87 亿元，同比增长 49.39%；毛利率 36.49%，同比下降 0.20 个百分点。',
  hypothesisId: 'HYP-SG-01',
  hypothesisStatement: '海外逆变器份额提升能够抵消价格竞争，维持盈利韧性',
  affectedHypotheses: [
    {
      hypothesisId: 'HYP-SG-01',
      statement: '海外逆变器份额提升能够抵消价格竞争，维持盈利韧性',
      metricName: '储能业务毛利率',
      actualValue: '36.49%',
      invalidationThreshold: '30%',
      direction: 'conflict',
    },
  ],
  direction: 'conflict',
  strength: 'high',
  transmissionPath: '收入高速增长但毛利率同比下降 → 规模扩张未同步改善盈利 → 盈利质量假设出现冲突信号',
  aiConfidence: '0.84',
  modelVersion: 'preset-eval-v2.3',
  promptVersion: 'equity-impact-v4',
  evidenceLocator: 'DOC-SG-2025-AR#paragraph-184',
  resultSource: 'preset_ai_result',
  relationStatus: 'pending',
  canManage: true,
}

let mockSuggestion: Suggestion = {
  suggestionId: 2031,
  currentStatus: '验证中',
  suggestedStatus: '出现分歧',
  reasons: ['核心假设同时存在 3 条支持与 1 条冲突证据', '收入增长与毛利率变化方向出现背离'],
  triggeredHypotheses: ['HYP-SG-01'],
  ruleVersion: 'status-rule-v1.8',
}

let mockTimeline: TimelineEvent[] = [
  {
    eventId: 'T-01',
    dimension: 'material',
    occurredAt: '2026-08-12 14:31',
    actorType: 'human',
    actorName: '徐研究员',
    summary: '上传并登记固定演示资料《阳光电源 2025 年年度报告》',
    after: { documentId: 'DOC-SG-2025-AR', documentType: '年度报告' },
  },
  {
    eventId: 'T-02',
    dimension: 'ai_analysis',
    occurredAt: '2026-08-12 14:31',
    actorType: 'preset_ai',
    actorName: '预置分析引擎',
    summary: '识别收入增长与毛利率下降的背离，并提出高强度冲突候选',
    after: { direction: '冲突', strength: '高', confidence: '0.84' },
    detailUrl: '/evidence/EVD-SG-DEMO-01/analysis?thesisId=THS-SG-001&relationId=REL-SG-DEMO-01',
  },
]

const citation: CitationContext = {
  documentTitle: '阳光电源 2025 年年度报告',
  documentType: '年度报告',
  disclosedAt: '2026-04-18',
  locator: 'DOC-SG-2025-AR#paragraph-184',
  page: 34,
  previous: '公司主营业务中，光伏行业与储能行业均形成规模化收入贡献。',
  target:
    '储能行业营业收入 372.87 亿元，同比增长 49.39%；毛利率 36.49%，同比下降 0.20 个百分点。',
  next: '海外地区营业收入 539.92 亿元，同比增长 48.76%，毛利率 40.36%。',
  sourceUrl: 'https://disc.static.szse.cn/',
}

class ControlledMockAdapter implements ScenarioAdapter {
  readonly mode = 'controlled-mock' as const

  async getThesis() {
    await wait()
    return structuredClone(mockThesis)
  }

  async uploadMaterial(id: string, file: File) {
    await wait(620)
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      throw new Error('当前流程演示仅支持指定的阳光电源公开资料 PDF。')
    }
    return {
      documentId: mockAnalysis.documentId,
      evidenceIds: [mockAnalysis.evidenceId],
      relationIds: [mockAnalysis.relationId],
      resultSource: 'preset_ai_result' as const,
      duplicate: false,
      nextUrl: `/evidence/${mockAnalysis.evidenceId}/analysis?thesisId=${id}&relationId=${mockAnalysis.relationId}`,
    }
  }

  async getAnalysis() {
    await wait()
    return structuredClone(mockAnalysis)
  }

  async getCitation() {
    await wait()
    return structuredClone(citation)
  }

  async getSuggestions() {
    await wait()
    return mockSuggestion.humanAction ? [] : [structuredClone(mockSuggestion)]
  }

  async getTimeline() {
    await wait()
    return structuredClone(mockTimeline)
  }

  async reviewRelation(
    _evidenceId: string,
    _relationId: string,
    action: '确认' | '驳回' | '暂不判断',
    reason: string,
  ) {
    await wait(480)
    if (action !== '确认' && !reason.trim()) throw new Error(`${action}时必须填写人工判断依据。`)
    mockAnalysis = {
      ...mockAnalysis,
      relationStatus: action === '确认' ? 'confirmed' : action === '驳回' ? 'rejected' : 'pending',
      reviewReason: reason,
    }
    if (action === '确认') {
      const hypothesis = mockThesis.hypotheses[0]
      mockThesis = {
        ...mockThesis,
        hypotheses: [
          {
            ...hypothesis,
            conflictConfirmed: hypothesis.conflictConfirmed + 1,
            pending: Math.max(0, hypothesis.pending - 1),
            health: '有分歧',
            healthReason: '既有支持证据与新增高强度冲突证据同时成立',
          },
          ...mockThesis.hypotheses.slice(1),
        ],
      }
    }
    mockTimeline = [
      ...mockTimeline,
      {
        eventId: `T-${mockTimeline.length + 1}`,
        dimension: 'human_review',
        occurredAt: '2026-08-12 14:38',
        actorType: 'human',
        actorName: '徐研究员',
        summary: `人工${action} AI 候选关系`,
        reason,
        before: { relationStatus: '待确认' },
        after: { relationStatus: action },
      },
    ]
    return structuredClone(mockAnalysis)
  }

  async decideStatus(
    _id: string,
    _suggestionId: number,
    action: DecisionAction,
    reason: string,
    targetStatus?: string,
  ) {
    await wait(480)
    if (action !== '接受' && !reason.trim()) throw new Error(`${action}时必须填写负责人决策理由。`)
    const nextStatus =
      action === '拒绝' ? mockThesis.status : action === '修改' ? targetStatus ?? mockThesis.status : mockSuggestion.suggestedStatus
    mockSuggestion = { ...mockSuggestion, humanAction: action }
    mockThesis = { ...mockThesis, status: nextStatus, version: mockThesis.version + 1 }
    mockTimeline = [
      ...mockTimeline,
      {
        eventId: `T-${mockTimeline.length + 1}`,
        dimension: 'logic_decision',
        occurredAt: '2026-08-12 14:46',
        actorType: 'human',
        actorName: '徐研究员',
        summary: `${action}状态建议，逻辑状态更新为「${nextStatus}」`,
        reason,
        before: { status: '验证中', version: mockThesis.version - 1 },
        after: { status: nextStatus, version: mockThesis.version },
      },
    ]
    return structuredClone(mockThesis)
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init)
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { message?: string; detail?: string } | null
    throw new Error(body?.message ?? body?.detail ?? `请求失败（${response.status}）`)
  }
  return response.json() as Promise<T>
}

type Raw = Record<string, unknown>
const raw = (value: unknown): Raw => (value && typeof value === 'object' ? value as Raw : {})
const text = (value: unknown, fallback = '') => value == null ? fallback : String(value)
const number = (value: unknown, fallback = 0) => {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function mapThesis(value: unknown, healthValue?: unknown): ThesisDetail {
  const item = raw(value)
  const healthItems = Array.isArray(healthValue) ? healthValue.map(raw) : []
  const healthById = new Map(healthItems.map((health) => [text(health.hypothesis_id), health]))
  const hypotheses = Array.isArray(item.hypotheses) ? item.hypotheses.map(raw) : []
  return {
    thesisId: text(item.thesis_id),
    securityId: text(item.security_id),
    securityName: text(item.security_name, '中芯国际'),
    title: text(item.title),
    coreView: text(item.core_view),
    status: text(item.status),
    direction: text(item.direction),
    owner: text(item.owner),
    version: number(item.version),
    establishedOn: text(item.established_on),
    hypotheses: hypotheses.map((hypothesis) => {
      const health = healthById.get(text(hypothesis.hypothesis_id)) ?? {}
      const metric = raw(health.metric)
      return {
        hypothesisId: text(hypothesis.hypothesis_id),
        statement: text(hypothesis.statement),
        importance: text(hypothesis.importance),
        supportConfirmed: number(health.support_confirmed),
        conflictConfirmed: number(health.conflict_confirmed),
        pending: number(health.pending),
        health: text(health.health, '待验证'),
        healthReason: text(health.health_reason, '等待后端派生健康度'),
        metric: {
          name: text(metric.name, '指标待映射'),
          value: text(metric.value, '—'),
          trend: text(metric.trend, 'NO DATA'),
        },
        invalidation: text(health.invalidation, '以当前逻辑版本定义的失效条件为准'),
      }
    }),
  }
}

function mapAnalysis(value: unknown): EvidenceAnalysis {
  const item = raw(value)
  const direction = text(item.direction)
  const strength = text(item.strength)
  const status = text(item.relation_status)
  const affectedHypotheses = Array.isArray(item.affected_hypotheses)
    ? item.affected_hypotheses.map(raw)
    : []
  return {
    evidenceId: text(item.evidence_id),
    relationId: text(item.relation_id),
    documentId: text(item.document_id),
    documentTitle: text(item.document_title),
    disclosedAt: text(item.disclosed_at),
    factExcerpt: text(item.fact_excerpt),
    hypothesisId: text(item.hypothesis_id),
    hypothesisStatement: text(item.hypothesis_statement),
    affectedHypotheses: affectedHypotheses.map((hypothesis) => {
      const hypothesisDirection = text(hypothesis.direction)
      return {
        hypothesisId: text(hypothesis.hypothesis_id),
        statement: text(hypothesis.statement),
        metricName: text(hypothesis.metric_name),
        actualValue: text(hypothesis.actual_value),
        invalidationThreshold: text(hypothesis.invalidation_threshold),
        direction: hypothesisDirection === '支持'
          ? 'support'
          : hypothesisDirection === '冲突'
            ? 'conflict'
            : 'neutral',
      }
    }),
    direction: direction === '支持' ? 'support' : direction === '冲突' ? 'conflict' : 'neutral',
    strength: strength === '高' ? 'high' : strength === '低' ? 'low' : 'medium',
    transmissionPath: text(item.transmission_path),
    aiConfidence: text(item.ai_confidence),
    modelVersion: text(item.model_version),
    promptVersion: text(item.prompt_version),
    evidenceLocator: text(item.evidence_locator),
    resultSource: 'preset_ai_result',
    relationStatus: status === '已确认' ? 'confirmed' : status === '已驳回' ? 'rejected' : 'pending',
    canManage: Boolean(item.can_manage),
    reviewReason: item.review_reason ? text(item.review_reason) : undefined,
  }
}

function mapCitation(value: unknown): CitationContext {
  const item = raw(value)
  const previous = raw(item.previous)
  const target = raw(item.target)
  const next = raw(item.next)
  return {
    documentTitle: text(item.document_title),
    documentType: text(item.document_type),
    disclosedAt: text(item.disclosed_at),
    locator: text(item.locator),
    page: item.page == null ? undefined : number(item.page),
    previous: text(previous.content || item.previous),
    target: text(target.content || item.target),
    next: text(next.content || item.next),
    sourceUrl: item.source_url ? text(item.source_url) : undefined,
  }
}

function mapSuggestion(value: unknown): Suggestion {
  const item = raw(value)
  return {
    suggestionId: number(item.suggestion_id),
    currentStatus: text(item.current_status),
    suggestedStatus: text(item.suggested_status),
    reasons: Array.isArray(item.reasons) ? item.reasons.map(String) : [],
    triggeredHypotheses: Array.isArray(item.triggered_hypotheses)
      ? item.triggered_hypotheses.map(String)
      : [],
    ruleVersion: text(item.rule_version),
    humanAction: item.human_action ? text(item.human_action) : undefined,
  }
}

function mapTimeline(value: unknown): TimelineEvent {
  const item = raw(value)
  return {
    eventId: text(item.event_id),
    dimension: text(item.dimension) as TimelineEvent['dimension'],
    occurredAt: text(item.occurred_at),
    actorType: text(item.actor_type) as TimelineEvent['actorType'],
    actorName: text(item.actor_name),
    summary: text(item.summary),
    reason: item.reason ? text(item.reason) : undefined,
    before: item.before ? raw(item.before) as Record<string, string | number> : undefined,
    after: item.after ? raw(item.after) as Record<string, string | number> : undefined,
    detailUrl: item.detail_url ? text(item.detail_url) : undefined,
  }
}

class RealAdapter implements ScenarioAdapter {
  readonly mode = 'real' as const
  private readonly prefix = import.meta.env.VITE_DEMO_API_PREFIX || '/api'

  async getThesis(id: string) {
    const [thesis, health] = await Promise.all([
      request<unknown>(`${this.prefix}/theses/${id}`),
      request<unknown>(`${this.prefix}/theses/${id}/hypothesis-health`),
    ])
    return mapThesis(thesis, health)
  }

  async uploadMaterial(id: string, file: File) {
    const data = new FormData()
    data.append('file', file)
    data.append('demo_case_id', import.meta.env.VITE_DEMO_CASE_ID || 'smic-2023-risk')
    const result = raw(await request<unknown>(`${this.prefix}/demo/theses/${id}/documents`, {
      method: 'POST',
      body: data,
    }))
    return {
      documentId: text(result.document_id),
      evidenceIds: Array.isArray(result.evidence_ids) ? result.evidence_ids.map(String) : [],
      relationIds: Array.isArray(result.relation_ids) ? result.relation_ids.map(String) : [],
      resultSource: 'preset_ai_result' as const,
      duplicate: Boolean(result.duplicate),
      nextUrl: text(result.next_url),
    }
  }

  async getAnalysis(evidenceId: string, relationId: string) {
    const result = await request<unknown>(
      `${this.prefix}/evidence/${evidenceId}/analysis?relation_id=${encodeURIComponent(relationId)}`,
    )
    return mapAnalysis(result)
  }

  async getCitation(documentId: string, locator: string) {
    const result = await request<unknown>(
      `${this.prefix}/documents/${documentId}/citation?locator=${encodeURIComponent(locator)}`,
    )
    return mapCitation(result)
  }

  async getSuggestions(id: string) {
    const result = await request<unknown>(`${this.prefix}/theses/${id}/suggestions`)
    return Array.isArray(result)
      ? result.map(mapSuggestion).filter((item) => !item.humanAction)
      : []
  }

  async getTimeline(id: string) {
    const result = await request<unknown>(`${this.prefix}/theses/${id}/timeline?limit=50&offset=0&order=asc`)
    const items = Array.isArray(result) ? result : Array.isArray(raw(result).items) ? raw(result).items as unknown[] : []
    return items.map(mapTimeline)
  }

  reviewRelation(
    evidenceId: string,
    relationId: string,
    action: '确认' | '驳回' | '暂不判断',
    reason: string,
  ) {
    if (action !== '确认' && !reason.trim()) {
      return Promise.reject(new Error(`${action}时必须填写人工判断依据。`))
    }
    return request<unknown>(
      `${this.prefix}/evidence/${evidenceId}/relations/${relationId}/review`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, reason }),
      },
    ).then(() => this.getAnalysis(evidenceId, relationId))
  }

  decideStatus(
    id: string,
    suggestionId: number,
    action: DecisionAction,
    reason: string,
    targetStatus?: string,
  ) {
    if (action !== '接受' && !reason.trim()) {
      return Promise.reject(new Error(`${action}时必须填写负责人决策理由。`))
    }
    return request<unknown>(`${this.prefix}/theses/${id}/status`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        suggestion_id: suggestionId,
        action,
        reason,
        target_status: action === '修改' ? targetStatus : undefined,
      }),
    }).then((result) => mapThesis(result))
  }
}

const mode = import.meta.env.VITE_DEMO_SCENARIO_MODE || 'real'
if (mode !== 'real' && mode !== 'controlled-mock') {
  throw new Error(`非法 VITE_DEMO_SCENARIO_MODE: ${mode}`)
}

export const scenario: ScenarioAdapter =
  mode === 'controlled-mock' ? new ControlledMockAdapter() : new RealAdapter()
