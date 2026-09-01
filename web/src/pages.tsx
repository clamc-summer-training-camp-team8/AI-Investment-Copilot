import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Navigate, NavLink, useParams, useSearchParams } from 'react-router-dom'
import {
  batchReviewRelations, createRelation, createReviewDraft, deactivateRelation, decideAdjudication, decideStatus, getAudit, getLatestDecisionBatch,
  getDocumentSegment, getEvidence, getEvidenceRetrievalTrace, getFullDocument, getInvestodayCollectionStatus, getRadarEvidence, getRelations, getResearchUpdates, getSuggestions, syncTodayResearch,
  getLogicChangeDigest, getPublishReadiness, getThesis, getThesisEvidenceFeed, getTrends, getWorkbench, getWorkbenchTasks, recheckThesisQuality,
  listAdjudications, listIngestionReviews, listMetrics, listProcessingJobs, listReviewTasks, listTheses,
  publishThesis, replayProcessingJob, resolveIngestionReview, resolveReviewTask,
  createHypothesis, recommendHypothesisMetrics, reviewRelation, saveMetricMapping, updateHypothesis,
  updateRelation, updateThesisMaintenance,
  getAssetInventory, getDataCenterOverview, rebuildAssetSearchIndex, searchAssets,
  createThesisRevision, getThesisRevisionDiff, publishThesisRevision, updateThesisRevision,
  getGoldQuality, getQuantCatalog, listPortfolioBacktests, registerDefaultMarketDataset, runPortfolioBacktest,
  getCompanyMetricCenter, getSecurity, getMaintainedCoverage, getCoverageUniverse, refreshCompanyMetrics,
  createCoverageSector, createCoverageCompany, updateCoverageCompany, updateCoverageSector,
  listDataCenterDocuments,
} from './api'
import type { CompanyMetric, Trend } from './types'
import {
  ConfirmDialog, DirectionBadge, EmptyState, ErrorState, EvidenceEventRow,
  InlineError, LoadingState, PageTitle, PriorityBadge, StatusBadge, ValidationChain,
} from './components'
import { buildCompanyEvidenceCards, getConfirmedHypothesisEvidenceState } from './companyEvidence'
import type { CompanyEvidenceCard } from './companyEvidence'
import { MetricEditorCard } from './metric-editor'
import { getRetrospectiveOverview } from './retrospective/api'
import type { Adjudication, AuditItem, DataCenterDocument, EvidenceFeedItem, EvidenceRetrievalTrace, GoldQualityGate, Hypothesis, IngestionReview, InvestodayCollectionStatus, LogicChangeDigestDetail, MetricDefinition, ProcessingJob, PortfolioBacktestRun, Relation, ReviewTask, Security, Suggestion, ThesisDetail, ThesisRevision } from './types'
import { formatDate, strengthText } from './ui'

export function OperationalWorkbenchPage() {
  const summary = useQuery({ queryKey: ['workbench'], queryFn: getWorkbench })
  const tasks = useQuery({ queryKey: ['workbench-tasks'], queryFn: () => getWorkbenchTasks(20) })
  const quality = useQuery({ queryKey: ['gold-quality'], queryFn: getGoldQuality })
  if (summary.isLoading || tasks.isLoading) return <LoadingState />
  if (summary.error || tasks.error || !summary.data || !tasks.data) return <ErrorState error={summary.error ?? tasks.error} />
  const first = tasks.data.items[0]
  const metrics = [
    ['待核验变化', tasks.data.total, '需要确认与投资假设的关系'],
    ['状态建议', summary.data.pendingSuggestions.length, '等待负责人最终决策'],
    ['到期复核', summary.data.reviewDue.length, '需要重新审视逻辑结论'],
    ['重大风险', tasks.data.items.filter((item) => item.priority === 'high').length, '高强度冲突或风险状态'],
  ] as const
  return <>
    <PageTitle eyebrow="研究员任务中心" title="今天最需要处理什么" description="按影响程度与披露时间排序，先完成最关键的证据核验。" />
    {quality.data && <section className="product-status-strip" aria-label="当前产品质量状态"><div><span className="eyebrow">产品就绪状态</span><strong>{quality.data.summary.goldSamples} 条最终金标已冻结</strong><p>{quality.data.summary.adjudicatedSamples} 条分歧完成裁决 · {quality.data.summary.evaluationEligibleSamples} 条可用于系统评测</p></div><div className="status-strip-flags"><span className="flag-passed">FINAL GOLD READY</span><span className={quality.data.summary.graphRagRolloutReady ? 'flag-passed' : 'flag-blocked'}>GRAPH RAG {quality.data.summary.graphRagRolloutReady ? 'READY' : 'BENCHMARK PENDING'}</span><NavLink className="primary-link inline" to="/quality">查看门禁详情 →</NavLink></div></section>}
    <section className="hero-section"><div className="section-heading"><div><span className="eyebrow">今日首要事项</span><h2>{first ? '先处理这条变化' : '当前没有紧急事项'}</h2></div>{first && <PriorityBadge priority={first.priority} />}</div>{first ? <EvidenceEventRow item={first} featured /> : <EmptyState title="待办已清空" description="当前没有需要人工核验的证据。" />}</section>
    <section className="metric-grid">{metrics.map(([label, value, note]) => <div className="metric-card" key={label}><span>{label}</span><strong>{value}</strong><p>{note}</p></div>)}</section>
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">全部待办</span><h2>待核验变化</h2></div><span className="muted">共 {tasks.data.total} 条</span></div><div className="evidence-list">{tasks.data.items.length ? tasks.data.items.map((item) => <EvidenceEventRow item={item} key={`${item.evidenceId}-${item.relationId}`} />) : <EmptyState title="没有待核验变化" description="新的公开信息进入系统后会显示在这里。" />}</div></section>
  </>
}

export function LegacyWorkbenchPage({ onCreate }: { onCreate?: () => void } = {}) {
  const [feedFilter, setFeedFilter] = useState('全部')
  const [expandedIndustries, setExpandedIndustries] = useState<Set<string>>(new Set())
  const coverage = useQuery({ queryKey: ['maintained-coverage'], queryFn: getMaintainedCoverage, staleTime: 30_000 })
  const events = [
    { time: '09:42', company: '比亚迪', source: '公司公告', title: '2024年一季度业绩预告：归母净利润同比增长 86.04%–118.88%', thesis: '销量增长驱动盈利提升；规模效应改善毛利率', importance: '高重要性', direction: '支持', status: 'AI生成' },
    { time: '09:15', company: '中芯国际', source: '行业资讯 · 芯思想', title: 'Q1产能利用率提升至 92.1%，价格年内趋稳', thesis: '成熟制程需求回暖；产能利用率提升驱动盈利改善', importance: '高重要性', direction: '支持', status: 'AI生成' },
    { time: '08:47', company: '恒瑞医药', source: '公司公告', title: '注射用 SHR-A1811 获批开展 III 期临床试验', thesis: '创新药管线持续推进；海外授权预期增强', importance: '高重要性', direction: '支持', status: 'AI生成' },
    { time: '08:21', company: '小鹏汽车', source: '媒体报道 · 36氪', title: '小鹏汽车与大众汽车集团签署平台与软件战略技术合作框架协议', thesis: '平台化合作提升长期销量与盈利弹性', importance: '中重要性', direction: '支持', status: 'AI生成' },
    { time: '07:58', company: '吉利汽车', source: '行业数据 · 乘联会', title: '4月新能源乘用车批发销量同比 +32.4%，环比 -8.7%', thesis: '行业需求增长出现弱点；价格战可能影响利润率', importance: '高重要性', direction: '冲突', status: 'AI生成' },
    { time: '07:30', company: '中芯国际', source: '券商研报 · 中金公司', title: '成熟制程稼动率改善，长期资本开支持续受益国产替代', thesis: '国产替代加速；长期 ROE 中枢上移', importance: '中重要性', direction: '支持', status: '研究员确认' },
  ] as const
  const logicRows = [
    ['比亚迪', '规模效应＋技术领先驱动销量与盈利双升', '强化', '今日 09:42 业绩预告超预期'],
    ['吉利汽车', '新能源转型加速＋新品周期驱动份额提升', '承压', '今日 07:58 行业增速放缓'],
    ['小鹏汽车', '智能化差异化＋成本改善提升盈利弹性', '稳定', '今日 08:21 战略合作落地'],
    ['恒瑞医药', '创新药管线兑现＋国际化提升长期空间', '强化', '今日 08:47 III期临床获批'],
    ['中芯国际', '国产替代＋稼动率提升驱动盈利改善', '待观察', '今日 09:15 数据待进一步验证'],
  ] as const
  const filteredEvents = feedFilter === '全部' ? events : events.filter((item) => feedFilter === '公司' ? item.source === '公司公告' : feedFilter === '行业' ? item.source.includes('行业') : feedFilter === '宏观' ? item.source.includes('宏观') : true)
  const toggleIndustry = (name: string) => setExpandedIndustries((current) => {
    const next = current.size ? new Set(current) : new Set((coverage.data ?? []).map((item) => item.name))
    if (next.has(name)) next.delete(name); else next.add(name)
    return next
  })
  return <div className="dashboard-page">
    <aside className="coverage-panel" aria-label="我的覆盖"><div className="dashboard-panel-title"><h1>我的覆盖</h1><NavLink to="/coverage" aria-label="管理覆盖范围">⚙</NavLink></div>{coverage.isLoading && <div className="coverage-loading" role="status">正在加载维护中的公司…</div>}{coverage.error && <div className="coverage-loading coverage-loading-error">覆盖数据暂时不可用</div>}{coverage.data?.map((industry) => { const expanded = expandedIndustries.size === 0 || expandedIndustries.has(industry.name); return <section className="coverage-group" key={industry.name}><button className="coverage-industry" aria-expanded={expanded} onClick={() => toggleIndustry(industry.name)}><span>{expanded ? '⌄' : '›'} ▥ {industry.name}</span><b>{industry.companies.length}</b></button>{expanded && <div className="coverage-companies">{industry.companies.map((company) => <NavLink to={`/companies/${encodeURIComponent(company.securityId)}`} key={company.securityId}><span><strong>▥ {company.name}</strong><small>{company.industry || '行业分类待补充'}</small></span></NavLink>)}</div>}</section>})}{coverage.data && coverage.data.length === 0 && <div className="coverage-loading">暂无正在维护的公司</div>}<nav className="coverage-links" aria-label="研究功能"><NavLink to="/coverage">⌁ 行业总览</NavLink><NavLink to="/macro-strategy">▧ 宏观与策略</NavLink><NavLink to="/assets">▤ 数据中心</NavLink><NavLink to="/assets">⌕ 知识库</NavLink><NavLink to="/theses">◇ 投资逻辑</NavLink><NavLink to="/quant">▦ 模型与因子</NavLink><NavLink to="/assets">▱ 研报与文档</NavLink><NavLink to="/radar">♧ 监控与预警</NavLink></nav><button className="new-research-button" onClick={onCreate}>＋ 新建研究主题</button></aside>
    <main className="dashboard-main"><section className="dashboard-card research-feed" aria-labelledby="research-feed-title"><header className="dashboard-card-header"><h2 id="research-feed-title">今日研究动态</h2><button>筛选 ⌄</button></header><div className="feed-tabs" role="tablist" aria-label="动态分类">{['全部', '公司', '行业', '宏观', '政策'].map((tab) => <button role="tab" aria-selected={feedFilter === tab} className={feedFilter === tab ? 'active' : ''} onClick={() => setFeedFilter(tab)} key={tab}>{tab}<span>{tab === '全部' ? 12 : tab === '公司' ? 8 : tab === '行业' ? 2 : 1}</span></button>)}</div><div className="dashboard-feed-list">{filteredEvents.map((item, index) => <article className="dashboard-event" key={`${item.time}-${item.company}`}><time>{item.time}</time><i className={item.direction === '冲突' ? 'conflict' : ''} /><div className="event-copy"><div className="event-meta"><strong>{item.company}</strong><span>{item.source}</span></div><h3>{item.title}</h3><p>相关假设：{item.thesis}</p></div><span className={`importance importance-${item.importance[0]}`}>{item.importance}</span><strong className={`direction-text ${item.direction === '冲突' ? 'conflict' : ''}`}>{item.direction} {item.direction === '支持' ? '↑' : '↓'}</strong><div className="event-actions"><span className={item.status === '研究员确认' ? 'human-label' : 'ai-label'}>{item.status}</span><NavLink to={`/updates/${index + 1}`}>查看影响</NavLink><button>加入证据</button></div></article>)}</div><NavLink className="dashboard-more" to="/updates">查看更多动态 ⌄</NavLink></section>
    <section className="dashboard-card logic-status" aria-labelledby="logic-title"><header className="dashboard-card-header"><h2 id="logic-title">主投资逻辑状态</h2><span>截至今天 10:00</span></header><div className="logic-table" role="table"><div className="logic-table-head" role="row"><span>公司</span><span>当前主投资逻辑</span><span>状态</span><span>最新变化</span><span>操作</span></div>{logicRows.map(([company, logic, status, change]) => <div className="logic-table-row" role="row" key={company}><strong>{company}</strong><span>{logic}</span><b className={`logic-state state-${status}`}>{status}</b><span>{change}</span><NavLink to="/theses">查看演变</NavLink></div>)}</div><NavLink className="dashboard-more" to="/theses">查看全部公司逻辑 ›</NavLink></section>
    <section className="dashboard-card indicator-panel"><header className="dashboard-card-header"><h2>关键指标异动</h2><NavLink to="/radar">更多 ›</NavLink></header>{[['比亚迪', '毛利率（%）', '20.14', '+2.41', 'up'], ['中芯国际', '产能利用率（%）', '92.1', '-3.12', 'down'], ['吉利汽车', '单车均价（万元）', '11.28', '-1.18', 'down']].map(([company, metric, value, delta, trend], index) => <div className="indicator-row" key={company}><strong>{company}</strong><span>{metric}</span><b>{value}</b><svg viewBox="0 0 120 28" aria-label={`${company}${metric}趋势`}><polyline points={index === 0 ? '0,19 12,18 24,20 36,13 48,16 60,5 72,17 84,12 96,18 108,15 120,18' : '0,8 12,11 24,6 36,13 48,10 60,17 72,14 84,20 96,16 108,21 120,18'} /></svg><em className={trend}>{delta} {trend === 'up' ? '↑' : '↓'}</em></div>)}<NavLink className="dashboard-more" to="/radar">查看全部异常指标 ›</NavLink></section></main>
    <aside className="dashboard-right"><section className="dashboard-card attention-card"><header className="dashboard-card-header"><h2>重点关注</h2></header>{[['▥', '3家公司出现重要变化', '查看公司'], ['⚖', '2条强反证', '查看证据'], ['⌁', '1个关键指标触及阈值', '查看指标']].map(([icon, label, action], index) => <div className={`attention-row attention-${index}`} key={label}><i>{icon}</i><strong>{label}</strong><button>{action}</button></div>)}</section><section className="dashboard-card todo-card"><header className="dashboard-card-header"><h2>今日待办</h2><NavLink to="/reviews">更多 ›</NavLink></header>{[['高优先级', '比亚迪：业绩预告超预期，更新盈利预测', '今天 11:30', '去复核'], ['高优先级', '中芯国际：产能利用率提升，验证持续性', '今天 14:00', '去复核'], ['中优先级', '恒瑞医药：III期临床进展影响评估', '今天 16:00', '去复核'], ['中优先级', '新能源汽车行业：价格战跟踪与影响评估', '明天 09:30', '去处理'], ['低优先级', '宏观：4月经济数据解读', '明天 10:30', '去阅读']].map(([level, title, due, action]) => <article className="todo-row" key={title}><span className={`todo-level level-${level[0]}`}>{level}</span><strong>{title}</strong><small>截至时间：{due}</small><button>{action}</button></article>)}</section><section className="dashboard-card risk-panel"><header className="dashboard-card-header"><h2>强反证与风险</h2><NavLink to="/radar">更多 ›</NavLink></header>{[['高风险', '新能源汽车价格战加剧', '多地出台促销政策，终端折扣扩大'], ['高风险', '中芯国际先进制程扩产不及预期', '海外设备限制与良率爬坡影响产能释放'], ['中风险', '恒瑞医药创新药研发不及预期', '核心管线临床失败或竞争加剧带来不确定性'], ['中风险', '全球宏观需求走弱', '海外经济放缓可能影响出口与企业盈利']].map(([level, title, note]) => <article className="risk-row" key={title}><i>!</i><div><strong>{title}</strong><p>{note}</p></div><span>{level}</span></article>)}<NavLink className="dashboard-more" to="/radar">查看全部风险 ›</NavLink></section></aside>
  </div>
}

function ThemeImpactLines({ item }: { item: EvidenceFeedItem }) {
  const impacts = item.themeImpacts.length ? item.themeImpacts : [{
    hypothesisId: item.hypothesisId,
    hypothesisStatement: item.hypothesisStatement,
    direction: item.direction,
    evidenceCount: item.atomicEvidenceCount,
    hasConflictingEvidence: false,
  }]
  return <div className="theme-impact-lines">{impacts.slice(0, 3).map((impact) => <span key={impact.hypothesisId} className={impact.hasConflictingEvidence ? 'mixed' : impact.direction}><b>{impact.hasConflictingEvidence ? '分歧' : updateDirectionLabel(impact.direction)}</b><i>→</i>{impact.hypothesisStatement}<em>{impact.evidenceCount} 条证据</em></span>)}{impacts.length > 3 && <small>另有 {impacts.length - 3} 条假设影响</small>}</div>
}

export function WorkbenchPage({ onCreate, retrospectiveEnabled = false, quantEnabled = false }: { onCreate?: () => void; retrospectiveEnabled?: boolean; quantEnabled?: boolean } = {}) {
  const [expandedIndustries, setExpandedIndustries] = useState<Set<string>>(new Set())
  const currentBusinessDay = new Date().toLocaleDateString('en-CA')
  // 左侧覆盖导航沿用 Phase 2：以覆盖板块/公司为全集，不要求公司已经建立投资逻辑。
  const coverage = useQuery({ queryKey: ['maintained-coverage'], queryFn: getMaintainedCoverage, staleTime: 30_000 })
  // 当前覆盖的九家公司以季度观察逻辑入库（thesis_kind=observation）。
  // 状态雷达需要完整假设明细；覆盖侧栏继续使用轻量目录，避免明细加载阻塞整页。
  const theses = useQuery({ queryKey: ['theses', 'current-coverage'], queryFn: () => listTheses(undefined, false, true) })
  // 自动采集和模型归并在页面打开后仍可能完成；保持轻量轮询，让新主题无需
  // 研究员手动刷新页面才出现。
  const updates = useQuery({ queryKey: ['research-updates', 'today'], queryFn: () => getResearchUpdates({ todayOnly: true }), refetchInterval: 20_000 })
  const collection = useQuery({ queryKey: ['investoday-collection-status'], queryFn: getInvestodayCollectionStatus, refetchInterval: 15_000 })
  const assets = useQuery({ queryKey: ['data-center', 'overview'], queryFn: getDataCenterOverview, staleTime: 30_000 })
  const retrospective = useQuery({
    queryKey: ['retrospectives', 'overview'],
    queryFn: getRetrospectiveOverview,
    enabled: retrospectiveEnabled,
    staleTime: 30_000,
  })
  const jobs = useQuery({ queryKey: ['processing-jobs', 'workbench'], queryFn: listProcessingJobs, refetchInterval: 15_000 })
  const dailyUpdates = useQuery({ queryKey: ['research-updates', 'business-day', currentBusinessDay], queryFn: () => getResearchUpdates({ businessDay: currentBusinessDay }), refetchInterval: 20_000 })
  const current = (theses.data ?? []).filter((item) => item.securityId !== '300274')
  const toggle = (industry: string) => setExpandedIndustries((before) => {
    const next = before.size ? new Set(before) : new Set((coverage.data ?? []).map((item) => item.name))
    if (next.has(industry)) next.delete(industry); else next.add(industry)
    return next
  })
  const todayThemeItems = (updates.data?.items ?? []).filter((item) => item.securityId !== '300274')
  const dailyThemeItems = (dailyUpdates.data?.items ?? []).filter((item) => item.securityId !== '300274')
  const themesByCompany = new Map<string, EvidenceFeedItem[]>()
  for (const item of todayThemeItems) themesByCompany.set(item.securityId, [...(themesByCompany.get(item.securityId) ?? []), item])
  const dailyThemesByCompany = new Map<string, EvidenceFeedItem[]>()
  for (const item of dailyThemeItems) dailyThemesByCompany.set(item.securityId, [...(dailyThemesByCompany.get(item.securityId) ?? []), item])
  const companyThemeBundles = [...themesByCompany.values()].map((themes) => {
    const primary = themes[0]
    const hypothesisCount = new Set(themes.flatMap((item) => item.themeImpacts.length ? item.themeImpacts.map((impact) => impact.hypothesisStatement) : [item.hypothesisStatement, ...item.secondaryHypotheses])).size
    return {
      securityId: primary.securityId,
      securityName: primary.securityName,
      date: primary.ingestedAt,
      themes,
      sourceCount: themes.reduce((count, item) => count + item.sourceDocumentCount, 0),
      hypothesisCount,
      pending: themes.some((item) => item.confirmationStatus === 'pending'),
      supportThemes: themes.filter((item) => (item.themeDirection ?? item.direction) === 'support').length,
      conflictThemes: themes.filter((item) => (item.themeDirection ?? item.direction) === 'conflict').length,
      mixedThemes: themes.filter((item) => (item.themeDirection ?? item.direction) === 'mixed').length,
      divergentThemes: themes.filter((item) => item.themeDirection === 'divergent').length,
    }
  }).sort((left, right) => right.date.localeCompare(left.date))
  const compactDate = (value: string) => {
    const match = formatDate(value).match(/^\d{4}-(\d{2})-(\d{2})$/u)
    return match ? `${Number(match[1])}月${Number(match[2])}日` : formatDate(value)
  }
  const sameBusinessDay = (value?: string) => {
    if (!value) return false
    const parsed = new Date(value)
    return Number.isFinite(parsed.getTime()) && parsed.toLocaleDateString('en-CA') === currentBusinessDay
  }
  const todayProcessingJobs = (jobs.data ?? []).filter((job) => sameBusinessDay(job.createdAt) || sameBusinessDay(job.startedAt) || sameBusinessDay(job.finishedAt))
  const isStaleProcessingJob = (job: ProcessingJob) => {
    if (job.status !== 'running' || !job.startedAt) return false
    const startedAt = new Date(job.startedAt).getTime()
    return Number.isFinite(startedAt) && Date.now() - startedAt > 5 * 60 * 1000
  }
  const analysisStatus = todayProcessingJobs.length ? {
    total: todayProcessingJobs.length,
    waiting: todayProcessingJobs.filter((job) => ['queued', 'retrying'].includes(job.status)).length,
    running: todayProcessingJobs.filter((job) => job.status === 'running' && !isStaleProcessingJob(job)).length,
    stale: todayProcessingJobs.filter(isStaleProcessingJob).length,
    completed: todayProcessingJobs.filter((job) => job.status === 'succeeded').length,
    failed: todayProcessingJobs.filter((job) => ['failed', 'dead_letter'].includes(job.status)).length,
  } : undefined
  const collectionStatus = collectionStatusPresentation(collection.data, analysisStatus, todayThemeItems.length)
  const cumulativeAffectedCompanyCount = dailyThemesByCompany.size
  const pendingTodayCount = todayThemeItems.filter((item) => item.confirmationStatus === 'pending').length
  const confirmedTodayCount = Math.max(dailyThemeItems.length - pendingTodayCount, 0)
  const supportImpactCount = dailyThemeItems.filter((item) => (item.themeDirection ?? item.direction) === 'support').length
  const conflictImpactCount = dailyThemeItems.filter((item) => (item.themeDirection ?? item.direction) === 'conflict').length
  const divergentImpactCount = dailyThemeItems.filter((item) => ['mixed', 'divergent'].includes(item.themeDirection ?? item.direction)).length
  const rankDirection = (direction: EvidenceFeedItem['themeDirection']) => direction === 'conflict' ? 4 : direction === 'divergent' ? 3 : direction === 'mixed' ? 2 : direction === 'support' ? 1 : 0
  const actionItems = todayThemeItems
    .filter((item) => item.confirmationStatus === 'pending')
    .sort((left, right) => rankDirection(right.themeDirection ?? right.direction) - rankDirection(left.themeDirection ?? left.direction) || right.atomicEvidenceCount - left.atomicEvidenceCount)
    .slice(0, 4)
  const missingMetricTasks = current
    .flatMap((thesis) => thesis.hypotheses
      .filter((hypothesis) => hypothesis.importance === '核心' && hypothesis.mappings.length === 0)
      .map((hypothesis) => ({ thesis, hypothesis })))
    .slice(0, 4)
  const collectedToday = ((collection.data?.news.queuedToday ?? collection.data?.news.queued ?? 0) + (collection.data?.reports.queuedToday ?? collection.data?.reports.queued ?? 0))
  const skippedSeenToday = ((collection.data?.news.skippedSeen ?? 0) + (collection.data?.reports.skippedSeen ?? 0))
  const closureItems = [
    { label: '资料入库', value: collectedToday || skippedSeenToday || dailyThemeItems.reduce((total, item) => total + item.sourceDocumentCount, 0), note: collectedToday ? '今日新增资料进入分析' : '命中资料多为已处理内容', to: '/updates' },
    { label: 'AI 归并', value: dailyUpdates.data?.total ?? 0, note: '今日累计主逻辑变化卡', to: '/updates' },
    { label: '待研究员确认', value: pendingTodayCount, note: '需要核验方向和证据链', to: '/updates' },
    { label: '已沉淀证据', value: confirmedTodayCount, note: '可进入假设证据库', to: '/reviews' },
  ]
  const pipelineTone = collection.data?.overallStatus === 'failed' || collection.data?.overallStatus === 'unavailable' ? 'blocked' : collection.data?.overallStatus === 'running' ? 'running' : actionItems.length ? 'attention' : 'ready'
  const pipelineSummary = collection.data?.overallStatus === 'running'
    ? '今日影响雷达仍在刷新'
    : collection.data?.overallStatus === 'failed'
      ? '今日采集未完成，需要补跑'
      : dailyThemeItems.length
        ? `今日累计归并 ${cumulativeAffectedCompanyCount} 家公司的 ${dailyUpdates.data?.total ?? 0} 张影响卡`
        : '今日暂未形成新的主逻辑影响'
  const failedProcessingCount = (analysisStatus?.failed ?? 0) + (analysisStatus?.stale ?? 0)
  const radarAttentionItems = [
    { label: '冲突影响', value: conflictImpactCount, note: '优先核验是否承压', tone: 'conflict' },
    { label: '分歧影响', value: divergentImpactCount, note: '确认哪条证据链更强', tone: 'mixed' },
    { label: '失败资料', value: failedProcessingCount, note: '需要重跑或排除', tone: 'failed' },
  ]
  const pipelineNextAction = collection.data?.overallStatus === 'failed'
    ? '建议先查看采集状态并立即补跑，原有资料不会丢失。'
    : actionItems.length
      ? `优先查看 ${actionItems[0].securityName}，它的影响证据数量和优先级最高。`
      : missingMetricTasks.length
        ? '今日暂无紧急复核，建议补齐缺少监控指标的核心假设。'
        : '当前无需手动操作，等待下一轮自动补采与盘后研报入库。'
  const now = new Date()
  const nowMinutes = now.getHours() * 60 + now.getMinutes()
  const roundState = (hour: number, minute: number, enabled: boolean, status?: InvestodayCollectionStatus['overallStatus']) => {
    const target = hour * 60 + minute
    if (!enabled) return '未启用'
    if (status === 'failed' && nowMinutes >= target) return '异常'
    if (status === 'running' && Math.abs(nowMinutes - target) <= 45) return '进行中'
    return nowMinutes >= target ? '已跑' : '待执行'
  }
  const collectionRounds = [
    { label: '早盘新闻', time: '07:05', state: roundState(7, 5, collection.data?.news.status !== 'disabled', collection.data?.overallStatus) },
    { label: '开盘跟踪', time: '09:05', state: roundState(9, 5, collection.data?.news.status !== 'disabled', collection.data?.overallStatus) },
    { label: '午间补采', time: '12:05', state: roundState(12, 5, collection.data?.news.status !== 'disabled', collection.data?.overallStatus) },
    { label: '尾盘跟踪', time: '15:05', state: roundState(15, 5, collection.data?.news.status !== 'disabled', collection.data?.overallStatus) },
    { label: '盘后新闻', time: '18:05', state: roundState(18, 5, collection.data?.news.status !== 'disabled', collection.data?.overallStatus) },
    { label: '早间研报', time: '07:20', state: roundState(7, 20, collection.data?.reports.status !== 'disabled', collection.data?.overallStatus) },
    { label: '盘后研报', time: '18:20', state: roundState(18, 20, collection.data?.reports.status !== 'disabled', collection.data?.overallStatus) },
    { label: '夜间补齐', time: '20:30', state: roundState(20, 30, collection.data?.reports.status !== 'disabled', collection.data?.overallStatus) },
  ]
  const radarSuggestions = [
    collection.data?.overallStatus === 'failed' ? '采集异常，先进入采集状态页补跑。' : '',
    divergentImpactCount > 0 ? `${divergentImpactCount} 张影响卡存在分歧，建议优先复核证据方向。` : '',
    conflictImpactCount > 0 ? `${conflictImpactCount} 张影响卡为冲突方向，建议检查是否触发假设承压。` : '',
    pendingTodayCount > 0 ? `${pendingTodayCount} 张影响卡待确认，优先处理分歧、冲突和高关注资讯。` : '',
    !pendingTodayCount && !conflictImpactCount && !divergentImpactCount && supportImpactCount > 0 ? '今日影响以支持为主，可将已确认内容沉淀到对应假设证据库。' : '',
    !(dailyUpdates.data?.total ?? 0) ? '当前暂无影响卡，等待下一轮自动采集和 AI 归并。' : '',
  ].filter(Boolean)
  const marketBriefs = [...dailyThemeItems]
    .sort((left, right) => (right.priority === 'high' ? 2 : right.priority === 'medium' ? 1 : 0) - (left.priority === 'high' ? 2 : left.priority === 'medium' ? 1 : 0) || right.atomicEvidenceCount - left.atomicEvidenceCount || right.sourceDocumentCount - left.sourceDocumentCount)
    .slice(0, 5)

  return <div className="dashboard-page">
    <aside className="coverage-panel" aria-label="我的覆盖">
      <div className="dashboard-panel-title"><h1>我的覆盖</h1><NavLink to="/coverage" aria-label="管理覆盖范围">⚙</NavLink></div>
      {coverage.isLoading && <div className="coverage-loading" role="status">正在加载维护中的公司…</div>}
      {coverage.error && <div className="coverage-loading coverage-loading-error">覆盖数据暂时不可用</div>}
      {coverage.data?.map((industry) => {
        const expanded = expandedIndustries.size === 0 || expandedIndustries.has(industry.name)
        return <section className="coverage-group" key={industry.name}><button className="coverage-industry" aria-expanded={expanded} onClick={() => toggle(industry.name)}><span>{expanded ? '⌄' : '›'} ▥ {industry.name}</span><b>{industry.companies.length}</b></button>{expanded && <div className="coverage-companies">{industry.companies.map((company) => <NavLink to={`/companies/${encodeURIComponent(company.securityId)}`} key={company.securityId}><span><strong>▥ {company.name}</strong><small>{company.industry || '行业分类待补充'}</small></span></NavLink>)}</div>}</section>
      })}
      {coverage.data && coverage.data.length === 0 && <div className="coverage-loading">暂无正在维护的公司</div>}
      <nav className="coverage-links" aria-label="研究功能"><NavLink to="/coverage">⌁ 行业与公司管理</NavLink><NavLink to="/macro-strategy">▧ 宏观与策略</NavLink><NavLink to="/assets?from=workbench">▤ 数据中心</NavLink><NavLink to="/theses">◇ 投资逻辑</NavLink>{quantEnabled && <NavLink to="/quant">▦ 模型与因子</NavLink>}<NavLink to="/updates">♧ 最新动态</NavLink>{retrospectiveEnabled && <NavLink to="/retrospective">↺ 复盘中心</NavLink>}</nav>
      <button className="new-research-button" onClick={onCreate}>＋ 新建研究主题</button>
    </aside>
    <main className="dashboard-main">
      <section className="dashboard-card research-feed company-theme-feed" aria-labelledby="research-feed-title">
        <header className="dashboard-card-header"><div><h2 id="research-feed-title">今日公司变化</h2><span>AI 已将当日资料映射到核心假设，并按主投资逻辑汇总</span></div><NavLink to="/updates">全部逻辑变化 ›</NavLink></header>
        <div className={`dashboard-collection-state ${collectionStatus.tone}`}><i /><div><strong>{collectionStatus.title}</strong><small>{collectionStatus.detail}</small></div><NavLink to="/assets/runs?from=workbench">查看数据运行 ›</NavLink></div>
        <div className="company-theme-bundles">{companyThemeBundles.slice(0, 4).map((bundle) => <article className="company-theme-bundle" key={bundle.securityId}>
          <header><div><div className="company-theme-company"><strong>{bundle.securityName}</strong><time>今日 · {compactDate(bundle.date)}</time></div><span><NavLink className="company-theme-source-link" to={`/assets/documents?security_id=${encodeURIComponent(bundle.securityId)}&sort=ingested_at&from=workbench`}>今日 {bundle.sourceCount} 份资料 ↗</NavLink> · 1 条主投资逻辑变化 · 涉及 {bundle.hypothesisCount} 项核心假设</span></div>{bundle.pending && <b className="ai-label">待确认</b>}</header>
          <div className="company-theme-list">{bundle.themes.map((item) => {
            const themeDirection = item.themeDirection ?? item.direction
            const impactHref = `/logic-changes/${encodeURIComponent(item.securityId)}/${encodeURIComponent(item.thesisId)}?business_day=${encodeURIComponent(item.ingestedAt.slice(0, 10))}`
            const sourceHref = item.sourceDocumentId ? `/assets/documents/${encodeURIComponent(item.sourceDocumentId)}?from=workbench` : `/assets/documents?security_id=${encodeURIComponent(item.securityId)}&from=workbench`
            return <section className="company-theme-row logic-change-row" key={item.thesisId}><i className={themeDirection === 'conflict' ? 'conflict' : themeDirection === 'mixed' ? 'mixed' : ''} /><div><div className="company-theme-meta"><span>主投资逻辑变化</span><strong className={themeDirection}>{updateThemeDirectionLabel(themeDirection)}</strong></div><h3>{item.thesisCoreView}</h3><p className="logic-change-summary">{item.aggregationSummary}</p><ThemeImpactLines item={item} /></div><div className="company-theme-actions"><NavLink to={`/theses/${encodeURIComponent(item.thesisId)}`}>查看逻辑</NavLink><NavLink to={impactHref}>查看影响</NavLink><NavLink className="source-action" to={sourceHref}>源资料</NavLink></div></section>
          })}</div>
        </article>)}{!companyThemeBundles.length && <div className="updates-empty">今日尚未形成可展示的主投资逻辑变化。资料可能仍在分析，或尚未触发任何现行假设；可查看数据运行了解详情。</div>}</div>
        <NavLink className="dashboard-more" to="/updates">查看全部公司变化 ⌄</NavLink>
      </section>
      <section className="dashboard-card market-brief-card market-brief-main"><header className="dashboard-card-header"><div><h2>最新资讯精选</h2><span>按优先级、证据数量和来源覆盖筛选，放在公司变化下方供快速扫读</span></div><NavLink to="/updates">全部资讯 ›</NavLink></header>{marketBriefs.map((item) => { const themeDirection = item.themeDirection ?? item.direction; const impactHref = `/logic-changes/${encodeURIComponent(item.securityId)}/${encodeURIComponent(item.thesisId)}?business_day=${encodeURIComponent(item.ingestedAt.slice(0, 10))}`; return <NavLink className={`market-brief-row ${themeDirection}`} to={impactHref} key={item.relationId}><div><span>{item.securityName}</span><b>{updatePriorityLabel(item.priority)}关注</b></div><strong>{item.sourceDocumentTitle}</strong><p>{item.factExcerpt || item.aggregationSummary || item.thesisCoreView}</p><footer><small>{item.sourceDocumentCount} 份来源 · {item.atomicEvidenceCount} 条事实</small><em>{updateThemeDirectionLabel(themeDirection)}</em></footer></NavLink> })}{!marketBriefs.length && <div className="side-empty">今日暂无可精选资讯；采集完成后会按关注度自动进入这里。</div>}</section>
    </main>
    <aside className="dashboard-right">
      <section className={`dashboard-card work-radar-card ${pipelineTone}`}><header className="dashboard-card-header"><div><h2>工作雷达监控</h2><span>{collectionStatus.title}</span></div><NavLink to="/updates">详情 ›</NavLink></header><div className="radar-scroll"><div className="radar-hero"><span>当前状态</span><strong>{pipelineSummary}</strong><p>优先看是否有待确认、冲突分歧或失败资料；底部再看今日处理闭环。</p></div><section className="radar-section"><header><span>今日采集轮次</span><small>自动刷新</small></header><div className="radar-rounds">{collectionRounds.map((round) => <article className={`radar-round state-${round.state}`} key={`${round.label}-${round.time}`}><time>{round.time}</time><span>{round.label}</span><b>{round.state}</b></article>)}</div></section><section className="radar-section"><header><span>需要关注</span><small>只保留行动信号</small></header><div className="radar-attention-grid">{radarAttentionItems.map((item) => <article className={`radar-attention-item ${item.tone}`} key={item.label}><span>{item.label}</span><strong>{item.value}</strong><small>{item.note}</small></article>)}</div></section><div className="radar-next"><span>下一步建议</span>{radarSuggestions.map((suggestion) => <p key={suggestion}>{suggestion}</p>)}{!radarSuggestions.length && <p>{pipelineNextAction}</p>}</div><section className="work-radar-closure" aria-labelledby="closure-title"><header><div><h3 id="closure-title">今日研究闭环</h3><span>从资料进入到研究员确认</span></div><div><NavLink to="/status-simulator">状态沙盘 ›</NavLink><NavLink to="/reviews">研究记录 ›</NavLink></div></header><div className="closure-grid">{closureItems.map((item) => <NavLink className="closure-step" to={item.to} key={item.label}><span>{item.label}</span><strong>{item.value}</strong><p>{item.note}</p></NavLink>)}</div></section></div></section>
      <section className="dashboard-card data-asset-card" aria-labelledby="data-asset-card-title"><header className="dashboard-card-header"><div><h2 id="data-asset-card-title">数据资产</h2><span>工作台使用的资料均可回查</span></div><NavLink to="/assets?from=workbench">进入数据中心 ›</NavLink></header>{assets.data ? <div className="data-asset-summary"><NavLink to="/assets/documents?from=workbench"><strong>{assets.data.documents.toLocaleString()}</strong><span>可见资料</span></NavLink><NavLink to="/assets/documents?content_status=完整正文&from=workbench"><strong>{assets.data.fullTextDocuments.toLocaleString()}</strong><span>完整正文</span></NavLink><NavLink className={assets.data.recentFailedRuns ? 'has-risk' : ''} to="/assets/runs?status=failed&from=workbench"><strong>{assets.data.recentFailedRuns.toLocaleString()}</strong><span>失败运行</span></NavLink></div> : <p className="data-asset-loading">{assets.error ? '数据资产摘要暂不可用，可进入数据中心查看。' : '正在读取数据资产摘要…'}</p>}</section>
      {retrospectiveEnabled && <section className="dashboard-card workbench-retrospective-card" aria-labelledby="workbench-retrospective-title"><header className="dashboard-card-header"><h2 id="workbench-retrospective-title">{retrospective.isLoading ? '复盘进度加载中' : '复盘进度'}</h2><NavLink to="/retrospective">进入中心 ›</NavLink></header>{retrospective.isLoading && <p className="muted">正在汇总复盘进度…</p>}{retrospective.error && <div className="workbench-card-error"><strong>复盘进度暂不可用</strong><NavLink to="/retrospective">打开复盘中心</NavLink></div>}{retrospective.data && <><div className="workbench-retrospective-summary"><strong>{retrospective.data.pending_reports}</strong><span>份待完成复盘</span><em>{Math.round(retrospective.data.average_completeness * 100)}% 平均完整度</em></div><div className="workbench-retrospective-states"><NavLink to="/retrospective?state=草稿"><span>草稿</span><strong>{retrospective.data.state_counts['草稿'] ?? 0}</strong></NavLink><NavLink to="/retrospective?state=待评审"><span>待评审</span><strong>{retrospective.data.state_counts['待评审'] ?? 0}</strong></NavLink><NavLink to="/retrospective?state=已发布"><span>已发布</span><strong>{retrospective.data.state_counts['已发布'] ?? 0}</strong></NavLink></div><NavLink className="workbench-retrospective-action" to={current[0] ? `/retrospective/new?thesisId=${encodeURIComponent(current[0].thesisId)}` : '/retrospective/new'}>发起复盘</NavLink></>}</section>}
    </aside>
  </div>
}

const researchUpdates = [
  { id:'1', time:'今天 09:42', company:'比亚迪', source:'公司公告', type:'公司', title:'2024年一季度业绩预告：归母净利润同比增长 86.04%–118.88%', thesis:'销量增长驱动盈利提升', hypothesis:'H1 规模效应持续改善毛利率', metric:'归母净利润', direction:'支持', importance:'高', status:'待确认', confidence:92 },
  { id:'2', time:'今天 09:15', company:'中芯国际', source:'行业资讯 · 芯思想', type:'行业', title:'Q1产能利用率提升至92.1%，价格年内趋稳', thesis:'成熟制程需求回暖', hypothesis:'H2 产能利用率提升驱动盈利改善', metric:'产能利用率', direction:'支持', importance:'高', status:'待确认', confidence:87 },
  { id:'3', time:'今天 08:47', company:'恒瑞医药', source:'公司公告', type:'公司', title:'注射用SHR-A1811获批开展III期临床试验', thesis:'创新药管线持续兑现', hypothesis:'H1 核心管线按计划推进', metric:'临床阶段', direction:'支持', importance:'高', status:'待确认', confidence:95 },
  { id:'4', time:'今天 08:21', company:'小鹏汽车', source:'媒体报道 · 36氪', type:'公司', title:'小鹏汽车与大众汽车集团签署平台与软件战略技术合作框架协议', thesis:'平台化合作提升长期盈利弹性', hypothesis:'H3 技术输出形成新增收入', metric:'技术服务收入', direction:'支持', importance:'中', status:'待确认', confidence:81 },
  { id:'5', time:'今天 07:58', company:'吉利汽车', source:'行业数据 · 乘联会', type:'行业', title:'4月新能源乘用车批发销量同比+32.4%，环比-8.7%', thesis:'新能源产品周期', hypothesis:'H2 新能源销量增长并带动规模效应', metric:'新能源月度销量', direction:'冲突', importance:'高', status:'待确认', confidence:84 },
  { id:'6', time:'昨天 17:30', company:'中芯国际', source:'券商研报 · 中金公司', type:'研报', title:'成熟制程稼动率改善，长期资本开支持续受益国产替代', thesis:'国产替代与盈利改善', hypothesis:'H1 国产替代需求保持韧性', metric:'资本开支', direction:'支持', importance:'中', status:'已确认', confidence:79 },
  { id:'7', time:'昨天 15:10', company:'吉利汽车', source:'渠道调研', type:'调研', title:'部分重点车型终端折扣率环比扩大1.2个百分点', thesis:'新能源产品周期', hypothesis:'H2 销量增长并非依赖大幅降价', metric:'终端折扣率', direction:'冲突', importance:'高', status:'待确认', confidence:89 },
  { id:'8', time:'昨天 11:25', company:'创新医药行业', source:'国家药监局', type:'政策', title:'创新药临床试验审评审批机制进一步优化', thesis:'创新药行业配置', hypothesis:'政策环境支持研发兑现', metric:'审批周期', direction:'支持', importance:'中', status:'已确认', confidence:90 },
] as const

export function LegacyResearchUpdatesPage() {
  const [filter, setFilter] = useState('全部')
  const [query, setQuery] = useState('')
  const visible = researchUpdates.filter((item) => (filter === '全部' || filter === item.type || filter === item.status) && `${item.company}${item.title}${item.source}`.includes(query))
  return <div className="updates-page"><header className="updates-page-header"><div><NavLink to="/workbench">← 返回工作台</NavLink><span>RESEARCH UPDATE STREAM</span><h1>全部研究动态</h1><p>集中查看系统实时检索到的公告、新闻、研报和行业数据，以及它们与现有投资逻辑的候选影响关系。</p></div><div className="updates-summary"><article><strong>{researchUpdates.length}</strong><span>最新动态</span></article><article><strong>{researchUpdates.filter((item) => item.status === '待确认').length}</strong><span>待确认</span></article><article><strong>{researchUpdates.filter((item) => item.direction === '冲突').length}</strong><span>冲突影响</span></article></div></header><main className="updates-layout"><aside className="updates-filter-panel"><h2>动态范围</h2>{['全部','公司','行业','政策','研报','调研','待确认','已确认'].map((item) => <button key={item} className={filter === item ? 'active' : ''} onClick={() => setFilter(item)}><span>{item}</span><b>{item === '全部' ? researchUpdates.length : researchUpdates.filter((update) => update.type === item || update.status === item).length}</b></button>)}<div><span>检索处理状态</span><strong><i /> 实时运行中</strong><small>最近更新：刚刚</small></div></aside><section className="updates-list-panel"><header><label><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索公司、事件或信息来源" /></label><button>时间范围：近7天⌄</button><button>重要性⌄</button></header><div className="updates-list-head"><span>时间</span><span>最新动态与候选影响</span><span>重要性</span><span>方向</span><span>状态</span><span>操作</span></div>{visible.map((item) => <article className="update-list-row" key={item.id}><time>{item.time}</time><div><div><strong>{item.company}</strong><span>{item.source}</span></div><h2>{item.title}</h2><p>候选关联：{item.thesis} / {item.hypothesis}</p></div><b className={`update-priority priority-${item.importance}`}>{item.importance}</b><em className={item.direction === '冲突' ? 'conflict' : 'support'}>{item.direction}</em><span className={`update-status status-${item.status}`}>{item.status}</span><NavLink to={`/updates/${item.id}`}>查看影响 →</NavLink></article>)}{!visible.length && <div className="updates-empty">没有符合当前条件的动态</div>}<footer><span>共 {visible.length} 条动态</span><div><button disabled>‹</button><b>1</b><button disabled>›</button></div></footer></section></main></div>
}

export function LegacyResearchImpactDetailPage() {
  const { updateId = '1' } = useParams()
  const item = researchUpdates.find((update) => update.id === updateId) ?? researchUpdates[0]
  const [decision, setDecision] = useState('')
  return <div className="impact-page"><header className="impact-page-header"><div><NavLink to="/updates">← 返回全部动态</NavLink><span>IMPACT REVIEW / {item.id.padStart(4,'0')}</span><h1>具体影响分析</h1></div><div><span className={`update-status status-${item.status}`}>{item.status}</span><small>AI关系置信度</small><strong>{item.confidence}%</strong></div></header><main className="impact-page-layout"><div className="impact-main-column"><section className="impact-fact-card"><header><div><span>01 / 原始事实</span><h2>{item.title}</h2></div><button>打开原文 ↗</button></header><p>系统从公开来源中识别出该事件。下面展示的是原始信息及可追溯定位，AI候选关系不会在研究员确认前修改任何投资逻辑。</p><dl><div><dt>公司／行业</dt><dd>{item.company}</dd></div><div><dt>来源</dt><dd>{item.source}</dd></div><div><dt>发布时间</dt><dd>{item.time}</dd></div><div><dt>信息类型</dt><dd>{item.type}</dd></div></dl><blockquote>“{item.title}”。该信息已完成来源、发布时间和研究对象识别，等待研究员判断其研究影响。</blockquote><footer>来源定位：公开信息正文第1段 <button>查看上下文</button></footer></section><section className="impact-relation-card"><header><div><span>02 / AI候选关系</span><h2>事件如何影响现有投资逻辑</h2></div><button>✎ 编辑路径</button></header><div className="impact-relation-flow"><article><span>事件事实</span><strong>{item.title}</strong></article><i>→</i><article><span>验证指标</span><strong>{item.metric}</strong><small>识别到指标变化</small></article><i>→</i><article><span>核心假设</span><strong>{item.hypothesis}</strong></article><i>→</i><article><span>投资逻辑</span><strong>{item.thesis}</strong><small>{item.company}</small></article></div><div className="impact-assessment-grid"><article><span>影响方向</span><strong className={item.direction === '冲突' ? 'conflict' : 'support'}>{item.direction}</strong></article><article><span>影响强度</span><strong>{item.importance}</strong></article><article><span>关系置信度</span><strong>{item.confidence}%</strong></article><article><span>逻辑状态建议</span><strong>{item.direction === '冲突' ? '逻辑承压' : '证据增强'}</strong></article></div><div className="impact-reason"><strong>AI判断理由</strong><p>该事件直接涉及“{item.metric}”，能够用于验证“{item.hypothesis}”，因此建议作为{item.direction}证据关联到“{item.thesis}”。</p></div></section></div><aside className="impact-review-panel"><section><span>03 / 研究员确认</span><h2>这条影响是否成立？</h2><p>确认后，系统才会将信息加入证据、刷新假设状态并生成复盘记录。</p><label>关联投资逻辑<select defaultValue={item.thesis}><option>{item.thesis}</option><option>选择其他逻辑</option></select></label><label>影响方向<select defaultValue={item.direction}><option>支持</option><option>冲突</option><option>中性</option></select></label><label>影响强度<select defaultValue={item.importance}><option>高</option><option>中</option><option>低</option></select></label><label>研究员备注<textarea placeholder="填写判断依据或修改原因" /></label><div className="impact-review-actions"><button onClick={() => setDecision('暂不判断')}>暂不判断</button><button onClick={() => setDecision('已驳回')}>驳回</button><button onClick={() => setDecision('已确认')} className="primary">确认影响</button></div>{decision && <div className="impact-decision-result" role="status"><strong>✓ {decision}</strong><span>已生成研究处理记录；当前为静态演示。</span></div>}</section><section className="impact-after-confirm"><h2>确认后将发生</h2><ol><li><b>1</b><span>证据写入对应核心假设</span></li><li><b>2</b><span>指标和逻辑状态重新计算</span></li><li><b>3</b><span>自动生成研究变更记录</span></li><li><b>4</b><span>进入后续复盘时间线</span></li></ol></section></aside></main></div>
}

function updateStatusLabel(status: EvidenceFeedItem['confirmationStatus']) {
  return status === 'confirmed' ? '已确认' : status === 'rejected' ? '已驳回' : status === 'deactivated' ? '已解除' : '待确认'
}

function updateDirectionLabel(direction: EvidenceFeedItem['direction']) {
  return direction === 'support' ? '支持' : direction === 'conflict' ? '冲突' : '中性'
}

function updateThemeDirectionLabel(direction: EvidenceFeedItem['themeDirection']) {
  return direction === 'divergent' ? '证据分歧' : direction === 'mixed' ? '混合影响' : direction === 'neutral' ? '待判断' : updateDirectionLabel(direction ?? 'neutral')
}

function updatePriorityLabel(priority: EvidenceFeedItem['priority']) {
  return priority === 'high' ? '高' : priority === 'medium' ? '中' : '低'
}

function collectionStatusPresentation(
  status?: InvestodayCollectionStatus,
  analysis?: { total: number; waiting: number; running: number; stale: number; completed: number; failed: number },
  impactCount = 0,
) {
  if (!status) return { tone: 'pending', title: '正在读取今日自动采集状态', detail: '工作台会持续检查新闻与研报是否已进入分析队列。' }
  if (status.news.status === 'disabled' && status.reports.status === 'disabled') return { tone: 'pending', title: '今日自动采集尚未启用', detail: '请配置资讯源后，系统将在工作日自动执行。' }
  if (status.overallStatus === 'completed') {
    const queued = (status.news.queuedToday ?? status.news.queued ?? 0) + (status.reports.queuedToday ?? status.reports.queued ?? 0)
    const previouslyProcessed = (status.news.skippedSeen ?? 0) + (status.reports.skippedSeen ?? 0)
    if (analysis?.total) {
      const active = analysis.waiting + analysis.running
      if (analysis.stale > 0) return {
        tone: 'failed',
        title: `${analysis.stale} 份资料疑似卡住，等待自动恢复或重跑`,
        detail: `今日已完成 ${analysis.completed} 份；排队 ${analysis.waiting} 份 · 正常分析中 ${analysis.running} 份 · 已失败 ${analysis.failed} 份。`,
      }
      if (active > 0) return {
        tone: 'running',
        title: `今日已入库 ${analysis.total} 份资料，${active} 份仍在处理`,
        detail: `排队 ${analysis.waiting} 份 · 分析中 ${analysis.running} 份 · 已完成 ${analysis.completed} 份 · 失败 ${analysis.failed} 份。`,
      }
      if (analysis.failed > 0 && analysis.completed === 0) return {
        tone: 'failed',
        title: `今日 ${analysis.failed} 份资料分析失败，未形成影响卡`,
        detail: '请进入采集状态或死信任务页查看失败原因，补跑后可继续归并到主投资逻辑。',
      }
      if (impactCount > 0) return {
        tone: 'ready',
        title: `今日已完成分析，形成 ${impactCount} 张主逻辑影响卡`,
        detail: `已完成 ${analysis.completed} 份资料分析${analysis.failed ? `，另有 ${analysis.failed} 份失败待处理` : ''}；影响卡会继续等待研究员确认。`,
      }
      return {
        tone: analysis.failed ? 'failed' : 'ready',
        title: `今日 ${analysis.completed} 份资料已完成 AI 分析，暂未形成新的影响卡`,
        detail: analysis.failed
          ? `另有 ${analysis.failed} 份失败待处理；已完成资料可能被判定为重复、背景信息或未命中现行假设。`
          : '已完成资料可能被判定为重复、背景信息或未命中现行假设，因此不会强行生成影响卡。',
      }
    }
    return queued > 0
      ? { tone: 'ready', title: `今日已采集 ${queued} 份资料，等待处理状态回传`, detail: '采集计数只代表资料入库，不等于仍在分析；任务状态回传后会显示排队、完成或失败。' }
      : previouslyProcessed > 0
        ? { tone: 'ready', title: '今日已完成检索，覆盖资料已在此前入库或分析', detail: '本轮查询仅命中已处理的资料，因此没有重复入库；后续盘中与盘后会继续补采集。' }
        : { tone: 'ready', title: '今日已完成检索，暂未发现新的覆盖资料', detail: '系统已按覆盖公司查询新闻和研报；后续盘中与盘后会继续补采集。' }
  }
  if (status.overallStatus === 'running') return { tone: 'running', title: '正在自动采集今日新闻与研报', detail: '资料入库后会自动解析、关联假设并生成影响候选。' }
  if (status.overallStatus === 'failed') return { tone: 'failed', title: '今日自动采集未完成', detail: '可点击“立即补跑”重新发起采集；原有资料不会丢失。' }
  if (status.overallStatus === 'unavailable' || !status.workerReady) return { tone: 'failed', title: '自动采集任务暂不可用', detail: 'Worker 或队列未就绪，恢复后会在启动时自动补跑。' }
  return { tone: 'pending', title: '今日采集尚未开始', detail: '系统会在工作日 07:05 自动预采集；也可立即补跑。' }
}

/** 全部动态：真实证据流，不再依赖页面内置案例。 */
export function ResearchUpdatesPage() {
  const [params] = useSearchParams()
  const [filter, setFilter] = useState('全部')
  const [query, setQuery] = useState('')
  const [showHistory, setShowHistory] = useState(false)
  const [syncMessage, setSyncMessage] = useState('')
  const [syncRefreshUntil, setSyncRefreshUntil] = useState(0)
  const qc = useQueryClient()
  const collection = useQuery({
    queryKey: ['investoday-collection-status'],
    queryFn: getInvestodayCollectionStatus,
    refetchInterval: 15_000,
  })
  const requestedBusinessDay = params.get('business_day')
  const businessDay = requestedBusinessDay && /^\d{4}-\d{2}-\d{2}$/.test(requestedBusinessDay) ? requestedBusinessDay : undefined
  const filters = { ...(filter === '待确认' ? { status: 'pending' } : filter === '已确认' ? { status: 'confirmed' } : filter === '支持' ? { direction: 'support' } : filter === '冲突' ? { direction: 'conflict' } : filter === '高重要性' ? { priority: 'high' } : {}), ...(businessDay ? { businessDay } : showHistory ? {} : { todayOnly: true }) }
  const updates = useQuery({
    queryKey: ['research-updates', filters],
    queryFn: () => getResearchUpdates(filters),
    refetchInterval: syncRefreshUntil > Date.now() ? 10_000 : false,
  })
  const sync = useMutation({
    mutationFn: syncTodayResearch,
    onSuccess: () => {
      setSyncMessage('已启动采集，系统将在最多 3 分钟内每 10 秒自动刷新主题影响。')
      setSyncRefreshUntil(Date.now() + 180_000)
      void qc.invalidateQueries({ queryKey: ['research-updates'] })
      void qc.invalidateQueries({ queryKey: ['investoday-collection-status'] })
      window.setTimeout(() => setSyncRefreshUntil(0), 180_000)
    },
  })
  if (updates.isLoading) return <LoadingState text="正在读取研究动态…" />
  if (updates.error || !updates.data) return <ErrorState error={updates.error} />
  const items = updates.data.items.filter((item) => `${item.securityName}${item.sourceDocumentTitle}${item.factExcerpt}${item.thesisTitle}${item.hypothesisStatement}`.includes(query.trim()))
  const all = updates.data.items
  const options = ['全部', '待确认', '已确认', '支持', '冲突', '高重要性']
  const collectionStatus = collectionStatusPresentation(collection.data)
  return <div className="updates-page"><header className="updates-page-header"><div><NavLink to="/workbench">← 返回工作台</NavLink><span>RESEARCH UPDATE STREAM</span><h1>全部研究动态</h1><p>默认展示本业务日新入库资料形成的主题影响；历史模式仅用于回溯。</p><div className={`collection-run-status ${collectionStatus.tone}`}><i /><div><strong>{collectionStatus.title}</strong><small>{collectionStatus.detail}</small></div></div><div className="updates-sync-actions"><button className="primary" onClick={() => sync.mutate()} disabled={sync.isPending}>{sync.isPending ? '正在启动采集…' : '立即补跑'}</button><button onClick={() => void updates.refetch()} disabled={updates.isFetching}>刷新动态</button><button onClick={() => setShowHistory((value) => !value)}>{showHistory ? '切回今日动态' : '查看全部历史'}</button></div>{syncMessage && <p className="muted" role="status">{syncMessage}</p>}<InlineError error={sync.error ?? collection.error} /></div><div className="updates-summary"><article><strong>{updates.data.total}</strong><span>{showHistory ? '历史主题' : '今日主题'}</span></article><article><strong>{all.filter((item) => item.confirmationStatus === 'pending').length}</strong><span>待确认</span></article><article><strong>{all.filter((item) => item.direction === 'conflict').length}</strong><span>冲突影响</span></article></div></header><main className="updates-layout"><aside className="updates-filter-panel"><h2>动态范围</h2>{options.map((option) => <button key={option} className={filter === option ? 'active' : ''} onClick={() => setFilter(option)}><span>{option}</span><b>{option === '全部' ? updates.data.total : option === '待确认' ? all.filter((item) => item.confirmationStatus === 'pending').length : option === '已确认' ? all.filter((item) => item.confirmationStatus === 'confirmed').length : option === '支持' ? all.filter((item) => item.direction === 'support').length : option === '冲突' ? all.filter((item) => item.direction === 'conflict').length : all.filter((item) => item.priority === 'high').length}</b></button>)}<div><span>数据处理状态</span><strong><i /> 已同步证据库</strong><small>仅展示有权限访问的研究对象</small></div></aside><section className="updates-list-panel"><header><label><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索公司、事实、来源或投资逻辑" /></label><span className="muted">{showHistory ? '按优先级与披露时间排序' : '按入库时间排序；原始披露时间在卡片内保留'}</span></header><div className="updates-list-head"><span>{showHistory ? '披露时间' : '入库时间'}</span><span>最新动态与候选影响</span><span>重要性</span><span>方向</span><span>状态</span><span>操作</span></div>{items.map((item) => { const impactHref = `/logic-changes/${encodeURIComponent(item.securityId)}/${encodeURIComponent(item.thesisId)}?business_day=${encodeURIComponent(item.ingestedAt.slice(0, 10))}`; return <article className="update-list-row" key={item.relationId}><time>{formatDate(showHistory ? item.disclosedAt : item.ingestedAt)}</time><div><div><strong>{item.securityName}</strong><span>{item.sourceDocumentTitle}{!showHistory ? ` · 原始披露 ${formatDate(item.disclosedAt)}` : ''}</span></div><h2>{item.aggregationSummary ?? item.factExcerpt}</h2><p>主关联：{item.hypothesisStatement} · {item.sourceDocumentCount} 个来源 / {item.atomicEvidenceCount} 条证据</p></div><b className={`update-priority priority-${updatePriorityLabel(item.priority)}`}>{updatePriorityLabel(item.priority)}</b><em className={item.direction === 'conflict' ? 'conflict' : 'support'}>{updateDirectionLabel(item.direction)}</em><span className={`update-status status-${updateStatusLabel(item.confirmationStatus)}`}>{updateStatusLabel(item.confirmationStatus)}</span><NavLink to={impactHref}>查看主题 →</NavLink></article> })}{!items.length && <div className="updates-empty">没有符合当前条件的真实动态</div>}<footer><span>当前显示 {items.length} / {updates.data.total} 条</span></footer></section></main></div>
}

/** 影响详情：保留新界面布局，但全部字段、确认与审计均来自后端。 */
function readableEvidenceText(value: string) {
  return value
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/\*\*/g, '')
    .replace(/`/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

function evidenceHighlights(value: string) {
  const cleaned = readableEvidenceText(value)
  const lines = cleaned
    .split(/\n+|(?=\s+-\s+)/u)
    .map((line) => line.replace(/^\s*[-•]\s*/u, '').replace(/^(风险提示|关键点|摘要)\s*[:：]\s*/u, '').trim())
    .filter((line) => line.length > 0)
  return lines.length ? lines.slice(0, 3) : ['资料事实待补充']
}

function readableSourceTitle(value: string) {
  return value.replace(/^\s*标题\s*[:：]\s*/u, '').trim()
}

function readableSourceLocator(value?: string) {
  const paragraph = value?.match(/#paragraph-(\d+)$/u)?.[1]
  return paragraph ? `本条资料的第 ${paragraph} 段` : '本条资料已入库的原文段落'
}

function logicDirectionLabel(direction: LogicChangeDigestDetail['overallDirection']) {
  return direction === 'support' ? '支持' : direction === 'conflict' ? '冲突' : direction === 'mixed' ? '混合影响' : '待观察'
}

function impactDirectionClass(direction: string) {
  return direction === '支持' ? 'support' : direction === '冲突' ? 'conflict' : direction === '分歧' ? 'mixed' : 'neutral'
}

function impactPresentationGuide(presentation: LogicChangeDigestDetail['hypothesisImpacts'][number]['presentation']) {
  if (presentation === '双向分歧') return { title: '研究员应核验分歧来源', text: '支持与冲突路径同时存在；先判断哪条路径更接近实际经营，再决定是否调整假设。' }
  if (presentation === '背景信号') return { title: '作为背景观察，不直接改写经营判断', text: '该信号反映市场、行业、政策或宏观环境；除非补充公司层面的传导证据，否则仅保留为观察。' }
  if (presentation === '证据不足') return { title: '暂不建立经营传导', text: '资料与假设之间尚缺少可验证的中间环节；优先补充订单、价格、产能或财务等直接证据。' }
  return { title: '沿此路径核验候选影响', text: '资料已形成一条候选传导，但仍需以原文和后续可观察指标确认是否成立。' }
}

function pathEffectCopy(direction: string, statement: string, effect?: string) {
  const action = direction === '支持' ? '可能强化' : direction === '冲突' ? '可能削弱' : effect === '暂不影响假设' ? '暂不改变' : '暂不确认对'
  const suffix = action === '暂不确认对' ? '的方向性影响' : ''
  return `${action}“${statement}”${suffix}`
}

function metricValue(value: string, unit: string) {
  const number = Number(value)
  if (!Number.isFinite(number)) return value
  return `${number.toFixed(Math.abs(number) >= 100 ? 1 : 2)}${unit}`
}

function metricChange(points: Trend['points'], unit: string) {
  if (points.length < 2) return '历史样本不足，暂不计算变化'
  const current = Number(points.at(-1)?.value)
  const previous = Number(points.at(-2)?.value)
  if (!Number.isFinite(current) || !Number.isFinite(previous)) return '指标值待核验'
  const delta = current - previous
  const sign = delta > 0 ? '+' : ''
  return unit === '%' ? `较上期 ${sign}${delta.toFixed(2)} 个百分点` : `较上期 ${sign}${delta.toFixed(2)}${unit}`
}

function MetricLineChart({ points, unit, expectedValue, invalidationThreshold }: { points: Trend['points']; unit: string; expectedValue?: string; invalidationThreshold?: string }) {
  const data = points.map((point) => ({ ...point, numeric: Number(point.value) })).filter((point) => Number.isFinite(point.numeric))
  if (data.length < 2) return <div className="metric-chart-empty">历史数据不足，暂不能绘制趋势图。</div>
  const finiteNumber = (value?: string) => {
    const numeric = Number(value)
    return Number.isFinite(numeric) ? numeric : undefined
  }
  const expected = finiteNumber(expectedValue)
  const threshold = finiteNumber(invalidationThreshold)
  const scaleValues = [...data.map((point) => point.numeric), ...(expected === undefined ? [] : [expected]), ...(threshold === undefined ? [] : [threshold])]
  const rawMin = Math.min(...scaleValues)
  const rawMax = Math.max(...scaleValues)
  const niceStep = (range: number) => {
    const magnitude = 10 ** Math.floor(Math.log10(Math.max(range / 4, 1)))
    const fraction = range / 4 / magnitude
    const niceFraction = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 2.5 ? 2.5 : fraction <= 5 ? 5 : 10
    return niceFraction * magnitude
  }
  const step = niceStep(rawMax - rawMin)
  const tickMinimum = Math.floor(rawMin / step) * step
  const tickMaximum = Math.ceil(rawMax / step) * step || step
  const minimum = tickMinimum - step * .16
  const maximum = tickMaximum + step * .16
  const width = 760
  const height = 246
  const left = 64
  const right = 72
  const top = 22
  const bottom = 44
  const chartWidth = width - left - right
  const chartHeight = height - top - bottom
  const x = (index: number) => left + (index / Math.max(data.length - 1, 1)) * chartWidth
  const y = (value: number) => top + ((maximum - value) / (maximum - minimum || 1)) * chartHeight
  const actualPath = data.map((point, index) => `${x(index)},${y(point.numeric)}`).join(' ')
  const firstValidation = data.findIndex((point) => point.isValidationWindow !== false)
  const validationPath = firstValidation >= 0 ? data.slice(firstValidation).map((point, index) => `${x(firstValidation + index)},${y(point.numeric)}`).join(' ') : ''
  const tickCount = Math.round((tickMaximum - tickMinimum) / step)
  const ticks = Array.from({ length: tickCount + 1 }, (_, index) => tickMaximum - index * step)
  const label = (value: number) => `${value.toFixed(Math.abs(value) >= 10 ? 0 : 1)}${unit}`
  const expectedY = expected === undefined ? undefined : y(expected)
  const thresholdY = threshold === undefined ? undefined : y(threshold)
  const labelsTooClose = expectedY !== undefined && thresholdY !== undefined && Math.abs(expectedY - thresholdY) < 18
  const current = data.at(-1)!
  const currentY = y(current.numeric)
  return <figure className="metric-line-chart">
    <figcaption><span><i className="actual" />实际值</span>{expected !== undefined && <span><i className="expected" />预期线 {label(expected)}</span>}{threshold !== undefined && <span><i className="threshold" />失效警示线 {label(threshold)}</span>}</figcaption>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="指标历史趋势图，包含预期线与失效警示线">
      {thresholdY !== undefined && <rect x={left} y={thresholdY} width={chartWidth} height={height - bottom - thresholdY} className="metric-warning-zone" />}
      {ticks.map((tick) => <g key={tick}><line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} className="metric-grid-line" /><text x={left - 10} y={y(tick) + 4} textAnchor="end" className="metric-y-label">{label(tick)}</text></g>)}
      {expected !== undefined && expectedY !== undefined && <g><line x1={left} x2={width - right} y1={expectedY} y2={expectedY} className="metric-expected-line" /><text x={width - right + 7} y={expectedY + (labelsTooClose ? -5 : 4)} className="metric-expected-label">预期 {label(expected)}</text></g>}
      {threshold !== undefined && thresholdY !== undefined && <g><line x1={left} x2={width - right} y1={thresholdY} y2={thresholdY} className="metric-threshold-line" /><text x={width - right + 7} y={thresholdY + (labelsTooClose ? 12 : 4)} className="metric-threshold-label">警示 {label(threshold)}</text></g>}
      <line x1={left} x2={left} y1={top} y2={height - bottom} className="metric-axis" /><line x1={left} x2={width - right} y1={height - bottom} y2={height - bottom} className="metric-axis" />
      <polyline points={actualPath} className="metric-history-line" />
      {validationPath && <polyline points={validationPath} className="metric-validation-line" />}
      {data.map((point, index) => <g key={point.period}><circle cx={x(index)} cy={y(point.numeric)} r={index === data.length - 1 ? 5 : 3.3} className={`${index === data.length - 1 ? 'metric-current-point' : point.isValidationWindow === false ? 'metric-reference-point' : 'metric-validation-point'}`}><title>{`${point.period}：${label(point.numeric)}${point.isValidationWindow === false ? '（历史参考）' : '（验证期）'}`}</title></circle><text x={x(index)} y={height - bottom + 18} textAnchor="middle" className="metric-x-label">{point.period}</text></g>)}
      <g><rect x={x(data.length - 1) - 23} y={Math.max(top + 2, currentY - 25)} width="46" height="16" rx="3" className="metric-current-label-bg" /><text x={x(data.length - 1)} y={Math.max(top + 13, currentY - 14)} textAnchor="middle" className="metric-current-value-label">{label(current.numeric)}</text></g>
    </svg>
  </figure>
}

function ImpactMetricPanel({ trend }: { trend?: Trend }) {
  if (!trend || !trend.metricId) return <div className="impact-metric-empty"><strong>量化指标尚未接入</strong><span>这条假设目前仅保留定性观察，需由研究员结合资料判断。</span></div>
  const latest = trend.points.at(-1)
  const previous = trend.points.at(-2)
  const change = metricChange(trend.points, trend.unit)
  const changeIsNegative = Number(latest?.value) < Number(previous?.value)
  return <div className="impact-metric-panel">
    <div className="impact-metric-heading"><span>关联指标</span><strong>{trend.metricName || trend.metricId}</strong><small>{trend.unit || '单位待补'} · 最近 {trend.points.length} 期历史</small></div>
    <div className="impact-metric-current"><span>最新已入库期</span><b>{latest ? metricValue(latest.value, trend.unit) : '—'}</b><small>{latest?.period ?? '尚无披露期'}</small></div>
    <div className={`impact-metric-change ${changeIsNegative ? 'down' : 'up'}`}><span>已披露期变化</span><strong>{change}</strong><small>对比 {previous?.period ?? '上一已入库期'}</small></div>
    <MetricLineChart points={trend.points} unit={trend.unit} expectedValue={trend.expectedValue} invalidationThreshold={trend.invalidationThreshold} />
    <div className="impact-metric-rules"><span>预期值 <b>{trend.expectedValue == null ? '待维护' : metricValue(trend.expectedValue, trend.unit)}</b></span><span>失效线 <b>{trend.invalidationThreshold == null ? '待维护' : metricValue(trend.invalidationThreshold, trend.unit)}</b></span><details><summary>查看监测口径</summary><p>{trend.invalidationRule || '尚未维护具体失效规则，请在主投资逻辑中补充。'}</p></details></div>
  </div>
}

type SourceFactWithDocument = LogicChangeDigestDetail['sourceDocuments'][number]['facts'][number] & {
  documentTitle: string
  documentType?: string
}

function ImpactEvidenceDrawer({ evidenceIds, sourceFacts }: { evidenceIds: string[]; sourceFacts: Map<string, SourceFactWithDocument> }) {
  const facts = evidenceIds.map((id) => sourceFacts.get(id)).filter((item): item is SourceFactWithDocument => Boolean(item))
  if (!facts.length) return <span className="hypothesis-evidence-unavailable">关联证据正在整理，暂不可直接回查</span>
  const previews = facts.slice(0, 2)
  return <details className="impact-evidence-preview impact-evidence-inline">
    <summary className="impact-evidence-preview-heading"><span>本路径依据</span><strong>查看 {facts.length} 条依据 <i>⌄</i></strong></summary>
    <div className="impact-evidence-preview-compact">
      <div className="impact-evidence-preview-list">
        {previews.map((fact) => <article key={fact.evidenceId}><header><span className="source-doc-type">{fact.documentType || '公开资料'}</span><small>资料事实</small></header><ul>{evidenceHighlights(fact.factExcerpt).map((highlight, index) => <li key={`${fact.evidenceId}-${index}`}>{highlight}</li>)}</ul><footer>来源：{readableSourceTitle(fact.documentTitle)}</footer></article>)}
      </div>
      {facts.length > previews.length && <div className="impact-evidence-inline-list">{facts.slice(previews.length).map((fact, index) => <article key={fact.evidenceId}><span>{String(index + previews.length + 1).padStart(2, '0')}</span><div><strong>{readableEvidenceText(fact.factExcerpt)}</strong><small>{readableSourceTitle(fact.documentTitle)}</small></div><div className="hypothesis-evidence-actions"><NavLink to={`/updates/${encodeURIComponent(fact.evidenceId)}`}>关联原文</NavLink><NavLink to={`/documents/${encodeURIComponent(fact.evidenceLocator.split('#')[0])}`}>阅读全文</NavLink></div></article>)}</div>}
      <div className="impact-evidence-inline-actions"><span>共 {facts.length} 条，均可回查入库原文</span><NavLink to={`/documents/${encodeURIComponent(facts[0].evidenceLocator.split('#')[0])}`}>打开完整资料 →</NavLink></div>
    </div>
  </details>
}

function ImpactReasoningChain({
  impact,
  sourceFacts,
}: {
  impact: LogicChangeDigestDetail['hypothesisImpacts'][number]
  sourceFacts: Map<string, SourceFactWithDocument>
}) {
  const strength = impact.strength ?? '待复核'
  const relatedMetrics = impact.relatedMetrics.length ? impact.relatedMetrics.join('、') : '尚未映射量化指标'
  const fallbackDirection = impact.direction === '支持' || impact.direction === '冲突' || impact.direction === '中性' ? impact.direction : '中性'
  const fallbackMechanism = impact.businessImpact && !impact.businessImpact.startsWith('尚不能确认')
    ? `${impact.rationale} 经营含义：${impact.businessImpact}`
    : `${impact.rationale} 当前尚缺少可确认的经营传导，需补充直接证据。`
  const hasLegacyPlaceholder = impact.paths.some((path) => /待核验.*候选关系|待研究员核验/u.test(path.label))
  const paths = impact.paths.length && !hasLegacyPlaceholder ? impact.paths : [{
    direction: fallbackDirection,
    label: 'AI 候选传导',
    mechanism: fallbackMechanism,
    evidenceIds: impact.evidenceIds,
  }]
  const hasSupport = paths.some((path) => path.direction === '支持')
  const hasConflict = paths.some((path) => path.direction === '冲突')
  const isDivergent = impact.presentation === '双向分歧' || impact.direction === '分歧' || (hasSupport && hasConflict)
  const presentation = impact.presentation ?? (isDivergent ? '双向分歧' : '单一路径')
  const causalLabel = isDivergent ? '正反证据如何汇合到同一假设' : 'AI 从资料到假设的候选传导'
  const guide = impactPresentationGuide(presentation)
  return <div className="impact-reasoning-chain">
    <div className="impact-reasoning-verdict">
      <div><span>AI 判断</span><p>{impact.rationale}</p><div className="impact-classification"><b>{presentation}</b><span>影响层级：{impact.impactLayer ?? '待判定'}</span><span>证据性质：{impact.directness ?? '待复核'}</span><span>传导状态：{impact.transmissionStatus ?? '尚待验证'}</span></div></div>
      <div className={`impact-strength-badge strength-${strength}`}><span>影响强度</span><strong>{strength}</strong><small>{impact.strengthReason ?? '待结合证据直接性与缺失信息复核。'}</small></div>
    </div>
    <section className={`impact-causal-map ${isDivergent ? 'is-divergent' : 'is-single'}`}>
      <header><div><span>传导路径</span><h4>{causalLabel}</h4></div><small>每条路径均可直接查看它实际引用的资料</small></header>
      <div className="impact-scenario-guidance"><strong>{guide.title}</strong><span>{guide.text}</span></div>
      <div className="impact-causal-paths">
        {paths.map((path, index) => <article key={`${path.label}-${index}`} className={`impact-causal-path ${impactDirectionClass(path.direction)}`}>
          <header><span>路径 {String(index + 1).padStart(2, '0')}</span><b>{path.direction}</b></header>
          <h5>{path.label}</h5>
          <p>{path.mechanism}</p>
          <div className="impact-path-effect"><span>落到当前假设</span><strong>{pathEffectCopy(path.direction, impact.statement, impact.hypothesisEffect)}</strong><small>{impact.hypothesisEffect ? `整体候选作用：${impact.hypothesisEffect}` : '候选作用待研究员确认'}</small></div>
          <ImpactEvidenceDrawer evidenceIds={path.evidenceIds} sourceFacts={sourceFacts} />
        </article>)}
      </div>
      {isDivergent && <div className="impact-path-convergence"><span>路径汇合</span><strong>{impact.hypothesisEffect ?? '增加不确定性'}</strong><p>{impact.businessImpact ?? '支持与冲突信号并存，尚不能据此确认公司经营事实。'}</p></div>}
    </section>
    <section className="impact-validation-row">
      <div><span>对该假设的候选作用</span><strong>{impact.hypothesisEffect ?? '待研究员判断'}</strong><p>{impact.businessImpact ?? '尚不能确认具体经营含义。'}</p></div>
      <div><span>后续验证</span><p>{impact.indicatorOutlook ?? '需结合后续可观察指标验证。'}</p><em>关联指标：{relatedMetrics}</em></div>
    </section>
  </div>
}

function researchOutputTone(outputType: Suggestion['outputType']) {
  return outputType === '状态变更建议' ? 'decision' : outputType === '研究提醒' ? 'alert' : 'record'
}

function ResearchOutcomePanel({
  output,
  hypothesisNames,
}: {
  output?: Pick<Suggestion, 'outputType' | 'currentStatus' | 'suggestedStatus' | 'requiresHumanConfirmation' | 'reasons' | 'researchAlerts' | 'hypothesisHealth'>
  hypothesisNames: Map<string, string>
}) {
  if (!output) return <section className="research-outcome-panel empty"><div><span>研究处理结果</span><h2>等待本批关系完成处置</h2><p>确认、观察或驳回候选关系后，系统会统一输出状态建议、研究提醒与各假设健康度。</p></div></section>
  const tone = researchOutputTone(output.outputType)
  const title = output.outputType === '状态变更建议'
    ? `建议正式状态由“${output.currentStatus}”调整为“${output.suggestedStatus}”`
    : output.outputType === '研究提醒'
      ? '正式状态不变，但有需要跟进的研究事项'
      : '本批仅沉淀证据与假设健康度，正式状态保持不变'
  return <section className={`research-outcome-panel ${tone}`}>
    <header><div><span>研究处理结果</span><h2>{title}</h2><p>{output.requiresHumanConfirmation ? '这是状态变更建议，需要负责人填写理由后在右侧接受、拒绝或修改。' : '这不是状态变更待办；请按提醒继续跟踪或将本轮信息留作研究依据。'}</p></div><b>{output.outputType}</b></header>
    {output.reasons.length > 0 && <div className="research-outcome-rationale"><strong>为什么得到这个结果</strong><ul>{output.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>}
    {output.researchAlerts.length > 0 && <section className="research-alert-list" aria-label="研究提醒"><header><strong>研究提醒</strong><span>不会自动改正式状态</span></header>{output.researchAlerts.map((alert, index) => <article key={`${alert.title}-${index}`}><b>{alert.level}</b><div><strong>{alert.title}</strong><p>{alert.detail}</p>{alert.hypothesisIds.length > 0 && <small>涉及：{alert.hypothesisIds.map((id) => hypothesisNames.get(id) ?? id).join('；')}</small>}</div></article>)}</section>}
    {output.hypothesisHealth.length > 0 && <section className="hypothesis-health-list" aria-label="假设健康度"><header><strong>本批假设健康度</strong><span>基于已确认关系与已维护的指标规则</span></header><div>{output.hypothesisHealth.map((health) => <article key={health.hypothesisId}><div><span className={`hypothesis-health-state state-${health.state}`}>{health.state}</span><strong>{hypothesisNames.get(health.hypothesisId) ?? health.hypothesisId}</strong><p>{health.reason}</p></div><small><b>支持 {health.supportCount}</b><b>冲突 {health.conflictCount}</b></small></article>)}</div></section>}
  </section>
}

export function HypothesisReviewCard({
  impact,
  thesisId,
  currentThesisStatus,
  suggestion,
  sourceFacts,
}: {
  impact: LogicChangeDigestDetail['hypothesisImpacts'][number]
  thesisId: string
  currentThesisStatus: string
  suggestion?: Suggestion
  sourceFacts: Map<string, SourceFactWithDocument>
}) {
  const qc = useQueryClient()
  const [activeDecision, setActiveDecision] = useState<{ relationId: string; kind: 'reject' | 'observe' } | null>(null)
  const [decisionReason, setDecisionReason] = useState('')
  const [missingInformation, setMissingInformation] = useState('')
  const [validationTrigger, setValidationTrigger] = useState('')
  const [reviewOn, setReviewOn] = useState('')
  const [statusReason, setStatusReason] = useState('')
  const [targetStatus, setTargetStatus] = useState(currentThesisStatus)
  const relations = useQuery({
    queryKey: ['logic-change-impact-relations', thesisId, impact.hypothesisId, impact.evidenceIds],
    queryFn: async () => {
      const results = await Promise.all(impact.evidenceIds.map(async (evidenceId) => ({ evidenceId, items: await getRelations(evidenceId) })))
      return results.flatMap(({ evidenceId, items }) => items
        .filter((relation) => relation.thesisId === thesisId && relation.hypothesisId === impact.hypothesisId && relation.status !== 'deactivated')
        .map((relation) => ({ evidenceId, relation })))
    },
    enabled: impact.evidenceIds.length > 0,
  })
  const observationPrefix = '[观察清单]'
  const observationRelations = (relations.data ?? []).filter((item) => item.relation.status === 'pending' && item.relation.reason.startsWith(observationPrefix))
  const pendingRelations = (relations.data ?? []).filter((item) => item.relation.status === 'pending' && !item.relation.reason.startsWith(observationPrefix))
  const reviewedRelations = (relations.data ?? []).filter((item) => item.relation.status !== 'pending')
  const groupRelations = (items: typeof pendingRelations) => {
    const groups = new Map<string, { key: string; direction: string; strength: string; sourceTitles: Set<string>; sourceTypes: Set<string>; items: typeof pendingRelations }>()
    for (const item of items) {
      const fact = sourceFacts.get(item.evidenceId)
      const title = fact?.documentTitle || '未识别来源资料'
      const docType = fact?.documentType || '研究资料'
      const key = `${item.relation.direction}@@${item.relation.strength}`
      const group = groups.get(key) ?? { key, direction: item.relation.direction, strength: item.relation.strength, sourceTitles: new Set<string>(), sourceTypes: new Set<string>(), items: [] }
      group.sourceTitles.add(title)
      group.sourceTypes.add(docType)
      group.items.push(item)
      groups.set(key, group)
    }
    return [...groups.values()]
  }
  const pendingGroups = groupRelations(pendingRelations)
  const observationGroups = groupRelations(observationRelations)
  const review = useMutation({
    mutationFn: ({ items, action, reason }: { items: typeof pendingRelations; action: '确认' | '驳回' | '暂不判断'; reason?: string }) => Promise.all(items.map(({ evidenceId, relation }) => reviewRelation(evidenceId, relation.relationId, action, reason))),
    onSuccess: async () => {
      setActiveDecision(null)
      setDecisionReason('')
      setMissingInformation('')
      setValidationTrigger('')
      setReviewOn('')
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['logic-change-impact-relations', thesisId, impact.hypothesisId] }),
        qc.invalidateQueries({ queryKey: ['suggestions', thesisId] }),
        qc.invalidateQueries({ queryKey: ['logic-change-digest'] }),
        qc.invalidateQueries({ queryKey: ['research-updates'] }),
        qc.invalidateQueries({ queryKey: ['workbench'] }),
      ])
    },
  })
  const hasSuggestion = Boolean(suggestion && !suggestion.humanAction && suggestion.requiresHumanConfirmation)
  const statusDecision = useMutation({
    mutationFn: (action: '接受' | '拒绝' | '修改') => decideStatus(thesisId, { suggestionId: suggestion!.suggestionId, action, reason: statusReason, targetStatus: action === '修改' ? targetStatus : undefined }),
    onSuccess: async () => {
      setStatusReason('')
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['suggestions', thesisId] }),
        qc.invalidateQueries({ queryKey: ['thesis', thesisId] }),
        qc.invalidateQueries({ queryKey: ['logic-change-digest'] }),
        qc.invalidateQueries({ queryKey: ['workbench'] }),
      ])
    },
  })
  const observationReason = `${observationPrefix} 缺失信息：${missingInformation.trim()}；触发条件：${validationTrigger.trim() || '获得新的直接证据'}；复查日期：${reviewOn}`
  return <section className={`hypothesis-review-card ${hasSuggestion ? 'has-suggestion' : 'stable'}`}>
    <header>
      <div><span>第一步 · 证据关系处置</span><strong>{pendingRelations.length ? `决定哪些信息进入“${impact.statement}”的证据链` : '本轮关系已完成分流'}</strong></div>
      <small>{pendingGroups.length ? `${pendingGroups.length} 个关系包待决策 · 已归并 ${pendingRelations.length} 条底层证据` : `${reviewedRelations.length} 条已处置 · ${observationGroups.length} 个关系包观察中`}</small>
    </header>
    {pendingGroups.length > 0 && <div className="relation-decision-list">{pendingGroups.map((group, index) => {
      const active = activeDecision?.relationId === group.key ? activeDecision.kind : null
      return <article className="relation-decision-item" key={group.key}>
        <div className="relation-decision-summary"><span>AI 判断主题 {String(index + 1).padStart(2, '0')} · {group.sourceTypes.size} 类资料</span><strong>{group.direction} · {group.strength}强度</strong><small>跨 {group.sourceTitles.size} 份资料归并 · 共 {group.items.length} 条底层证据</small></div>
        <details className="relation-group-evidence"><summary>查看来源与原始事实（{group.sourceTitles.size} 份资料 / {group.items.length} 条证据）</summary>{group.items.map(({ evidenceId }) => { const fact = sourceFacts.get(evidenceId); return <div key={evidenceId}><b>{fact?.documentTitle || evidenceId}</b><span>{fact?.factExcerpt || '原始事实可在来源资料区查看'}</span></div> })}</details>
        <div className="relation-decision-buttons"><button className="button primary" disabled={review.isPending} onClick={() => review.mutate({ items: group.items, action: '确认', reason: `研究员确认 AI 判断主题：${group.direction} / ${group.strength}强度，覆盖 ${group.sourceTitles.size} 份资料` })}>纳入该判断主题</button><button className="button secondary" disabled={review.isPending} onClick={() => setActiveDecision({ relationId: group.key, kind: 'reject' })}>不纳入该主题</button><button className="button secondary" disabled={review.isPending} onClick={() => setActiveDecision({ relationId: group.key, kind: 'observe' })}>加入观察清单</button></div>
        {active === 'reject' && <div className="relation-decision-form"><label><span>不纳入原因（必填）</span><textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} placeholder="例如：关系不成立、信息重复、来源不足或与当前假设无关" /></label><div><button className="button danger-link" disabled={review.isPending || !decisionReason.trim()} onClick={() => review.mutate({ items: group.items, action: '驳回', reason: decisionReason.trim() })}>确认整包不纳入</button><button className="button ghost" onClick={() => setActiveDecision(null)}>取消</button></div></div>}
        {active === 'observe' && <div className="relation-decision-form observation-form"><label><span>还缺少什么（必填）</span><textarea value={missingInformation} onChange={(event) => setMissingInformation(event.target.value)} placeholder="例如：缺少下一季度订单兑现或毛利率数据" /></label><label><span>重新验证条件</span><input value={validationTrigger} onChange={(event) => setValidationTrigger(event.target.value)} placeholder="例如：公司披露季报或指标越过阈值" /></label><label><span>复查日期（必填）</span><input type="date" value={reviewOn} onChange={(event) => setReviewOn(event.target.value)} /></label><div><button className="button primary" disabled={review.isPending || !missingInformation.trim() || !reviewOn} onClick={() => review.mutate({ items: group.items, action: '暂不判断', reason: observationReason })}>整包保存到观察清单</button><button className="button ghost" onClick={() => setActiveDecision(null)}>取消</button></div></div>}
      </article>
    })}</div>}
    {observationGroups.length > 0 && <div className="observation-list"><header><strong>观察清单</strong><span>条件满足后重新进入判断</span></header>{observationGroups.map((group) => <article key={group.key}><div><b>{group.direction} · {group.strength}强度 · {group.sourceTitles.size} 份资料</b><p>{group.items[0].relation.reason.replace(observationPrefix, '').trim()}</p></div><button className="button secondary" disabled={review.isPending} onClick={() => review.mutate({ items: group.items, action: '暂不判断', reason: '观察条件已满足，重新进入待处理' })}>整包重新评估</button></article>)}</div>}
    <InlineError error={review.error} />
    {pendingRelations.length === 0 && <section className={`status-decision-stage ${hasSuggestion ? 'is-actionable' : ''}`}>
      <header><div><span>第二步 · 主逻辑状态决策</span><strong>{hasSuggestion ? `${suggestion!.currentStatus} → ${suggestion!.suggestedStatus}` : `本轮无需调整主逻辑状态（当前：${currentThesisStatus}）`}</strong></div></header>
      {hasSuggestion ? <><div className="hypothesis-suggestion-reasons"><b>触发依据</b><ul>{suggestion!.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div><label className="status-decision-reason"><span>研究员判断理由（必填）</span><textarea value={statusReason} onChange={(event) => setStatusReason(event.target.value)} placeholder="说明为什么接受建议、坚持原状态或调整为其他状态" /></label><div className="status-decision-actions"><button className="button primary" disabled={!statusReason.trim() || statusDecision.isPending} onClick={() => statusDecision.mutate('接受')}>接受状态建议</button><button className="button secondary" disabled={!statusReason.trim() || statusDecision.isPending} onClick={() => statusDecision.mutate('拒绝')}>保持当前状态</button><select aria-label="自定义目标状态" value={targetStatus} onChange={(event) => setTargetStatus(event.target.value)}><option>验证中</option><option>出现分歧</option><option>重大风险</option><option>已关闭</option></select><button className="button secondary" disabled={!statusReason.trim() || targetStatus === currentThesisStatus || statusDecision.isPending} onClick={() => statusDecision.mutate('修改')}>调整为所选状态</button></div><InlineError error={statusDecision.error} /></> : <p>证据关系已完成处置，但尚未达到正式状态变化阈值。系统已保留本轮证据决策与观察项，不再要求重复点击“维持不变”。</p>}
    </section>}
    <div className="hypothesis-review-complete"><span>所有操作都会写入关系记录和审计日志；AI 不会自动修改正式投资逻辑。</span><NavLink to={`/theses/${encodeURIComponent(thesisId)}`}>进入公司逻辑维护页 →</NavLink></div>
  </section>
}

function LogicChangeSourceFact({ fact, hypothesisNames }: { fact: LogicChangeDigestDetail['sourceDocuments'][number]['facts'][number]; hypothesisNames: Map<string, string> }) {
  const [expanded, setExpanded] = useState(false)
  const source = useQuery({
    queryKey: ['logic-change-source-segment', fact.evidenceLocator],
    queryFn: () => getDocumentSegment(fact.evidenceLocator),
    enabled: expanded,
  })
  const affectedHypotheses = fact.hypothesisIds.map((id) => hypothesisNames.get(id) ?? id)
  return <article className="logic-change-source-fact">
    <header>
      <div className="logic-change-fact-tags">
        {fact.isKeyCitation && <span className="citation-tag">AI 关键依据</span>}
        {fact.directions.map((direction) => <span key={direction} className={`direction-chip ${impactDirectionClass(direction)}`}>{direction}</span>)}
      </div>
      <span className="mono">{fact.evidenceId}</span>
    </header>
    <p>{fact.factExcerpt}</p>
    <footer>
      <span>关联：{affectedHypotheses.join('；') || '待确认'}</span>
      <button type="button" className="text-action" onClick={() => setExpanded((value) => !value)}>{expanded ? '收起入库原文' : '查看入库原文'} <i>{expanded ? '⌃' : '⌄'}</i></button>
    </footer>
    {expanded && <div className="logic-change-original">
      {source.isLoading ? <span className="muted">正在定位原文段落…</span> : <>
        <blockquote>{source.data?.content ?? fact.factExcerpt}</blockquote>
        <small>{readableSourceLocator(source.data?.locator ?? fact.evidenceLocator)}{source.data?.page ? ` · 第 ${source.data.page} 页` : ''}</small>
        {source.error && <p className="inline-error">原文段落暂不可用，当前展示事实摘录。</p>}
      </>}
    </div>}
  </article>
}

function BatchDecisionWorkspace({ item }: { item: LogicChangeDigestDetail }) {
  const qc = useQueryClient()
  const evidenceIds = [...new Set(item.hypothesisImpacts.flatMap((impact) => impact.evidenceIds))]
  const relationQueries = useQueries({ queries: evidenceIds.map((evidenceId) => ({ queryKey: ['batch-review-relation', evidenceId], queryFn: () => getRelations(evidenceId) })) })
  const previousBatch = useQuery({ queryKey: ['decision-batch', item.thesisId, item.digestId], queryFn: () => getLatestDecisionBatch(item.thesisId, item.digestId) })
  const [decisions, setDecisions] = useState<Record<string, '确认' | '驳回' | '暂不判断'>>(() => Object.fromEntries(item.hypothesisImpacts.map((impact) => [impact.hypothesisId, impact.direction === '分歧' || impact.presentation === '双向分歧' ? '暂不判断' : '确认'])))
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const [statusReason, setStatusReason] = useState('')
  const [targetStatus, setTargetStatus] = useState('验证中')
  const relations = evidenceIds.flatMap((evidenceId, index) => (relationQueries[index].data ?? []).filter((relation) => relation.thesisId === item.thesisId && relation.status === 'pending').map((relation) => ({ evidenceId, relation })))
  const submit = useMutation({ mutationFn: () => batchReviewRelations(item.thesisId, item.digestId, relations.map(({ evidenceId, relation }) => ({ evidenceId, relationId: relation.relationId, action: decisions[relation.hypothesisId] ?? '暂不判断', reason: reasons[relation.hypothesisId] || (decisions[relation.hypothesisId] === '确认' ? '研究员接受本批 AI 判断' : undefined) }))), onSuccess: async () => { await Promise.all([qc.invalidateQueries({ queryKey: ['logic-change-digest'] }), qc.invalidateQueries({ queryKey: ['research-updates'] }), qc.invalidateQueries({ queryKey: ['suggestions', item.thesisId] }), qc.invalidateQueries({ queryKey: ['audit', item.thesisId] }), qc.invalidateQueries({ queryKey: ['thesis', item.thesisId] }), qc.invalidateQueries({ queryKey: ['company-theses'] }), qc.invalidateQueries({ queryKey: ['workbench'] })]) } })
  const statusDecision = useMutation({
    mutationFn: async (action: '接受' | '拒绝' | '修改') => {
      const batch = submit.data ?? previousBatch.data
      if (!batch) throw new Error('未找到可处置的研究决策批次')
      await decideStatus(item.thesisId, { suggestionId: batch.suggestionId, action, reason: statusReason.trim(), targetStatus: action === '修改' ? targetStatus : undefined })
      return action
    },
    onSuccess: async () => { await Promise.all([qc.invalidateQueries({ queryKey: ['thesis', item.thesisId] }), qc.invalidateQueries({ queryKey: ['company-theses'] }), qc.invalidateQueries({ queryKey: ['suggestions', item.thesisId] }), qc.invalidateQueries({ queryKey: ['audit', item.thesisId] }), qc.invalidateQueries({ queryKey: ['workbench'] })]) },
  })
  const needsReason = item.hypothesisImpacts.some((impact) => decisions[impact.hypothesisId] !== '确认' && !reasons[impact.hypothesisId]?.trim())
  const counts = Object.values(decisions).reduce<Record<string, number>>((result, action) => ({ ...result, [action]: (result[action] ?? 0) + 1 }), {})
  const savedBatch = submit.data ?? previousBatch.data
  if (savedBatch) {
    const result = savedBatch
    const statusHandled = statusDecision.isSuccess || Boolean(result.statusDecisionAction)
    return <section className="batch-decision-workspace batch-decision-result" aria-live="polite">
      <span>{statusHandled ? '正式状态决策完成' : '本批处理完成'}</span>
      <h2>{statusHandled ? '本轮研究处置已全部完成' : '研究决策已保存并可追溯'}</h2>
      <p>关系决策、AI 原始判断和最终状态建议已作为同一批次写入操作记录。</p>
      <div className="batch-result-counts"><article><b>{result.confirmedCount}</b><span>纳入</span></article><article><b>{result.pendingCount}</b><span>观察</span></article><article><b>{result.rejectedCount}</b><span>不纳入</span></article></div>
      <div className={`batch-result-status ${result.requiresStatusDecision ? 'requires-decision' : 'stable'}`}><span>{result.requiresStatusDecision ? '需要负责人决策' : result.outputType}</span><strong>{result.currentStatus}{result.requiresStatusDecision ? ` → ${result.suggestedStatus}` : ''}</strong><small>{result.requiresStatusDecision ? '正式投资逻辑尚未变更' : result.outputType === '研究提醒' ? '已生成关注事项，正式状态不变' : `正式状态继续保持“${result.currentStatus}”，无需重复确认`}</small></div>
      {result.researchAlerts.length > 0 && <p className="batch-reminder-note">已生成 {result.researchAlerts.length} 项研究提醒，详见左侧“研究处理结果”；提醒不会改变正式状态。</p>}
      {result.requiresStatusDecision && !statusHandled && <section className="batch-status-decision"><h3>处理正式投资逻辑状态</h3>{result.suggestionReasons.length > 0 && <ul>{result.suggestionReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>}<label><span>研究员判断理由（必填）</span><textarea value={statusReason} onChange={(event) => setStatusReason(event.target.value)} placeholder="说明为什么接受建议、保持当前状态或调整为其他状态" /></label><div className="batch-status-actions"><button className="button primary" disabled={!statusReason.trim() || statusDecision.isPending} onClick={() => statusDecision.mutate('接受')}>接受建议</button><button className="button secondary" disabled={!statusReason.trim() || statusDecision.isPending} onClick={() => statusDecision.mutate('拒绝')}>保持当前状态</button><select aria-label="调整后的正式状态" value={targetStatus} onChange={(event) => setTargetStatus(event.target.value)}><option>验证中</option><option>出现分歧</option><option>重大风险</option><option>已关闭</option></select><button className="button secondary" disabled={!statusReason.trim() || targetStatus === result.currentStatus || statusDecision.isPending} onClick={() => statusDecision.mutate('修改')}>调整为所选状态</button></div><InlineError error={statusDecision.error} /></section>}
      {statusHandled && <p className="batch-success">✓ 已{(statusDecision.data ?? result.statusDecisionAction) === '拒绝' ? `保持“${result.currentStatus}”` : (statusDecision.data ?? result.statusDecisionAction) === '修改' ? `调整为“${targetStatus}”` : `更新为“${result.suggestedStatus}”`}，版本、审计和复盘时间线已同步记录。</p>}
      <details className="batch-result-details"><summary>查看本次操作记录 <span>{result.batchId}</span></summary><div>{result.items.map((entry, index) => <article key={entry.relation_id ?? index}><strong>{entry.hypothesis_statement ?? `核心假设 ${index + 1}`}</strong><p><span>AI：{entry.ai_direction ?? '—'} · {entry.ai_strength ?? '—'}</span><b>{entry.human_action === '确认' ? '已纳入' : entry.human_action === '驳回' ? '不纳入' : '继续观察'}</b></p>{entry.human_reason && <small>{entry.human_reason}</small>}</article>)}</div></details>
      <NavLink className="button secondary batch-followup" to={`/companies/${encodeURIComponent(item.securityId)}?thesisId=${encodeURIComponent(item.thesisId)}&tab=研究记录`}>查看投资逻辑与操作记录</NavLink>
    </section>
  }
  if (!previousBatch.isLoading && !relationQueries.some((query) => query.isLoading) && relations.length === 0) {
    return <section className="batch-decision-workspace batch-decision-empty"><span>无需重复处理</span><h2>本批没有待确认关系</h2><p>相关关系可能已由其他入口处理，或不再属于当前投资逻辑。页面不会提交空批次。</p><button className="button secondary" onClick={() => { previousBatch.refetch(); relationQueries.forEach((query) => query.refetch()) }}>重新检查处理状态</button><InlineError error={previousBatch.error ?? relationQueries.find((query) => query.error)?.error} /></section>
  }
  return <section className="batch-decision-workspace"><span>本批决策草稿</span><h2>在 AI 判断基础上统一确认</h2><p>左侧保留完整推理与来源；这里只汇总每项假设的最终处理方式。</p><div className="batch-decision-items">{item.hypothesisImpacts.map((impact, index) => <article key={impact.hypothesisId}><button className="batch-decision-anchor" onClick={() => document.getElementById(`impact-${impact.hypothesisId}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}><span className="hypothesis-order"><small>核心假设</small><b>{String(index + 1).padStart(2, '0')}</b></span><span className="hypothesis-draft-title">{impact.statement}</span></button><div className="hypothesis-draft-meta"><span className={`direction-chip ${impactDirectionClass(impact.direction)}`}>{impact.direction}</span><span>{impact.strength}强度</span><span className={`decision-chip decision-${decisions[impact.hypothesisId]}`}>{decisions[impact.hypothesisId] === '确认' ? '拟纳入' : decisions[impact.hypothesisId] === '驳回' ? '拟排除' : '拟观察'}</span></div><select aria-label={`${impact.statement}的处理方式`} value={decisions[impact.hypothesisId]} onChange={(event) => setDecisions((current) => ({ ...current, [impact.hypothesisId]: event.target.value as '确认' | '驳回' | '暂不判断' }))}><option value="确认">纳入证据链</option><option value="暂不判断">加入观察清单</option><option value="驳回">不纳入</option></select>{decisions[impact.hypothesisId] !== '确认' && <textarea value={reasons[impact.hypothesisId] ?? ''} onChange={(event) => setReasons((current) => ({ ...current, [impact.hypothesisId]: event.target.value }))} placeholder={decisions[impact.hypothesisId] === '暂不判断' ? '填写缺失信息、验证条件和复查计划' : '填写不纳入原因'} />}</article>)}</div><div className="batch-decision-total"><span>纳入 {counts['确认'] ?? 0}</span><span>观察 {counts['暂不判断'] ?? 0}</span><span>不纳入 {counts['驳回'] ?? 0}</span><small>将处理 {relations.length} 条底层关系</small></div><button className="button primary batch-submit" disabled={relationQueries.some((query) => query.isLoading) || !relations.length || needsReason || submit.isPending} onClick={() => submit.mutate()}>{submit.isPending ? '正在提交整批决策…' : '确认本批处理结果'}</button><InlineError error={submit.error} /></section>
}

export function LogicChangeImpactPage() {
  const { securityId = '', thesisId = '' } = useParams()
  const [params] = useSearchParams()
  const businessDay = params.get('business_day') ?? undefined
  const thesis = useQuery({ queryKey: ['thesis', thesisId], queryFn: () => getThesis(thesisId), enabled: Boolean(thesisId) })
  const suggestions = useQuery({ queryKey: ['suggestions', thesisId], queryFn: () => getSuggestions(thesisId), enabled: Boolean(thesisId) })
  const digest = useQuery({
    queryKey: ['logic-change-digest', securityId, thesisId, businessDay],
    queryFn: () => getLogicChangeDigest(securityId, thesisId, businessDay),
    enabled: Boolean(securityId && thesisId),
  })
  const decisionBatch = useQuery({
    queryKey: ['decision-batch', thesisId, digest.data?.digestId],
    queryFn: () => getLatestDecisionBatch(thesisId, digest.data!.digestId),
    enabled: Boolean(thesisId && digest.data?.digestId),
  })
  const trends = useQuery({
    queryKey: ['logic-change-trends', thesisId],
    queryFn: () => getTrends(thesisId),
    enabled: Boolean(thesisId),
  })
  if (digest.isLoading || thesis.isLoading || suggestions.isLoading) return <LoadingState text="正在整理归并影响与来源材料…" />
  if (digest.error || thesis.error || suggestions.error || !digest.data || !thesis.data || !suggestions.data) return <ErrorState error={digest.error ?? thesis.error ?? suggestions.error} />
  const item = digest.data
  const activeSuggestions = suggestions.data.filter((suggestion) => !suggestion.humanAction && suggestion.requiresHumanConfirmation)
  const hypothesisNames = new Map(item.hypothesisImpacts.map((impact) => [impact.hypothesisId, impact.statement]))
  const latestOutput = decisionBatch.data ? {
    outputType: decisionBatch.data.outputType,
    currentStatus: decisionBatch.data.currentStatus,
    suggestedStatus: decisionBatch.data.suggestedStatus,
    requiresHumanConfirmation: decisionBatch.data.requiresHumanConfirmation,
    reasons: decisionBatch.data.suggestionReasons,
    researchAlerts: decisionBatch.data.researchAlerts,
    hypothesisHealth: decisionBatch.data.hypothesisHealth,
  } : suggestions.data.at(-1)
  const trendsByHypothesis = new Map((trends.data ?? []).map((trend) => [trend.hypothesisId, trend]))
  const sourceFacts = new Map<string, SourceFactWithDocument>(item.sourceDocuments.flatMap((source) => source.facts.map((fact) => [fact.evidenceId, { ...fact, documentTitle: source.title, documentType: source.docType }] as const)))
  const uniqueImpactEvidence = new Set(item.hypothesisImpacts.flatMap((impact) => impact.evidenceIds)).size
  return <div className="logic-change-detail-page">
    <header className="logic-change-detail-header">
      <div>
        <NavLink to="/updates">← 返回全部逻辑变化</NavLink>
        <span className="eyebrow">LOGIC CHANGE / {item.businessDate}</span>
        <h1>{item.securityName} · 主投资逻辑影响</h1>
        <p>{item.thesisCoreView}</p>
      </div>
      <div className={`logic-change-direction-card ${item.overallDirection}`}>
        <span>AI 初判</span><strong>{logicDirectionLabel(item.overallDirection)}</strong><small>待研究员确认</small>
      </div>
    </header>
    <main className="logic-change-detail-layout">
      <div className="logic-change-detail-main">
        <section className="logic-change-conclusion-card">
          <header><span>01 / AI 对主投资逻辑的判断</span><small>基于当日已入库资料归并；不改变正式投资逻辑</small></header>
          <p>{item.summary}</p>
          <dl>
            <div><dt>当日来源</dt><dd>{item.sourceDocumentCount} 份</dd></div>
            <div><dt>关联证据</dt><dd>{uniqueImpactEvidence} 条</dd></div>
            <div><dt>影响假设</dt><dd>{item.hypothesisImpacts.length} 条</dd></div>
            <div><dt>状态建议</dt><dd>{activeSuggestions.length ? `${activeSuggestions.length} 项待处置` : '维持不变'}</dd></div>
          </dl>
        </section>
        <ResearchOutcomePanel output={latestOutput ?? undefined} hypothesisNames={hypothesisNames} />
        <section className="logic-change-hypotheses">
          <header><div><span>02 / 影响推理链</span><h2>AI 如何从资料关联到投资逻辑</h2></div><small>每一步均可回查</small></header>
          <div>{item.hypothesisImpacts.map((impact) => <article id={`impact-${impact.hypothesisId}`} key={impact.hypothesisId} className={`logic-change-hypothesis ${impactDirectionClass(impact.direction)} impact-logic-card`}>
            <header><div><span>受影响核心假设</span><h3>{impact.statement}</h3></div><div className="impact-direction-summary"><i /><span>{impact.direction}</span></div></header>
            <div><ImpactReasoningChain impact={impact} sourceFacts={sourceFacts} /><section className="impact-historical-verification"><header><span>历史表现与后续验证</span><small>已披露财务数据仅作为背景，不代表本次新闻造成的实际结果</small></header><ImpactMetricPanel trend={trendsByHypothesis.get(impact.hypothesisId)} /></section></div>
          </article>)}</div>
        </section>
        <section className="logic-change-sources">
          <header><div><span>03 / 全部资料与原文回查</span><h2>补充核验时，再展开查看同日全部材料</h2></div><small>上方已列出 AI 实际引用的依据</small></header>
          <div className="logic-change-source-list">{item.sourceDocuments.map((source) => <details className="logic-change-source-document" key={source.documentId}>
            <summary>
              <div><span className="source-doc-type">{source.docType || '研究资料'}</span><strong>{readableSourceTitle(source.title)}</strong><small>{source.publishedAt ? `披露于 ${formatDate(source.publishedAt)}` : '披露时间待补'} · {source.facts.length} 条事实</small></div>
              <div><span>{source.facts.some((fact) => fact.isKeyCitation) ? '含 AI 关键依据' : '候选来源'}</span><i>⌄</i></div>
            </summary>
            <div className="logic-change-source-body">
              <div className="logic-change-source-tools"><span>每条事实均保留入库定位；展开后只读取对应原文段落。</span><SafeSourceLink url={source.sourceUrl ?? ''} /></div>
              {source.facts.map((fact) => <LogicChangeSourceFact key={fact.evidenceId} fact={fact} hypothesisNames={hypothesisNames} />)}
            </div>
          </details>)}</div>
        </section>
      </div>
      <aside className="logic-change-detail-side">
        <BatchDecisionWorkspace item={item} />
      </aside>
    </main>
  </div>
}

export function DocumentReaderPage() {
  const { documentId = '' } = useParams()
  const document = useQuery({ queryKey: ['full-document', documentId], queryFn: () => getFullDocument(documentId), enabled: Boolean(documentId) })
  if (document.isLoading) return <LoadingState text="正在加载完整入库文档…" />
  if (document.error || !document.data) return <ErrorState error={document.error} />
  const item = document.data
  return <div className="full-document-page">
    <header className="full-document-header"><div><NavLink to="/updates">← 返回研究动态</NavLink><span>{item.docType || '公开资料'} · 完整入库文档</span><h1>{readableSourceTitle(item.title || item.documentId)}</h1><p>披露于 {formatDate(item.publishedAt)} · 共 {item.segmentCount} 个解析段落 · 解析器 {item.parserVersion}</p></div><a href={`#segment-${item.segments[0]?.ordinal ?? 1}`}>从正文开始 ↓</a></header>
    <main className="full-document-layout">
      <aside className="full-document-outline"><strong>文档目录</strong><small>完整解析正文</small><nav>{item.segments.map((segment) => <a key={segment.ordinal} href={`#segment-${segment.ordinal}`}>{segment.page ? `P.${segment.page}` : '正文'} · 第 {segment.ordinal} 段</a>)}</nav></aside>
      <article className="full-document-body">{item.segments.map((segment) => <section id={`segment-${segment.ordinal}`} key={segment.ordinal}><header><span>{segment.page ? `第 ${segment.page} 页` : '正文'}</span><small>第 {segment.ordinal} 段 · {segment.contentKind === 'table_row' ? '表格内容' : '文本段落'}</small></header><p>{segment.content}</p></section>)}</article>
    </main>
  </div>
}

function SourceFactPanel({ item, sourceText, sourceLocator, sourceFailed, status }: { item: { factExcerpt: string; sourceDocumentTitle: string; sourceUrl: string; securityId: string; disclosedAt: string; evidenceLocator?: string }; sourceText?: string; sourceLocator?: string; sourceFailed: boolean; status: string }) {
  const excerpt = readableEvidenceText(item.factExcerpt)
  const original = readableEvidenceText(sourceText || item.factExcerpt)
  const hasDistinctOriginal = original.replace(/\s+/g, ' ').trim() !== excerpt.replace(/\s+/g, ' ').trim()
  const locator = sourceLocator ?? item.evidenceLocator
  return <section className="impact-fact-card"><header><div><span>01 / 来源材料</span><small className="source-title-hint">来源标题 · 用于定位原始资料，不代表影响结论</small><h2>{readableSourceTitle(item.sourceDocumentTitle)}</h2></div><SafeSourceLink url={item.sourceUrl} /></header><div className="source-fact-summary"><span>本次材料要点</span><p>{excerpt}</p><small>系统从原文提炼，供研究员快速判断；尚未代表正式研究结论。</small></div><dl><div><dt>证券</dt><dd>{item.securityId}</dd></div><div><dt>来源类型</dt><dd>公开资料</dd></div><div><dt>发布时间</dt><dd>{formatDate(item.disclosedAt)}</dd></div><div><dt>证据状态</dt><dd>{status}</dd></div></dl><details className="source-original"><summary><span>查看入库原文</span><small>{readableSourceLocator(locator)}</small></summary><blockquote>{original}</blockquote>{!hasDistinctOriginal && <p>当前“材料要点”与这段入库原文内容一致。</p>}</details><footer><span>原文位置：{readableSourceLocator(locator)}</span>{sourceFailed && <span className="inline-error">原文段落暂不可用，当前展示证据摘录。</span>}</footer></section>
}

function ThemeImpactCandidates({ items, activeEvidenceId, activeRelationId }: { items: EvidenceFeedItem[]; activeEvidenceId: string; activeRelationId?: string }) {
  const grouped = new Map<string, EvidenceFeedItem[]>()
  for (const item of items) grouped.set(item.hypothesisId, [...(grouped.get(item.hypothesisId) ?? []), item])
  if (!grouped.size) return null
  return <section className="theme-impact-candidates"><header><div><span>03 / 本主题涉及的核心假设</span><h2>{grouped.size} 条假设等待复核</h2></div><small>{items.length} 条候选关联</small></header><div>{[...grouped.values()].map((group) => { const first = group[0]; const active = first.evidenceId === activeEvidenceId && first.relationId === activeRelationId; return <NavLink className={active ? 'active' : ''} key={first.hypothesisId} to={`/updates/${encodeURIComponent(first.evidenceId)}?relationId=${encodeURIComponent(first.relationId)}`}><i className={first.direction === 'conflict' ? 'conflict' : ''} /><section><strong>{first.hypothesisStatement}</strong><small>{group.length} 条候选关联 · {first.direction === 'conflict' ? '存在冲突影响' : first.direction === 'support' ? '存在支持影响' : '待判断'}</small></section><b>查看 →</b></NavLink> })}</div></section>
}

export function ResearchImpactDetailPage() {
  const { updateId = '' } = useParams()
  const isLegacyDemoId = /^\d+$/.test(updateId)
  const [params] = useSearchParams()
  const qc = useQueryClient()
  const evidence = useQuery({ queryKey: ['evidence', updateId], queryFn: () => getEvidence(updateId), enabled: Boolean(updateId) && !isLegacyDemoId })
  const relations = useQuery({ queryKey: ['relations', updateId], queryFn: () => getRelations(updateId), enabled: Boolean(updateId) && !isLegacyDemoId })
  const source = useQuery({ queryKey: ['source-segment', evidence.data?.evidenceLocator], queryFn: () => getDocumentSegment(evidence.data!.evidenceLocator), enabled: Boolean(evidence.data?.evidenceLocator) })
  const relationId = params.get('relationId')
  const activeRelation = relations.data?.find((item) => item.relationId === relationId) ?? relations.data?.find((item) => item.status !== 'deactivated')
  const thesis = useQuery({ queryKey: ['thesis', activeRelation?.thesisId], queryFn: () => getThesis(activeRelation!.thesisId), enabled: Boolean(activeRelation?.thesisId) })
  const themeFeed = useQuery({ queryKey: ['theme-impact-feed', activeRelation?.thesisId], queryFn: () => getThesisEvidenceFeed(activeRelation!.thesisId), enabled: Boolean(activeRelation?.thesisId) })
  const [note, setNote] = useState('')
  const [result, setResult] = useState('')
  const review = useMutation({ mutationFn: (action: '确认' | '驳回' | '暂不判断') => reviewRelation(updateId, activeRelation!.relationId, action, note || undefined), onSuccess: async (_value, action) => { setResult(action === '确认' ? '已确认影响并刷新相关逻辑状态建议。' : action === '驳回' ? '已驳回候选关联，处理记录已保留。' : '已标记为暂不判断，可稍后继续处理。'); await Promise.all([qc.invalidateQueries({ queryKey: ['research-updates'] }), qc.invalidateQueries({ queryKey: ['relations', updateId] }), qc.invalidateQueries({ queryKey: ['thesis', activeRelation?.thesisId] }), qc.invalidateQueries({ queryKey: ['company-theses'] }), qc.invalidateQueries({ queryKey: ['workbench'] }), qc.invalidateQueries({ queryKey: ['workbench-tasks'] })]) } })
  if (isLegacyDemoId) return <Navigate to="/updates" replace />
  if (evidence.isLoading || relations.isLoading || thesis.isLoading) return <LoadingState text="正在读取影响分析…" />
  if (evidence.error || relations.error || thesis.error || !evidence.data || !relations.data) return <ErrorState error={evidence.error ?? relations.error ?? thesis.error} />
  const item = evidence.data
  const themeItems = (themeFeed.data?.items ?? []).filter((entry) => entry.ingestedAt.slice(0, 10) === item.ingestedAt.slice(0, 10))
  const hypothesis = thesis.data?.hypotheses.find((entry) => entry.hypothesisId === activeRelation?.hypothesisId)
  const metric = hypothesis?.mappings[0]?.metricName ?? hypothesis?.mappings[0]?.metricId ?? '暂未绑定验证指标'
  const status = activeRelation ? updateStatusLabel(activeRelation.status) : '未关联'
  const direction = activeRelation ? updateDirectionLabel(activeRelation.direction) : updateDirectionLabel(item.direction)
  const strength = activeRelation?.strength ?? item.strength
  return <div className="impact-page"><header className="impact-page-header"><div><NavLink to="/updates">← 返回全部动态</NavLink><span>IMPACT REVIEW / {item.evidenceId}</span><h1>具体影响分析</h1></div><div><span className={`update-status status-${status}`}>{status}</span><small>AI 关系置信度</small><strong>{Math.round(item.aiConfidence * 100)}%</strong></div></header><main className="impact-page-layout"><div className="impact-main-column"><SourceFactPanel item={item} sourceText={source.data?.content} sourceLocator={source.data?.locator} sourceFailed={Boolean(source.error)} status={status} /><section className="impact-relation-card"><header><div><span>02 / AI 候选关系</span><h2>事件如何影响现有投资逻辑</h2></div><NavLink to={`/radar/${encodeURIComponent(item.evidenceId)}${activeRelation ? `?relationId=${encodeURIComponent(activeRelation.relationId)}` : ''}`}>查看召回路径与编辑 ›</NavLink></header>{activeRelation && thesis.data && hypothesis ? <><div className="impact-relation-flow"><article><span>事件事实</span><strong>{item.factExcerpt}</strong></article><i>→</i><article><span>验证指标</span><strong>{metric}</strong><small>由假设映射维护</small></article><i>→</i><article><span>核心假设</span><strong>{hypothesis.statement}</strong></article><i>→</i><article><span>投资逻辑</span><strong>{thesis.data.title}</strong><small>{item.securityId}</small></article></div><div className="impact-assessment-grid"><article><span>影响方向</span><strong className={activeRelation.direction === 'conflict' ? 'conflict' : 'support'}>{direction}</strong></article><article><span>影响强度</span><strong>{strengthText[strength] ?? '待评估'}</strong></article><article><span>关系置信度</span><strong>{Math.round(item.aiConfidence * 100)}%</strong></article><article><span>确认状态</span><strong>{status}</strong></article></div><div className="impact-reason"><strong>候选关联理由</strong><p>{activeRelation.reason || '系统未提供文字理由，请通过原文和召回路径完成判断。'}</p></div></> : <div className="updates-empty">该证据尚未关联到可见投资逻辑。可前往证据页新增关联。</div>}</section><ThemeImpactCandidates items={themeItems} activeEvidenceId={item.evidenceId} activeRelationId={activeRelation?.relationId} /></div><aside className="impact-review-panel"><section><span>04 / 研究员确认</span><h2>这条影响是否成立？</h2><p>确认操作会写入审计记录，并重新计算受影响逻辑的状态建议。</p><label>当前投资逻辑<input value={thesis.data?.title ?? '暂无可见关联'} readOnly /></label><label>影响方向<input value={direction} readOnly /></label><label>影响强度<input value={strengthText[strength] ?? '待评估'} readOnly /></label><label>研究员备注<textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="可选：补充判断依据或驳回原因" disabled={!activeRelation?.canManage || activeRelation.status === 'deactivated'} /></label>{activeRelation?.canManage && activeRelation.status !== 'deactivated' ? <div className="impact-review-actions"><button disabled={review.isPending} onClick={() => review.mutate('暂不判断')}>暂不判断</button><button disabled={review.isPending} onClick={() => review.mutate('驳回')}>驳回</button><button disabled={review.isPending} onClick={() => review.mutate('确认')} className="primary">确认影响</button></div> : <p className="muted">当前账户没有此关联的确认权限，或该关联已经解除。</p>}<InlineError error={review.error} />{result && <div className="impact-decision-result" role="status"><strong>✓ {result}</strong></div>}</section><section className="impact-after-confirm"><h2>确认后将发生</h2><ol><li><b>1</b><span>关系状态与审计记录更新</span></li><li><b>2</b><span>受影响逻辑重新计算状态建议</span></li><li><b>3</b><span>工作台待确认任务同步刷新</span></li><li><b>4</b><span>后续可进入复盘与版本演变</span></li></ol></section></aside></main></div>
}

export function MacroStrategyPage() {
  const [activeView, setActiveView] = useState('环境总览')
  const macroIndicators = [
    ['制造业 PMI', '50.4', '+0.3', '边际改善', '05-31'], ['社融存量增速', '8.7%', '+0.2pp', '信用企稳', '06-13'], ['M1 同比', '-1.4%', '+0.3pp', '仍待修复', '06-13'], ['10Y国债收益率', '1.72%', '-4bp', '流动性宽松', '实时'], ['PPI 同比', '-2.5%', '+0.3pp', '低位回升', '06-09'], ['美元兑人民币', '7.21', '+0.4%', '高位震荡', '实时'],
  ]
  const sectors = [['芯片半导体', '超配', '国产替代、库存周期改善', 'positive'], ['创新医药', '超配', '流动性支撑、产品兑现', 'positive'], ['新能源汽车', '标配', '新品周期与价格竞争并存', 'neutral'], ['地产产业链', '低配', '需求恢复仍偏弱', 'negative']]
  const transmissions = [
    { tag: '政策', time: '09:30', title: '汽车以旧换新补贴范围进一步扩大', path: ['政策加码', '汽车需求改善', '新能源汽车', '吉利汽车'], impact: '支持', note: '建议关联“新能源产品周期”逻辑，等待研究员确认。' },
    { tag: '海外', time: '08:45', title: '美债收益率回落，成长资产估值压力边际缓解', path: ['海外利率下降', '风险偏好改善', '创新药/半导体', '行业配置'], impact: '支持', note: '宏观影响方向明确，行业影响强度仍需复核。' },
    { tag: '汇率', time: '昨天', title: '人民币汇率高位震荡，出口企业影响出现分化', path: ['人民币偏弱', '出口收入换算', '原料成本上升', '公司差异'], impact: '中性', note: '同时存在支持和冲突路径，不自动关联公司逻辑。' },
  ]
  return <div className="macro-strategy-page">
    <header className="macro-page-header"><div><span>MACRO & MARKET STRATEGY</span><h1>宏观与策略</h1><p>统一维护市场环境判断，并查看宏观变化如何向行业与公司研究传导。</p></div><div><button>查看历史版本</button><button className="primary">更新策略观点</button></div></header>
    <nav className="macro-view-tabs" aria-label="宏观策略页面导航">{['环境总览', '宏观指标', '行业配置', '传导事件'].map((item) => <button key={item} className={activeView === item ? 'active' : ''} onClick={() => setActiveView(item)}>{item}</button>)}<span>数据更新时间：今天 10:30</span></nav>
    <main className="macro-layout">
      <section className="macro-regime"><div className="macro-regime-copy"><span>当前市场环境</span><h2>弱复苏 <i>×</i> 宽流动性 <i>×</i> 成长占优</h2><p>国内增长边际企稳，流动性维持偏宽松，成长资产具备估值支撑；但盈利兑现不足仍限制整体风险偏好上行。</p><footer><b>策略立场：中性偏积极</b><span>负责人：策略研究组</span><span>置信状态：较高</span></footer></div><div className="macro-regime-dials">{[['国内增长','弱复苏','up'],['流动性','偏宽松','up'],['通胀','低位回升','flat'],['海外利率','高位震荡','risk'],['风险偏好','中性','flat'],['政策力度','增强','up']].map(([name,value,tone]) => <article key={name}><span>{name}</span><strong className={tone}>{value}</strong><i><b className={tone} /></i></article>)}</div></section>
      <div className="macro-primary-column"><section className="macro-indicators"><header><div><span>01 / DATA PULSE</span><h2>核心宏观变量</h2></div><button>查看全部指标 ›</button></header><div className="macro-indicator-head"><span>指标</span><span>最新值</span><span>较前值</span><span>当前判断</span><span>下次更新</span></div>{macroIndicators.map(([name,value,delta,state,next]) => <div className="macro-indicator-row" key={name}><strong>{name}</strong><b>{value}</b><em className={delta.startsWith('+') ? 'up' : ''}>{delta}</em><span>{state}</span><time>{next}</time></div>)}</section><section className="macro-transmission"><header><div><span>03 / TRANSMISSION</span><h2>最新事件与研究传导</h2></div><button>查看全部事件 ›</button></header>{transmissions.map((item) => <article key={item.title}><div className="transmission-time"><b>{item.tag}</b><time>{item.time}</time></div><div className="transmission-content"><h3>{item.title}</h3><div className="transmission-path">{item.path.map((node,index) => <span key={node}>{node}{index < item.path.length - 1 && <i>→</i>}</span>)}</div><p>{item.note}</p></div><em className={item.impact === '支持' ? 'support' : 'neutral'}>{item.impact}</em><button>查看详情</button></article>)}</section></div>
      <div className="macro-secondary-column"><section className="macro-allocation"><header><div><span>02 / ALLOCATION</span><h2>行业配置观点</h2></div><button>编辑配置</button></header><div className="market-style"><h3>市场风格</h3>{[['成长',78],['价值',58],['大盘',61],['小盘',43],['高股息',72]].map(([name,value]) => <div key={name}><span>{name}</span><i><b style={{width:`${value}%`}} /></i><strong>{value}</strong></div>)}</div><div className="sector-allocation"><h3>行业配置</h3>{sectors.map(([name,rating,driver,tone]) => <article key={name}><i className={tone}>{rating}</i><div><strong>{name}</strong><span>{driver}</span></div><button>查看行业 ›</button></article>)}</div></section><aside className="macro-side"><section><header><h2>需要关注</h2><b>3</b></header><article><i className="risk">!</i><div><strong>海外利率拐点仍不明确</strong><span>影响成长估值与风险偏好</span></div></article><article><i>?</i><div><strong>M1修复力度弱于预期</strong><span>企业活跃度仍需观察</span></div></article><article><i className="notice">↗</i><div><strong>政策支持力度增强</strong><span>汽车、设备更新方向受益</span></div></article></section><section><header><h2>近期数据日历</h2></header><ol><li><time>05-31</time><span>5月制造业PMI</span><b>高</b></li><li><time>06-09</time><span>5月CPI / PPI</span><b>高</b></li><li><time>06-13</time><span>社融与货币数据</span><b>高</b></li></ol></section></aside></div>
    </main>
  </div>
}

type CoverageCompany = { id: string; securityId: string; name: string; code: string; industry?: string; market: string; owner: string; thesisCount: number; status: '正常覆盖' | '待建档' | '暂停覆盖'; updated: string }
type CoverageIndustry = { id: string; name: string; code: string; color: string; description: string; companies: CoverageCompany[] }

const coverageColors = ['#1473e6', '#16a173', '#7558c7', '#df8b2c', '#4f718e']

function coverageMarket(ticker: string | undefined) {
  const value = ticker?.toUpperCase() ?? ''
  if (value.endsWith('.HK')) return '港股'
  if (value.endsWith('.US')) return '美股'
  if (value.endsWith('.SH') || value.endsWith('.SZ') || /^\d{6}$/.test(value)) return 'A股'
  return '未标注'
}

function toCoverageIndustries(groups: Awaited<ReturnType<typeof getCoverageUniverse>>): CoverageIndustry[] {
  return groups.map((group, index) => ({
    id: group.sectorId || `industry-${group.name}`,
    name: group.name,
    code: group.code || (group.name === '未分类' ? 'UNCLASSIFIED' : `IND-${String(index + 1).padStart(2, '0')}`),
    color: coverageColors[index % coverageColors.length],
    description: group.description || '研究板块；公司下方显示正式行业分类',
    companies: group.companies.map((company) => ({
      id: company.coverageCompanyId || company.securityId,
      securityId: company.securityId,
      name: company.name,
      code: company.ticker || company.securityId,
      industry: company.industry,
      market: company.market || coverageMarket(company.ticker),
      owner: company.owner || '待分配',
      thesisCount: company.thesisCount,
      status: (company.status as CoverageCompany['status']) || (company.thesisId ? '正常覆盖' : '待建档'),
      updated: company.updatedAt ? new Date(company.updatedAt).toLocaleDateString('zh-CN') : '尚未建立逻辑',
    })),
  }))
}

export function CoverageManagementPage({ onCreate }: { onCreate?: (security?: Security) => void } = {}) {
  const [industries, setIndustries] = useState<CoverageIndustry[]>([])
  const [activeIndustryId, setActiveIndustryId] = useState('')
  const [sectorQuery, setSectorQuery] = useState('')
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<'全部' | CoverageCompany['status']>('全部')
  const [dialog, setDialog] = useState<'industry' | 'sector-edit' | 'company' | null>(null)
  const [toast, setToast] = useState('')
  const coverage = useQuery({ queryKey: ['coverage-universe', sectorQuery], queryFn: () => getCoverageUniverse(sectorQuery), staleTime: 30_000 })
  const qc = useQueryClient()
  useEffect(() => {
    if (!coverage.data) return
    const next = toCoverageIndustries(coverage.data)
    setIndustries(next)
    setActiveIndustryId((current) => next.some((item) => item.id === current) ? current : next[0]?.id ?? '')
  }, [coverage.data])
  const industry = industries.find((item) => item.id === activeIndustryId) ?? industries[0]
  const currentIndustry: CoverageIndustry = industry ?? { id: '', name: '暂无板块', code: '-', color: '#4f718e', description: '请先新增研究板块', companies: [] }
  const createSectorMutation = useMutation({
    mutationFn: createCoverageSector,
    onSuccess: (created) => { setActiveIndustryId(created.sectorId || ''); setDialog(null); void qc.invalidateQueries({ queryKey: ['coverage-universe'] }); showToast(`已添加板块：${created.name}`) },
  })
  const createCompanyMutation = useMutation({
    mutationFn: (payload: { sectorId: string; securityId?: string; name?: string; industry?: string; market?: string; owner?: string }) => createCoverageCompany(payload.sectorId, payload),
    onSuccess: (created) => { setDialog(null); void qc.invalidateQueries({ queryKey: ['coverage-universe'] }); void qc.invalidateQueries({ queryKey: ['securities'] }); showToast(`已将${created.name}加入${currentIndustry.name}`) },
  })
  const updateSectorMutation = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => updateCoverageSector(id, { name }),
    onSuccess: (updated) => { setDialog(null); void qc.invalidateQueries({ queryKey: ['coverage-universe'] }); showToast(`已将板块更名为：${updated.name}`) },
  })
  const updateCompanyMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => updateCoverageCompany(id, { status }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['coverage-universe'] }); void qc.invalidateQueries({ queryKey: ['maintained-coverage'] }); showToast('覆盖状态已更新') },
  })
  if (coverage.isLoading) return <LoadingState text="正在加载行业与公司数据…" />
  if (coverage.error) return <ErrorState error={coverage.error} />
  const companies = currentIndustry.companies.filter((item) => (statusFilter === '全部' || item.status === statusFilter) && `${item.name}${item.code}${item.owner}`.toLowerCase().includes(query.trim().toLowerCase()))
  const totalCompanies = industries.reduce((sum, item) => sum + item.companies.length, 0)
  const totalTheses = industries.reduce((sum, item) => sum + item.companies.reduce((companySum, company) => companySum + company.thesisCount, 0), 0)
  const showToast = (message: string) => { setToast(message); window.setTimeout(() => setToast(''), 2200) }
  const addIndustry = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const data = new FormData(event.currentTarget); createSectorMutation.mutate({ name: String(data.get('name') ?? '').trim(), code: String(data.get('code') || '').trim() || undefined, description: String(data.get('description') || '').trim() || undefined }) }
  const editIndustry = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (!currentIndustry.id) return; const data = new FormData(event.currentTarget); updateSectorMutation.mutate({ id: currentIndustry.id, name: String(data.get('name') ?? '').trim() }) }
  const addCompany = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); if (!currentIndustry.id) return; const data = new FormData(event.currentTarget); createCompanyMutation.mutate({ sectorId: currentIndustry.id, securityId: String(data.get('code') || '').trim() || undefined, name: String(data.get('name') || '').trim() || undefined, industry: String(data.get('industry') || '').trim() || undefined, market: String(data.get('market') || '').trim() || undefined, owner: String(data.get('owner') || '').trim() || undefined }) }
  const toggleCoverage = (company: CoverageCompany) => { if (!company.id.startsWith('COV-')) return; updateCompanyMutation.mutate({ id: company.id, status: company.status === '暂停覆盖' ? '正常覆盖' : '暂停覆盖' }) }
  return <div className="coverage-management-page">
    <header className="coverage-management-header"><div><span>研究覆盖管理 / COVERAGE UNIVERSE</span><h1>板块与公司管理</h1><p>维护研究团队的研究板块、公司覆盖范围与负责人。公司下方保留正式行业分类，新增对象后可继续建立投资逻辑和指标体系。</p></div><div className="coverage-header-actions"><button onClick={() => setDialog('industry')}>＋ 新增板块</button></div></header>
    <section className="coverage-summary" aria-label="覆盖概况"><div><span>研究板块</span><strong>{industries.length}</strong><small>个活跃板块</small></div><div><span>覆盖公司</span><strong>{totalCompanies}</strong><small>家公司</small></div><div><span>活跃投资逻辑</span><strong>{totalTheses}</strong><small>条逻辑</small></div><div><span>待完善档案</span><strong>{industries.flatMap((item) => item.companies).filter((item) => item.status === '待建档').length}</strong><small>需要处理</small></div><div className="coverage-governance"><b>覆盖治理</b><span>板块、公司和研究逻辑为三级独立对象</span><em>最后同步：今天 10:30</em></div></section>
    <main className="coverage-management-grid">
      <aside className="industry-manager"><header><div><span>01</span><h2>板块目录</h2></div><button onClick={() => setDialog('industry')} aria-label="新增板块">＋</button></header><label className="industry-search"><span>⌕</span><input value={sectorQuery} onChange={(event) => setSectorQuery(event.target.value)} placeholder="搜索板块" aria-label="搜索板块" /></label><div className="industry-list">{industries.map((item) => <button key={item.id} className={activeIndustryId === item.id ? 'active' : ''} onClick={() => { setActiveIndustryId(item.id); setQuery(''); setStatusFilter('全部') }}><i style={{ background: item.color }}>{item.name.slice(0,1)}</i><span><strong>{item.name}</strong><small>{item.description}</small></span><b>{item.companies.length}</b></button>)}</div>{!industries.length && <div className="coverage-empty"><strong>没有匹配的板块</strong><span>请调整搜索条件，或新建研究板块。</span></div>}<footer><span>归档板块 <b>0</b></span><button>查看归档 ›</button></footer></aside>
      <section className="company-manager"><header className="company-manager-title"><div><span>02 / {currentIndustry.code}</span><h2>{currentIndustry.name}</h2><p>{currentIndustry.description} · 当前覆盖 {currentIndustry.companies.length} 家公司</p></div><div><button onClick={() => currentIndustry.id && setDialog('sector-edit')} disabled={!currentIndustry.id}>板块设置</button><button className="primary" onClick={() => currentIndustry.id && setDialog('company')} disabled={!currentIndustry.id}>＋ 添加公司</button></div></header><div className="company-manager-toolbar"><label><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索公司名称、代码或负责人" aria-label="搜索公司" /></label><div className="company-filters">{(['全部','正常覆盖','待建档','暂停覆盖'] as const).map((status) => <button key={status} className={statusFilter === status ? 'active' : ''} onClick={() => setStatusFilter(status)}>{status}{status === '全部' ? ` ${currentIndustry.companies.length}` : ''}</button>)}</div><button>筛选⌄</button></div>
        <div className="coverage-company-table" role="table" aria-label={`${currentIndustry.name}公司列表`}><div className="coverage-company-head" role="row"><span>公司</span><span>市场</span><span>研究负责人</span><span>投资逻辑</span><span>覆盖状态</span><span>最近更新</span><span>操作</span></div>{companies.map((company) => <article className="coverage-company-row" role="row" key={company.id}><div className="coverage-company-name"><i>{company.name.slice(0,1)}</i><span><strong>{company.name}</strong><small>{company.code}</small><small className="company-industry-caption" title={company.industry || '行业分类待补充'}>{company.industry || '行业分类待补充'}</small></span></div><span>{company.market}</span><div className="coverage-owner"><i>{company.owner.slice(0,1)}</i><span>{company.owner}</span></div><b className={company.thesisCount ? '' : 'empty'}>{company.thesisCount} 条</b><em className={`coverage-status status-${company.status}`}>{company.status}</em><time>{company.updated}</time><div className="coverage-row-actions">{company.thesisCount > 0 ? <NavLink to={`/companies/${encodeURIComponent(company.securityId)}`}>进入研究</NavLink> : <button onClick={() => onCreate?.({ securityId: company.securityId, name: company.name, ticker: company.code, industry: company.industry })}>新建逻辑</button>}<button className="coverage-pause-button" disabled={updateCompanyMutation.isPending} onClick={() => toggleCoverage(company)}>{company.status === '暂停覆盖' ? '恢复覆盖' : '暂停覆盖'}</button></div></article>)}</div>
        {!companies.length && <div className="coverage-empty"><strong>没有匹配的公司</strong><span>调整搜索条件，或将新公司添加到当前板块。</span><button onClick={() => currentIndustry.id && setDialog('company')} disabled={!currentIndustry.id}>＋ 添加公司</button></div>}
        <footer className="company-manager-footer"><span>显示 {companies.length} / {currentIndustry.companies.length} 家公司</span><div><button disabled>‹</button><b>1</b><button disabled>›</button></div></footer>
      </section>
    </main>
    {dialog && <div className="coverage-dialog-backdrop" role="presentation" onMouseDown={() => setDialog(null)}><section className="coverage-dialog" role="dialog" aria-modal="true" aria-labelledby="coverage-dialog-title" onMouseDown={(event) => event.stopPropagation()}><header><span>{dialog === 'company' ? 'COMPANY SETUP' : 'SECTOR SETUP'}</span><h2 id="coverage-dialog-title">{dialog === 'industry' ? '新增研究板块' : dialog === 'sector-edit' ? '修改板块名称' : `添加公司到“${currentIndustry.name}”`}</h2><p>{dialog === 'industry' ? '建立研究板块后，可继续添加覆盖公司和行业级研究资料。' : dialog === 'sector-edit' ? '更名后会立即保存到板块目录并更新前端展示。' : '这里只建立公司档案；代码和名称填写一个即可，系统会优先从市场主数据补全并判断上市市场。添加后投资逻辑数量默认为 0。'}</p><button onClick={() => setDialog(null)} aria-label="关闭">×</button></header><form onSubmit={dialog === 'industry' ? addIndustry : dialog === 'sector-edit' ? editIndustry : addCompany}>{dialog === 'industry' ? <><label>板块名称<input name="name" placeholder="例如：消费电子" required autoFocus /></label><label>板块代码<input name="code" placeholder="例如：ELEC.CN" /></label><label>板块说明<textarea name="description" placeholder="简要描述板块覆盖范围" /></label></> : dialog === 'sector-edit' ? <label>板块名称<input name="name" defaultValue={currentIndustry.name} required autoFocus /></label> : <><div className="coverage-form-two"><label>公司名称<input name="name" placeholder="例如：理想汽车" autoFocus /></label><label>证券代码<input name="code" placeholder="例如：2015.HK" /></label></div><div className="coverage-form-two"><label>所属行业<input name="industry" placeholder="可从证券主数据补全" /></label><label>上市市场<select name="market"><option value="">自动识别</option><option>A股</option><option>港股</option><option>美股</option><option>未上市</option></select></label></div><label>研究负责人<input name="owner" placeholder="输入姓名" /></label></>}<div className="coverage-dialog-actions"><button type="button" onClick={() => setDialog(null)}>取消</button><button type="submit" className="primary" disabled={createSectorMutation.isPending || updateSectorMutation.isPending || createCompanyMutation.isPending}>{dialog === 'industry' ? (createSectorMutation.isPending ? '创建中…' : '创建板块') : dialog === 'sector-edit' ? (updateSectorMutation.isPending ? '保存中…' : '保存名称') : (createCompanyMutation.isPending ? '添加中…' : '添加公司')}</button></div><InlineError error={createSectorMutation.error ?? updateSectorMutation.error ?? createCompanyMutation.error} /></form></section></div>}
    {toast && <div className="coverage-toast" role="status">✓ {toast}</div>}
  </div>
}

const companyTheses = [
  { id: 'product', title: '新能源产品周期', horizon: '未来12个月', direction: '正向', health: '证据增强', confidence: 78, summary: '我们预计吉利汽车将受益于新能源产品周期上行，推动销量与结构改善，并带动盈利能力逐步提升。' },
  { id: 'overseas', title: '海外增长', horizon: '未来1—2年', direction: '正向', health: '证据中性', confidence: 65, summary: '海外渠道扩张与重点市场新品投放有望支撑出口增长，但贸易政策与本地化能力仍需持续验证。' },
  { id: 'valuation', title: '盈利与估值修复', horizon: '未来6—12个月', direction: '中性', health: '证据不足', confidence: 50, summary: '费用效率和产品结构改善具备修复空间，但价格竞争使盈利兑现节奏仍存在不确定性。' },
] as const

const thesisResearch = {
  product: {
    hypotheses: [
      { id: 'H1', title: '新车型周期推动新能源产品结构持续升级', state: '支持', tone: 'support' },
      { id: 'H2', title: '新能源销量加速提升，并带动规模效应与盈利改善', state: '冲突', tone: 'conflict' },
      { id: 'H3', title: '成本持续优化，费用结构改善带动利润率修复', state: '待验证', tone: 'pending' },
    ],
    metrics: {
      H1: [['新能源车型占比', '42.1%', '+5.8pp', '支持'], ['重点车型订单兑现率', '91%', '+7pp', '支持'], ['高配车型销售占比', '36.4%', '+3.2pp', '支持']],
      H2: [['终端折扣率（整体）', '8.6%', '+1.2pp', '冲突'], ['新能源销量（单月）', '8.1万', '+18.3%', '支持'], ['单车收入（YoY）', '-2.4%', '-1.1pp', '冲突']],
      H3: [['单车制造成本', '10.2万', '-4.6%', '支持'], ['销售费用率', '5.8%', '+0.4pp', '冲突'], ['综合毛利率', '15.3%', '+0.8pp', '待验证']],
    },
    evidence: {
      H1: [['支持', '极氪品牌结构升级持续，高配车型占比提升', '公司官网 · 2025-05-07'], ['支持', '银河系列新车型首月订单超过内部计划', '公司公告 · 2025-05-12'], ['待验证', '新车型交付爬坡速度仍需观察', '渠道调研 · 2025-05-15']],
      H2: [['支持', '4月新能源销量8.1万台，环比+18%，同比+78%', '吉利汽车公告 · 2025-05-12'], ['冲突', '4月终端折扣率上升至8.6%，高于预期', '渠道调研纪要 · 2025-05-09'], ['支持', '极氪品牌结构升级持续，带动均价环比提升', '公司官网 · 2025-05-07']],
      H3: [['支持', '平台化采购带动电池与零部件成本下降', '供应链调研 · 2025-05-11'], ['冲突', '新品上市营销投入使销售费用率阶段性上行', '一季报 · 2025-04-30'], ['待验证', '规模效应向毛利率传导仍需二季度数据确认', '研究员判断 · 2025-05-18']],
    },
  },
  overseas: null,
  valuation: null,
} as const

type ResearchMetricPoint = { period: string; value: string }
type ResearchMetricRow = [string, string, string, string, ResearchMetricPoint[]?]
type ResearchEvidenceRow = [string, string, string]
type ResearchHypothesisView = { id: string; title: string; state: string; tone: 'support' | 'conflict' | 'mixed' | 'neutral' | 'pending' }
type ResearchView = { hypotheses: ResearchHypothesisView[]; metrics: Record<string, ResearchMetricRow[]>; evidence: Record<string, ResearchEvidenceRow[]> }
type CompanyThesisView = { id: string; title: string; horizon: string; direction: string; health: string; confidence?: number; summary: string; record?: ThesisDetail }

function normalizeResearchView(value: { hypotheses: readonly { id: string; title: string; state: string; tone: string }[]; metrics: Readonly<Record<string, ReadonlyArray<ReadonlyArray<string>>>>; evidence: Readonly<Record<string, ReadonlyArray<ReadonlyArray<string>>>> }): ResearchView {
  return {
    hypotheses: value.hypotheses.map((item) => ({ ...item, tone: item.tone === 'support' || item.tone === 'conflict' ? item.tone : 'pending' })),
    metrics: Object.fromEntries(Object.entries(value.metrics).map(([key, rows]) => [key, rows.map((row) => [String(row[0]), String(row[1]), String(row[2]), String(row[3])] as ResearchMetricRow)])),
    evidence: Object.fromEntries(Object.entries(value.evidence).map(([key, rows]) => [key, rows.map((row) => [String(row[0]), String(row[1]), String(row[2])] as ResearchEvidenceRow)])),
  }
}

function metricRowFromTrend(item: Trend, history: ResearchMetricPoint[] = item.points.map((point) => ({ period: point.period, value: point.value }))): ResearchMetricRow {
  const latest = history.at(-1)?.value
  const previous = history.at(-2)?.value
  const latestNumber = latest == null ? Number.NaN : Number(latest)
  const previousNumber = previous == null ? Number.NaN : Number(previous)
  const delta = Number.isFinite(latestNumber) && Number.isFinite(previousNumber) && previousNumber !== 0
    ? `${latestNumber - previousNumber >= 0 ? '+' : ''}${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(((latestNumber - previousNumber) / Math.abs(previousNumber)) * 100)}%`
    : '—'
  const state = item.verdict?.includes('冲突') ? '冲突' : item.verdict?.includes('支持') ? '支持' : '待验证'
  return [item.metricName || item.metricId, formatResearchMetricValue(latest), delta, state, history]
}

function formatResearchMetricValue(value?: string) {
  if (value == null || value.trim() === '') return '—'
  const numeric = Number(value.replaceAll(',', ''))
  return Number.isFinite(numeric)
    ? new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(numeric)
    : value
}

function KeyMetricSparkline({ points, state }: { points?: ResearchMetricPoint[]; state: string }) {
  const values = (points ?? []).map((point) => Number(point.value)).filter(Number.isFinite)
  if (values.length < 2) return null
  const min = Math.min(...values), max = Math.max(...values), range = max - min || 1
  const polyline = values.map((value, index) => `${(index / Math.max(values.length - 1, 1)) * 110},${28 - ((value - min) / range) * 23}`).join(' ')
  return <svg className={`key-metric-sparkline ${state === '支持' ? 'support' : state === '冲突' ? 'conflict' : 'pending'}`} viewBox="0 0 110 32" preserveAspectRatio="none" aria-label="近期波动"><polyline points={polyline} /></svg>
}

function formatCompanyNumber(value?: string) {
  if (value == null || value.trim() === '') return '—'
  const numeric = Number(value.replaceAll(',', ''))
  return Number.isFinite(numeric) ? numeric.toFixed(2) : value
}

function dynamicThesisView(record: ThesisDetail): CompanyThesisView {
  return {
    id: record.thesisId,
    title: record.title,
    horizon: record.horizonEndOn ? `截至 ${record.horizonEndOn}` : '观察期未设置',
    direction: record.direction,
    health: record.status === '草稿' ? '待验证' : record.status,
    summary: record.coreView,
    record,
  }
}

function companyContextText(item: Record<string, unknown>): string {
  return String(item.statement ?? item.label ?? item.title ?? item.text ?? '').trim()
}

function CompanyCatalystRiskPanel({ thesis, demo }: { thesis?: ThesisDetail; demo: boolean }) {
  const fallbackCatalysts = ['新车型密集上市带动销量结构改善', '海外市场放量与渠道拓展提供增量', '电池成本下降改善产品竞争力']
  const fallbackRisks = ['行业价格战加剧，终端折扣率继续上行', '海外地缘政治、关税及监管政策变化', '原材料价格上涨压缩盈利空间']
  const catalysts = (thesis?.catalystSuggestions ?? []).map(companyContextText).filter(Boolean)
  const risks = (thesis?.riskSuggestions ?? []).map(companyContextText).filter(Boolean)
  const displayedCatalysts = catalysts.length ? catalysts : demo ? fallbackCatalysts : []
  const displayedRisks = risks.length ? risks : demo ? fallbackRisks : []
  const renderItems = (items: string[], original: Array<Record<string, unknown>>) => items.map((text, index) => {
    const item = original[index]
    const source = item && String(item.source_title ?? item.source ?? '').trim()
    return <li key={`${text}-${index}`}><span>{text}</span>{source && <small>{source}</small>}</li>
  })
  return <section><header><h2>催化剂与风险</h2><span className="company-context-note">基于近期公开资料</span></header><h3 className="support-text">催化剂</h3>{displayedCatalysts.length ? <ul>{renderItems(displayedCatalysts, thesis?.catalystSuggestions ?? [])}</ul> : <p className="company-side-state">暂无已生成的公司催化剂。</p>}<h3 className="conflict-text">风险</h3>{displayedRisks.length ? <ul>{renderItems(displayedRisks, thesis?.riskSuggestions ?? [])}</ul> : <p className="company-side-state">暂无已生成的公司风险。</p>}</section>
}

function ResearchAuditDetails({ detail, modelVersion }: { detail?: Record<string, unknown>; modelVersion?: string }) {
  const labels: Record<string, string> = {
    suggested_status: '建议状态', suggested_thesis_status: '建议逻辑状态', suggested_logic_status: '建议逻辑状态', current_status: '当前状态',
    previous_thesis_status: '变更前状态', reason: '原因', reasons: '触发原因', suggestion_reasons: '触发原因', rule_version: '规则版本',
    prompt_version: '提示词版本', ai_status: 'AI 状态', batch_id: '批次 ID', digest_id: '归并 ID',
    suggestion_id: '建议 ID', thesis_id: '逻辑 ID', relation_count: '关联数量', confirmed_count: '已确认', pending_count: '待观察',
    rejected_count: '不纳入', requires_status_decision: '需要人工变更', note: '备注', version: '版本', changed_fields: '变更字段',
  }
  const entries = Object.entries(detail ?? {}).filter(([key]) => key !== 'items' && key !== 'before' && key !== 'after' && key !== 'reasons' && key !== 'suggestion_reasons' && key !== 'suggested_status')
  const valueText = (value: unknown): string => {
    if (Array.isArray(value)) return value.length ? value.map((item) => typeof item === 'object' ? JSON.stringify(item) : String(item)).join('；') : '—'
    if (value && typeof value === 'object') return Object.entries(value as Record<string, unknown>).map(([key, item]) => `${key}: ${String(item)}`).join('；')
    if (typeof value === 'boolean') return value ? '是' : '否'
    return value == null || value === '' ? '—' : String(value)
  }
  const batchItems = Array.isArray(detail?.items) ? detail.items : []
  const reasonValue = detail?.reasons ?? detail?.suggestion_reasons
  const reasons = Array.isArray(reasonValue) ? reasonValue.map((item) => String(item)).join('；') : reasonValue ? String(reasonValue) : ''
  if (!entries.length && !batchItems.length && !modelVersion && !reasons) return null
  return <div className="research-history-detail-inline">{reasons && <div className="research-history-trigger"><dt>触发原因</dt><dd>{reasons}</dd></div>}<div className="research-history-detail-grid">{entries.map(([key, value]) => <div key={key}><dt>{labels[key] ?? key}</dt><dd>{valueText(value)}</dd></div>)}{modelVersion && <div><dt>模型版本</dt><dd>{modelVersion}</dd></div>}{batchItems.length > 0 && <div><dt>批次明细</dt><dd>{batchItems.length} 条</dd></div>}{(detail?.before != null || detail?.after != null) && <div className="research-history-transition"><dt>状态变化</dt><dd>{detail?.before != null ? valueText(detail.before) : '—'} → {detail?.after != null ? valueText(detail.after) : '—'}</dd></div>}</div></div>
}

function groupResearchAuditEntries(entries: AuditItem[]) {
  const groups = new Map<string, AuditItem & { repeatCount: number }>()
  for (const entry of entries) {
    const detail = entry.detail ?? {}
    const reasonValue = detail.reasons ?? detail.suggestion_reasons
    const reasons = Array.isArray(reasonValue) ? reasonValue.map((item) => String(item)).join('；') : String(detail.reason ?? reasonValue ?? '')
    const suggestedStatus = detail.suggested_status ?? detail.suggested_logic_status ?? ''
    const key = [entry.action, formatDate(entry.occurredAt), suggestedStatus, reasons, detail.rule_version ?? ''].join('\u0000')
    const existing = groups.get(key)
    if (existing) existing.repeatCount += 1
    else groups.set(key, { ...entry, repeatCount: 1 })
  }
  return [...groups.values()]
}

function displayHypothesisHealthState(hypothesis: Hypothesis) {
  const state = hypothesis.healthState || hypothesis.status || '待验证'
  return state === '强化' ? '得到加强' : state === '失效条件命中' ? '可能失效' : state === '暂无新增证据' ? '不变' : state
}

function hypothesisHealthTone(state?: string): 'support' | 'conflict' | 'pending' {
  if (!state) return 'pending'
  if (['强化', '得到加强', '支持'].includes(state)) return 'support'
  if (['承压', '分歧', '轻微分歧', '临近失效', '失效条件命中', '可能失效', '风险'].some((item) => state.includes(item))) return 'conflict'
  return 'pending'
}

export function CompanyResearchPage({ onUpload, onCreate }: { onUpload?: (thesisId?: string, securityId?: string) => void; onCreate?: (security?: Security) => void } = {}) {
  const { securityId: routeSecurityId } = useParams()
  const [companyParams, setCompanyParams] = useSearchParams()
  const isDemoGeely = routeSecurityId === 'geely'
  const securityId = isDemoGeely ? '00175' : routeSecurityId ?? ''
  const [companyTab, setCompanyTab] = useState(() => {
    const requested = companyParams.get('tab')
    return ['总览', '投资逻辑', '事件与证据', '指标中心', '资料库', '研究记录'].includes(requested ?? '') ? requested! : '总览'
  })
  const security = useQuery({ queryKey: ['security', securityId], queryFn: () => getSecurity(securityId), enabled: Boolean(securityId) && !isDemoGeely })
  const companyMetrics = useQuery({ queryKey: ['company-metric-center', securityId], queryFn: () => getCompanyMetricCenter(securityId), enabled: Boolean(securityId) && !isDemoGeely, refetchInterval: 60_000 })
  const maintainedTheses = useQuery({ queryKey: ['company-theses', securityId], queryFn: () => listTheses(securityId, false, true), enabled: Boolean(securityId) && !isDemoGeely })
  const keyNodeDocuments = useQuery({
    queryKey: ['company-key-node-documents', securityId],
    queryFn: () => listDataCenterDocuments(new URLSearchParams({ security_id: securityId, sort: 'published_at', direction: 'desc', limit: '5', offset: '0' })),
    enabled: Boolean(securityId) && !isDemoGeely && !['指标中心', '资料库', '研究记录'].includes(companyTab),
    staleTime: 60_000,
  })
  const requestedThesisId = companyParams.get('thesisId') || ''
  const [activeThesis, setActiveThesis] = useState(requestedThesisId || 'product')
  const [activeHypothesis, setActiveHypothesis] = useState('H2')
  const [showEditDialog, setShowEditDialog] = useState(false)
  const [showAddHypothesisDialog, setShowAddHypothesisDialog] = useState(false)
  useEffect(() => {
    if (isDemoGeely) return
    const first = maintainedTheses.data?.[0]
    const requested = maintainedTheses.data?.find((item) => item.thesisId === requestedThesisId)
    if (requested && requested.thesisId !== activeThesis) setActiveThesis(requested.thesisId)
    else if (first && !maintainedTheses.data?.some((item) => item.thesisId === activeThesis)) setActiveThesis(first.thesisId)
  }, [activeThesis, isDemoGeely, maintainedTheses.data, requestedThesisId])
  const activeRecord = maintainedTheses.data?.find((item) => item.thesisId === activeThesis) ?? maintainedTheses.data?.[0]
  useEffect(() => {
    const first = isDemoGeely ? 'H2' : activeRecord?.hypotheses[0]?.hypothesisId
    const ids = isDemoGeely ? ['H1', 'H2', 'H3'] : activeRecord?.hypotheses.map((item) => item.hypothesisId) ?? []
    if (first && !ids.includes(activeHypothesis)) setActiveHypothesis(first)
  }, [activeHypothesis, activeRecord, isDemoGeely])
  const trends = useQuery({ queryKey: ['company-thesis-trends', activeRecord?.thesisId], queryFn: () => getTrends(activeRecord!.thesisId), enabled: Boolean(activeRecord) && !isDemoGeely })
  const evidenceFeed = useQuery({ queryKey: ['company-thesis-evidence', activeRecord?.thesisId], queryFn: () => getThesisEvidenceFeed(activeRecord!.thesisId), enabled: Boolean(activeRecord) && !isDemoGeely })
  const researchAudit = useQuery({ queryKey: ['audit', activeRecord?.thesisId], queryFn: () => getAudit(activeRecord!.thesisId), enabled: Boolean(activeRecord) && !isDemoGeely && companyTab === '研究记录' })
  const visibleResearchAudit = (researchAudit.data ?? []).filter((entry) => entry.action !== '查看')
  const groupedResearchAudit = groupResearchAuditEntries(visibleResearchAudit)
  const staticBaseResearch = activeThesis === 'product' ? thesisResearch.product : {
    hypotheses: activeThesis === 'overseas' ? [
      { id: 'H1', title: '重点海外市场渠道覆盖持续扩大', state: '支持', tone: 'support' },
      { id: 'H2', title: '海外新品供给能够转化为有效销量', state: '待验证', tone: 'pending' },
      { id: 'H3', title: '贸易政策变化不显著影响盈利能力', state: '冲突', tone: 'conflict' },
    ] : [
      { id: 'H1', title: '规模效应带动单车盈利修复', state: '待验证', tone: 'pending' },
      { id: 'H2', title: '市场盈利预期具备上修空间', state: '冲突', tone: 'conflict' },
      { id: 'H3', title: '当前估值已充分反映价格竞争风险', state: '支持', tone: 'support' },
    ],
    metrics: thesisResearch.product.metrics,
    evidence: thesisResearch.product.evidence,
  }
  const staticResearch = normalizeResearchView(staticBaseResearch)
  const dynamicResearch: ResearchView | undefined = activeRecord ? {
    hypotheses: activeRecord.hypotheses.map((item) => {
      const evidenceState = getConfirmedHypothesisEvidenceState(evidenceFeed.data?.items ?? [], item.hypothesisId)
      return {
        id: item.hypothesisId,
        title: item.statement,
        state: item.healthState ? displayHypothesisHealthState(item) : evidenceState.label,
        tone: item.healthState ? hypothesisHealthTone(item.healthState) : evidenceState.tone,
      }
    }),
    metrics: Object.fromEntries(activeRecord.hypotheses.map((item) => [item.hypothesisId, (trends.data ?? []).filter((trend) => trend.hypothesisId === item.hypothesisId && trend.metricId).map((trend) => metricRowFromTrend(trend, companyMetrics.data?.metrics.find((metric) => metric.metricId === trend.metricId)?.observations ?? undefined))])),
    evidence: Object.fromEntries(activeRecord.hypotheses.map((item) => [item.hypothesisId, (evidenceFeed.data?.items ?? []).filter((feed) => feed.hypothesisId === item.hypothesisId).map((feed) => [feed.direction === 'support' ? '支持' : feed.direction === 'conflict' ? '冲突' : '待验证', feed.sourceDocumentTitle, `公开资料 · ${formatDate(feed.disclosedAt)}`] as ResearchEvidenceRow)])),
  } : undefined
  const availableTheses: CompanyThesisView[] = isDemoGeely ? companyTheses.map((item) => ({ ...item })) : (maintainedTheses.data ?? []).map(dynamicThesisView)
  const thesis = availableTheses.find((item) => item.id === activeThesis) ?? availableTheses[0]
  const research = isDemoGeely ? staticResearch : dynamicResearch
  const selected = research?.hypotheses.find((item) => item.id === activeHypothesis) ?? research?.hypotheses[0]
  const selectedHypothesisRecord = activeRecord?.hypotheses.find((item) => item.hypothesisId === selected?.id)
  const metrics = selected ? research?.metrics[selected.id] ?? [] : []
  const evidenceRows = selected ? research?.evidence[selected.id] ?? [] : []
  const evidenceCards: CompanyEvidenceCard[] = isDemoGeely
    ? evidenceRows.filter(([state]) => state !== '待验证').map(([state, summary, source], index) => ({
        documentKey: `${selected?.id ?? 'H'}-${index}-${source}`,
        evidenceId: '', relationId: '', title: source, summary,
        disclosedAt: source.match(/\d{4}-\d{2}-\d{2}/u)?.[0] ?? '', ingestedAt: '', sourceUrl: '',
        direction: state === '支持' ? 'support' : state === '冲突' ? 'conflict' : 'neutral',
        confirmationStatus: 'confirmed', evidenceCount: 1, aiConfidence: 0,
      }))
    : selected
      ? buildCompanyEvidenceCards(evidenceFeed.data?.items ?? [], selected.id)
      : []
  const chooseThesis = (id: string) => {
    setActiveThesis(id)
    setCompanyParams(companyTab === '总览' ? { thesisId: id } : { tab: companyTab, thesisId: id })
    const target = availableTheses.find((item) => item.id === id)
    setActiveHypothesis(target?.record?.hypotheses[0]?.hypothesisId ?? 'H2')
  }
  const displaySecurity = security.data ?? (isDemoGeely ? { securityId: '00175', name: '吉利汽车', ticker: '0175.HK', industry: '汽车' } : undefined)
  const closeMetric = companyMetrics.data?.metrics.find((item) => item.metricId === 'MKT-CLOSE-D')
  const returnMetric = companyMetrics.data?.metrics.find((item) => item.metricId === 'MKT-CHANGE-PCT-D')
  if (!isDemoGeely && (security.isLoading || maintainedTheses.isLoading)) return <LoadingState />
  if (!isDemoGeely && (security.error || maintainedTheses.error)) return <ErrorState error={security.error ?? maintainedTheses.error} />
  return <div className="company-research-page">
    <header className="company-identity">
      <NavLink className="company-back" to="/workbench" aria-label="返回工作台">‹</NavLink><div className="company-emblem">{displaySecurity?.name.slice(0, 1) || '研'}</div><div className="company-name"><span>公司研究 / {displaySecurity?.industry || '待分类'}</span><h1>{displaySecurity?.name || securityId} <small>{displaySecurity?.ticker || securityId}</small></h1></div>
      <div className="company-quote"><span>最新收盘价</span><strong>{formatCompanyNumber(closeMetric?.latestValue)} <small>{closeMetric?.unit || '—'}</small></strong><em>{returnMetric ? `${formatCompanyNumber(returnMetric.latestValue)}%` : '—'}</em></div><div className="company-stat"><span>投资评级</span><strong>{thesis?.record?.investmentRating || thesis?.direction || '待研究员填写'}</strong></div><div className="company-stat"><span>目标价（12个月）</span><strong>{thesis?.record?.targetPrice ? formatCompanyNumber(thesis.record.targetPrice) : '—'}</strong></div><div className="company-stat"><span>分析师</span><strong>{thesis?.record?.owner || '张明'}</strong></div><div className="company-stat"><span>数据更新</span><strong>{companyMetrics.data?.updatedAt || '尚未同步'}</strong></div>
      <div className="company-actions"><button onClick={() => onUpload?.(activeRecord?.thesisId, securityId)}>添加资料</button><button className="primary" onClick={() => { if (activeRecord) { setCompanyTab('总览'); setCompanyParams({}); return } onCreate?.(displaySecurity) }}><span aria-hidden>＋</span>新建逻辑</button></div>
    </header>
    <nav className="company-tabs" aria-label="公司研究导航">{['总览', '投资逻辑', '事件与证据', '指标中心', '资料库', '研究记录'].map((item) => <button className={item === companyTab ? 'active' : ''} key={item} onClick={() => { setCompanyTab(item); setCompanyParams(item === '总览' ? { thesisId: activeThesis } : { tab: item, thesisId: activeThesis }) }}>{item}</button>)}</nav>
    {companyTab === '研究记录'
      ? <main className="company-canvas company-research-history"><section className="research-history-header"><div><span>RESEARCH DECISION LOG</span><h2>研究决策与操作记录</h2><p>按时间还原证据处理、状态建议、正式状态变化与版本演进。</p></div>{activeRecord && <NavLink className="button primary" to={`/retrospective/new?thesisId=${encodeURIComponent(activeRecord.thesisId)}`}>基于记录发起复盘</NavLink>}</section>{isDemoGeely ? <EmptyState title="暂无可用研究记录" description="演示公司未接入数据库审计记录。" /> : !activeRecord ? <EmptyState title="尚未建立投资逻辑" description="建立投资逻辑后，这里会显示对应的研究决策与操作记录。" /> : researchAudit.isLoading ? <LoadingState text="正在加载研究记录…" /> : researchAudit.error ? <ErrorState error={researchAudit.error} /> : groupedResearchAudit.length ? <div className="research-history-list">{groupedResearchAudit.map((entry, index) => <article key={`${entry.action}-${entry.occurredAt}-${index}`}><div className="research-history-card-meta"><strong>{entry.action}</strong><time>{formatDate(entry.occurredAt)}</time><p>{entry.actor}{entry.objectType ? ` · ${entry.objectType}` : ''}</p>{entry.repeatCount > 1 && <small className="research-history-repeat">重复生成 {entry.repeatCount} 次</small>}</div><div className="research-history-card-content"><header><span>记录内容</span>{Boolean(entry.detail?.suggested_status || entry.detail?.suggested_logic_status) && <b className="research-history-status">建议状态：{String(entry.detail?.suggested_status ?? entry.detail?.suggested_logic_status)}</b>}</header><ResearchAuditDetails detail={entry.detail} modelVersion={entry.modelVersion} /></div></article>)}</div> : <EmptyState title="暂无研究操作记录" description="证据确认、状态建议和逻辑版本变更会按时间记录在这里。" />}</main>
      : companyTab === '指标中心'
        ? <CompanyMetricCenterPanel securityId={securityId} />
        : companyTab === '资料库'
          ? <CompanyLibraryPanel securityId={securityId} securityName={displaySecurity?.name || securityId} />
          : <main className="company-canvas">
      {!thesis || !research || !selected ? <EmptyState title="尚未建立投资逻辑" description="该证券已建档，但数据库中暂时没有可展示的投资逻辑。" /> : <>
      <section className="thesis-switcher" aria-label="投资逻辑选择">{availableTheses.map((item) => <button key={item.id} className={activeThesis === item.id ? 'active' : ''} onClick={() => chooseThesis(item.id)} aria-pressed={activeThesis === item.id}><strong>{item.title}</strong><span><i className={`dot ${item.health === '证据不足' ? 'warning' : ''}`} />{item.direction} · {item.health} · {item.confidence == null ? '待计算' : `${item.confidence}%`}</span></button>)}</section>
      <section className="active-thesis-summary"><div><div className="summary-meta"><span>{thesis.horizon}</span><b>{thesis.direction}</b><b>{thesis.health}</b></div><h2>{thesis.summary}</h2></div><div className="confidence-block"><span>逻辑置信度 ⓘ</span><strong>{thesis.confidence == null ? '—' : `${thesis.confidence}%`}</strong><i><b style={{ width: `${thesis.confidence ?? 0}%` }} /></i></div><dl><div><dt>逻辑负责人</dt><dd>{thesis.record?.owner || '张明'}</dd></div><div><dt>最后更新</dt><dd>{thesis.record?.establishedOn || '2025-05-20'}</dd></div></dl><button className="edit-thesis" disabled={!activeRecord} onClick={() => setShowEditDialog(true)}>✎ 编辑逻辑</button></section>
       <div className="company-research-grid"><section className="hypothesis-panel"><header><h2>核心假设</h2><button disabled={!activeRecord || activeRecord.hypotheses.length >= 5} title={activeRecord?.hypotheses.length === 5 ? '一条投资逻辑最多维护 5 条关键假设' : undefined} onClick={() => setShowAddHypothesisDialog(true)}>＋ 添加假设</button></header><div className="hypothesis-list">{research.hypotheses.map((item) => <button key={item.id} className={selected.id === item.id ? 'active' : ''} onClick={() => setActiveHypothesis(item.id)}><div className="hypothesis-card-copy"><span className={isDemoGeely ? 'hypothesis-index' : 'hypothesis-id'}>{item.id}</span><strong>{item.title}</strong></div><em className={item.tone}>{item.state}</em></button>)}</div></section>
      <section className="verification-panel"><header><div><span>当前验证对象</span><h2><span className="hypothesis-id">{selected.id}</span><span>{selected.title}</span></h2></div></header>{selectedHypothesisRecord && <div className={`hypothesis-health-summary ${hypothesisHealthTone(selectedHypothesisRecord.healthState || selectedHypothesisRecord.status)}`}><div><span>最新假设状态</span><strong>{displayHypothesisHealthState(selectedHypothesisRecord)}</strong><p>{selectedHypothesisRecord.healthReason || '尚未经过研究决策批次刷新，仍沿用原始假设状态。'}</p></div><dl><div><dt>已纳入支持</dt><dd>{selectedHypothesisRecord.healthSupportCount ?? 0}</dd></div><div><dt>已纳入冲突</dt><dd>{selectedHypothesisRecord.healthConflictCount ?? 0}</dd></div><div><dt>更新时间</dt><dd>{selectedHypothesisRecord.healthUpdatedAt ? formatDate(selectedHypothesisRecord.healthUpdatedAt) : '待刷新'}</dd></div></dl></div>}<h3>关键指标</h3><div className="metric-table"><div className="metric-table-head"><span>指标</span><span>最新值</span><span>趋势（vs 前值）</span><span>近期波动</span><span>状态</span></div>{metrics.map(([name, value, delta, state, points]) => <div className="metric-table-row" key={name}><strong>{name}</strong><b>{value}</b><em className={state === '支持' ? 'support' : state === '冲突' ? 'conflict' : 'pending'}>{delta}</em><div className="key-metric-wave"><KeyMetricSparkline points={points} state={state} /></div><span className={state === '支持' ? 'support' : state === '冲突' ? 'conflict' : 'pending'}>{state}</span></div>)}</div><h3>已确认资料证据 <small>（{evidenceCards.length} 份资料）</small></h3><div className="company-evidence-list">{!isDemoGeely && evidenceFeed.isLoading && <p className="company-evidence-state">正在读取该假设的已确认资料…</p>}{!isDemoGeely && evidenceFeed.error && <p className="company-evidence-state error">关联资料暂时不可用，请稍后重试。</p>}{evidenceCards.map((card) => { const directionClass = card.direction === 'support' ? 'support' : card.direction === 'conflict' ? 'conflict' : card.direction === 'mixed' ? 'mixed' : 'neutral'; const directionLabel = card.direction === 'mixed' ? '证据分歧' : card.direction === 'neutral' ? '中性' : updateDirectionLabel(card.direction); return <article className={`company-evidence-card ${directionClass}`} key={card.documentKey}><i /><div className="company-evidence-card-body"><div className="company-evidence-meta"><span>资料证据{card.disclosedAt ? ` · ${formatDate(card.disclosedAt)}` : ''}</span><strong className={directionClass}>{directionLabel}</strong></div><h4>{card.title}</h4><p>{card.summary}</p><footer><span>{card.evidenceCount} 条证据</span>{card.aiConfidence > 0 && <span>AI 置信度 {Math.round(card.aiConfidence * 100)}%</span>}<b className={`status-${updateStatusLabel(card.confirmationStatus)}`}>{updateStatusLabel(card.confirmationStatus)}</b></footer></div>{card.evidenceId && <NavLink to={`/radar/${encodeURIComponent(card.evidenceId)}`}>查看证据</NavLink>}</article> })}{!evidenceFeed.isLoading && !evidenceCards.length && <p className="company-evidence-state">该假设暂未关联已确认的资料证据。</p>}</div></section>
        <aside className="company-side-column"><CompanyCatalystRiskPanel thesis={activeRecord} demo={isDemoGeely} /><CompanyRecentKeyNodes documents={keyNodeDocuments.data?.items ?? []} loading={keyNodeDocuments.isLoading} error={keyNodeDocuments.error} demo={isDemoGeely} /></aside>
      </div>
      <section className="company-version"><header><h2>逻辑版本记录</h2><button>查看全部版本⌃</button></header><div><strong>{isDemoGeely ? 'v1.2（当前）' : `v${thesis.record?.version ?? 0}（当前）`}</strong><span>{isDemoGeely ? '下调单车收入预期；更新4月销量与折扣率数据；补充渠道反馈证据' : `数据库记录 · ${thesis.record?.status || '草稿'}`}</span><span>{thesis.record?.owner || '张明'}</span><time>{thesis.record?.establishedOn || '2025-05-20'}</time><b>{thesis.confidence == null ? '—' : `${thesis.confidence}%`}</b><button>查看详情</button></div></section>
      </>}
    </main>}
    {showEditDialog && activeRecord && <EditLogicDialog thesis={activeRecord} onClose={() => setShowEditDialog(false)} />}
    {showAddHypothesisDialog && activeRecord && <AddHypothesisDialog thesis={activeRecord} onClose={() => setShowAddHypothesisDialog(false)} onAdded={(hypothesisId) => { setActiveHypothesis(hypothesisId); setShowAddHypothesisDialog(false) }} />}
  </div>
}

function CompanyRecentKeyNodes({ documents, loading, error, demo }: { documents: DataCenterDocument[]; loading: boolean; error: Error | null; demo: boolean }) {
  const demoNodes = [
    { documentId: 'demo-q1', publishedAt: '2025-05-22', title: '2025年Q1业绩发布' },
    { documentId: 'demo-sales', publishedAt: '2025-06-10', title: '5月销量发布' },
    { documentId: 'demo-strategy', publishedAt: '2025-06-18', title: '证券机构策略会' },
  ]
  const rows = demo ? demoNodes : documents
  return <section className="company-key-nodes"><header><h2>近期关键节点</h2></header>{loading && !demo ? <p className="company-side-state">正在读取该公司的资料节点…</p> : error && !demo ? <p className="company-side-state error">近期节点暂时不可用。</p> : rows.length ? <ol>{rows.map((item) => <li key={item.documentId}><time>{item.publishedAt.slice(0, 10)}</time>{demo ? <span>{item.title}</span> : <NavLink to={`/assets/documents/${encodeURIComponent(item.documentId)}`}>{item.title}</NavLink>}</li>)}</ol> : <p className="company-side-state">该公司暂时没有已入库资料节点。</p>}</section>
}

function CompanyLibraryPanel({ securityId, securityName }: { securityId: string; securityName: string }) {
  const [direction, setDirection] = useState<'asc' | 'desc'>('desc')
  const documents = useQuery({
    queryKey: ['company-library-documents', securityId, direction],
    queryFn: () => listDataCenterDocuments(new URLSearchParams({ security_id: securityId, sort: 'published_at', direction, limit: '100', offset: '0' })),
    staleTime: 60_000,
  })
  return <main className="company-library">
    <header className="company-library-header"><div><span>公司资料库 / COMPANY LIBRARY</span><h2>{securityName}相关资料</h2><p>展示数据库中已关联到 {securityId} 的公告、研报和上传资料。</p></div><div className="company-library-sort" role="group" aria-label="资料时间排序"><small>共 {documents.data?.total ?? 0} 份资料</small><button className={direction === 'desc' ? 'active' : ''} onClick={() => setDirection('desc')}>时间倒序</button><button className={direction === 'asc' ? 'active' : ''} onClick={() => setDirection('asc')}>时间正序</button></div></header>
    {documents.isLoading ? <LoadingState /> : documents.error || !documents.data ? <ErrorState error={documents.error} /> : documents.data.items.length ? <section className="company-library-list">{documents.data.items.map((item) => <CompanyLibraryDocumentCard item={item} securityName={securityName} key={item.documentId} />)}</section> : <EmptyState title="暂无公司资料" description="新增并关联该公司的资料后，会按公开时间显示在这里。" />}
  </main>
}

function CompanyLibraryDocumentCard({ item, securityName }: { item: DataCenterDocument; securityName: string }) {
  const [expanded, setExpanded] = useState(false)
  const sourceName = !item.sourceName.trim() || item.sourceName.trim() === '未登记来源' || item.sourceName.trim() === '来源待补充'
    ? '今日投资新闻 API'
    : item.sourceName
  const content = useQuery({
    queryKey: ['company-library-document-content', item.documentId],
    queryFn: () => getFullDocument(item.documentId),
    enabled: expanded && item.segmentCount > 0,
    staleTime: 5 * 60_000,
  })
  return <article className={`company-library-card ${expanded ? 'expanded' : ''}`}>
    <div className="company-library-date"><time>{item.publishedAt.slice(0, 10)}</time><span>{item.docType || '研究资料'}</span></div>
    <div className="company-library-copy"><div><span>{sourceName}</span><b>{item.contentStatus}</b></div><h3>{item.title}</h3><p>关联证券：{item.securityNames.length ? item.securityNames.join('、') : securityName}</p><footer><span>{item.segmentCount} 个内容片段</span><span>{item.revisionCount} 个版本</span>{item.ingestedAt && <span>入库于 {item.ingestedAt.slice(0, 10)}</span>}</footer></div>
    <div className="company-library-actions"><button aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}>{expanded ? '收起内容' : '展开内容'}<i>{expanded ? '⌃' : '⌄'}</i></button></div>
    {expanded && <div className="company-library-content">{item.segmentCount === 0 ? <p>该资料当前没有可展开的正文片段。</p> : content.isLoading ? <p>正在读取资料正文…</p> : content.error || !content.data ? <p className="error">正文暂时不可用，请稍后重试。</p> : <><header><span>资料具体内容</span><small>{content.data.segmentCount} 个可回查片段</small></header><div>{content.data.segments.map((segment) => <section key={segment.locator}><span>{segment.page ? `第 ${segment.page} 页` : `第 ${segment.ordinal} 段`}</span><p>{segment.content}</p></section>)}</div></>}</div>}
  </article>
}

function AddHypothesisDialog({ thesis, onClose, onAdded }: { thesis: ThesisDetail; onClose: () => void; onAdded: (hypothesisId: string) => void }) {
  const qc = useQueryClient()
  const [statement, setStatement] = useState('')
  const [hypothesisType, setHypothesisType] = useState('盈利')
  const [importance, setImportance] = useState('核心')
  const [observationWindow, setObservationWindow] = useState('')
  const [invalidationRule, setInvalidationRule] = useState('')
  const knownIds = new Set(thesis.hypotheses.map((item) => item.hypothesisId))
  const mutation = useMutation({
    mutationFn: () => createHypothesis(thesis.thesisId, { statement: statement.trim(), hypothesisType, importance, observationWindow: observationWindow.trim(), invalidationRule: invalidationRule.trim() }),
    onSuccess: async (updated) => {
      const created = updated.hypotheses.find((item) => !knownIds.has(item.hypothesisId))
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['company-theses', thesis.securityId] }),
        qc.invalidateQueries({ queryKey: ['theses'] }),
        qc.invalidateQueries({ queryKey: ['thesis', thesis.thesisId] }),
        qc.invalidateQueries({ queryKey: ['audit', thesis.thesisId] }),
      ])
      onAdded(created?.hypothesisId ?? updated.hypotheses.at(-1)?.hypothesisId ?? '')
    },
  })
  return <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}><section className="dialog maintenance-dialog add-hypothesis-dialog" role="dialog" aria-modal="true" aria-labelledby="add-hypothesis-title" onMouseDown={(event) => event.stopPropagation()}><header><div><span className="eyebrow">投资逻辑维护</span><h2 id="add-hypothesis-title">增加核心假设</h2><p>新增内容会写入当前投资逻辑，并生成一条新的版本记录。</p></div><button type="button" aria-label="关闭" onClick={onClose}>×</button></header><form onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><label>假设内容<textarea autoFocus value={statement} onChange={(event) => setStatement(event.target.value)} placeholder="输入一个可验证、可证伪的关键假设" maxLength={2000} required /></label><div className="form-grid two"><label>假设类型<select value={hypothesisType} onChange={(event) => setHypothesisType(event.target.value)}><option>盈利</option><option>增长</option><option>竞争</option><option>估值</option><option>风险</option><option>其他</option></select></label><label>重要程度<select value={importance} onChange={(event) => setImportance(event.target.value)}><option>核心</option><option>辅助</option></select></label><label>观察窗口<input value={observationWindow} onChange={(event) => setObservationWindow(event.target.value)} placeholder="例如：未来 4 个季度" maxLength={128} /></label><label>失效条件<input value={invalidationRule} onChange={(event) => setInvalidationRule(event.target.value)} placeholder="例如：连续两个季度低于阈值" maxLength={2000} /></label></div><InlineError error={mutation.error} /><div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>取消</button><button type="submit" className="button primary" disabled={mutation.isPending || !statement.trim()}>{mutation.isPending ? '正在保存…' : '保存假设'}</button></div></form></section></div>
}

const metricCategories = ['全部指标', '价格与成交量', '技术指标', '财务与运营', '估值指标', '宏观及行业']

function CompanyMetricCenterPanel({ securityId }: { securityId: string }) {
  const qc = useQueryClient()
  const [category, setCategory] = useState('全部指标')
  const [expanded, setExpanded] = useState<string | null>(null)
  const center = useQuery({ queryKey: ['company-metric-center', securityId], queryFn: () => getCompanyMetricCenter(securityId), refetchInterval: 60_000 })
  const refresh = useMutation({ mutationFn: () => refreshCompanyMetrics(securityId), onSuccess: async () => { await qc.invalidateQueries({ queryKey: ['company-metric-center', securityId] }); await qc.refetchQueries({ queryKey: ['company-metric-center', securityId], type: 'active' }) } })
  if (center.isLoading) return <main className="company-metric-center"><LoadingState /></main>
  if (center.error || !center.data) return <main className="company-metric-center"><ErrorState error={center.error} /></main>
  const metrics = category === '全部指标' ? center.data.metrics : center.data.metrics.filter((item) => item.category === category)
  const counts = Object.fromEntries(metricCategories.map((item) => [item, item === '全部指标' ? center.data.metrics.length : center.data.metrics.filter((metric) => metric.category === item).length]))
  return <main className="company-metric-center"><header><div><span>企业量化数据中心</span><h2>指标中心</h2><p>展示该公司全部已入库指标，与投资假设关联相互独立。数据按来源频率增量更新。</p></div><div><small>数据更新至 {center.data.updatedAt || '尚无数据'}</small><button disabled={refresh.isPending} onClick={() => refresh.mutate()}>{refresh.isPending ? '正在更新…' : '更新最新数据'}</button>{refresh.isSuccess && <div className={`metric-refresh-notice ${refresh.data.errors.length ? 'warning' : 'success'}`} role="status"><strong>{refresh.data.errors.length && refresh.data.fetched === 0 ? '指标数据刷新失败' : refresh.data.errors.length ? '主要指标已刷新，部分数据源暂不可用' : '指标数据已刷新'}</strong><span>公开数据源本次获取 {refresh.data.fetched} 条，新增入库 {refresh.data.inserted} 条。</span>{refresh.data.errors.length > 0 && <ul>{refresh.data.errors.map((error, index) => <li key={`${error}-${index}`}>{error}</li>)}</ul>}</div>}<InlineError error={refresh.error} /></div></header><div className="metric-center-layout"><aside>{metricCategories.map((item) => <button className={category === item ? 'active' : ''} onClick={() => setCategory(item)} key={item}><span>{item}</span><b>{counts[item]}</b></button>)}</aside><section className="metric-center-list"><div className="metric-center-head"><span>指标</span><span>频率</span><span>最新值</span><span>趋势（vs 前值）</span><span>近期波动</span><span /></div>{metrics.map((metric) => <CompanyMetricRow metric={metric} expanded={expanded === metric.metricId} onToggle={() => setExpanded(expanded === metric.metricId ? null : metric.metricId)} key={metric.metricId} />)}{!metrics.length && <div className="metric-center-empty">当前分类暂无已入库数据。点击“更新最新数据”后再次查看；数据源不可用时不会生成模拟值。</div>}</section></div></main>
}

function CompanyMetricRow({ metric, expanded, onToggle }: { metric: CompanyMetric; expanded: boolean; onToggle: () => void }) {
  const values = metric.observations.map((item) => Number(item.value)).filter(Number.isFinite)
  const min = Math.min(...values), max = Math.max(...values), range = max - min || 1
  const points = values.map((value, index) => `${(index / Math.max(values.length - 1, 1)) * 110},${28 - ((value - min) / range) * 23}`).join(' ')
  const change = metric.changeRate == null ? null : Number(metric.changeRate)
  const format = (value: string) => new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(Number(value))
  return <article className={`metric-center-row ${expanded ? 'expanded' : ''}`}><button onClick={onToggle} aria-expanded={expanded}><strong>{metric.name}<small>{metric.metricId}</small></strong><span>{metric.frequency}</span><b>{format(metric.latestValue)} <small>{metric.unit}</small></b><em className={change == null ? '' : change >= 0 ? 'up' : 'down'}>{change == null ? '—' : `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`}</em><svg viewBox="0 0 110 32" preserveAspectRatio="none"><polyline points={points} /></svg><i>{expanded ? '︿' : '﹀'}</i></button>{expanded && <div className="metric-center-detail"><div><h3>指标说明</h3><p>{metric.definition}</p><dl><div><dt>数据来源</dt><dd>{metric.sourceId}</dd></div><div><dt>最近期间</dt><dd>{metric.latestPeriod}</dd></div><div><dt>前值</dt><dd>{metric.previousValue == null ? '—' : format(metric.previousValue)}</dd></div><div><dt>更新时间</dt><dd>{metric.latestDate}</dd></div></dl></div><MetricDetailChart metric={metric} /></div>}</article>
}

function MetricDetailChart({ metric }: { metric: CompanyMetric }) {
  const values = metric.observations.map((item) => Number(item.value))
  const min = Math.min(...values), max = Math.max(...values), range = max - min || 1
  const points = values.map((value, index) => `${20 + (index / Math.max(values.length - 1, 1)) * 520},${130 - ((value - min) / range) * 105}`).join(' ')
  return <div className="metric-detail-chart"><svg viewBox="0 0 560 155" preserveAspectRatio="none"><line x1="20" y1="130" x2="540" y2="130" /><polyline points={points} /></svg><div><span>{metric.observations[0]?.period}</span><b>最高 {new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(max)}</b><b>最低 {new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(min)}</b><span>{metric.observations.at(-1)?.period}</span></div></div>
}

type MaintenanceMappingState = {
  key: string
  mappingId?: string
  metricId: string
  metricVersion: string
  metricName: string
  expectedDirection: string
  expectedLower: string
  expectedUpper: string
  invalidationThreshold: string
  invalidationConsecutivePeriods: number
  expectationSource: string
  expanded: boolean
}

type MaintenanceHypothesisState = {
  hypothesisId: string
  statement: string
  hypothesisType: string
  importance: string
  observationWindow: string
  invalidationRule: string
  mappings: MaintenanceMappingState[]
  suggestions: Array<Record<string, unknown>>
}

function toMaintenanceMapping(mapping: NonNullable<ThesisDetail['hypotheses'][number]['mappings']>[number]): MaintenanceMappingState {
  return {
    key: mapping.mappingId,
    mappingId: mapping.mappingId,
    metricId: mapping.metricId,
    metricVersion: mapping.metricVersion,
    metricName: mapping.metricName || mapping.metricId,
    expectedDirection: ['下降', '越低越好', '不高于阈值'].includes(mapping.expectedDirection) ? '下降' : mapping.expectedDirection === '波动' ? '波动' : '上升',
    expectedLower: mapping.expectedLower || '',
    expectedUpper: mapping.expectedUpper || '',
    invalidationThreshold: mapping.invalidationThreshold || '',
    invalidationConsecutivePeriods: mapping.invalidationConsecutivePeriods || 1,
    expectationSource: mapping.expectationSource || '研究员人工确认',
    expanded: false,
  }
}

function EditLogicDialog({ thesis, onClose }: { thesis: ThesisDetail; onClose: () => void }) {
  const qc = useQueryClient()
  const [title, setTitle] = useState(thesis.title)
  const [coreView, setCoreView] = useState(thesis.coreView)
  const [rating, setRating] = useState(thesis.investmentRating || thesis.direction || '观察')
  const [targetPrice, setTargetPrice] = useState(thesis.targetPrice || '')
  const [observationPeriod, setObservationPeriod] = useState(thesis.observationPeriod || '')
  const [horizonEndOn, setHorizonEndOn] = useState(thesis.horizonEndOn || '')
  const [nextReviewAt, setNextReviewAt] = useState(thesis.nextReviewAt || '')
  const [reason, setReason] = useState('研究员维护逻辑')
  const [rows, setRows] = useState<MaintenanceHypothesisState[]>(() => thesis.hypotheses.map((item) => ({
    hypothesisId: item.hypothesisId,
    statement: item.statement,
    hypothesisType: item.hypothesisType,
    importance: item.importance,
    observationWindow: item.observationWindow || '',
    invalidationRule: item.invalidationRule || '',
    mappings: item.mappings.map(toMaintenanceMapping),
    suggestions: item.metricSuggestions,
  })))
  const [recommendingHypothesisIds, setRecommendingHypothesisIds] = useState<Set<string>>(() => new Set())
  const metrics = useQuery({ queryKey: ['metrics', 'maintenance-editor'], queryFn: () => listMetrics(), staleTime: 5 * 60_000 })
  const companyMetrics = useQuery({ queryKey: ['company-metric-center', thesis.securityId], queryFn: () => getCompanyMetricCenter(thesis.securityId), staleTime: 60_000 })
  const updateRow = (hypothesisId: string, patch: Partial<MaintenanceHypothesisState>) => setRows((current) => current.map((row) => row.hypothesisId === hypothesisId ? { ...row, ...patch } : row))
  const updateMapping = (hypothesisId: string, mappingKey: string, patch: Partial<MaintenanceMappingState>) => setRows((current) => current.map((row) => row.hypothesisId === hypothesisId ? { ...row, mappings: row.mappings.map((mapping) => mapping.key === mappingKey ? { ...mapping, ...patch } : mapping) } : row))
  const removeMapping = (hypothesisId: string, mappingKey: string) => setRows((current) => current.map((row) => row.hypothesisId === hypothesisId ? { ...row, mappings: row.mappings.filter((mapping) => mapping.key !== mappingKey) } : row))
  const recommendation = useMutation({
    mutationFn: (hypothesisId: string) => recommendHypothesisMetrics(thesis.thesisId, hypothesisId),
    onMutate: (hypothesisId) => setRecommendingHypothesisIds((current) => new Set(current).add(hypothesisId)),
    onSuccess: (candidate, hypothesisId) => {
      const suggestions = Array.isArray(candidate.payload.recommendations) ? candidate.payload.recommendations as Array<Record<string, unknown>> : []
      updateRow(hypothesisId, { suggestions })
    },
    onSettled: (_candidate, _error, hypothesisId) => setRecommendingHypothesisIds((current) => {
      const next = new Set(current)
      next.delete(hypothesisId)
      return next
    }),
  })
  const adoptSuggestion = (hypothesisId: string, item: Record<string, unknown>) => {
    const metricId = String(item.metric_id ?? '')
    if (!metricId) return
    const threshold = (item.threshold_suggestion ?? {}) as Record<string, unknown>
    const direction = String(item.expected_direction ?? '上升')
    const falling = ['下降', '越低越好', '不高于阈值'].includes(direction)
    const value = threshold.value == null ? '' : String(threshold.value)
    const metric = (metrics.data ?? []).find((entry) => entry.metricId === metricId)
    const mapping: MaintenanceMappingState = {
      key: `new-${hypothesisId}-${metricId}-${Date.now()}`,
      metricId,
      metricVersion: String(item.metric_version ?? metric?.version ?? 'v1.0'),
      metricName: String(item.metric_name ?? metric?.name ?? metricId),
      expectedDirection: falling ? '下降' : direction === '波动' ? '波动' : '上升',
      expectedLower: falling ? '' : value,
      expectedUpper: falling ? value : '',
      invalidationThreshold: '',
      invalidationConsecutivePeriods: 1,
      expectationSource: '人工确认 Agent 候选',
      expanded: true,
    }
    setRows((current) => current.map((row) => row.hypothesisId === hypothesisId ? { ...row, mappings: [...row.mappings, mapping] } : row))
  }
  const adoptCenterMetric = (hypothesisId: string, metric: CompanyMetric) => {
    setRows((current) => current.map((row) => {
      if (row.hypothesisId !== hypothesisId || row.mappings.some((mapping) => mapping.metricId === metric.metricId)) return row
      return { ...row, mappings: [...row.mappings, {
        key: `new-${hypothesisId}-${metric.metricId}-${Date.now()}`,
        metricId: metric.metricId,
        metricVersion: 'v1.0',
        metricName: metric.name,
        expectedDirection: '上升',
        expectedLower: '',
        expectedUpper: '',
        invalidationThreshold: '',
        invalidationConsecutivePeriods: 1,
        expectationSource: '指标中心人工选择',
        expanded: true,
      }] }
    }))
  }
  const save = useMutation({
    mutationFn: () => {
      const mappings = rows.flatMap((row) => row.mappings.map((mapping) => ({
        hypothesisId: row.hypothesisId,
        mappingId: mapping.mappingId?.startsWith('new-') ? undefined : mapping.mappingId,
        metricId: mapping.metricId,
        metricVersion: mapping.metricVersion,
        expectedDirection: mapping.expectedDirection,
        expectedLower: mapping.expectedLower,
        expectedUpper: mapping.expectedUpper,
        invalidationThreshold: mapping.invalidationThreshold,
        invalidationConsecutivePeriods: mapping.invalidationConsecutivePeriods,
        expectationSource: mapping.expectationSource,
      })))
      return updateThesisMaintenance(thesis.thesisId, {
        title, coreView, direction: rating, investmentRating: rating, targetPrice, observationPeriod, horizonEndOn, nextReviewAt, reason,
        hypotheses: rows.map((row) => ({ hypothesisId: row.hypothesisId, statement: row.statement, hypothesisType: row.hypothesisType, importance: row.importance, observationWindow: row.observationWindow, invalidationRule: row.invalidationRule })),
        mappings,
      })
    },
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['company-theses', thesis.securityId] }),
        qc.invalidateQueries({ queryKey: ['theses'] }),
        qc.invalidateQueries({ queryKey: ['thesis', thesis.thesisId] }),
        qc.invalidateQueries({ queryKey: ['audit', thesis.thesisId] }),
        qc.invalidateQueries({ queryKey: ['company-thesis-trends', thesis.thesisId] }),
      ])
      onClose()
    },
  })
  return <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}><section className="dialog maintenance-dialog" role="dialog" aria-modal="true" aria-labelledby="maintenance-title" onMouseDown={(event) => event.stopPropagation()}>
    <span className="eyebrow">逻辑维护 · 版本化保存</span><h2 id="maintenance-title">编辑投资逻辑</h2><p>修改会写入新的逻辑版本并保留审计记录；AI 推荐只作为候选，只有你提交的指标才会进入维护数据。</p>
    <div className="form-grid two"><label>逻辑标题<input value={title} maxLength={40} onChange={(event) => setTitle(event.target.value)} /></label><label>投资评级<select value={rating} onChange={(event) => setRating(event.target.value)}><option>看多</option><option>看空</option><option>观察</option></select></label><label className="revision-core-view">核心观点<textarea value={coreView} maxLength={200} onChange={(event) => setCoreView(event.target.value)} /></label><label>目标价（可选）<input inputMode="decimal" value={targetPrice} onChange={(event) => setTargetPrice(event.target.value)} placeholder="可不填" /></label><label>观察期（可选）<input value={observationPeriod} onChange={(event) => setObservationPeriod(event.target.value)} placeholder="例如：未来 12 个月" /></label><label>逻辑截止日（可选）<input type="date" value={horizonEndOn} onChange={(event) => setHorizonEndOn(event.target.value)} /></label><label>下次复核（可选）<input type="date" value={nextReviewAt} onChange={(event) => setNextReviewAt(event.target.value)} /></label></div>
    <div className="maintenance-hypotheses">{rows.map((row) => {
      const suggestions = row.suggestions.filter((item) => String(item.metric_id ?? ''))
      const suggestionMetricIds = new Set(suggestions.map((item) => String(item.metric_id)))
      const additionalMappings = row.mappings.filter((mapping) => !suggestionMetricIds.has(mapping.metricId))
      return <article className="maintenance-hypothesis" key={row.hypothesisId}>
        <header><strong>{row.hypothesisId}</strong><span>{row.mappings.length} 个关联指标</span><button type="button" className="button secondary" disabled={recommendingHypothesisIds.has(row.hypothesisId)} onClick={() => recommendation.mutate(row.hypothesisId)}>{recommendingHypothesisIds.has(row.hypothesisId) ? '推荐中…' : '重新推荐指标'}</button></header>
        <label>从指标中心添加<select value="" onChange={(event) => { const metric = companyMetrics.data?.metrics.find((item) => item.metricId === event.target.value); if (metric) adoptCenterMetric(row.hypothesisId, metric) }}><option value="">选择已获取指标</option>{companyMetrics.data?.metrics.map((metric) => <option value={metric.metricId} key={metric.metricId}>{metric.name} · {metric.category}</option>)}</select></label>
        <label>投资假设<textarea value={row.statement} onChange={(event) => updateRow(row.hypothesisId, { statement: event.target.value })} /></label>
        <div className="form-grid two"><label>假设类型<select value={row.hypothesisType} onChange={(event) => updateRow(row.hypothesisId, { hypothesisType: event.target.value })}><option>行业</option><option>公司竞争力</option><option>经营</option><option>盈利</option><option>政策</option><option>估值</option><option>其他</option></select></label><label>重要性<select value={row.importance} onChange={(event) => updateRow(row.hypothesisId, { importance: event.target.value })}><option>核心</option><option>辅助</option></select></label><label>观察窗口<input value={row.observationWindow} onChange={(event) => updateRow(row.hypothesisId, { observationWindow: event.target.value })} placeholder="例如：未来 4 个季度" /></label><label>失效条件<textarea value={row.invalidationRule} onChange={(event) => updateRow(row.hypothesisId, { invalidationRule: event.target.value })} /></label></div>
        {suggestions.length > 0 && <section className="maintenance-metric-section"><span>AI 候选指标</span><div className="metric-candidate-list">{suggestions.map((item, index) => {
          const metricId = String(item.metric_id ?? '')
          const mapping = row.mappings.find((candidate) => candidate.metricId === metricId)
          const centerMetric = companyMetrics.data?.metrics.find((metric) => metric.metricId === metricId)
          const observations = Array.isArray(item.observations) ? item.observations as Array<Record<string, unknown>> : centerMetric?.observations
          const unit = String(item.unit ?? centerMetric?.unit ?? '未标注')
          return <MetricEditorCard key={`${metricId}-${index}`} selected={Boolean(mapping)} name={String(item.metric_name ?? centerMetric?.name ?? metricId)} metricId={metricId} meta={`${unit} · ${String(item.observation_frequency ?? centerMetric?.frequency ?? '频率待确认')}`} tag={mapping ? '已加入' : String(item.relation_type ?? 'AI 候选')} description={String(item.rationale ?? centerMetric?.definition ?? 'AI 尚未提供指标说明')} observations={observations} unit={unit} latestPeriod={centerMetric?.latestPeriod} expanded={mapping?.expanded} onToggleSelected={() => mapping ? removeMapping(row.hypothesisId, mapping.key) : adoptSuggestion(row.hypothesisId, item)} onToggleExpanded={() => mapping && updateMapping(row.hypothesisId, mapping.key, { expanded: !mapping.expanded })}>
            {mapping && <div className="metric-config-grid"><label>变化方向<select value={mapping.expectedDirection} onChange={(event) => updateMapping(row.hypothesisId, mapping.key, { expectedDirection: event.target.value })}><option>上升</option><option>下降</option><option>波动</option></select></label><label>下限（可选）<input value={mapping.expectedLower} onChange={(event) => updateMapping(row.hypothesisId, mapping.key, { expectedLower: event.target.value })} /></label><label>上限（可选）<input value={mapping.expectedUpper} onChange={(event) => updateMapping(row.hypothesisId, mapping.key, { expectedUpper: event.target.value })} /></label><label>连续触发期数<input type="number" min="1" max="12" value={mapping.invalidationConsecutivePeriods} onChange={(event) => updateMapping(row.hypothesisId, mapping.key, { invalidationConsecutivePeriods: Number(event.target.value) || 1 })} /></label><label>失效阈值（可选）<input value={mapping.invalidationThreshold} onChange={(event) => updateMapping(row.hypothesisId, mapping.key, { invalidationThreshold: event.target.value })} /></label><label>判断依据<input value={mapping.expectationSource} onChange={(event) => updateMapping(row.hypothesisId, mapping.key, { expectationSource: event.target.value })} /></label><p className="metric-rule-help">连续越出允许区间后，仅生成复核提醒，不自动改变假设或逻辑状态。</p></div>}
          </MetricEditorCard>
        })}</div></section>}
        {additionalMappings.length > 0 && <section className="maintenance-metric-section"><span>从指标中心加入</span><div className="metric-candidate-list">{additionalMappings.map((mapping) => {
          const centerMetric = companyMetrics.data?.metrics.find((item) => item.metricId === mapping.metricId)
          return <MetricEditorCard key={mapping.key} selected name={mapping.metricName} metricId={mapping.metricId} meta={centerMetric ? `${centerMetric.unit} · ${centerMetric.frequency}` : mapping.metricVersion} tag="已关联" description={centerMetric?.definition ?? '已保存的指标关联，当前中心暂无指标说明。'} observations={centerMetric?.observations} unit={centerMetric?.unit} latestPeriod={centerMetric?.latestPeriod} expanded={mapping.expanded} onToggleSelected={() => removeMapping(row.hypothesisId, mapping.key)} onToggleExpanded={() => updateMapping(row.hypothesisId, mapping.key, { expanded: !mapping.expanded })}>
            <div className="metric-config-grid"><label>变化方向<select value={mapping.expectedDirection} onChange={(event) => updateMapping(row.hypothesisId, mapping.key, { expectedDirection: event.target.value })}><option>上升</option><option>下降</option><option>波动</option></select></label><label>下限（可选）<input value={mapping.expectedLower} onChange={(event) => updateMapping(row.hypothesisId, mapping.key, { expectedLower: event.target.value })} /></label><label>上限（可选）<input value={mapping.expectedUpper} onChange={(event) => updateMapping(row.hypothesisId, mapping.key, { expectedUpper: event.target.value })} /></label><label>连续触发期数<input type="number" min="1" max="12" value={mapping.invalidationConsecutivePeriods} onChange={(event) => updateMapping(row.hypothesisId, mapping.key, { invalidationConsecutivePeriods: Number(event.target.value) || 1 })} /></label><label>失效阈值（可选）<input value={mapping.invalidationThreshold} onChange={(event) => updateMapping(row.hypothesisId, mapping.key, { invalidationThreshold: event.target.value })} /></label><label>判断依据<input value={mapping.expectationSource} onChange={(event) => updateMapping(row.hypothesisId, mapping.key, { expectationSource: event.target.value })} /></label><p className="metric-rule-help">连续越出允许区间后，仅生成复核提醒，不自动改变假设或逻辑状态。</p></div>
          </MetricEditorCard>
        })}</div></section>}
      </article>
    })}</div>
    <label>本次修改说明<textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="说明为什么调整逻辑或指标" /></label><InlineError error={save.error ?? recommendation.error ?? metrics.error ?? companyMetrics.error} /><div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>取消</button><button type="button" className="button primary" disabled={save.isPending || !title.trim() || !coreView.trim()} onClick={() => save.mutate()}>{save.isPending ? '保存并生成版本…' : '保存修改'}</button></div>
  </section></div>
}

export function RadarPage() {
  const [params, setParams] = useSearchParams()
  const thesisId = params.get('thesisId') ?? ''
  const status = params.get('status') ?? ''
  const direction = params.get('direction') ?? ''
  const thesis = useQuery({ queryKey: ['thesis', thesisId], queryFn: () => getThesis(thesisId), enabled: Boolean(thesisId) })
  const feed = useQuery({ queryKey: ['radar-evidence', thesisId, status, direction], queryFn: () => getRadarEvidence(thesisId, { status: status || undefined, direction: direction || undefined }), enabled: Boolean(thesisId) })
  if (!thesisId) return <><PageTitle eyebrow="变化监测" title="选择一个投资逻辑" description="变化雷达围绕明确的投资逻辑工作，不再随机选择第一条数据。" /><EmptyState title="尚未选择研究对象" description="请从顶部选择投资逻辑，或从工作台待办进入变化详情。" action={<NavLink className="primary-link inline" to="/workbench">返回工作台</NavLink>} /></>
  if (thesis.isLoading || feed.isLoading) return <LoadingState />
  if (thesis.error || feed.error || !thesis.data || !feed.data) return <ErrorState error={thesis.error ?? feed.error} />
  const updateFilter = (key: string, value: string) => { const next = new URLSearchParams(params); if (value) next.set(key, value); else next.delete(key); setParams(next) }
  return <>
    <PageTitle eyebrow="变化雷达" title={thesis.data.title} description="事件按优先级和披露时间排序，直接呈现事实、影响假设与处置状态。" />
    <div className="filter-bar"><label>确认状态<select value={status} onChange={(event) => updateFilter('status', event.target.value)}><option value="">全部</option><option value="待确认">待确认</option><option value="已确认">已确认</option><option value="已驳回">已驳回</option></select></label><label>影响方向<select value={direction} onChange={(event) => updateFilter('direction', event.target.value)}><option value="">全部</option><option value="支持">支持</option><option value="冲突">冲突</option><option value="中性">中性</option></select></label><span className="filter-count">{feed.data.total} 条研究事件</span></div>
    <div className="evidence-list">{feed.data.items.length ? feed.data.items.map((item) => <EvidenceEventRow item={item} key={`${item.evidenceId}-${item.relationId}`} />) : <EmptyState title="当前筛选没有变化" description="清除筛选条件后查看该逻辑的全部证据。" action={<button className="button secondary" onClick={() => setParams({ thesisId })}>清除筛选</button>} />}</div>
  </>
}

export function ThesisListPage() {
  const query = useQuery({ queryKey: ['theses'], queryFn: () => listTheses() })
  if (query.isLoading) return <LoadingState />
  if (query.error || !query.data) return <ErrorState error={query.error} />
  return <><PageTitle eyebrow="研究覆盖" title="投资逻辑" description="选择一家公司进入统一的投资逻辑维护页面。" /><div className="thesis-grid">{query.data.map((item) => <NavLink className="thesis-card" to={`/companies/${encodeURIComponent(item.securityId)}?thesisId=${encodeURIComponent(item.thesisId)}`} key={item.thesisId}><div><span className="security-code">{item.securityId}</span><span className={`thesis-status thesis-${item.status}`}>{item.status}</span></div><h2>{item.title}</h2><p>{item.coreView}</p><footer><span>负责人：{item.owner}</span><span>进入公司逻辑维护 →</span></footer></NavLink>)}</div></>
}

export function ThesisCompanyRedirect() {
  const { thesisId = '' } = useParams()
  const thesis = useQuery({ queryKey: ['thesis', thesisId], queryFn: () => getThesis(thesisId), enabled: Boolean(thesisId) })
  if (thesis.isLoading) return <LoadingState text="正在打开公司投资逻辑…" />
  if (thesis.error || !thesis.data) return <ErrorState error={thesis.error} />
  return <Navigate replace to={`/companies/${encodeURIComponent(thesis.data.securityId)}?thesisId=${encodeURIComponent(thesis.data.thesisId)}`} />
}

export function ThesisPage() {
  return <ThesisCompanyRedirect />
}

export function LegacyThesisPage() {
  const { thesisId = '' } = useParams()
  const qc = useQueryClient()
  const thesis = useQuery({ queryKey: ['thesis', thesisId], queryFn: () => getThesis(thesisId) })
  const feed = useQuery({ queryKey: ['thesis-evidence-feed', thesisId], queryFn: () => getThesisEvidenceFeed(thesisId) })
  const suggestions = useQuery({ queryKey: ['suggestions', thesisId], queryFn: () => getSuggestions(thesisId) })
  const trends = useQuery({ queryKey: ['trends', thesisId], queryFn: () => getTrends(thesisId) })
  const audit = useQuery({ queryKey: ['audit', thesisId], queryFn: () => getAudit(thesisId) })
  const [decisionReason, setDecisionReason] = useState('')
  const [targetStatus, setTargetStatus] = useState('验证中')
  const decision = useMutation({ mutationFn: (input: { id: number; action: string }) => decideStatus(thesisId, { suggestionId: input.id, action: input.action, reason: decisionReason, targetStatus: input.action === '修改' ? targetStatus : undefined }), onSuccess: () => { qc.invalidateQueries({ queryKey: ['thesis', thesisId] }); qc.invalidateQueries({ queryKey: ['suggestions', thesisId] }); qc.invalidateQueries({ queryKey: ['audit', thesisId] }) } })
  const qualityCheck = useMutation({ mutationFn: () => recheckThesisQuality(thesisId), onSuccess: (updated) => qc.setQueryData(['thesis', thesisId], updated) })
  if (thesis.isLoading || feed.isLoading) return <LoadingState />
  if (thesis.error || feed.error || !thesis.data || !feed.data) return <ErrorState error={thesis.error ?? feed.error} />
  const item = thesis.data
  const evidence = feed.data.items
  const counts = { support: evidence.filter((x) => x.direction === 'support' && x.confirmationStatus === 'confirmed').length, conflict: evidence.filter((x) => x.direction === 'conflict' && x.confirmationStatus === 'confirmed').length, pending: evidence.filter((x) => x.confirmationStatus === 'pending').length }
  const risk = evidence.find((x) => x.priority === 'high')
  const openSuggestion = suggestions.data?.find((x) => !x.humanAction)
  const businessAudit = audit.data?.filter((line) => line.action !== '查看').slice(0, 8) ?? []
  if (item.status === '草稿') {
    return <><PageTitle eyebrow={`${item.securityId} · 草稿`} title={item.title} description={item.coreView} /><DraftQualitySection thesis={item} onCheck={() => qualityCheck.mutate()} checking={qualityCheck.isPending} checked={qualityCheck.isSuccess} error={qualityCheck.error} /><DraftPublishWorkspace thesis={item} /></>
  }
  return <>
    <PageTitle eyebrow={`${item.securityId} · V${item.version}`} title={item.title} description={item.coreView} actions={<><NavLink className="button secondary" to={`/radar?thesisId=${encodeURIComponent(thesisId)}`}>查看变化雷达</NavLink><NavLink className="button secondary" to={`/quant/new?thesisId=${encodeURIComponent(thesisId)}&securityId=${encodeURIComponent(item.securityId)}`}>进入模型验证</NavLink><NavLink className="button primary" to={`/retrospective/new?thesisId=${encodeURIComponent(thesisId)}`}>发起复盘</NavLink></>} />
    <StageBar status={item.status} />
    <section className="logic-overview"><div><span>当前结论</span><strong>{item.direction}</strong><small>{item.status}</small></div><div><span>支持证据</span><strong className="positive">{counts.support}</strong><small>人工已确认</small></div><div><span>冲突证据</span><strong className="negative">{counts.conflict}</strong><small>人工已确认</small></div><div><span>待核验</span><strong>{counts.pending}</strong><small>需要研究员处理</small></div><div><span>下次复核</span><strong className="date-value">{formatDate(item.nextReviewAt)}</strong><small>负责人 {item.owner}</small></div></section>
    {risk && <section className="risk-callout"><div><span className="risk-icon">!</span><div><strong>当前最大风险</strong><p>{risk.sourceDocumentTitle} · 影响“{risk.hypothesisStatement}”</p></div></div><NavLink to={`/radar/${risk.evidenceId}?thesisId=${thesisId}&relationId=${risk.relationId}`}>立即核验 →</NavLink></section>}
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">逻辑链</span><h2>关键假设健康度</h2></div>{item.status === '草稿' && <button className="button secondary" disabled={qualityCheck.isPending} onClick={() => qualityCheck.mutate()}>{qualityCheck.isPending ? '检查中…' : '重新检查假设逻辑'}</button>}</div><div className="hypothesis-grid">{item.hypotheses.map((hypothesis) => { const related = evidence.filter((x) => x.hypothesisId === hypothesis.hypothesisId); const metrics = trends.data?.filter((trend) => trend.hypothesisId === hypothesis.hypothesisId) ?? []; return <article className="hypothesis-card" key={hypothesis.hypothesisId}><div><span className="importance">{hypothesis.importance}</span>{(hypothesis.logicDimension || hypothesis.causalLevel) && <span className="hypothesis-status">{hypothesis.logicDimension || hypothesis.causalLevel}</span>}<span className={`hypothesis-status health-${hypothesisHealthTone(hypothesis.healthState || hypothesis.status)}`}>{displayHypothesisHealthState(hypothesis)}</span></div><h3>{hypothesis.statement}</h3>{hypothesis.healthReason && <p className={`hypothesis-health-note ${hypothesisHealthTone(hypothesis.healthState || hypothesis.status)}`}>{hypothesis.healthReason}<small>支持 {hypothesis.healthSupportCount ?? 0} · 冲突 {hypothesis.healthConflictCount ?? 0}{hypothesis.healthUpdatedAt ? ` · ${formatDate(hypothesis.healthUpdatedAt)}` : ''}</small></p>}{hypothesis.qualityWarning && <p className="warning-note">{hypothesis.qualityWarning}</p>}<div className="hypothesis-metrics"><strong>验证指标</strong>{metrics.length ? metrics.map((metric) => <div key={`${metric.hypothesisId}-${metric.metricId}`}><span>{metric.metricName || metric.metricId}（{metric.metricId}）</span>{metric.points.length > 0 && <MiniHistoryChart observations={metric.points.map((point) => ({ period: point.period, value: point.value }))} unit={metric.unit} />}{metric.note && <small>{metric.note}</small>}</div>) : <span>尚未配置指标</span>}</div><footer><span className="positive">支持 {related.filter((x) => x.direction === 'support' && x.confirmationStatus === 'confirmed').length}</span><span className="negative">冲突 {related.filter((x) => x.direction === 'conflict' && x.confirmationStatus === 'confirmed').length}</span><span>待确认 {related.filter((x) => x.confirmationStatus === 'pending').length}</span></footer></article> })}</div></section>
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">证据链</span><h2>最关键变化</h2></div><NavLink className="secondary-link" to={`/radar?thesisId=${thesisId}`}>查看全部 {feed.data.total} 条</NavLink></div><div className="evidence-list">{evidence.slice(0, 3).map((record) => <EvidenceEventRow item={record} key={`${record.evidenceId}-${record.relationId}`} />)}</div></section>
    <section className="content-section two-column"><div><div className="section-heading"><div><span className="eyebrow">人工闸门</span><h2>状态建议</h2></div></div>{openSuggestion ? <article className="suggestion-card"><span>规则建议</span><h3>{openSuggestion.currentStatus} → {openSuggestion.suggestedStatus}</h3><p>{openSuggestion.reasons.join('；')}</p><textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} placeholder="填写决策原因（必填）" /><select value={targetStatus} onChange={(event) => setTargetStatus(event.target.value)}><option>验证中</option><option>出现分歧</option><option>重大风险</option><option>已关闭</option></select><div className="button-row"><button disabled={!decisionReason.trim() || decision.isPending} className="button primary" onClick={() => decision.mutate({ id: openSuggestion.suggestionId, action: '接受' })}>接受建议</button><button disabled={!decisionReason.trim() || decision.isPending} className="button secondary" onClick={() => decision.mutate({ id: openSuggestion.suggestionId, action: '拒绝' })}>拒绝</button><button disabled={!decisionReason.trim() || decision.isPending} className="button secondary" onClick={() => decision.mutate({ id: openSuggestion.suggestionId, action: '修改' })}>修改状态</button></div><InlineError error={decision.error} /></article> : <EmptyState title="没有待处置建议" description="证据审核后，规则引擎会生成新的状态建议。" />}</div><div><div className="section-heading"><div><span className="eyebrow">可追溯</span><h2>关键审计记录</h2></div></div><div className="timeline">{businessAudit.length ? businessAudit.map((line, index) => <div className="timeline-item" key={`${line.action}-${index}`}><i /><div><strong>{line.action}</strong><p>{line.actor} · {formatDate(line.occurredAt)}</p></div></div>) : <p className="muted">暂无关键业务变更记录。</p>}</div></div></section>
    {item.status === '草稿' ? <DraftPublishWorkspace thesis={item} /> : <PostPublicationRevisionWorkspace thesis={item} />}
  </>
}

function PostPublicationRevisionWorkspace({ thesis }: { thesis: ThesisDetail }) {
  const [draft, setDraft] = useState<ThesisRevision | null>(null)
  const create = useMutation({ mutationFn: () => createThesisRevision(thesis.thesisId), onSuccess: setDraft })
  return <section className="content-section"><div className="section-heading"><div><span className="eyebrow">发布后修订</span><h2>版本化修改</h2></div>{!draft && <button className="button secondary" disabled={create.isPending} onClick={() => create.mutate()}>{create.isPending ? '创建中…' : `基于 V${thesis.version} 创建修订`}</button>}</div><p className="muted">修订保留基础版本、差异和编辑代次；发布前检查并发冲突，成功后生成新的不可变版本快照。</p><InlineError error={create.error} />{draft && <ThesisRevisionEditor initial={draft} />}</section>
}

function ThesisRevisionEditor({ initial }: { initial: ThesisRevision }) {
  const qc = useQueryClient()
  const [draft, setDraft] = useState(initial)
  const thesisPayload = (draft.payload.thesis ?? {}) as Record<string, unknown>
  const [title, setTitle] = useState(String(thesisPayload.title ?? ''))
  const [coreView, setCoreView] = useState(String(thesisPayload.core_view ?? ''))
  const [direction, setDirection] = useState(String(thesisPayload.direction ?? '观察'))
  const [reason, setReason] = useState('')
  const diff = useQuery({ queryKey: ['thesis-revision-diff', draft.draftId, draft.revision], queryFn: () => getThesisRevisionDiff(draft.draftId) })
  const nextPayload = () => ({ ...draft.payload, thesis: { ...thesisPayload, title, core_view: coreView, direction } })
  const save = useMutation({ mutationFn: () => updateThesisRevision(draft, nextPayload()), onSuccess: async (updated) => { setDraft(updated); await qc.invalidateQueries({ queryKey: ['thesis-revision-diff', updated.draftId] }) } })
  const publish = useMutation({ mutationFn: async () => { const saved = await updateThesisRevision(draft, nextPayload()); setDraft(saved); return publishThesisRevision(saved, reason) }, onSuccess: async (updated) => { setDraft(updated); await Promise.all([qc.invalidateQueries({ queryKey: ['thesis', draft.thesisId] }), qc.invalidateQueries({ queryKey: ['audit', draft.thesisId] })]) } })
  if (draft.status === 'published') return <p className="success-note">修订已发布，新版本快照已生成。</p>
  return <div className="revision-editor"><div className="form-grid two"><label>标题<input value={title} maxLength={40} onChange={(event) => setTitle(event.target.value)} /></label><label>投资方向<select value={direction} onChange={(event) => setDirection(event.target.value)}><option>看多</option><option>看空</option><option>观察</option></select></label><label className="revision-core-view">核心观点<textarea value={coreView} maxLength={200} onChange={(event) => setCoreView(event.target.value)} /></label></div><div className="button-row"><button className="button secondary" disabled={save.isPending || !title.trim() || !coreView.trim()} onClick={() => save.mutate()}>{save.isPending ? '保存中…' : `保存草稿 r${draft.revision}`}</button></div><InlineError error={save.error} /><div className="revision-diff"><strong>相对 V{draft.baseVersion} 的差异</strong>{diff.data && Object.keys(diff.data.changes).length ? Object.entries(diff.data.changes).map(([field, values]) => <p key={field}><span>{field}</span><del>{String(values.before ?? '—')}</del><ins>{String(values.after ?? '—')}</ins></p>) : <p className="muted">保存草稿后在这里预览差异。</p>}</div><label>发布原因<textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="说明为什么修改正式研究结论（必填）" /></label><button className="button primary" disabled={publish.isPending || reason.trim().length < 2} onClick={() => publish.mutate()}>{publish.isPending ? '发布中…' : '发布为新版本'}</button><InlineError error={publish.error} /></div>
}

function dateAfter(days: number) {
  const value = new Date()
  value.setDate(value.getDate() + days)
  return value.toISOString().slice(0, 10)
}

function StageBar({ status }: { status: string }) {
  const active = status === '草稿' ? 0 : status === '验证中' ? 1 : 2
  return <div className="stage-bar" aria-label="逻辑生命周期"><span className={active === 0 ? 'active' : ''}>1. 草稿确认</span><i>→</i><span className={active === 1 ? 'active' : ''}>2. 验证中</span><i>→</i><span className={active === 2 ? 'active' : ''}>3. 维护复盘</span></div>
}

function DraftQualitySection({ thesis, onCheck, checking, checked, error }: { thesis: ThesisDetail; onCheck: () => void; checking: boolean; checked: boolean; error?: Error | null }) {
  return <section className="content-section"><div className="section-heading"><div><span className="eyebrow">草稿质量检查</span><h2>假设逻辑检查</h2></div><button className="button secondary" disabled={checking} onClick={onCheck}>{checking ? '检查中…' : '重新检查假设逻辑'}</button></div><p className="muted">检查假设之间的维度、重复和交叉关系。</p>{checked && <p className="success-note">检查完成，结果已更新。</p>}{error && <InlineError error={error} />}<div className="hypothesis-grid">{thesis.hypotheses.map((hypothesis) => <article className="hypothesis-card" key={hypothesis.hypothesisId}><div><span className="importance">{hypothesis.importance}</span><span className="hypothesis-status">{hypothesis.logicDimension || hypothesis.causalLevel || '待检查'}</span></div><h3>{hypothesis.statement}</h3>{hypothesis.qualityWarning && <p className="warning-note">{hypothesis.qualityWarning}</p>}</article>)}</div></section>
}

function DraftPublishWorkspace({ thesis }: { thesis: ThesisDetail }) {
  const [metricKeyword, setMetricKeyword] = useState('')
  const metrics = useQuery({ queryKey: ['metrics', metricKeyword], queryFn: () => listMetrics(metricKeyword) })
  const trends = useQuery({ queryKey: ['trends', thesis.thesisId], queryFn: () => getTrends(thesis.thesisId) })
  const aiRiskSuggestions = thesis.riskSuggestions.filter((item) => !String(item.source_url ?? '').trim())
  return <>
    <section className="content-section draft-config"><div className="section-heading"><div><span className="eyebrow">人工配置</span><h2>假设、指标与失效条件</h2></div><span className="muted">草稿阶段：可在每条假设下重新推荐相关指标</span></div>
      <label className="metric-search">搜索指标字典<input value={metricKeyword} onChange={(event) => setMetricKeyword(event.target.value)} placeholder="输入指标名称或 ID" /></label>
      <InlineError error={metrics.error} />
      <div className="hypothesis-editor-list">{thesis.hypotheses.map((hypothesis) => <HypothesisEditor key={hypothesis.hypothesisId} thesisId={thesis.thesisId} hypothesis={hypothesis} metrics={metrics.data ?? []} trend={trends.data?.find((item) => item.hypothesisId === hypothesis.hypothesisId)} />)}</div>
      {(aiRiskSuggestions.length > 0 || thesis.invalidationSuggestions.length > 0) && <div className="ai-candidate-panel"><strong>AI 风险与失效建议（待人工判断）</strong>{[...aiRiskSuggestions, ...thesis.invalidationSuggestions].map((item, index) => <p key={index}>{String(item.statement ?? '未提供建议文本')}</p>)}</div>}
    </section>
    <PublishPanel thesisId={thesis.thesisId} />
  </>
}

function MiniHistoryChart({ observations, unit }: { observations: Array<Record<string, unknown>>; unit: string }) {
  const values = observations.map((item) => Number(item.value)).filter(Number.isFinite)
  if (!values.length) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const latest = observations[observations.length - 1]
  const formatValue = (value: unknown) => { const number = Number(value); return Number.isFinite(number) ? number.toLocaleString('zh-CN', { maximumFractionDigits: 3 }) : String(value ?? '—') }
  return <div className="history-chart" aria-label={`${unit || '指标'}历史波动`}><div className="history-chart-head"><strong>历史波动</strong><span>单位：{unit || '未标注'}</span><span>最新：{formatValue(latest?.value)}（{String(latest?.period ?? '—')}）</span></div><div className="history-scale"><span>最高 {formatValue(max)}</span><span>最低 {formatValue(min)}</span></div><div className="history-bars">{observations.map((item, index) => { const value = Number(item.value); const height = 18 + ((value - min) / range) * 52; return <div className="history-bar-wrap" key={`${String(item.period)}-${index}`} title={`${String(item.period)}：${formatValue(item.value)} ${unit}`}><b>{formatValue(item.value)}</b><i style={{ height: `${height}px` }} /><small>{String(item.period)}</small></div> })}</div></div>
}

function HypothesisEditor({ thesisId, hypothesis, metrics, trend }: { thesisId: string; hypothesis: Hypothesis; metrics: MetricDefinition[]; trend?: Trend }) {
  const qc = useQueryClient()
  const initial = hypothesis.mappings[0]
  const [mappingId, setMappingId] = useState(initial?.mappingId ?? '')
  const current = hypothesis.mappings.find((item) => item.mappingId === mappingId)
  const [statement, setStatement] = useState(hypothesis.statement)
  const [hypothesisType, setHypothesisType] = useState(hypothesis.hypothesisType)
  const [importance, setImportance] = useState(hypothesis.importance)
  const [observationWindow, setObservationWindow] = useState(hypothesis.observationWindow ?? '')
  const [invalidationRule, setInvalidationRule] = useState(hypothesis.invalidationRule ?? '')
  const [metricKey, setMetricKey] = useState(initial ? `${initial.metricId}@@${initial.metricVersion}` : '')
  const [expectedDirection, setExpectedDirection] = useState(['下降', '越低越好', '不高于阈值'].includes(initial?.expectedDirection ?? '') ? '下降' : initial?.expectedDirection === '波动' ? '波动' : '上升')
  const [lowerBound, setLowerBound] = useState(initial?.expectedLower ?? '')
  const [upperBound, setUpperBound] = useState(initial?.expectedUpper ?? '')
  const [periods, setPeriods] = useState(String(initial?.invalidationConsecutivePeriods ?? 1))
  const [source, setSource] = useState(initial?.expectationSource ?? '研究员人工录入')
  const [agentSuggestions, setAgentSuggestions] = useState(hypothesis.metricSuggestions)
  const [adoptedMetric, setAdoptedMetric] = useState<MetricDefinition | null>(null)
  const [adoptedNotice, setAdoptedNotice] = useState('')
  const selected = metrics.find((item) => `${item.metricId}@@${item.version}` === metricKey) ?? adoptedMetric
  const refresh = async () => { await Promise.all([qc.invalidateQueries({ queryKey: ['thesis', thesisId] }), qc.invalidateQueries({ queryKey: ['trends', thesisId] }), qc.invalidateQueries({ queryKey: ['publish-readiness', thesisId] }), qc.invalidateQueries({ queryKey: ['audit', thesisId] })]) }
  const hypothesisMutation = useMutation({ mutationFn: () => updateHypothesis(thesisId, hypothesis.hypothesisId, { statement, hypothesisType, importance, observationWindow, invalidationRule }), onSuccess: refresh })
  const mappingMutation = useMutation({ mutationFn: () => { if (!selected) throw new Error('请从指标字典选择指标。'); if (!lowerBound && !upperBound) throw new Error('上限和下限至少填写一项。'); if (expectedDirection === '上升' && !lowerBound) throw new Error('上升方向需要填写下限。'); if (expectedDirection === '下降' && !upperBound) throw new Error('下降方向需要填写上限。'); return saveMetricMapping(thesisId, hypothesis.hypothesisId, { mappingId: mappingId || undefined, metricId: selected.metricId, metricVersion: selected.version, expectedDirection, expectedLower: lowerBound, expectedUpper: upperBound, invalidationConsecutivePeriods: Number(periods), expectationSource: source }) }, onSuccess: async (saved) => { setMappingId(saved.mappingId); await refresh() } })
  const agentMutation = useMutation({ mutationFn: () => recommendHypothesisMetrics(thesisId, hypothesis.hypothesisId), onSuccess: (candidate) => setAgentSuggestions((candidate.payload.recommendations ?? []) as Array<Record<string, unknown>>) })
  useEffect(() => {
    if (agentMutation.isPending) setAdoptedNotice('正在读取历史数据并推荐指标…')
    else if (agentMutation.isSuccess) setAdoptedNotice(`已完成指标推荐，共 ${agentSuggestions.length} 个候选；请人工确认后保存。`)
  }, [agentMutation.isPending, agentMutation.isSuccess, agentSuggestions.length])
  const chooseMetric = (value: string) => { setMetricKey(value); setAdoptedMetric(null); const metric = metrics.find((item) => `${item.metricId}@@${item.version}` === value); if (metric?.expectedDirection) setExpectedDirection(['下降', '越低越好', '不高于阈值'].includes(metric.expectedDirection) ? '下降' : metric.expectedDirection === '波动' ? '波动' : '上升') }
  const chooseMapping = (value: string) => { const item = hypothesis.mappings.find((mapping) => mapping.mappingId === value); const direction = item?.expectedDirection ?? '上升'; setMappingId(value); setMetricKey(item ? `${item.metricId}@@${item.metricVersion}` : ''); setExpectedDirection(['下降', '越低越好', '不高于阈值'].includes(direction) ? '下降' : direction === '波动' ? '波动' : '上升'); setLowerBound(item?.expectedLower ?? ''); setUpperBound(item?.expectedUpper ?? ''); setPeriods(String(item?.invalidationConsecutivePeriods ?? 1)); setSource(item?.expectationSource ?? '研究员人工录入') }
  const adoptSuggestion = (item: Record<string, unknown>) => { const thresholdSuggestion = (item.threshold_suggestion ?? {}) as Record<string, unknown>; const metric = item.metric_id ? metrics.find((candidate) => `${candidate.metricId}` === String(item.metric_id) && `${candidate.version}` === String(item.metric_version ?? 'v1.0')) ?? { metricId: String(item.metric_id), version: String(item.metric_version ?? 'v1.0'), name: String(item.metric_name ?? item.metric_id), unit: '', status: '待确认' } : metrics.find((candidate) => candidate.name.includes(String(item.metric_name ?? '')) || String(item.metric_name ?? '').includes(candidate.name)); if (!metric) { setMetricKey(''); setSource('请先将 Agent 候选匹配到指标字典'); return } const falling = ['下降', '越低越好', '不高于阈值'].includes(String(item.expected_direction ?? metric.expectedDirection ?? '')); const bound = thresholdSuggestion.value == null ? '' : String(thresholdSuggestion.value); setAdoptedMetric(metric); setMappingId(''); setMetricKey(`${metric.metricId}@@${metric.version}`); setExpectedDirection(falling ? '下降' : '上升'); setLowerBound(falling ? '' : bound); setUpperBound(falling ? bound : ''); setSource(`人工确认 Agent 候选；依据：${String(thresholdSuggestion.rationale ?? item.rationale ?? '待补充')}`); setAdoptedNotice(`已填入：${metric.name}。请确认方向和上下界后保存。`) }
  const renderSuggestionDetails = (item: Record<string, unknown>) => { const thresholdSuggestion = (item.threshold_suggestion ?? {}) as Record<string, unknown>; const observations = Array.isArray(item.observations) ? item.observations as Array<Record<string, unknown>> : []; const unit = String(item.unit ?? (String(item.metric_id ?? '').startsWith('AUTO-') ? '辆' : '')) ; return <><span className="suggestion-meta">{String(item.relation_type ?? '候选指标')} · {String(item.expected_direction ?? '待确认')}</span>{thresholdSuggestion.formula && <span className="suggestion-meta">阈值依据：{String(thresholdSuggestion.formula)} · 样本 {String(thresholdSuggestion.sample_count ?? 0)} 期</span>}{thresholdSuggestion.value != null && <span className="suggestion-meta">建议阈值：{String(thresholdSuggestion.value)}（单位：{unit || '未标注'}）</span>}{observations.length > 0 ? <MiniHistoryChart observations={observations} unit={unit} /> : <span className="suggestion-meta">暂无可用历史观测（可点击重新推荐以触发数据补取）</span>}</> }
  return <article className="hypothesis-editor"><div className="editor-heading"><div><strong>{hypothesis.hypothesisId}</strong><span className={`badge ${importance === '核心' ? 'priority-high' : 'neutral-badge'}`}>{importance}</span>{(hypothesis.logicDimension || hypothesis.causalLevel) && <span className="badge neutral-badge">{hypothesis.logicDimension || hypothesis.causalLevel}</span>}</div><span className="muted">{hypothesis.mappings.length} 个验证指标</span></div>{hypothesis.qualityWarning && <p className="warning-note">{hypothesis.qualityWarning}</p>}
    <div className="ai-suggestions"><span>Agent 指标与阈值依据（仅候选）</span><button className="button secondary" disabled={agentMutation.isPending} onClick={() => agentMutation.mutate()}>{agentMutation.isPending ? '生成中…' : '重新推荐相关指标'}</button>{agentSuggestions.map((item, index) => <em key={index}><strong>{String(item.metric_name ?? '未命名指标')}</strong>{item.rationale ? ` · ${String(item.rationale)}` : ''}{renderSuggestionDetails(item)}<button className="button secondary" onClick={() => adoptSuggestion(item)}>填入人工确认区</button></em>)}<InlineError error={agentMutation.error} /></div>
    <div className="form-grid two"><label>假设内容<textarea value={statement} onChange={(event) => setStatement(event.target.value)} /></label><label>失效条件描述<textarea value={invalidationRule} onChange={(event) => setInvalidationRule(event.target.value)} placeholder="由研究员确认，不自动采用 AI 建议" /></label><label>假设类型<select value={hypothesisType} onChange={(event) => setHypothesisType(event.target.value)}><option>行业</option><option>公司竞争力</option><option>经营</option><option>盈利</option><option>政策</option><option>估值</option><option>其他</option></select></label><label>重要性<select value={importance} onChange={(event) => setImportance(event.target.value)}><option>核心</option><option>辅助</option></select></label><label>观察窗口<input value={observationWindow} onChange={(event) => setObservationWindow(event.target.value)} placeholder="例如：未来 4 个季度" /></label><div className="editor-action"><button className="button secondary" disabled={hypothesisMutation.isPending || !statement.trim()} onClick={() => hypothesisMutation.mutate()}>保存假设</button></div></div><InlineError error={hypothesisMutation.error} />
    <div className="mapping-editor"><h3>验证指标与研究员判断区间</h3>{adoptedNotice && <p className="success-note">{adoptedNotice}</p>}{trend && <div className="existing-trend"><strong>已有指标历史波动</strong><span>{trend.metricId} · {trend.points.length} 期 · {trend.points.map((point) => `${point.period} ${point.value}${trend.unit}`).join('，')}</span></div>}<div className="form-grid mapping-grid"><label>编辑映射<select value={mappingId} onChange={(event) => chooseMapping(event.target.value)}><option value="">新增指标映射</option>{hypothesis.mappings.map((item) => <option key={item.mappingId} value={item.mappingId}>{item.metricName ? `${item.metricName}（${item.metricId}）` : item.metricId} · {item.metricVersion}</option>)}</select></label><label>指标字典<select value={metricKey} onChange={(event) => chooseMetric(event.target.value)}><option value="">选择已有指标</option>{metrics.map((item) => <option key={`${item.metricId}-${item.version}`} value={`${item.metricId}@@${item.version}`}>{item.name}（{item.metricId} · {item.unit}）</option>)}</select></label><label>变化方向<select value={expectedDirection} onChange={(event) => setExpectedDirection(event.target.value)}><option>上升</option><option>下降</option><option>波动</option></select></label><label>下限（可选）<input inputMode="decimal" value={lowerBound} onChange={(event) => setLowerBound(event.target.value)} placeholder={expectedDirection === '上升' ? '上升方向必填' : '允许区间下界'} /></label><label>上限（可选）<input inputMode="decimal" value={upperBound} onChange={(event) => setUpperBound(event.target.value)} placeholder={expectedDirection === '下降' ? '下降方向必填' : '允许区间上界'} /></label><label>连续期数<input type="number" min="1" max="12" value={periods} onChange={(event) => setPeriods(event.target.value)} /></label><label>判断依据<input value={source} onChange={(event) => setSource(event.target.value)} placeholder="会议纪要、研究员判断等" /></label></div><p className="metric-rule-help">连续越出允许区间后，后端仅生成复核提醒，不自动改变假设或投资逻辑状态。</p><button className="button primary" disabled={mappingMutation.isPending || !metricKey || !source.trim()} onClick={() => mappingMutation.mutate()}>{mappingMutation.isPending ? '保存中…' : current ? '更新指标映射' : '人工确认并新增指标'}</button><InlineError error={mappingMutation.error} /></div>
  </article>
}

function PublishPanel({ thesisId }: { thesisId: string }) {
  const qc = useQueryClient()
  const [direction, setDirection] = useState('观察')
  const [horizonEndOn, setHorizonEndOn] = useState(() => dateAfter(365))
  const [nextReviewAt, setNextReviewAt] = useState(() => dateAfter(90))
  const readiness = useQuery({ queryKey: ['publish-readiness', thesisId, direction, horizonEndOn, nextReviewAt], queryFn: () => getPublishReadiness(thesisId, { direction, horizonEndOn, nextReviewAt }) })
  const mutation = useMutation({ mutationFn: () => publishThesis(thesisId, { direction, horizonEndOn, nextReviewAt }), onSuccess: () => qc.invalidateQueries({ queryKey: ['thesis', thesisId] }) })
  return <section className="content-section publish-panel"><div className="section-heading"><div><span className="eyebrow">发布监控</span><h2>人工发布就绪清单</h2></div><span className={`badge ${readiness.data?.ready ? 'status-confirmed' : 'priority-medium'}`}>{readiness.data?.ready ? '可以发布' : '配置未完成'}</span></div><div className="form-grid publish-fields"><label>投资方向<select value={direction} onChange={(event) => setDirection(event.target.value)}><option>观察</option><option>看多</option><option>看空</option></select></label><label>监控期限<input type="date" value={horizonEndOn} onChange={(event) => setHorizonEndOn(event.target.value)} /></label><label>下次复核<input type="date" value={nextReviewAt} onChange={(event) => setNextReviewAt(event.target.value)} /></label></div><div className="readiness-list">{readiness.data?.items.map((item) => <div className={item.passed ? 'readiness-passed' : 'readiness-failed'} key={item.code}><span>{item.passed ? '✓' : '!'}</span><div><strong>{item.label}</strong><p>{item.message}</p></div></div>)}</div><button className="button primary" disabled={mutation.isPending || !readiness.data?.ready} onClick={() => mutation.mutate()}>确认配置并发布监控</button><InlineError error={readiness.error ?? mutation.error} /></section>
}

export function EvidencePage() {
  const { evidenceId = '' } = useParams()
  const [params] = useSearchParams()
  const requestedRelationId = params.get('relationId')
  const qc = useQueryClient()
  const evidence = useQuery({ queryKey: ['evidence', evidenceId], queryFn: () => getEvidence(evidenceId) })
  const retrievalTrace = useQuery({ queryKey: ['evidence-retrieval-trace', evidenceId], queryFn: () => getEvidenceRetrievalTrace(evidenceId) })
  const relations = useQuery({ queryKey: ['relations', evidenceId], queryFn: () => getRelations(evidenceId) })
  const source = useQuery({ queryKey: ['source-segment', evidence.data?.evidenceLocator], queryFn: () => getDocumentSegment(evidence.data!.evidenceLocator), enabled: Boolean(evidence.data?.evidenceLocator) })
  const theses = useQuery({ queryKey: ['target-theses', evidence.data?.securityId], queryFn: () => listTheses(evidence.data!.securityId, false, true), enabled: Boolean(evidence.data?.securityId) })
  const manageableTheses = useQuery({ queryKey: ['manageable-theses', evidence.data?.securityId], queryFn: () => listTheses(evidence.data!.securityId, true, true), enabled: Boolean(evidence.data?.securityId) })
  const activeRelation = relations.data?.find((item) => item.relationId === requestedRelationId) ?? relations.data?.find((item) => item.status !== 'deactivated')
  const activeFeed = useQuery({ queryKey: ['thesis-evidence-feed', activeRelation?.thesisId], queryFn: () => getThesisEvidenceFeed(activeRelation!.thesisId), enabled: Boolean(activeRelation?.thesisId) })
  const [dialog, setDialog] = useState<{ relation: Relation; action: '确认' | '驳回' | '暂不判断' | '解除' } | null>(null)
  const [editing, setEditing] = useState<Relation | null>(null)
  const context = activeFeed.data?.items.find((item) => item.evidenceId === evidenceId && item.relationId === activeRelation?.relationId)
  const invalidate = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['relations', evidenceId] }),
      qc.invalidateQueries({ queryKey: ['workbench-tasks'] }),
      qc.invalidateQueries({ queryKey: ['workbench'] }),
      qc.invalidateQueries({ queryKey: ['radar-evidence'] }),
      qc.invalidateQueries({ queryKey: ['thesis-evidence-feed'] }),
      qc.invalidateQueries({ queryKey: ['suggestions'] }),
    ])
  }
  const action = useMutation({
    mutationFn: async (input: { relation: Relation; action: string; reason: string }) => input.action === '解除'
      ? deactivateRelation(evidenceId, input.relation.relationId, input.reason)
      : reviewRelation(evidenceId, input.relation.relationId, input.action, input.reason),
    onSuccess: async () => { setDialog(null); await invalidate() },
  })
  if (evidence.isLoading || relations.isLoading || theses.isLoading || manageableTheses.isLoading) return <LoadingState />
  if (evidence.error || relations.error || theses.error || manageableTheses.error || !evidence.data || !relations.data || !theses.data || !manageableTheses.data) return <ErrorState error={evidence.error ?? relations.error ?? theses.error ?? manageableTheses.error} />
  const item = evidence.data
  const thesisMap = new Map(theses.data.map((thesis) => [thesis.thesisId, thesis]))
  const activeThesis = activeRelation ? thesisMap.get(activeRelation.thesisId) : undefined
  const activeHypothesis = activeThesis?.hypotheses.find((hypothesis) => hypothesis.hypothesisId === activeRelation?.hypothesisId)
  const confirmedFacts = (activeFeed.data?.items ?? []).filter((candidate) => {
    const primaryConfirmed = candidate.evidenceId === item.evidenceId && (item.confirmationStatus === 'confirmed' || activeRelation?.status === 'confirmed')
    if ((!primaryConfirmed && candidate.confirmationStatus !== 'confirmed') || candidate.hypothesisId !== activeRelation?.hypothesisId) return false
    if (candidate.sourceDocumentId && item.sourceDocumentId) return candidate.sourceDocumentId === item.sourceDocumentId
    if (candidate.sourceUrl && item.sourceUrl) return candidate.sourceUrl === item.sourceUrl
    return candidate.sourceDocumentTitle === item.sourceDocumentTitle && candidate.disclosedAt.slice(0, 10) === item.disclosedAt.slice(0, 10)
  })
  const factRows = confirmedFacts.length > 0 ? confirmedFacts : (item.confirmationStatus === 'confirmed' || activeRelation?.status === 'confirmed') ? [{
    evidenceId: item.evidenceId, factExcerpt: item.factExcerpt, evidenceLocator: item.evidenceLocator,
    direction: item.direction, strength: item.strength, aiConfidence: item.aiConfidence,
  }] : []
  return <div className="evidence-detail-page">
    <header className="evidence-detail-header">
      <div className="evidence-detail-heading">
        <NavLink to={`/companies/${encodeURIComponent(item.securityId)}`}>← 返回公司总览</NavLink>
        <span>证据验证 / EVIDENCE REVIEW · {item.securityId}</span>
        <h1>{item.sourceDocumentTitle}</h1>
        <p>披露于 {formatDate(item.disclosedAt)}，以下内容均来自数据库归档的资料、事实和关联记录。</p>
      </div>
      <div className="evidence-detail-status">
        <DirectionBadge direction={activeRelation?.direction ?? item.direction} />
        <StatusBadge state={activeRelation?.status ?? item.confirmationStatus} />
        <span><small>AI 关系置信度</small><strong>{Math.round(item.aiConfidence * 100)}%</strong></span>
      </div>
    </header>
    <main className="evidence-detail-layout">
      <div className="evidence-detail-main">
        <section className="fact-panel evidence-detail-card evidence-source-card">
          <header><div><span>01 / 资料证据</span><h2>数据库已确认的资料内容</h2></div><SafeSourceLink url={item.sourceUrl} /></header>
          <div className="evidence-fact-list">{factRows.length ? factRows.map((fact, index) => { const label = fact.direction === 'support' ? '支持' : fact.direction === 'conflict' ? '冲突' : '中性'; return <details className={`evidence-fact-card ${fact.direction}`} key={fact.evidenceId}><summary><span className="evidence-fact-number">{String(index + 1).padStart(2, '0')}</span><div><b>{label}</b><strong>{fact.factExcerpt}</strong></div><small>查看原文<i>⌄</i></small></summary><div><blockquote className="evidence-source-copy">{fact.evidenceId === item.evidenceId ? source.data?.content ?? fact.factExcerpt : fact.factExcerpt}</blockquote><p>证据编号：{fact.evidenceId} · 原文定位：{fact.evidenceLocator || '未记录'}</p></div></details> }) : <p className="company-evidence-state">该资料暂未找到已确认的事实证据。</p>}</div>
          {source.error && <p className="inline-error">数据库原文段落暂不可用，当前展示证据摘录。</p>}
          <div className="source-footer"><span>{item.sourceDocumentTitle} · {formatDate(item.disclosedAt)}{source.data?.page ? ` · 第 ${source.data.page} 页` : ''}{source.data?.contentKind === 'table_row' ? ` · 表 ${source.data.tableIndex} / 单元格 ${source.data.cellRange}` : ''}{source.data?.extractionMethod === 'ocr' ? ` · OCR${source.data.confidence == null ? '' : ` ${Math.round(source.data.confidence * 100)}%`}` : ''}{source.data?.locator ? ` · 定位 ${source.data.locator}` : ''}</span></div>
        </section>
        {context && <section className="content-section evidence-detail-card evidence-validation-card"><div className="section-heading"><div><span className="eyebrow">02 / 验证记录</span><h2>数据库验证结果</h2></div><span className="validation-summary">{context.validationItems.filter((v) => v.status === 'passed').length}/{context.validationItems.length} 项通过</span></div><ValidationChain items={context.validationItems} /></section>}
        <div className="evidence-trace-wrap"><RetrievalTracePanel trace={retrievalTrace.data} loading={retrievalTrace.isLoading} error={retrievalTrace.error} /></div>
      </div>
      <aside className="evidence-detail-side">
        <section className="impact-panel evidence-detail-card"><div><span className="eyebrow">03 / 关联假设</span><h2>{activeHypothesis?.statement ?? '未找到关联假设'}</h2><p>{activeThesis?.title ?? '当前资料没有可展示的投资逻辑关联'}</p><div className="badge-row">{activeRelation && <><DirectionBadge direction={activeRelation.direction} /><StatusBadge state={activeRelation.status} /><span className="badge neutral-badge">{strengthText[activeRelation.strength]}强度</span></>}</div></div>{activeRelation?.canManage && activeRelation.status !== 'deactivated' ? <div className="decision-panel"><span>你的判断</span><div className="button-row"><button className="button primary" onClick={() => setDialog({ relation: activeRelation, action: '确认' })}>确认关联</button><button className="button secondary" onClick={() => setDialog({ relation: activeRelation, action: '驳回' })}>驳回</button><button className="button ghost" onClick={() => setDialog({ relation: activeRelation, action: '暂不判断' })}>暂不判断</button></div></div> : <p className="read-only-note">当前关联为只读，或已退出状态计算。</p>}</section>
        <section className="evidence-audit-card evidence-detail-card"><span>可追溯信息</span><dl><div><dt>证据编号</dt><dd>{item.evidenceId}</dd></div><div><dt>关联数量</dt><dd>{relations.data.length} 条</dd></div><div><dt>来源资料</dt><dd>{item.sourceDocumentId}</dd></div><div><dt>处理模型</dt><dd>{item.modelVersion}</dd></div></dl></section>
      </aside>
    </main>
    <section className="evidence-detail-lower">
      <details className="content-section disclosure evidence-detail-card"><summary>关联假设记录 <span>{relations.data.length} 条关联</span></summary><div className="relation-list">{relations.data.map((relation) => { const target = thesisMap.get(relation.thesisId); const hypothesis = target?.hypotheses.find((h) => h.hypothesisId === relation.hypothesisId); return <article className={`relation-row ${relation.status === 'deactivated' ? 'disabled' : ''}`} key={relation.relationId}><div><div className="badge-row"><StatusBadge state={relation.status} /><DirectionBadge direction={relation.direction} /></div><h3>{hypothesis?.statement ?? '假设信息待加载'}</h3><p>{target?.title ?? relation.thesisId}</p><small>关联理由：{relation.reason || '未填写'} · 创建人：{relation.createdBy}{relation.reviewedBy ? ` · 审核人：${relation.reviewedBy}` : ''}</small></div>{relation.canManage && relation.status !== 'deactivated' && <div className="relation-actions"><button className="button secondary" onClick={() => setEditing(relation)}>修改</button><button className="button danger-link" onClick={() => setDialog({ relation, action: '解除' })}>解除</button></div>}</article> })}</div><RelationForm evidenceId={evidenceId} thesisList={manageableTheses.data} editing={editing} onDone={async () => { setEditing(null); await invalidate() }} /></details>
      <details className="content-section disclosure technical evidence-detail-card"><summary>技术信息</summary><dl><dt>证据 ID</dt><dd>{item.evidenceId}</dd><dt>来源文档 ID</dt><dd>{item.sourceDocumentId}</dd><dt>原文定位</dt><dd>{item.evidenceLocator}</dd><dt>模型版本</dt><dd>{item.modelVersion}</dd><dt>提示词版本</dt><dd>{item.promptVersion}</dd></dl></details>
    </section>
    <InlineError error={action.error} />
    {dialog && <ConfirmDialog title={dialog.action === '解除' ? '解除这条证据关联' : `${dialog.action}这条证据关联`} description={dialog.action === '解除' ? '解除后该关联保留为历史记录，不再参与状态建议。' : '本次人工判断将被记录并刷新受影响逻辑的状态建议。'} confirmText={dialog.action} danger={dialog.action === '解除' || dialog.action === '驳回'} requireReason={dialog.action === '解除'} onClose={() => setDialog(null)} onConfirm={(reason) => action.mutate({ relation: dialog.relation, action: dialog.action, reason })} />}
  </div>
}

function RelationForm({ evidenceId, thesisList, editing, onDone }: { evidenceId: string; thesisList: ThesisDetail[]; editing: Relation | null; onDone: () => void | Promise<void> }) {
  const [thesisId, setThesisId] = useState(editing?.thesisId ?? thesisList[0]?.thesisId ?? '')
  const [hypothesisId, setHypothesisId] = useState(editing?.hypothesisId ?? '')
  const [direction, setDirection] = useState(editing?.direction === 'support' ? '支持' : editing?.direction === 'conflict' ? '冲突' : '中性')
  const [strength, setStrength] = useState(editing?.strength === 'high' ? '高' : editing?.strength === 'low' ? '低' : '中')
  const [reason, setReason] = useState(editing?.reason ?? '')
  const selected = thesisList.find((item) => item.thesisId === thesisId)
  const mutation = useMutation({
    mutationFn: () => editing
      ? updateRelation(evidenceId, editing.relationId, { thesisId, hypothesisId, direction, strength, reason })
      : createRelation(evidenceId, { thesisId, hypothesisId, direction, strength, reason }),
    onSuccess: onDone,
  })
  return <form className="relation-form" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><h3>{editing ? '修改关联' : '新增关联'}</h3><div className="form-grid two"><label>目标逻辑<select value={thesisId} disabled={Boolean(editing)} onChange={(event) => { setThesisId(event.target.value); setHypothesisId('') }} required><option value="">选择逻辑</option>{thesisList.map((item) => <option key={item.thesisId} value={item.thesisId}>{item.title}</option>)}</select></label><label>目标假设<select value={hypothesisId} onChange={(event) => setHypothesisId(event.target.value)} required><option value="">选择假设</option>{selected?.hypotheses.map((hypothesis) => <option key={hypothesis.hypothesisId} value={hypothesis.hypothesisId}>{hypothesis.statement}</option>)}</select></label><label>影响方向<select value={direction} onChange={(event) => setDirection(event.target.value)}><option>支持</option><option>冲突</option><option>中性</option></select></label><label>影响强度<select value={strength} onChange={(event) => setStrength(event.target.value)}><option>高</option><option>中</option><option>低</option></select></label></div><label>关联理由<textarea value={reason} onChange={(event) => setReason(event.target.value)} required placeholder="说明这条事实为什么影响目标假设" /></label><button className="button primary" disabled={mutation.isPending}>{mutation.isPending ? '提交中…' : editing ? '保存修改' : '新增关联'}</button><InlineError error={mutation.error} /></form>
}

function RetrievalTracePanel({ trace, loading, error }: { trace?: EvidenceRetrievalTrace; loading: boolean; error: Error | null }) {
  if (loading) return <section className="retrieval-trace-panel"><span className="eyebrow">召回依据</span><p className="muted">正在读取文本与关系图追踪…</p></section>
  if (error) return <section className="retrieval-trace-panel"><span className="eyebrow">召回依据</span><p className="inline-error">召回追踪暂不可用，不影响证据核验。</p></section>
  if (!trace?.available) return <details className="retrieval-trace-panel"><summary><span><small>召回依据</small>历史证据未记录检索追踪</span><em>不影响原文核验</em></summary><p className="retrieval-empty">该证据生成于追踪字段启用前，仍可依据原文和人工关联进行判断。</p></details>
  const text = Math.max(0, Math.min(trace.scoreComponents.text, 1))
  const graph = Math.max(0, Math.min(trace.scoreComponents.graph, 1))
  const finalScore = Math.max(0, Math.min(trace.finalScore, 1))
  const mode = text > 0 && graph > 0 ? '文本 + 关系图' : graph > 0 ? '关系图' : '文本'
  return <details className="retrieval-trace-panel" open>
    <summary><span><small>召回依据</small>为什么匹配到这条证据？</span><em>{mode}</em></summary>
    <div className="retrieval-trace-body">
      <div className="retrieval-score-list">
        <ScoreBar label="文本相关度" value={text} tone="text" />
        <ScoreBar label="图谱相关度" value={graph} tone="graph" />
        <ScoreBar label="融合得分" value={finalScore} tone="fused" />
      </div>
      <div className="retrieval-paths">
        <h3>关系路径</h3>
        {trace.graphPaths.length ? trace.graphPaths.map((path, index) => <article key={`${path.explanation}-${index}`}>
          <div className="layer-sequence">{path.layers.map((layer, layerIndex) => <span key={`${layer}-${layerIndex}`}>{layer.replace('层', '')}</span>)}</div>
          <p>{path.explanation}</p>
          <small>路径置信 {path.score.toFixed(3)}{path.provenanceLocators.length ? ` · 来源 ${path.provenanceLocators.join('、')}` : ''}</small>
        </article>) : <p className="retrieval-empty">本次由文本链路命中，没有使用关系图路径。</p>}
      </div>
      <dl className="retrieval-meta">
        <dt>检索版本</dt><dd>{trace.retrievalVersion}</dd>
        <dt>证据定位</dt><dd>{trace.locator}</dd>
        <dt>图快照</dt><dd>{trace.graphSnapshot?.snapshotId ?? '未使用图快照'}</dd>
        {trace.graphSnapshot && <><dt>知识层规模</dt><dd>{trace.graphSnapshot.layers.map((layer) => `${layer.layer} ${layer.nodeCount}`).join(' · ')}</dd></>}
      </dl>
    </div>
  </details>
}

function ScoreBar({ label, value, tone }: { label: string; value: number; tone: 'text' | 'graph' | 'fused' }) {
  return <div className="retrieval-score"><span>{label}</span><div><i className={`score-${tone}`} style={{ width: `${Math.round(value * 100)}%` }} /></div><strong>{value.toFixed(3)}</strong></div>
}

function ReviewDraftPanel() {
  const theses = useQuery({ queryKey: ['theses', 'review-draft'], queryFn: () => listTheses(undefined, true) })
  const today = new Date().toISOString().slice(0, 10)
  const [thesisId, setThesisId] = useState('')
  const [periodStart, setPeriodStart] = useState(`${new Date().getFullYear()}-01-01`)
  const [periodEnd, setPeriodEnd] = useState(today)
  const [candidate, setCandidate] = useState<Awaited<ReturnType<typeof createReviewDraft>> | null>(null)
  const mutation = useMutation({ mutationFn: () => createReviewDraft(thesisId, { periodStart, periodEnd }), onSuccess: setCandidate })
  useEffect(() => { if (!thesisId && theses.data?.[0]) setThesisId(theses.data[0].thesisId) }, [thesisId, theses.data])
  if (theses.error) return <InlineError error={theses.error} />
  if (theses.isLoading || !theses.data) return null
  const payload = candidate?.payload ?? {}
  const list = (key: string) => Array.isArray(payload[key]) ? payload[key].map(String) : []
  return <section className="content-section"><div className="section-heading"><div><span className="eyebrow">AI 复盘候选</span><h2>生成复盘草稿</h2></div><span className="muted">仅使用已确认记录，结果需人工审核</span></div><div className="form-grid two"><label>投资逻辑<select value={thesisId} onChange={(event) => { setThesisId(event.target.value); setCandidate(null) }} required><option value="">选择投资逻辑</option>{theses.data.map((item) => <option key={item.thesisId} value={item.thesisId}>{item.title} · {item.securityId}</option>)}</select></label><label>开始日期<input type="date" value={periodStart} onChange={(event) => setPeriodStart(event.target.value)} required /></label><label>结束日期<input type="date" value={periodEnd} onChange={(event) => setPeriodEnd(event.target.value)} required /></label></div><button className="button primary" disabled={!thesisId || !periodStart || !periodEnd || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? '生成中…' : '生成复盘草稿'}</button><InlineError error={mutation.error} />{candidate && <div className="review-card ai-suggestions"><div className="review-header"><strong>复盘候选</strong><span className="badge priority-medium">待人工审核</span></div><p>{String(payload.summary ?? '未生成摘要')}</p>{[['支持变化', 'supporting_changes'], ['冲突变化', 'conflicting_changes'], ['待跟进问题', 'open_questions']].map(([label, key]) => <div key={key}><strong>{label}</strong>{list(key).length ? <ul>{list(key).map((item) => <li key={item}>{item}</li>)}</ul> : <p className="muted">暂无</p>}</div>)}{list('citations').length > 0 && <small className="muted">引用：{list('citations').join('、')}</small>}</div>}</section>
}

export function RetrospectiveCenterPage() {
  const [activeTab, setActiveTab] = useState('时间线')
  const [expandedSecond, setExpandedSecond] = useState(false)
  const [draftState, setDraftState] = useState('')
  const timeline = [
    { date:'4月1日', title:'建立投资逻辑', note:'判断：新能源产品周期上行，规模效应推动盈利改善', tone:'support' },
    { date:'4月15日', title:'新增支持证据', note:'新车型订单强劲，电池成本下降趋势确认', tone:'support' },
    { date:'5月9日', title:'出现冲突证据', note:'终端折扣率上升，单车盈利改善低于预期', tone:'conflict' },
    { date:'5月20日', title:'研究员更新判断', note:'原因：销量增长部分依赖降价，逻辑方向不变但验证程度下降', tone:'current' },
  ]
  return <div className="retrospective-page"><header className="retro-header"><div><span>RESEARCH RETROSPECTIVE</span><h1>复盘中心</h1><p>回看历史判断、逻辑演变与最终验证，并沉淀经过研究员确认的可复用经验。</p></div><div><button>⇧ 导出复盘</button><button className="primary" onClick={() => setDraftState('已生成最新复盘草稿')}>✦ 生成复盘草稿</button></div></header><section className="retro-search"><label><span>⌕</span><input placeholder="搜索公司、投资逻辑、核心假设、事件或研究结论" aria-label="搜索复盘记录" /></label><div>{[['时间范围','近一季度'],['行业','全部'],['公司','全部'],['研究员','全部'],['验证结果','全部']].map(([label,value]) => <label key={label}><span>{label}</span><select defaultValue={value}><option>{value}</option><option>吉利汽车</option><option>中芯国际</option></select></label>)}</div></section><section className="retro-metrics" aria-label="复盘概览">{[['逻辑变更','12','↯','blue'],['已验证假设','18','✓','green'],['待验证判断','14','⌛','amber'],['强反证处理','7/8','!','red'],['记录完整度','91%','◷','cyan']].map(([label,value,icon,tone]) => <article key={label}><i className={tone}>{icon}</i><div><span>{label}</span><strong>{value}</strong></div></article>)}</section><nav className="retro-tabs" aria-label="复盘视图">{['时间线','逻辑演变','假设验证'].map((tab) => <button key={tab} className={activeTab === tab ? 'active' : ''} onClick={() => setActiveTab(tab)}>{tab}</button>)}</nav><main className="retro-main-grid"><section className="retro-records"><header><h2>{activeTab === '时间线' ? '研究复盘记录' : activeTab === '逻辑演变' ? '投资逻辑版本演变' : '核心假设验证结果'}</h2><span>按最近变化排序</span></header>{activeTab === '时间线' && <><article className="retro-thesis open"><header><div><i>汽</i><div><strong>吉利汽车 / 新能源产品周期</strong><span>未来12个月 · 张明负责</span></div></div><b>展开中</b></header><div className="retro-timeline">{timeline.map((item) => <article key={item.date} className={item.tone}><i>{item.tone === 'conflict' ? '!' : item.tone === 'current' ? '●' : '✓'}</i><time>{item.date}</time><div><strong>{item.title}</strong>{item.tone === 'current' && <p className="confidence-change">置信度：<b>78%</b><i>→</i><em>66%</em></p>}<p>{item.note}</p></div><button>查看详情</button></article>)}</div></article><article className={`retro-thesis ${expandedSecond ? 'open' : ''}`}><button className="retro-collapsed" onClick={() => setExpandedSecond(!expandedSecond)} aria-expanded={expandedSecond}><div><i>芯</i><span><strong>中芯国际 / 国产替代</strong><small>最近更新：5月18日 · 新增强支持证据</small></span></div><b>{expandedSecond ? '收起⌃' : '展开⌄'}</b></button>{expandedSecond && <div className="retro-mini-history"><span>3月12日 建立逻辑</span><span>4月28日 稼动率改善</span><span>5月18日 研究员确认支持证据</span></div>}</article></>}{activeTab === '逻辑演变' && <div className="retro-version-view"><div><span>v1.0 · 4月1日</span><strong>产品周期驱动销量与盈利同步改善</strong><p>置信度78% · 三项核心假设</p></div><i>→</i><div className="active"><span>v1.2 · 5月20日</span><strong>产品周期支持销量增长，但价格竞争限制盈利弹性</strong><p>置信度66% · 调整H2与失效条件</p></div><section><h3>主要修改</h3><p>补充终端折扣率为主验证指标；将“规模效应必然改善盈利”调整为条件性假设。</p></section></div>}{activeTab === '假设验证' && <div className="retro-validation-table"><div><span>核心假设</span><span>验证期限</span><span>最终结果</span><span>关键依据</span></div>{[['新能源销量持续增长','6月30日','成立','连续三月销量增长'],['增长不依赖大幅降价','6月30日','部分成立','销量增长但折扣扩大'],['结构改善推动单车盈利','8月31日','尚未验证','等待中报数据']].map(([hypothesis,due,result,basis]) => <article key={hypothesis}><strong>{hypothesis}</strong><time>{due}</time><b className={`result-${result}`}>{result}</b><span>{basis}</span></article>)}</div>}</section><aside className="retro-side"><section className="retro-pending"><header><h2>待完成验证</h2><NavLink to="/reviews">查看全部（14）</NavLink></header>{[['吉利汽车','新车型毛利率能否在Q2回升至17%以上','6月15日'],['中芯国际','成熟制程利用率是否维持高位','6月20日'],['宁德时代','海外储能盈利稳定性是否达预期','6月25日']].map(([company,title,due],index) => <article key={company}><i className={index === 2 ? 'risk' : ''}>{index === 2 ? '!' : '⌛'}</i><div><strong>{company}</strong><span>{title}</span></div><time>{due}<b>待验证</b></time></article>)}</section><section className="retro-draft"><header><h2>自动复盘草稿</h2><span>吉利汽车 / 新能源产品周期</span></header><div><strong className="support">● 成立部分</strong><p>新能源产品周期确立，订单与销量增长符合预期；规模效应带来费用率改善。</p></div><div><strong className="conflict">● 未成立部分</strong><p>毛利率改善低于预期，终端折扣率上升；单车盈利未达目标。</p></div><div><strong className="pending">● 主要误差来源</strong><p>低估终端价格竞争强度，对需求结构变化判断不足。</p></div><footer><button onClick={() => setDraftState('正在查看复盘草稿')}>查看草稿</button><button className="primary" onClick={() => setDraftState('经验已确认并沉淀')}>确认并沉淀经验</button></footer>{draftState && <p className="retro-result" role="status">✓ {draftState}（静态演示）</p>}</section></aside></main><section className="retro-knowledge"><header><h2>已沉淀研究经验</h2><button>查看经验库 ›</button></header><article><i>✓</i><strong>销量增长不能单独作为盈利改善证据，需同时观察折扣率与单车盈利。</strong><span>新能源汽车</span><span>研究员已确认</span><button>查看详情 ›</button></article></section></div>
}

function ReviewsPageContent() {
  const adjudications = useQuery({ queryKey: ['adjudications'], queryFn: listAdjudications })
  const quality = useQuery({ queryKey: ['gold-quality'], queryFn: getGoldQuality })
  const tasks = useQuery({ queryKey: ['review-tasks'], queryFn: listReviewTasks })
  const ingestion = useQuery({ queryKey: ['ingestion-reviews'], queryFn: listIngestionReviews })
  const jobs = useQuery({ queryKey: ['processing-jobs'], queryFn: listProcessingJobs })
  const theses = useQuery({ queryKey: ['theses', 'review-draft'], queryFn: () => listTheses(undefined, true) })
  if (adjudications.isLoading || tasks.isLoading || ingestion.isLoading || jobs.isLoading || theses.isLoading) return <LoadingState />
  if (adjudications.error || tasks.error || ingestion.error || jobs.error || theses.error || !adjudications.data || !tasks.data || !ingestion.data || !jobs.data || !theses.data) return <ErrorState error={adjudications.error ?? tasks.error ?? ingestion.error ?? jobs.error ?? theses.error} />
  const deadLetters = jobs.data.filter((item) => ['failed', 'dead_letter'].includes(item.status))
  return <>
    <PageTitle eyebrow="质量治理" title="复核与复盘" description="统一处理资料归属、假设匹配、低置信、失败重放与独立导师裁决。" />
    {quality.data?.summary.productionGoldReady && <section className="adjudication-complete"><div><span className="flag-passed">FINAL GOLD READY</span><h2>161 条独立金标分歧已全部裁决</h2><p>最终 360 条硬金标已冻结，其中 358 条可进入系统评测；2 条原文异常样本仅保留审计。</p></div><NavLink className="button secondary" to="/quality">查看质量报告</NavLink></section>}
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">资料复核</span><h2>新资料人工队列</h2></div><span className="muted">{ingestion.data.filter((item) => item.status === 'pending').length} 条待处理</span></div>{ingestion.data.length ? <div className="review-list">{ingestion.data.map((item) => <IngestionReviewCard key={item.reviewId} item={item} />)}</div> : <EmptyState title="没有资料复核项" description="未归属证券、无法匹配假设、低置信事件和处理失败会显示在这里。" />}</section>
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">失败恢复</span><h2>死信与任务重放</h2></div><span className="muted">{deadLetters.length} 条可重放</span></div>{deadLetters.length ? <div className="review-list">{deadLetters.map((job) => <ProcessingJobCard key={job.jobId} job={job} />)}</div> : <EmptyState title="没有失败任务" description="达到重试上限的任务会持久化在这里，可在原件保留期内重放。" />}</section>
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">产品复核</span><h2>分配给我的逻辑任务</h2></div><span className="muted">{tasks.data.filter((item) => item.state === '待处理').length} 条待处理</span></div>{tasks.data.length ? <div className="review-list">{tasks.data.map((task) => <ReviewTaskCard key={task.taskId} task={task} />)}</div> : <EmptyState title="没有复核任务" description="重大事件或人工发起的逻辑任务会显示在这里。" />}</section>
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">持续评测</span><h2>在线抽样裁决队列</h2></div><span className="muted">{adjudications.data.filter((item) => !item.resolved).length} 条待裁决</span></div>{adjudications.data.length ? <div className="review-list">{adjudications.data.map((item) => <AdjudicationCard key={item.eventId} item={item} />)}</div> : <EmptyState title="当前没有新增分歧" description="冻结金标已完成；后续线上抽样产生的新分歧会进入此队列。" />}</section>
  </>
}

type StatusScenario = {
  id: string
  label: string
  tone: 'support' | 'conflict' | 'mixed' | 'warning' | 'neutral'
  evidence: string
  combination: string
  hypothesisBefore: string
  hypothesisAfter: string
  thesisBefore: string
  thesisSuggestion: string
  companySync: string
  promptPlace: string
  why: string[]
  sample: string
}

const statusScenarios: StatusScenario[] = [
  { id: 'single-strong-conflict', label: '单条直接高强度冲突', tone: 'conflict', evidence: '一条公司经营直接证据被确认，方向为冲突，强度为高。', combination: '单条证据即可触发“承压”建议，但不直接改正式状态。', hypothesisBefore: '验证中', hypothesisAfter: '核心假设承压', thesisBefore: '验证中', thesisSuggestion: '自动生成建议：核心假设承压 / 提示负责人关注', companySync: '公司页仍显示正式状态“验证中”，同时在该假设下出现承压提示和待处理建议入口。', promptPlace: '影响详情页顶部“研究处理结果”与右侧“正式状态决策”出现。', why: ['证据来自公司公告或财报口径，直接指向经营变量。', 'AI 关系被研究员纳入，进入状态规则计算。', '尚未命中组合失效规则，因此只生成建议。'], sample: '例：订单取消公告直接冲击“产能释放支撑收入增长”。' },
  { id: 'multi-support', label: '两条以上独立同向支持', tone: 'support', evidence: '两条以上独立来源已确认，均支持同一假设。', combination: '假设得到加强；正式投资逻辑通常维持现状。', hypothesisBefore: '验证中', hypothesisAfter: '假设得到加强', thesisBefore: '验证中', thesisSuggestion: '自动生成建议：假设得到加强；正式状态不变', companySync: '公司页假设卡显示“得到加强”，证据沉淀到证据链；工作台不再要求状态处置。', promptPlace: '影响详情页显示“本批仅沉淀证据与假设健康度”。', why: ['已确认 2 条以上独立证据。', '证据方向一致，且不与其他已确认冲突证据构成分歧。', '支持不等于需要改正式状态。'], sample: '例：销量、订单、渠道调研同时支持“需求复苏”。' },
  { id: 'same-hypothesis-divergent', label: '同一假设支持与冲突并存', tone: 'mixed', evidence: '同一假设下，已确认支持和已确认冲突同时达到阈值。', combination: '假设存在明显分歧，主逻辑建议进入“出现分歧”。', hypothesisBefore: '验证中', hypothesisAfter: '分歧', thesisBefore: '验证中', thesisSuggestion: '自动生成建议：出现分歧', companySync: '公司页正式状态只有研究员接受后才改；未接受前展示“待决策建议”。', promptPlace: '影响页右侧出现“接受建议 / 保持当前 / 修改状态”。', why: ['同一核心假设内出现相反方向证据。', '两类证据都已被人工纳入，不再只是 AI 候选。', '其他假设支持不能抵消该假设分歧。'], sample: '例：融资净卖出提示需求弱，但政策与信创活跃又支持需求恢复。' },
  { id: 'multi-hypothesis-divergent', label: '多条假设出现分歧', tone: 'mixed', evidence: '多条核心假设分别出现支持与冲突并存。', combination: '投资逻辑级别仍建议“出现分歧”，但页面必须列出是哪几条假设。', hypothesisBefore: '验证中', hypothesisAfter: 'H1 分歧；H2 分歧；H3 得到加强', thesisBefore: '验证中', thesisSuggestion: '自动生成建议：出现分歧 / 要求复核', companySync: '公司页顶部显示主逻辑分歧建议；各假设卡分别显示自己的健康状态。', promptPlace: '研究处理结果展示“受影响假设清单”，右侧统一做主逻辑状态决策。', why: ['状态建议按假设独立计算，再汇总到投资逻辑层。', '多个分歧不会生成多个主逻辑状态，只生成一个主状态建议。', '页面应突出本批新增影响，避免历史与新增混在一起。'], sample: '例：需求假设分歧，毛利假设也分歧，产能假设支持。' },
  { id: 'near-threshold', label: '量化指标触及预警阈值', tone: 'warning', evidence: '绑定指标接近或触及预警线，但未连续达到失效期数。', combination: '提示“接近失效”，暂不改变投资逻辑状态。', hypothesisBefore: '验证中', hypothesisAfter: '临近失效', thesisBefore: '验证中', thesisSuggestion: '自动生成建议：接近失效 / 继续观察', companySync: '公司页指标区高亮预警线，本期变化醒目；正式状态保持当前。', promptPlace: '假设指标卡和研究提醒区提示，不要求状态按钮。', why: ['指标是量化验证，不等于单独完成经营解释。', '只触及预警还不是连续失效。', '需要后续期数或更多直接证据确认。'], sample: '例：出口销量低于预期区间 1 期。' },
  { id: 'invalidation', label: '连续达到失效条件', tone: 'conflict', evidence: '绑定指标连续达到失效条件，或冲突证据命中失效规则。', combination: '优先建议“重大风险”，优先级高于“出现分歧”。', hypothesisBefore: '验证中', hypothesisAfter: '可能失效', thesisBefore: '验证中', thesisSuggestion: '自动生成建议：重大风险 / 发起失效评审', companySync: '接受后公司主逻辑正式状态变为“重大风险”；拒绝或修改会写入理由和审计。', promptPlace: '影响页和公司页都应出现高优先级决策提示。', why: ['关键假设命中已维护的失效条件。', '连续期数满足规则，强于单条噪音。', '重大风险优先级高于分歧与支持。'], sample: '例：毛利率连续 2 期低于失效阈值。' },
  { id: 'observe', label: '暂不判断 / 进入观察', tone: 'neutral', evidence: '资料相关但证据链不完整，研究员选择暂不判断。', combination: '不参与状态计算；进入观察清单。', hypothesisBefore: '验证中', hypothesisAfter: '待观察', thesisBefore: '验证中', thesisSuggestion: '不生成状态变更建议', companySync: '公司页保持原状态；研究记录里显示缺失信息、触发条件和复查日期。', promptPlace: '影响页右侧要求填写缺失信息与复查计划。', why: ['AI 候选关系还缺直接经营含义。', '研究员没有把它纳入确认集合。', '观察项只提醒后续复查，不改变状态。'], sample: '例：行业资金流变化可能相关，但还不能证明公司订单变化。' },
  { id: 'reject', label: '驳回候选关系', tone: 'neutral', evidence: '研究员判断资料不相关、重复或推理链不成立。', combination: '不进入假设状态，也不影响投资逻辑建议。', hypothesisBefore: '验证中', hypothesisAfter: '不变', thesisBefore: '验证中', thesisSuggestion: '不生成状态变更建议', companySync: '仅保留审计记录，避免同类候选反复打扰。', promptPlace: '影响页右侧要求填写不纳入原因。', why: ['驳回后不参与支持/冲突计数。', '可用于后续改进归并与候选关系召回。', '不会从页面上制造虚假的状态波动。'], sample: '例：宏观新闻过宽泛，无法落到当前公司假设。' },
  { id: 'closed-thesis', label: '投资逻辑已经关闭', tone: 'neutral', evidence: '新证据仍可采集和留存。', combination: '不会自动重新开启或改变关闭状态。', hypothesisBefore: '已关闭', hypothesisAfter: '留存证据', thesisBefore: '已关闭', thesisSuggestion: '不自动重开；可生成“有新资料可复查”提醒', companySync: '公司页保持已关闭；如研究员主动重启，需要在维护页发起新版本或复盘。', promptPlace: '研究记录提示，不进入正式状态变更按钮。', why: ['关闭是人工治理状态。', '新资料可作为复盘材料，但不能自动推翻关闭决策。', '需要研究员主动创建新逻辑版本。'], sample: '例：关闭后的财报新信息只进入历史资料与复盘入口。' },
]

function scenarioToneLabel(tone: StatusScenario['tone']) {
  return tone === 'support' ? '支持' : tone === 'conflict' ? '冲突' : tone === 'mixed' ? '分歧' : tone === 'warning' ? '预警' : '留存'
}

export function StatusInteractionSimulatorPage() {
  const [selectedId, setSelectedId] = useState(statusScenarios[0].id)
  const [decision, setDecision] = useState<'确认纳入' | '暂不判断' | '驳回'>('确认纳入')
  const selected = statusScenarios.find((item) => item.id === selectedId) ?? statusScenarios[0]
  const effective = decision === '确认纳入'
    ? selected
    : decision === '暂不判断'
      ? { ...selected, hypothesisAfter: '待观察', thesisSuggestion: '不生成状态变更建议', companySync: '公司页保持原正式状态；观察原因、触发条件和复查日期写入研究记录。', promptPlace: '只提示后续复查，不出现主逻辑状态变更按钮。', why: ['关系未被纳入确认集合。', '系统保留观察任务，但不参与支持/冲突/失效计算。', '后续满足触发条件后可重新进入判断。'] }
      : { ...selected, hypothesisAfter: '不变', thesisSuggestion: '不生成状态变更建议', companySync: '公司页保持原正式状态；驳回理由写入审计，后续同类噪音可降权。', promptPlace: '只保留驳回记录，不出现主逻辑状态变更按钮。', why: ['关系被研究员驳回。', '驳回证据不进入假设计数。', '不影响投资逻辑正式状态，也不形成待办。'] }
  const actionable = decision === '确认纳入' && ['出现分歧', '重大风险'].some((word) => effective.thesisSuggestion.includes(word))
  return <div className="status-simulator-page">
    <PageTitle eyebrow="STATUS FLOW SANDBOX" title="证据、假设与投资逻辑状态流转沙盘" description="用模拟数据把所有典型组合跑一遍：AI 只生成建议，研究员确认后才会改变正式投资逻辑状态。" actions={<NavLink className="button secondary" to="/workbench">返回工作台</NavLink>} />
    <section className="simulator-truth-card">
      <article><span>真实链路</span><strong>候选关系 → 研究员纳入/观察/驳回 → 假设健康度 → 主逻辑状态建议 → 人工决策</strong><p>当前后端会保存研究决策批次和主逻辑状态建议；假设健康度主要作为批次快照展示，需要继续补成公司页长期状态。</p></article>
      <article><span>同步规则</span><strong>正式状态不会自动改变</strong><p>只有研究员在状态建议上选择“接受”或“修改”，主投资逻辑正式状态才会更新；“拒绝”会保留原状态并写明理由。</p></article>
    </section>
    <section className="status-simulator-layout">
      <aside className="scenario-list" aria-label="状态场景">
        {statusScenarios.map((item) => <button className={item.id === selected.id ? 'active' : ''} type="button" key={item.id} onClick={() => setSelectedId(item.id)}><i className={`tone-${item.tone}`} /> <span>{item.label}</span><b>{scenarioToneLabel(item.tone)}</b></button>)}
      </aside>
      <main className={`scenario-board tone-${effective.tone}`}>
        <header>
          <div><span>当前模拟场景</span><h2>{selected.label}</h2><p>{selected.sample}</p></div>
          <div className="scenario-decision-toggle" role="group" aria-label="研究员关系决策">{(['确认纳入', '暂不判断', '驳回'] as const).map((item) => <button className={decision === item ? 'active' : ''} type="button" key={item} onClick={() => setDecision(item)}>{item}</button>)}</div>
        </header>
        <div className="status-flow-steps">
          <article><span>01 证据处理</span><strong>{decision}</strong><p>{effective.evidence}</p><small>{effective.combination}</small></article>
          <article><span>02 假设状态</span><strong>{effective.hypothesisBefore} → {effective.hypothesisAfter}</strong><p>假设状态是对单条核心假设的健康判断，应该在影响页和公司逻辑页的假设卡上同步提示。</p></article>
          <article className={actionable ? 'needs-action' : ''}><span>03 投资逻辑建议</span><strong>{effective.thesisSuggestion}</strong><p>{actionable ? '达到主逻辑建议阈值，需要负责人选择接受、保持当前或改成其他状态。' : '没有达到正式状态变更阈值时，只做信息沉淀或研究提醒。'}</p></article>
          <article><span>04 页面同步</span><strong>{effective.thesisBefore} / 人工闸门</strong><p>{effective.companySync}</p><small>{effective.promptPlace}</small></article>
        </div>
        <section className="scenario-reasoning">
          <div><span>为什么这样触发</span><ul>{effective.why.map((item) => <li key={item}>{item}</li>)}</ul></div>
          <div><span>推荐交互</span><p>{actionable ? '在影响详情页右侧显示状态建议卡；在公司投资逻辑页顶部同步一条“待决策建议”，研究员处理后写入研究记录。' : '在影响详情页显示处理结果；在公司页假设卡更新本批健康度提示，不强迫研究员做主逻辑状态选择。'}</p></div>
        </section>
      </main>
    </section>
    <section className="status-rule-matrix">
      <header><h2>后端需要稳定输出的状态类型</h2><p>前端只负责清晰呈现，真正可维护的关键是后端每批都返回同一套结构。</p></header>
      <div>
        <article><b>relation_decision</b><span>确认 / 暂不判断 / 驳回</span><p>决定证据是否进入状态计算。</p></article>
        <article><b>hypothesis_health</b><span>加强 / 承压 / 分歧 / 临近失效 / 可能失效 / 不变</span><p>按单条假设独立计算，应该可在公司页长期查看。</p></article>
        <article><b>thesis_status_suggestion</b><span>维持 / 出现分歧 / 重大风险 / 发起评审</span><p>只生成建议，不自动修改正式状态。</p></article>
        <article><b>human_decision</b><span>接受 / 拒绝 / 修改</span><p>研究员最终闸门，写入审计并同步公司页。</p></article>
      </div>
    </section>
  </div>
}

export function NotFoundPage() {
  return <section className="not-found-page"><span className="mono">404 / ROUTE NOT FOUND</span><h1>这个研究页面不存在</h1><p>链接可能已过期，或当前账户没有可访问的对应入口。你可以返回任务工作台继续处理。</p><NavLink className="button primary" to="/workbench">返回工作台</NavLink></section>
}

export function ReviewsPage() {
  return <><ReviewDraftPanel /><ReviewsPageContent /></>
}

export function AssetPage() {
  const qc = useQueryClient()
  const [query, setQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const inventory = useQuery({ queryKey: ['asset-inventory'], queryFn: getAssetInventory })
  const search = useQuery({ queryKey: ['asset-search', submittedQuery], queryFn: () => searchAssets(submittedQuery), enabled: Boolean(submittedQuery) })
  const rebuild = useMutation({ mutationFn: rebuildAssetSearchIndex, onSuccess: async () => { await qc.invalidateQueries({ queryKey: ['asset-inventory'] }); if (submittedQuery) await qc.invalidateQueries({ queryKey: ['asset-search', submittedQuery] }) } })
  if (inventory.isLoading) return <LoadingState />
  if (inventory.error || !inventory.data) return <ErrorState error={inventory.error} />
  const data = inventory.data
  const metrics = [
    ['文档资产', data.documents, '当前数据库中的文档事实'],
    ['已归档原件', data.archivedSourceDocuments, `${data.missingObjectArchive} 份仍待回填`],
    ['授权已核验', data.authorizationVerifiedDocuments, `${data.pendingAuthorization} 份仍待确认`],
    ['标题索引', data.titleIndexDocuments, '仅可按标题检索，不冒充公告正文'],
  ] as const
  return <>
    <PageTitle eyebrow="P1 数据资产治理" title="资产治理" description="盘点原件、授权、内容状态与权限感知索引；回填和重处理只追加新修订与运行，不覆盖历史产物。" actions={<button className="button secondary" disabled={rebuild.isPending} onClick={() => rebuild.mutate()}>{rebuild.isPending ? '重建中…' : '重建检索索引'}</button>} />
    <section className="metric-grid">{metrics.map(([label, value, note]) => <div className="metric-card" key={label}><span>{label}</span><strong>{value}</strong><p>{note}</p></div>)}</section>
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">历史质量盘点</span><h2>治理状态与不可覆盖产物</h2></div></div><div className="asset-quality-grid"><p><strong>{data.revisions}</strong><span>不可变 revision 谱系</span></p><p><strong>{data.ingestionRuns}</strong><span>追加式处理与归档运行</span></p><p><strong>{data.artifactSegments}</strong><span>运行级切片产物</span></p><p><strong>{data.embeddings}</strong><span>版本化 embedding</span></p></div><InlineError error={rebuild.error} />{rebuild.data != null && <p className="success-note">索引已重建，共 {rebuild.data} 个切片。</p>}</section>
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">P1 权限感知混合召回</span><h2>验证可见切片</h2></div></div><form className="asset-search" onSubmit={(event) => { event.preventDefault(); if (query.trim()) setSubmittedQuery(query.trim()) }}><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入信息需求、标题或正文关键词" /><button className="button primary" type="submit" disabled={!query.trim()}>混合召回</button></form><InlineError error={search.error} />{search.isFetching ? <LoadingState /> : submittedQuery && (search.data?.length ? <div className="review-list">{search.data.map((item) => <article className="review-card" key={`${item.documentId}-${item.locator}`}><div className="review-header"><strong>{item.documentId}</strong><div><span className="badge neutral-badge">{item.contentStatus}</span><span className="badge neutral-badge">{item.visibilityLabel}</span></div></div><p>{item.content}</p><small className="muted">定位：{item.locator} · 综合 {item.rank.toFixed(3)} · 关键词 {(item.keywordRank ?? 0).toFixed(3)} · 向量 {(item.vectorRank ?? 0).toFixed(3)} · {item.embeddingVersion}</small></article>)}</div> : <EmptyState title="没有可见命中" description="权限、证券、行业和时间过滤在排序前执行。" />)}</section>
  </>
}

function IngestionReviewCard({ item }: { item: IngestionReview }) {
  const qc = useQueryClient()
  const [securityId, setSecurityId] = useState(item.securityCandidates[0]?.securityId ?? '')
  const [resolution, setResolution] = useState('')
  const mutation = useMutation({ mutationFn: () => resolveIngestionReview(item.reviewId, { resolution, securityId: item.reviewType === 'security_assignment' ? securityId : undefined }), onSuccess: async () => { await Promise.all([qc.invalidateQueries({ queryKey: ['ingestion-reviews'] }), qc.invalidateQueries({ queryKey: ['processing-jobs'] })]) } })
  return <article className="review-card"><div className="review-header"><div><span className={`badge ${item.status === 'pending' ? 'priority-medium' : 'status-confirmed'}`}>{item.status === 'pending' ? '待处理' : '已完成'}</span><h2>{item.reviewType} · {item.documentId}</h2></div></div><p className="review-detail">{item.reason}</p>{item.status === 'pending' ? <div className="review-decision">{item.reviewType === 'security_assignment' && <select value={securityId} onChange={(event) => setSecurityId(event.target.value)}><option value="">不归属证券</option>{item.securityCandidates.map((candidate) => <option key={candidate.securityId} value={candidate.securityId}>{candidate.securityId} · {candidate.name}（匹配 {candidate.matchedTerms.join('、')}）</option>)}</select>}<textarea value={resolution} onChange={(event) => setResolution(event.target.value)} placeholder="填写复核结论（必填）" /><button className="button primary" disabled={resolution.trim().length < 2 || mutation.isPending} onClick={() => mutation.mutate()}>提交并继续处理</button><InlineError error={mutation.error} /></div> : <p className="review-result"><strong>复核结论：</strong>{item.resolution}</p>}</article>
}

function ProcessingJobCard({ job }: { job: ProcessingJob }) {
  const qc = useQueryClient()
  const mutation = useMutation({ mutationFn: () => replayProcessingJob(job.jobId), onSuccess: async () => { await qc.invalidateQueries({ queryKey: ['processing-jobs'] }) } })
  return <article className="review-card"><div className="review-header"><div><span className="badge priority-high">{job.status === 'dead_letter' ? '死信' : '失败'}</span><h2>{job.sourceFilename}</h2></div><span className="muted">第 {job.attemptCount} 次</span></div><p className="review-detail">{job.lastError ?? '未知错误'}</p><button className="button secondary" disabled={mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? '入队中…' : '重放任务'}</button><InlineError error={mutation.error} /></article>
}

function ReviewTaskCard({ task }: { task: ReviewTask }) {
  const qc = useQueryClient()
  const [resolution, setResolution] = useState('')
  const mutation = useMutation({ mutationFn: () => resolveReviewTask(task.taskId, resolution), onSuccess: () => qc.invalidateQueries({ queryKey: ['review-tasks'] }) })
  return <article className="review-card"><div className="review-header"><div><span className={`badge ${task.state === '待处理' ? 'priority-medium' : 'status-confirmed'}`}>{task.state}</span><h2>{task.trigger} · {task.thesisId}</h2></div><div className="button-row"><span className="muted">{task.priority}优先级</span><NavLink className="button secondary" to={`/retrospective/new?thesisId=${encodeURIComponent(task.thesisId)}`}>发起复盘</NavLink></div></div>{task.detail && <p className="review-detail">{Object.entries(task.detail).map(([key, value]) => `${key}: ${String(value)}`).join(' · ')}</p>}{task.state === '待处理' ? <div className="review-decision"><textarea value={resolution} onChange={(event) => setResolution(event.target.value)} placeholder="填写复核结论（必填）" /><button className="button primary" disabled={resolution.trim().length < 2 || mutation.isPending} onClick={() => mutation.mutate()}>提交复核</button><InlineError error={mutation.error} /></div> : <p className="review-result"><strong>复核结论：</strong>{task.resolution}</p>}</article>
}

function AdjudicationCard({ item }: { item: Adjudication }) {
  const qc = useQueryClient()
  const [hypothesis, setHypothesis] = useState(item.annotatorAHypothesis)
  const [direction, setDirection] = useState('中性')
  const [reason, setReason] = useState('')
  const mutation = useMutation({ mutationFn: () => decideAdjudication(item.eventId, { hypothesis, direction, reason }), onSuccess: () => qc.invalidateQueries({ queryKey: ['adjudications'] }) })
  return <article className="review-card"><div className="review-header"><div><span className={`badge ${item.resolved ? 'status-confirmed' : 'priority-medium'}`}>{item.resolved ? '已裁决' : '待裁决'}</span><h2>{item.company} · {item.title}</h2></div><span className="muted">{item.category}</span></div><div className="review-comparison"><p><strong>标注 A</strong>{item.annotatorAHypothesis} · {item.annotatorADirection}</p><p><strong>标注 B</strong>{item.annotatorBHypothesis} · {item.annotatorBDirection}</p></div>{item.resolved ? <p className="review-result"><strong>独立裁决：</strong>{item.decidedHypothesis} · {item.decidedDirection}<br />{item.decisionReason}</p> : <div className="adjudication-form"><label>关联假设<input value={hypothesis} onChange={(event) => setHypothesis(event.target.value)} /></label><label>方向<select value={direction} onChange={(event) => setDirection(event.target.value)}><option>支持</option><option>冲突</option><option>中性</option><option>无关</option></select></label><label className="decision-reason">裁决理由<textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder="独立阅读原文后填写理由" /></label><button className="button primary" disabled={!hypothesis.trim() || reason.trim().length < 2 || mutation.isPending} onClick={() => mutation.mutate()}>提交独立裁决</button><InlineError error={mutation.error} /></div>}</article>
}

function gateValue(value: GoldQualityGate['current']) {
  if (value == null) return '待运行'
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (value > 0 && value < 1) return value.toFixed(4)
  return String(value)
}

export function QualityPage() {
  const report = useQuery({ queryKey: ['gold-quality'], queryFn: getGoldQuality })
  if (report.isLoading) return <LoadingState text="正在读取冻结金标与质量门禁…" />
  if (report.error || !report.data) return <ErrorState error={report.error} />
  const data = report.data
  const summary = data.summary
  const benchmark = data.graphRagBenchmark
  const selectedAgreement = data.agreement.filter((item) => [
    'event.影响方向', 'body_fact.变化方向', 'graph_relevance.相关性等级', 'graph_relevance.关系路径可成立',
  ].includes(`${item.task}.${item.field}`))
  const metrics = [
    ['最终硬金标', summary.goldSamples, `${(summary.goldCoverage * 100).toFixed(0)}% 已完成裁决与冻结`],
    ['独立裁决', summary.adjudicatedSamples, `${summary.consensusSamples} 个双人共识 + ${summary.adjudicatedSamples} 个裁决`],
    ['评测可用', summary.evaluationEligibleSamples, `${summary.totalSamples - summary.evaluationEligibleSamples} 个源文件异常样本仅保留审计`],
    ['Graph RAG 放量', summary.graphRagRolloutReady ? '可放量' : '受控关闭', summary.graphRagRolloutReady ? '全部发布门禁已通过' : benchmark ? '系统基准存在未通过项' : '系统基准尚未运行'],
  ] as const
  return <>
    <PageTitle eyebrow="EVALUATION & RELEASE GATES" title="质量中心" description="把独立金标、评测结果和功能放量条件放在同一条可审计链路中；共识集可评测，最终金标与 Graph RAG 放量必须分别过门禁。" />
    <section className={`quality-release ${summary.graphRagRolloutReady ? 'release-ready' : 'release-blocked'}`}>
      <div><span className="eyebrow">当前发布结论</span><h2>{summary.productionGoldReady ? '最终硬金标已冻结，可进入系统评测' : summary.evaluationReady ? '共识金标已可用于离线评测' : '评测数据尚未就绪'}</h2><p>版本 {data.goldVersion} · 状态 {data.goldState === 'consensus' ? '双人共识冻结' : '161 条分歧已完成独立裁决'} · 生成于 {formatDate(data.createdAt)}</p></div>
      <div className="release-flags"><span className={summary.evaluationReady ? 'flag-passed' : 'flag-blocked'}>离线评测 {summary.evaluationReady ? 'READY' : 'BLOCKED'}</span><span className={summary.productionGoldReady ? 'flag-passed' : 'flag-blocked'}>最终金标 {summary.productionGoldReady ? 'READY' : 'PENDING'}</span><span className={summary.graphRagRolloutReady ? 'flag-passed' : 'flag-blocked'}>GRAPH RAG {summary.graphRagRolloutReady ? 'READY' : 'OFF'}</span></div>
    </section>
    <section className="metric-grid">{metrics.map(([label, value, note]) => <article className="metric-card" key={label}><span>{label}</span><strong>{value}</strong><p>{note}</p></article>)}</section>
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">冻结数据集</span><h2>三类任务覆盖</h2></div><span className="mono muted">{data.sourcePackage}</span></div><div className="quality-task-grid">{data.tasks.map((task) => <article className="quality-task-card" key={task.task}><div><span>{task.label}</span><strong>{task.final} / {task.total}</strong></div><div className="quality-progress" aria-label={`${task.label}最终金标覆盖率 ${(task.coverage * 100).toFixed(1)}%`}><i style={{ width: `${task.coverage * 100}%` }} /></div><p>{task.consensus} 共识 + {task.adjudicated} 裁决 · {task.evaluationEligible} 可评测</p><small>{task.coreFields.join(' · ')}</small></article>)}</div></section>
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">双人一致性</span><h2>关键字段 Cohen&apos;s κ</h2></div><span className="muted">0.60 为本轮稳定性参考线</span></div><div className="quality-agreement-table"><div className="quality-table-head"><span>任务</span><span>字段</span><span>一致率</span><span>Cohen&apos;s κ</span><span>判断</span></div>{selectedAgreement.map((metric) => { const passed = (metric.cohenKappa ?? 0) >= .6; const task = data.tasks.find((item) => item.task === metric.task); return <div key={`${metric.task}-${metric.field}`}><strong>{task?.label ?? metric.task}</strong><span>{metric.field}</span><span>{(metric.agreement * 100).toFixed(1)}%</span><span className="mono">{metric.cohenKappa?.toFixed(4) ?? '—'}</span><span className={`quality-state ${passed ? 'gate-passed' : 'gate-warning'}`}>{passed ? '通过' : '需收敛'}</span></div> })}</div></section>
    {benchmark && <section className="content-section benchmark-section"><div className="section-heading"><div><span className="eyebrow">GRAPH RAG SYSTEM BENCHMARK</span><h2>文本基线与关系图融合实测</h2></div><span className={`quality-state ${benchmark.rolloutReady ? 'gate-passed' : 'gate-warning'}`}>{benchmark.rolloutReady ? '全部通过' : '继续受控'}</span></div><p className="benchmark-intro">最终相关性金标共覆盖 {benchmark.evaluatedQueries} 个查询，其中 {benchmark.positiveQueries} 个包含相关候选。Recall 使用相关集合的宏平均召回率；MRR 使用首个相关结果排名。金标标签不参与建图。</p><div className="benchmark-table"><div><span>指标</span><span>文本基线</span><span>Graph RAG</span><span>目标</span></div><div><strong>Recall@5</strong><span>{(benchmark.textBaseline.recallAtK['5'] * 100).toFixed(2)}%</span><span>{(benchmark.graphRag.recallAtK['5'] * 100).toFixed(2)}%</span><span>≥ 80%</span></div><div><strong>MRR</strong><span>{benchmark.textBaseline.mrr.toFixed(4)}</span><span>{benchmark.graphRag.mrr.toFixed(4)}</span><span>≥ 0.65</span></div><div><strong>NDCG@5</strong><span>{benchmark.textBaseline.ndcgAtK['5'].toFixed(4)}</span><span>{benchmark.graphRag.ndcgAtK['5'].toFixed(4)}</span><span>≥ 0.75</span></div><div><strong>Top-1 正确率</strong><span>{(benchmark.textBaseline.top1Correctness * 100).toFixed(2)}%</span><span>{(benchmark.graphRag.top1Correctness * 100).toFixed(2)}%</span><span>≥ 70%</span></div></div><div className="benchmark-safety"><article><strong>{benchmark.safety.adversarialCanaryCount}</strong><span>对抗诱饵</span></article><article><strong>{benchmark.safety.permissionLeakageCount}</strong><span>权限泄漏</span></article><article><strong>{benchmark.safety.securityLeakageCount}</strong><span>跨证券泄漏</span></article><article><strong>{benchmark.safety.futureLeakageCount}</strong><span>未来信息泄漏</span></article><article><strong>{(benchmark.safety.pathProvenanceRate * 100).toFixed(0)}%</strong><span>路径来源完整</span></article></div>{!benchmark.rolloutReady && <div className="benchmark-failures"><strong>未通过的放量条件</strong>{benchmark.gates.filter((gate) => !gate.passed).map((gate) => <span key={gate.code}><b>{gate.code}</b> · 当前 {gateValue(gate.current)} / 目标 {gateValue(gate.target)}</span>)}</div>}<small className="mono muted">{benchmark.benchmarkVersion} · {benchmark.reportPath}</small></section>}
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">发布门禁</span><h2>可以做什么、还不能做什么</h2></div></div><div className="quality-gates">{data.gates.map((gate) => <article key={gate.code} className={`quality-gate gate-${gate.status}`}><span className="gate-marker">{gate.status === 'passed' ? '✓' : gate.status === 'warning' ? '!' : '×'}</span><div><div className="gate-title"><strong>{gate.label}</strong><span>{gate.status === 'passed' ? '通过' : gate.status === 'warning' ? '注意' : '阻断'}</span></div><p>{gate.message}</p>{(gate.current != null || gate.target != null) && <small className="mono">CURRENT {gateValue(gate.current)} · TARGET {gateValue(gate.target)}</small>}</div></article>)}</div>{data.qualityExceptions.length > 0 && <div className="quality-exceptions"><div><strong>评测排除清单</strong><span>{data.qualityExceptions.length} 条，仅保留审计</span></div>{data.qualityExceptions.map((item) => <p key={`${item.task}-${item.sampleId}`}><span className="mono">{item.sampleId}</span><span>{data.tasks.find((task) => task.task === item.task)?.label}</span><span>{item.reason}</span></p>)}</div>}</section>
  </>
}

function percent(value: number | undefined | null) {
  return value == null ? '—' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`
}

export function QuantPage() {
  const qc = useQueryClient()
  const [quantParams] = useSearchParams()
  const requestedDatasetId = quantParams.get('marketDatasetId') ?? ''
  const catalog = useQuery({ queryKey: ['quant-catalog'], queryFn: getQuantCatalog })
  const history = useQuery({ queryKey: ['quant-portfolio-history'], queryFn: listPortfolioBacktests })
  const [datasetId, setDatasetId] = useState(requestedDatasetId)
  const [signalSetId, setSignalSetId] = useState('')
  const [securityText, setSecurityText] = useState('688981,603986,002371')
  const [rollingDays, setRollingDays] = useState(60)
  const [walkForwardDays, setWalkForwardDays] = useState(20)
  const [rebalanceDays, setRebalanceDays] = useState(5)
  const [costBps, setCostBps] = useState(10)
  const [slippageBps, setSlippageBps] = useState(5)
  const [neutralizeIndustry, setNeutralizeIndustry] = useState(true)
  const [neutralizeMarketCap, setNeutralizeMarketCap] = useState(false)
  const [run, setRun] = useState<PortfolioBacktestRun | null>(null)
  const configuredDefaultDataset = catalog.data?.marketDatasets.find((item) => item.datasetId === catalog.data?.defaultMarketDatasetId)
  const dataset = catalog.data?.marketDatasets.find((item) => item.datasetId === datasetId) ?? configuredDefaultDataset ?? catalog.data?.marketDatasets[0]
  const signalSet = catalog.data?.signalSets.find((item) => item.signalSetId === signalSetId) ?? catalog.data?.signalSets[0]
  useEffect(() => {
    const requestedDataset = catalog.data?.marketDatasets.find((item) => item.datasetId === requestedDatasetId)
    if (requestedDataset && datasetId !== requestedDataset.datasetId) setDatasetId(requestedDataset.datasetId)
    else if (!datasetId && dataset) setDatasetId(dataset.datasetId)
    if (!signalSetId && catalog.data?.signalSets[0]) setSignalSetId(catalog.data.signalSets[0].signalSetId)
  }, [catalog.data, dataset, datasetId, requestedDatasetId, signalSetId])
  useEffect(() => {
    if (!run && history.data?.[0]) setRun(history.data[0])
  }, [history.data, run])
  const register = useMutation({
    mutationFn: registerDefaultMarketDataset,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['quant-catalog'] }),
  })
  const mutation = useMutation({
    mutationFn: () => runPortfolioBacktest({
      name: '版本化组合事件信号研究', marketDatasetId: dataset!.datasetId,
      signalSetId: signalSet!.signalSetId,
      modelTemplateId: 'confirmed-event-research-v3',
      securityIds: securityText.split(',').map((item) => item.trim()).filter(Boolean),
      start: dataset?.coverageStart, end: dataset?.coverageEnd,
      config: {
        initialCapital: 1_000_000, rollingWindowDays: rollingDays, walkForwardDays,
        rebalanceDays, transactionCostBps: costBps, slippageBps,
        maxSecurityWeight: .2, maxIndustryWeight: .4, capacityParticipationRate: .1,
        neutralizeIndustry, neutralizeMarketCap, enforceCapacity: true, allowShort: true,
      },
    }),
    onSuccess: (item) => { setRun(item); qc.invalidateQueries({ queryKey: ['quant-portfolio-history'] }) },
  })
  if (catalog.isLoading || history.isLoading) return <LoadingState />
  if (catalog.error || history.error || !catalog.data) return <ErrorState error={catalog.error ?? history.error} />
  const metrics = run?.result.metrics
  const metricItems = metrics ? [
    ['组合收益', percent(Number(metrics.total_return)), `基准 ${percent(Number(metrics.benchmark_return))}`],
    ['超额收益', percent(Number(metrics.excess_return)), '成本与滑点已计入'],
    ['最大回撤', percent(Number(metrics.max_drawdown)), `跟踪误差 ${percent(Number(metrics.tracking_error))}`],
    ['信息比率', metrics.information_ratio == null ? '—' : Number(metrics.information_ratio).toFixed(2), `Beta ${metrics.beta == null ? '—' : Number(metrics.beta).toFixed(2)}`],
  ] : []
  return <>
    <PageTitle eyebrow="QUANT RESEARCH LAB · P2" title="组合量化验证" description="使用冻结行情与人工确认信号做可复算的样本外验证；结果不生成订单、评级或调仓指令。" actions={!dataset ? <button className="button primary" disabled={register.isPending} onClick={() => register.mutate()}>{register.isPending ? '正在校验…' : '登记默认冻结行情'}</button> : <button className="button primary" disabled={!signalSet || mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? '正在计算…' : '运行组合回测'}</button>} />
    <section className="quality-release release-ready"><div><span className="eyebrow">三轨评测强制隔离</span><h2>语义准确率 · 检索排序 · Alpha 验证</h2><p>{catalog.data.evaluationSeparation.hardRule}</p></div><div className="release-flags"><span className="flag-passed">SEMANTIC 独立</span><span className="flag-passed">RETRIEVAL 独立</span><span className="flag-passed">ALPHA 独立</span></div></section>
    {dataset ? <section className="content-section"><div className="section-heading"><div><span className="eyebrow">冻结数据资产</span><h2>{dataset.dataVersion}</h2></div><span className="flag-passed">{dataset.authorizationStatus}</span></div><div className="quant-summary"><span>复权口径<strong>{dataset.adjustment}</strong></span><span>覆盖区间<strong>{dataset.coverageStart} ~ {dataset.coverageEnd}</strong></span><span>证券数<strong>{dataset.securities.length}</strong></span><span>清单哈希<strong className="mono">{dataset.manifestSha256.slice(0, 12)}</strong></span></div><ul>{dataset.limitations.map((item) => <li key={item}>{item}</li>)}</ul></section> : <EmptyState title="尚未登记冻结行情" description="登记动作会核验授权状态、清单与行情/日历/公司行动三类 SHA-256。" />}
    <section className="quant-config hero-section"><div className="section-heading"><div><span className="eyebrow">组合口径</span><h2>滚动窗口 · 中性化 · 容量约束</h2></div><span className="quant-safety">POINT-IN-TIME · REPRODUCIBLE</span></div><div className="quant-controls"><label>行情版本<select value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>{catalog.data.marketDatasets.map((item) => <option key={item.datasetId} value={item.datasetId}>{item.dataVersion}{item.datasetId === catalog.data.defaultMarketDatasetId ? ' · 默认' : ''}</option>)}</select></label><label>信号集<select value={signalSetId} onChange={(event) => setSignalSetId(event.target.value)}><option value="">请选择人工确认信号集</option>{catalog.data.signalSets.map((item) => <option key={item.signalSetId} value={item.signalSetId}>{item.name} · {item.version}</option>)}</select></label><label>证券代码<input value={securityText} onChange={(event) => setSecurityText(event.target.value)} /></label><label>滚动窗口<input type="number" min="2" max="756" value={rollingDays} onChange={(event) => setRollingDays(Number(event.target.value))} /></label><label>测试窗口<input type="number" min="1" max="252" value={walkForwardDays} onChange={(event) => setWalkForwardDays(Number(event.target.value))} /></label><label>再平衡日<input type="number" min="1" max="252" value={rebalanceDays} onChange={(event) => setRebalanceDays(Number(event.target.value))} /></label><label>成本 bps<input type="number" min="0" max="1000" value={costBps} onChange={(event) => setCostBps(Number(event.target.value))} /></label><label>滑点 bps<input type="number" min="0" max="1000" value={slippageBps} onChange={(event) => setSlippageBps(Number(event.target.value))} /></label><label className="quant-toggle"><input type="checkbox" checked={neutralizeIndustry} onChange={(event) => setNeutralizeIndustry(event.target.checked)} /><span>行业中性</span></label><label className="quant-toggle"><input type="checkbox" checked={neutralizeMarketCap} disabled={!(dataset?.capabilities.point_in_time_market_cap || dataset?.capabilities.a_share_point_in_time_market_cap)} onChange={(event) => setNeutralizeMarketCap(event.target.checked)} /><span>市值中性{dataset?.capabilities.a_share_point_in_time_market_cap && !dataset?.capabilities.point_in_time_market_cap ? '（仅 A 股）' : ''}</span></label></div>{!signalSet && <p className="quant-dataset-note">尚无人工确认且带真实生成时间的冻结信号集。候选信号、语义金标或检索标签不能直接进入 Alpha 验证。</p>}<InlineError error={mutation.error ?? register.error} /></section>
    {!run ? <EmptyState title="尚无版本化组合回测" description="选择冻结行情与人工确认信号集后运行；刷新页面仍可从历史运行恢复。" /> : <>
      <section className="metric-grid quant-metrics">{metricItems.map(([label, value, note]) => <article className="metric-card" key={label}><span>{label}</span><strong>{value}</strong><p>{note}</p></article>)}</section>
      <section className="content-section"><div className="section-heading"><div><span className="eyebrow">WALK-FORWARD</span><h2>滚动样本外窗口</h2></div><span className="mono run-id">{run.runId}</span></div><div className="quant-table-wrap"><table className="quant-table"><thead><tr><th>训练区间</th><th>测试区间</th><th>样本</th><th>组合收益</th><th>基准</th><th>超额</th></tr></thead><tbody>{run.result.walkForward.map((item) => <tr key={`${item.test_start}`}><td>{String(item.train_start)} ~ {String(item.train_end)}</td><td>{String(item.test_start)} ~ {String(item.test_end)}</td><td>{String(item.observation_count)}</td><td>{percent(Number(item.total_return))}</td><td>{percent(Number(item.benchmark_return))}</td><td>{percent(Number(item.excess_return))}</td></tr>)}</tbody></table></div></section>
      <section className="content-section"><div className="section-heading"><div><span className="eyebrow">组合级风险归因</span><h2>行业与证券风险贡献</h2></div><span className="filter-count">IC {run.result.signalResearch.ic == null ? '—' : Number(run.result.signalResearch.ic).toFixed(3)} · Rank IC {run.result.signalResearch.rankIc == null ? '—' : Number(run.result.signalResearch.rankIc).toFixed(3)}</span></div><div className="quality-task-grid">{Object.entries(run.result.riskAttribution.industry).map(([name, value]) => <article className="quality-task-card" key={name}><div><span>{name}</span><strong>{percent(Number(value))}</strong></div><p>年化波动贡献</p></article>)}{Object.entries(run.result.riskAttribution.factorExposure).map(([name, value]) => <article className="quality-task-card" key={name}><div><span>{name}</span><strong>{Number(value).toFixed(3)}</strong></div><p>平均因子暴露</p></article>)}</div></section>
      <section className="content-section quant-methodology"><div><span className="eyebrow">方法与限制</span><h2>{run.methodologyVersion}</h2><p>运行绑定行情清单哈希、信号内容哈希和全部参数；相同输入产生相同 QPF 编号。</p></div><ul>{run.result.diagnostics.warnings.map((warning) => <li key={warning}>{warning}</li>)}{run.result.diagnostics.skippedSignals.map((warning) => <li key={warning}>{warning}</li>)}</ul></section>
    </>}
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">持久化历史</span><h2>我的组合回测</h2></div><span className="filter-count">{history.data?.length ?? 0} 次</span></div>{history.data?.length ? <div className="quant-table-wrap"><table className="quant-table"><thead><tr><th>运行编号</th><th>名称</th><th>方法</th><th>生成时间</th><th>评测轨</th></tr></thead><tbody>{history.data.map((item) => <tr key={item.runId} onClick={() => setRun(item)}><td className="mono">{item.runId}</td><td>{item.name}</td><td>{item.methodologyVersion}</td><td>{formatDate(item.generatedAt)}</td><td>{item.evaluationTrack}</td></tr>)}</tbody></table></div> : <EmptyState title="没有历史运行" description="成功运行后会保存参数、结果与版本哈希。" />}</section>
  </>
}

function SafeSourceLink({ url }: { url: string }) {
  const parsed = (() => { try { return new URL(url) } catch { return null } })()
  const valid = parsed && ['http:', 'https:'].includes(parsed.protocol)
  const isProviderApi = parsed?.hostname === 'data-api.investoday.net'
  return valid && !isProviderApi ? <a className="source-link" href={url} target="_blank" rel="noopener noreferrer">打开外部原文 ↗</a> : <span className="source-link-unavailable">外部原文链接暂未提供</span>
}
