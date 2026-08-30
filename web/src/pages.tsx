import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { NavLink, useParams, useSearchParams } from 'react-router-dom'
import {
  createRelation, createReviewDraft, deactivateRelation, decideAdjudication, decideStatus, getAudit,
  getDocumentSegment, getEvidence, getEvidenceRetrievalTrace, getRadarEvidence, getRelations, getSuggestions,
  getPublishReadiness, getThesis, getThesisEvidenceFeed, getTrends, getWorkbench, getWorkbenchTasks, recheckThesisQuality,
  listAdjudications, listIngestionReviews, listMetrics, listProcessingJobs, listReviewTasks, listTheses,
  publishThesis, replayProcessingJob, resolveIngestionReview, resolveReviewTask,
  recommendHypothesisMetrics, reviewRelation, saveMetricMapping, updateHypothesis, updateRelation,
  getAssetInventory, rebuildAssetSearchIndex, searchAssets,
  createThesisRevision, getThesisRevisionDiff, publishThesisRevision, updateThesisRevision,
  getGoldQuality, runQuantBacktest,
} from './api'
import type { Trend } from './types'
import {
  ConfirmDialog, DirectionBadge, EmptyState, ErrorState, EvidenceEventRow,
  InlineError, LoadingState, PageTitle, PriorityBadge, StatusBadge, ValidationChain,
} from './components'
import type { Adjudication, EvidenceRetrievalTrace, GoldQualityGate, Hypothesis, IngestionReview, MetricDefinition, ProcessingJob, QuantBacktestRequest, QuantBacktestRun, QuantEquityPoint, Relation, ReviewTask, ThesisDetail, ThesisRevision } from './types'
import { formatDate, strengthText } from './ui'

export function WorkbenchPage() {
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
  const [expectedDirection, setExpectedDirection] = useState(initial?.expectedDirection ?? '越高越好')
  const [expectedValue, setExpectedValue] = useState(initial?.expectedValue ?? '')
  const [threshold, setThreshold] = useState(initial?.invalidationThreshold ?? '')
  const [periods, setPeriods] = useState(String(initial?.invalidationConsecutivePeriods ?? 1))
  const [source, setSource] = useState(initial?.expectationSource ?? '研究员人工录入')
  const [agentSuggestions, setAgentSuggestions] = useState(hypothesis.metricSuggestions)
  const [adoptedMetric, setAdoptedMetric] = useState<MetricDefinition | null>(null)
  const [adoptedNotice, setAdoptedNotice] = useState('')
  const selected = metrics.find((item) => `${item.metricId}@@${item.version}` === metricKey) ?? adoptedMetric
  const refresh = async () => { await Promise.all([qc.invalidateQueries({ queryKey: ['thesis', thesisId] }), qc.invalidateQueries({ queryKey: ['trends', thesisId] }), qc.invalidateQueries({ queryKey: ['publish-readiness', thesisId] }), qc.invalidateQueries({ queryKey: ['audit', thesisId] })]) }
  const hypothesisMutation = useMutation({ mutationFn: () => updateHypothesis(thesisId, hypothesis.hypothesisId, { statement, hypothesisType, importance, observationWindow, invalidationRule }), onSuccess: refresh })
  const mappingMutation = useMutation({ mutationFn: () => { if (!selected) throw new Error('请从指标字典选择指标。'); if (!expectedValue && !threshold) throw new Error('预期值与失效阈值至少填写一项。'); return saveMetricMapping(thesisId, hypothesis.hypothesisId, { mappingId: mappingId || undefined, metricId: selected.metricId, metricVersion: selected.version, expectedDirection, expectedValue, invalidationThreshold: threshold, invalidationConsecutivePeriods: Number(periods), expectationSource: source }) }, onSuccess: async (saved) => { setMappingId(saved.mappingId); await refresh() } })
  const agentMutation = useMutation({ mutationFn: () => recommendHypothesisMetrics(thesisId, hypothesis.hypothesisId), onSuccess: (candidate) => setAgentSuggestions((candidate.payload.recommendations ?? []) as Array<Record<string, unknown>>) })
  useEffect(() => {
    if (agentMutation.isPending) setAdoptedNotice('正在读取历史数据并推荐指标…')
    else if (agentMutation.isSuccess) setAdoptedNotice(`已完成指标推荐，共 ${agentSuggestions.length} 个候选；请人工确认后保存。`)
  }, [agentMutation.isPending, agentMutation.isSuccess, agentSuggestions.length])
  const chooseMetric = (value: string) => { setMetricKey(value); setAdoptedMetric(null); const metric = metrics.find((item) => `${item.metricId}@@${item.version}` === value); if (metric?.expectedDirection) setExpectedDirection(metric.expectedDirection) }
  const chooseMapping = (value: string) => { const item = hypothesis.mappings.find((mapping) => mapping.mappingId === value); setMappingId(value); setMetricKey(item ? `${item.metricId}@@${item.metricVersion}` : ''); setExpectedDirection(item?.expectedDirection ?? '越高越好'); setExpectedValue(item?.expectedValue ?? ''); setThreshold(item?.invalidationThreshold ?? ''); setPeriods(String(item?.invalidationConsecutivePeriods ?? 1)); setSource(item?.expectationSource ?? '研究员人工录入') }
  const adoptSuggestion = (item: Record<string, unknown>) => { const thresholdSuggestion = (item.threshold_suggestion ?? {}) as Record<string, unknown>; const metric = item.metric_id ? metrics.find((candidate) => `${candidate.metricId}` === String(item.metric_id) && `${candidate.version}` === String(item.metric_version ?? 'v1.0')) ?? { metricId: String(item.metric_id), version: String(item.metric_version ?? 'v1.0'), name: String(item.metric_name ?? item.metric_id), unit: '', status: '待确认' } : metrics.find((candidate) => candidate.name.includes(String(item.metric_name ?? '')) || String(item.metric_name ?? '').includes(candidate.name)); if (!metric) { setMetricKey(''); setSource('请先将 Agent 候选匹配到指标字典'); return } setAdoptedMetric(metric); setMappingId(''); setMetricKey(`${metric.metricId}@@${metric.version}`); setExpectedDirection(String(item.expected_direction ?? metric.expectedDirection ?? '越高越好')); setExpectedValue(''); setThreshold(thresholdSuggestion.value == null ? '' : String(thresholdSuggestion.value)); setSource(`人工确认 Agent 候选；依据：${String(thresholdSuggestion.rationale ?? item.rationale ?? '待补充')}`); setAdoptedNotice(`已填入：${metric.name}。请检查并补充阈值或预期值后保存。`) }
  const renderSuggestionDetails = (item: Record<string, unknown>) => { const thresholdSuggestion = (item.threshold_suggestion ?? {}) as Record<string, unknown>; const observations = Array.isArray(item.observations) ? item.observations as Array<Record<string, unknown>> : []; const unit = String(item.unit ?? (String(item.metric_id ?? '').startsWith('AUTO-') ? '辆' : '')) ; return <><span className="suggestion-meta">{String(item.relation_type ?? '候选指标')} · {String(item.expected_direction ?? '待确认')}</span>{thresholdSuggestion.formula && <span className="suggestion-meta">阈值依据：{String(thresholdSuggestion.formula)} · 样本 {String(thresholdSuggestion.sample_count ?? 0)} 期</span>}{thresholdSuggestion.value != null && <span className="suggestion-meta">建议阈值：{String(thresholdSuggestion.value)}（单位：{unit || '未标注'}）</span>}{observations.length > 0 ? <MiniHistoryChart observations={observations} unit={unit} /> : <span className="suggestion-meta">暂无可用历史观测（可点击重新推荐以触发数据补取）</span>}</> }
  return <article className="hypothesis-editor"><div className="editor-heading"><div><strong>{hypothesis.hypothesisId}</strong><span className={`badge ${importance === '核心' ? 'priority-high' : 'neutral-badge'}`}>{importance}</span>{(hypothesis.logicDimension || hypothesis.causalLevel) && <span className="badge neutral-badge">{hypothesis.logicDimension || hypothesis.causalLevel}</span>}</div><span className="muted">{hypothesis.mappings.length} 个验证指标</span></div>{hypothesis.qualityWarning && <p className="warning-note">{hypothesis.qualityWarning}</p>}
    <div className="ai-suggestions"><span>Agent 指标与阈值依据（仅候选）</span><button className="button secondary" disabled={agentMutation.isPending} onClick={() => agentMutation.mutate()}>{agentMutation.isPending ? '生成中…' : '重新推荐相关指标'}</button>{agentSuggestions.map((item, index) => <em key={index}><strong>{String(item.metric_name ?? '未命名指标')}</strong>{item.rationale ? ` · ${String(item.rationale)}` : ''}{renderSuggestionDetails(item)}<button className="button secondary" onClick={() => adoptSuggestion(item)}>填入人工确认区</button></em>)}<InlineError error={agentMutation.error} /></div>
    <div className="form-grid two"><label>假设内容<textarea value={statement} onChange={(event) => setStatement(event.target.value)} /></label><label>失效条件描述<textarea value={invalidationRule} onChange={(event) => setInvalidationRule(event.target.value)} placeholder="由研究员确认，不自动采用 AI 建议" /></label><label>假设类型<select value={hypothesisType} onChange={(event) => setHypothesisType(event.target.value)}><option>行业</option><option>公司竞争力</option><option>经营</option><option>盈利</option><option>政策</option><option>估值</option><option>其他</option></select></label><label>重要性<select value={importance} onChange={(event) => setImportance(event.target.value)}><option>核心</option><option>辅助</option></select></label><label>观察窗口<input value={observationWindow} onChange={(event) => setObservationWindow(event.target.value)} placeholder="例如：未来 4 个季度" /></label><div className="editor-action"><button className="button secondary" disabled={hypothesisMutation.isPending || !statement.trim()} onClick={() => hypothesisMutation.mutate()}>保存假设</button></div></div><InlineError error={hypothesisMutation.error} />
    <div className="mapping-editor"><h3>验证指标与研究员预期</h3>{adoptedNotice && <p className="success-note">{adoptedNotice}</p>}{trend && <div className="existing-trend"><strong>已有指标历史波动</strong><span>{trend.metricId} · {trend.points.length} 期 · {trend.points.map((point) => `${point.period} ${point.value}${trend.unit}`).join('，')}</span></div>}<div className="form-grid mapping-grid"><label>编辑映射<select value={mappingId} onChange={(event) => chooseMapping(event.target.value)}><option value="">新增指标映射</option>{hypothesis.mappings.map((item) => <option key={item.mappingId} value={item.mappingId}>{item.metricId} · {item.metricVersion}</option>)}</select></label><label>指标字典<select value={metricKey} onChange={(event) => chooseMetric(event.target.value)}><option value="">选择已有指标</option>{metrics.map((item) => <option key={`${item.metricId}-${item.version}`} value={`${item.metricId}@@${item.version}`}>{item.name}（{item.metricId} · {item.unit}）</option>)}</select></label><label>预期方向<select value={expectedDirection} onChange={(event) => setExpectedDirection(event.target.value)}><option>越高越好</option><option>越低越好</option><option>不低于阈值</option><option>不高于阈值</option></select></label><label>预期值<input inputMode="decimal" value={expectedValue} onChange={(event) => setExpectedValue(event.target.value)} placeholder="可选" /></label><label>失效阈值<input inputMode="decimal" value={threshold} onChange={(event) => setThreshold(event.target.value)} placeholder="可选" /></label><label>连续期数<input type="number" min="1" max="12" value={periods} onChange={(event) => setPeriods(event.target.value)} /></label><label>预期来源<input value={source} onChange={(event) => setSource(event.target.value)} placeholder="会议纪要、研究员判断等" /></label></div><button className="button primary" disabled={mappingMutation.isPending || !metricKey || !source.trim()} onClick={() => mappingMutation.mutate()}>{mappingMutation.isPending ? '保存中…' : current ? '更新指标映射' : '人工确认并新增指标'}</button><InlineError error={mappingMutation.error} /></div>
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
