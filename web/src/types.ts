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
  humanAction?: string
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
  slope?: string
  verdict?: string
  note?: string
  points: Array<{ period: string; value: string; publishedOn: string; acquiredAt?: string; sourceDocumentId?: string; dataVersion?: string }>
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
}

export interface CompanyDocument {
  documentId: string
  title?: string
  sourceId?: string
  docType?: string
  securityId?: string
  publishedAt: string
  ingestedAt?: string
  visibilityLabel: string
  segmentCount: number
  factCount: number
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
