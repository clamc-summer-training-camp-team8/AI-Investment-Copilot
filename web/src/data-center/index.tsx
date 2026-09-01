import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { NavLink, Outlet, useParams, useSearchParams } from 'react-router-dom'
import {
  deleteDataCenterDocument,
  fetchDataCenterContent,
  getDataCenterDocument,
  getDataCenterOverview,
  getDocumentSegment,
  getMarketDatasetDetail,
  getQuantCatalog,
  listDataCenterDocuments,
  listDataCenterRuns,
  listDataCenterSources,
  rebuildAssetSearchIndex,
  reprocessDataCenterDocument,
  restoreDataCenterDocument,
  updateDataCenterVisibility,
} from '../api'
import { EmptyState, ErrorState, InlineError, LoadingState, PageTitle } from '../components'
import type { DataCenterDocument, DataCenterRun } from '../types'
import './data-center.css'

const pageSize = 20

function dateTime(value?: string) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

function bytes(value?: number) {
  if (value == null) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KiB`
  return `${(value / 1024 / 1024).toFixed(1)} MiB`
}

function shortHash(value: string) {
  return value.length > 16 ? `${value.slice(0, 12)}…${value.slice(-4)}` : value
}

function Status({ value, tone }: { value: string; tone?: string }) {
  const resolved = tone ?? (
    ['succeeded', '完整正文', '公开披露已核验', '用户授权上传', '项目自有', 'frozen'].includes(value)
      ? 'good'
      : ['failed', 'dead_letter', '待确认', 'blocked'].includes(value) ? 'bad' : 'neutral'
  )
  return <span className={`dc-status ${resolved}`}>{value}</span>
}

export function DataCenterLayout() {
  return <section className="data-center">
    <PageTitle eyebrow="GOVERNED DATA ASSETS" title="数据中心" description="统一查看研究资料、不可变版本、来源授权、处理运行和冻结量化数据。" />
    <nav className="dc-tabs" aria-label="数据中心二级导航">
      <NavLink end to="/assets">数据总览</NavLink>
      <NavLink to="/assets/documents">研究资料</NavLink>
      <NavLink to="/assets/market-datasets">量化数据</NavLink>
      <NavLink to="/assets/runs">数据源与运行</NavLink>
    </nav>
    <Outlet />
  </section>
}

export function DataCenterOverviewPage() {
  const query = useQuery({ queryKey: ['data-center', 'overview'], queryFn: getDataCenterOverview })
  if (query.isLoading) return <LoadingState text="正在汇总受治理数据资产…" />
  if (query.error || !query.data) return <ErrorState error={query.error} />
  const data = query.data
  const metrics = [
    ['活动研究资料', data.documents, '当前账户可见范围', '/assets/documents'],
    ['已归档原件', data.archivedDocuments, `${data.missingArchiveDocuments} 份缺少对象原件`, '/assets/documents?archived=true'],
    ['完整正文', data.fullTextDocuments, `${data.titleIndexDocuments} 份仍为标题索引`, '/assets/documents?content_status=完整正文'],
    ['授权已核验', data.authorizationVerifiedDocuments, `${data.pendingAuthorizationDocuments} 份待确认`, '/assets/documents?authorization_status=公开披露已核验'],
    ['冻结行情版本', data.marketDatasetCount, data.defaultMarketDataVersion ?? '尚未登记默认版本', '/assets/market-datasets'],
    ['近 7 日成功运行', data.recentSucceededRuns, `${data.recentFailedRuns} 条失败`, '/assets/runs'],
  ] as const
  return <>
    <div className="dc-as-of">统计时点 {dateTime(data.asOf)}</div>
    <section className="dc-metrics" aria-label="数据资产概览">
      {metrics.map(([label, value, note, target]) => <NavLink to={target} key={label}><span>{label}</span><strong>{value.toLocaleString()}</strong><small>{note}</small></NavLink>)}
    </section>
    <div className="dc-overview-grid">
      <section className="dc-panel">
        <header><div><span className="eyebrow">ACTION REQUIRED</span><h2>需要关注</h2></div><NavLink to="/assets/runs">查看运行</NavLink></header>
        {data.attention.length ? <div className="dc-attention-list">{data.attention.map((item) => <NavLink to={item.target} key={item.code}><i className={item.severity}>{item.severity === 'high' ? '!' : '·'}</i><span><strong>{item.label}</strong><small>进入对应目录定位具体对象</small></span><b>{item.count}</b></NavLink>)}</div> : <EmptyState title="当前没有治理阻断项" description="原件、授权和最近处理运行均处于可接受状态。" />}
      </section>
      <section className="dc-panel">
        <header><div><span className="eyebrow">LATEST RUNS</span><h2>最近处理运行</h2></div><NavLink to="/assets/runs">全部运行</NavLink></header>
        {data.recentRuns.length ? <RunList runs={data.recentRuns} compact /> : <EmptyState title="暂无最近运行" description="新的归档、解析和重处理运行会出现在这里。" />}
      </section>
    </div>
    <section className="dc-principles"><article><b>01</b><div><strong>原件归档 ≠ 正文解析</strong><p>对象已保存只证明可回溯，只有成功解析并具备 locator 才能支撑正文事实。</p></div></article><article><b>02</b><div><strong>候选版本 ≠ 默认版本</strong><p>只有清单和子资产哈希通过并完成登记的冻结数据，才可进入量化研究。</p></div></article><article><b>03</b><div><strong>权限先于检索与统计</strong><p>列表、聚合、来源和原件均按当前账户权限过滤，不展示不可见对象数量。</p></div></article></section>
  </>
}

function setParam(current: URLSearchParams, key: string, value: string) {
  const next = new URLSearchParams(current)
  if (value) next.set(key, value); else next.delete(key)
  next.set('offset', '0')
  return next
}

export function DataCenterDocumentsPage() {
  const [params, setParams] = useSearchParams()
  const [searchText, setSearchText] = useState(params.get('q') ?? '')
  const requestParams = useMemo(() => {
    const next = new URLSearchParams(params)
    next.set('limit', String(pageSize))
    if (!next.has('offset')) next.set('offset', '0')
    return next
  }, [params])
  const key = requestParams.toString()
  const query = useQuery({ queryKey: ['data-center', 'documents', key], queryFn: () => listDataCenterDocuments(requestParams), placeholderData: (previous) => previous })
  useEffect(() => setSearchText(params.get('q') ?? ''), [params])
  const submit = (event: FormEvent) => { event.preventDefault(); setParams(setParam(params, 'q', searchText.trim())) }
  const offset = Number(params.get('offset') ?? 0)
  return <>
    <section className="dc-panel dc-catalog-toolbar">
      <form onSubmit={submit}><label className="dc-search"><span>⌕</span><input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder="搜索标题、资料编号或可检索正文" /><button className="button primary">搜索</button></label></form>
      <div className="dc-filters">
        <label>内容状态<select value={params.get('content_status') ?? ''} onChange={(event) => setParams(setParam(params, 'content_status', event.target.value))}><option value="">全部</option><option>完整正文</option><option>标题索引</option><option>原件已归档</option><option>待核验</option><option>合成样例</option></select></label>
        <label>原件归档<select value={params.get('archived') ?? ''} onChange={(event) => setParams(setParam(params, 'archived', event.target.value))}><option value="">全部</option><option value="true">已归档</option><option value="false">缺原件</option></select></label>
        <label>运行状态<select value={params.get('run_status') ?? ''} onChange={(event) => setParams(setParam(params, 'run_status', event.target.value))}><option value="">全部</option><option value="succeeded">成功</option><option value="running">运行中</option><option value="failed">失败</option><option value="queued">排队</option></select></label>
        <label>授权状态<select value={params.get('authorization_status') ?? ''} onChange={(event) => setParams(setParam(params, 'authorization_status', event.target.value))}><option value="">全部</option><option>公开披露已核验</option><option>用户授权上传</option><option>项目自有</option><option>待确认</option></select></label>
        <label>证券<input value={params.get('security_id') ?? ''} onChange={(event) => setParams(setParam(params, 'security_id', event.target.value.trim()))} placeholder="代码" /></label>
        <label>行业<input value={params.get('industry') ?? ''} onChange={(event) => setParams(setParam(params, 'industry', event.target.value.trim()))} placeholder="行业名称" /></label>
        <label>来源<input value={params.get('source_id') ?? ''} onChange={(event) => setParams(setParam(params, 'source_id', event.target.value.trim()))} placeholder="来源编号" /></label>
        <label>排序<select value={params.get('sort') ?? 'published_at'} onChange={(event) => setParams(setParam(params, 'sort', event.target.value))}><option value="published_at">披露时间</option><option value="ingested_at">入库时间</option><option value="latest_run_at">最近运行</option><option value="title">标题</option></select></label>
      </div>
      <div className="dc-filter-footer"><span>{query.data ? `共 ${query.data.total.toLocaleString()} 份资料` : '正在读取目录'}</span><button className="button secondary" onClick={() => { setSearchText(''); setParams({}) }}>清空筛选</button></div>
    </section>
    {query.isLoading && <LoadingState text="正在加载研究资料目录…" />}
    {query.error && <ErrorState error={query.error} />}
    {query.data && (query.data.items.length ? <section className="dc-panel dc-table-panel"><div className="dc-document-table dc-table-head"><span>资料</span><span>关联对象</span><span>披露/来源</span><span>内容与授权</span><span>处理状态</span><span /></div>{query.data.items.map((item) => <DocumentRow item={item} key={item.documentId} />)}<Pagination offset={offset} total={query.data.total} onChange={(value) => { const next = new URLSearchParams(params); next.set('offset', String(value)); setParams(next) }} /></section> : <EmptyState title="筛选条件下没有匹配资料" description="可以清空部分筛选，或使用更具体的公司、编号和资料标题。" />)}
  </>
}

function DocumentRow({ item }: { item: DataCenterDocument }) {
  return <article className="dc-document-table dc-document-row">
    <div><NavLink to={`/assets/documents/${encodeURIComponent(item.documentId)}`}>{item.title}</NavLink><small className="mono">{item.documentId}</small>{item.isIllustrative && <Status value="合成样例" />}</div>
    <div><strong>{item.securityNames.join('、') || '未关联证券'}</strong><small>{item.securityIds.join('、') || '—'} · {item.industries.join('、') || '未标注行业'}</small></div>
    <div><strong>{dateTime(item.publishedAt)}</strong><small>{item.sourceName}{item.docType ? ` · ${item.docType}` : ''}</small></div>
    <div><span className="dc-status-line"><Status value={item.contentStatus} tone={item.contentStatus === '标题索引' ? 'warn' : undefined} /><Status value={item.authorizationStatus} /></span><small>{item.archived ? '原件已归档' : '缺少对象原件'} · {item.visibilityLabel}</small></div>
    <div><Status value={item.latestRunStatus ?? '尚无运行'} /><small>{item.segmentCount} 片段 · {item.revisionCount} revisions</small></div>
    <NavLink className="dc-row-link" to={`/assets/documents/${encodeURIComponent(item.documentId)}`}>查看 ›</NavLink>
  </article>
}

function Pagination({ offset, total, onChange }: { offset: number; total: number; onChange: (offset: number) => void }) {
  const current = Math.floor(offset / pageSize) + 1
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return <footer className="dc-pagination"><span>第 {current} / {pages} 页</span><div><button disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - pageSize))}>上一页</button><button disabled={offset + pageSize >= total} onClick={() => onChange(offset + pageSize)}>下一页</button></div></footer>
}

export function DataCenterDocumentDetailPage() {
  const { documentId = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const includeDeleted = params.get('include_deleted') === 'true'
  const requestedLocator = params.get('locator') ?? ''
  const locatorBelongsToDocument = !requestedLocator || requestedLocator.startsWith(`${documentId}#paragraph-`)
  const [activeLocator, setActiveLocator] = useState(locatorBelongsToDocument ? requestedLocator : '')
  const qc = useQueryClient()
  const query = useQuery({ queryKey: ['data-center', 'document', documentId, includeDeleted], queryFn: () => getDataCenterDocument(documentId, includeDeleted) })
  const segment = useQuery({ queryKey: ['document-segment', activeLocator], queryFn: () => getDocumentSegment(activeLocator), enabled: Boolean(activeLocator) && activeLocator.startsWith(`${documentId}#paragraph-`) })
  const [visibility, setVisibility] = useState('内部受限')
  const [actionMessage, setActionMessage] = useState('')
  const [contentError, setContentError] = useState<Error | null>(null)
  const refresh = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['data-center', 'document', documentId] }),
      qc.invalidateQueries({ queryKey: ['data-center', 'documents'] }),
      qc.invalidateQueries({ queryKey: ['data-center', 'overview'] }),
    ])
  }
  const visibilityMutation = useMutation({ mutationFn: () => updateDataCenterVisibility(documentId, visibility), onSuccess: async () => { setActionMessage('可见性已更新'); await refresh() } })
  const reprocessMutation = useMutation({ mutationFn: () => reprocessDataCenterDocument(documentId), onSuccess: async (result) => { setActionMessage(`重处理已入队：${result.jobId}`); await refresh() } })
  const deleteMutation = useMutation({ mutationFn: () => deleteDataCenterDocument(documentId), onSuccess: async () => { setActionMessage('资料已软删除，原件和历史版本继续保留'); await refresh() } })
  const restoreMutation = useMutation({ mutationFn: () => restoreDataCenterDocument(documentId, visibility), onSuccess: async (count) => { setActionMessage(`资料已恢复，检索索引包含 ${count} 个片段`); await refresh() } })
  useEffect(() => {
    if (!locatorBelongsToDocument) setActiveLocator('')
    else if (requestedLocator) setActiveLocator(requestedLocator)
    else if (!requestedLocator && query.data?.contentStatus === '完整正文' && query.data.segmentCount > 0) setActiveLocator(`${documentId}#paragraph-1`)
  }, [documentId, locatorBelongsToDocument, query.data, requestedLocator])
  if (query.isLoading) return <LoadingState text="正在加载资料谱系…" />
  if (query.error || !query.data) return <ErrorState error={query.error} />
  const data = query.data
  const openLocator = (locator?: string) => {
    if (!locator) return
    const next = new URLSearchParams(params)
    next.set('locator', locator)
    setParams(next)
    setActiveLocator(locator)
  }
  const viewContent = async (download: boolean) => {
    setContentError(null)
    try {
      const blob = await fetchDataCenterContent(documentId, download)
      const url = URL.createObjectURL(blob)
      if (download) {
        const link = window.document.createElement('a'); link.href = url; link.download = data.revisions[0]?.sourceFilename ?? data.title; link.click()
      } else window.open(url, '_blank', 'noopener,noreferrer')
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
    } catch (error) { setContentError(error as Error) }
  }
  return <>
    <NavLink className="dc-back" to="/assets/documents">← 返回研究资料</NavLink>
    <section className="dc-detail-hero">
      <div><span className="eyebrow">{data.docType ?? 'RESEARCH DOCUMENT'}</span><h2>{data.title}</h2><p className="mono">{data.documentId}</p><div className="dc-status-line"><Status value={data.contentStatus} tone={data.contentStatus === '标题索引' ? 'warn' : undefined} /><Status value={data.authorizationStatus} /><Status value={data.visibilityLabel} tone="neutral" />{data.archived && <Status value="原件已归档" />}</div></div>
      <div className="dc-detail-actions">{data.allowedActions.includes('view_content') && <><button className="button primary" onClick={() => viewContent(false)}>打开原件</button><button className="button secondary" onClick={() => viewContent(true)}>下载</button></>}</div>
    </section>
    {data.contentStatus === '标题索引' && <section className="dc-boundary-warning"><b>公告标题（非正文）</b><p>当前只允许按标题发现资料。原件已归档不等于正文已解析，不能据此核验正文事实或支撑 AI 事实回答。</p></section>}
    <InlineError error={contentError} />
    <div className="dc-detail-grid">
      <main>
        <section className="dc-panel dc-metadata"><header><div><span className="eyebrow">METADATA</span><h2>资料信息</h2></div></header><dl><div><dt>披露时间</dt><dd>{dateTime(data.publishedAt)}</dd></div><div><dt>入库时间</dt><dd>{dateTime(data.ingestedAt)}</dd></div><div><dt>来源</dt><dd>{data.sourceName}</dd></div><div><dt>证券/公司</dt><dd>{data.securityNames.join('、') || '未关联'}</dd></div><div><dt>行业</dt><dd>{data.industries.join('、') || '未标注'}</dd></div><div><dt>解析片段</dt><dd>{data.segmentCount.toLocaleString()}</dd></div></dl></section>
        {data.contentStatus === '完整正文' && <section className="dc-panel dc-segment-reader"><header><div><span className="eyebrow">TRACEABLE CONTENT</span><h2>可回查正文片段</h2></div><span>{data.segmentCount} 个可定位片段</span></header>{!locatorBelongsToDocument && <div className="dc-boundary-warning"><b>定位参数已忽略</b><p>该 locator 不属于当前资料，页面没有发起跨对象读取。</p></div>}{segment.isLoading && <LoadingState text="正在再次鉴权并读取片段…" />}{segment.error && <ErrorState error={segment.error} />}{segment.data && <article><div className="dc-segment-meta"><code>{segment.data.locator}</code>{segment.data.page && <span>第 {segment.data.page} 页</span>}<span>{segment.data.contentKind}</span><span>{segment.data.extractionMethod}</span>{segment.data.cellRange && <span>{segment.data.cellRange}</span>}</div><p>{segment.data.content}</p><footer><button disabled={!segment.data.previousLocator} onClick={() => openLocator(segment.data?.previousLocator)}>← 上一片段</button><small>正文由服务端按当前账户重新鉴权；内容不会从不可见缓存回填。</small><button disabled={!segment.data.nextLocator} onClick={() => openLocator(segment.data?.nextLocator)}>下一片段 →</button></footer></article>}</section>}
        <section className="dc-panel"><header><div><span className="eyebrow">IMMUTABLE LINEAGE</span><h2>不可变 Revision</h2></div><span>{data.revisions.length} 个版本</span></header>{data.revisions.length ? <div className="dc-revision-list">{data.revisions.map((revision) => <article key={revision.revisionId}><div><Status value={revision.contentStatus} /><strong>{revision.sourceFilename}</strong><small className="mono">{revision.revisionId}</small></div><dl><div><dt>SHA-256</dt><dd className="mono" title={revision.contentHash}>{shortHash(revision.contentHash)}</dd></div><div><dt>原件</dt><dd>{revision.hasObject ? `${bytes(revision.byteSize)} · 已归档` : '缺失'}</dd></div><div><dt>授权</dt><dd>{revision.authorizationStatus}</dd></div><div><dt>来源域名</dt><dd>{revision.sourceHost ?? '—'}</dd></div><div><dt>创建时间</dt><dd>{dateTime(revision.createdAt)}</dd></div><div><dt>状态</dt><dd>{revision.tombstonedAt ? '已软删除' : '活动'}</dd></div></dl>{revision.authorizationBasis && <p>{revision.authorizationBasis}</p>}</article>)}</div> : <EmptyState title="尚无 Revision" description="资料尚未完成不可变原件登记。" />}</section>
        <section className="dc-panel"><header><div><span className="eyebrow">PROCESSING LINEAGE</span><h2>处理运行</h2></div><NavLink to={`/assets/runs?document_id=${encodeURIComponent(documentId)}`}>运行中心</NavLink></header>{data.runs.length ? <RunList runs={data.runs} /> : <EmptyState title="尚无处理运行" description="归档或重处理后会在这里保留追加式历史。" />}</section>
      </main>
      <aside>
        <section className="dc-panel dc-governance-actions"><header><div><span className="eyebrow">GOVERNANCE</span><h2>受控治理</h2></div></header>{data.allowedActions.some((action) => ['change_visibility', 'restore'].includes(action)) && <label>恢复/调整可见性<select value={visibility} onChange={(event) => setVisibility(event.target.value)}><option>公开</option><option>内部</option><option>内部受限</option><option>机密</option></select></label>}{data.allowedActions.includes('change_visibility') && <button className="button secondary" disabled={visibilityMutation.isPending} onClick={() => visibilityMutation.mutate()}>保存可见性</button>}{data.allowedActions.includes('reprocess') && <button className="button primary" disabled={reprocessMutation.isPending} onClick={() => reprocessMutation.mutate()}>提交重处理</button>}{data.allowedActions.includes('delete') && <button className="button danger" disabled={deleteMutation.isPending} onClick={() => { if (window.confirm(`确认软删除“${data.title}”？原件和历史 Revision 会继续保留。`)) deleteMutation.mutate() }}>软删除资料</button>}{data.allowedActions.includes('restore') && <button className="button primary" disabled={restoreMutation.isPending} onClick={() => restoreMutation.mutate()}>恢复资料</button>}<InlineError error={visibilityMutation.error ?? reprocessMutation.error ?? deleteMutation.error ?? restoreMutation.error} />{actionMessage && <p className="success-note">✓ {actionMessage}</p>}</section>
        <section className="dc-panel dc-boundary-card"><h3>数据边界</h3><ul><li>原件访问会再次鉴权并记录审计。</li><li>失败运行与成功重试均不可覆盖。</li><li>软删除只移出活动索引，不物理删除历史对象。</li></ul></section>
      </aside>
    </div>
  </>
}

function RunList({ runs, compact = false }: { runs: DataCenterRun[]; compact?: boolean }) {
  return <div className={`dc-run-list ${compact ? 'compact' : ''}`}>{runs.map((run) => <article key={run.runId}><Status value={run.status} /><div><strong>{run.documentTitle}</strong><small className="mono">{run.runId}</small><p>{run.parserVersion} · {run.chunkerVersion} · {run.extractorVersion}{run.embeddingVersion ? ` · ${run.embeddingVersion}` : ''}</p>{run.error && <em>{run.error}</em>}</div><dl><div><dt>片段</dt><dd>{run.segmentCount}</dd></div><div><dt>事实</dt><dd>{run.factCount}</dd></div><div><dt>事件</dt><dd>{run.eventCount}</dd></div></dl><time>{dateTime(run.finishedAt ?? run.createdAt)}</time></article>)}</div>
}

export function DataCenterMarketDatasetsPage() {
  const query = useQuery({ queryKey: ['quant-catalog'], queryFn: getQuantCatalog })
  if (query.isLoading) return <LoadingState text="正在读取冻结量化数据目录…" />
  if (query.error || !query.data) return <ErrorState error={query.error} />
  return <section className="dc-panel"><header><div><span className="eyebrow">REPRODUCIBLE DATASETS</span><h2>冻结行情版本</h2></div><span>{query.data.marketDatasets.length} 个已登记版本</span></header>{query.data.marketDatasets.length ? <div className="dc-dataset-list">{query.data.marketDatasets.map((dataset) => <article key={dataset.datasetId}><div><span className="dc-status-line"><Status value={dataset.status} />{dataset.datasetId === query.data.defaultMarketDatasetId && <Status value="当前默认" tone="primary" />}</span><h3>{dataset.dataVersion}</h3><small className="mono">{dataset.datasetId}</small></div><dl><div><dt>覆盖区间</dt><dd>{dataset.coverageStart} ~ {dataset.coverageEnd}</dd></div><div><dt>证券数</dt><dd>{dataset.securities.length}</dd></div><div><dt>复权口径</dt><dd>{dataset.adjustment}</dd></div><div><dt>清单哈希</dt><dd className="mono">{shortHash(dataset.manifestSha256)}</dd></div></dl><p>{dataset.limitations[0] ?? '无额外限制说明'}</p><NavLink className="button secondary" to={`/assets/market-datasets/${encodeURIComponent(dataset.datasetId)}`}>查看数据能力</NavLink></article>)}</div> : <EmptyState title="尚无已登记冻结行情" description="候选目录不会自动出现在正式目录；需先完成清单校验和人工发布。" />}</section>
}

export function DataCenterMarketDatasetDetailPage() {
  const { datasetId = '' } = useParams()
  const query = useQuery({ queryKey: ['data-center', 'market-dataset', datasetId], queryFn: () => getMarketDatasetDetail(datasetId) })
  if (query.isLoading) return <LoadingState text="正在核验冻结行情清单…" />
  if (query.error || !query.data) return <ErrorState error={query.error} />
  const data = query.data
  const capabilities = Object.entries(data.capabilities)
  return <>
    <NavLink className="dc-back" to="/assets/market-datasets">← 返回量化数据</NavLink>
    <section className="dc-detail-hero"><div><span className="eyebrow">FROZEN MARKET DATASET</span><h2>{data.dataVersion}</h2><p className="mono">{data.datasetId}</p><div className="dc-status-line"><Status value={data.status} />{data.isDefault && <Status value="当前默认" tone="primary" />}<Status value={data.manifestVerified ? '清单完整' : '完整性失败'} tone={data.manifestVerified ? 'good' : 'bad'} /></div></div><div className="dc-detail-actions"><NavLink className="button primary" to={`/quant?marketDatasetId=${encodeURIComponent(data.datasetId)}`}>使用此版本进入量化实验</NavLink></div></section>
    <section className="dc-panel dc-metadata"><header><div><span className="eyebrow">DATA SCOPE</span><h2>覆盖与授权</h2></div></header><dl><div><dt>覆盖区间</dt><dd>{data.coverageStart} ~ {data.coverageEnd}</dd></div><div><dt>证券数量</dt><dd>{data.securities.length}</dd></div><div><dt>复权口径</dt><dd>{data.adjustment}</dd></div><div><dt>复权锚点</dt><dd>{data.adjustmentAnchorDate ?? '—'}</dd></div><div><dt>时区</dt><dd>{data.timezone}</dd></div><div><dt>历史组合运行</dt><dd>{data.backtestCount}</dd></div></dl>{data.authorizationScope && <p className="dc-note">授权范围：{data.authorizationScope}</p>}</section>
    <div className="dc-two-columns"><section className="dc-panel"><header><div><span className="eyebrow">CAPABILITIES</span><h2>能力矩阵</h2></div></header><div className="dc-capabilities">{capabilities.map(([name, enabled]) => <div key={name}><Status value={enabled ? '可用' : '未准入'} tone={enabled ? 'good' : 'neutral'} /><span>{name}</span></div>)}</div></section><section className="dc-panel"><header><div><span className="eyebrow">LIMITATIONS</span><h2>研究限制</h2></div></header><ul className="dc-limitations">{data.limitations.map((item) => <li key={item}>{item}</li>)}</ul></section></div>
    <section className="dc-panel"><header><div><span className="eyebrow">MANIFEST ASSETS</span><h2>清单子资产</h2></div><span className="mono">{shortHash(data.manifestSha256)}</span></header><div className="dc-asset-files">{data.assets.map((asset) => <article key={asset.name}><Status value={asset.verified ? '哈希通过' : '校验失败'} tone={asset.verified ? 'good' : 'bad'} /><div><strong>{asset.name}</strong><small>{asset.path} · {bytes(asset.byteSize)}</small></div><code title={asset.sha256}>{shortHash(asset.sha256)}</code></article>)}</div></section>
    <section className="dc-panel"><header><div><span className="eyebrow">ALPHA INPUT GATE</span><h2>可用人工确认信号集</h2></div><span>{data.availableSignalSets.length} 个</span></header>{data.availableSignalSets.length ? <div className="dc-signal-sets">{data.availableSignalSets.map((signal) => <article key={signal.signalSetId}><Status value={signal.status} /><div><strong>{signal.name} · {signal.version}</strong><small>{signal.signalCount} 条 · {signal.evaluationTrack} · {shortHash(signal.contentSha256)}</small></div></article>)}</div> : <EmptyState title="暂无可用信号集" description="候选证据、语义金标和检索标签不能直接进入 Alpha 验证。" />}</section>
  </>
}

export function DataCenterRunsPage() {
  const [params, setParams] = useSearchParams()
  const qc = useQueryClient()
  const runParams = useMemo(() => { const next = new URLSearchParams(params); next.set('limit', String(pageSize)); if (!next.has('offset')) next.set('offset', '0'); return next }, [params])
  const runs = useQuery({ queryKey: ['data-center', 'runs', runParams.toString()], queryFn: () => listDataCenterRuns(runParams), placeholderData: (previous) => previous })
  const sources = useQuery({ queryKey: ['data-center', 'sources'], queryFn: listDataCenterSources })
  const rebuild = useMutation({ mutationFn: rebuildAssetSearchIndex, onSuccess: async () => { await Promise.all([qc.invalidateQueries({ queryKey: ['data-center'] }), qc.invalidateQueries({ queryKey: ['asset-inventory'] })]) } })
  const offset = Number(params.get('offset') ?? 0)
  return <div className="dc-runs-grid"><main><section className="dc-panel"><header><div><span className="eyebrow">INGESTION OPERATIONS</span><h2>文档处理运行</h2></div><label>状态<select value={params.get('status') ?? ''} onChange={(event) => setParams(setParam(params, 'status', event.target.value))}><option value="">全部</option><option value="queued">排队</option><option value="running">运行中</option><option value="succeeded">成功</option><option value="failed">失败</option><option value="dead_letter">死信</option></select></label></header>{runs.isLoading && <LoadingState />}{runs.error && <ErrorState error={runs.error} />}{runs.data && (runs.data.items.length ? <><RunList runs={runs.data.items} /><Pagination offset={offset} total={runs.data.total} onChange={(value) => { const next = new URLSearchParams(params); next.set('offset', String(value)); setParams(next) }} /></> : <EmptyState title="当前没有匹配运行" description="调整状态筛选，或等待新的归档与重处理任务。" />)}</section></main><aside><section className="dc-panel"><header><div><span className="eyebrow">SOURCES</span><h2>数据来源</h2></div></header>{sources.isLoading && <LoadingState />}{sources.error && <ErrorState error={sources.error} />}{sources.data?.map((source) => <article className="dc-source-card" key={source.sourceId}><div><Status value={source.authorizationStatus} /><strong>{source.name}</strong><small>{source.sourceType} · {source.baseHost ?? '内部来源'}</small></div><b>{source.documentCount.toLocaleString()}<small>份资料</small></b><p>{source.authorizationBasis ?? source.licenseNote ?? '暂无补充授权说明'}</p></article>)}</section><section className="dc-panel dc-index-admin"><h3>检索索引</h3><p>索引重建是全局管理员操作，不会覆盖不可变 Revision 或历史运行。</p><button className="button secondary" disabled={rebuild.isPending} onClick={() => rebuild.mutate()}>{rebuild.isPending ? '正在重建…' : '重建检索索引'}</button><InlineError error={rebuild.error} />{rebuild.data != null && <p className="success-note">已索引 {rebuild.data} 个片段。</p>}</section></aside></div>
}
