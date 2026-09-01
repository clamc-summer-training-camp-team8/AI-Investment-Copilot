import type {
  AssetSearchHit, AuditItem, EvidenceDetail, EvidenceFeedItem, IngestionReview,
  MetricDefinition, ProcessingJob, Relation, ReviewTask, Security, Suggestion,
  ThesisDetail, Trend, WorkbenchData,
} from './types'

const hypotheses: ThesisDetail['hypotheses'] = [
  {
    hypothesisId: 'HYP-SG-001', statement: '海外逆变器份额提升能够抵消价格竞争，维持盈利韧性',
    hypothesisType: '公司竞争力', importance: '核心', status: '验证中', observationWindow: '未来 4 个季度',
    invalidationRule: '连续两个季度海外业务毛利率低于 30%',
    metricSuggestions: [{ name: '海外业务毛利率', reason: '直接观察海外盈利韧性' }],
    mappings: [{ mappingId: 'MAP-SG-001', metricId: 'MET-GM-001', metricVersion: 'v1.0', expectedDirection: '不低于阈值', expectedValue: '35', invalidationThreshold: '30', invalidationConsecutivePeriods: 2, expectationSource: '研究员初始建模', confirmationStatus: '已确认' }],
  },
  {
    hypothesisId: 'HYP-SG-002', statement: '储能业务规模增长可转化为稳定现金回报，而非单纯收入扩张',
    hypothesisType: '盈利', importance: '核心', status: '出现分歧', observationWindow: '未来 6 个季度',
    invalidationRule: '应收账款增速连续两期显著高于收入增速',
    metricSuggestions: [{ name: '经营现金净额', reason: '验证收入增长质量' }],
    mappings: [{ mappingId: 'MAP-SG-002', metricId: 'MET-CFO-001', metricVersion: 'v1.0', expectedDirection: '越高越好', expectationSource: '2025 年报复盘', confirmationStatus: '已确认' }],
  },
  {
    hypothesisId: 'HYP-SG-003', statement: '研发投入和渠道密度能够保持产品迭代领先',
    hypothesisType: '公司竞争力', importance: '辅助', status: '验证中', observationWindow: '未来 8 个季度',
    invalidationRule: '核心市场新品迭代落后主要竞争对手两个周期',
    metricSuggestions: [{ name: '研发费用率', reason: '跟踪持续投入强度' }], mappings: [],
  },
]

export const demoThesis: ThesisDetail = {
  thesisId: 'THS-SG-001', securityId: '300274', title: '阳光电源：全球光储龙头的盈利韧性与结构性增长',
  owner: 'analyst-mvp', status: '出现分歧', direction: '看多', version: 3, establishedOn: '2026-07-18',
  horizonEndOn: '2027-07-18', nextReviewAt: '2026-10-18',
  coreView: '逆变器全球份额与储能系统集成能力构成双重护城河，核心验证点是海外毛利率、储能交付质量与现金流的同步性。',
  hypotheses,
  catalystSuggestions: [],
  riskSuggestions: [{ label: '价格竞争加剧', source: 'AI 候选' }, { label: '海外渠道库存波动', source: 'AI 候选' }],
  invalidationSuggestions: [{ label: '海外毛利率连续两季低于 30%', source: 'AI 候选' }],
}

export const demoTheses: ThesisDetail[] = [
  demoThesis,
  { ...demoThesis, thesisId: 'THS-BYD-001', securityId: '002594', title: '比亚迪：规模效应与出海驱动盈利质量', status: '验证中', direction: '观察', version: 2, coreView: '销量、海外市场和垂直一体化共同决定盈利质量。', hypotheses: hypotheses.slice(0, 2).map((item, index) => ({ ...item, hypothesisId: `HYP-BYD-00${index + 1}` })) },
  { ...demoThesis, thesisId: 'THS-SMIC-001', securityId: '688981', title: '中芯国际：利用率回升验证成熟制程景气', status: '重大风险', direction: '观察', version: 4, coreView: '国产替代与产能利用率回升支撑收入，折旧与价格压力是主要风险。', hypotheses: hypotheses.slice(0, 2).map((item, index) => ({ ...item, hypothesisId: `HYP-SMIC-00${index + 1}` })) },
]

export const demoEvidence: EvidenceDetail = {
  evidenceId: 'EVD-SG-001', securityId: '300274', sourceDocumentTitle: '阳光电源 2025 年年度报告',
  factExcerpt: '储能行业营业收入 372.87 亿元，同比增长 49.39%；毛利率 36.49%，同比下降 0.20 个百分点。',
  disclosedAt: '2026-04-18T18:00:00+08:00', ingestedAt: '2026-04-18T18:05:00+08:00', sourceUrl: 'https://www.cninfo.com.cn/',
  direction: 'conflict', strength: 'high', aiConfidence: 0.84, aiStatus: '候选',
  modelVersion: 'local-rule-v1', promptVersion: 'event-impact-v4', confirmationStatus: 'pending',
  sourceDocumentId: 'DOC-SG-2025-AR', evidenceLocator: 'DOC-SG-2025-AR#paragraph-184',
}

const validationItems: EvidenceFeedItem['validationItems'] = [
  { code: 'source', label: '原文可回查', status: 'passed', message: '定位到年报第 34 页第 184 段。' },
  { code: 'time', label: '时间边界', status: 'passed', message: '披露时间早于检索截止时间。' },
  { code: 'permission', label: '权限过滤', status: 'passed', message: '来源为当前账户可见的公开资料。' },
  { code: 'relation', label: '假设关系', status: 'warning', message: '收入增长与毛利率变化方向出现背离，需人工确认。' },
  { code: 'human', label: '人工闸门', status: 'warning', message: '尚未形成正式证据关系。' },
]

export const demoEvidenceFeed: EvidenceFeedItem = {
  ...demoEvidence, relationId: 'REL-SG-001', sourceDocumentId: 'DOC-SG-2025-AR', securityName: '阳光电源', thesisId: demoThesis.thesisId,
  thesisTitle: demoThesis.title, thesisCoreView: demoThesis.coreView, hypothesisId: 'HYP-SG-001', hypothesisStatement: hypotheses[0].statement,
  priority: 'high', canManage: true, validationItems, atomicEvidenceCount: 1, sourceDocumentCount: 1,
  supportEvidenceCount: 0, conflictEvidenceCount: 1, affectedHypothesisCount: 1, secondaryHypotheses: [], themeImpacts: [],
}

export const demoEvidenceFeeds: EvidenceFeedItem[] = [
  demoEvidenceFeed,
  { ...demoEvidenceFeed, evidenceId: 'EVD-SG-002', relationId: 'REL-SG-002', sourceDocumentId: 'DOC-SG-2026-Q1', sourceDocumentTitle: '阳光电源 2026 年一季度报告', factExcerpt: '海外地区收入同比增长 31.8%，渠道库存周转保持在正常区间。', disclosedAt: '2026-04-29T18:00:00+08:00', direction: 'support', strength: 'medium', aiConfidence: .91, confirmationStatus: 'confirmed', priority: 'medium' },
  { ...demoEvidenceFeed, evidenceId: 'EVD-SG-003', relationId: 'REL-SG-003', sourceDocumentId: 'DOC-SG-ORDER-202607', sourceDocumentTitle: '关于储能系统订单的自愿性公告', factExcerpt: '公司签署海外储能系统供货协议，合同金额约 42.6 亿元。', disclosedAt: '2026-07-16T18:00:00+08:00', direction: 'support', strength: 'high', aiConfidence: .88, hypothesisId: 'HYP-SG-002', hypothesisStatement: hypotheses[1].statement, priority: 'high' },
  { ...demoEvidenceFeed, evidenceId: 'EVD-SG-004', relationId: 'REL-SG-004', sourceDocumentId: 'DOC-SG-IR-202608', sourceDocumentTitle: '投资者关系活动记录表', factExcerpt: '管理层表示价格竞争仍将持续，短期盈利弹性存在不确定性。', disclosedAt: '2026-08-20T18:00:00+08:00', direction: 'neutral', strength: 'low', aiConfidence: .67, hypothesisId: 'HYP-SG-003', hypothesisStatement: hypotheses[2].statement, priority: 'low' },
]

export const demoRelations: Relation[] = [{ relationId: 'REL-SG-001', thesisId: demoThesis.thesisId, hypothesisId: 'HYP-SG-001', direction: 'conflict', strength: 'high', status: 'pending', reason: '收入高速增长但毛利率未同步改善，可能削弱盈利韧性。', createdBy: 'ai-runtime', canManage: true }]

export const demoSuggestions: Suggestion[] = [{ suggestionId: 2031, currentStatus: '验证中', suggestedStatus: '出现分歧', reasons: ['核心假设同时存在已确认支持证据与高强度冲突候选', '收入增长与毛利率变化方向背离'], triggeredHypotheses: ['HYP-SG-001'], ruleVersion: 'status-rule-v1.8' }]

export const demoTrends: Trend[] = [
  { hypothesisId: 'HYP-SG-001', statement: hypotheses[0].statement, metricId: 'MET-GM-001', unit: '%', direction: '改善', points: [{ period: '2025Q2', value: '34.2', publishedOn: '2025-08-20' }, { period: '2025Q3', value: '35.1', publishedOn: '2025-10-30' }, { period: '2025Q4', value: '36.5', publishedOn: '2026-04-18' }, { period: '2026Q1', value: '38.4', publishedOn: '2026-04-29' }] },
  { hypothesisId: 'HYP-SG-002', statement: hypotheses[1].statement, metricId: 'MET-CFO-001', unit: '亿元', direction: '波动', points: [{ period: '2025Q2', value: '9.8', publishedOn: '2025-08-20' }, { period: '2025Q3', value: '15.4', publishedOn: '2025-10-30' }, { period: '2025Q4', value: '48.7', publishedOn: '2026-04-18' }, { period: '2026Q1', value: '6.2', publishedOn: '2026-04-29' }] },
]

export const demoAudit: AuditItem[] = [
  { action: '发布投资逻辑 V3', actor: 'analyst-mvp', occurredAt: '2026-07-18T10:20:00+08:00' },
  { action: '确认证据关系', actor: 'analyst-mvp', occurredAt: '2026-08-01T16:08:00+08:00' },
  { action: '生成状态建议：出现分歧', actor: 'status-rule-v1.8', occurredAt: '2026-08-20T18:12:00+08:00' },
]

export const demoWorkbench: WorkbenchData = {
  statusCounts: { 验证中: 1, 出现分歧: 1, 重大风险: 1 },
  pendingEvidence: [{ kind: '证据', thesisId: demoThesis.thesisId, title: demoThesis.title, objectId: 'EVD-SG-001', summary: '高强度冲突候选待确认' }],
  pendingSuggestions: [{ kind: '状态建议', thesisId: demoThesis.thesisId, title: demoThesis.title, objectId: '2031', summary: '建议由验证中调整为出现分歧' }],
  reviewDue: [{ kind: '到期复核', thesisId: 'THS-SMIC-001', title: '中芯国际：利用率回升验证成熟制程景气', objectId: 'REV-SMIC-001', summary: '距离计划复核日 2 天' }],
}

export const demoSecurities: Security[] = [
  { securityId: '300274', ticker: '300274.SZ', name: '阳光电源', industry: '电力设备' },
  { securityId: '002594', ticker: '002594.SZ', name: '比亚迪', industry: '新能源汽车' },
  { securityId: '688981', ticker: '688981.SH', name: '中芯国际', industry: '半导体' },
]

export const demoMetrics: MetricDefinition[] = [
  { metricId: 'MET-GM-001', version: 'v1.0', name: '海外业务毛利率', unit: '%', category: '盈利质量', definition: '海外业务毛利额/海外业务收入', frequency: '季度', expectedDirection: '越高越好', status: '有效' },
  { metricId: 'MET-CFO-001', version: 'v1.0', name: '经营活动现金流量净额', unit: '亿元', category: '现金流', definition: '经营活动产生的现金流量净额', frequency: '季度', expectedDirection: '越高越好', status: '有效' },
]

export const demoIngestionReviews: IngestionReview[] = [{ reviewId: 'IR-DEMO-001', reviewType: 'security_assignment', documentId: 'DOC-DEMO-UNASSIGNED', jobId: 'JOB-DEMO-002', reason: '文件同时提及母公司与子公司，证券归属需要人工选择。', status: 'pending', payload: {}, securityCandidates: [{ securityId: '300274', name: '阳光电源', score: .82, matchedTerms: ['阳光电源', '储能'] }, { securityId: '002594', name: '比亚迪', score: .41, matchedTerms: ['新能源'] }] }]

export const demoProcessingJobs: ProcessingJob[] = [{ jobId: 'JOB-DEMO-DEAD', documentId: 'DOC-DEMO-SCAN', sourceFilename: '扫描版行业报告.pdf', status: 'dead_letter', attemptCount: 3, maxAttempts: 3, lastError: 'OCR 结果为空，无法形成可引用段落。', createdAt: '2026-08-25T09:00:00+08:00' }]

export const demoReviewTasks: ReviewTask[] = [{ taskId: 'REV-DEMO-001', thesisId: 'THS-SMIC-001', trigger: '到期', priority: '高', assignee: 'analyst-mvp', state: '待处理', detail: { reason: '计划复核日临近', due_at: '2026-08-28' }, createdAt: '2026-08-25T10:00:00+08:00' }]

export const demoAssetHits: AssetSearchHit[] = [{ documentId: 'DOC-SG-2025-AR', locator: 'DOC-SG-2025-AR#paragraph-184', content: demoEvidence.factExcerpt, visibilityLabel: '公开', rank: .912, retrievalMode: 'hybrid', keywordRank: .76, vectorRank: .94, ingestionRunId: 'RUN-SG-2025-AR-v2', embeddingVersion: 'hash-char-2gram-v1', contentStatus: '完整正文' }]
