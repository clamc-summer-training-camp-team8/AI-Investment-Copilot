export type Direction = 'support' | 'conflict' | 'neutral'
export type ThemeDirection = Direction | 'mixed' | 'divergent'
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
  thesisCoreView: string
  hypothesisId: string
  hypothesisStatement: string
  sourceDocumentTitle: string
  factExcerpt: string
  disclosedAt: string
  ingestedAt: string
  occurredAt?: string
  sourceUrl: string
  direction: Direction
  strength: Strength
  aiConfidence: number
  confirmationStatus: ConfirmationState
  priority: Priority
  canManage: boolean
  validationItems: ValidationItem[]
  aggregationSummary?: string
  atomicEvidenceCount: number
  sourceDocumentCount: number
  supportEvidenceCount: number
  conflictEvidenceCount: number
  affectedHypothesisCount: number
  secondaryHypotheses: string[]
  themeImpacts: Array<{
    hypothesisId: string
    hypothesisStatement: string
    direction: Direction
    evidenceCount: number
    hasConflictingEvidence: boolean
  }>
  themeDirection?: ThemeDirection
}

export interface PageResult<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface InvestodayCollectionRun {
  kind: 'news' | 'report'
  status: 'not_started' | 'running' | 'completed' | 'failed' | 'disabled' | 'unavailable'
  businessDate: string
  isCurrent: boolean
  updatedAt?: string
  fetched?: number
  queued?: number
  queuedToday?: number
  skippedSeen?: number
}

export interface InvestodayCollectionStatus {
  businessDate: string
  workerReady: boolean
  overallStatus: InvestodayCollectionRun['status']
  news: InvestodayCollectionRun
  reports: InvestodayCollectionRun
}

export interface EvidenceDetail {
  evidenceId: string
  securityId: string
  factExcerpt: string
  sourceDocumentTitle: string
  disclosedAt: string
  occurredAt?: string
  ingestedAt: string
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

export interface LogicChangeDigestDetail {
  digestId: string
  securityId: string
  securityName: string
  thesisId: string
  thesisTitle: string
  thesisCoreView: string
  businessDate: string
  overallDirection: 'support' | 'conflict' | 'mixed' | 'neutral'
  summary: string
  confirmationStatus: ConfirmationState
  candidateCount: number
  sourceDocumentCount: number
  confidence?: number
  openQuestions: string[]
  modelVersion?: string
  promptVersion?: string
  hypothesisImpacts: Array<{
    hypothesisId: string
    statement: string
    direction: string
    strength?: '弱' | '中' | '强'
    strengthReason?: string
    rationale: string
    businessImpact?: string
    indicatorOutlook?: string
    impactLayer?: string
    directness?: string
    transmissionStatus?: string
    hypothesisEffect?: string
    presentation?: '单一路径' | '双向分歧' | '背景信号' | '证据不足'
    paths: Array<{
      direction: string
      label: string
      mechanism: string
      evidenceIds: string[]
    }>
    relatedMetrics: string[]
    evidenceIds: string[]
  }>
  sourceDocuments: Array<{
    documentId: string
    title: string
    docType?: string
    publishedAt?: string
    sourceUrl?: string
    facts: Array<{
      evidenceId: string
      factExcerpt: string
      evidenceLocator: string
      hypothesisIds: string[]
      directions: string[]
      isKeyCitation: boolean
    }>
  }>
}

export interface FullDocument {
  documentId: string
  title?: string
  docType?: string
  publishedAt: string
  parserVersion: string
  segmentCount: number
  segments: Array<{
    locator: string
    ordinal: number
    page?: number
    content: string
    contentKind: string
    extractionMethod: string
  }>
}

export interface RetrievalScoreComponents {
  text: number
  graph: number
}

export interface GraphPathTrace {
  score: number
  nodeIds: string[]
  nodeKinds: string[]
  layers: string[]
  relations: string[]
  provenanceLocators: string[]
  explanation: string
}

export interface GraphLayerSnapshot {
  layer: string
  nodeCount: number
  contentHash: string
}

export interface GraphSnapshotTrace {
  snapshotId: string
  schemaVersion: string
  builderVersion: string
  vocabularyVersion: string
  builtAt: string
  asOf?: string
  thesisIds: string[]
  securityIds: string[]
  layers: GraphLayerSnapshot[]
}

export interface EvidenceRetrievalTrace {
  available: boolean
  retrievalMode: string
  retrievalVersion: string
  locator: string
  finalScore: number
  scoreComponents: RetrievalScoreComponents
  graphPaths: GraphPathTrace[]
  graphSnapshot?: GraphSnapshotTrace
}

export interface ThesisSummary {
  thesisId: string
  securityId: string
  title: string
  owner: string
  status: string
  direction?: string
  thesisKind?: string
  thesisSeriesId?: string
}

export interface Security {
  securityId: string
  name: string
  ticker?: string
  industry?: string
}

export interface MaintainedCoverageCompany {
  securityId: string
  name: string
  ticker?: string
  industry?: string
  thesisId?: string
  thesisTitle?: string
  thesisStatus: string
  hypothesisCount: number
  configuredMetricCount: number
  updatedAt?: string
}

export interface MaintainedCoverageIndustry {
  name: string
  companies: MaintainedCoverageCompany[]
}

export interface CoverageUniverseCompany {
  coverageCompanyId?: string
  sectorId?: string
  securityId: string
  name: string
  ticker?: string
  industry?: string
  thesisId?: string
  thesisTitle?: string
  thesisStatus?: string
  thesisCount: number
  owner?: string
  hypothesisCount: number
  configuredMetricCount: number
  updatedAt?: string
  status?: string
  market?: string
}

export interface CoverageUniverseIndustry {
  sectorId?: string
  code?: string
  description?: string
  status?: string
  name: string
  companies: CoverageUniverseCompany[]
}

export interface CompanyMetricPoint { period: string; date: string; value: string }
export interface CompanyMetric {
  metricId: string; name: string; category: string; unit: string; frequency: string
  definition: string; sourceId: string; latestValue: string; latestPeriod: string; latestDate: string
  previousValue?: string; changeValue?: string; changeRate?: string; observations: CompanyMetricPoint[]
}
export interface CompanyMetricCenter { securityId: string; updatedAt?: string; metrics: CompanyMetric[] }

export interface ThesisDetail extends ThesisSummary {
  direction: string
  coreView: string
  version: number
  establishedOn: string
  horizonEndOn?: string
  nextReviewAt?: string
  investmentRating?: string
  targetPrice?: string
  observationPeriod?: string
  hypotheses: Hypothesis[]
  riskSuggestions: Array<Record<string, unknown>>
  invalidationSuggestions: Array<Record<string, unknown>>
}

export interface MetricMapping {
  mappingId: string
  metricId: string
  metricName?: string
  expectedValue?: string
  expectedLower?: string
  expectedUpper?: string
  invalidationThreshold?: string
  invalidationConsecutivePeriods?: number
  metricVersion: string
  expectedDirection: string
  expectationSource: string
  confirmationStatus: string
}

export interface Hypothesis {
  hypothesisId: string
  statement: string
  hypothesisType: string
  importance: string
  status: string
  observationWindow?: string
  invalidationRule?: string
  metricSuggestions: Array<Record<string, unknown>>
  causalLevel?: string
  logicDimension?: string
  qualityWarning?: string
  mappings: MetricMapping[]
}

export interface MetricDefinition {
  metricId: string
  version: string
  name: string
  unit: string
  category?: string
  definition?: string
  frequency?: string
  expectedDirection?: string
  status: string
}

export interface PublishReadiness {
  ready: boolean
  items: Array<{ code: string; label: string; passed: boolean; message: string }>
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
  outputType: '状态变更建议' | '研究提醒' | '信息沉淀'
  requiresHumanConfirmation: boolean
  researchAlerts: ResearchAlert[]
  hypothesisHealth: HypothesisHealth[]
  humanAction?: string
}

export interface ResearchAlert {
  category: string
  level: string
  title: string
  detail: string
  hypothesisIds: string[]
}

export interface HypothesisHealth {
  hypothesisId: string
  state: string
  reason: string
  supportCount: number
  conflictCount: number
}

export interface Trend {
  hypothesisId: string
  statement: string
  metricId: string
  metricName?: string
  unit: string
  direction: string
  expectedValue?: string
  expectedLower?: string
  expectedUpper?: string
  invalidationThreshold?: string
  invalidationConsecutivePeriods?: number
  invalidationRule?: string
  slope?: string
  verdict?: string
  note?: string
  points: Array<{ period: string; value: string; publishedOn: string; acquiredAt?: string; sourceDocumentId?: string; dataVersion?: string; isValidationWindow?: boolean }>
}

export interface AuditItem {
  action: string
  actor: string
  occurredAt?: string
  detail?: Record<string, unknown> & {
    batch_id?: string
    confirmed_count?: number
    pending_count?: number
    rejected_count?: number
    suggested_thesis_status?: string
  }
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

export interface ProcessingJob {
  jobId: string
  documentId: string
  sourceFilename: string
  securityId?: string
  status: string
  attemptCount: number
  maxAttempts: number
  result?: Record<string, unknown>
  lastError?: string
  createdAt?: string
  startedAt?: string
  finishedAt?: string
}

export interface IngestionReview {
  reviewId: string
  reviewType: string
  documentId: string
  jobId?: string
  eventId?: string
  reason: string
  status: string
  payload: Record<string, unknown>
  securityCandidates: Array<{ securityId: string; name: string; score: number; matchedTerms: string[] }>
  resolution?: string
  createdAt?: string
  resolvedAt?: string
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

export interface ReviewDraftCandidate {
  runId: string
  status: string
  aiStatus?: string
  requiresHumanReview: boolean
  payload: Record<string, unknown>
  errors: string[]
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
  contentKind: string
  extractionMethod: string
  tableIndex?: number
  rowIndex?: number
  cellRange?: string
  confidence?: number
  previousLocator?: string
  nextLocator?: string
}

export interface AssetInventory {
  documents: number
  revisions: number
  ingestionRuns: number
  segments: number
  facts: number
  singleSegmentDocuments: number
  pendingAuthorization: number
  missingObjectArchive: number
  semanticRuns: number
  artifactSegments: number
  artifactFacts: number
  artifactEvents: number
  embeddings: number
  titleIndexDocuments: number
  archivedSourceDocuments: number
  authorizationVerifiedDocuments: number
}

export interface AssetSearchHit {
  documentId: string
  locator: string
  content: string
  visibilityLabel: string
  rank: number
  retrievalMode?: string
  keywordRank?: number
  vectorRank?: number
  ingestionRunId?: string
  embeddingVersion?: string
  contentStatus: string
}

export interface DataCenterRun {
  runId: string
  revisionId: string
  documentId: string
  documentTitle: string
  sourceFilename: string
  parserVersion: string
  chunkerVersion: string
  extractorVersion: string
  embeddingVersion?: string
  status: string
  segmentCount: number
  factCount: number
  eventCount: number
  qualitySummary: Record<string, unknown>
  error?: string
  startedAt?: string
  finishedAt?: string
  createdAt?: string
}

export interface DataCenterOverview {
  documents: number
  archivedDocuments: number
  missingArchiveDocuments: number
  authorizationVerifiedDocuments: number
  pendingAuthorizationDocuments: number
  titleIndexDocuments: number
  fullTextDocuments: number
  recentSucceededRuns: number
  recentFailedRuns: number
  marketDatasetCount: number
  signalSetCount: number
  defaultMarketDatasetId?: string
  defaultMarketDataVersion?: string
  defaultMarketCoverageEnd?: string
  attention: Array<{ code: string; label: string; count: number; severity: string; target: string }>
  recentRuns: DataCenterRun[]
  asOf: string
}

export interface DataCenterDocument {
  documentId: string
  title: string
  sourceId?: string
  sourceName: string
  docType?: string
  publishedAt: string
  ingestedAt?: string
  contentStatus: string
  visibilityLabel: string
  isIllustrative: boolean
  deletedAt?: string
  archived: boolean
  authorizationStatus: string
  revisionCount: number
  segmentCount: number
  latestRunStatus?: string
  latestRunAt?: string
  securityIds: string[]
  securityNames: string[]
  industries: string[]
}

export interface DataCenterRevision {
  revisionId: string
  contentHash: string
  sourceFilename: string
  hasObject: boolean
  objectVersionId?: string
  mediaType?: string
  byteSize?: number
  sourceId?: string
  sourceHost?: string
  authorizationStatus: string
  authorizationBasis?: string
  authorizationVerifiedBy?: string
  authorizationVerifiedAt?: string
  contentStatus: string
  uploadedBy: string
  publishedAt?: string
  createdAt?: string
  tombstonedAt?: string
}

export interface DataCenterDocumentDetail extends DataCenterDocument {
  allowedActions: string[]
  revisions: DataCenterRevision[]
  runs: DataCenterRun[]
}

export interface DataCenterDocumentPage {
  items: DataCenterDocument[]
  total: number
  limit: number
  offset: number
}

export interface DataCenterSource {
  sourceId: string
  name: string
  sourceType: string
  authorizationStatus: string
  licenseNote?: string
  authorizationBasis?: string
  authorizationVerifiedBy?: string
  authorizationVerifiedAt?: string
  active: boolean
  documentCount: number
  latestRunStatus?: string
  latestRunAt?: string
  baseHost?: string
}

export type GlobalSearchType = 'security' | 'industry' | 'thesis' | 'event' | 'document'
export type GlobalSearchTargetKind = 'security' | 'industry' | 'thesis' | 'event' | 'document_segment'

export interface GlobalSearchItem {
  id: string
  title: string
  subtitle: string
  excerpt?: string
  matchKind: string
  target: { kind: GlobalSearchTargetKind; id: string }
  contentStatus?: string
  contentKind?: string
  retrievalMode?: string
  publishedAt?: string
}

export interface GlobalSearchResult {
  query: string
  groups: Array<{ type: GlobalSearchType; items: GlobalSearchItem[] }>
  requestId: string
}

export interface KnowledgeAnswerRequest {
  question: string
  context?: { thesisId?: string; securityId?: string; asOf?: string }
  history?: Array<{ role: 'user' | 'assistant'; content: string }>
}

export interface AnswerCitation {
  ref: string
  locator: string
  documentId: string
  title: string
  excerpt: string
  publishedAt?: string
  contentStatus: string
  contentKind: string
  retrievalMode: string
}

export interface KnowledgeAnswer {
  answerId: string
  answerStatus: 'supported' | 'partial' | 'insufficient_evidence'
  aiStatus: string
  answer: string
  inferences: string[]
  citations: AnswerCitation[]
  modelVersion: string
  promptVersion: string
  retrievalVersion: string
  graphSnapshotId?: string
  generatedAt: string
  requestId: string
}

export interface ThesisRevision {
  draftId: string
  thesisId: string
  baseVersion: number
  revision: number
  owner: string
  payload: Record<string, unknown>
  status: string
}

export interface ThesisRevisionDiff {
  draftId: string
  baseVersion: number
  changes: Record<string, { before?: unknown; after?: unknown }>
}

export interface QuantBarInput {
  tradingDate: string
  close: number
  benchmarkClose: number
  tradable?: boolean
}

export interface QuantSignalInput {
  signalId: string
  disclosedAt: string
  generatedAt: string
  direction: '支持' | '冲突' | '中性'
  strength: '高' | '中' | '低'
  confidence: number
}

export interface QuantBacktestRequest {
  name: string
  bars: QuantBarInput[]
  signals: QuantSignalInput[]
  config: {
    initialCapital: number
    holdingDays: number
    transactionCostBps: number
    slippageBps: number
    allowShort: boolean
  }
}

export interface QuantMetrics {
  initialCapital: number
  finalEquity: number
  totalReturn: number
  benchmarkReturn: number
  excessReturn: number
  annualizedReturn: number
  annualizedVolatility: number
  sharpeRatio?: number
  maxDrawdown: number
  winRate?: number
  turnover: number
  tradeCount: number
  averageExposure: number
}

export interface QuantEquityPoint {
  tradingDate: string
  equity: number
  benchmarkEquity: number
  drawdown: number
  position: number
}

export interface QuantTrade {
  signalId: string
  direction: string
  entryDate: string
  exitDate: string
  entryPrice: number
  exitPrice: number
  position: number
  grossReturn: number
  netReturn: number
  holdingDays: number
  exitReason: string
}

export interface QuantBacktestRun {
  runId: string
  name: string
  generatedAt: string
  methodologyVersion: string
  metrics: QuantMetrics
  equityCurve: QuantEquityPoint[]
  trades: QuantTrade[]
  diagnostics: {
    inputSignalCount: number
    acceptedSignalCount: number
    skippedSignalCount: number
    skippedSignals: string[]
    warnings: string[]
  }
}

export interface QuantMarketDataset {
  datasetId: string
  dataVersion: string
  manifestSha256: string
  authorizationStatus: string
  adjustment: string
  coverageStart: string
  coverageEnd: string
  securities: string[]
  capabilities: Record<string, boolean>
  limitations: string[]
  status: string
}

export interface QuantMarketDatasetDetail extends QuantMarketDataset {
  isDefault: boolean
  manifestVerified: boolean
  assets: Array<{ name: string; path: string; sha256: string; byteSize?: number; verified: boolean }>
  sourcePriority: string[]
  authorizationScope?: string
  timezone: string
  adjustmentAnchorDate?: string
  availableSignalSets: QuantSignalSet[]
  backtestCount: number
}

export interface QuantSignalSet {
  signalSetId: string
  name: string
  version: string
  contentSha256: string
  signalCount: number
  humanConfirmedOnly: boolean
  evaluationTrack: string
  status: string
}

export interface QuantCatalog {
  defaultMarketDatasetId: string | null
  marketDatasets: QuantMarketDataset[]
  signalSets: QuantSignalSet[]
  evaluationSeparation: {
    semanticEvaluation: string
    retrievalEvaluation: string
    alphaValidation: string
    hardRule: string
  }
}

export interface PortfolioBacktestRequest {
  name: string
  marketDatasetId: string
  signalSetId: string
  securityIds: string[]
  start?: string
  end?: string
  config: {
    initialCapital: number
    rollingWindowDays: number
    walkForwardDays: number
    rebalanceDays: number
    transactionCostBps: number
    slippageBps: number
    maxSecurityWeight: number
    maxIndustryWeight: number
    capacityParticipationRate: number
    neutralizeIndustry: boolean
    neutralizeMarketCap: boolean
    enforceCapacity: boolean
    allowShort: boolean
  }
}

export interface PortfolioBacktestRun {
  runId: string
  name: string
  marketDatasetId: string
  signalSetId: string
  methodologyVersion: string
  evaluationTrack: string
  generatedAt: string
  parameters: Record<string, unknown>
  result: {
    metrics: Record<string, number | string | null>
    equityCurve: Array<Record<string, number | string>>
    walkForward: Array<Record<string, number | string>>
    signalResearch: {
      observationCount: number
      ic?: number | string | null
      rankIc?: number | string | null
      quantileReturns: Record<string, number | string>
    }
    riskAttribution: {
      security: Record<string, number | string>
      industry: Record<string, number | string>
      factorExposure: Record<string, number | string>
      residual: number | string
    }
    diagnostics: {
      acceptedSignalCount: number
      inputSignalCount: number
      skippedSignals: string[]
      blockedTrades: string[]
      warnings: string[]
    }
  }
}

export interface GoldQualitySummary {
  totalSamples: number
  consensusSamples: number
  adjudicatedSamples: number
  goldSamples: number
  evaluationEligibleSamples: number
  pendingAdjudication: number
  consensusCoverage: number
  goldCoverage: number
  evaluationReady: boolean
  productionGoldReady: boolean
  graphRagRolloutReady: boolean
}

export interface GoldTaskQuality {
  task: string
  label: string
  total: number
  consensus: number
  adjudicated: number
  final: number
  evaluationEligible: number
  pending: number
  coverage: number
  coreFields: string[]
  file: string
}

export interface GoldAgreement {
  task: string
  field: string
  n: number
  agreement: number
  cohenKappa?: number
}

export interface GoldQualityGate {
  code: string
  label: string
  status: 'passed' | 'warning' | 'blocked'
  current?: boolean | number
  target?: boolean | number
  message: string
}

export interface GraphRagRankingMetrics {
  evaluatedQueries: number
  positiveQueries: number
  recallAtK: Record<string, number>
  hitRateAtK: Record<string, number>
  ndcgAtK: Record<string, number>
  mrr: number
  top1Correctness: number
  unjudgedResultCount: number
}

export interface GraphRagBenchmarkGate {
  code: string
  current: boolean | number
  target: boolean | number
  passed: boolean
}

export interface GraphRagSystemBenchmark {
  benchmarkVersion: string
  generatedAt: string
  reportPath: string
  rolloutReady: boolean
  evaluatedQueries: number
  positiveQueries: number
  textBaseline: GraphRagRankingMetrics
  graphRag: GraphRagRankingMetrics
  safety: {
    permissionLeakageCount: number
    securityLeakageCount: number
    futureLeakageCount: number
    canaryContentLeakageCount: number
    adversarialCanaryCount: number
    pathProvenanceValid: number
    pathProvenanceRelevantHits: number
    pathProvenanceRate: number
  }
  gates: GraphRagBenchmarkGate[]
}

export interface GoldQualityReport {
  schemaVersion: string
  goldVersion: string
  goldState: 'consensus' | 'final'
  createdAt: string
  sourcePackage: string
  summary: GoldQualitySummary
  tasks: GoldTaskQuality[]
  agreement: GoldAgreement[]
  gates: GoldQualityGate[]
  qualityExceptions: Array<{ task: string; sampleId: string; reason: string }>
  files: Array<{ path: string; rows: number; sha256: string }>
  graphRagBenchmark?: GraphRagSystemBenchmark
}
