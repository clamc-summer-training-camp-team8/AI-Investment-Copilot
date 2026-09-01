import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { NavLink, useParams, useSearchParams } from 'react-router-dom'
import {
  createRelation, createReviewDraft, deactivateRelation, decideAdjudication, decideStatus, getAudit,
  getDocumentSegment, getEvidence, getEvidenceRetrievalTrace, getRadarEvidence, getRelations, getSuggestions,
  getPublishReadiness, getThesis, getThesisEvidenceFeed, getTrends, getWorkbench, getWorkbenchTasks, recheckThesisQuality,
  listAdjudications, listIngestionReviews, listMetrics, listProcessingJobs, listReviewTasks, listTheses,
  publishThesis, replayProcessingJob, resolveIngestionReview, resolveReviewTask,
  recommendHypothesisMetrics, reviewRelation, saveMetricMapping, updateHypothesis, updateRelation,
  updateThesisMaintenance,
  getAssetInventory, rebuildAssetSearchIndex, searchAssets,
  createThesisRevision, getThesisRevisionDiff, publishThesisRevision, updateThesisRevision,
  getGoldQuality, runQuantBacktest,
  getCompanyMetricCenter, getSecurity, getMaintainedCoverage, getCoverageUniverse, refreshCompanyMetrics,
  createCoverageSector, createCoverageCompany, updateCoverageCompany, updateCoverageSector,
} from './api'
import type { CompanyMetric, Trend } from './types'
import {
  ConfirmDialog, DirectionBadge, EmptyState, ErrorState, EvidenceEventRow,
  InlineError, LoadingState, PageTitle, PriorityBadge, StatusBadge, ValidationChain,
} from './components'
import { MetricEditorCard } from './metric-editor'
import type { Adjudication, EvidenceRetrievalTrace, GoldQualityGate, Hypothesis, IngestionReview, MetricDefinition, ProcessingJob, QuantBacktestRequest, QuantBacktestRun, QuantEquityPoint, Relation, ReviewTask, Security, ThesisDetail, ThesisRevision } from './types'
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

export function WorkbenchPage({ onCreate }: { onCreate?: () => void } = {}) {
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
    <aside className="coverage-panel" aria-label="我的覆盖"><div className="dashboard-panel-title"><h1>我的覆盖</h1><NavLink to="/coverage" aria-label="管理覆盖范围">⚙</NavLink></div>{coverage.isLoading && <div className="coverage-loading" role="status">正在加载维护中的公司…</div>}{coverage.error && <div className="coverage-loading coverage-loading-error">覆盖数据暂时不可用</div>}{coverage.data?.map((industry) => { const expanded = expandedIndustries.size === 0 || expandedIndustries.has(industry.name); return <section className="coverage-group" key={industry.name}><button className="coverage-industry" aria-expanded={expanded} onClick={() => toggleIndustry(industry.name)}><span>{expanded ? '⌄' : '›'} ▥ {industry.name}</span><b>{industry.companies.length}</b></button>{expanded && <div className="coverage-companies">{industry.companies.map((company) => <NavLink to={`/companies/${encodeURIComponent(company.securityId)}`} key={company.securityId}><span><strong>▥ {company.name}</strong><small>{company.industry || '行业分类待补充'}</small></span></NavLink>)}</div>}</section>})}{coverage.data && coverage.data.length === 0 && <div className="coverage-loading">暂无正在维护的公司</div>}<nav className="coverage-links" aria-label="研究功能"><NavLink to="/coverage">⌁ 行业总览</NavLink><NavLink to="/macro-strategy">▧ 宏观与策略</NavLink><NavLink to="/assets">▤ 数据中心</NavLink><NavLink to="/assets">⌕ 知识库</NavLink><NavLink to="/theses">◇ 模型与因子</NavLink><NavLink to="/assets">▱ 研报与文档</NavLink><NavLink to="/radar">♧ 监控与预警</NavLink></nav><button className="new-research-button" onClick={onCreate}>＋ 新建研究主题</button></aside>
    <main className="dashboard-main"><section className="dashboard-card research-feed" aria-labelledby="research-feed-title"><header className="dashboard-card-header"><h2 id="research-feed-title">今日研究动态</h2><button>筛选 ⌄</button></header><div className="feed-tabs" role="tablist" aria-label="动态分类">{['全部', '公司', '行业', '宏观', '政策'].map((tab) => <button role="tab" aria-selected={feedFilter === tab} className={feedFilter === tab ? 'active' : ''} onClick={() => setFeedFilter(tab)} key={tab}>{tab}<span>{tab === '全部' ? 12 : tab === '公司' ? 8 : tab === '行业' ? 2 : 1}</span></button>)}</div><div className="dashboard-feed-list">{filteredEvents.map((item, index) => <article className="dashboard-event" key={`${item.time}-${item.company}`}><time>{item.time}</time><i className={item.direction === '冲突' ? 'conflict' : ''} /><div className="event-copy"><div className="event-meta"><strong>{item.company}</strong><span>{item.source}</span></div><h3>{item.title}</h3><p>相关假设：{item.thesis}</p></div><span className={`importance importance-${item.importance[0]}`}>{item.importance}</span><strong className={`direction-text ${item.direction === '冲突' ? 'conflict' : ''}`}>{item.direction} {item.direction === '支持' ? '↑' : '↓'}</strong><div className="event-actions"><span className={item.status === '研究员确认' ? 'human-label' : 'ai-label'}>{item.status}</span><NavLink to={`/updates/${index + 1}`}>查看影响</NavLink><button>加入证据</button></div></article>)}</div><NavLink className="dashboard-more" to="/updates">查看更多动态 ⌄</NavLink></section>
    <section className="dashboard-card logic-status" aria-labelledby="logic-title"><header className="dashboard-card-header"><h2 id="logic-title">主投资逻辑状态</h2><span>截至今天 10:00</span></header><div className="logic-table" role="table"><div className="logic-table-head" role="row"><span>公司</span><span>当前主投资逻辑</span><span>状态</span><span>最新变化</span><span>操作</span></div>{logicRows.map(([company, logic, status, change]) => <div className="logic-table-row" role="row" key={company}><strong>{company}</strong><span>{logic}</span><b className={`logic-state state-${status}`}>{status}</b><span>{change}</span><NavLink to="/theses">查看演变</NavLink></div>)}</div><NavLink className="dashboard-more" to="/theses">查看全部公司逻辑 ›</NavLink></section>
    <section className="dashboard-card indicator-panel"><header className="dashboard-card-header"><h2>关键指标异动</h2><NavLink to="/radar">更多 ›</NavLink></header>{[['比亚迪', '毛利率（%）', '20.14', '+2.41', 'up'], ['中芯国际', '产能利用率（%）', '92.1', '-3.12', 'down'], ['吉利汽车', '单车均价（万元）', '11.28', '-1.18', 'down']].map(([company, metric, value, delta, trend], index) => <div className="indicator-row" key={company}><strong>{company}</strong><span>{metric}</span><b>{value}</b><svg viewBox="0 0 120 28" aria-label={`${company}${metric}趋势`}><polyline points={index === 0 ? '0,19 12,18 24,20 36,13 48,16 60,5 72,17 84,12 96,18 108,15 120,18' : '0,8 12,11 24,6 36,13 48,10 60,17 72,14 84,20 96,16 108,21 120,18'} /></svg><em className={trend}>{delta} {trend === 'up' ? '↑' : '↓'}</em></div>)}<NavLink className="dashboard-more" to="/radar">查看全部异常指标 ›</NavLink></section></main>
    <aside className="dashboard-right"><section className="dashboard-card attention-card"><header className="dashboard-card-header"><h2>重点关注</h2></header>{[['▥', '3家公司出现重要变化', '查看公司'], ['⚖', '2条强反证', '查看证据'], ['⌁', '1个关键指标触及阈值', '查看指标']].map(([icon, label, action], index) => <div className={`attention-row attention-${index}`} key={label}><i>{icon}</i><strong>{label}</strong><button>{action}</button></div>)}</section><section className="dashboard-card todo-card"><header className="dashboard-card-header"><h2>今日待办</h2><NavLink to="/reviews">更多 ›</NavLink></header>{[['高优先级', '比亚迪：业绩预告超预期，更新盈利预测', '今天 11:30', '去复核'], ['高优先级', '中芯国际：产能利用率提升，验证持续性', '今天 14:00', '去复核'], ['中优先级', '恒瑞医药：III期临床进展影响评估', '今天 16:00', '去复核'], ['中优先级', '新能源汽车行业：价格战跟踪与影响评估', '明天 09:30', '去处理'], ['低优先级', '宏观：4月经济数据解读', '明天 10:30', '去阅读']].map(([level, title, due, action]) => <article className="todo-row" key={title}><span className={`todo-level level-${level[0]}`}>{level}</span><strong>{title}</strong><small>截至时间：{due}</small><button>{action}</button></article>)}</section><section className="dashboard-card risk-panel"><header className="dashboard-card-header"><h2>强反证与风险</h2><NavLink to="/radar">更多 ›</NavLink></header>{[['高风险', '新能源汽车价格战加剧', '多地出台促销政策，终端折扣扩大'], ['高风险', '中芯国际先进制程扩产不及预期', '海外设备限制与良率爬坡影响产能释放'], ['中风险', '恒瑞医药创新药研发不及预期', '核心管线临床失败或竞争加剧带来不确定性'], ['中风险', '全球宏观需求走弱', '海外经济放缓可能影响出口与企业盈利']].map(([level, title, note]) => <article className="risk-row" key={title}><i>!</i><div><strong>{title}</strong><p>{note}</p></div><span>{level}</span></article>)}<NavLink className="dashboard-more" to="/radar">查看全部风险 ›</NavLink></section></aside>
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

export function ResearchUpdatesPage() {
  const [filter, setFilter] = useState('全部')
  const [query, setQuery] = useState('')
  const visible = researchUpdates.filter((item) => (filter === '全部' || filter === item.type || filter === item.status) && `${item.company}${item.title}${item.source}`.includes(query))
  return <div className="updates-page"><header className="updates-page-header"><div><NavLink to="/workbench">← 返回工作台</NavLink><span>RESEARCH UPDATE STREAM</span><h1>全部研究动态</h1><p>集中查看系统实时检索到的公告、新闻、研报和行业数据，以及它们与现有投资逻辑的候选影响关系。</p></div><div className="updates-summary"><article><strong>{researchUpdates.length}</strong><span>最新动态</span></article><article><strong>{researchUpdates.filter((item) => item.status === '待确认').length}</strong><span>待确认</span></article><article><strong>{researchUpdates.filter((item) => item.direction === '冲突').length}</strong><span>冲突影响</span></article></div></header><main className="updates-layout"><aside className="updates-filter-panel"><h2>动态范围</h2>{['全部','公司','行业','政策','研报','调研','待确认','已确认'].map((item) => <button key={item} className={filter === item ? 'active' : ''} onClick={() => setFilter(item)}><span>{item}</span><b>{item === '全部' ? researchUpdates.length : researchUpdates.filter((update) => update.type === item || update.status === item).length}</b></button>)}<div><span>检索处理状态</span><strong><i /> 实时运行中</strong><small>最近更新：刚刚</small></div></aside><section className="updates-list-panel"><header><label><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索公司、事件或信息来源" /></label><button>时间范围：近7天⌄</button><button>重要性⌄</button></header><div className="updates-list-head"><span>时间</span><span>最新动态与候选影响</span><span>重要性</span><span>方向</span><span>状态</span><span>操作</span></div>{visible.map((item) => <article className="update-list-row" key={item.id}><time>{item.time}</time><div><div><strong>{item.company}</strong><span>{item.source}</span></div><h2>{item.title}</h2><p>候选关联：{item.thesis} / {item.hypothesis}</p></div><b className={`update-priority priority-${item.importance}`}>{item.importance}</b><em className={item.direction === '冲突' ? 'conflict' : 'support'}>{item.direction}</em><span className={`update-status status-${item.status}`}>{item.status}</span><NavLink to={`/updates/${item.id}`}>查看影响 →</NavLink></article>)}{!visible.length && <div className="updates-empty">没有符合当前条件的动态</div>}<footer><span>共 {visible.length} 条动态</span><div><button disabled>‹</button><b>1</b><button disabled>›</button></div></footer></section></main></div>
}

export function ResearchImpactDetailPage() {
  const { updateId = '1' } = useParams()
  const item = researchUpdates.find((update) => update.id === updateId) ?? researchUpdates[0]
  const [decision, setDecision] = useState('')
  return <div className="impact-page"><header className="impact-page-header"><div><NavLink to="/updates">← 返回全部动态</NavLink><span>IMPACT REVIEW / {item.id.padStart(4,'0')}</span><h1>具体影响分析</h1></div><div><span className={`update-status status-${item.status}`}>{item.status}</span><small>AI关系置信度</small><strong>{item.confidence}%</strong></div></header><main className="impact-page-layout"><div className="impact-main-column"><section className="impact-fact-card"><header><div><span>01 / 原始事实</span><h2>{item.title}</h2></div><button>打开原文 ↗</button></header><p>系统从公开来源中识别出该事件。下面展示的是原始信息及可追溯定位，AI候选关系不会在研究员确认前修改任何投资逻辑。</p><dl><div><dt>公司／行业</dt><dd>{item.company}</dd></div><div><dt>来源</dt><dd>{item.source}</dd></div><div><dt>发布时间</dt><dd>{item.time}</dd></div><div><dt>信息类型</dt><dd>{item.type}</dd></div></dl><blockquote>“{item.title}”。该信息已完成来源、发布时间和研究对象识别，等待研究员判断其研究影响。</blockquote><footer>来源定位：公开信息正文第1段 <button>查看上下文</button></footer></section><section className="impact-relation-card"><header><div><span>02 / AI候选关系</span><h2>事件如何影响现有投资逻辑</h2></div><button>✎ 编辑路径</button></header><div className="impact-relation-flow"><article><span>事件事实</span><strong>{item.title}</strong></article><i>→</i><article><span>验证指标</span><strong>{item.metric}</strong><small>识别到指标变化</small></article><i>→</i><article><span>核心假设</span><strong>{item.hypothesis}</strong></article><i>→</i><article><span>投资逻辑</span><strong>{item.thesis}</strong><small>{item.company}</small></article></div><div className="impact-assessment-grid"><article><span>影响方向</span><strong className={item.direction === '冲突' ? 'conflict' : 'support'}>{item.direction}</strong></article><article><span>影响强度</span><strong>{item.importance}</strong></article><article><span>关系置信度</span><strong>{item.confidence}%</strong></article><article><span>逻辑状态建议</span><strong>{item.direction === '冲突' ? '逻辑承压' : '证据增强'}</strong></article></div><div className="impact-reason"><strong>AI判断理由</strong><p>该事件直接涉及“{item.metric}”，能够用于验证“{item.hypothesis}”，因此建议作为{item.direction}证据关联到“{item.thesis}”。</p></div></section></div><aside className="impact-review-panel"><section><span>03 / 研究员确认</span><h2>这条影响是否成立？</h2><p>确认后，系统才会将信息加入证据、刷新假设状态并生成复盘记录。</p><label>关联投资逻辑<select defaultValue={item.thesis}><option>{item.thesis}</option><option>选择其他逻辑</option></select></label><label>影响方向<select defaultValue={item.direction}><option>支持</option><option>冲突</option><option>中性</option></select></label><label>影响强度<select defaultValue={item.importance}><option>高</option><option>中</option><option>低</option></select></label><label>研究员备注<textarea placeholder="填写判断依据或修改原因" /></label><div className="impact-review-actions"><button onClick={() => setDecision('暂不判断')}>暂不判断</button><button onClick={() => setDecision('已驳回')}>驳回</button><button onClick={() => setDecision('已确认')} className="primary">确认影响</button></div>{decision && <div className="impact-decision-result" role="status"><strong>✓ {decision}</strong><span>已生成研究处理记录；当前为静态演示。</span></div>}</section><section className="impact-after-confirm"><h2>确认后将发生</h2><ol><li><b>1</b><span>证据写入对应核心假设</span></li><li><b>2</b><span>指标和逻辑状态重新计算</span></li><li><b>3</b><span>自动生成研究变更记录</span></li><li><b>4</b><span>进入后续复盘时间线</span></li></ol></section></aside></main></div>
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
        <div className="coverage-company-table" role="table" aria-label={`${currentIndustry.name}公司列表`}><div className="coverage-company-head" role="row"><span>公司</span><span>市场</span><span>研究负责人</span><span>投资逻辑</span><span>覆盖状态</span><span>最近更新</span><span>操作</span></div>{companies.map((company) => <article className="coverage-company-row" role="row" key={company.id}><div className="coverage-company-name"><i>{company.name.slice(0,1)}</i><span><strong>{company.name}</strong><small>{company.code}</small><small className="company-industry-caption" title={company.industry || '行业分类待补充'}>{company.industry || '行业分类待补充'}</small></span></div><span>{company.market}</span><div className="coverage-owner"><i>{company.owner.slice(0,1)}</i><span>{company.owner}</span></div><b className={company.thesisCount ? '' : 'empty'}>{company.thesisCount} 条</b><em className={`coverage-status status-${company.status}`}>{company.status}</em><time>{company.updated}</time><div className="coverage-row-actions">{onCreate ? <button onClick={() => onCreate({ securityId: company.securityId, name: company.name, ticker: company.code, industry: company.industry })}>进入研究</button> : <NavLink to={`/companies/${encodeURIComponent(company.securityId)}`}>进入研究</NavLink>}<button className="coverage-pause-button" disabled={updateCompanyMutation.isPending} onClick={() => toggleCoverage(company)}>{company.status === '暂停覆盖' ? '恢复覆盖' : '暂停覆盖'}</button></div></article>)}</div>
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

type ResearchMetricRow = [string, string, string, string]
type ResearchEvidenceRow = [string, string, string]
type ResearchHypothesisView = { id: string; title: string; state: string; tone: 'support' | 'conflict' | 'pending' }
type ResearchView = { hypotheses: ResearchHypothesisView[]; metrics: Record<string, ResearchMetricRow[]>; evidence: Record<string, ResearchEvidenceRow[]> }
type CompanyThesisView = { id: string; title: string; horizon: string; direction: string; health: string; confidence?: number; summary: string; record?: ThesisDetail }

function normalizeResearchView(value: { hypotheses: readonly { id: string; title: string; state: string; tone: string }[]; metrics: Readonly<Record<string, ReadonlyArray<ReadonlyArray<string>>>>; evidence: Readonly<Record<string, ReadonlyArray<ReadonlyArray<string>>>> }): ResearchView {
  return {
    hypotheses: value.hypotheses.map((item) => ({ ...item, tone: item.tone === 'support' || item.tone === 'conflict' ? item.tone : 'pending' })),
    metrics: Object.fromEntries(Object.entries(value.metrics).map(([key, rows]) => [key, rows.map((row) => [String(row[0]), String(row[1]), String(row[2]), String(row[3])] as ResearchMetricRow)])),
    evidence: Object.fromEntries(Object.entries(value.evidence).map(([key, rows]) => [key, rows.map((row) => [String(row[0]), String(row[1]), String(row[2])] as ResearchEvidenceRow)])),
  }
}

function metricRowFromTrend(item: Trend): ResearchMetricRow {
  const latest = item.points.at(-1)?.value
  const previous = item.points.at(-2)?.value
  const latestNumber = latest == null ? Number.NaN : Number(latest)
  const previousNumber = previous == null ? Number.NaN : Number(previous)
  const delta = Number.isFinite(latestNumber) && Number.isFinite(previousNumber) && previousNumber !== 0
    ? `${latestNumber - previousNumber >= 0 ? '+' : ''}${(((latestNumber - previousNumber) / Math.abs(previousNumber)) * 100).toFixed(2)}%`
    : '—'
  const state = item.verdict?.includes('冲突') ? '冲突' : item.verdict?.includes('支持') ? '支持' : '待验证'
  return [item.metricName || item.metricId, latest ?? '—', delta, state]
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

export function CompanyResearchPage({ onUpload, onCreate }: { onUpload?: (thesisId?: string, securityId?: string) => void; onCreate?: (security?: Security) => void } = {}) {
  const { securityId: routeSecurityId } = useParams()
  const [companyParams, setCompanyParams] = useSearchParams()
  const isDemoGeely = routeSecurityId === 'geely'
  const securityId = isDemoGeely ? '00175' : routeSecurityId ?? ''
  const [companyTab, setCompanyTab] = useState(companyParams.get('tab') || '投资逻辑')
  const security = useQuery({ queryKey: ['security', securityId], queryFn: () => getSecurity(securityId), enabled: Boolean(securityId) && !isDemoGeely })
  const companyMetrics = useQuery({ queryKey: ['company-metric-center', securityId], queryFn: () => getCompanyMetricCenter(securityId), enabled: Boolean(securityId) && !isDemoGeely, refetchInterval: 60_000 })
  const maintainedTheses = useQuery({ queryKey: ['company-theses', securityId], queryFn: () => listTheses(securityId, false, true), enabled: Boolean(securityId) && !isDemoGeely })
  const [activeThesis, setActiveThesis] = useState('product')
  const [activeHypothesis, setActiveHypothesis] = useState('H2')
  const [showEditDialog, setShowEditDialog] = useState(false)
  useEffect(() => {
    if (isDemoGeely) return
    const first = maintainedTheses.data?.[0]
    if (first && !maintainedTheses.data?.some((item) => item.thesisId === activeThesis)) setActiveThesis(first.thesisId)
  }, [activeThesis, isDemoGeely, maintainedTheses.data])
  const activeRecord = maintainedTheses.data?.find((item) => item.thesisId === activeThesis) ?? maintainedTheses.data?.[0]
  useEffect(() => {
    const first = isDemoGeely ? 'H2' : activeRecord?.hypotheses[0]?.hypothesisId
    const ids = isDemoGeely ? ['H1', 'H2', 'H3'] : activeRecord?.hypotheses.map((item) => item.hypothesisId) ?? []
    if (first && !ids.includes(activeHypothesis)) setActiveHypothesis(first)
  }, [activeHypothesis, activeRecord, isDemoGeely])
  const trends = useQuery({ queryKey: ['company-thesis-trends', activeRecord?.thesisId], queryFn: () => getTrends(activeRecord!.thesisId), enabled: Boolean(activeRecord) && !isDemoGeely })
  const evidenceFeed = useQuery({ queryKey: ['company-thesis-evidence', activeRecord?.thesisId], queryFn: () => getThesisEvidenceFeed(activeRecord!.thesisId), enabled: Boolean(activeRecord) && !isDemoGeely })
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
    hypotheses: activeRecord.hypotheses.map((item) => ({ id: item.hypothesisId, title: item.statement, state: item.status, tone: item.status.includes('冲突') ? 'conflict' : item.status.includes('支持') ? 'support' : 'pending' })),
    metrics: Object.fromEntries(activeRecord.hypotheses.map((item) => [item.hypothesisId, (trends.data ?? []).filter((trend) => trend.hypothesisId === item.hypothesisId && trend.metricId).map(metricRowFromTrend)])),
    evidence: Object.fromEntries(activeRecord.hypotheses.map((item) => [item.hypothesisId, (evidenceFeed.data?.items ?? []).filter((feed) => feed.hypothesisId === item.hypothesisId).map((feed) => [feed.direction === 'support' ? '支持' : feed.direction === 'conflict' ? '冲突' : '待验证', feed.sourceDocumentTitle, `公开资料 · ${formatDate(feed.disclosedAt)}`] as ResearchEvidenceRow)])),
  } : undefined
  const availableTheses: CompanyThesisView[] = isDemoGeely ? companyTheses.map((item) => ({ ...item })) : (maintainedTheses.data ?? []).map(dynamicThesisView)
  const thesis = availableTheses.find((item) => item.id === activeThesis) ?? availableTheses[0]
  const research = isDemoGeely ? staticResearch : dynamicResearch
  const selected = research?.hypotheses.find((item) => item.id === activeHypothesis) ?? research?.hypotheses[0]
  const metrics = selected ? research?.metrics[selected.id] ?? [] : []
  const evidence = selected ? research?.evidence[selected.id] ?? [] : []
  const chooseThesis = (id: string) => { setActiveThesis(id); const target = availableTheses.find((item) => item.id === id); setActiveHypothesis(target?.record?.hypotheses[0]?.hypothesisId ?? 'H2') }
  const displaySecurity = security.data ?? (isDemoGeely ? { securityId: '00175', name: '吉利汽车', ticker: '0175.HK', industry: '汽车' } : undefined)
  const closeMetric = companyMetrics.data?.metrics.find((item) => item.metricId === 'MKT-CLOSE-D')
  const returnMetric = companyMetrics.data?.metrics.find((item) => item.metricId === 'MKT-CHANGE-PCT-D')
  if (!isDemoGeely && (security.isLoading || maintainedTheses.isLoading)) return <LoadingState />
  if (!isDemoGeely && (security.error || maintainedTheses.error)) return <ErrorState error={security.error ?? maintainedTheses.error} />
  return <div className="company-research-page">
    <header className="company-identity">
      <NavLink className="company-back" to="/workbench" aria-label="返回工作台">‹</NavLink><div className="company-emblem">{displaySecurity?.name.slice(0, 1) || '研'}</div><div className="company-name"><span>公司研究 / {displaySecurity?.industry || '待分类'}</span><h1>{displaySecurity?.name || securityId} <small>{displaySecurity?.ticker || securityId}</small></h1></div>
      <div className="company-quote"><span>最新收盘价</span><strong>{formatCompanyNumber(closeMetric?.latestValue)} <small>{closeMetric?.unit || '—'}</small></strong><em>{returnMetric ? `${formatCompanyNumber(returnMetric.latestValue)}%` : '—'}</em></div><div className="company-stat"><span>投资评级</span><strong>{thesis?.record?.investmentRating || thesis?.direction || '待研究员填写'}</strong></div><div className="company-stat"><span>目标价（12个月）</span><strong>{thesis?.record?.targetPrice ? formatCompanyNumber(thesis.record.targetPrice) : '—'}</strong></div><div className="company-stat"><span>分析师</span><strong>{thesis?.record?.owner || '张明'}</strong></div><div className="company-stat"><span>数据更新</span><strong>{companyMetrics.data?.updatedAt || '尚未同步'}</strong></div>
      <div className="company-actions"><button onClick={() => onUpload?.(activeRecord?.thesisId, securityId)}>添加资料</button><button className="primary" onClick={() => onCreate?.(displaySecurity)}><span aria-hidden>＋</span>新建逻辑</button></div>
    </header>
    <nav className="company-tabs" aria-label="公司研究导航">{['总览', '投资逻辑', '事件与证据', '指标中心', '资料库', '研究记录'].map((item) => <button className={item === companyTab ? 'active' : ''} key={item} onClick={() => { setCompanyTab(item); setCompanyParams(item === '投资逻辑' ? {} : { tab: item }) }}>{item}</button>)}</nav>
    {companyTab === '指标中心' ? <CompanyMetricCenterPanel securityId={securityId} /> : <main className="company-canvas">
      {!thesis || !research || !selected ? <EmptyState title="尚未建立投资逻辑" description="该证券已建档，但数据库中暂时没有可展示的投资逻辑。" /> : <>
      <section className="thesis-switcher" aria-label="投资逻辑选择">{availableTheses.map((item) => <button key={item.id} className={activeThesis === item.id ? 'active' : ''} onClick={() => chooseThesis(item.id)} aria-pressed={activeThesis === item.id}><strong>{item.title}</strong><span><i className={`dot ${item.health === '证据不足' ? 'warning' : ''}`} />{item.direction} · {item.health} · {item.confidence == null ? '待计算' : `${item.confidence}%`}</span></button>)}</section>
      <section className="active-thesis-summary"><div><div className="summary-meta"><span>{thesis.horizon}</span><b>{thesis.direction}</b><b>{thesis.health}</b></div><h2>{thesis.summary}</h2></div><div className="confidence-block"><span>逻辑置信度 ⓘ</span><strong>{thesis.confidence == null ? '—' : `${thesis.confidence}%`}</strong><i><b style={{ width: `${thesis.confidence ?? 0}%` }} /></i></div><dl><div><dt>逻辑负责人</dt><dd>{thesis.record?.owner || '张明'}</dd></div><div><dt>最后更新</dt><dd>{thesis.record?.establishedOn || '2025-05-20'}</dd></div></dl><button className="edit-thesis" disabled={!activeRecord} onClick={() => setShowEditDialog(true)}>✎ 编辑逻辑</button></section>
       <div className="company-research-grid"><section className="hypothesis-panel"><header><h2>核心假设</h2><button>＋ 添加假设</button></header><div className="hypothesis-list">{research.hypotheses.map((item) => <button key={item.id} className={selected.id === item.id ? 'active' : ''} onClick={() => setActiveHypothesis(item.id)}><div className="hypothesis-card-copy"><span className={isDemoGeely ? 'hypothesis-index' : 'hypothesis-id'}>{item.id}</span><strong>{item.title}</strong></div><em className={item.tone}>{item.state}</em></button>)}</div><button className="view-all-hypotheses">查看全部假设（{research.hypotheses.length}）⌄</button></section>
         <section className="verification-panel"><header><div><span>当前验证对象</span><h2><span className="hypothesis-id">{selected.id}</span><span>{selected.title}</span></h2></div><button>收起⌃</button></header><h3>关键指标</h3><div className="metric-table"><div className="metric-table-head"><span>指标</span><span>最新值</span><span>趋势（vs 前值）</span><span>状态</span></div>{metrics.map(([name, value, delta, state]) => <div className="metric-table-row" key={name}><strong>{name}</strong><b>{value}</b><em className={state === '支持' ? 'support' : state === '冲突' ? 'conflict' : 'pending'}>{delta}</em><span className={state === '支持' ? 'support' : state === '冲突' ? 'conflict' : 'pending'}>{state}</span></div>)}</div><h3>证据验证 <small>（{evidence.length}）</small></h3><div className="company-evidence-list">{evidence.map(([state, title, source]) => <article key={title}><i className={state === '支持' ? 'support' : state === '冲突' ? 'conflict' : 'pending'}>{state === '支持' ? '↗' : state === '冲突' ? '!' : '?'}</i><div><strong>{title}</strong><span>来源：{source}</span></div><b className={state === '支持' ? 'support' : state === '冲突' ? 'conflict' : 'pending'}>{state}</b></article>)}</div></section>
        <aside className="company-side-column"><section><header><h2>催化剂与风险</h2><button>⌃</button></header><h3 className="support-text">催化剂</h3><ul><li>新车型密集上市（银河星舰7/极氪007GT等）</li><li>海外市场放量超预期</li><li>电池成本下降超预期</li></ul><h3 className="conflict-text">风险</h3><ul><li>行业价格战加剧，折扣率继续上行</li><li>海外地缘政治及关税风险</li><li>原材料价格大幅上涨</li></ul></section><section><header><h2>待复核事项 <small>2</small></h2></header><label><input type="checkbox" />5月中旬渠道调研更新终端折扣率数据<time>05-28</time></label><label><input type="checkbox" />Q2订单跟踪与交付节奏复核<time>06-10</time></label></section><section><header><h2>近期关键节点</h2></header><ol><li><time>2025-05-22</time>2025年Q1业绩发布</li><li><time>2025-06-10</time>5月销量发布</li><li><time>2025-06-18</time>证券机构策略会</li></ol></section></aside>
      </div>
      <section className="company-version"><header><h2>逻辑版本记录</h2><button>查看全部版本⌃</button></header><div><strong>{isDemoGeely ? 'v1.2（当前）' : `v${thesis.record?.version ?? 0}（当前）`}</strong><span>{isDemoGeely ? '下调单车收入预期；更新4月销量与折扣率数据；补充渠道反馈证据' : `数据库记录 · ${thesis.record?.status || '草稿'}`}</span><span>{thesis.record?.owner || '张明'}</span><time>{thesis.record?.establishedOn || '2025-05-20'}</time><b>{thesis.confidence == null ? '—' : `${thesis.confidence}%`}</b><button>查看详情</button></div></section>
      </>}
    </main>}
    {showEditDialog && activeRecord && <EditLogicDialog thesis={activeRecord} onClose={() => setShowEditDialog(false)} />}
  </div>
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
  return <><PageTitle eyebrow="研究覆盖" title="投资逻辑" description="选择一条逻辑查看观点健康度、关键假设和证据变化。" /><div className="thesis-grid">{query.data.map((item) => <NavLink className="thesis-card" to={`/theses/${item.thesisId}`} key={item.thesisId}><div><span className="security-code">{item.securityId}</span><span className={`thesis-status thesis-${item.status}`}>{item.status}</span></div><h2>{item.title}</h2><p>{item.coreView}</p><footer><span>负责人：{item.owner}</span><span>查看逻辑 →</span></footer></NavLink>)}</div></>
}

export function ThesisPage() {
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
    <PageTitle eyebrow={`${item.securityId} · V${item.version}`} title={item.title} description={item.coreView} actions={<NavLink className="button secondary" to={`/radar?thesisId=${encodeURIComponent(thesisId)}`}>查看变化雷达</NavLink>} />
    <StageBar status={item.status} />
    <section className="logic-overview"><div><span>当前结论</span><strong>{item.direction}</strong><small>{item.status}</small></div><div><span>支持证据</span><strong className="positive">{counts.support}</strong><small>人工已确认</small></div><div><span>冲突证据</span><strong className="negative">{counts.conflict}</strong><small>人工已确认</small></div><div><span>待核验</span><strong>{counts.pending}</strong><small>需要研究员处理</small></div><div><span>下次复核</span><strong className="date-value">{formatDate(item.nextReviewAt)}</strong><small>负责人 {item.owner}</small></div></section>
    {risk && <section className="risk-callout"><div><span className="risk-icon">!</span><div><strong>当前最大风险</strong><p>{risk.sourceDocumentTitle} · 影响“{risk.hypothesisStatement}”</p></div></div><NavLink to={`/radar/${risk.evidenceId}?thesisId=${thesisId}&relationId=${risk.relationId}`}>立即核验 →</NavLink></section>}
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">逻辑链</span><h2>关键假设健康度</h2></div>{item.status === '草稿' && <button className="button secondary" disabled={qualityCheck.isPending} onClick={() => qualityCheck.mutate()}>{qualityCheck.isPending ? '检查中…' : '重新检查假设逻辑'}</button>}</div><div className="hypothesis-grid">{item.hypotheses.map((hypothesis) => { const related = evidence.filter((x) => x.hypothesisId === hypothesis.hypothesisId); const metrics = trends.data?.filter((trend) => trend.hypothesisId === hypothesis.hypothesisId) ?? []; return <article className="hypothesis-card" key={hypothesis.hypothesisId}><div><span className="importance">{hypothesis.importance}</span>{(hypothesis.logicDimension || hypothesis.causalLevel) && <span className="hypothesis-status">{hypothesis.logicDimension || hypothesis.causalLevel}</span>}<span className="hypothesis-status">{hypothesis.status}</span></div><h3>{hypothesis.statement}</h3>{hypothesis.qualityWarning && <p className="warning-note">{hypothesis.qualityWarning}</p>}<div className="hypothesis-metrics"><strong>验证指标</strong>{metrics.length ? metrics.map((metric) => <div key={`${metric.hypothesisId}-${metric.metricId}`}><span>{metric.metricName || metric.metricId}（{metric.metricId}）</span>{metric.points.length > 0 && <MiniHistoryChart observations={metric.points.map((point) => ({ period: point.period, value: point.value }))} unit={metric.unit} />}{metric.note && <small>{metric.note}</small>}</div>) : <span>尚未配置指标</span>}</div><footer><span className="positive">支持 {related.filter((x) => x.direction === 'support' && x.confirmationStatus === 'confirmed').length}</span><span className="negative">冲突 {related.filter((x) => x.direction === 'conflict' && x.confirmationStatus === 'confirmed').length}</span><span>待确认 {related.filter((x) => x.confirmationStatus === 'pending').length}</span></footer></article> })}</div></section>
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
  return <>
    <section className="content-section draft-config"><div className="section-heading"><div><span className="eyebrow">人工配置</span><h2>假设、指标与失效条件</h2></div><span className="muted">草稿阶段：可在每条假设下重新推荐相关指标</span></div>
      <label className="metric-search">搜索指标字典<input value={metricKeyword} onChange={(event) => setMetricKeyword(event.target.value)} placeholder="输入指标名称或 ID" /></label>
      <InlineError error={metrics.error} />
      <div className="hypothesis-editor-list">{thesis.hypotheses.map((hypothesis) => <HypothesisEditor key={hypothesis.hypothesisId} thesisId={thesis.thesisId} hypothesis={hypothesis} metrics={metrics.data ?? []} trend={trends.data?.find((item) => item.hypothesisId === hypothesis.hypothesisId)} />)}</div>
      {(thesis.riskSuggestions.length > 0 || thesis.invalidationSuggestions.length > 0) && <div className="ai-candidate-panel"><strong>AI 风险与失效建议（待人工判断）</strong>{[...thesis.riskSuggestions, ...thesis.invalidationSuggestions].map((item, index) => <p key={index}>{String(item.statement ?? '未提供建议文本')}</p>)}</div>}
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
  const theses = useQuery({ queryKey: ['target-theses', evidence.data?.securityId], queryFn: () => listTheses(evidence.data!.securityId), enabled: Boolean(evidence.data?.securityId) })
  // 可编辑目标必须由后端按当前身份过滤，前端不再依赖写死的负责人账号。
  const manageableTheses = useQuery({ queryKey: ['manageable-theses', evidence.data?.securityId], queryFn: () => listTheses(evidence.data!.securityId, true), enabled: Boolean(evidence.data?.securityId) })
  const activeRelation = relations.data?.find((item) => item.relationId === requestedRelationId) ?? relations.data?.find((item) => item.status !== 'deactivated')
  const activeFeed = useQuery({ queryKey: ['thesis-evidence-feed', activeRelation?.thesisId], queryFn: () => getThesisEvidenceFeed(activeRelation!.thesisId), enabled: Boolean(activeRelation?.thesisId) })
  const [dialog, setDialog] = useState<{ relation: Relation; action: '确认' | '驳回' | '暂不判断' | '解除' } | null>(null)
  const [editing, setEditing] = useState<Relation | null>(null)
  const context = activeFeed.data?.items.find((item) => item.evidenceId === evidenceId && item.relationId === activeRelation?.relationId)
  const invalidate = async () => { await Promise.all([qc.invalidateQueries({ queryKey: ['relations', evidenceId] }), qc.invalidateQueries({ queryKey: ['workbench-tasks'] }), qc.invalidateQueries({ queryKey: ['workbench'] }), qc.invalidateQueries({ queryKey: ['radar-evidence'] }), qc.invalidateQueries({ queryKey: ['thesis-evidence-feed'] }), qc.invalidateQueries({ queryKey: ['suggestions'] })]) }
  const action = useMutation({ mutationFn: async (input: { relation: Relation; action: string; reason: string }) => input.action === '解除' ? deactivateRelation(evidenceId, input.relation.relationId, input.reason) : reviewRelation(evidenceId, input.relation.relationId, input.action, input.reason), onSuccess: async () => { setDialog(null); await invalidate() } })
  if (evidence.isLoading || relations.isLoading || theses.isLoading || manageableTheses.isLoading) return <LoadingState />
  if (evidence.error || relations.error || theses.error || manageableTheses.error || !evidence.data || !relations.data || !theses.data || !manageableTheses.data) return <ErrorState error={evidence.error ?? relations.error ?? theses.error ?? manageableTheses.error} />
  const item = evidence.data
  const thesisMap = new Map(theses.data.map((thesis) => [thesis.thesisId, thesis]))
  const activeThesis = activeRelation ? thesisMap.get(activeRelation.thesisId) : undefined
  const activeHypothesis = activeThesis?.hypotheses.find((hypothesis) => hypothesis.hypothesisId === activeRelation?.hypothesisId)
  return <>
    <PageTitle eyebrow={`${item.securityId} · 公开披露`} title={item.sourceDocumentTitle} description={`披露于 ${formatDate(item.disclosedAt)}，请核验事实来源及其对投资假设的影响。`} />
    <section className="fact-panel"><div className="panel-label">原文回查</div><blockquote>{source.data?.content ?? item.factExcerpt}</blockquote>{source.error && <p className="inline-error">数据库原文段落暂不可用，当前展示证据摘录。</p>}<div className="source-footer"><span>{item.sourceDocumentTitle} · {formatDate(item.disclosedAt)}{source.data?.page ? ` · 第 ${source.data.page} 页` : ''}{source.data?.contentKind === 'table_row' ? ` · 表 ${source.data.tableIndex} / 单元格 ${source.data.cellRange}` : ''}{source.data?.extractionMethod === 'ocr' ? ` · OCR${source.data.confidence == null ? '' : ` ${Math.round(source.data.confidence * 100)}%`}` : ''}{source.data?.locator ? ` · 定位 ${source.data.locator}` : ''}</span><SafeSourceLink url={item.sourceUrl} /></div></section>
    {context && <section className="content-section"><div className="section-heading"><div><span className="eyebrow">数据验证</span><h2>这条证据是否可用于研究判断</h2></div><span className="validation-summary">{context.validationItems.filter((v) => v.status === 'passed').length}/{context.validationItems.length} 项通过</span></div><ValidationChain items={context.validationItems} /></section>}
    <RetrievalTracePanel trace={retrievalTrace.data} loading={retrievalTrace.isLoading} error={retrievalTrace.error} />
    <section className="impact-panel"><div><span className="eyebrow">当前影响</span><h2>{activeHypothesis?.statement ?? '选择一条有效关联后进行判断'}</h2><p>{activeThesis?.title ?? '当前没有可操作的逻辑关联'}</p><div className="badge-row">{activeRelation && <><DirectionBadge direction={activeRelation.direction} /><StatusBadge state={activeRelation.status} /><span className="badge neutral-badge">{strengthText[activeRelation.strength]}强度</span><span className="badge neutral-badge">AI {Math.round(item.aiConfidence * 100)}%</span></>}</div></div>{activeRelation?.canManage && activeRelation.status !== 'deactivated' && <div className="decision-panel"><span>你的判断</span><div className="button-row"><button className="button primary" onClick={() => setDialog({ relation: activeRelation, action: '确认' })}>确认关联</button><button className="button secondary" onClick={() => setDialog({ relation: activeRelation, action: '驳回' })}>驳回</button><button className="button ghost" onClick={() => setDialog({ relation: activeRelation, action: '暂不判断' })}>暂不判断</button></div></div>}</section>
    <InlineError error={action.error} />
    <details className="content-section disclosure"><summary>高级关联管理 <span>{relations.data.length} 条关联</span></summary><div className="relation-list">{relations.data.map((relation) => { const target = thesisMap.get(relation.thesisId); const hypothesis = target?.hypotheses.find((h) => h.hypothesisId === relation.hypothesisId); return <article className={`relation-row ${relation.status === 'deactivated' ? 'disabled' : ''}`} key={relation.relationId}><div><div className="badge-row"><StatusBadge state={relation.status} /><DirectionBadge direction={relation.direction} /></div><h3>{hypothesis?.statement ?? '假设信息待加载'}</h3><p>{target?.title ?? relation.thesisId}</p><small>关联理由：{relation.reason || '未填写'} · 创建人：{relation.createdBy}{relation.reviewedBy ? ` · 审核人：${relation.reviewedBy}` : ''}</small></div>{relation.canManage && relation.status !== 'deactivated' && <div className="relation-actions"><button className="button secondary" onClick={() => setEditing(relation)}>修改</button><button className="button danger-link" onClick={() => setDialog({ relation, action: '解除' })}>解除</button></div>}</article> })}</div><RelationForm evidenceId={evidenceId} thesisList={manageableTheses.data} editing={editing} onDone={async () => { setEditing(null); await invalidate() }} /></details>
    <details className="content-section disclosure technical"><summary>技术信息</summary><dl><dt>证据 ID</dt><dd>{item.evidenceId}</dd><dt>来源文档 ID</dt><dd>{item.sourceDocumentId}</dd><dt>原文定位</dt><dd>{item.evidenceLocator}</dd><dt>模型版本</dt><dd>{item.modelVersion}</dd><dt>提示词版本</dt><dd>{item.promptVersion}</dd></dl></details>
    {dialog && <ConfirmDialog title={dialog.action === '解除' ? '解除这条证据关联' : `${dialog.action}这条证据关联`} description={dialog.action === '解除' ? '解除后该关联保留为历史记录，不再参与状态建议。' : '本次人工判断将被记录并刷新受影响逻辑的状态建议。'} confirmText={dialog.action} danger={dialog.action === '解除' || dialog.action === '驳回'} requireReason={dialog.action === '解除'} onClose={() => setDialog(null)} onConfirm={(reason) => action.mutate({ relation: dialog.relation, action: dialog.action, reason })} />}
  </>
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

function RelationForm({ evidenceId, thesisList, editing, onDone }: { evidenceId: string; thesisList: ThesisDetail[]; editing: Relation | null; onDone: () => void | Promise<void> }) {
  const [thesisId, setThesisId] = useState(editing?.thesisId ?? thesisList[0]?.thesisId ?? '')
  const [hypothesisId, setHypothesisId] = useState(editing?.hypothesisId ?? '')
  const [direction, setDirection] = useState(editing?.direction === 'support' ? '支持' : editing?.direction === 'conflict' ? '冲突' : '中性')
  const [strength, setStrength] = useState(editing?.strength === 'high' ? '高' : editing?.strength === 'low' ? '低' : '中')
  const [reason, setReason] = useState(editing?.reason ?? '')
  const selected = thesisList.find((item) => item.thesisId === thesisId)
  const mutation = useMutation({ mutationFn: () => editing ? updateRelation(evidenceId, editing.relationId, { thesisId, hypothesisId, direction, strength, reason }) : createRelation(evidenceId, { thesisId, hypothesisId, direction, strength, reason }), onSuccess: onDone })
  return <form className="relation-form" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><h3>{editing ? '修改关联' : '新增关联'}</h3><div className="form-grid two"><label>目标逻辑<select value={thesisId} disabled={Boolean(editing)} onChange={(event) => { setThesisId(event.target.value); setHypothesisId('') }} required><option value="">选择逻辑</option>{thesisList.map((item) => <option key={item.thesisId} value={item.thesisId}>{item.title}</option>)}</select></label><label>目标假设<select value={hypothesisId} onChange={(event) => setHypothesisId(event.target.value)} required><option value="">选择假设</option>{selected?.hypotheses.map((hypothesis) => <option key={hypothesis.hypothesisId} value={hypothesis.hypothesisId}>{hypothesis.statement}</option>)}</select></label><label>影响方向<select value={direction} onChange={(event) => setDirection(event.target.value)}><option>支持</option><option>冲突</option><option>中性</option></select></label><label>影响强度<select value={strength} onChange={(event) => setStrength(event.target.value)}><option>高</option><option>中</option><option>低</option></select></label></div><label>关联理由<textarea value={reason} onChange={(event) => setReason(event.target.value)} required placeholder="说明这条事实为什么影响目标假设" /></label><button className="button primary" disabled={mutation.isPending}>{mutation.isPending ? '提交中…' : editing ? '保存修改' : '新增关联'}</button><InlineError error={mutation.error} /></form>
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
    ['不可变修订', data.revisions, '原件哈希与对象版本谱系'],
    ['处理运行', data.ingestionRuns, `${data.semanticRuns} 次 semantic-v1 运行`],
    ['待归档原件', data.missingObjectArchive, '历史原件待对象存储回填'],
  ] as const
  return <>
    <PageTitle eyebrow="P0-3 数据资产层" title="资产治理" description="盘点原件、修订、处理运行与权限感知索引；重处理只追加新运行，不覆盖历史产物。" actions={<button className="button secondary" disabled={rebuild.isPending} onClick={() => rebuild.mutate()}>{rebuild.isPending ? '重建中…' : '重建检索索引'}</button>} />
    <section className="metric-grid">{metrics.map(([label, value, note]) => <div className="metric-card" key={label}><span>{label}</span><strong>{value}</strong><p>{note}</p></div>)}</section>
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">历史质量盘点</span><h2>治理状态与不可覆盖产物</h2></div></div><div className="asset-quality-grid"><p><strong>{data.singleSegmentDocuments}</strong><span>规范表中的历史单切片（保留不覆盖）</span></p><p><strong>{data.pendingAuthorization}</strong><span>来源授权待确认</span></p><p><strong>{data.artifactSegments}</strong><span>运行级切片产物</span></p><p><strong>{data.artifactFacts + data.artifactEvents}</strong><span>运行级事实与事件产物</span></p></div><InlineError error={rebuild.error} />{rebuild.data != null && <p className="success-note">索引已重建，共 {rebuild.data} 个切片。</p>}</section>
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">P1 权限感知混合召回</span><h2>验证可见切片</h2></div></div><form className="asset-search" onSubmit={(event) => { event.preventDefault(); if (query.trim()) setSubmittedQuery(query.trim()) }}><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="输入信息需求或正文关键词" /><button className="button primary" type="submit" disabled={!query.trim()}>混合召回</button></form><InlineError error={search.error} />{search.isFetching ? <LoadingState /> : submittedQuery && (search.data?.length ? <div className="review-list">{search.data.map((item) => <article className="review-card" key={`${item.documentId}-${item.locator}`}><div className="review-header"><strong>{item.documentId}</strong><span className="badge neutral-badge">{item.visibilityLabel}</span></div><p>{item.content}</p><small className="muted">定位：{item.locator} · 综合 {item.rank.toFixed(3)} · 关键词 {(item.keywordRank ?? 0).toFixed(3)} · 向量 {(item.vectorRank ?? 0).toFixed(3)} · {item.embeddingVersion}</small></article>)}</div> : <EmptyState title="没有可见命中" description="权限、证券、行业和时间过滤在排序前执行。" />)}</section>
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
  return <article className="review-card"><div className="review-header"><div><span className={`badge ${task.state === '待处理' ? 'priority-medium' : 'status-confirmed'}`}>{task.state}</span><h2>{task.trigger} · {task.thesisId}</h2></div><span className="muted">{task.priority}优先级</span></div>{task.detail && <p className="review-detail">{Object.entries(task.detail).map(([key, value]) => `${key}: ${String(value)}`).join(' · ')}</p>}{task.state === '待处理' ? <div className="review-decision"><textarea value={resolution} onChange={(event) => setResolution(event.target.value)} placeholder="填写复核结论（必填）" /><button className="button primary" disabled={resolution.trim().length < 2 || mutation.isPending} onClick={() => mutation.mutate()}>提交复核</button><InlineError error={mutation.error} /></div> : <p className="review-result"><strong>复核结论：</strong>{task.resolution}</p>}</article>
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

function quantDemoInput(config: QuantBacktestRequest['config']): QuantBacktestRequest {
  const bars: QuantBacktestRequest['bars'] = []
  const cursor = new Date(Date.UTC(2026, 0, 5))
  while (bars.length < 80) {
    const weekday = cursor.getUTCDay()
    if (weekday !== 0 && weekday !== 6) {
      const index = bars.length
      bars.push({
        tradingDate: cursor.toISOString().slice(0, 10),
        close: Number((100 + index * .13 + Math.sin(index / 4) * 2.8 + Math.sin(index / 11) * 1.4).toFixed(2)),
        benchmarkClose: Number((100 + index * .07 + Math.sin(index / 8) * 1.1).toFixed(2)),
      })
    }
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  const signalSpecs = [
    [6, '支持', '高', .88], [23, '冲突', '中', .78], [39, '支持', '高', .91], [58, '支持', '中', .72],
  ] as const
  return {
    name: '事件方向信号 · 受控演示', bars, config,
    signals: signalSpecs.map(([index, direction, strength, confidence], order) => ({
      signalId: `DEMO-SIG-${order + 1}`,
      disclosedAt: `${bars[index].tradingDate}T08:30:00+08:00`,
      generatedAt: `${bars[index].tradingDate}T18:00:00+08:00`,
      direction, strength, confidence,
    })),
  }
}

function percent(value: number | undefined) {
  return value == null ? '—' : `${value >= 0 ? '+' : ''}${(value * 100).toFixed(2)}%`
}

function money(value: number) {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 }).format(value)
}

function QuantCurve({ points }: { points: QuantEquityPoint[] }) {
  if (points.length < 2) return null
  const width = 900
  const height = 250
  const padding = 22
  const all = points.flatMap((point) => [point.equity, point.benchmarkEquity])
  const minimum = Math.min(...all)
  const maximum = Math.max(...all)
  const range = maximum - minimum || 1
  const line = (key: 'equity' | 'benchmarkEquity') => points.map((point, index) => {
    const x = padding + index * (width - padding * 2) / (points.length - 1)
    const y = height - padding - (point[key] - minimum) * (height - padding * 2) / range
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
  return <div className="quant-chart"><div className="chart-legend"><span className="strategy-line">策略净值</span><span className="benchmark-line">基准净值</span></div><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="策略与基准净值曲线"><line x1={padding} y1={height - padding} x2={width - padding} y2={height - padding} className="chart-axis" /><polyline points={line('benchmarkEquity')} className="chart-benchmark" /><polyline points={line('equity')} className="chart-strategy" /></svg><div className="chart-dates"><span>{points[0].tradingDate}</span><span>{points.at(-1)?.tradingDate}</span></div></div>
}

export function QuantPage() {
  const [holdingDays, setHoldingDays] = useState(20)
  const [costBps, setCostBps] = useState(10)
  const [slippageBps, setSlippageBps] = useState(5)
  const [allowShort, setAllowShort] = useState(false)
  const [run, setRun] = useState<QuantBacktestRun | null>(null)
  const mutation = useMutation({
    mutationFn: () => runQuantBacktest(quantDemoInput({
      initialCapital: 1_000_000, holdingDays, transactionCostBps: costBps, slippageBps, allowShort,
    })),
    onSuccess: setRun,
  })
  const metrics = run?.metrics
  const metricItems = metrics ? [
    ['策略收益', percent(metrics.totalReturn), `基准 ${percent(metrics.benchmarkReturn)}`],
    ['超额收益', percent(metrics.excessReturn), '已扣交易摩擦'],
    ['最大回撤', percent(metrics.maxDrawdown), '峰值至谷值'],
    ['夏普比率', metrics.sharpeRatio?.toFixed(2) ?? '—', `年化波动 ${percent(metrics.annualizedVolatility)}`],
  ] : []
  return <>
    <PageTitle eyebrow="QUANT RESEARCH LAB" title="量化实验" description="把已确认的研究信号转成可复算的历史验证；结果只用于研究评估，不产生交易或调仓指令。" actions={<button className="button primary" disabled={mutation.isPending} onClick={() => mutation.mutate()}>{mutation.isPending ? '正在计算…' : run ? '重新运行' : '运行受控演示'}</button>} />
    <section className="quant-config hero-section"><div className="section-heading"><div><span className="eyebrow">策略口径</span><h2>事件信号 · T+1 执行</h2></div><span className="quant-safety">NO LOOK-AHEAD · COST-AWARE</span></div><div className="quant-controls"><label>持有交易日<input type="number" min="1" max="252" value={holdingDays} onChange={(event) => setHoldingDays(Number(event.target.value))} /></label><label>交易成本（bps）<input type="number" min="0" max="1000" value={costBps} onChange={(event) => setCostBps(Number(event.target.value))} /></label><label>滑点（bps）<input type="number" min="0" max="1000" value={slippageBps} onChange={(event) => setSlippageBps(Number(event.target.value))} /></label><label className="quant-toggle"><input type="checkbox" checked={allowShort} onChange={(event) => setAllowShort(event.target.checked)} /><span>允许做空</span></label></div><p className="quant-dataset-note">当前使用 80 个交易日、4 条事件信号的受控演示数据。API 已支持接收真实复权行情和独立信号；生产接入前仍需完成交易日历与行情授权。</p><InlineError error={mutation.error} /></section>
    {!run ? <EmptyState title="尚未运行回测" description="设置持有期和交易摩擦后运行演示，系统将输出净值、风险和逐笔交易。" /> : <>
      <section className="metric-grid quant-metrics">{metricItems.map(([label, value, note]) => <article className="metric-card" key={label}><span>{label}</span><strong>{value}</strong><p>{note}</p></article>)}</section>
      <section className="content-section quant-result"><div className="section-heading"><div><span className="eyebrow">净值对照</span><h2>策略与基准</h2></div><span className="mono run-id">{run.runId}</span></div><QuantCurve points={run.equityCurve} /><div className="quant-summary"><span>期末净值<strong>¥ {money(metrics!.finalEquity)}</strong></span><span>交易次数<strong>{metrics!.tradeCount}</strong></span><span>胜率<strong>{percent(metrics!.winRate)}</strong></span><span>累计换手<strong>{metrics!.turnover.toFixed(2)}×</strong></span><span>平均暴露<strong>{percent(metrics!.averageExposure)}</strong></span></div></section>
      <section className="content-section"><div className="section-heading"><div><span className="eyebrow">交易审计</span><h2>逐笔记录</h2></div><span className="filter-count">信号 {run.diagnostics.acceptedSignalCount}/{run.diagnostics.inputSignalCount} 进入回测</span></div><div className="quant-table-wrap"><table className="quant-table"><thead><tr><th>信号</th><th>方向 / 仓位</th><th>建仓</th><th>退出</th><th>持有</th><th>净收益</th><th>退出原因</th></tr></thead><tbody>{run.trades.map((trade) => <tr key={`${trade.signalId}-${trade.entryDate}`}><td className="mono">{trade.signalId}</td><td>{trade.direction} · {(Math.abs(trade.position) * 100).toFixed(0)}%</td><td>{trade.entryDate}<small>¥{trade.entryPrice.toFixed(2)}</small></td><td>{trade.exitDate}<small>¥{trade.exitPrice.toFixed(2)}</small></td><td>{trade.holdingDays} 日</td><td className={trade.netReturn >= 0 ? 'quant-positive' : 'quant-negative'}>{percent(trade.netReturn)}</td><td>{trade.exitReason}</td></tr>)}</tbody></table></div></section>
      <section className="content-section quant-methodology"><div><span className="eyebrow">方法与限制</span><h2>{run.methodologyVersion}</h2><p>信号在生成后的下一可交易日执行；披露晚于生成的信号会被隔离；每次仓位变化扣除成本与滑点；回测结束强制平仓。</p></div><ul>{run.diagnostics.warnings.map((warning) => <li key={warning}>{warning}</li>)}{run.diagnostics.skippedSignals.map((warning) => <li key={warning}>{warning}</li>)}</ul></section>
    </>}
  </>
}

function SafeSourceLink({ url }: { url: string }) {
  const valid = (() => { try { return ['http:', 'https:'].includes(new URL(url).protocol) } catch { return false } })()
  return valid ? <a className="source-link" href={url} target="_blank" rel="noopener noreferrer">查看公开原文 ↗</a> : <span className="muted">公开原文链接不可用</span>
}
