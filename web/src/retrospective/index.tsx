import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { NavLink, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { listTheses } from '../api'
import { EmptyState, ErrorState, InlineError, LoadingState, PageTitle } from '../components'
import {
  archiveRetrospective,
  createRetrospective,
  exportRetrospective,
  generateRetrospectiveAiDraft,
  getRetrospective,
  getRetrospectiveOverview,
  getRetrospectiveTimeline,
  listRetrospectives,
  previewRetrospectiveSources,
  publishRetrospective,
  returnRetrospective,
  reviseRetrospective,
  saveRetrospectiveDraft,
  submitRetrospective,
} from './api'
import type {
  HypothesisAssessment,
  HypothesisResult,
  RetrospectiveContent,
  RetrospectiveDetail,
  RetrospectiveRecord,
  RetrospectiveSource,
  SourcePreview,
} from './types'
import './retrospective.css'

const pageSize = 20
const sourceTypeLabels: Record<string, string> = {
  thesis_version: '逻辑版本', confirmed_evidence: '已确认证据', metric_observation: '指标观测',
  status_decision: '状态处置', review_task: '复核任务', audit: '研究动作',
}

function dateTime(value?: string) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function percent(value: number) { return `${Math.round(value * 100)}%` }

function endOfDayIso(value: string) {
  const end = new Date(`${value}T23:59:59`)
  return new Date(Math.min(end.getTime(), Date.now())).toISOString()
}

function setParam(params: URLSearchParams, key: string, value: string) {
  const next = new URLSearchParams(params)
  if (value) next.set(key, value); else next.delete(key)
  next.set('offset', '0')
  return next
}

function Status({ value }: { value: string }) {
  const tone = value === '已发布' || value === '成立' ? 'good' : value === '待评审' || value === '部分成立' ? 'warn' : value === '已归档' || value === '不成立' ? 'bad' : 'neutral'
  return <span className={`rt-status ${tone}`}>{value}</span>
}

export function RetrospectiveCenterPage() {
  const [params, setParams] = useSearchParams()
  const [searchText, setSearchText] = useState(params.get('q') ?? '')
  const requestParams = useMemo(() => {
    const next = new URLSearchParams(params)
    next.set('limit', String(pageSize))
    if (!next.has('offset')) next.set('offset', '0')
    return next
  }, [params])
  const key = requestParams.toString()
  const overview = useQuery({ queryKey: ['retrospectives', 'overview'], queryFn: getRetrospectiveOverview })
  const list = useQuery({ queryKey: ['retrospectives', 'list', key], queryFn: () => listRetrospectives(requestParams), placeholderData: (previous) => previous })
  useEffect(() => setSearchText(params.get('q') ?? ''), [params])
  const offset = Number(params.get('offset') ?? 0)
  const submit = (event: FormEvent) => { event.preventDefault(); setParams(setParam(params, 'q', searchText.trim())) }
  const metrics = overview.data ? [
    ['逻辑变更', overview.data.logic_changes, '冻结来源中的正式版本'],
    ['已验证假设', overview.data.validated_hypotheses, '已发布人工结论'],
    ['待验证判断', overview.data.pending_hypotheses, '证据不足或尚未到期'],
    ['强反证处理', `${overview.data.strong_conflicts_handled}/${overview.data.strong_conflicts_total}`, '引用或统一解释'],
    ['记录完整度', percent(overview.data.average_completeness), '当前可见复盘平均值'],
    ['待完成复盘', overview.data.pending_reports, '草稿与待评审'],
  ] : []
  return <section className="retrospective-center">
    <PageTitle eyebrow="RESEARCH RETROSPECTIVE" title="复盘中心" description="按历史时点冻结可见来源，完成人工结论、发布、修订与回查。" actions={<NavLink className="button primary" to="/retrospective/new">创建复盘</NavLink>} />
    {overview.isLoading && <LoadingState text="正在汇总可见复盘指标…" />}
    {overview.error && <ErrorState error={overview.error} />}
    {overview.data && <><div className="rt-as-of">统计时点 {dateTime(overview.data.as_of)}{overview.data.is_truncated ? ' · 大于 100 条，概览已标记截断' : ''}</div><section className="rt-metrics" aria-label="复盘概览">{metrics.map(([label, value, note]) => <article key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small></article>)}</section></>}
    <section className="rt-panel rt-toolbar">
      <form onSubmit={submit}><label className="rt-search"><span>⌕</span><input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="搜索报告、投资逻辑或证券代码" /><button className="button primary">搜索</button></label></form>
      <div className="rt-filters">
        <label>状态<select value={params.get('state') ?? ''} onChange={(event) => setParams(setParam(params, 'state', event.target.value))}><option value="">全部</option>{['草稿', '待评审', '已发布', '已归档'].map((item) => <option key={item}>{item}</option>)}</select></label>
        <label>类型<select value={params.get('retrospective_type') ?? ''} onChange={(event) => setParams(setParam(params, 'retrospective_type', event.target.value))}><option value="">全部</option>{['周期', '结项', '专题', '人工'].map((item) => <option key={item}>{item}</option>)}</select></label>
        <label>负责人<input value={params.get('owner') ?? ''} onChange={(event) => setParams(setParam(params, 'owner', event.target.value.trim()))} placeholder="账号 ID" /></label>
        <label>评审人<input value={params.get('reviewer') ?? ''} onChange={(event) => setParams(setParam(params, 'reviewer', event.target.value.trim()))} placeholder="账号 ID" /></label>
        <label>证券<input value={params.get('security_id') ?? ''} onChange={(event) => setParams(setParam(params, 'security_id', event.target.value.trim()))} placeholder="证券代码" /></label>
        <label>行业<input value={params.get('industry') ?? ''} onChange={(event) => setParams(setParam(params, 'industry', event.target.value.trim()))} placeholder="行业名称" /></label>
        <label>假设结果<select value={params.get('hypothesis_result') ?? ''} onChange={(event) => setParams(setParam(params, 'hypothesis_result', event.target.value))}><option value="">全部</option>{['成立', '部分成立', '不成立', '证据不足', '尚未到期'].map((item) => <option key={item}>{item}</option>)}</select></label>
        <label>强反证<select value={params.get('has_strong_conflict') ?? ''} onChange={(event) => setParams(setParam(params, 'has_strong_conflict', event.target.value))}><option value="">全部</option><option value="true">存在</option><option value="false">不存在</option></select></label>
        <label>完整度下限<select value={params.get('completeness_min') ?? ''} onChange={(event) => setParams(setParam(params, 'completeness_min', event.target.value))}><option value="">不限</option><option value="0.5">50%</option><option value="0.8">80%</option><option value="1">100%</option></select></label>
        <label>复盘区间从<input type="date" value={params.get('period_start') ?? ''} onChange={(event) => setParams(setParam(params, 'period_start', event.target.value))} /></label>
        <label>复盘区间至<input type="date" value={params.get('period_end') ?? ''} onChange={(event) => setParams(setParam(params, 'period_end', event.target.value))} /></label>
        <label>发布日从<input type="date" value={params.get('published_start') ?? ''} onChange={(event) => setParams(setParam(params, 'published_start', event.target.value))} /></label>
        <label>发布日至<input type="date" value={params.get('published_end') ?? ''} onChange={(event) => setParams(setParam(params, 'published_end', event.target.value))} /></label>
        <label>排序<select value={params.get('sort') ?? 'updated_at'} onChange={(event) => setParams(setParam(params, 'sort', event.target.value))}><option value="updated_at">最近更新</option><option value="published_at">最近发布</option><option value="period_end">区间结束日</option><option value="completeness_score">记录完整度</option></select></label>
      </div>
      <footer><span>{list.data ? `共 ${list.data.total} 份可见复盘` : '正在读取复盘目录'}</span><button className="button secondary" onClick={() => { setSearchText(''); setParams({}) }}>清空筛选</button></footer>
    </section>
    {list.isLoading && <LoadingState text="正在加载复盘目录…" />}
    {list.error && <ErrorState error={list.error} />}
    {list.data && (list.data.items.length ? <section className="rt-panel rt-list"><div className="rt-row rt-head"><span>报告 / 投资逻辑</span><span>区间 / 截止时点</span><span>负责人</span><span>状态 / 版本</span><span>完整度</span><span /></div>{list.data.items.map((item) => <RetrospectiveRow key={item.retrospective_id} item={item} />)}<Pagination offset={offset} total={list.data.total} onChange={(value) => { const next = new URLSearchParams(params); next.set('offset', String(value)); setParams(next) }} /></section> : <EmptyState title="没有匹配的复盘" description="可调整筛选，或基于一条当前可见的投资逻辑创建首份复盘。" action={<NavLink className="button primary" to="/retrospective/new">创建复盘</NavLink>} />)}
  </section>
}

function RetrospectiveRow({ item }: { item: RetrospectiveRecord }) {
  const results = Object.entries(item.hypothesis_result_counts).map(([key, value]) => `${key} ${value}`).join(' · ')
  return <article className="rt-row rt-report-row"><div><NavLink to={`/retrospective/${item.retrospective_id}`}>{item.title}</NavLink><small>{item.security_id} · {item.thesis_title} · {item.retrospective_type}</small><small>{results || '尚无假设结论'} · 强反证 {item.strong_conflicts_handled}/{item.strong_conflicts_total}</small></div><div><strong>{item.period_start} → {item.period_end}</strong><small>截止 {dateTime(item.data_cutoff_at)}</small></div><div><strong>{item.owner}</strong><small>{item.reviewer ? `评审：${item.reviewer}` : '未指定评审人'}</small></div><div><Status value={item.state} /><small>v{item.current_version} · {item.ai_status}</small></div><div><strong>{percent(item.completeness_score)}</strong><small>{item.completeness_completed}/{item.completeness_applicable} · {item.source_count} 项来源</small></div><NavLink to={`/retrospective/${item.retrospective_id}`}>查看 ›</NavLink></article>
}

function Pagination({ offset, total, onChange }: { offset: number; total: number; onChange: (value: number) => void }) {
  return <footer className="rt-pagination"><span>第 {Math.floor(offset / pageSize) + 1} / {Math.max(1, Math.ceil(total / pageSize))} 页</span><div><button disabled={!offset} onClick={() => onChange(Math.max(0, offset - pageSize))}>上一页</button><button disabled={offset + pageSize >= total} onClick={() => onChange(offset + pageSize)}>下一页</button></div></footer>
}

export function RetrospectiveCreatePage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const theses = useQuery({ queryKey: ['theses'], queryFn: () => listTheses() })
  const today = new Date().toISOString().slice(0, 10)
  const [form, setForm] = useState({ thesis_id: params.get('thesisId') ?? '', retrospective_type: '周期', title: '', period_start: today, period_end: today, reviewer: '' })
  const [preview, setPreview] = useState<SourcePreview | null>(null)
  const input = () => ({ thesis_id: form.thesis_id, period_start: form.period_start, period_end: form.period_end, data_cutoff_at: endOfDayIso(form.period_end) })
  const previewMutation = useMutation({ mutationFn: () => previewRetrospectiveSources(input()), onSuccess: setPreview })
  const createMutation = useMutation({ mutationFn: () => createRetrospective({ ...input(), retrospective_type: form.retrospective_type, title: form.title, reviewer: form.reviewer || undefined }), onSuccess: (item) => navigate(`/retrospective/${item.retrospective_id}/edit`) })
  const change = (key: string, value: string) => { setForm((current) => ({ ...current, [key]: value })); setPreview(null) }
  return <section className="retrospective-center">
    <NavLink className="rt-back" to="/retrospective">‹ 返回复盘目录</NavLink>
    <PageTitle eyebrow="POINT-IN-TIME FREEZE" title="创建复盘" description="先预检来源、时点与缺口；确认后创建不可变来源白名单和人工草稿。" />
    <div className="rt-create-grid"><form className="rt-panel rt-create-form" onSubmit={(event) => { event.preventDefault(); previewMutation.mutate() }}>
      <label>投资逻辑<select value={form.thesis_id} onChange={(event) => change('thesis_id', event.target.value)} required><option value="">选择当前可见逻辑</option>{theses.data?.map((item) => <option value={item.thesisId} key={item.thesisId}>{item.securityId} · {item.title} · {item.owner}</option>)}</select></label>
      <div><label>复盘类型<select value={form.retrospective_type} onChange={(event) => change('retrospective_type', event.target.value)}>{['周期', '结项', '专题', '人工'].map((item) => <option key={item}>{item}</option>)}</select></label><label>评审人（可选）<input value={form.reviewer} onChange={(event) => change('reviewer', event.target.value)} placeholder="账号 ID" /></label></div>
      <label>报告标题<input value={form.title} onChange={(event) => change('title', event.target.value)} minLength={2} required placeholder="例如：2026 年中期逻辑复盘" /></label>
      <div><label>区间开始<input type="date" value={form.period_start} onChange={(event) => change('period_start', event.target.value)} required /></label><label>区间结束<input type="date" max={today} value={form.period_end} onChange={(event) => change('period_end', event.target.value)} required /></label></div>
      <p className="rt-boundary">数据截止默认取区间结束日团队时区日终；若为当天，则取当前实际时点。截止时点后入库、披露或确认的记录不会进入来源。</p>
      <InlineError error={previewMutation.error} /><button className="button primary" disabled={previewMutation.isPending}>{previewMutation.isPending ? '正在执行权限与时点预检…' : '预检冻结来源'}</button>
    </form><aside className="rt-panel rt-preview">{preview ? <PreviewResult preview={preview} onCreate={() => createMutation.mutate()} pending={createMutation.isPending} error={createMutation.error} /> : <EmptyState title="尚未执行来源预检" description="预检不会创建业务对象；它会列出纳入来源、排除数量、完整度和缺项。" />}</aside></div>
  </section>
}

function PreviewResult({ preview, onCreate, pending, error }: { preview: SourcePreview; onCreate: () => void; pending: boolean; error: Error | null }) {
  return <><header><div><span className="eyebrow">SOURCE PREVIEW</span><h2>{preview.thesis_title}</h2></div><strong>{preview.source_count} 项</strong></header><div className="rt-preview-score"><strong>{percent(preview.completeness_score)}</strong><span>记录完整度 · {preview.completeness_completed}/{preview.completeness_applicable}</span></div>{preview.missing_items.length ? <section className="rt-warning"><strong>创建后仍需补齐</strong><ul>{preview.missing_items.map((item) => <li key={item}>{item}</li>)}</ul></section> : <p className="rt-success">当前预检未发现必需记录缺项。</p>}<dl className="rt-exclusions">{Object.entries(preview.excluded_counts).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl><p className="rt-fingerprint">来源指纹预览 <code>{preview.source_fingerprint.slice(0, 16)}…</code></p><InlineError error={error} /><button className="button primary" onClick={onCreate} disabled={pending}>{pending ? '正在冻结并创建…' : '确认范围并创建草稿'}</button></>
}

export function RetrospectiveDetailPage() {
  const { retrospectiveId = '' } = useParams()
  const [tab, setTab] = useState('report')
  const query = useQuery({ queryKey: ['retrospective', retrospectiveId], queryFn: () => getRetrospective(retrospectiveId) })
  const timeline = useQuery({ queryKey: ['retrospective', retrospectiveId, 'timeline'], queryFn: () => getRetrospectiveTimeline(retrospectiveId), enabled: tab === 'timeline' })
  const qc = useQueryClient()
  const action = useMutation({ mutationFn: async (kind: string) => {
    const record = query.data!.retrospective
    if (kind === 'return') return returnRetrospective(retrospectiveId, window.prompt('退回原因') ?? '', record.lock_version)
    if (kind === 'revise') return reviseRetrospective(retrospectiveId, window.prompt('修订原因') ?? '', record.lock_version)
    if (kind === 'archive') return archiveRetrospective(retrospectiveId, window.prompt('归档原因') ?? '', record.lock_version)
    throw new Error('未知操作')
  }, onSuccess: () => qc.invalidateQueries({ queryKey: ['retrospective', retrospectiveId] }) })
  if (query.isLoading) return <LoadingState text="正在加载复盘与冻结来源…" />
  if (query.error || !query.data) return <ErrorState error={query.error} />
  const detail = query.data; const record = detail.retrospective
  return <section className="retrospective-center">
    <NavLink className="rt-back" to="/retrospective">‹ 返回复盘目录</NavLink>
    <header className="rt-detail-hero"><div><span className="eyebrow">{record.retrospective_type} RETROSPECTIVE · {record.retrospective_id}</span><h1>{record.title}</h1><p>{record.security_id} · {record.thesis_title} · {record.period_start} 至 {record.period_end} · 截止 {dateTime(record.data_cutoff_at)}</p></div><div><Status value={record.state} />{detail.allowed_actions.includes('edit') && <NavLink className="button primary" to={`/retrospective/${record.retrospective_id}/edit`}>编辑草稿</NavLink>}{detail.allowed_actions.includes('revise') && <button className="button secondary" onClick={() => action.mutate('revise')}>创建修订</button>}{detail.allowed_actions.includes('return') && <button className="button secondary" onClick={() => action.mutate('return')}>退回修改</button>}{detail.allowed_actions.includes('archive') && <button className="button secondary" onClick={() => action.mutate('archive')}>归档</button>}</div></header>
    <InlineError error={action.error} />
    <section className="rt-facts"><div><span>来源</span><strong>{record.source_count}</strong></div><div><span>完整度</span><strong>{percent(record.completeness_score)}</strong></div><div><span>发布版本</span><strong>v{record.current_version}</strong></div><div><span>负责人 / 评审</span><strong>{record.owner} / {record.reviewer ?? '—'}</strong></div><div><span>来源指纹</span><code>{record.source_fingerprint.slice(0, 14)}…</code></div></section>
    <nav className="rt-tabs">{[['report', '复盘报告'], ['timeline', '研究时间线'], ['sources', '冻结来源'], ['versions', '发布版本']].map(([key, label]) => <button key={key} className={tab === key ? 'active' : ''} onClick={() => setTab(key)}>{label}</button>)}</nav>
    {tab === 'report' && <ReportContent detail={detail} />}
    {tab === 'timeline' && (timeline.isLoading ? <LoadingState text="正在还原研究时间线…" /> : timeline.error ? <ErrorState error={timeline.error} /> : <section className="rt-panel rt-timeline">{timeline.data?.map((item) => <article key={item.source_id} className={item.direction === '冲突' ? 'conflict' : ''}><time>{dateTime(item.occurred_at)}</time><i /><div><span>{item.title}{item.direction ? ` · ${item.direction}` : ''}</span><strong>{item.summary}</strong><small>披露 {dateTime(item.disclosed_at)} · 确认 {dateTime(item.confirmed_at)}</small></div>{item.locator && <SourceLink locator={item.locator} />}</article>)}</section>)}
    {tab === 'sources' && <SourceList sources={detail.sources} />}
    {tab === 'versions' && <section className="rt-panel rt-versions">{detail.versions.length ? detail.versions.map((item) => <article key={item.version}><div><strong>v{item.version}</strong><span>{dateTime(item.created_at)} · {item.published_by}</span></div><p>{item.publish_reason}</p><code>{item.source_fingerprint.slice(0, 18)}…</code></article>) : <EmptyState title="尚无已发布版本" description="草稿不会出现在发布版本列表中。" />}</section>}
    {record.current_version > 0 && <footer className="rt-export"><span>导出只包含当前可见的已发布版本和冻结来源。</span><button onClick={() => exportRetrospective(retrospectiveId, 'markdown')}>导出 Markdown</button><button onClick={() => exportRetrospective(retrospectiveId, 'json')}>导出 JSON</button></footer>}
  </section>
}

function ReportContent({ detail }: { detail: RetrospectiveDetail }) {
  const content = detail.content
  const assessments = Array.isArray(content.hypothesis_assessments) ? content.hypothesis_assessments : []
  return <div className="rt-detail-grid"><main><section className="rt-panel rt-prose"><h2>摘要</h2><p>{content.summary || '尚未填写摘要。'}</p><h2>原判断</h2><p>{content.original_judgement || '—'}</p><h2>关键变化</h2>{Array.isArray(content.key_changes) && content.key_changes.length ? <ul>{content.key_changes.map((item) => <li key={item}>{item}</li>)}</ul> : <p>本区间尚未记录正式变化。</p>}<h2>误差与遗漏</h2><p>{content.errors_and_omissions || '—'}</p><h2>强反证处理</h2><p>{content.conflict_resolution || '—'}</p><h2>来源缺口说明</h2><p>{String(content.source_gaps_acknowledgement || '—')}</p><h2>方法与数据局限</h2><p>{content.limitations || '—'}</p><h2>后续研究建议</h2><p>{content.next_actions || '—'}</p></section></main><aside><section className="rt-panel rt-assessments"><header><h2>假设验证</h2><span>{assessments.length} 条</span></header>{assessments.map((item) => <article key={item.hypothesis_id}><div><strong>{item.statement}</strong><Status value={item.result} /></div><p>{item.rationale || '尚未填写判断理由。'}</p><small>依据：{item.source_ids.length ? item.source_ids.join('、') : '未选择'}</small></article>)}</section>{detail.ai_candidate && <section className="rt-panel rt-ai-note"><span>AI CANDIDATE</span><strong>存在待人工采纳的 AI 候选</strong><p>候选不会自动进入上方报告正文，也不能自动发布。</p></section>}</aside></div>
}

function SourceList({ sources, selectable, selected = [], onToggle }: { sources: RetrospectiveSource[]; selectable?: boolean; selected?: string[]; onToggle?: (id: string) => void }) {
  return <section className="rt-panel rt-sources">{sources.map((item) => <article key={item.source_id}><div>{selectable && <input type="checkbox" aria-label={`选择来源 ${item.source_id}`} checked={selected.includes(item.source_id)} onChange={() => onToggle?.(item.source_id)} />}<span>{sourceTypeLabels[item.source_type] ?? item.source_type}</span><strong>{item.summary}</strong><small>{item.source_id} · 披露 {dateTime(item.disclosed_at)} · 确认 {dateTime(item.confirmed_at)}</small></div><div>{item.direction && <Status value={`${item.direction}${item.strength ? ` · ${item.strength}` : ''}`} />}{item.locator && <SourceLink locator={item.locator} />}</div></article>)}</section>
}

function SourceLink({ locator }: { locator: string }) {
  const documentId = locator.split('#')[0]
  return <NavLink to={`/assets/documents/${encodeURIComponent(documentId)}?locator=${encodeURIComponent(locator)}`}>打开原文 ›</NavLink>
}

export function RetrospectiveEditorPage({ aiEnabled = false }: { aiEnabled?: boolean }) {
  const { retrospectiveId = '' } = useParams()
  const query = useQuery({ queryKey: ['retrospective', retrospectiveId], queryFn: () => getRetrospective(retrospectiveId) })
  if (query.isLoading) return <LoadingState text="正在加载可编辑草稿…" />
  if (query.error || !query.data) return <ErrorState error={query.error} />
  if (!query.data.allowed_actions.includes('edit')) return <ErrorState error={new Error('当前状态或账户不可编辑此复盘。')} />
  return <RetrospectiveEditor key={retrospectiveId} initial={query.data} aiEnabled={aiEnabled} />
}

function RetrospectiveEditor({ initial, aiEnabled }: { initial: RetrospectiveDetail; aiEnabled: boolean }) {
  const id = initial.retrospective.retrospective_id
  const qc = useQueryClient(); const navigate = useNavigate()
  const [title, setTitle] = useState(initial.retrospective.title)
  const [content, setContent] = useState<RetrospectiveContent>(initial.content)
  const [lockVersion, setLockVersion] = useState(initial.retrospective.lock_version)
  const [dirty, setDirty] = useState(false); const [savedAt, setSavedAt] = useState<string>()
  const [candidate, setCandidate] = useState<Record<string, unknown> | undefined>(initial.ai_candidate)
  const contentRef = useRef(content); contentRef.current = content
  const save = useMutation({ mutationFn: (variables: { content: RetrospectiveContent; title: string; lock: number }) => saveRetrospectiveDraft(id, variables.content, variables.lock, variables.title), onSuccess: (record, variables) => { setLockVersion(record.lock_version); setSavedAt(new Date().toISOString()); if (JSON.stringify(contentRef.current) === JSON.stringify(variables.content)) setDirty(false); qc.invalidateQueries({ queryKey: ['retrospective', id] }) } })
  const updateContent = (patch: Partial<RetrospectiveContent>) => { save.reset(); setContent((current) => ({ ...current, ...patch })); setDirty(true) }
  useEffect(() => {
    if (!dirty || save.isPending || save.error) return
    const timer = window.setTimeout(() => save.mutate({ content, title, lock: lockVersion }), 1500)
    return () => window.clearTimeout(timer)
  }, [content, dirty, lockVersion, save, title])
  const ai = useMutation({ mutationFn: () => generateRetrospectiveAiDraft(id, lockVersion), onSuccess: (result) => { setCandidate(result.status === 'completed' && result.candidate ? result.candidate : { status: 'failed' }); setLockVersion(result.lock_version); qc.invalidateQueries({ queryKey: ['retrospective', id] }) } })
  const lifecycle = useMutation({ mutationFn: async (kind: string) => {
    if (dirty) throw new Error('请先保存当前编辑内容，再执行状态操作。')
    if (kind === 'submit') return submitRetrospective(id, window.prompt('指定评审人账号') ?? '', lockVersion)
    if (kind === 'publish') return publishRetrospective(id, window.prompt('发布说明') ?? '', lockVersion)
    throw new Error('未知状态操作')
  }, onSuccess: (record) => { qc.invalidateQueries({ queryKey: ['retrospective', id] }); navigate(`/retrospective/${record.retrospective_id}`) } })
  const assessments = Array.isArray(content.hypothesis_assessments) ? content.hypothesis_assessments : []
  const setAssessment = (index: number, patch: Partial<HypothesisAssessment>) => updateContent({ hypothesis_assessments: assessments.map((item, current) => current === index ? { ...item, ...patch } : item) })
  const applyCandidate = (key: keyof RetrospectiveContent) => { const value = candidate?.[key]; if (value !== undefined) updateContent({ [key]: value }) }
  return <section className="retrospective-center rt-editor">
    <NavLink className="rt-back" to={`/retrospective/${id}`}>‹ 返回复盘详情</NavLink>
    <header className="rt-editor-header"><div><span className="eyebrow">HUMAN EDITOR · LOCK {lockVersion}</span><input value={title} onChange={(event) => { save.reset(); setTitle(event.target.value); setDirty(true) }} aria-label="复盘标题" /></div><div aria-live="polite"><span>{save.isPending ? '正在自动保存…' : save.error ? '保存失败，本地内容已保留' : dirty ? '有未保存修改' : savedAt ? `已保存 ${dateTime(savedAt)}` : '已加载服务端草稿'}</span><button className="button secondary" disabled={save.isPending || !dirty} onClick={() => save.mutate({ content, title, lock: lockVersion })}>保存草稿</button>{initial.allowed_actions.includes('ai_draft') && <button className="button secondary" disabled={!aiEnabled || ai.isPending || dirty} onClick={() => ai.mutate()}>{ai.isPending ? 'AI 整理中…' : aiEnabled ? '生成 AI 候选' : 'AI 候选未启用'}</button>}{initial.allowed_actions.includes('submit') && <button className="button secondary" disabled={lifecycle.isPending} onClick={() => lifecycle.mutate('submit')}>提交评审</button>}{initial.allowed_actions.includes('publish') && <button className="button primary" disabled={lifecycle.isPending} onClick={() => lifecycle.mutate('publish')}>人工发布</button>}</div></header>
    <InlineError error={save.error ?? ai.error ?? lifecycle.error} />
    <div className="rt-editor-grid"><main><TextField label="复盘摘要" value={String(content.summary ?? '')} onChange={(value) => updateContent({ summary: value })} /><TextField label="原判断" value={String(content.original_judgement ?? '')} onChange={(value) => updateContent({ original_judgement: value })} /><TextField label="误差与遗漏" value={String(content.errors_and_omissions ?? '')} onChange={(value) => updateContent({ errors_and_omissions: value })} /><TextField label="高强度冲突处理" value={String(content.conflict_resolution ?? '')} onChange={(value) => updateContent({ conflict_resolution: value })} /><TextField label="来源缺口说明" value={String(content.source_gaps_acknowledgement ?? '')} onChange={(value) => updateContent({ source_gaps_acknowledgement: value })} /><TextField label="方法与数据局限" value={String(content.limitations ?? '')} onChange={(value) => updateContent({ limitations: value })} /><TextField label="后续研究建议" value={String(content.next_actions ?? '')} onChange={(value) => updateContent({ next_actions: value })} />
      <section className="rt-panel rt-edit-assessments"><header><h2>逐条假设结论</h2><span>正式结果由研究员选择</span></header>{assessments.map((item, index) => <article key={item.hypothesis_id}><div><strong>{item.statement}</strong><select value={item.result} onChange={(event) => setAssessment(index, { result: event.target.value as HypothesisResult })}>{['成立', '部分成立', '不成立', '证据不足', '尚未到期'].map((result) => <option key={result}>{result}</option>)}</select></div><textarea value={item.rationale} onChange={(event) => setAssessment(index, { rationale: event.target.value })} placeholder="填写人工判断理由" /><details><summary>选择关键依据（{item.source_ids.length}）</summary><SourceList sources={initial.sources.filter((source) => !source.hypothesis_id || source.hypothesis_id === item.hypothesis_id)} selectable selected={item.source_ids} onToggle={(sourceId) => setAssessment(index, { source_ids: item.source_ids.includes(sourceId) ? item.source_ids.filter((value) => value !== sourceId) : [...item.source_ids, sourceId] })} /></details></article>)}</section></main><aside><section className="rt-panel rt-publication-check"><h2>发布门禁</h2><ul><li className={content.summary ? 'done' : ''}>复盘摘要</li><li className={content.errors_and_omissions ? 'done' : ''}>误差与遗漏</li><li className={content.limitations ? 'done' : ''}>方法与数据局限</li><li className={content.next_actions ? 'done' : ''}>后续研究建议</li><li className={initial.retrospective.completeness_score >= 1 || content.source_gaps_acknowledgement ? 'done' : ''}>来源缺口说明</li><li className={assessments.every((item) => item.rationale && (!['成立', '部分成立', '不成立'].includes(item.result) || item.source_ids.length)) ? 'done' : ''}>假设理由与依据</li><li className={initial.sources.some((item) => item.direction === '冲突' && item.strength === '高') ? (content.conflict_resolution ? 'done' : '') : 'done'}>高强度冲突处理</li></ul><p>这里用于提示；服务端会重新鉴权并执行最终门禁。</p></section><AiCandidate candidate={candidate} apply={applyCandidate} /></aside></div>
  </section>
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label className="rt-panel rt-text-field"><strong>{label}</strong><textarea value={value} onChange={(event) => onChange(event.target.value)} /></label> }

function AiCandidate({ candidate, apply }: { candidate?: Record<string, unknown>; apply: (key: keyof RetrospectiveContent) => void }) {
  if (!candidate) return <section className="rt-panel rt-ai-candidate"><span>AI CANDIDATE</span><strong>尚无候选内容</strong><p>AI 关闭时，人工编辑、评审和发布保持完整可用。</p></section>
  if (candidate.status === 'failed') return <section className="rt-panel rt-ai-candidate"><span>AI CANDIDATE · 生成失败</span><strong>人工编辑仍可继续</strong><p>上一次生成未通过模型、Schema 或引用白名单校验；未覆盖任何人工正文。</p></section>
  return <section className="rt-panel rt-ai-candidate"><span>AI CANDIDATE · 需人工确认</span><h2>冻结来源整理建议</h2><p>{String(candidate.summary ?? '')}</p>{(['summary', 'original_judgement', 'errors_and_omissions', 'limitations', 'next_actions'] as const).map((key) => candidate[key] !== undefined && <button key={key} onClick={() => apply(key)}>采纳 {key}</button>)}<small>模型 {String(candidate.model_version ?? '—')} · Prompt {String(candidate.prompt_version ?? '—')}</small></section>
}
