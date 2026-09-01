import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { changePassword, clearAccessToken, createDraft, createSecurity, getAccessToken, getAuthConfig, getCompanyMetricCenter, getCurrentUser, getJob, listSecurities, listThesisSummaries, login, lookupSecurities, reanalyzeProcessingJob, refreshCompanyMetrics, saveMetricMapping, setAccessToken, updateHypothesis, updateThesisDraft, uploadDocument, useMock } from './api'
import type { AuthConfig, AuthUser } from './api'
import { Icon, InlineError, ResearchContextPicker } from './components'
import { MetricEditorCard } from './metric-editor'
import type { CompanyMetric, JobAccepted, Security, ThesisDetail, ThesisSummary } from './types'
import { CompanyResearchPage, CoverageManagementPage, DocumentReaderPage, EvidencePage, LogicChangeImpactPage, MacroStrategyPage, NotFoundPage, OperationalWorkbenchPage, QualityPage, QuantPage, RadarPage, ResearchImpactDetailPage, ResearchUpdatesPage, ReviewsPage, ThesisListPage, ThesisPage, WorkbenchPage } from './pages'
import { GlobalSearch, KnowledgeAssistant, SourceDrawer } from './research-assistant'
import { DataCenterDocumentDetailPage, DataCenterDocumentsPage, DataCenterLayout, DataCenterMarketDatasetDetailPage, DataCenterMarketDatasetsPage, DataCenterOverviewPage, DataCenterRunsPage } from './data-center'
import { RetrospectiveCenterPage, RetrospectiveCreatePage, RetrospectiveDetailPage, RetrospectiveEditorPage } from './retrospective'

function localDateTimeValue(date = new Date()) {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

const uploadStageLabels: Record<string, string> = {
  parsing: '正在解析文件…',
  reusing_parsed: '正在复用已解析内容…',
  indexed: '解析完成，正在准备事件抽取…',
  extracting_events: '正在抽取事件…',
  matching_hypotheses: '正在判断事件与假设的关系…',
  analysis_timeout: 'AI 分析超时，文件已完成解析',
  analysis_failed: 'AI 分析失败，文件已完成解析',
  completed: '处理完成',
}

export function App() {
  const queryClient = useQueryClient()
  const config = useQuery({ queryKey: ['auth-config'], queryFn: getAuthConfig, retry: 1 })
  const [tokenVersion, setTokenVersion] = useState(0)
  const hasToken = Boolean(getAccessToken())
  const currentUser = useQuery({
    queryKey: ['auth-user', tokenVersion],
    queryFn: getCurrentUser,
    enabled: config.data?.loginRequired === true && hasToken,
    retry: false,
  })

  useEffect(() => {
    const handleUnauthorized = () => {
      queryClient.removeQueries({ queryKey: ['auth-user'] })
      setTokenVersion((value) => value + 1)
    }
    window.addEventListener('copilot:unauthorized', handleUnauthorized)
    return () => window.removeEventListener('copilot:unauthorized', handleUnauthorized)
  }, [queryClient])

  const acceptSession = (token: string) => {
    setAccessToken(token)
    setTokenVersion((value) => value + 1)
  }
  const logout = () => {
    clearAccessToken()
    queryClient.clear()
    setTokenVersion((value) => value + 1)
  }

  if (config.isPending) return <AuthLoading />
  if (config.isError) return <AuthUnavailable error={config.error} onRetry={() => config.refetch()} />
  if (!config.data.loginRequired) {
    return <ProductApp user={{ userId: 'analyst-mvp', teams: ['local'], mustChangePassword: false }} features={config.data} />
  }
  if (!hasToken) return <LoginPage onAuthenticated={acceptSession} />
  if (currentUser.isPending) return <AuthLoading />
  if (currentUser.isError || !currentUser.data) return <LoginPage onAuthenticated={acceptSession} />
  if (currentUser.data.mustChangePassword) {
    return <ChangePasswordPage user={currentUser.data} onChanged={acceptSession} onLogout={logout} />
  }
  return <ProductApp user={currentUser.data} onLogout={logout} features={config.data} />
}

function AuthLoading() {
  return <main className="auth-screen auth-loading"><div className="auth-loading-mark"><span /><span /><span /></div><p>正在建立安全会话…</p></main>
}

function AuthUnavailable({ error, onRetry }: { error: Error; onRetry: () => void }) {
  return <main className="auth-screen"><section className="auth-card auth-state-card"><span className="auth-logo">AI</span><h1>暂时无法连接共享环境</h1><p>{error.message}</p><button className="auth-submit" onClick={onRetry}>重新连接</button></section></main>
}

function LoginPage({ onAuthenticated }: { onAuthenticated: (token: string) => void }) {
  const [userId, setUserId] = useState('')
  const [password, setPassword] = useState('')
  const mutation = useMutation({
    mutationFn: () => login(userId.trim(), password),
    onSuccess: (session) => onAuthenticated(session.accessToken),
  })
  return <main className="auth-screen"><div className="auth-layout"><section className="auth-story"><div className="auth-brand"><span className="auth-logo">AI</span><div><strong>投研引擎</strong><small>INVESTMENT COPILOT</small></div></div><div className="auth-story-copy"><span className="auth-kicker">RESEARCH INFRASTRUCTURE</span><h1>让每条投资逻辑，<br />都沿着证据持续生长。</h1><p>以公司为中心串联逻辑、假设、变量、指标与事实。Graph RAG 帮你找回关系，研究员保留最终判断。</p></div><div className="auth-graph" aria-hidden><span className="node node-a" /><span className="node node-b" /><span className="node node-c" /><span className="node node-d" /><i className="edge edge-a" /><i className="edge edge-b" /><i className="edge edge-c" /></div><footer><span>GRAPH + TEXT RAG</span><span>HUMAN-GATED</span><span>AUDITABLE</span></footer></section><section className="auth-panel"><form className="auth-card" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><span className="auth-panel-index">01 / SECURE ACCESS</span><h2>欢迎回来</h2><p>登录共享集成环境，继续团队投研协作。</p><label>账号<input autoFocus autoComplete="username" value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="请输入团队账号" required /></label><label>密码<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="请输入密码" required /></label>{mutation.error && <div className="auth-error" role="alert">{mutation.error.message}</div>}<button className="auth-submit" type="submit" disabled={mutation.isPending}>{mutation.isPending ? '正在验证…' : '进入研究工作台'}<span>→</span></button><div className="auth-security-note"><span>◈</span><p><strong>安全提示</strong>首次登录后需要修改初始密码；访问令牌仅保存在当前浏览器会话。</p></div></form></section></div></main>
}

function ChangePasswordPage({ user, onChanged, onLogout }: { user: AuthUser; onChanged: (token: string) => void; onLogout: () => void }) {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const mutation = useMutation({
    mutationFn: async () => {
      if (newPassword !== confirmation) throw new Error('两次输入的新密码不一致')
      return changePassword(currentPassword, newPassword)
    },
    onSuccess: (session) => onChanged(session.accessToken),
  })
  return <main className="auth-screen"><section className="auth-card password-card"><div className="auth-brand compact"><span className="auth-logo">AI</span><div><strong>投研引擎</strong><small>SECURITY CHECKPOINT</small></div></div><span className="auth-panel-index">FIRST SIGN-IN</span><h1>设置你的专属密码</h1><p>你好，{user.userId}。这是首次登录，完成改密后即可进入共享研究空间。</p><form onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><label>当前初始密码<input type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required /></label><label>新密码<input type="password" autoComplete="new-password" minLength={10} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder="至少 10 个字符，且不包含账号名" required /></label><label>再次输入新密码<input type="password" autoComplete="new-password" minLength={10} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required /></label>{mutation.error && <div className="auth-error" role="alert">{mutation.error.message}</div>}<button className="auth-submit" disabled={mutation.isPending}>{mutation.isPending ? '正在保存…' : '保存并进入工作台'}<span>→</span></button><button type="button" className="auth-link-button" onClick={onLogout}>返回登录</button></form></section></main>
}

function ProductApp({ user, onLogout, features }: { user: AuthUser; onLogout?: () => void; features: AuthConfig }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [showCreate, setShowCreate] = useState(false)
  const [createPrefill, setCreatePrefill] = useState<Security | undefined>()
  const [showUpload, setShowUpload] = useState(false)
  const [assistantDraft, setAssistantDraft] = useState<{ text: string; nonce: number }>()
  const [sourceLocator, setSourceLocator] = useState<string | null>(null)
  const [uploadThesisId, setUploadThesisId] = useState<string | undefined>()
  const [uploadSecurityId, setUploadSecurityId] = useState<string | undefined>()
  const openCreate = (security?: Security) => { setCreatePrefill(security); setShowCreate(true) }
  const closeCreate = () => { setShowCreate(false); setCreatePrefill(undefined) }
  const openUpload = (thesisId?: string, securityId?: string) => { setUploadThesisId(thesisId); setUploadSecurityId(securityId); setShowUpload(true) }
  const closeUpload = () => { setShowUpload(false); setUploadThesisId(undefined); setUploadSecurityId(undefined) }
  const theses = useQuery({ queryKey: ['thesis-summaries'], queryFn: listThesisSummaries })
  const routeThesis = location.pathname.match(/^\/theses\/([^/]+)/)?.[1]
  const queryThesis = new URLSearchParams(location.search).get('thesisId') ?? undefined
  const currentThesisId = routeThesis ?? queryThesis
  const radarPath = currentThesisId ? `/radar?thesisId=${encodeURIComponent(currentThesisId)}` : '/radar'
  const navigation = [
    ['工作台', '/workbench', '01', 'grid'],
    ['变化雷达', radarPath, '02', 'radar'],
    ['投资逻辑', '/theses', '03', 'graph'],
    ['复核与复盘', '/reviews', '04', 'check'],
    ['数据中心', '/assets', '05', 'archive'],
    ['质量中心', '/quality', '06', 'quality'],
    ['量化实验', '/quant', '07', 'quant'],
  ] as const
  const isNavigationActive = (label: string, path: string) => location.pathname === path || (label === '变化雷达' && location.pathname.startsWith('/radar')) || (label === '投资逻辑' && location.pathname.startsWith('/theses')) || (label === '复核与复盘' && location.pathname.startsWith('/retrospective')) || (label === '数据中心' && location.pathname.startsWith('/assets'))
  const activeIndex = navigation.findIndex(([label, path]) => isNavigationActive(label, path))
  const isWorkbench = location.pathname === '/workbench'
  const isCompanyResearch = location.pathname.startsWith('/companies/')
  const isCoverageManagement = location.pathname === '/coverage'
  const isMacroStrategy = location.pathname === '/macro-strategy'
  const isResearchUpdates = location.pathname.startsWith('/updates')
  const isRetrospective = location.pathname.startsWith('/retrospective')
  const isLogicChange = location.pathname.startsWith('/logic-changes/')
  const isDocumentReader = location.pathname.startsWith('/documents/')
  const isEvidenceDetail = /^\/radar\/[^/]+$/u.test(location.pathname)
  return <div className={`app-shell ${isWorkbench ? 'workbench-shell' : ''} ${isCompanyResearch ? 'company-shell' : ''} ${isCoverageManagement ? 'coverage-shell' : ''} ${isMacroStrategy ? 'macro-shell' : ''} ${isResearchUpdates ? 'updates-shell' : ''} ${isRetrospective ? 'retrospective-shell' : ''} ${isLogicChange ? 'logic-change-shell' : ''} ${isDocumentReader ? 'document-reader-shell' : ''} ${isEvidenceDetail ? 'evidence-detail-shell' : ''}`}>
    <a className="skip-link" href="#main-content">跳到主要内容</a>
    <header className="global-topbar dashboard-topbar">
      <NavLink to="/workbench" className="brand dashboard-brand" aria-label="返回工作台"><span className="brand-mark"><Icon name="graph" size={20} /></span><span className="brand-copy"><strong>投研引擎工作台</strong><small>AI INVESTMENT COPILOT</small></span></NavLink>
      {features.globalSearchEnabled ? <GlobalSearch userId={user.userId} onAsk={features.knowledgeQaEnabled ? (text) => setAssistantDraft({ text, nonce: Date.now() }) : undefined} onOpenSource={setSourceLocator} /> : <label className="global-search"><span aria-hidden>⌕</span><input readOnly aria-label="搜索功能未启用" placeholder="搜索功能未启用" /></label>}
      <nav className="dashboard-nav" aria-label="顶部主导航"><NavLink to="/workbench">工作台</NavLink><NavLink to="/operations">任务中心</NavLink><NavLink to="/retrospective">复盘中心</NavLink><NavLink to="/assets">数据中心</NavLink><NavLink to="/theses">模型与因子</NavLink></nav>
      <div className="dashboard-utilities"><button aria-label="收藏">☆</button><button aria-label="消息">♧<b>8</b></button><span className="dashboard-avatar">{user.userId.slice(0, 1).toUpperCase()}</span><span>{user.userId}</span>{onLogout && <button className="logout-button" onClick={onLogout}>退出</button>}</div>
    </header>
    <aside className="sidebar" aria-label="产品主导航"><div className="rail-heading"><span className="mono">0{Math.max(0, activeIndex) + 1}</span><small>RESEARCH DESK</small></div><nav>{navigation.map(([label, path, index, icon]) => <NavLink key={label} to={path} aria-label={label} className={() => isNavigationActive(label, path) ? 'active' : ''}><Icon name={icon} size={18} /><span className="nav-copy"><b>{label}</b><small className="mono">{index}</small></span></NavLink>)}</nav><div className="sidebar-footer"><span><i className="live-dot" />{useMock ? '受控 Mock 数据' : '真实公开数据'}</span><small>研究辅助 · 人工决策</small></div></aside>
    <div className="workspace"><header className="workspace-bar"><ResearchContextPicker theses={theses.data ?? []} value={currentThesisId} onChange={(id) => id ? navigate(`/radar?thesisId=${encodeURIComponent(id)}`) : navigate('/workbench')} /><div className="top-actions"><button className="button secondary" onClick={() => openUpload()}><Icon name="upload" size={15} />上传研究资料</button><button className="button primary" onClick={() => openCreate()}><span aria-hidden>＋</span>新建研究主题</button></div></header><main className="main-content" id="main-content" tabIndex={-1}><Routes><Route path="/" element={<Navigate to="/workbench" replace />} /><Route path="/workbench" element={<WorkbenchPage onCreate={() => openCreate()} />} /><Route path="/operations" element={<OperationalWorkbenchPage />} /><Route path="/coverage" element={<CoverageManagementPage onCreate={openCreate} />} /><Route path="/macro-strategy" element={<MacroStrategyPage />} /><Route path="/updates" element={<ResearchUpdatesPage />} /><Route path="/updates/:updateId" element={<ResearchImpactDetailPage />} /><Route path="/logic-changes/:securityId/:thesisId" element={<LogicChangeImpactPage />} /><Route path="/documents/:documentId" element={<DocumentReaderPage />} /><Route path="/companies/:securityId" element={<CompanyResearchPage onCreate={openCreate} onUpload={openUpload} />} /><Route path="/radar" element={<RadarPage />} /><Route path="/radar/:evidenceId" element={<EvidencePage />} /><Route path="/theses" element={<ThesisListPage />} /><Route path="/theses/:thesisId" element={<ThesisPage />} /><Route path="/reviews" element={<ReviewsPage />} /><Route path="/retrospective" element={features.retrospectiveCenterEnabled ? <RetrospectiveCenterPage /> : <NotFoundPage />} /><Route path="/retrospective/new" element={features.retrospectiveCenterEnabled ? <RetrospectiveCreatePage /> : <NotFoundPage />} /><Route path="/retrospective/:retrospectiveId" element={features.retrospectiveCenterEnabled ? <RetrospectiveDetailPage /> : <NotFoundPage />} /><Route path="/retrospective/:retrospectiveId/edit" element={features.retrospectiveCenterEnabled ? <RetrospectiveEditorPage aiEnabled={features.retrospectiveAiDraftEnabled} /> : <NotFoundPage />} /><Route path="/assets" element={<DataCenterLayout />}><Route index element={<DataCenterOverviewPage />} /><Route path="documents" element={<DataCenterDocumentsPage />} /><Route path="documents/:documentId" element={<DataCenterDocumentDetailPage />} /><Route path="market-datasets" element={<DataCenterMarketDatasetsPage />} /><Route path="market-datasets/:datasetId" element={<DataCenterMarketDatasetDetailPage />} /><Route path="runs" element={<DataCenterRunsPage />} /></Route><Route path="/quality" element={<QualityPage />} /><Route path="/quant" element={<QuantPage />} /><Route path="*" element={<NotFoundPage />} /></Routes></main></div>
    <nav className="mobile-nav" aria-label="移动端主导航">{navigation.map(([label, path, , icon]) => <NavLink key={label} to={path} aria-label={label} className={() => isNavigationActive(label, path) ? 'active' : ''}><Icon name={icon} size={18} /><span>{label}</span></NavLink>)}</nav>
    <footer className="disclaimer">AI 生成内容仅作为研究候选 · 所有证据、关系与状态变更均需人工确认<span className="mono">AUDITABLE / TRACEABLE / HUMAN-GATED</span></footer>
    {features.knowledgeQaEnabled && <KnowledgeAssistant currentThesisId={currentThesisId} theses={theses.data ?? []} prefill={assistantDraft} onOpenSource={setSourceLocator} />}
    <SourceDrawer locator={sourceLocator} onClose={() => setSourceLocator(null)} />
    {showCreate && <CreateDraftDialogV2 theses={theses.data ?? []} initialSecurity={createPrefill} onClose={closeCreate} />}
    {showUpload && <UploadDocumentDialog theses={theses.data ?? []} initialThesisId={uploadThesisId ?? currentThesisId} initialSecurityId={uploadSecurityId} onClose={closeUpload} />}
  </div>
}

function UploadDocumentDialog({ theses, initialThesisId, initialSecurityId, onClose }: { theses: ThesisSummary[]; initialThesisId?: string; initialSecurityId?: string; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [publishedAt, setPublishedAt] = useState(() => localDateTimeValue())
  const thesisSecurityId = theses.find((item) => item.thesisId === initialThesisId)?.securityId ?? ''
  const refreshSecurityId = initialSecurityId ?? thesisSecurityId
  const [securityChoice, setSecurityChoice] = useState(initialSecurityId ?? thesisSecurityId)
  const [newSecurityId, setNewSecurityId] = useState('')
  const [newSecurityName, setNewSecurityName] = useState('')
  const [newSecurityIndustry, setNewSecurityIndustry] = useState('')
  const [accepted, setAccepted] = useState<JobAccepted | null>(null)
  const securities = useQuery({ queryKey: ['securities'], queryFn: listSecurities })
  const qc = useQueryClient()
  const mutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('请选择 PDF、DOCX 或 TXT 文件。')
      let securityId = securityChoice
      if (securityChoice === '__new__') {
        if (!newSecurityId.trim() || !newSecurityName.trim()) throw new Error('新证券的代码和名称必填。')
        const created = await createSecurity({ securityId: newSecurityId, name: newSecurityName, industry: newSecurityIndustry })
        securityId = created.securityId
        await qc.invalidateQueries({ queryKey: ['securities'] })
      }
      return uploadDocument({ file, publishedAt, thesisId: initialThesisId, securityId: securityId || undefined })
    },
    onSuccess: setAccepted,
  })
  const job = useQuery({
    queryKey: ['document-job', accepted?.jobId],
    queryFn: () => getJob(accepted!.jobId),
    enabled: Boolean(accepted),
    refetchInterval: (query) => ['complete', 'not_found'].includes(query.state.data?.status ?? '') ? false : 1000,
  })
  useEffect(() => {
    if (job.data?.status !== 'complete' || !job.data.success) return
    void Promise.all([
      qc.invalidateQueries({ queryKey: ['theses'] }),
      initialThesisId ? qc.invalidateQueries({ queryKey: ['thesis', initialThesisId] }) : Promise.resolve(),
      initialThesisId ? qc.invalidateQueries({ queryKey: ['company-thesis-trends', initialThesisId] }) : Promise.resolve(),
      initialThesisId ? qc.invalidateQueries({ queryKey: ['company-thesis-evidence', initialThesisId] }) : Promise.resolve(),
      refreshSecurityId ? qc.invalidateQueries({ queryKey: ['company-metric-center', refreshSecurityId] }) : Promise.resolve(),
    ])
  }, [initialThesisId, job.data?.status, job.data?.success, qc, refreshSecurityId])
  const result = job.data?.result
  const progressLabel = uploadStageLabels[String(result?.stage ?? '')] ?? '后台处理中…'
  const reanalyze = useMutation({ mutationFn: () => reanalyzeProcessingJob(accepted!.jobId), onSuccess: setAccepted })
  return <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}><section className="dialog upload-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><span className="eyebrow">变化处理链</span><h2>上传研究资料</h2><p>选择证券后，系统会执行“事件抽取 → 已发布投资逻辑召回 → 候选证据 → 变化雷达”。候选结果仍需人工确认。</p>{!accepted ? <form className="form-grid" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><label>文件<input type="file" accept=".pdf,.docx,.txt" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required /></label><label>首次公开时间<input type="datetime-local" value={publishedAt} onChange={(event) => setPublishedAt(event.target.value)} required /></label><label>归属证券<select value={securityChoice} onChange={(event) => setSecurityChoice(event.target.value)}><option value="">仅入知识库（不进入雷达）</option>{securities.data?.map((item) => <option key={item.securityId} value={item.securityId}>{item.securityId} · {item.name}</option>)}<option value="__new__">＋ 新建证券档案</option></select></label>{securityChoice === '__new__' && <div className="form-grid two nested-fields"><label>证券代码<input value={newSecurityId} onChange={(event) => setNewSecurityId(event.target.value)} required /></label><label>证券名称<input value={newSecurityName} onChange={(event) => setNewSecurityName(event.target.value)} required /></label><label>所属行业<input value={newSecurityIndustry} onChange={(event) => setNewSecurityIndustry(event.target.value)} /></label></div>}<div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>取消</button><button type="submit" className="button primary" disabled={mutation.isPending}>{mutation.isPending ? '上传中…' : '上传并处理'}</button></div><InlineError error={mutation.error ?? securities.error} /></form> : <div className="job-progress"><span className={`job-state ${job.data?.success === false ? 'failed' : ''}`}>{job.data?.status === 'complete' ? (job.data.success ? '处理完成' : '处理失败') : progressLabel}</span><dl><dt>文档 ID</dt><dd>{accepted.documentId}</dd>{result && <><dt>段落</dt><dd>{String(result.segment_count ?? 0)}</dd><dt>正文事实</dt><dd>{String(result.fact_count ?? 0)}</dd><dt>事件</dt><dd>{String(result.event_count ?? 0)}</dd><dt>召回逻辑</dt><dd>{String(result.matched_thesis_count ?? 0)}</dd><dt>检索模式</dt><dd>{result.retrieval_mode === 'text+graph' ? '文本＋关系图' : result.retrieval_mode === 'graph' ? '关系图' : result.retrieval_mode === 'text' ? '文本' : '基础规则'}</dd><dt>候选证据</dt><dd>{String(result.candidate_evidence_count ?? 0)}</dd><dt>待人工判断</dt><dd>{String(result.deferred_event_count ?? 0)}</dd><dt>重复文档</dt><dd>{result.duplicate ? '是，已复用既有记录' : '否'}</dd></>}</dl>{job.data?.success === false && <p className="inline-error">{String(result?.reason ?? result?.message ?? '处理失败，请检查任务详情。')}</p>}<div className="dialog-actions">{job.data?.success === false && Boolean(result?.parsed) && <button className="button secondary" disabled={reanalyze.isPending} onClick={() => reanalyze.mutate()}>{reanalyze.isPending ? '正在重新入队…' : '重新分析（不解析文件）'}</button>}{job.data?.success === false && !result?.parsed && <button className="button secondary" onClick={() => { setAccepted(null); mutation.reset() }}>重新提交文件</button>}<button className="button primary" onClick={onClose} disabled={!job.data || (job.data.status !== 'complete' && job.data.status !== 'not_found')}>完成</button></div></div>}</section></div>
}

type DraftMetricConfig = {
  key: string
  metricId: string
  metricVersion: string
  selected: boolean
  expanded: boolean
  expectedDirection: string
  lowerBound: string
  upperBound: string
  consecutivePeriods: string
  expectationSource: string
  suggestion: Record<string, unknown>
}

const directionOptions = [
  { value: '上升', label: '上升' },
  { value: '下降', label: '下降' },
  { value: '波动', label: '波动' },
]

function normalizedDirection(value: string) {
  if (['越低越好', '不高于阈值', '下降'].includes(value)) return '下降'
  if (value === '波动') return '波动'
  return '上升'
}

function suggestionText(item: Record<string, unknown>, key: string, fallback = '') {
  const value = item[key] ?? item[key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`)]
  return value == null ? fallback : String(value)
}

function buildDraftMetricConfigs(thesis: ThesisDetail): Record<string, DraftMetricConfig[]> {
  return Object.fromEntries(thesis.hypotheses.map((hypothesis) => [hypothesis.hypothesisId, hypothesis.metricSuggestions.map((item, index) => {
    const metricId = suggestionText(item, 'metric_id') || suggestionText(item, 'metricId')
    const threshold = (item.threshold_suggestion ?? {}) as Record<string, unknown>
    return {
      key: `${hypothesis.hypothesisId}:${metricId || 'candidate'}:${index}`,
      metricId,
      metricVersion: suggestionText(item, 'metric_version', 'v1.0'),
      selected: false,
      expanded: false,
      expectedDirection: normalizedDirection(suggestionText(item, 'expected_direction')),
      lowerBound: ['越低越好', '不高于阈值', '下降'].includes(suggestionText(item, 'expected_direction')) ? '' : threshold.value == null ? '' : String(threshold.value),
      upperBound: ['越低越好', '不高于阈值', '下降'].includes(suggestionText(item, 'expected_direction')) ? threshold.value == null ? '' : String(threshold.value) : '',
      consecutivePeriods: '1',
      expectationSource: 'AI候选（待研究员确认）',
      suggestion: item,
    }
  })]))
}

function CreateDraftDialogV2({ theses, initialSecurity, onClose }: { theses: ThesisSummary[]; initialSecurity?: Security; onClose: () => void }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const securities = useQuery({ queryKey: ['securities'], queryFn: listSecurities })
  const [step, setStep] = useState<1 | 2>(1)
  const [securityIdInput, setSecurityIdInput] = useState('')
  const [securityNameInput, setSecurityNameInput] = useState('')
  const [industryInput, setIndustryInput] = useState('')
  const [view, setView] = useState('')
  const [useRag, setUseRag] = useState(true)
  const [generated, setGenerated] = useState<ThesisDetail | null>(null)
  const [draftTitle, setDraftTitle] = useState('')
  const [draftCoreView, setDraftCoreView] = useState('')
  const [hypothesisStatements, setHypothesisStatements] = useState<Record<string, string>>({})
  const [metricConfigs, setMetricConfigs] = useState<Record<string, DraftMetricConfig[]>>({})
  const [metricRefreshNotice, setMetricRefreshNotice] = useState<{ fetched: number; inserted: number; errors: string[] } | null>(null)
  const [lookupSource, setLookupSource] = useState<'code' | 'name'>('code')
  const companyMetrics = useQuery({ queryKey: ['company-metric-center', generated?.securityId], queryFn: () => getCompanyMetricCenter(generated!.securityId), enabled: Boolean(generated) })
  // 只用当前正在输入的字段查询，避免已经回填的旧值抢走查询条件。
  const lookupTerm = lookupSource === 'code' ? securityIdInput.trim() : securityNameInput.trim()
  const marketLookup = useQuery({ queryKey: ['security-resolve', lookupTerm], queryFn: () => lookupSecurities(lookupTerm), enabled: lookupTerm.length >= 2, staleTime: 5 * 60_000 })
  const securityPool = [...(securities.data ?? []), ...(marketLookup.data ?? []).filter((item) => !(securities.data ?? []).some((local) => local.securityId === item.securityId))]
  const matchedSecurity = securityPool.find((item) => {
    const code = securityIdInput.trim().toLowerCase()
    const name = securityNameInput.trim().toLowerCase()
    const aliases = ((item as Security & { aliases?: string[] }).aliases ?? []).map((alias) => alias.toLowerCase())
    return lookupSource === 'code'
      ? Boolean(code && [item.securityId, item.ticker].filter(Boolean).some((value) => String(value).toLowerCase() === code))
      : Boolean(name && [item.name.toLowerCase(), ...aliases].includes(name))
  })
  const selectedSecurityId = matchedSecurity?.securityId ?? (lookupSource === 'code' ? securityIdInput.trim() : '')
  const existing = theses.find((item) => item.securityId === selectedSecurityId)
  const securityMatches = securityPool.filter((item) => {
    const query = lookupTerm.toLowerCase()
    return !query || `${item.securityId} ${item.ticker ?? ''} ${item.name}`.toLowerCase().includes(query)
  }).slice(0, 5)
  const applySecurity = (item: Security) => {
    setSecurityIdInput(item.securityId)
    setSecurityNameInput(item.name)
    setIndustryInput(item.industry ?? '')
  }
  useEffect(() => {
    if (initialSecurity) applySecurity(initialSecurity)
  }, [initialSecurity])
  useEffect(() => {
    const normalizedCode = securityIdInput.trim().toLowerCase()
    const normalizedName = securityNameInput.trim().toLowerCase()
    const exact = (marketLookup.data ?? []).find((item) => lookupSource === 'code'
      ? item.securityId.toLowerCase() === normalizedCode || item.ticker?.toLowerCase() === normalizedCode
      : item.name.toLowerCase() === normalizedName)
    if (exact && (securityIdInput !== exact.securityId || securityNameInput !== exact.name || industryInput !== (exact.industry ?? ''))) applySecurity(exact)
  }, [marketLookup.data, lookupSource, securityIdInput, securityNameInput, industryInput])
  const handleSecurityIdChange = (value: string) => {
    setLookupSource('code')
    setSecurityIdInput(value)
    if (value.trim() && securityNameInput.trim()) {
      setSecurityNameInput('')
      setIndustryInput('')
    }
    const normalized = value.trim().toLowerCase()
    const item = securityPool.find((candidate) => [candidate.securityId, candidate.ticker].filter(Boolean).some((code) => String(code).toLowerCase() === normalized))
    if (item) applySecurity(item)
  }
  const handleSecurityNameChange = (value: string) => {
    setLookupSource('name')
    setSecurityNameInput(value)
    if (value.trim() && securityIdInput.trim()) {
      setSecurityIdInput('')
      setIndustryInput('')
    }
    const normalized = value.trim().toLowerCase()
    const item = securityPool.find((candidate) => candidate.name.toLowerCase() === normalized)
    if (item) applySecurity(item)
  }
  const draftMutation = useMutation({
    mutationFn: async () => {
      let resolvedSecurity = matchedSecurity
      // 提交时再确认一次，避免用户在查询请求返回前点击按钮导致状态尚未回填。
      if (!resolvedSecurity && lookupTerm.length >= 2) {
        const candidates = await lookupSecurities(lookupTerm)
        const normalized = lookupTerm.toLowerCase()
        resolvedSecurity = candidates.find((item) => lookupSource === 'code'
          ? [item.securityId, item.ticker].filter(Boolean).some((value) => String(value).toLowerCase() === normalized)
          : item.name.toLowerCase() === normalized)
      }
      let securityId = resolvedSecurity?.securityId ?? securityIdInput.trim()
      const securityName = resolvedSecurity?.name ?? securityNameInput.trim()
      // 未匹配到完整证券信息时保持安静，让研究员继续编辑输入内容。
      if (!securityId || !securityName) return null
      const localSecurity = (securities.data ?? []).find((item) => item.securityId === securityId)
      if (!localSecurity) {
        const created = await createSecurity({ securityId, name: securityName, ticker: resolvedSecurity?.ticker, industry: resolvedSecurity?.industry ?? industryInput.trim() })
        securityId = created.securityId
        await qc.invalidateQueries({ queryKey: ['securities'] })
      }
      const existingForSecurity = theses.find((item) => item.securityId === securityId)
      if (existingForSecurity) return { thesis: existingForSecurity, reusedExisting: true }
      // 指标刷新是创建逻辑前的独立步骤；即使某个公开数据源暂时失败，
      // 也继续生成草稿，并把真实结果带到下一步，避免错误被静默吞掉。
      let metricRefresh: { fetched: number; inserted: number; errors: string[] }
      try {
        metricRefresh = await refreshCompanyMetrics(securityId)
      } catch (error) {
        metricRefresh = {
          fetched: 0,
          inserted: 0,
          errors: [error instanceof Error ? error.message : '指标刷新请求失败。'],
        }
      }
      return { thesis: await createDraft({ securityId, view: view.trim(), useRag }), reusedExisting: false, metricRefresh }
    },
    onSuccess: async (result) => {
      if (!result) return
      const { thesis, reusedExisting, metricRefresh } = result
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['theses'] }),
        qc.invalidateQueries({ queryKey: ['thesis-summaries'] }),
      ])
      // 只有用户选择了已有逻辑时才打开维护页；新生成的草稿始终留在当前弹窗，
      // 进入第 2 步完成 AI 指标推荐与人工确认。不能用刷新后的 theses 列表判断，
      // 否则新草稿落库后可能被误判成“已有逻辑”而跳回旧页面。
      if (reusedExisting) {
        onClose()
        navigate(`/theses/${thesis.thesisId}`)
        return
      }
      const generatedThesis = thesis as ThesisDetail
      setGenerated(generatedThesis)
      setDraftTitle(generatedThesis.title)
      setDraftCoreView(generatedThesis.coreView)
      setHypothesisStatements(Object.fromEntries(generatedThesis.hypotheses.map((item) => [item.hypothesisId, item.statement])))
      setMetricConfigs(buildDraftMetricConfigs(generatedThesis))
      setMetricRefreshNotice(metricRefresh ?? null)
      setStep(2)
    },
  })
  const updateConfig = (hypothesisId: string, key: string, patch: Partial<DraftMetricConfig>) => setMetricConfigs((current) => ({ ...current, [hypothesisId]: (current[hypothesisId] ?? []).map((item) => item.key === key ? { ...item, ...patch } : item) }))
  const addCenterMetric = (hypothesisId: string, metric: CompanyMetric) => setMetricConfigs((current) => {
    const rows = current[hypothesisId] ?? []
    if (rows.some((item) => item.metricId === metric.metricId)) return current
    const suggestion = { metric_id: metric.metricId, metric_name: metric.name, unit: metric.unit, frequency: metric.frequency, rationale: metric.definition, relation_type: '指标中心', observations: metric.observations }
    return { ...current, [hypothesisId]: [...rows, { key: `${hypothesisId}:${metric.metricId}:center`, metricId: metric.metricId, metricVersion: 'v1.0', selected: true, expanded: true, expectedDirection: '上升', lowerBound: '', upperBound: '', consecutivePeriods: '1', expectationSource: '指标中心人工选择', suggestion }] }
  })
  const selectedRows = Object.entries(metricConfigs).flatMap(([hypothesisId, rows]) => rows.filter((row) => row.selected).map((row) => ({ hypothesisId, row })))
  const mappingMutation = useMutation({
    mutationFn: async () => {
      if (!generated) throw new Error('逻辑草稿尚未生成。')
      if (!draftTitle.trim() || !draftCoreView.trim()) throw new Error('投资逻辑标题和核心观点不能为空。')
      if (!selectedRows.length) return
      for (const selection of selectedRows) {
        if (!selection.row.metricId) throw new Error('有候选缺少指标 ID，请取消选择后再提交。')
        if (!selection.row.lowerBound.trim() && !selection.row.upperBound.trim()) throw new Error(`${selection.row.metricId} 的上限和下限至少填写一项。`)
        if (selection.row.expectedDirection === '上升' && !selection.row.lowerBound.trim()) throw new Error(`${selection.row.metricId} 选择上升时需要填写下限。`)
        if (selection.row.expectedDirection === '下降' && !selection.row.upperBound.trim()) throw new Error(`${selection.row.metricId} 选择下降时需要填写上限。`)
      }
      await updateThesisDraft(generated.thesisId, { title: draftTitle.trim(), coreView: draftCoreView.trim() })
      for (const hypothesis of generated.hypotheses) {
        const statement = (hypothesisStatements[hypothesis.hypothesisId] ?? '').trim()
        if (!statement) throw new Error('假设内容不能为空。')
        if (statement !== hypothesis.statement) await updateHypothesis(generated.thesisId, hypothesis.hypothesisId, { statement, hypothesisType: hypothesis.hypothesisType, importance: hypothesis.importance, observationWindow: hypothesis.observationWindow, invalidationRule: hypothesis.invalidationRule })
      }
      for (const { hypothesisId, row } of selectedRows) {
        await saveMetricMapping(generated.thesisId, hypothesisId, {
          metricId: row.metricId,
          metricVersion: row.metricVersion,
          expectedDirection: row.expectedDirection,
          expectedLower: row.lowerBound,
          expectedUpper: row.upperBound,
          invalidationConsecutivePeriods: Number(row.consecutivePeriods) || 1,
          expectationSource: row.expectationSource.trim() || '研究员人工确认',
        })
      }
    },
    onSuccess: async () => {
      await Promise.all([qc.invalidateQueries({ queryKey: ['theses'] }), qc.invalidateQueries({ queryKey: ['thesis', generated?.thesisId] })])
      // 人工确认完成后进入公司看台，直接查看刚刚保存的投资逻辑和指标配置。
      if (generated) navigate(`/companies/${encodeURIComponent(generated.securityId)}`)
      onClose()
    },
  })
  return <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}><section className="dialog create-dialog draft-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
    <div className="draft-stepper" aria-label="研究主题建立进度"><span className={step === 1 ? 'active' : 'done'}>01 建立逻辑草稿</span><i>→</i><span className={step === 2 ? 'active' : ''}>02 AI 推荐指标 · 人工确认</span></div>
    {step === 1 && <><span className="eyebrow">公司级研究主线</span><h2>新建研究主题</h2><p>输入股票代码或名称，系统会从证券主数据补全名称和行业；随后使用 Graph RAG 与研究问题生成投资逻辑和可证伪假设草稿。</p><form className="form-grid" onSubmit={(event: FormEvent) => { event.preventDefault(); draftMutation.mutate() }}>
      <div className="security-input-grid"><label>股票代码<input value={securityIdInput} onChange={(event) => handleSecurityIdChange(event.target.value)} placeholder="例如 002594" /></label><label>股票名称<input value={securityNameInput} onChange={(event) => handleSecurityNameChange(event.target.value)} placeholder="例如 比亚迪" /></label></div>
      {securityMatches.length > 0 && <div className="security-match-list" aria-label="证券主数据匹配结果">{securityMatches.map((item) => <button type="button" key={item.securityId} onClick={() => applySecurity(item)}><strong>{item.name}</strong><span>{item.securityId}{item.industry ? ` · ${item.industry}` : ''}</span></button>)}</div>}
      <label>所属行业板块<input value={industryInput} onChange={(event) => setIndustryInput(event.target.value)} placeholder="匹配后自动填写；新公司可人工补充" readOnly={Boolean(matchedSecurity)} /></label>
      {matchedSecurity && <div className="security-match-note">已匹配证券主数据：{matchedSecurity.name} · {matchedSecurity.securityId}{matchedSecurity.industry ? ` · ${matchedSecurity.industry}` : ''}</div>}
      {existing ? <div className="success-note"><strong>{existing.title}</strong><br />该公司已有投资逻辑，将直接打开维护页，不会重复建立。</div> : <><label>研究问题（建议填写）<textarea value={view} onChange={(event) => setView(event.target.value)} placeholder="例如：海外新能源需求增长能否支撑未来两年出口与盈利改善？" /></label><label className="checkbox-field"><input type="checkbox" checked={useRag} onChange={(event) => setUseRag(event.target.checked)} /> 使用权限过滤后的 Graph RAG 历史资料生成草稿</label></>}
      <div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>取消</button><button type="submit" className="button primary" disabled={draftMutation.isPending || securities.isLoading}>{draftMutation.isPending ? 'AI 生成中…' : existing ? '打开现有逻辑' : '生成逻辑草稿'}</button></div><InlineError error={draftMutation.error ?? securities.error} />
    </form></>}
    {step === 2 && generated && <>
      <span className="eyebrow">AI 指标推荐 · 研究员确认</span><h2>调整逻辑并确认跟踪指标</h2>
      <p>AI 结果只是草稿。请先调整投资逻辑和假设，再为每条假设加入一个或多个跟踪指标；未加入的候选不会写入维护数据。</p>
      {metricRefreshNotice && <div className={`metric-refresh-notice ${metricRefreshNotice.errors.length ? 'warning' : 'success'}`} role="status" aria-live="polite"><strong>{metricRefreshNotice.errors.length && metricRefreshNotice.fetched === 0 ? '指标数据刷新失败' : metricRefreshNotice.errors.length ? '主要指标已刷新，部分数据源暂不可用' : '指标数据已刷新'}</strong><span>公开数据源本次获取 {metricRefreshNotice.fetched} 条，新增入库 {metricRefreshNotice.inserted} 条。</span>{metricRefreshNotice.errors.length > 0 && <ul>{metricRefreshNotice.errors.map((error, index) => <li key={`${error}-${index}`}>{error}</li>)}</ul>}<small>指标刷新结果仅影响可用的候选数据，不影响本次逻辑草稿生成；可在公司界面的指标中心再次更新。</small></div>}
      <div className="draft-edit-panel">
        <label>投资逻辑标题<input value={draftTitle} maxLength={40} onChange={(event) => setDraftTitle(event.target.value)} /></label>
        <label>核心观点<textarea value={draftCoreView} maxLength={200} onChange={(event) => setDraftCoreView(event.target.value)} /></label>
      </div>
      <div className="metric-review-list">{generated.hypotheses.map((hypothesis) => <article className="metric-review-card" key={hypothesis.hypothesisId}>
        <header><div className="hypothesis-heading"><span className="hypothesis-id">{hypothesis.hypothesisId}</span><span className="badge neutral-badge">{hypothesis.logicDimension || hypothesis.causalLevel || hypothesis.hypothesisType || '研究维度'}</span></div><label>投资假设<textarea value={hypothesisStatements[hypothesis.hypothesisId] ?? ''} onChange={(event) => setHypothesisStatements((current) => ({ ...current, [hypothesis.hypothesisId]: event.target.value }))} /></label><label>从指标中心添加<select value="" onChange={(event) => { const metric = companyMetrics.data?.metrics.find((item) => item.metricId === event.target.value); if (metric) addCenterMetric(hypothesis.hypothesisId, metric) }}><option value="">选择已获取指标</option>{companyMetrics.data?.metrics.map((metric) => <option value={metric.metricId} key={metric.metricId}>{metric.name} · {metric.category}</option>)}</select></label></header>
        {(metricConfigs[hypothesis.hypothesisId] ?? []).length === 0 ? <p className="metric-empty">AI 暂未找到候选指标，可在维护页继续配置。</p> : <div className="metric-candidate-list">{(metricConfigs[hypothesis.hypothesisId] ?? []).map((config) => {
          const item = config.suggestion
          const metricName = suggestionText(item, 'metric_name') || suggestionText(item, 'name', config.metricId || '未命名指标')
          const unit = suggestionText(item, 'unit', '未标注')
          const rationale = suggestionText(item, 'rationale') || suggestionText(item, 'reason', 'AI 尚未提供说明')
          const frequency = suggestionText(item, 'observation_frequency') || suggestionText(item, 'frequency', '频率待确认')
          const availability = suggestionText(item, 'availability_grade')
          const observations = Array.isArray(item.observations) ? item.observations as Array<Record<string, unknown>> : []
          return <MetricEditorCard key={config.key} selected={config.selected} name={metricName} metricId={config.metricId} meta={`${unit} · ${frequency}${availability ? ` · 可用性 ${availability}` : ''}`} tag={suggestionText(item, 'relation_type', 'AI 候选')} description={rationale} observations={observations} unit={unit} expanded={config.expanded} disabled={!config.metricId} onToggleSelected={() => updateConfig(hypothesis.hypothesisId, config.key, { selected: !config.selected, expanded: !config.selected ? true : false })} onToggleExpanded={() => updateConfig(hypothesis.hypothesisId, config.key, { expanded: !config.expanded })}>
            <div className="metric-config-grid"><label>变化方向<select value={config.expectedDirection} onChange={(event) => updateConfig(hypothesis.hypothesisId, config.key, { expectedDirection: event.target.value })}>{directionOptions.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</select></label><label>下限（可选）<input value={config.lowerBound} onChange={(event) => updateConfig(hypothesis.hypothesisId, config.key, { lowerBound: event.target.value })} placeholder={config.expectedDirection === '上升' ? '上升方向必填' : '允许区间下界'} /></label><label>上限（可选）<input value={config.upperBound} onChange={(event) => updateConfig(hypothesis.hypothesisId, config.key, { upperBound: event.target.value })} placeholder={config.expectedDirection === '下降' ? '下降方向必填' : '允许区间上界'} /></label><label>连续触发期数<input type="number" min="1" max="12" value={config.consecutivePeriods} onChange={(event) => updateConfig(hypothesis.hypothesisId, config.key, { consecutivePeriods: event.target.value })} /></label><label className="metric-source-field">判断依据<input value={config.expectationSource} onChange={(event) => updateConfig(hypothesis.hypothesisId, config.key, { expectationSource: event.target.value })} /></label><p className="metric-rule-help">上升：指标应保持在［下限，+∞）内；下降：应保持在（-∞，上限］内；波动：按已填写的上下界判断。连续越界后仅生成复核提醒，不自动判定假设失效。</p></div>
          </MetricEditorCard>
        })}</div>}
      </article>)}</div>
      <div className="dialog-actions"><button type="button" className="button secondary" onClick={() => setStep(1)} disabled={mappingMutation.isPending}>返回上一步</button><button type="button" className="button primary" onClick={() => mappingMutation.mutate()} disabled={mappingMutation.isPending}>{mappingMutation.isPending ? '正在保存确认…' : selectedRows.length ? `确认并进入维护（${selectedRows.length} 个指标）` : '保存逻辑，暂不关联指标'}</button></div><InlineError error={mappingMutation.error ?? companyMetrics.error} />
    </>}
  </section></div>
}
