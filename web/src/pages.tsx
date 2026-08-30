import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { NavLink, useParams, useSearchParams } from 'react-router-dom'
import {
  createRelation, createReviewDraft, deactivateRelation, decideAdjudication, decideStatus, getAudit,
  getDocumentSegment, getEvidence, getRadarEvidence, getRelations, getSuggestions,
  getPublishReadiness, getThesis, getThesisEvidenceFeed, getTrends, getWorkbench, getWorkbenchTasks, recheckThesisQuality,
  listAdjudications, listIngestionReviews, listMetrics, listProcessingJobs, listReviewTasks, listTheses,
  publishThesis, replayProcessingJob, resolveIngestionReview, resolveReviewTask,
  recommendHypothesisMetrics, reviewRelation, saveMetricMapping, updateHypothesis, updateRelation,
  getAssetInventory, rebuildAssetSearchIndex, searchAssets,
  createThesisRevision, getThesisRevisionDiff, publishThesisRevision, updateThesisRevision,
} from './api'
import type { Trend } from './types'
import {
  ConfirmDialog, DirectionBadge, EmptyState, ErrorState, EvidenceEventRow,
  InlineError, LoadingState, PageTitle, PriorityBadge, StatusBadge, ValidationChain,
} from './components'
import type { Adjudication, Hypothesis, IngestionReview, MetricDefinition, ProcessingJob, Relation, ReviewTask, ThesisDetail, ThesisRevision } from './types'
import { formatDate, strengthText } from './ui'

export function WorkbenchPage() {
  const summary = useQuery({ queryKey: ['workbench'], queryFn: getWorkbench })
  const tasks = useQuery({ queryKey: ['workbench-tasks'], queryFn: () => getWorkbenchTasks(20) })
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
  const tasks = useQuery({ queryKey: ['review-tasks'], queryFn: listReviewTasks })
  const ingestion = useQuery({ queryKey: ['ingestion-reviews'], queryFn: listIngestionReviews })
  const jobs = useQuery({ queryKey: ['processing-jobs'], queryFn: listProcessingJobs })
  const theses = useQuery({ queryKey: ['theses', 'review-draft'], queryFn: () => listTheses(undefined, true) })
  if (adjudications.isLoading || tasks.isLoading || ingestion.isLoading || jobs.isLoading || theses.isLoading) return <LoadingState />
  if (adjudications.error || tasks.error || ingestion.error || jobs.error || theses.error || !adjudications.data || !tasks.data || !ingestion.data || !jobs.data || !theses.data) return <ErrorState error={adjudications.error ?? tasks.error ?? ingestion.error ?? jobs.error ?? theses.error} />
  const deadLetters = jobs.data.filter((item) => ['failed', 'dead_letter'].includes(item.status))
  return <><PageTitle eyebrow="质量治理" title="复核与复盘" description="统一处理资料归属、假设匹配、低置信、失败重放与独立导师裁决。" /><section className="content-section"><div className="section-heading"><div><span className="eyebrow">资料复核</span><h2>新资料人工队列</h2></div><span className="muted">{ingestion.data.filter((item) => item.status === 'pending').length} 条待处理</span></div>{ingestion.data.length ? <div className="review-list">{ingestion.data.map((item) => <IngestionReviewCard key={item.reviewId} item={item} />)}</div> : <EmptyState title="没有资料复核项" description="未归属证券、无法匹配假设、低置信事件和处理失败会显示在这里。" />}</section><section className="content-section"><div className="section-heading"><div><span className="eyebrow">失败恢复</span><h2>死信与任务重放</h2></div><span className="muted">{deadLetters.length} 条可重放</span></div>{deadLetters.length ? <div className="review-list">{deadLetters.map((job) => <ProcessingJobCard key={job.jobId} job={job} />)}</div> : <EmptyState title="没有失败任务" description="达到重试上限的任务会持久化在这里，可在原件保留期内重放。" />}</section><section className="content-section"><div className="section-heading"><div><span className="eyebrow">产品复核</span><h2>分配给我的逻辑任务</h2></div><span className="muted">{tasks.data.filter((item) => item.state === '待处理').length} 条待处理</span></div>{tasks.data.length ? <div className="review-list">{tasks.data.map((task) => <ReviewTaskCard key={task.taskId} task={task} />)}</div> : <EmptyState title="没有复核任务" description="重大事件或人工发起的逻辑任务会显示在这里。" />}</section><section className="content-section"><div className="section-heading"><div><span className="eyebrow">独立评测</span><h2>导师裁决队列</h2></div><span className="muted">{adjudications.data.filter((item) => !item.resolved).length} 条待裁决</span></div>{adjudications.data.length ? <div className="review-list">{adjudications.data.map((item) => <AdjudicationCard key={item.eventId} item={item} />)}</div> : <EmptyState title="没有待裁决样本" description="存在独立标注分歧时会进入此队列。" />}</section></>
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

function SafeSourceLink({ url }: { url: string }) {
  const valid = (() => { try { return ['http:', 'https:'].includes(new URL(url).protocol) } catch { return false } })()
  return valid ? <a className="source-link" href={url} target="_blank" rel="noopener noreferrer">查看公开原文 ↗</a> : <span className="muted">公开原文链接不可用</span>
}
