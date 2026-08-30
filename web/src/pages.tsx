import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { NavLink, useParams, useSearchParams } from 'react-router-dom'
import {
  createRelation, deactivateRelation, decideAdjudication, decideStatus, getAudit,
  getDocumentSegment, getEvidence, getRadarEvidence, getRelations, getSuggestions,
  getPublishReadiness, getThesis, getThesisEvidenceFeed, getTrends,
  listAdjudications, listIngestionReviews, listMetrics, listProcessingJobs, listReviewTasks, listTheses,
  publishThesis, replayProcessingJob, resolveIngestionReview, resolveReviewTask,
  reviewRelation, saveMetricMapping, updateHypothesis, updateRelation,
  getAssetInventory, rebuildAssetSearchIndex, searchAssets,
  createThesisRevision, getThesisRevisionDiff, publishThesisRevision, updateThesisRevision,
} from './api'
import {
  ConfirmDialog, DirectionBadge, EmptyState, ErrorState, EvidenceEventRow,
  InlineError, LoadingState, PageTitle, StatusBadge, ValidationChain,
} from './components'
import type { Adjudication, Hypothesis, IngestionReview, MetricDefinition, ProcessingJob, Relation, ReviewTask, ThesisDetail, ThesisRevision } from './types'
import { formatDate, strengthText } from './ui'

export function WorkbenchPage() {
  const [feedFilter, setFeedFilter] = useState('全部')
  const [expandedIndustries, setExpandedIndustries] = useState(() => new Set(['新能源汽车', '医药', '芯片半导体']))
  const industries = [
    { name: '新能源汽车', count: 3, companies: [['吉利汽车', 2], ['比亚迪', 5], ['小鹏汽车', 1]] },
    { name: '医药', count: 2, companies: [['云南白药', 1], ['恒瑞医药', 3], ['药明康德', 2]] },
    { name: '芯片半导体', count: 2, companies: [['北方华创', 2], ['兆易创新', 1], ['中芯国际', 4]] },
  ] as const
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
  const toggleIndustry = (name: string) => setExpandedIndustries((current) => { const next = new Set(current); if (next.has(name)) next.delete(name); else next.add(name); return next })
  return <div className="dashboard-page">
    <aside className="coverage-panel" aria-label="我的覆盖"><div className="dashboard-panel-title"><h1>我的覆盖</h1><NavLink to="/coverage" aria-label="管理覆盖范围">⚙</NavLink></div>{industries.map((industry) => <section className="coverage-group" key={industry.name}><button className="coverage-industry" aria-expanded={expandedIndustries.has(industry.name)} onClick={() => toggleIndustry(industry.name)}><span>{expandedIndustries.has(industry.name) ? '⌄' : '›'} ▥ {industry.name}</span><b>{industry.count}</b></button>{expandedIndustries.has(industry.name) && <div className="coverage-companies">{industry.companies.map(([company, count]) => <NavLink to={company === '吉利汽车' ? '/companies/geely' : '/theses'} key={company}><span>▥ {company}</span><b>{count}</b></NavLink>)}</div>}</section>)}<nav className="coverage-links" aria-label="研究功能"><NavLink to="/coverage">⌁ 行业总览</NavLink><NavLink to="/macro-strategy">▧ 宏观与策略</NavLink><NavLink to="/assets">▤ 数据中心</NavLink><NavLink to="/assets">⌕ 知识库</NavLink><NavLink to="/theses">◇ 模型与因子</NavLink><NavLink to="/assets">▱ 研报与文档</NavLink><NavLink to="/radar">♧ 监控与预警</NavLink></nav><button className="new-research-button">＋ 新建研究主题</button></aside>
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

type CoverageCompany = { id: string; name: string; code: string; market: string; owner: string; thesisCount: number; status: '正常覆盖' | '待建档' | '暂停覆盖'; updated: string }
type CoverageIndustry = { id: string; name: string; code: string; color: string; description: string; companies: CoverageCompany[] }

const initialCoverageIndustries: CoverageIndustry[] = [
  { id: 'auto', name: '新能源汽车', code: 'AUTO.NE', color: '#1473e6', description: '整车、动力电池与智能驾驶产业链', companies: [
    { id: 'geely', name: '吉利汽车', code: '0175.HK', market: '港股', owner: '张明', thesisCount: 3, status: '正常覆盖', updated: '今天 10:30' },
    { id: 'byd', name: '比亚迪', code: '002594.SZ', market: 'A股', owner: '张明', thesisCount: 2, status: '正常覆盖', updated: '今天 09:42' },
    { id: 'xpeng', name: '小鹏汽车', code: '9868.HK', market: '港股', owner: '李然', thesisCount: 2, status: '正常覆盖', updated: '昨天 18:20' },
  ] },
  { id: 'pharma', name: '创新医药', code: 'PHARMA.CN', color: '#16a173', description: '创新药、CXO与中药消费', companies: [
    { id: 'hengrui', name: '恒瑞医药', code: '600276.SH', market: 'A股', owner: '王妍', thesisCount: 2, status: '正常覆盖', updated: '今天 08:47' },
    { id: 'wuxi', name: '药明康德', code: '603259.SH', market: 'A股', owner: '王妍', thesisCount: 1, status: '正常覆盖', updated: '昨天 16:10' },
    { id: 'ynby', name: '云南白药', code: '000538.SZ', market: 'A股', owner: '周宁', thesisCount: 0, status: '待建档', updated: '3天前' },
  ] },
  { id: 'semi', name: '芯片半导体', code: 'SEMI.CN', color: '#7558c7', description: '制造、设备、材料与设计公司', companies: [
    { id: 'naura', name: '北方华创', code: '002371.SZ', market: 'A股', owner: '赵谦', thesisCount: 2, status: '正常覆盖', updated: '今天 09:15' },
    { id: 'giga', name: '兆易创新', code: '603986.SH', market: 'A股', owner: '赵谦', thesisCount: 1, status: '正常覆盖', updated: '昨天 15:32' },
    { id: 'smic', name: '中芯国际', code: '0981.HK', market: '港股', owner: '赵谦', thesisCount: 3, status: '正常覆盖', updated: '今天 09:15' },
  ] },
]

export function CoverageManagementPage() {
  const [industries, setIndustries] = useState<CoverageIndustry[]>(initialCoverageIndustries)
  const [activeIndustryId, setActiveIndustryId] = useState('auto')
  const [query, setQuery] = useState('')
  const [dialog, setDialog] = useState<'industry' | 'company' | null>(null)
  const [toast, setToast] = useState('')
  const industry = industries.find((item) => item.id === activeIndustryId) ?? industries[0]
  const companies = industry.companies.filter((item) => `${item.name}${item.code}${item.owner}`.toLowerCase().includes(query.trim().toLowerCase()))
  const totalCompanies = industries.reduce((sum, item) => sum + item.companies.length, 0)
  const totalTheses = industries.reduce((sum, item) => sum + item.companies.reduce((companySum, company) => companySum + company.thesisCount, 0), 0)
  const showToast = (message: string) => { setToast(message); window.setTimeout(() => setToast(''), 2200) }
  const addIndustry = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const data = new FormData(event.currentTarget); const name = String(data.get('name') ?? '').trim(); if (!name) return; const id = `industry-${Date.now()}`; setIndustries((current) => [...current, { id, name, code: String(data.get('code') || 'CUSTOM'), color: '#df8b2c', description: String(data.get('description') || '自定义研究行业'), companies: [] }]); setActiveIndustryId(id); setDialog(null); showToast(`已添加行业：${name}`) }
  const addCompany = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const data = new FormData(event.currentTarget); const name = String(data.get('name') ?? '').trim(); if (!name) return; const company: CoverageCompany = { id: `company-${Date.now()}`, name, code: String(data.get('code') || '待补充'), market: String(data.get('market') || 'A股'), owner: String(data.get('owner') || '待分配'), thesisCount: 0, status: '待建档', updated: '刚刚' }; setIndustries((current) => current.map((item) => item.id === activeIndustryId ? { ...item, companies: [...item.companies, company] } : item)); setDialog(null); showToast(`已将${name}加入${industry.name}`) }
  const toggleCoverage = (companyId: string) => setIndustries((current) => current.map((item) => item.id === activeIndustryId ? { ...item, companies: item.companies.map((company) => company.id === companyId ? { ...company, status: company.status === '暂停覆盖' ? '正常覆盖' : '暂停覆盖' } : company) } : item))
  return <div className="coverage-management-page">
    <header className="coverage-management-header"><div><span>研究覆盖管理 / COVERAGE UNIVERSE</span><h1>行业与公司管理</h1><p>维护研究团队的行业分类、公司覆盖范围与负责人。新增对象后可继续建立投资逻辑和指标体系。</p></div><div className="coverage-header-actions"><button onClick={() => setDialog('industry')}>＋ 新增行业</button><button className="primary" onClick={() => setDialog('company')}>＋ 添加公司</button></div></header>
    <section className="coverage-summary" aria-label="覆盖概况"><div><span>行业分类</span><strong>{industries.length}</strong><small>个活跃行业</small></div><div><span>覆盖公司</span><strong>{totalCompanies}</strong><small>家公司</small></div><div><span>活跃投资逻辑</span><strong>{totalTheses}</strong><small>条逻辑</small></div><div><span>待完善档案</span><strong>{industries.flatMap((item) => item.companies).filter((item) => item.status === '待建档').length}</strong><small>需要处理</small></div><div className="coverage-governance"><b>覆盖治理</b><span>行业、公司和研究逻辑为三级独立对象</span><em>最后同步：今天 10:30</em></div></section>
    <main className="coverage-management-grid">
      <aside className="industry-manager"><header><div><span>01</span><h2>行业目录</h2></div><button onClick={() => setDialog('industry')} aria-label="新增行业">＋</button></header><label className="industry-search"><span>⌕</span><input placeholder="搜索行业" aria-label="搜索行业" /></label><div className="industry-list">{industries.map((item) => <button key={item.id} className={activeIndustryId === item.id ? 'active' : ''} onClick={() => { setActiveIndustryId(item.id); setQuery('') }}><i style={{ background: item.color }}>{item.name.slice(0,1)}</i><span><strong>{item.name}</strong><small>{item.description}</small></span><b>{item.companies.length}</b></button>)}</div><footer><span>归档行业 <b>0</b></span><button>查看归档 ›</button></footer></aside>
      <section className="company-manager"><header className="company-manager-title"><div><span>02 / {industry.code}</span><h2>{industry.name}</h2><p>{industry.description} · 当前覆盖 {industry.companies.length} 家公司</p></div><div><button>行业设置</button><button className="primary" onClick={() => setDialog('company')}>＋ 添加公司</button></div></header><div className="company-manager-toolbar"><label><span>⌕</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索公司名称、代码或负责人" aria-label="搜索公司" /></label><div className="company-filters"><button className="active">全部 {industry.companies.length}</button><button>正常覆盖</button><button>待建档</button><button>暂停覆盖</button></div><button>筛选⌄</button></div>
        <div className="coverage-company-table" role="table" aria-label={`${industry.name}公司列表`}><div className="coverage-company-head" role="row"><span>公司</span><span>市场</span><span>研究负责人</span><span>投资逻辑</span><span>覆盖状态</span><span>最近更新</span><span>操作</span></div>{companies.map((company) => <article className="coverage-company-row" role="row" key={company.id}><div className="coverage-company-name"><i>{company.name.slice(0,1)}</i><span><strong>{company.name}</strong><small>{company.code}</small></span></div><span>{company.market}</span><div className="coverage-owner"><i>{company.owner.slice(0,1)}</i><span>{company.owner}</span></div><b className={company.thesisCount ? '' : 'empty'}>{company.thesisCount ? `${company.thesisCount} 条` : '未建立'}</b><em className={`coverage-status status-${company.status}`}>{company.status}</em><time>{company.updated}</time><div className="coverage-row-actions">{company.id === 'geely' ? <NavLink to="/companies/geely">进入研究</NavLink> : <button>{company.thesisCount ? '查看研究' : '完善档案'}</button>}<button className="more" aria-label={`${company.name}更多操作`}>···</button><div className="coverage-quick-menu"><button onClick={() => showToast(`已打开${company.name}编辑项`)}>编辑公司</button><button onClick={() => toggleCoverage(company.id)}>{company.status === '暂停覆盖' ? '恢复覆盖' : '暂停覆盖'}</button></div></div></article>)}</div>
        {!companies.length && <div className="coverage-empty"><strong>没有匹配的公司</strong><span>调整搜索条件，或将新公司添加到当前行业。</span><button onClick={() => setDialog('company')}>＋ 添加公司</button></div>}
        <footer className="company-manager-footer"><span>显示 {companies.length} / {industry.companies.length} 家公司</span><div><button disabled>‹</button><b>1</b><button disabled>›</button></div></footer>
      </section>
    </main>
    {dialog && <div className="coverage-dialog-backdrop" role="presentation" onMouseDown={() => setDialog(null)}><section className="coverage-dialog" role="dialog" aria-modal="true" aria-labelledby="coverage-dialog-title" onMouseDown={(event) => event.stopPropagation()}><header><span>{dialog === 'industry' ? 'INDUSTRY SETUP' : 'COMPANY SETUP'}</span><h2 id="coverage-dialog-title">{dialog === 'industry' ? '新增研究行业' : `添加公司到“${industry.name}”`}</h2><p>{dialog === 'industry' ? '建立行业分类后，可继续添加覆盖公司和行业级研究资料。' : '这里只建立静态公司档案，不会自动创建投资逻辑。'}</p><button onClick={() => setDialog(null)} aria-label="关闭">×</button></header><form onSubmit={dialog === 'industry' ? addIndustry : addCompany}>{dialog === 'industry' ? <><label>行业名称<input name="name" placeholder="例如：消费电子" required autoFocus /></label><label>行业代码<input name="code" placeholder="例如：ELEC.CN" /></label><label>行业说明<textarea name="description" placeholder="简要描述行业覆盖范围" /></label></> : <><div className="coverage-form-two"><label>公司名称<input name="name" placeholder="例如：理想汽车" required autoFocus /></label><label>证券代码<input name="code" placeholder="例如：2015.HK" /></label></div><div className="coverage-form-two"><label>上市市场<select name="market"><option>A股</option><option>港股</option><option>美股</option><option>未上市</option></select></label><label>研究负责人<input name="owner" placeholder="输入姓名" /></label></div></>}<div className="coverage-dialog-actions"><button type="button" onClick={() => setDialog(null)}>取消</button><button type="submit" className="primary">{dialog === 'industry' ? '创建行业' : '添加公司'}</button></div></form></section></div>}
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

export function CompanyResearchPage() {
  const [activeThesis, setActiveThesis] = useState<(typeof companyTheses)[number]['id']>('product')
  const [activeHypothesis, setActiveHypothesis] = useState('H2')
  const thesis = companyTheses.find((item) => item.id === activeThesis) ?? companyTheses[0]
  const baseResearch = thesisResearch.product
  const research = activeThesis === 'product' ? baseResearch : {
    hypotheses: activeThesis === 'overseas' ? [
      { id: 'H1', title: '重点海外市场渠道覆盖持续扩大', state: '支持', tone: 'support' },
      { id: 'H2', title: '海外新品供给能够转化为有效销量', state: '待验证', tone: 'pending' },
      { id: 'H3', title: '贸易政策变化不显著影响盈利能力', state: '冲突', tone: 'conflict' },
    ] : [
      { id: 'H1', title: '规模效应带动单车盈利修复', state: '待验证', tone: 'pending' },
      { id: 'H2', title: '市场盈利预期具备上修空间', state: '冲突', tone: 'conflict' },
      { id: 'H3', title: '当前估值已充分反映价格竞争风险', state: '支持', tone: 'support' },
    ],
    metrics: baseResearch.metrics,
    evidence: baseResearch.evidence,
  }
  const selected = research.hypotheses.find((item) => item.id === activeHypothesis) ?? research.hypotheses[0]
  const metrics = research.metrics[selected.id as keyof typeof research.metrics]
  const evidence = research.evidence[selected.id as keyof typeof research.evidence]
  const chooseThesis = (id: (typeof companyTheses)[number]['id']) => { setActiveThesis(id); setActiveHypothesis('H2') }
  return <div className="company-research-page">
    <header className="company-identity">
      <NavLink className="company-back" to="/workbench" aria-label="返回工作台">‹</NavLink><div className="company-emblem">吉</div><div className="company-name"><span>公司研究 / 汽车</span><h1>吉利汽车 <small>0175.HK</small></h1></div>
      <div className="company-quote"><span>当前价</span><strong>13.42 <small>HKD</small></strong><em>+2.18%</em></div><div className="company-stat"><span>投资评级</span><strong>增持</strong></div><div className="company-stat"><span>目标价（12个月）</span><strong>16.80 <small>HKD</small></strong></div><div className="company-stat"><span>分析师</span><strong>张明</strong></div><div className="company-stat"><span>最后更新</span><strong>2025-05-20 10:30</strong></div>
      <div className="company-actions"><button>添加资料</button><button className="primary">更新观点</button></div>
    </header>
    <nav className="company-tabs" aria-label="公司研究导航">{['总览', '投资逻辑', '事件与证据', '指标中心', '资料库', '研究记录'].map((item) => <button className={item === '投资逻辑' ? 'active' : ''} key={item}>{item}</button>)}</nav>
    <main className="company-canvas">
      <section className="thesis-switcher" aria-label="投资逻辑选择">{companyTheses.map((item) => <button key={item.id} className={activeThesis === item.id ? 'active' : ''} onClick={() => chooseThesis(item.id)} aria-pressed={activeThesis === item.id}><strong>{item.title}</strong><span><i className={`dot ${item.health === '证据不足' ? 'warning' : ''}`} />{item.direction} · {item.health} · {item.confidence}%</span></button>)}<div className="thesis-switch-actions"><button>☷ 全部逻辑</button><button>＋ 新建逻辑</button></div></section>
      <section className="active-thesis-summary"><div><div className="summary-meta"><span>{thesis.horizon}</span><b>{thesis.direction}</b><b>{thesis.health}</b></div><h2>{thesis.summary}</h2></div><div className="confidence-block"><span>逻辑置信度 ⓘ</span><strong>{thesis.confidence}%</strong><i><b style={{ width: `${thesis.confidence}%` }} /></i></div><dl><div><dt>逻辑负责人</dt><dd>张明</dd></div><div><dt>最后更新</dt><dd>2025-05-20</dd></div></dl><button className="edit-thesis">✎ 编辑逻辑</button></section>
      <div className="company-research-grid"><section className="hypothesis-panel"><header><h2>核心假设</h2><button>＋ 添加假设</button></header><div className="hypothesis-list">{research.hypotheses.map((item) => <button key={item.id} className={selected.id === item.id ? 'active' : ''} onClick={() => setActiveHypothesis(item.id)}><span>{item.id}</span><strong>{item.title}</strong><em className={item.tone}>{item.state}</em></button>)}</div><button className="view-all-hypotheses">查看全部假设（3）⌄</button></section>
        <section className="verification-panel"><header><div><span>当前验证对象</span><h2>{selected.id} · {selected.title}</h2></div><button>收起⌃</button></header><h3>关键指标</h3><div className="metric-table"><div className="metric-table-head"><span>指标</span><span>最新值</span><span>趋势（vs 前值）</span><span>状态</span></div>{metrics.map(([name, value, delta, state]) => <div className="metric-table-row" key={name}><strong>{name}</strong><b>{value}</b><em className={state === '支持' ? 'support' : state === '冲突' ? 'conflict' : 'pending'}>{delta}</em><span className={state === '支持' ? 'support' : state === '冲突' ? 'conflict' : 'pending'}>{state}</span></div>)}</div><h3>证据验证 <small>（{evidence.length}）</small></h3><div className="company-evidence-list">{evidence.map(([state, title, source]) => <article key={title}><i className={state === '支持' ? 'support' : state === '冲突' ? 'conflict' : 'pending'}>{state === '支持' ? '↗' : state === '冲突' ? '!' : '?'}</i><div><strong>{title}</strong><span>来源：{source}</span></div><b className={state === '支持' ? 'support' : state === '冲突' ? 'conflict' : 'pending'}>{state}</b></article>)}</div></section>
        <aside className="company-side-column"><section><header><h2>催化剂与风险</h2><button>⌃</button></header><h3 className="support-text">催化剂</h3><ul><li>新车型密集上市（银河星舰7/极氪007GT等）</li><li>海外市场放量超预期</li><li>电池成本下降超预期</li></ul><h3 className="conflict-text">风险</h3><ul><li>行业价格战加剧，折扣率继续上行</li><li>海外地缘政治及关税风险</li><li>原材料价格大幅上涨</li></ul></section><section><header><h2>待复核事项 <small>2</small></h2></header><label><input type="checkbox" />5月中旬渠道调研更新终端折扣率数据<time>05-28</time></label><label><input type="checkbox" />Q2订单跟踪与交付节奏复核<time>06-10</time></label></section><section><header><h2>近期关键节点</h2></header><ol><li><time>2025-05-22</time>2025年Q1业绩发布</li><li><time>2025-06-10</time>5月销量发布</li><li><time>2025-06-18</time>证券机构策略会</li></ol></section></aside>
      </div>
      <section className="company-version"><header><h2>逻辑版本记录</h2><button>查看全部版本⌃</button></header><div><strong>v1.2（当前）</strong><span>下调单车收入预期；更新4月销量与折扣率数据；补充渠道反馈证据</span><span>张明</span><time>2025-05-20 10:30</time><b>{thesis.confidence}%</b><button>查看详情</button></div></section>
    </main>
  </div>
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
  if (thesis.isLoading || feed.isLoading) return <LoadingState />
  if (thesis.error || feed.error || !thesis.data || !feed.data) return <ErrorState error={thesis.error ?? feed.error} />
  const item = thesis.data
  const evidence = feed.data.items
  const counts = { support: evidence.filter((x) => x.direction === 'support' && x.confirmationStatus === 'confirmed').length, conflict: evidence.filter((x) => x.direction === 'conflict' && x.confirmationStatus === 'confirmed').length, pending: evidence.filter((x) => x.confirmationStatus === 'pending').length }
  const risk = evidence.find((x) => x.priority === 'high')
  const openSuggestion = suggestions.data?.find((x) => !x.humanAction)
  const businessAudit = audit.data?.filter((line) => line.action !== '查看').slice(0, 8) ?? []
  return <>
    <PageTitle eyebrow={`${item.securityId} · V${item.version}`} title={item.title} description={item.coreView} actions={<NavLink className="button secondary" to={`/radar?thesisId=${encodeURIComponent(thesisId)}`}>查看变化雷达</NavLink>} />
    <section className="logic-overview"><div><span>当前结论</span><strong>{item.direction}</strong><small>{item.status}</small></div><div><span>支持证据</span><strong className="positive">{counts.support}</strong><small>人工已确认</small></div><div><span>冲突证据</span><strong className="negative">{counts.conflict}</strong><small>人工已确认</small></div><div><span>待核验</span><strong>{counts.pending}</strong><small>需要研究员处理</small></div><div><span>下次复核</span><strong className="date-value">{formatDate(item.nextReviewAt)}</strong><small>负责人 {item.owner}</small></div></section>
    {risk && <section className="risk-callout"><div><span className="risk-icon">!</span><div><strong>当前最大风险</strong><p>{risk.sourceDocumentTitle} · 影响“{risk.hypothesisStatement}”</p></div></div><NavLink to={`/radar/${risk.evidenceId}?thesisId=${thesisId}&relationId=${risk.relationId}`}>立即核验 →</NavLink></section>}
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">逻辑链</span><h2>关键假设健康度</h2></div></div><div className="hypothesis-grid">{item.hypotheses.map((hypothesis) => { const related = evidence.filter((x) => x.hypothesisId === hypothesis.hypothesisId); return <article className="hypothesis-card" key={hypothesis.hypothesisId}><div><span className="importance">{hypothesis.importance}</span><span className="hypothesis-status">{hypothesis.status}</span></div><h3>{hypothesis.statement}</h3><footer><span className="positive">支持 {related.filter((x) => x.direction === 'support' && x.confirmationStatus === 'confirmed').length}</span><span className="negative">冲突 {related.filter((x) => x.direction === 'conflict' && x.confirmationStatus === 'confirmed').length}</span><span>待确认 {related.filter((x) => x.confirmationStatus === 'pending').length}</span></footer></article> })}</div></section>
    <section className="content-section"><div className="section-heading"><div><span className="eyebrow">证据链</span><h2>最关键变化</h2></div><NavLink className="secondary-link" to={`/radar?thesisId=${thesisId}`}>查看全部 {feed.data.total} 条</NavLink></div><div className="evidence-list">{evidence.slice(0, 3).map((record) => <EvidenceEventRow item={record} key={`${record.evidenceId}-${record.relationId}`} />)}</div></section>
    <section className="content-section two-column"><div><div className="section-heading"><div><span className="eyebrow">人工闸门</span><h2>状态建议</h2></div></div>{openSuggestion ? <article className="suggestion-card"><span>规则建议</span><h3>{openSuggestion.currentStatus} → {openSuggestion.suggestedStatus}</h3><p>{openSuggestion.reasons.join('；')}</p><textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} placeholder="填写决策原因（必填）" /><select value={targetStatus} onChange={(event) => setTargetStatus(event.target.value)}><option>验证中</option><option>出现分歧</option><option>重大风险</option><option>已关闭</option></select><div className="button-row"><button disabled={!decisionReason.trim() || decision.isPending} className="button primary" onClick={() => decision.mutate({ id: openSuggestion.suggestionId, action: '接受' })}>接受建议</button><button disabled={!decisionReason.trim() || decision.isPending} className="button secondary" onClick={() => decision.mutate({ id: openSuggestion.suggestionId, action: '拒绝' })}>拒绝</button><button disabled={!decisionReason.trim() || decision.isPending} className="button secondary" onClick={() => decision.mutate({ id: openSuggestion.suggestionId, action: '修改' })}>修改状态</button></div><InlineError error={decision.error} /></article> : <EmptyState title="没有待处置建议" description="证据审核后，规则引擎会生成新的状态建议。" />}</div><div><div className="section-heading"><div><span className="eyebrow">可追溯</span><h2>关键审计记录</h2></div></div><div className="timeline">{businessAudit.length ? businessAudit.map((line, index) => <div className="timeline-item" key={`${line.action}-${index}`}><i /><div><strong>{line.action}</strong><p>{line.actor} · {formatDate(line.occurredAt)}</p></div></div>) : <p className="muted">暂无关键业务变更记录。</p>}</div></div></section>
    <details className="content-section disclosure"><summary>指标趋势与计算口径</summary><div className="trend-list">{trends.data?.map((trend) => <p key={trend.hypothesisId}><strong>{trend.statement}</strong><span>{trend.direction} · {trend.points.map((point) => `${point.period} ${point.value}${trend.unit}`).join('，') || '需人工判断'}</span></p>)}</div></details>
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

function DraftPublishWorkspace({ thesis }: { thesis: ThesisDetail }) {
  const [metricKeyword, setMetricKeyword] = useState('')
  const metrics = useQuery({ queryKey: ['metrics', metricKeyword], queryFn: () => listMetrics(metricKeyword) })
  return <>
    <section className="content-section draft-config"><div className="section-heading"><div><span className="eyebrow">人工配置</span><h2>假设、指标与失效条件</h2></div><span className="muted">AI 内容均为待采用候选</span></div>
      <label className="metric-search">搜索指标字典<input value={metricKeyword} onChange={(event) => setMetricKeyword(event.target.value)} placeholder="输入指标名称或 ID" /></label>
      <InlineError error={metrics.error} />
      <div className="hypothesis-editor-list">{thesis.hypotheses.map((hypothesis) => <HypothesisEditor key={hypothesis.hypothesisId} thesisId={thesis.thesisId} hypothesis={hypothesis} metrics={metrics.data ?? []} />)}</div>
      {(thesis.riskSuggestions.length > 0 || thesis.invalidationSuggestions.length > 0) && <div className="ai-candidate-panel"><strong>AI 风险与失效建议（待人工判断）</strong>{[...thesis.riskSuggestions, ...thesis.invalidationSuggestions].map((item, index) => <p key={index}>{String(item.statement ?? '未提供建议文本')}</p>)}</div>}
    </section>
    <PublishPanel thesisId={thesis.thesisId} />
  </>
}

function HypothesisEditor({ thesisId, hypothesis, metrics }: { thesisId: string; hypothesis: Hypothesis; metrics: MetricDefinition[] }) {
  const qc = useQueryClient()
  const current = hypothesis.mappings[0]
  const [statement, setStatement] = useState(hypothesis.statement)
  const [hypothesisType, setHypothesisType] = useState(hypothesis.hypothesisType)
  const [importance, setImportance] = useState(hypothesis.importance)
  const [observationWindow, setObservationWindow] = useState(hypothesis.observationWindow ?? '')
  const [invalidationRule, setInvalidationRule] = useState(hypothesis.invalidationRule ?? '')
  const [metricKey, setMetricKey] = useState(current ? `${current.metricId}@@${current.metricVersion}` : '')
  const [expectedDirection, setExpectedDirection] = useState(current?.expectedDirection ?? '越高越好')
  const [expectedValue, setExpectedValue] = useState(current?.expectedValue ?? '')
  const [threshold, setThreshold] = useState(current?.invalidationThreshold ?? '')
  const [periods, setPeriods] = useState(String(current?.invalidationConsecutivePeriods ?? 1))
  const [source, setSource] = useState(current?.expectationSource ?? '研究员人工录入')
  const selected = metrics.find((item) => `${item.metricId}@@${item.version}` === metricKey)
  const refresh = async () => { await Promise.all([qc.invalidateQueries({ queryKey: ['thesis', thesisId] }), qc.invalidateQueries({ queryKey: ['publish-readiness', thesisId] }), qc.invalidateQueries({ queryKey: ['audit', thesisId] })]) }
  const hypothesisMutation = useMutation({ mutationFn: () => updateHypothesis(thesisId, hypothesis.hypothesisId, { statement, hypothesisType, importance, observationWindow, invalidationRule }), onSuccess: refresh })
  const mappingMutation = useMutation({ mutationFn: () => { if (!selected) throw new Error('请从指标字典选择指标。'); if (!expectedValue && !threshold) throw new Error('预期值与失效阈值至少填写一项。'); return saveMetricMapping(thesisId, hypothesis.hypothesisId, { mappingId: current?.mappingId, metricId: selected.metricId, metricVersion: selected.version, expectedDirection, expectedValue, invalidationThreshold: threshold, invalidationConsecutivePeriods: Number(periods), expectationSource: source }) }, onSuccess: refresh })
  const chooseMetric = (value: string) => { setMetricKey(value); const metric = metrics.find((item) => `${item.metricId}@@${item.version}` === value); if (metric?.expectedDirection) setExpectedDirection(metric.expectedDirection) }
  return <article className="hypothesis-editor"><div className="editor-heading"><div><strong>{hypothesis.hypothesisId}</strong><span className={`badge ${importance === '核心' ? 'priority-high' : 'neutral-badge'}`}>{importance}</span></div><span className="muted">{hypothesis.mappings.length} 个验证指标</span></div>
    {hypothesis.metricSuggestions.length > 0 && <div className="ai-suggestions"><span>AI 指标建议（待采用）</span>{hypothesis.metricSuggestions.map((item, index) => <em key={index}>{String(item.metric_name ?? '未命名指标')}{item.rationale ? ` · ${String(item.rationale)}` : ''}</em>)}</div>}
    <div className="form-grid two"><label>假设内容<textarea value={statement} onChange={(event) => setStatement(event.target.value)} /></label><label>失效条件描述<textarea value={invalidationRule} onChange={(event) => setInvalidationRule(event.target.value)} placeholder="由研究员确认，不自动采用 AI 建议" /></label><label>假设类型<select value={hypothesisType} onChange={(event) => setHypothesisType(event.target.value)}><option>行业</option><option>公司竞争力</option><option>经营</option><option>盈利</option><option>政策</option><option>估值</option><option>其他</option></select></label><label>重要性<select value={importance} onChange={(event) => setImportance(event.target.value)}><option>核心</option><option>辅助</option></select></label><label>观察窗口<input value={observationWindow} onChange={(event) => setObservationWindow(event.target.value)} placeholder="例如：未来 4 个季度" /></label><div className="editor-action"><button className="button secondary" disabled={hypothesisMutation.isPending || !statement.trim()} onClick={() => hypothesisMutation.mutate()}>保存假设</button></div></div><InlineError error={hypothesisMutation.error} />
    <div className="mapping-editor"><h3>验证指标与研究员预期</h3><div className="form-grid mapping-grid"><label>指标字典<select value={metricKey} onChange={(event) => chooseMetric(event.target.value)}><option value="">选择已有指标</option>{metrics.map((item) => <option key={`${item.metricId}-${item.version}`} value={`${item.metricId}@@${item.version}`}>{item.name}（{item.metricId} · {item.unit}）</option>)}</select></label><label>预期方向<select value={expectedDirection} onChange={(event) => setExpectedDirection(event.target.value)}><option>越高越好</option><option>越低越好</option><option>不低于阈值</option><option>不高于阈值</option></select></label><label>预期值<input inputMode="decimal" value={expectedValue} onChange={(event) => setExpectedValue(event.target.value)} placeholder="可选" /></label><label>失效阈值<input inputMode="decimal" value={threshold} onChange={(event) => setThreshold(event.target.value)} placeholder="可选" /></label><label>连续期数<input type="number" min="1" max="12" value={periods} onChange={(event) => setPeriods(event.target.value)} /></label><label>预期来源<input value={source} onChange={(event) => setSource(event.target.value)} placeholder="会议纪要、研究员判断等" /></label></div><button className="button primary" disabled={mappingMutation.isPending || !metricKey || !source.trim()} onClick={() => mappingMutation.mutate()}>{current ? '更新指标映射' : '采用并保存指标'}</button><InlineError error={mappingMutation.error} /></div>
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
    <section className="impact-panel"><div><span className="eyebrow">当前影响</span><h2>{activeHypothesis?.statement ?? '选择一条有效关联后进行判断'}</h2><p>{activeThesis?.title ?? '当前没有可操作的逻辑关联'}</p><div className="badge-row">{activeRelation && <><DirectionBadge direction={activeRelation.direction} /><StatusBadge state={activeRelation.status} /><span className="badge neutral-badge">{strengthText[activeRelation.strength]}强度</span><span className="badge neutral-badge">AI {Math.round(item.aiConfidence * 100)}%</span></>}</div></div>{activeRelation?.canManage && activeRelation.status !== 'deactivated' && <div className="decision-panel"><span>你的判断</span><div className="button-row"><button className="button primary" onClick={() => setDialog({ relation: activeRelation, action: '确认' })}>确认关联</button><button className="button secondary" onClick={() => setDialog({ relation: activeRelation, action: '驳回' })}>驳回</button><button className="button ghost" onClick={() => setDialog({ relation: activeRelation, action: '暂不判断' })}>暂不判断</button></div></div>}</section>
    <InlineError error={action.error} />
    <details className="content-section disclosure"><summary>高级关联管理 <span>{relations.data.length} 条关联</span></summary><div className="relation-list">{relations.data.map((relation) => { const target = thesisMap.get(relation.thesisId); const hypothesis = target?.hypotheses.find((h) => h.hypothesisId === relation.hypothesisId); return <article className={`relation-row ${relation.status === 'deactivated' ? 'disabled' : ''}`} key={relation.relationId}><div><div className="badge-row"><StatusBadge state={relation.status} /><DirectionBadge direction={relation.direction} /></div><h3>{hypothesis?.statement ?? '假设信息待加载'}</h3><p>{target?.title ?? relation.thesisId}</p><small>关联理由：{relation.reason || '未填写'} · 创建人：{relation.createdBy}{relation.reviewedBy ? ` · 审核人：${relation.reviewedBy}` : ''}</small></div>{relation.canManage && relation.status !== 'deactivated' && <div className="relation-actions"><button className="button secondary" onClick={() => setEditing(relation)}>修改</button><button className="button danger-link" onClick={() => setDialog({ relation, action: '解除' })}>解除</button></div>}</article> })}</div><RelationForm evidenceId={evidenceId} thesisList={manageableTheses.data} editing={editing} onDone={async () => { setEditing(null); await invalidate() }} /></details>
    <details className="content-section disclosure technical"><summary>技术信息</summary><dl><dt>证据 ID</dt><dd>{item.evidenceId}</dd><dt>来源文档 ID</dt><dd>{item.sourceDocumentId}</dd><dt>原文定位</dt><dd>{item.evidenceLocator}</dd><dt>模型版本</dt><dd>{item.modelVersion}</dd><dt>提示词版本</dt><dd>{item.promptVersion}</dd></dl></details>
    {dialog && <ConfirmDialog title={dialog.action === '解除' ? '解除这条证据关联' : `${dialog.action}这条证据关联`} description={dialog.action === '解除' ? '解除后该关联保留为历史记录，不再参与状态建议。' : '本次人工判断将被记录并刷新受影响逻辑的状态建议。'} confirmText={dialog.action} danger={dialog.action === '解除' || dialog.action === '驳回'} requireReason={dialog.action === '解除'} onClose={() => setDialog(null)} onConfirm={(reason) => action.mutate({ relation: dialog.relation, action: dialog.action, reason })} />}
  </>
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

export function ReviewsPage() {
  const adjudications = useQuery({ queryKey: ['adjudications'], queryFn: listAdjudications })
  const tasks = useQuery({ queryKey: ['review-tasks'], queryFn: listReviewTasks })
  const ingestion = useQuery({ queryKey: ['ingestion-reviews'], queryFn: listIngestionReviews })
  const jobs = useQuery({ queryKey: ['processing-jobs'], queryFn: listProcessingJobs })
  if (adjudications.isLoading || tasks.isLoading || ingestion.isLoading || jobs.isLoading) return <LoadingState />
  if (adjudications.error || tasks.error || ingestion.error || jobs.error || !adjudications.data || !tasks.data || !ingestion.data || !jobs.data) return <ErrorState error={adjudications.error ?? tasks.error ?? ingestion.error ?? jobs.error} />
  const deadLetters = jobs.data.filter((item) => ['failed', 'dead_letter'].includes(item.status))
  return <><PageTitle eyebrow="质量治理" title="复核与复盘" description="统一处理资料归属、假设匹配、低置信、失败重放与独立导师裁决。" /><section className="content-section"><div className="section-heading"><div><span className="eyebrow">资料复核</span><h2>新资料人工队列</h2></div><span className="muted">{ingestion.data.filter((item) => item.status === 'pending').length} 条待处理</span></div>{ingestion.data.length ? <div className="review-list">{ingestion.data.map((item) => <IngestionReviewCard key={item.reviewId} item={item} />)}</div> : <EmptyState title="没有资料复核项" description="未归属证券、无法匹配假设、低置信事件和处理失败会显示在这里。" />}</section><section className="content-section"><div className="section-heading"><div><span className="eyebrow">失败恢复</span><h2>死信与任务重放</h2></div><span className="muted">{deadLetters.length} 条可重放</span></div>{deadLetters.length ? <div className="review-list">{deadLetters.map((job) => <ProcessingJobCard key={job.jobId} job={job} />)}</div> : <EmptyState title="没有失败任务" description="达到重试上限的任务会持久化在这里，可在原件保留期内重放。" />}</section><section className="content-section"><div className="section-heading"><div><span className="eyebrow">产品复核</span><h2>分配给我的逻辑任务</h2></div><span className="muted">{tasks.data.filter((item) => item.state === '待处理').length} 条待处理</span></div>{tasks.data.length ? <div className="review-list">{tasks.data.map((task) => <ReviewTaskCard key={task.taskId} task={task} />)}</div> : <EmptyState title="没有复核任务" description="重大事件或人工发起的逻辑任务会显示在这里。" />}</section><section className="content-section"><div className="section-heading"><div><span className="eyebrow">独立评测</span><h2>导师裁决队列</h2></div><span className="muted">{adjudications.data.filter((item) => !item.resolved).length} 条待裁决</span></div>{adjudications.data.length ? <div className="review-list">{adjudications.data.map((item) => <AdjudicationCard key={item.eventId} item={item} />)}</div> : <EmptyState title="没有待裁决样本" description="存在独立标注分歧时会进入此队列。" />}</section></>
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

function SafeSourceLink({ url }: { url: string }) {
  const valid = (() => { try { return ['http:', 'https:'].includes(new URL(url).protocol) } catch { return false } })()
  return valid ? <a className="source-link" href={url} target="_blank" rel="noopener noreferrer">查看公开原文 ↗</a> : <span className="muted">公开原文链接不可用</span>
}
