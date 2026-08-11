import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { NavLink, useParams, useSearchParams } from 'react-router-dom'
import {
  createRelation, deactivateRelation, decideStatus, getAdjudications, getAudit,
  getEvidence, getRadarEvidence, getRelations, getSuggestions, getThesis,
  getThesisEvidenceFeed, getTrends, getWorkbench, getWorkbenchTasks, listTheses,
  publishThesis, reviewRelation, updateRelation,
} from './api'
import {
  ConfirmDialog, DirectionBadge, EmptyState, ErrorState, EvidenceEventRow,
  InlineError, LoadingState, PageTitle, PriorityBadge, StatusBadge, ValidationChain,
} from './components'
import type { Relation, ThesisDetail } from './types'
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
    {item.status === '草稿' && <PublishPanel thesisId={thesisId} />}
  </>
}

function PublishPanel({ thesisId }: { thesisId: string }) {
  const qc = useQueryClient()
  const [direction, setDirection] = useState('观察')
  const [horizonEndOn, setHorizonEndOn] = useState('2026-12-31')
  const [nextReviewAt, setNextReviewAt] = useState('2026-09-30')
  const mutation = useMutation({ mutationFn: () => publishThesis(thesisId, { direction, horizonEndOn, nextReviewAt }), onSuccess: () => qc.invalidateQueries({ queryKey: ['thesis', thesisId] }) })
  return <section className="content-section"><h2>人工发布逻辑</h2><div className="form-grid"><select value={direction} onChange={(event) => setDirection(event.target.value)}><option>观察</option><option>看多</option><option>看空</option></select><input type="date" value={horizonEndOn} onChange={(event) => setHorizonEndOn(event.target.value)} /><input type="date" value={nextReviewAt} onChange={(event) => setNextReviewAt(event.target.value)} /><button className="button primary" disabled={mutation.isPending} onClick={() => mutation.mutate()}>确认并发布</button><InlineError error={mutation.error} /></div></section>
}

export function EvidencePage() {
  const { evidenceId = '' } = useParams()
  const [params] = useSearchParams()
  const requestedRelationId = params.get('relationId')
  const qc = useQueryClient()
  const evidence = useQuery({ queryKey: ['evidence', evidenceId], queryFn: () => getEvidence(evidenceId) })
  const relations = useQuery({ queryKey: ['relations', evidenceId], queryFn: () => getRelations(evidenceId) })
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
    <section className="fact-panel"><div className="panel-label">来源事实</div><blockquote>{item.factExcerpt}</blockquote><div className="source-footer"><span>{item.sourceDocumentTitle} · {formatDate(item.disclosedAt)}</span><SafeSourceLink url={item.sourceUrl} /></div></section>
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

export function ReviewsPage() {
  const query = useQuery({ queryKey: ['adjudications'], queryFn: getAdjudications })
  if (query.isLoading) return <LoadingState />
  if (query.error || !query.data) return <ErrorState error={query.error} />
  return <><PageTitle eyebrow="质量治理" title="复核与复盘" description="聚焦存在标注分歧的样本，保留人工裁决与复盘记录。" />{query.data.length ? <div className="review-list">{query.data.map((item) => <article className="review-card" key={String(item.event_id)}><div><span className="badge priority-medium">待裁决</span><h2>{String(item.company)} · {String(item.title)}</h2></div><div className="review-comparison"><p><strong>标注 A</strong>{String(item.annotator_a_hypothesis)} · {String(item.annotator_a_direction)}</p><p><strong>标注 B</strong>{String(item.annotator_b_hypothesis)} · {String(item.annotator_b_direction)}</p></div></article>)}</div> : <EmptyState title="没有待裁决任务" description="存在模型或人工标注分歧时会进入此队列。" />}</>
}

function SafeSourceLink({ url }: { url: string }) {
  const valid = (() => { try { return ['http:', 'https:'].includes(new URL(url).protocol) } catch { return false } })()
  return valid ? <a className="source-link" href={url} target="_blank" rel="noopener noreferrer">查看公开原文 ↗</a> : <span className="muted">公开原文链接不可用</span>
}
