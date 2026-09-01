import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { NavLink, Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { listSecurities } from '../api'
import { EmptyState, ErrorState, InlineError, LoadingState } from '../components'
import type {
  PortfolioBacktestRequest,
  PortfolioBacktestRun,
  QuantFactorDefinition,
  QuantMarketDataset,
  QuantMarketDatasetDetail,
  QuantModelTemplate,
  QuantSecurityMetadata,
  QuantSignalSet,
} from '../types'
import {
  getMarketDatasetDetail,
  getPortfolioBacktest,
  getQuantCatalog,
  getQuantFactors,
  getQuantModelTemplates,
  getQuantSignalSetDetail,
  listPortfolioBacktests,
  runPortfolioBacktest,
} from './api'
import './quant.css'

const factorLabels: Record<string, string> = {
  market_beta: '市场 Beta',
  market_cap_rank: '市值秩暴露',
  average_net: '平均净暴露',
}

function shortHash(value?: string) {
  return value ? `${value.slice(0, 10)}…${value.slice(-6)}` : '—'
}

function dateTime(value?: string) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

function percent(value: unknown) {
  const number = Number(value)
  return Number.isFinite(number) ? `${number >= 0 ? '+' : ''}${(number * 100).toFixed(2)}%` : '—'
}

function decimal(value: unknown, digits = 3) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toFixed(digits) : '—'
}

function isV3(dataset: QuantMarketDataset) {
  return dataset.datasetId === 'MDS-akshare-qfq-tuaremax10000-20260831-v3'
}

function Status({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'good' | 'warn' | 'bad' | 'primary' }) {
  return <span className={`quant-status ${tone}`}>{children}</span>
}

function ResearchBoundary() {
  return <div className="quant-boundary" role="note"><strong>研究验证边界</strong><span>结果不构成投资建议，不生成订单、评级或调仓指令。</span></div>
}

function QuantLayout({ children }: { children: ReactNode }) {
  return <section className="quant-product">
    <header className="quant-page-header">
      <div><span className="eyebrow">MODELS &amp; FACTORS · GOVERNED RESEARCH</span><h1>模型与因子</h1><p>用冻结行情与人工确认信号，完成可追溯、可复算的样本外研究验证。</p></div>
      <NavLink className="button primary" to="/quant/new">＋ 新建组合验证</NavLink>
    </header>
    <nav className="quant-tabs" aria-label="模型与因子二级导航">
      <NavLink end to="/quant">研究概览</NavLink>
      <NavLink to="/quant/signals">研究信号</NavLink>
      <NavLink to="/quant/factors">因子目录</NavLink>
      <NavLink to="/quant/models">模型模板</NavLink>
      <NavLink to="/quant/new">新建验证</NavLink>
      <NavLink to="/quant/runs">历史运行</NavLink>
    </nav>
    <ResearchBoundary />
    {children}
  </section>
}

function DatasetCard({ dataset, defaultId, compact = false }: { dataset: QuantMarketDataset; defaultId: string | null; compact?: boolean }) {
  const isDefault = dataset.datasetId === defaultId
  return <article className={`quant-dataset-card ${compact ? 'compact' : ''}`}>
    <header><div><span className="mono">{dataset.datasetId}</span><h3>{dataset.dataVersion}</h3></div><div className="quant-status-row"><Status tone="good">已冻结</Status>{isDefault ? <Status tone="primary">当前默认</Status> : <Status tone="warn">已登记候选 · 非默认</Status>}</div></header>
    <dl><div><dt>覆盖区间</dt><dd>{dataset.coverageStart} ~ {dataset.coverageEnd}</dd></div><div><dt>证券范围</dt><dd>{dataset.securities.length} 只</dd></div><div><dt>复权口径</dt><dd>{dataset.adjustment}</dd></div><div><dt>清单哈希</dt><dd className="mono">{shortHash(dataset.manifestSha256)}</dd></div></dl>
    {isV3(dataset) && <p className="quant-v3-fact">V3：5,937 条行情；4,649/4,649 条 A 股证券日具备点时市值。</p>}
    <footer><NavLink to={`/assets/market-datasets/${encodeURIComponent(dataset.datasetId)}`}>查看冻结资产</NavLink><NavLink to={`/quant/new?marketDatasetId=${encodeURIComponent(dataset.datasetId)}`}>使用此版本验证 →</NavLink></footer>
  </article>
}

function SignalCard({ signal }: { signal: QuantSignalSet }) {
  return <article className="quant-signal-card">
    <header><div><span className="eyebrow">HUMAN-CONFIRMED SIGNALS</span><h3>{signal.name}</h3></div><Status tone={signal.humanConfirmedOnly ? 'good' : 'bad'}>{signal.humanConfirmedOnly ? '仅人工确认' : '不可用于验证'}</Status></header>
    <dl><div><dt>版本</dt><dd>{signal.version}</dd></div><div><dt>信号数</dt><dd>{signal.signalCount}</dd></div><div><dt>评测轨</dt><dd>{signal.evaluationTrack}</dd></div><div><dt>内容哈希</dt><dd className="mono">{shortHash(signal.contentSha256)}</dd></div></dl>
    <footer><span>{dateTime(signal.frozenAt)}</span><NavLink to={`/quant/signals/${encodeURIComponent(signal.signalSetId)}`}>查看来源 →</NavLink></footer>
  </article>
}

export function QuantOverviewPage() {
  const catalog = useQuery({ queryKey: ['quant-catalog'], queryFn: getQuantCatalog })
  const runs = useQuery({ queryKey: ['quant-portfolio-history'], queryFn: listPortfolioBacktests })
  if (catalog.isLoading || runs.isLoading) return <LoadingState text="正在读取模型与因子研究状态…" />
  if (catalog.error || runs.error || !catalog.data || !runs.data) return <ErrorState error={catalog.error ?? runs.error} />
  const defaultDataset = catalog.data.marketDatasets.find((item) => item.datasetId === catalog.data.defaultMarketDatasetId)
  const v3 = catalog.data.marketDatasets.find(isV3)
  const latestRun = runs.data[0]
  return <>
    <section className="quant-overview-grid" aria-label="研究状态概览">
      <article><span>显式默认数据</span><strong>{defaultDataset ? defaultDataset.dataVersion : '尚未登记'}</strong><small>只信任后端默认清单，不按时间推断</small></article>
      <article><span>已登记数据版本</span><strong>{catalog.data.marketDatasets.length}</strong><small>{v3 ? 'V3 已登记为候选版本' : '尚未发现 V3 候选'}</small></article>
      <article><span>人工确认信号</span><strong>{catalog.data.signalSets.reduce((sum, item) => sum + item.signalCount, 0)}</strong><small>{catalog.data.signalSets.length} 个不可变信号集</small></article>
      <article><span>我的历史运行</span><strong>{runs.data.length}</strong><small>{latestRun ? `最近 ${dateTime(latestRun.generatedAt)}` : '尚未执行组合验证'}</small></article>
    </section>
    <section className="quant-separation"><div><span className="eyebrow">THREE INDEPENDENT TRACKS</span><h2>语义准确率 · 检索排序 · Alpha 验证</h2><p>{catalog.data.evaluationSeparation.hardRule}</p></div><div><Status tone="good">SEMANTIC 独立</Status><Status tone="good">RETRIEVAL 独立</Status><Status tone="good">ALPHA 独立</Status></div></section>
    <section className="quant-section"><header><div><span className="eyebrow">FROZEN MARKET DATA</span><h2>行情与能力版本</h2></div><NavLink to="/assets/market-datasets">在数据中心查看全部 ›</NavLink></header>{catalog.data.marketDatasets.length ? <div className="quant-card-grid">{catalog.data.marketDatasets.map((dataset) => <DatasetCard key={dataset.datasetId} dataset={dataset} defaultId={catalog.data.defaultMarketDatasetId} />)}</div> : <EmptyState title="尚无已登记冻结行情" description="候选数据需要通过受控发布命令登记；普通研究员不能在页面切换默认版本。" />}</section>
    <section className="quant-section"><header><div><span className="eyebrow">GOVERNED SIGNALS</span><h2>人工确认研究信号</h2></div><NavLink to="/quant/signals">查看全部 ›</NavLink></header>{catalog.data.signalSets.length ? <div className="quant-card-grid">{catalog.data.signalSets.map((signal) => <SignalCard key={signal.signalSetId} signal={signal} />)}</div> : <EmptyState title="尚无可用于 Alpha 验证的信号" description="只有已人工确认、且生成时间不早于确认时间的信号才能冻结进入这里。" />}</section>
    {latestRun && <section className="quant-section"><header><div><span className="eyebrow">LATEST RUN</span><h2>最近一次组合验证</h2></div><NavLink to={`/quant/runs/${encodeURIComponent(latestRun.runId)}`}>打开完整结果 ›</NavLink></header><RunSummary run={latestRun} /></section>}
  </>
}

export function QuantSignalSetsPage() {
  const catalog = useQuery({ queryKey: ['quant-catalog'], queryFn: getQuantCatalog })
  if (catalog.isLoading) return <LoadingState text="正在读取冻结信号集…" />
  if (catalog.error || !catalog.data) return <ErrorState error={catalog.error} />
  return <section className="quant-section"><header><div><span className="eyebrow">SIGNAL CATALOG</span><h2>研究信号集</h2><p>信号只能来自已确认 Evidence/Relation，并保留披露、确认和生成时点。</p></div><span>{catalog.data.signalSets.length} 个版本</span></header>{catalog.data.signalSets.length ? <div className="quant-card-grid">{catalog.data.signalSets.map((signal) => <SignalCard key={signal.signalSetId} signal={signal} />)}</div> : <EmptyState title="没有可见信号集" description="请先在人工证据确认链完成冻结；AI 候选不能直接进入 Alpha 验证。" />}</section>
}

export function QuantSignalSetDetailPage() {
  const { signalSetId = '' } = useParams()
  const query = useQuery({ queryKey: ['quant-signal-set', signalSetId], queryFn: () => getQuantSignalSetDetail(signalSetId) })
  if (query.isLoading) return <LoadingState text="正在核验信号来源权限…" />
  if (query.error || !query.data) return <ErrorState error={query.error} />
  const data = query.data
  return <>
    <NavLink className="quant-back" to="/quant/signals">← 返回研究信号</NavLink>
    <section className="quant-detail-hero"><div><span className="eyebrow">FROZEN SIGNAL SET</span><h2>{data.name}</h2><p className="mono">{data.signalSetId}</p></div><div className="quant-status-row"><Status tone="good">{data.status}</Status><Status tone="primary">{data.evaluationTrack}</Status><Status tone="good">{data.visibleSignalCount}/{data.signalCount} 条可追溯</Status></div></section>
    <section className="quant-section"><header><div><span className="eyebrow">PROVENANCE</span><h2>人工确认来源</h2></div><NavLink className="button primary" to={`/quant/new?signalSetId=${encodeURIComponent(data.signalSetId)}`}>使用此信号集验证</NavLink></header><div className="quant-signal-table" role="table"><div className="quant-signal-head" role="row"><span>证券 / 信号</span><span>方向</span><span>披露 → 生成</span><span>来源关系</span><span>操作</span></div>{data.signals.map((signal) => <article role="row" key={signal.signalId}><div><strong>{signal.securityId}</strong><small className="mono">{signal.signalId}</small></div><div><Status tone={signal.direction === '冲突' ? 'bad' : signal.direction === '支持' ? 'good' : 'neutral'}>{signal.direction} · {signal.strength}</Status><small>AI 判断置信度 {Math.round(signal.confidence * 100)}% · 不参与 Alpha 权重</small></div><div><time>{dateTime(signal.disclosedAt)}</time><small>生成 {dateTime(signal.generatedAt)}</small></div><div><strong>{signal.sourceDocumentTitle ?? signal.sourceLocator}</strong><small className="mono">{signal.sourceRelationId} · {signal.sourceRelationStatus}</small></div><div className="quant-row-actions"><NavLink to={`/radar/${encodeURIComponent(signal.sourceEvidenceId)}?relationId=${encodeURIComponent(signal.sourceRelationId)}`}>查看证据</NavLink><NavLink to={`/theses/${encodeURIComponent(signal.thesisId)}`}>查看逻辑</NavLink>{signal.sourceDocumentId && <NavLink to={`/assets/documents/${encodeURIComponent(signal.sourceDocumentId)}`}>源资料</NavLink>}</div></article>)}</div></section>
  </>
}

const factorStatus: Record<string, { label: string; tone: 'good' | 'warn' | 'neutral' }> = {
  active: { label: '当前生效', tone: 'good' },
  gated: { label: '数据/截面门禁', tone: 'warn' },
  planned: { label: '规划中', tone: 'neutral' },
}

const factorCategory: Record<string, string> = {
  alpha_input: 'Alpha 输入', alpha_candidate: 'Alpha 候选', risk_control: '风险约束',
  risk_candidate: '风险候选', execution_constraint: '执行约束', diagnostic: '结果诊断',
}

function FactorCard({ factor }: { factor: QuantFactorDefinition }) {
  const status = factorStatus[factor.status] ?? { label: factor.status, tone: 'neutral' as const }
  return <article className="quant-factor-card">
    <header><div><span className="mono">{factor.factorId}</span><h3>{factor.name}</h3></div><div className="quant-status-row"><Status tone={status.tone}>{status.label}</Status>{factor.enabledByDefault && <Status tone="primary">默认启用</Status>}</div></header>
    <p>{factor.description}</p>
    <dl><div><dt>类别</dt><dd>{factorCategory[factor.category] ?? factor.category}</dd></div><div><dt>因子版本</dt><dd>V{factor.version}</dd></div><div><dt>频率</dt><dd>{factor.frequency}</dd></div><div><dt>覆盖</dt><dd>{factor.coverageScope}</dd></div><div><dt>方法版本</dt><dd>{factor.methodologyVersion}</dd></div><div><dt>发布日期</dt><dd>{factor.publishedAt}</dd></div></dl>
    <code>{factor.formula}</code>
    <div className="quant-factor-inputs">{factor.inputFields.map((item) => <span key={item}>{item}</span>)}</div>
    {factor.limitations.length > 0 && <ul>{factor.limitations.map((item) => <li key={item}>{item}</li>)}</ul>}
  </article>
}

export function QuantFactorsPage() {
  const query = useQuery({ queryKey: ['quant-factors'], queryFn: getQuantFactors })
  if (query.isLoading) return <LoadingState text="正在读取受治理因子目录…" />
  if (query.error || !query.data) return <ErrorState error={query.error} />
  const active = query.data.filter((item) => item.status === 'active').length
  const gated = query.data.filter((item) => item.status === 'gated').length
  const planned = query.data.filter((item) => item.status === 'planned').length
  return <>
    <section className="quant-separation"><div><span className="eyebrow">FACTOR GOVERNANCE</span><h2>当前能力、数据门禁和规划项分开管理</h2><p>目录描述“系统实际计算了什么”；规划因子不会进入组合权重，也不会出现在有效性宣称中。</p></div><div><Status tone="good">生效 {active}</Status><Status tone="warn">门禁 {gated}</Status><Status>规划 {planned}</Status></div></section>
    <section className="quant-section"><header><div><span className="eyebrow">GOVERNED FACTOR REGISTRY</span><h2>因子与约束目录</h2><p>当前唯一 Alpha 输入是人工确认的事件方向与强度；AI 判断置信度只保留为诊断元数据。</p></div><span>{query.data.length} 项</span></header><div className="quant-factor-grid">{query.data.map((factor) => <FactorCard factor={factor} key={factor.factorId} />)}</div></section>
  </>
}

const modelStatus: Record<string, { label: string; tone: 'good' | 'warn' | 'neutral' }> = {
  active: { label: '已发布 · 可运行', tone: 'good' },
  gated: { label: '已发布 · 受门禁', tone: 'warn' },
  planned: { label: '规划中 · 不可运行', tone: 'neutral' },
}

function ModelTemplateCard({ template }: { template: QuantModelTemplate }) {
  const status = modelStatus[template.status] ?? { label: template.status, tone: 'neutral' as const }
  const runnable = template.status !== 'planned' && Boolean(template.publishedAt)
  return <article className="quant-model-card">
    <header><div><span className="mono">{template.templateId}</span><h3>{template.name}</h3></div><Status tone={status.tone}>{status.label}</Status></header>
    <p>{template.description}</p>
    <dl><div><dt>模板版本</dt><dd>V{template.version}</dd></div><div><dt>方法版本</dt><dd>{template.methodologyVersion}</dd></div><div><dt>发布状态</dt><dd>{template.publishedAt ?? '尚未发布'}</dd></div><div><dt>治理负责人</dt><dd>{template.owner}</dd></div></dl>
    <div className="quant-model-factors"><div><strong>Alpha 因子</strong>{template.alphaFactorIds.map((item) => <code key={item}>{item}</code>)}</div><div><strong>控制与约束</strong>{template.controlFactorIds.map((item) => <code key={item}>{item}</code>)}</div></div>
    <div className="quant-model-defaults"><strong>参数预设</strong><span>滚动 {template.defaultConfig.rollingWindowDays} 日</span><span>测试 {template.defaultConfig.walkForwardDays} 日</span><span>再平衡 {template.defaultConfig.rebalanceDays} 日</span><span>成本 {template.defaultConfig.transactionCostBps} bps</span><span>滑点 {template.defaultConfig.slippageBps} bps</span><span>个股上限 {(template.defaultConfig.maxSecurityWeight * 100).toFixed(0)}%</span></div>
    <div className="quant-model-gate"><strong>研究候选样本门槛</strong><span>证券 ≥ {template.sampleGate.minimumUniqueSecurities}</span><span>观测 ≥ {template.sampleGate.minimumObservations}</span><span>有效暴露日 ≥ {template.sampleGate.minimumActiveTradingDays}</span></div>
    {template.limitations.length > 0 && <ul>{template.limitations.map((item) => <li key={item}>{item}</li>)}</ul>}
    <footer><NavLink to="/quant/factors">查看因子定义</NavLink>{runnable ? <NavLink className="button primary" to={`/quant/new?modelTemplateId=${encodeURIComponent(template.templateId)}`}>使用此模板</NavLink> : <span>等待数据与方法准入</span>}</footer>
  </article>
}

export function QuantModelsPage() {
  const query = useQuery({ queryKey: ['quant-model-templates'], queryFn: getQuantModelTemplates })
  if (query.isLoading) return <LoadingState text="正在读取已发布模型模板…" />
  if (query.error || !query.data) return <ErrorState error={query.error} />
  return <>
    <section className="quant-separation"><div><span className="eyebrow">MODEL VERSION GOVERNANCE</span><h2>模板是方法与参数预设，不是收益承诺</h2><p>运行会固化模板、方法、因子和参数版本；规划模板不可运行，受门禁模板仍需满足数据截面要求。</p></div><div><Status tone="good">可运行 {query.data.filter((item) => item.status === 'active').length}</Status><Status tone="warn">受门禁 {query.data.filter((item) => item.status === 'gated').length}</Status><Status>规划 {query.data.filter((item) => item.status === 'planned').length}</Status></div></section>
    <section className="quant-section"><header><div><span className="eyebrow">READ-ONLY TEMPLATE REGISTRY</span><h2>模型模板与发布版本</h2><p>页面只展示服务端发布目录；研究员可在模板默认值上调整非强制参数，最终有效参数会随运行保存。</p></div><span>{query.data.length} 个版本</span></header><div className="quant-model-grid">{query.data.map((template) => <ModelTemplateCard template={template} key={template.templateId} />)}</div></section>
  </>
}

type RunForm = {
  name: string
  start: string
  end: string
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

const defaultRunForm: RunForm = {
  name: '版本化组合事件信号研究', start: '', end: '', initialCapital: 1_000_000,
  rollingWindowDays: 60, walkForwardDays: 20, rebalanceDays: 5,
  transactionCostBps: 10, slippageBps: 5, maxSecurityWeight: .2,
  maxIndustryWeight: .4, capacityParticipationRate: .1,
  neutralizeIndustry: false, neutralizeMarketCap: false, enforceCapacity: true, allowShort: true,
}

function securityLabel(metadata: QuantSecurityMetadata, names: Map<string, string>) {
  return `${names.get(metadata.securityId) ?? metadata.securityId} · ${metadata.securityId}`
}

function datasetWarnings(dataset: QuantMarketDatasetDetail | undefined, selected: string[], neutralizeIndustry: boolean, neutralizeMarketCap: boolean, nonzeroSignalSecurities: Set<string>) {
  if (!dataset) return []
  const metadata = dataset.securityMetadata.filter((item) => selected.includes(item.securityId))
  const warnings: string[] = []
  const currencies = new Set(metadata.map((item) => item.currency))
  if (currencies.size > 1) warnings.push('所选组合包含 CNY/HKD；FX 尚未冻结，本次结果不得解释为可交易 Alpha。')
  if (!dataset.capabilities.price_limit_status) warnings.push('涨跌停状态仍有供应端缺口，成交可行性模拟不完整。')
  if (!dataset.capabilities.structured_corporate_action_events) warnings.push('结构化公司行动未启用，仅使用冻结前复权结果。')
  if (neutralizeIndustry) {
    const industryCounts = new Map<string, number>()
    metadata.filter((item) => nonzeroSignalSecurities.has(item.securityId)).forEach((item) => industryCounts.set(item.industry, (industryCounts.get(item.industry) ?? 0) + 1))
    const singletons = [...industryCounts.entries()].filter(([, count]) => count < 2).map(([industry]) => industry).sort()
    if (singletons.length) warnings.push(`行业中性要求每个有信号行业至少两只证券；单例行业：${singletons.join('、')}。`)
  }
  if (neutralizeMarketCap && selected.length < 3) warnings.push('市值中性截面至少需要三只证券。')
  if (neutralizeMarketCap && metadata.some((item) => !item.marketCapComplete)) warnings.push('所选证券区间存在点时市值缺口；包含港股时不能启用市值中性。')
  return warnings
}

export function QuantNewRunPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const [params] = useSearchParams()
  const catalog = useQuery({ queryKey: ['quant-catalog'], queryFn: getQuantCatalog })
  const templates = useQuery({ queryKey: ['quant-model-templates'], queryFn: getQuantModelTemplates })
  const securities = useQuery({ queryKey: ['securities'], queryFn: listSecurities })
  const [datasetId, setDatasetId] = useState(params.get('marketDatasetId') ?? '')
  const [signalSetId, setSignalSetId] = useState(params.get('signalSetId') ?? '')
  const [modelTemplateId, setModelTemplateId] = useState(params.get('modelTemplateId') ?? '')
  const [selected, setSelected] = useState<string[]>([])
  const [form, setForm] = useState<RunForm>(defaultRunForm)
  const researchThesisId = params.get('thesisId')
  const preferredSecurityId = params.get('securityId')
  const dataset = useQuery({ queryKey: ['quant-dataset', datasetId], queryFn: () => getMarketDatasetDetail(datasetId), enabled: Boolean(datasetId) })
  const signal = useQuery({ queryKey: ['quant-signal-set', signalSetId], queryFn: () => getQuantSignalSetDetail(signalSetId), enabled: Boolean(signalSetId) })
  useEffect(() => {
    if (!catalog.data) return
    if (!datasetId) setDatasetId(catalog.data.defaultMarketDatasetId ?? catalog.data.marketDatasets[0]?.datasetId ?? '')
    if (!signalSetId) setSignalSetId(catalog.data.signalSets[0]?.signalSetId ?? '')
  }, [catalog.data, datasetId, signalSetId])
  useEffect(() => {
    if (!templates.data || modelTemplateId) return
    setModelTemplateId(templates.data.find((item) => item.status === 'active')?.templateId ?? '')
  }, [modelTemplateId, templates.data])
  const selectedTemplate = templates.data?.find((item) => item.templateId === modelTemplateId)
  useEffect(() => {
    if (!selectedTemplate) return
    setForm((current) => ({ ...current, ...selectedTemplate.defaultConfig }))
  }, [selectedTemplate])
  useEffect(() => {
    if (!dataset.data) return
    setForm((current) => ({ ...current, start: current.start || dataset.data.coverageStart, end: current.end || dataset.data.coverageEnd }))
  }, [dataset.data])
  const available = useMemo(() => {
    if (!dataset.data || !signal.data) return []
    const signalIds = new Set(signal.data.signals.map((item) => item.securityId))
    return dataset.data.securityMetadata.filter((item) => signalIds.has(item.securityId))
  }, [dataset.data, signal.data])
  useEffect(() => {
    if (selected.length || !available.length) return
    const preferred = preferredSecurityId && available.some((item) => item.securityId === preferredSecurityId)
      ? [preferredSecurityId]
      : available.map((item) => item.securityId)
    setSelected(preferred)
  }, [available, preferredSecurityId, selected.length])
  useEffect(() => {
    setSelected([])
    setForm((current) => ({ ...current, start: '', end: '' }))
  }, [datasetId, signalSetId])
  const names = useMemo(() => new Map((securities.data ?? []).map((item) => [item.securityId, item.name])), [securities.data])
  const nonzeroSignalSecurities = new Set((signal.data?.signals ?? []).filter((item) => item.direction !== '中性').map((item) => item.securityId))
  const warnings = datasetWarnings(dataset.data, selected, form.neutralizeIndustry, form.neutralizeMarketCap, nonzeroSignalSecurities)
  const blockers = warnings.filter((item) => item.includes('行业中性要求') || item.includes('至少需要三只') || item.includes('点时市值缺口'))
  if (!selectedTemplate) blockers.push('必须选择一个已发布模型模板。')
  if (selectedTemplate?.status === 'planned' || (selectedTemplate && !selectedTemplate.publishedAt)) blockers.push('所选模型模板尚未发布，不能用于组合验证。')
  if (selectedTemplate?.requiredConfig.neutralizeIndustry !== undefined && form.neutralizeIndustry !== selectedTemplate.requiredConfig.neutralizeIndustry) blockers.push(`所选模型模板强制${selectedTemplate.requiredConfig.neutralizeIndustry ? '启用' : '关闭'}行业中性。`)
  if (selectedTemplate?.requiredConfig.neutralizeMarketCap !== undefined && form.neutralizeMarketCap !== selectedTemplate.requiredConfig.neutralizeMarketCap) blockers.push(`所选模型模板强制${selectedTemplate.requiredConfig.neutralizeMarketCap ? '启用' : '关闭'}市值中性。`)
  if (selectedTemplate?.requiredConfig.enforceCapacity !== undefined && form.enforceCapacity !== selectedTemplate.requiredConfig.enforceCapacity) blockers.push(`所选模型模板强制${selectedTemplate.requiredConfig.enforceCapacity ? '启用' : '关闭'}容量约束。`)
  if (selectedTemplate?.requiredConfig.allowShort !== undefined && form.allowShort !== selectedTemplate.requiredConfig.allowShort) blockers.push(`所选模型模板强制${selectedTemplate.requiredConfig.allowShort ? '启用' : '关闭'}研究型空头。`)
  const lateSignals = (signal.data?.signals ?? []).filter((item) => item.generatedAt.slice(0, 10) > (dataset.data?.coverageEnd ?? ''))
  if (lateSignals.length) blockers.push(`${lateSignals.length} 条信号晚于行情截止日 ${dataset.data?.coverageEnd}，必须选择更新的数据版本。`)
  if (form.start && dataset.data && form.start < dataset.data.coverageStart) blockers.push('开始日期早于数据集覆盖范围。')
  if (form.end && dataset.data && form.end > dataset.data.coverageEnd) blockers.push('结束日期晚于数据集覆盖范围。')
  if (form.start && form.end && form.start > form.end) blockers.push('开始日期不得晚于结束日期。')
  const mutation = useMutation({
    mutationFn: () => runPortfolioBacktest({
      name: form.name, marketDatasetId: datasetId, signalSetId, modelTemplateId, securityIds: selected,
      start: form.start, end: form.end,
      config: {
        initialCapital: form.initialCapital, rollingWindowDays: form.rollingWindowDays,
        walkForwardDays: form.walkForwardDays, rebalanceDays: form.rebalanceDays,
        transactionCostBps: form.transactionCostBps, slippageBps: form.slippageBps,
        maxSecurityWeight: form.maxSecurityWeight, maxIndustryWeight: form.maxIndustryWeight,
        capacityParticipationRate: form.capacityParticipationRate,
        neutralizeIndustry: form.neutralizeIndustry, neutralizeMarketCap: form.neutralizeMarketCap,
        enforceCapacity: form.enforceCapacity, allowShort: form.allowShort,
      },
    } satisfies PortfolioBacktestRequest),
    onSuccess: async (run) => {
      await qc.invalidateQueries({ queryKey: ['quant-portfolio-history'] })
      navigate(`/quant/runs/${encodeURIComponent(run.runId)}`)
    },
  })
  const update = <K extends keyof RunForm>(key: K, value: RunForm[K]) => setForm((current) => ({ ...current, [key]: value }))
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!datasetId || !signalSetId || !modelTemplateId || !selected.length || blockers.length) return
    mutation.mutate()
  }
  if (catalog.isLoading || templates.isLoading || securities.isLoading) return <LoadingState text="正在准备冻结研究环境…" />
  if (catalog.error || templates.error || securities.error || !catalog.data || !templates.data) return <ErrorState error={catalog.error ?? templates.error ?? securities.error} />
  return <form className="quant-run-form" onSubmit={submit}>
    {researchThesisId && <section className="quant-research-context" role="note"><div><span className="eyebrow">RESEARCH CONTEXT</span><strong>从投资逻辑进入验证</strong><p>逻辑与证券仅用于预填研究范围；实际 Alpha 输入仍以所选冻结信号集为准。</p></div><NavLink to={`/theses/${encodeURIComponent(researchThesisId)}`}>返回投资逻辑 →</NavLink></section>}
    <section className="quant-section"><header><div><span className="eyebrow">INPUT VERSIONS</span><h2>1. 选择冻结输入与模型模板</h2><p>数据、信号、模板和方法版本一经运行即形成不可变快照。</p></div></header><div className="quant-form-grid three"><label>模型模板<select value={modelTemplateId} onChange={(event) => setModelTemplateId(event.target.value)} required><option value="">请选择</option>{templates.data.map((item) => <option value={item.templateId} key={item.templateId} disabled={item.status === 'planned'}>{item.name} · V{item.version}{item.status === 'gated' ? ' · 受门禁' : item.status === 'planned' ? ' · 规划中' : ''}</option>)}</select></label><label>行情数据集<select value={datasetId} onChange={(event) => setDatasetId(event.target.value)} required><option value="">请选择</option>{catalog.data.marketDatasets.map((item) => <option value={item.datasetId} key={item.datasetId}>{item.dataVersion}{item.datasetId === catalog.data.defaultMarketDatasetId ? ' · 当前默认' : ' · 候选/历史'}</option>)}</select></label><label>人工确认信号集<select value={signalSetId} onChange={(event) => setSignalSetId(event.target.value)} required><option value="">请选择</option>{catalog.data.signalSets.map((item) => <option value={item.signalSetId} key={item.signalSetId}>{item.name} · {item.version}</option>)}</select></label></div>{selectedTemplate && <div className="quant-template-selection"><div><span>当前模板</span><strong>{selectedTemplate.name} · V{selectedTemplate.version}</strong></div><div><span>方法版本</span><strong>{selectedTemplate.methodologyVersion}</strong></div><div><span>Alpha 因子</span><strong>{selectedTemplate.alphaFactorIds.length}</strong></div><NavLink to="/quant/models">查看模板定义 →</NavLink></div>}{dataset.isLoading || signal.isLoading ? <LoadingState text="正在核验版本与来源…" /> : dataset.error || signal.error ? <ErrorState error={dataset.error ?? signal.error} /> : dataset.data && <DatasetCard compact dataset={dataset.data} defaultId={catalog.data.defaultMarketDatasetId} />}</section>
    <section className="quant-section"><header><div><span className="eyebrow">RESEARCH UNIVERSE</span><h2>2. 选择研究证券</h2><p>只展示数据集与当前可见信号集共同覆盖的证券。</p></div><span>{selected.length}/{available.length} 已选</span></header>{available.length ? <div className="quant-security-picker">{available.map((item) => <label key={item.securityId} className={selected.includes(item.securityId) ? 'selected' : ''}><input type="checkbox" checked={selected.includes(item.securityId)} onChange={() => setSelected((current) => current.includes(item.securityId) ? current.filter((id) => id !== item.securityId) : [...current, item.securityId])} /><span><strong>{securityLabel(item, names)}</strong><small>{item.market} · {item.currency} · {item.industry}</small></span><Status tone={item.marketCapComplete ? 'good' : 'warn'}>{item.marketCapComplete ? '点时市值完整' : '无完整市值'}</Status></label>)}</div> : <EmptyState title="没有共同覆盖的证券" description="请选择包含当前人工确认信号的行情版本。" />}</section>
    <section className="quant-section"><header><div><span className="eyebrow">RESEARCH CONFIGURATION</span><h2>3. 配置组合与样本外验证</h2></div></header><div className="quant-form-grid"><label>运行名称<input value={form.name} onChange={(event) => update('name', event.target.value)} required /></label><label>开始日期<input type="date" min={dataset.data?.coverageStart} max={dataset.data?.coverageEnd} value={form.start} onChange={(event) => update('start', event.target.value)} required /></label><label>结束日期<input type="date" min={dataset.data?.coverageStart} max={dataset.data?.coverageEnd} value={form.end} onChange={(event) => update('end', event.target.value)} required /></label><label>初始资金<input type="number" min="1" value={form.initialCapital} onChange={(event) => update('initialCapital', Number(event.target.value))} /></label><label>滚动窗口（日）<input type="number" min="2" max="756" value={form.rollingWindowDays} onChange={(event) => update('rollingWindowDays', Number(event.target.value))} /></label><label>测试窗口（日）<input type="number" min="1" max="252" value={form.walkForwardDays} onChange={(event) => update('walkForwardDays', Number(event.target.value))} /></label><label>再平衡周期（日）<input type="number" min="1" max="252" value={form.rebalanceDays} onChange={(event) => update('rebalanceDays', Number(event.target.value))} /></label><label>交易成本（bps）<input type="number" min="0" max="1000" value={form.transactionCostBps} onChange={(event) => update('transactionCostBps', Number(event.target.value))} /></label></div><details className="quant-advanced"><summary>高级参数与组合约束</summary><div className="quant-form-grid"><label>滑点（bps）<input type="number" min="0" max="1000" value={form.slippageBps} onChange={(event) => update('slippageBps', Number(event.target.value))} /></label><label>个股权重上限<input type="number" min="0.01" max="1" step="0.01" value={form.maxSecurityWeight} onChange={(event) => update('maxSecurityWeight', Number(event.target.value))} /></label><label>行业权重上限<input type="number" min="0.01" max="1" step="0.01" value={form.maxIndustryWeight} onChange={(event) => update('maxIndustryWeight', Number(event.target.value))} /></label><label>容量参与率<input type="number" min="0.01" max="1" step="0.01" value={form.capacityParticipationRate} onChange={(event) => update('capacityParticipationRate', Number(event.target.value))} /></label></div><div className="quant-toggle-grid"><label><input type="checkbox" checked={form.neutralizeIndustry} onChange={(event) => update('neutralizeIndustry', event.target.checked)} />行业中性</label><label><input type="checkbox" checked={form.neutralizeMarketCap} onChange={(event) => update('neutralizeMarketCap', event.target.checked)} />市值中性（仅完整纯 A 股截面）</label><label><input type="checkbox" checked={form.enforceCapacity} onChange={(event) => update('enforceCapacity', event.target.checked)} />执行容量约束</label><label><input type="checkbox" checked={form.allowShort} onChange={(event) => update('allowShort', event.target.checked)} />允许研究型空头信号</label></div></details></section>
    {(warnings.length > 0 || blockers.length > 0) && <section className={`quant-preflight ${blockers.length ? 'blocked' : 'warning'}`} aria-live="polite"><header><strong>{blockers.length ? '运行前门禁未通过' : '研究解释限制'}</strong><span>{blockers.length ? '请修正后再运行' : '可以运行，但必须保留以下限制'}</span></header><ul>{[...new Set([...blockers, ...warnings])].map((item) => <li key={item}>{item}</li>)}</ul></section>}
    <InlineError error={mutation.error} />
    <div className="quant-submit-bar"><div><strong>输入将绑定为不可变运行</strong><span>相同 Manifest、信号哈希、模板、因子版本、方法和参数会复用相同 QPF 编号。</span></div><button className="button primary" disabled={mutation.isPending || !modelTemplateId || !selected.length || blockers.length > 0}>{mutation.isPending ? '正在执行确定性计算…' : '运行组合验证'}</button></div>
  </form>
}

function RunSummary({ run }: { run: PortfolioBacktestRun }) {
  const metrics = run.result.metrics
  const activeRange = metrics.active_start_date ? `${String(metrics.active_start_date)} ~ ${String(metrics.active_end_date ?? '—')}` : undefined
  return <div className="quant-run-summary"><article><span>组合收益</span><strong>{percent(metrics.total_return)}</strong><small>{activeRange ? `有效暴露期 ${activeRange}` : '历史方法未记录有效暴露期'}</small></article><article><span>有效暴露期超额</span><strong>{percent(metrics.excess_return)}</strong><small>同期基准 {percent(metrics.benchmark_return)} · 成本已计入</small></article><article><span>最大回撤</span><strong>{percent(metrics.max_drawdown)}</strong><small>跟踪误差 {percent(metrics.tracking_error)}</small></article><article><span>信息比率</span><strong>{metrics.information_ratio == null ? '—' : decimal(metrics.information_ratio, 2)}</strong><small>全区间基准 {percent(metrics.full_period_benchmark_return ?? metrics.benchmark_return)}</small></article></div>
}

function ValidationQualityPanel({ run }: { run: PortfolioBacktestRun }) {
  const quality = run.result.validationQuality
  if (!quality) return <section className="quant-preflight warning"><header><strong>历史运行未包含样本质量分级</strong><span>请使用 portfolio-research-v3 重新运行</span></header></section>
  const tone = quality.status === 'research_candidate' ? 'good' : quality.status === 'engineering_test' ? 'bad' : 'warn'
  return <section className={`quant-quality-panel ${tone}`}><header><div><span className="eyebrow">VALIDATION QUALITY</span><h2>{quality.label}</h2></div><Status tone={tone}>{quality.alphaClaimAllowed ? '可宣称 Alpha' : '禁止直接宣称 Alpha'}</Status></header><div className="quant-quality-metrics"><div><span>证券覆盖</span><strong>{quality.uniqueSecurityCount}</strong><small>候选门槛 20</small></div><div><span>非零信号</span><strong>{quality.nonzeroSignalCount}</strong></div><div><span>前瞻观测</span><strong>{quality.observationCount}</strong><small>候选门槛 100</small></div><div><span>有效暴露日</span><strong>{quality.activeTradingDays}</strong><small>候选门槛 60</small></div></div>{quality.reasons.length > 0 && <ul>{quality.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}</section>
}

function EquityCurve({ run }: { run: PortfolioBacktestRun }) {
  const rows = run.result.equityCurve
  if (rows.length < 2) return <EmptyState title="净值路径不可用" description="当前运行没有足够的逐日结果用于绘图。" />
  const values = rows.flatMap((row) => [Number(row.equity), Number(row.benchmark_equity)]).filter(Number.isFinite)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const scaleX = (index: number) => 24 + index / (rows.length - 1) * 752
  const scaleY = (value: number) => 24 + (max === min ? .5 : (max - value) / (max - min)) * 212
  const path = (key: 'equity' | 'benchmark_equity') => rows.map((row, index) => `${index ? 'L' : 'M'}${scaleX(index).toFixed(1)},${scaleY(Number(row[key])).toFixed(1)}`).join(' ')
  return <div className="quant-chart-wrap"><svg className="quant-equity-chart" viewBox="0 0 800 270" role="img" aria-label={`组合与基准净值曲线，共 ${rows.length} 个交易日`}><line x1="24" y1="236" x2="776" y2="236" /><line x1="24" y1="24" x2="24" y2="236" /><path className="portfolio" d={path('equity')} /><path className="benchmark" d={path('benchmark_equity')} /><text x="28" y="258">{String(rows[0].trading_date)}</text><text x="670" y="258">{String(rows.at(-1)?.trading_date)}</text></svg><div className="quant-chart-legend"><span><i className="portfolio" />组合净值</span><span><i className="benchmark" />基准净值</span><small>区间 {String(rows[0].trading_date)} 至 {String(rows.at(-1)?.trading_date)}；期末组合 {decimal(rows.at(-1)?.equity, 2)}，基准 {decimal(rows.at(-1)?.benchmark_equity, 2)}</small></div></div>
}

function ExposureList({ values, factor = false }: { values: Record<string, number | string>; factor?: boolean }) {
  const entries = Object.entries(values)
  if (!entries.length) return <p className="quant-muted">当前样本没有可展示归因。</p>
  const max = Math.max(...entries.map(([, value]) => Math.abs(Number(value))), .000001)
  return <div className="quant-exposure-list">{entries.map(([name, value]) => <div key={name}><span>{factor ? factorLabels[name] ?? name : name}</span><div><i style={{ width: `${Math.max(3, Math.abs(Number(value)) / max * 100)}%` }} /></div><strong>{factor ? decimal(value) : percent(value)}</strong></div>)}</div>
}

export function QuantRunDetailPage() {
  const { runId = '' } = useParams()
  const run = useQuery({ queryKey: ['quant-run', runId], queryFn: () => getPortfolioBacktest(runId) })
  const catalog = useQuery({ queryKey: ['quant-catalog'], queryFn: getQuantCatalog })
  const templates = useQuery({ queryKey: ['quant-model-templates'], queryFn: getQuantModelTemplates })
  if (run.isLoading || catalog.isLoading || templates.isLoading) return <LoadingState text="正在恢复不可变运行…" />
  if (run.error || catalog.error || templates.error || !run.data || !catalog.data || !templates.data) return <ErrorState error={run.error ?? catalog.error ?? templates.error} />
  const data = run.data
  const dataset = catalog.data.marketDatasets.find((item) => item.datasetId === data.marketDatasetId)
  const signal = catalog.data.signalSets.find((item) => item.signalSetId === data.signalSetId)
  const modelTemplateId = typeof data.parameters.model_template_id === 'string' ? data.parameters.model_template_id : undefined
  const modelTemplateVersion = typeof data.parameters.model_template_version === 'string' ? data.parameters.model_template_version : undefined
  const modelTemplate = templates.data.find((item) => item.templateId === modelTemplateId)
  return <>
    <NavLink className="quant-back" to="/quant/runs">← 返回历史运行</NavLink>
    <section className="quant-detail-hero"><div><span className="eyebrow">IMMUTABLE PORTFOLIO RUN</span><h2>{data.name}</h2><p className="mono">{data.runId}</p></div><div className="quant-status-row"><Status tone="good">已完成</Status><Status tone="primary">{data.evaluationTrack}</Status><Status>{data.methodologyVersion}</Status></div></section>
    <RunSummary run={data} />
    <ValidationQualityPanel run={data} />
    <section className="quant-section"><header><div><span className="eyebrow">EQUITY PATH</span><h2>组合与基准净值</h2></div><span>{data.result.equityCurve.length} 个交易日</span></header><EquityCurve run={data} /></section>
    <section className="quant-section"><header><div><span className="eyebrow">WALK-FORWARD</span><h2>滚动样本外窗口</h2></div><span>{data.result.walkForward.length} 个窗口</span></header>{data.result.walkForward.length ? <div className="quant-table-wrap"><table><thead><tr><th>训练区间</th><th>测试区间</th><th>样本</th><th>组合收益</th><th>基准</th><th>超额</th></tr></thead><tbody>{data.result.walkForward.map((item, index) => <tr key={`${item.test_start}-${index}`}><td>{String(item.train_start)} ~ {String(item.train_end)}</td><td>{String(item.test_start)} ~ {String(item.test_end)}</td><td>{String(item.observation_count)}</td><td>{percent(item.total_return)}</td><td>{percent(item.benchmark_return)}</td><td>{percent(item.excess_return)}</td></tr>)}</tbody></table></div> : <EmptyState title="没有样本外窗口" description="当前区间不足以形成滚动训练和测试窗口。" />}</section>
    <div className="quant-two-columns"><section className="quant-section"><header><div><span className="eyebrow">SIGNAL RESEARCH</span><h2>信号区分度</h2></div></header><div className="quant-mini-metrics"><div><span>观测数</span><strong>{data.result.signalResearch.observationCount}</strong></div><div><span>IC</span><strong>{data.result.signalResearch.ic == null ? '无可用样本' : decimal(data.result.signalResearch.ic)}</strong></div><div><span>Rank IC</span><strong>{data.result.signalResearch.rankIc == null ? '无可用样本' : decimal(data.result.signalResearch.rankIc)}</strong></div></div><ExposureList values={data.result.signalResearch.quantileReturns} /></section><section className="quant-section"><header><div><span className="eyebrow">FACTOR EXPOSURE</span><h2>风险因子暴露</h2></div></header><ExposureList factor values={data.result.riskAttribution.factorExposure} /></section></div>
    <div className="quant-two-columns"><section className="quant-section"><header><div><span className="eyebrow">SECURITY RISK</span><h2>证券风险贡献</h2></div></header><ExposureList values={data.result.riskAttribution.security} /></section><section className="quant-section"><header><div><span className="eyebrow">INDUSTRY RISK</span><h2>行业风险贡献</h2></div></header><ExposureList values={data.result.riskAttribution.industry} /></section></div>
    <section className="quant-section quant-diagnostics"><header><div><span className="eyebrow">DIAGNOSTICS &amp; REPRODUCIBILITY</span><h2>诊断与复现信息</h2></div></header><div className="quant-diagnostic-grid"><article><span>输入信号</span><strong>{data.result.diagnostics.inputSignalCount}</strong></article><article><span>接收信号</span><strong>{data.result.diagnostics.acceptedSignalCount}</strong></article><article><span>跳过信号</span><strong>{data.result.diagnostics.skippedSignals.length}</strong></article><article><span>阻断交易</span><strong>{data.result.diagnostics.blockedTrades.length}</strong></article></div><div className="quant-provenance"><div><span>模型模板</span><strong>{modelTemplate?.name ?? modelTemplateId ?? '历史运行未绑定模板'}</strong>{modelTemplateId ? <NavLink to="/quant/models">{modelTemplateVersion ? `V${modelTemplateVersion}` : modelTemplateId} →</NavLink> : <small>旧记录保持可读，不补写虚假版本</small>}</div><div><span>行情数据集</span><strong>{dataset?.dataVersion ?? data.marketDatasetId}</strong><NavLink to={`/assets/market-datasets/${encodeURIComponent(data.marketDatasetId)}`}>{shortHash(dataset?.manifestSha256)} →</NavLink></div><div><span>研究信号集</span><strong>{signal?.name ?? data.signalSetId}</strong><NavLink to={`/quant/signals/${encodeURIComponent(data.signalSetId)}`}>{shortHash(signal?.contentSha256)} →</NavLink></div><div><span>方法版本</span><strong>{data.methodologyVersion}</strong><small>{dateTime(data.generatedAt)}</small></div></div>{[...data.result.diagnostics.warnings, ...data.result.diagnostics.skippedSignals, ...data.result.diagnostics.blockedTrades].length > 0 && <ul className="quant-warning-list">{[...data.result.diagnostics.warnings, ...data.result.diagnostics.skippedSignals, ...data.result.diagnostics.blockedTrades].map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>}<details className="quant-parameters"><summary>查看完整运行参数</summary><pre>{JSON.stringify(data.parameters, null, 2)}</pre></details></section>
  </>
}

export function QuantRunsPage() {
  const runs = useQuery({ queryKey: ['quant-portfolio-history'], queryFn: listPortfolioBacktests })
  const catalog = useQuery({ queryKey: ['quant-catalog'], queryFn: getQuantCatalog })
  const [query, setQuery] = useState('')
  if (runs.isLoading || catalog.isLoading) return <LoadingState text="正在读取本人历史运行…" />
  if (runs.error || catalog.error || !runs.data || !catalog.data) return <ErrorState error={runs.error ?? catalog.error} />
  const datasetNames = new Map(catalog.data.marketDatasets.map((item) => [item.datasetId, item.dataVersion]))
  const signalNames = new Map(catalog.data.signalSets.map((item) => [item.signalSetId, item.name]))
  const needle = query.trim().toLowerCase()
  const visible = runs.data.filter((item) => !needle || [item.runId, item.name, item.marketDatasetId, item.signalSetId, item.methodologyVersion, typeof item.parameters.model_template_id === 'string' ? item.parameters.model_template_id : undefined, datasetNames.get(item.marketDatasetId), signalNames.get(item.signalSetId)].some((value) => value?.toLowerCase().includes(needle)))
  return <section className="quant-section"><header><div><span className="eyebrow">MY IMMUTABLE RUNS</span><h2>历史运行</h2><p>默认只显示当前用户最近 50 次运行，详情链接可刷新和分享给同一有权账号复看。</p></div><span>{visible.length}/{runs.data.length} 次</span></header><label className="quant-run-search"><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索运行名称、QPF 编号、数据或方法版本" /></label>{visible.length ? <div className="quant-run-list">{visible.map((run) => <NavLink key={run.runId} to={`/quant/runs/${encodeURIComponent(run.runId)}`}><div><span className="mono">{run.runId}</span><h3>{run.name}</h3><small>{datasetNames.get(run.marketDatasetId) ?? run.marketDatasetId}</small></div><div><Status tone="primary">{run.evaluationTrack}</Status><strong>{percent(run.result.metrics.excess_return)}</strong><small>{dateTime(run.generatedAt)}</small></div><span aria-hidden>→</span></NavLink>)}</div> : <EmptyState title={runs.data.length ? '没有符合筛选的运行' : '尚无历史运行'} description={runs.data.length ? '请调整搜索条件。' : '从新建验证选择冻结数据和人工确认信号开始。'} action={!runs.data.length ? <NavLink className="button primary" to="/quant/new">新建组合验证</NavLink> : undefined} />}</section>
}

export function QuantModule() {
  return <QuantLayout><Routes><Route index element={<QuantOverviewPage />} /><Route path="signals" element={<QuantSignalSetsPage />} /><Route path="signals/:signalSetId" element={<QuantSignalSetDetailPage />} /><Route path="factors" element={<QuantFactorsPage />} /><Route path="models" element={<QuantModelsPage />} /><Route path="new" element={<QuantNewRunPage />} /><Route path="runs" element={<QuantRunsPage />} /><Route path="runs/:runId" element={<QuantRunDetailPage />} /><Route path="*" element={<EmptyState title="模型与因子页面不存在" description="请从研究概览重新进入。" action={<NavLink className="button primary" to="/quant">返回研究概览</NavLink>} />} /></Routes></QuantLayout>
}

export default QuantModule
