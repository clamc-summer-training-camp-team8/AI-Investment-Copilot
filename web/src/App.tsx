import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { createDraft, createSecurity, getJob, listSecurities, listTheses, uploadDocument, useMock } from './api'
import { Icon, InlineError, ResearchContextPicker } from './components'
import type { JobAccepted, ThesisDetail } from './types'
import { AssetPage, CompanyResearchPage, CoverageManagementPage, EvidencePage, MacroStrategyPage, RadarPage, ResearchImpactDetailPage, ResearchUpdatesPage, RetrospectiveCenterPage, ThesisListPage, ThesisPage, WorkbenchPage } from './pages'

function localDateTimeValue(date = new Date()) {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

export function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const [showCreate, setShowCreate] = useState(false)
  const [showUpload, setShowUpload] = useState(false)
  const theses = useQuery({ queryKey: ['theses'], queryFn: () => listTheses() })
  const routeThesis = location.pathname.match(/^\/theses\/([^/]+)/)?.[1]
  const queryThesis = new URLSearchParams(location.search).get('thesisId') ?? undefined
  const currentThesisId = routeThesis ?? queryThesis
  const radarPath = currentThesisId ? `/radar?thesisId=${encodeURIComponent(currentThesisId)}` : '/radar'
  const navigation = [
    ['工作台', '/workbench', '01', 'grid'],
    ['变化雷达', radarPath, '02', 'radar'],
    ['投资逻辑', '/theses', '03', 'graph'],
    ['复核与复盘', '/reviews', '04', 'check'],
    ['资产治理', '/assets', '05', 'archive'],
  ] as const
  const isNavigationActive = (label: string, path: string) => location.pathname === path || (label === '变化雷达' && location.pathname.startsWith('/radar')) || (label === '投资逻辑' && location.pathname.startsWith('/theses'))
  const activeIndex = navigation.findIndex(([label, path]) => isNavigationActive(label, path))
  const isWorkbench = location.pathname === '/workbench'
  const isCompanyResearch = location.pathname.startsWith('/companies/')
  const isCoverageManagement = location.pathname === '/coverage'
  const isMacroStrategy = location.pathname === '/macro-strategy'
  const isResearchUpdates = location.pathname.startsWith('/updates')
  const isRetrospective = location.pathname === '/reviews'
  return <div className={`app-shell ${isWorkbench ? 'workbench-shell' : ''} ${isCompanyResearch ? 'company-shell' : ''} ${isCoverageManagement ? 'coverage-shell' : ''} ${isMacroStrategy ? 'macro-shell' : ''} ${isResearchUpdates ? 'updates-shell' : ''} ${isRetrospective ? 'retrospective-shell' : ''}`}>
    <a className="skip-link" href="#main-content">跳到主要内容</a>
    <header className="global-topbar dashboard-topbar">
      <NavLink to="/workbench" className="brand dashboard-brand" aria-label="返回工作台"><span className="brand-mark"><Icon name="graph" size={20} /></span><span className="brand-copy"><strong>投研引擎工作台</strong><small>AI INVESTMENT COPILOT</small></span></NavLink>
      <label className="global-search"><span aria-hidden>⌕</span><input aria-label="全局搜索" placeholder="搜索公司、行业、事件或输入投研问题" /></label>
      <nav className="dashboard-nav" aria-label="顶部主导航"><NavLink to="/workbench">工作台</NavLink><NavLink to="/reviews">复盘中心</NavLink><NavLink to="/assets">研报库</NavLink><NavLink to="/assets">数据中心</NavLink><NavLink to="/theses">模型与因子</NavLink></nav>
      <div className="dashboard-utilities"><button aria-label="收藏">☆</button><button aria-label="消息">♧<b>8</b></button><span className="dashboard-avatar">研</span><span>研究员张明</span></div>
    </header>
    <aside className="sidebar" aria-label="产品主导航"><div className="rail-heading"><span className="mono">0{Math.max(0, activeIndex) + 1}</span><small>RESEARCH DESK</small></div><nav>{navigation.map(([label, path, index, icon]) => <NavLink key={label} to={path} aria-label={label} className={() => isNavigationActive(label, path) ? 'active' : ''}><Icon name={icon} size={18} /><span className="nav-copy"><b>{label}</b><small className="mono">{index}</small></span></NavLink>)}</nav><div className="sidebar-footer"><span><i className="live-dot" />{useMock ? '受控 Mock 数据' : '真实公开数据'}</span><small>研究辅助 · 人工决策</small></div></aside>
    <div className="workspace"><header className="workspace-bar"><ResearchContextPicker theses={theses.data ?? []} value={currentThesisId} onChange={(id) => id ? navigate(`/radar?thesisId=${encodeURIComponent(id)}`) : navigate('/workbench')} /><div className="top-actions"><button className="button secondary" onClick={() => setShowUpload(true)}><Icon name="upload" size={15} />上传研究资料</button><button className="button primary" onClick={() => setShowCreate(true)}><span aria-hidden>＋</span>新建投资逻辑</button></div></header><main className="main-content" id="main-content" tabIndex={-1}><Routes><Route path="/workbench" element={<WorkbenchPage />} /><Route path="/coverage" element={<CoverageManagementPage />} /><Route path="/macro-strategy" element={<MacroStrategyPage />} /><Route path="/updates" element={<ResearchUpdatesPage />} /><Route path="/updates/:updateId" element={<ResearchImpactDetailPage />} /><Route path="/companies/geely" element={<CompanyResearchPage />} /><Route path="/radar" element={<RadarPage />} /><Route path="/radar/:evidenceId" element={<EvidencePage />} /><Route path="/theses" element={<ThesisListPage />} /><Route path="/theses/:thesisId" element={<ThesisPage />} /><Route path="/reviews" element={<RetrospectiveCenterPage />} /><Route path="/assets" element={<AssetPage />} /><Route path="*" element={<Navigate to="/workbench" replace />} /></Routes></main></div>
    <nav className="mobile-nav" aria-label="移动端主导航">{navigation.map(([label, path, , icon]) => <NavLink key={label} to={path} aria-label={label} className={() => isNavigationActive(label, path) ? 'active' : ''}><Icon name={icon} size={18} /><span>{label}</span></NavLink>)}</nav>
    <footer className="disclaimer">AI 生成内容仅作为研究候选 · 所有证据、关系与状态变更均需人工确认<span className="mono">AUDITABLE / TRACEABLE / HUMAN-GATED</span></footer>
    {showCreate && <CreateDraftDialog onClose={() => setShowCreate(false)} />}
    {showUpload && <UploadDocumentDialog theses={theses.data ?? []} initialThesisId={currentThesisId} onClose={() => setShowUpload(false)} />}
  </div>
}

function UploadDocumentDialog({ theses, initialThesisId, onClose }: { theses: ThesisDetail[]; initialThesisId?: string; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [publishedAt, setPublishedAt] = useState(() => localDateTimeValue())
  const initialSecurityId = theses.find((item) => item.thesisId === initialThesisId)?.securityId ?? ''
  const [securityChoice, setSecurityChoice] = useState(initialSecurityId)
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
      return uploadDocument({ file, publishedAt, securityId: securityId || undefined })
    },
    onSuccess: setAccepted,
  })
  const job = useQuery({
    queryKey: ['document-job', accepted?.jobId],
    queryFn: () => getJob(accepted!.jobId),
    enabled: Boolean(accepted),
    refetchInterval: (query) => ['complete', 'not_found'].includes(query.state.data?.status ?? '') ? false : 1000,
  })
  const result = job.data?.result
  return <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}><section className="dialog upload-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><span className="eyebrow">变化处理链</span><h2>上传研究资料</h2><p>选择证券后，系统会执行“事件抽取 → 已发布投资逻辑召回 → 候选证据 → 变化雷达”。候选结果仍需人工确认。</p>{!accepted ? <form className="form-grid" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><label>文件<input type="file" accept=".pdf,.docx,.txt" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required /></label><label>首次公开时间<input type="datetime-local" value={publishedAt} onChange={(event) => setPublishedAt(event.target.value)} required /></label><label>归属证券<select value={securityChoice} onChange={(event) => setSecurityChoice(event.target.value)}><option value="">仅入知识库（不进入雷达）</option>{securities.data?.map((item) => <option key={item.securityId} value={item.securityId}>{item.securityId} · {item.name}</option>)}<option value="__new__">＋ 新建证券档案</option></select></label>{securityChoice === '__new__' && <div className="form-grid two nested-fields"><label>证券代码<input value={newSecurityId} onChange={(event) => setNewSecurityId(event.target.value)} required /></label><label>证券名称<input value={newSecurityName} onChange={(event) => setNewSecurityName(event.target.value)} required /></label><label>所属行业<input value={newSecurityIndustry} onChange={(event) => setNewSecurityIndustry(event.target.value)} /></label></div>}<div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>取消</button><button type="submit" className="button primary" disabled={mutation.isPending}>{mutation.isPending ? '上传中…' : '上传并处理'}</button></div><InlineError error={mutation.error ?? securities.error} /></form> : <div className="job-progress"><span className={`job-state ${job.data?.success === false ? 'failed' : ''}`}>{job.data?.status === 'complete' ? (job.data.success ? '处理完成' : '处理失败') : '后台处理中…'}</span><dl><dt>文档 ID</dt><dd>{accepted.documentId}</dd>{result && <><dt>段落</dt><dd>{String(result.segment_count ?? 0)}</dd><dt>正文事实</dt><dd>{String(result.fact_count ?? 0)}</dd><dt>事件</dt><dd>{String(result.event_count ?? 0)}</dd><dt>召回逻辑</dt><dd>{String(result.matched_thesis_count ?? 0)}</dd><dt>候选证据</dt><dd>{String(result.candidate_evidence_count ?? 0)}</dd><dt>待人工判断</dt><dd>{String(result.deferred_event_count ?? 0)}</dd><dt>重复文档</dt><dd>{result.duplicate ? '是，已复用既有记录' : '否'}</dd></>}</dl>{job.data?.success === false && <p className="inline-error">{String(result?.reason ?? result?.message ?? '处理失败，请检查任务详情。')}</p>}<div className="dialog-actions">{job.data?.success === false && <button className="button secondary" onClick={() => { setAccepted(null); mutation.reset() }}>重新提交</button>}<button className="button primary" onClick={onClose} disabled={!job.data || (job.data.status !== 'complete' && job.data.status !== 'not_found')}>完成</button></div></div>}</section></div>
}

function CreateDraftDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const securities = useQuery({ queryKey: ['securities'], queryFn: listSecurities })
  const [securityChoice, setSecurityChoice] = useState('')
  const [newSecurityId, setNewSecurityId] = useState('')
  const [newSecurityName, setNewSecurityName] = useState('')
  const [newSecurityIndustry, setNewSecurityIndustry] = useState('')
  const [view, setView] = useState('')
  const [useRag, setUseRag] = useState(false)
  const mutation = useMutation({ mutationFn: async () => { let securityId = securityChoice; if (securityChoice === '__new__') { if (!newSecurityId.trim() || !newSecurityName.trim()) throw new Error('新证券的代码和名称必填。'); const created = await createSecurity({ securityId: newSecurityId, name: newSecurityName, industry: newSecurityIndustry }); securityId = created.securityId; await qc.invalidateQueries({ queryKey: ['securities'] }) } if (!securityId) throw new Error('请选择或新建证券。'); return createDraft({ securityId, view, useRag }) }, onSuccess: async (thesis) => { await qc.invalidateQueries({ queryKey: ['theses'] }); onClose(); navigate(`/theses/${thesis.thesisId}`) } })
  return <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}><section className="dialog create-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><span className="eyebrow">AI 候选草稿</span><h2>新建投资逻辑</h2><p>模型会根据你的观点生成 2–5 条新的可证伪假设候选。可选的 RAG 试点只召回当前账户有权查看的同证券历史切片；引用仍是候选，发布前必须人工确认。</p><form className="form-grid" onSubmit={(event: FormEvent) => { event.preventDefault(); mutation.mutate() }}><label>投资对象<select value={securityChoice} onChange={(event) => setSecurityChoice(event.target.value)} required><option value="">选择已建档证券</option>{securities.data?.map((item) => <option key={item.securityId} value={item.securityId}>{item.securityId} · {item.name}</option>)}<option value="__new__">＋ 新建证券档案</option></select></label>{securityChoice === '__new__' && <div className="form-grid two nested-fields"><label>证券代码<input value={newSecurityId} onChange={(event) => setNewSecurityId(event.target.value)} required /></label><label>证券名称<input value={newSecurityName} onChange={(event) => setNewSecurityName(event.target.value)} required /></label><label>所属行业<input value={newSecurityIndustry} onChange={(event) => setNewSecurityIndustry(event.target.value)} /></label></div>}<label>研究观点<textarea value={view} onChange={(event) => setView(event.target.value)} placeholder="输入对公司、行业或关键经营变量的研究判断" required /></label><label className="checkbox-field"><input type="checkbox" checked={useRag} onChange={(event) => setUseRag(event.target.checked)} /> 使用权限过滤后的混合召回（P1 试点）</label><div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>取消</button><button type="submit" className="button primary" disabled={mutation.isPending}>{mutation.isPending ? '生成中…' : '生成草稿'}</button></div><InlineError error={mutation.error ?? securities.error} /></form></section></div>
}
