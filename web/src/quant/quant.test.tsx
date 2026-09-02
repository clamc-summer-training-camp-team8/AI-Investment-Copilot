import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { listSecurities } from '../api'
import type {
  PortfolioBacktestRun,
  QuantCatalog,
  QuantDemoScenario,
  QuantFactorDefinition,
  QuantMarketDatasetDetail,
  QuantModelTemplate,
  QuantSignalSetDetail,
} from '../types'
import {
  getMarketDatasetDetail,
  getPortfolioBacktest,
  getQuantCatalog,
  getQuantDemoScenario,
  getQuantFactors,
  getQuantModelTemplates,
  getQuantSignalSetDetail,
  listPortfolioBacktests,
} from './api'
import QuantModule, { QuantFactorsPage, QuantModelsPage, QuantNewRunPage, QuantOverviewPage, QuantRunDetailPage, QuantSignalSetDetailPage } from './index'

vi.mock('../api', () => ({ listSecurities: vi.fn() }))
vi.mock('./api', () => ({
  getMarketDatasetDetail: vi.fn(),
  getPortfolioBacktest: vi.fn(),
  getQuantCatalog: vi.fn(),
  getQuantDemoScenario: vi.fn(),
  getQuantFactors: vi.fn(),
  getQuantModelTemplates: vi.fn(),
  getQuantSignalSetDetail: vi.fn(),
  listPortfolioBacktests: vi.fn(),
  runPortfolioBacktest: vi.fn(),
}))

const v2 = {
  datasetId: 'MDS-default-v2', dataVersion: '20260801-v2', manifestSha256: 'a'.repeat(64),
  authorizationStatus: 'approved', adjustment: 'qfq', coverageStart: '2024-01-01',
  coverageEnd: '2026-07-31', securities: ['688981'], capabilities: {}, limitations: [], status: 'frozen',
}

const v3 = {
  datasetId: 'MDS-akshare-qfq-tuaremax10000-20260831-v3', dataVersion: '20260831-v3',
  manifestSha256: 'b'.repeat(64), authorizationStatus: 'approved', adjustment: 'qfq',
  coverageStart: '2023-12-01', coverageEnd: '2026-08-28', securities: ['688981', '0700.HK', '603986'],
  capabilities: { a_share_point_in_time_market_cap: true, price_limit_status: false, structured_corporate_action_events: false },
  limitations: ['HKD/CNY 未冻结汇率'], status: 'frozen',
}

const signalSet = {
  signalSetId: 'QSS-1', name: '人工确认事件信号', version: '20260820-v1', contentSha256: 'c'.repeat(64),
  signalCount: 2, humanConfirmedOnly: true, evaluationTrack: 'alpha_validation', status: 'frozen',
  frozenAt: '2026-08-20T08:00:00Z',
}

const catalog: QuantCatalog = {
  defaultMarketDatasetId: v2.datasetId,
  marketDatasets: [v2, v3],
  signalSets: [signalSet],
  evaluationSeparation: {
    semanticEvaluation: '独立语义轨', retrievalEvaluation: '独立检索轨', alphaValidation: '独立 Alpha 轨',
    hardRule: '三类评测样本、标签和结论不得混用。',
  },
}

const datasetDetail: QuantMarketDatasetDetail = {
  ...v3, isDefault: false, manifestVerified: true, assets: [], sourcePriority: ['akshare'],
  timezone: 'Asia/Shanghai', availableSignalSets: [signalSet], backtestCount: 0,
  securityMetadata: [
    { securityId: '688981', name: '中芯国际', market: 'SSE', currency: 'CNY', industry: '半导体', benchmarkId: '000300', coverageStart: v3.coverageStart, coverageEnd: v3.coverageEnd, rowCount: 650, marketCapCount: 650, marketCapComplete: true },
    { securityId: '0700.HK', name: '腾讯控股', market: 'HKEX', currency: 'HKD', industry: '互联网', benchmarkId: 'HSI', coverageStart: v3.coverageStart, coverageEnd: v3.coverageEnd, rowCount: 630, marketCapCount: 0, marketCapComplete: false },
    { securityId: '603986', name: '兆易创新', market: 'SSE', currency: 'CNY', industry: '半导体', benchmarkId: '000300', coverageStart: v3.coverageStart, coverageEnd: v3.coverageEnd, rowCount: 650, marketCapCount: 650, marketCapComplete: true },
  ],
}

const signalDetail: QuantSignalSetDetail = {
  ...signalSet, visibleSignalCount: 2,
  signals: [
    { signalId: 'SIG-1', securityId: '688981', disclosedAt: '2026-08-18T08:00:00Z', generatedAt: '2026-08-20T08:00:00Z', direction: '支持', strength: '强', confidence: .9, confidenceUsedForAlphaWeight: false, confirmationStatus: '已确认', sourceEvidenceId: 'EVD-1', sourceRelationId: 'REL-1', sourceRelationStatus: '已确认', thesisId: 'THS-1', hypothesisId: 'HYP-1', sourceLocator: '公告第 2 页', sourceDocumentId: 'DOC-1', sourceDocumentTitle: '中芯国际公告' },
    { signalId: 'SIG-2', securityId: '0700.HK', disclosedAt: '2026-08-18T08:00:00Z', generatedAt: '2026-08-20T08:00:00Z', direction: '冲突', strength: '中', confidence: .8, confidenceUsedForAlphaWeight: false, confirmationStatus: '已确认', sourceEvidenceId: 'EVD-2', sourceRelationId: 'REL-2', sourceRelationStatus: '已确认', thesisId: 'THS-2', hypothesisId: 'HYP-2', sourceLocator: '财报第 6 页', sourceDocumentTitle: '腾讯财报' },
  ],
}

const factors: QuantFactorDefinition[] = [
  { factorId: 'confirmed_event_direction_strength', name: '人工确认事件方向与强度', category: 'alpha_input', description: '人工确认事件分数', formula: 'direction_sign × strength_weight', frequency: '事件驱动', coverageScope: '冻结信号', inputFields: ['direction', 'strength'], status: 'active', version: '1.0.0', methodologyVersion: 'portfolio-research-v3', owner: 'quant-research', publishedAt: '2026-09-01', enabledByDefault: true, limitations: ['AI 判断置信度不参与 Alpha 权重'] },
  { factorId: 'industry_neutralization', name: '行业中性约束', category: 'risk_control', description: '行业内去均值', formula: 'score - industry_mean', frequency: '再平衡', coverageScope: '点时截面', inputFields: ['industry'], status: 'gated', version: '1.0.0', methodologyVersion: 'portfolio-research-v3', owner: 'quant-research', publishedAt: '2026-09-01', enabledByDefault: false, limitations: ['单例行业硬阻断'] },
  { factorId: 'momentum_20_60_120', name: '20/60/120 日动量', category: 'alpha_candidate', description: '动量候选', formula: 'close ratio', frequency: '日频', coverageScope: '待扩大样本', inputFields: ['adjusted_close'], status: 'planned', version: '1.0.0', methodologyVersion: 'portfolio-research-v3', owner: 'quant-research', publishedAt: '2026-09-01', enabledByDefault: false, limitations: ['尚未启用'] },
]

const templateConfig = {
  initialCapital: 1_000_000, rollingWindowDays: 60, walkForwardDays: 20, rebalanceDays: 5,
  transactionCostBps: 10, slippageBps: 5, maxSecurityWeight: .2, maxIndustryWeight: .4,
  capacityParticipationRate: .1, neutralizeIndustry: false, neutralizeMarketCap: false,
  enforceCapacity: true, allowShort: true,
}

const modelTemplates: QuantModelTemplate[] = [
  {
    templateId: 'confirmed-event-research-v3', name: '人工确认事件研究', version: '3.0.0', status: 'active',
    description: '人工确认事件研究模板', methodologyVersion: 'portfolio-research-v3',
    alphaFactorIds: ['confirmed_event_direction_strength'], controlFactorIds: ['adv20_capacity'],
    defaultConfig: templateConfig, requiredConfig: {},
    sampleGate: { minimumUniqueSecurities: 20, minimumObservations: 100, minimumActiveTradingDays: 60 },
    owner: 'quant-research', publishedAt: '2026-09-01', limitations: ['样本不足时禁止宣称 Alpha'],
  },
  {
    templateId: 'confirmed-event-industry-neutral-v3', name: '人工确认事件研究 · 行业中性', version: '3.0.0', status: 'gated',
    description: '行业内去均值', methodologyVersion: 'portfolio-research-v3',
    alphaFactorIds: ['confirmed_event_direction_strength'], controlFactorIds: ['industry_neutralization'],
    defaultConfig: { ...templateConfig, neutralizeIndustry: true }, requiredConfig: { neutralizeIndustry: true },
    sampleGate: { minimumUniqueSecurities: 20, minimumObservations: 100, minimumActiveTradingDays: 60 },
    owner: 'quant-research', publishedAt: '2026-09-01', limitations: ['单例行业硬阻断'],
  },
  {
    templateId: 'event-momentum-overlay-v1', name: '事件信号 × 动量增量检验', version: '1.0.0-draft', status: 'planned',
    description: '规划中的动量增量检验', methodologyVersion: 'portfolio-research-v3',
    alphaFactorIds: ['confirmed_event_direction_strength', 'momentum_20_60_120'], controlFactorIds: [],
    defaultConfig: templateConfig, requiredConfig: {},
    sampleGate: { minimumUniqueSecurities: 20, minimumObservations: 100, minimumActiveTradingDays: 60 },
    owner: 'quant-research', limitations: ['尚未发布'],
  },
]

const run: PortfolioBacktestRun = {
  runId: 'QPF-test-001', name: 'V3 事件信号样本外验证', marketDatasetId: v3.datasetId,
  signalSetId: signalSet.signalSetId, methodologyVersion: 'portfolio-event-signal-v1',
  evaluationTrack: 'alpha_validation', generatedAt: '2026-08-31T10:00:00Z', parameters: { model_template_id: 'confirmed-event-research-v3', model_template_version: '3.0.0' },
  result: {
    metrics: { total_return: .12, benchmark_return: -.03, excess_return: .15, full_period_benchmark_return: .08, full_period_excess_return: .04, active_start_date: '2026-08-13', active_end_date: '2026-08-28', active_trading_days: 12, max_drawdown: -.07, tracking_error: .03, information_ratio: 1.1, beta: .92 },
    equityCurve: [
      { trading_date: '2026-01-02', equity: 100, benchmark_equity: 100 },
      { trading_date: '2026-08-28', equity: 112, benchmark_equity: 108 },
    ],
    walkForward: [{ train_start: '2025-01-01', train_end: '2025-12-31', test_start: '2026-01-01', test_end: '2026-03-31', observation_count: 40, total_return: .03, benchmark_return: .02, excess_return: .01 }],
    signalResearch: { observationCount: 18, ic: .12, rankIc: .18, quantileReturns: { Q1: -.01, Q5: .03 } },
    riskAttribution: { security: { '688981': .02 }, industry: { 半导体: .015 }, factorExposure: { market_beta: .92 }, residual: .01 },
    validationQuality: { status: 'insufficient_sample', label: '样本不足', alphaClaimAllowed: false, reasons: ['有效信号仅覆盖 2 只证券'], uniqueSecurityCount: 2, nonzeroSignalCount: 2, observationCount: 18, activeTradingDays: 12 },
    diagnostics: { acceptedSignalCount: 2, inputSignalCount: 2, skippedSignals: [], blockedTrades: [], warnings: ['HKD/CNY 未冻结汇率'] },
  },
}

const demoScenario: QuantDemoScenario = {
  scenarioId: 'QDS-demo-30', runId: 'QPF-DEMO-30', title: '30 证券投资逻辑回测验证 · 全量确认情景',
  evaluationTrack: 'scenario_simulation', scenarioPolicyVersion: 'assumed-confirmation-neutral-noop-v1',
  methodologyVersion: 'portfolio-research-v3+neutral-noop-v1', generatedAt: '2026-09-02T16:00:00+08:00',
  assumption: '假定研究员对本情景中的 AI 待确认关系逐条核验并全部通过；这些关系仅为演示输入，不写入真实研究库。',
  disclaimer: '用于验证产品链路与量化方法表达，不构成 Alpha 结论。',
  dataset: { datasetId: 'MDS-v4-30', dataVersion: '20260902-v4', manifestSha256: 'd'.repeat(64), coverageStart: '2023-12-01', coverageEnd: '2026-09-01', securityCount: 30, tradingDayCount: 667 },
  summary: { candidateCount: 330, assumedConfirmedCount: 330, directionalSignalCount: 264, neutralNoopCount: 66, checkpointCount: 11, supportCount: 132, conflictCount: 132 },
  scoreMapping: [
    { direction: '支持', strength: '高', score: 1, portfolioEffect: '进入正向排序' },
    { direction: '支持', strength: '中', score: .7, portfolioEffect: '进入正向排序' },
    { direction: '支持', strength: '低', score: .4, portfolioEffect: '进入正向排序' },
    { direction: '中性', strength: '高', score: 0, portfolioEffect: '保留上一有效状态' },
    { direction: '中性', strength: '中', score: 0, portfolioEffect: '保留上一有效状态' },
    { direction: '中性', strength: '低', score: 0, portfolioEffect: '保留上一有效状态' },
    { direction: '冲突', strength: '高', score: -1, portfolioEffect: '进入负向排序' },
    { direction: '冲突', strength: '中', score: -.7, portfolioEffect: '进入负向排序' },
    { direction: '冲突', strength: '低', score: -.4, portfolioEffect: '进入负向排序' },
  ],
  decisionPipeline: [
    { step: '01', title: '人工确认', description: '核验候选关系。' },
    { step: '02', title: '事件因子化', description: '方向与强度映射。' },
    { step: '03', title: '组合约束', description: '施加容量和权重约束。' },
    { step: '04', title: 'T+1 验证', description: '输出研究指标。' },
  ],
  latestEvents: [{ signalId: 'DEMO-1', securityId: '688981', securityName: '中芯国际', industry: '半导体', disclosedAt: '2026-08-03T09:00:00+08:00', assumedReviewedAt: '2026-08-03T15:30:00+08:00', direction: '中性', strength: '中', score: 0, decisionEffect: '中性留痕 · 组合状态不变', thesisTitle: '国产替代与产品结构兑现', hypothesisStatement: '产品结构改善', evidenceTitle: '第 11 期经营变化摘要' }],
  result: {
    ...run.result,
    validationQuality: { status: 'research_candidate', label: '可提交研究评审', alphaClaimAllowed: false, reasons: ['仍需独立评审'], uniqueSecurityCount: 30, nonzeroSignalCount: 264, observationCount: 3170, activeTradingDays: 547 },
    metrics: { ...run.result.metrics, total_return: .02, excess_return: -.5, max_drawdown: -.13, information_ratio: -.88, rebalance_count: 119 },
  },
}

function renderPage(route: string, element: ReactNode, path = '*') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}><Routes><Route path={path} element={element} /></Routes></MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(cleanup)

beforeEach(() => {
  vi.mocked(getQuantCatalog).mockResolvedValue(catalog)
  vi.mocked(getQuantDemoScenario).mockResolvedValue(demoScenario)
  vi.mocked(getQuantFactors).mockResolvedValue(factors)
  vi.mocked(getQuantModelTemplates).mockResolvedValue(modelTemplates)
  vi.mocked(listPortfolioBacktests).mockResolvedValue([])
  vi.mocked(getMarketDatasetDetail).mockResolvedValue(datasetDetail)
  vi.mocked(getQuantSignalSetDetail).mockResolvedValue(signalDetail)
  vi.mocked(getPortfolioBacktest).mockResolvedValue(run)
  vi.mocked(listSecurities).mockResolvedValue([
    { securityId: '688981', name: '中芯国际' },
    { securityId: '0700.HK', name: '腾讯控股' },
    { securityId: '603986', name: '兆易创新' },
    { securityId: '09868', name: '小鹏汽车' },
  ])
})

describe('模型与因子 P0 页面', () => {
  it('答辩演示页解释分数决策语义并展示完整30证券验证链路', async () => {
    renderPage('/quant/demo', <QuantModule demoEnabled />, '/quant/*')
    expect(await screen.findByRole('heading', { name: '30 证券投资逻辑回测验证 · 全量确认情景' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '答辩演示' })).toHaveAttribute('href', '/quant/demo')
    expect(screen.getByText('中性 0 分，不等于清仓')).toBeInTheDocument()
    expect(screen.getByText('NO-OP')).toBeInTheDocument()
    expect(screen.getByText('547')).toBeInTheDocument()
    expect(screen.getByText('3170')).toBeInTheDocument()
    expect(screen.getByText('可提交研究评审')).toBeInTheDocument()
    expect(getQuantDemoScenario).toHaveBeenCalledOnce()
  })

  it('承接工作台来源并在模块内保留返回路径', async () => {
    document.documentElement.scrollTop = 120
    document.body.scrollTop = 120
    renderPage('/quant?from=workbench', <QuantModule />, '/quant/*')
    expect(await screen.findByText('已承接工作台研究上下文')).toBeInTheDocument()
    expect(document.documentElement.scrollTop).toBe(0)
    expect(document.body.scrollTop).toBe(0)
    expect(screen.getAllByRole('link', { name: '返回工作台' })[0]).toHaveAttribute('href', '/workbench')
    expect(screen.getByRole('link', { name: '研究信号' })).toHaveAttribute('href', '/quant/signals?from=workbench')
    expect(screen.getAllByRole('link', { name: /新建组合验证/ })[0]).toHaveAttribute('href', '/quant/new?from=workbench')
  })

  it('明确区分显式默认数据与 V3 候选版本', async () => {
    renderPage('/quant', <QuantOverviewPage />)
    expect((await screen.findAllByText('20260801-v2')).length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('V3 已登记为候选版本')).toBeInTheDocument()
    expect(screen.getByText('已登记候选 · 非默认')).toBeInTheDocument()
    expect(screen.getByText('V3：5,937 条行情；4,649/4,649 条 A 股证券日具备点时市值。')).toBeInTheDocument()
  })

  it('信号详情只呈现后端返回的可见来源并保留跳转', async () => {
    renderPage('/quant/signals/QSS-1', <QuantSignalSetDetailPage />, '/quant/signals/:signalSetId')
    expect(await screen.findByText('2/2 条可追溯')).toBeInTheDocument()
    expect(screen.getByText('中芯国际公告')).toBeInTheDocument()
    expect(screen.getAllByText(/不参与 Alpha 权重/).length).toBe(2)
    expect(screen.getAllByRole('link', { name: '查看证据' })[0]).toHaveAttribute('href', '/radar/EVD-1?relationId=REL-1')
    expect(getQuantSignalSetDetail).toHaveBeenCalledWith('QSS-1')
  })

  it('混合市场且市值不完整时阻断市值中性验证', async () => {
    renderPage(`/quant/new?marketDatasetId=${encodeURIComponent(v3.datasetId)}`, <QuantNewRunPage />)
    expect(await screen.findByText(/中芯国际 · 688981/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: /市值中性/ }))
    expect(await screen.findByText('运行前门禁未通过')).toBeInTheDocument()
    expect(screen.getByText('市值中性截面至少需要三只证券。')).toBeInTheDocument()
    expect(screen.getByText('所选证券区间存在点时市值缺口；包含港股时不能启用市值中性。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '运行组合验证' })).toBeDisabled()
  })

  it('行业中性遇到单例行业时在运行前硬阻断', async () => {
    renderPage(`/quant/new?marketDatasetId=${encodeURIComponent(v3.datasetId)}`, <QuantNewRunPage />)
    expect(await screen.findByText(/中芯国际 · 688981/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: '行业中性' }))
    expect(await screen.findByText(/单例行业：互联网、半导体/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '运行组合验证' })).toBeDisabled()
  })

  it('投资逻辑深链预选证券且受门禁模板应用治理预设', async () => {
    renderPage(`/quant/new?thesisId=THS-1&securityId=688981&marketDatasetId=${encodeURIComponent(v3.datasetId)}`, <QuantNewRunPage />)
    expect(await screen.findByText('从投资逻辑进入验证')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回投资逻辑 →' })).toHaveAttribute('href', '/theses/THS-1')
    expect(await screen.findByRole('checkbox', { name: /中芯国际 · 688981/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /腾讯控股 · 0700.HK/ })).not.toBeChecked()
    fireEvent.change(screen.getByLabelText('模型模板'), { target: { value: 'confirmed-event-industry-neutral-v3' } })
    expect(await screen.findByText(/单例行业：半导体/)).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: '行业中性' })).toBeChecked()
    expect(screen.getByRole('button', { name: '运行组合验证' })).toBeDisabled()
  })

  it('工作台标的不满足冻结输入门禁时明确说明且不伪造预选', async () => {
    renderPage(`/quant/new?from=workbench&thesisId=THS-1&securityId=09868&marketDatasetId=${encodeURIComponent(v3.datasetId)}`, <QuantNewRunPage />)
    expect(await screen.findByText(/工作台标的 (小鹏汽车 · )?09868 未被当前冻结数据与信号集共同覆盖，未自动勾选。/)).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /09868/ })).not.toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /中芯国际 · 688981/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /腾讯控股 · 0700.HK/ })).toBeChecked()
  })

  it('第 2 步按可回测、待信号和待数据三组展示完整研究范围', async () => {
    vi.mocked(getQuantSignalSetDetail).mockResolvedValueOnce({
      ...signalDetail,
      visibleSignalCount: 3,
      signals: [
        ...signalDetail.signals,
        { ...signalDetail.signals[0], signalId: 'SIG-3', securityId: '09868', sourceRelationId: 'REL-3', sourceEvidenceId: 'EVD-3' },
      ],
    })
    renderPage(`/quant/new?marketDatasetId=${encodeURIComponent(v3.datasetId)}`, <QuantNewRunPage />)

    expect(await screen.findByRole('heading', { name: '可回测证券' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '行情就绪 · 待确认信号' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '信号就绪 · 待补行情' })).toBeInTheDocument()
    expect(await screen.findByText('等待人工确认')).toBeInTheDocument()
    expect(screen.getByText('缺少冻结行情')).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: /兆易创新 · 603986/ })).not.toBeInTheDocument()
    expect(screen.getByText('小鹏汽车 · 09868')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('搜索研究证券'), { target: { value: '兆易' } })
    expect(screen.getByText('兆易创新 · 603986')).toBeInTheDocument()
    expect(screen.getByText('当前搜索下没有可回测证券。')).toBeInTheDocument()
  })

  it('因子目录区分当前生效、数据门禁和规划项', async () => {
    renderPage('/quant/factors', <QuantFactorsPage />)
    expect(await screen.findByText('人工确认事件方向与强度')).toBeInTheDocument()
    expect(screen.getByText('当前生效')).toBeInTheDocument()
    expect(screen.getByText('数据/截面门禁')).toBeInTheDocument()
    expect(screen.getByText('规划中')).toBeInTheDocument()
    expect(screen.getByText('AI 判断置信度不参与 Alpha 权重')).toBeInTheDocument()
    expect(screen.getAllByText('V1.0.0').length).toBeGreaterThan(0)
  })

  it('模型模板目录区分可运行、受门禁和不可运行版本', async () => {
    renderPage('/quant/models', <QuantModelsPage />)
    expect(await screen.findByText('人工确认事件研究')).toBeInTheDocument()
    expect(screen.getByText('已发布 · 可运行')).toBeInTheDocument()
    expect(screen.getByText('已发布 · 受门禁')).toBeInTheDocument()
    expect(screen.getByText('规划中 · 不可运行')).toBeInTheDocument()
    expect(screen.getByText('等待数据与方法准入')).toBeInTheDocument()
  })

  it('通过稳定 URL 恢复运行结果、净值与归因', async () => {
    renderPage('/quant/runs/QPF-test-001', <QuantRunDetailPage />, '/quant/runs/:runId')
    expect(await screen.findByText('V3 事件信号样本外验证')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /组合与基准净值曲线/ })).toBeInTheDocument()
    expect(screen.getByText('滚动样本外窗口')).toBeInTheDocument()
    expect(screen.getByText('风险因子暴露')).toBeInTheDocument()
    expect(screen.getByText('样本不足')).toBeInTheDocument()
    expect(screen.getByText('禁止直接宣称 Alpha')).toBeInTheDocument()
    expect(screen.getByText(/有效暴露期 2026-08-13 ~ 2026-08-28/)).toBeInTheDocument()
    expect(screen.getByText('HKD/CNY 未冻结汇率')).toBeInTheDocument()
    expect(screen.getByText('人工确认事件研究')).toBeInTheDocument()
    expect(getPortfolioBacktest).toHaveBeenCalledWith('QPF-test-001')
  })
})
