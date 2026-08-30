import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { createDraft, createSecurity, getJob, listSecurities, listTheses, reanalyzeProcessingJob, uploadDocument, useMock } from './api'
import { Icon, InlineError, ResearchContextPicker } from './components'
import type { JobAccepted, ThesisDetail } from './types'
import { AssetPage, EvidencePage, RadarPage, ReviewsPage, ThesisListPage, ThesisPage, WorkbenchPage } from './pages'

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
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">跳到主要内容</a>
    <header className="global-topbar">
      <NavLink to="/workbench" className="brand" aria-label="返回工作台"><span className="brand-mark"><Icon name="graph" size={20} /></span><span className="brand-copy"><strong>RESEARCH GRAPH</strong><small>AI INVESTMENT COPILOT</small></span></NavLink>
      <div className="terminal-meta"><span className="live-dot" /><span>{useMock ? 'CONTROLLED MOCK' : 'PUBLIC DATA · LIVE'}</span><span className="mono">HUMAN GATED</span></div>
    </header>
    <aside className="sidebar" aria-label="产品主导航"><div className="rail-heading"><span className="mono">0{Math.max(0, activeIndex) + 1}</span><small>RESEARCH DESK</small></div><nav>{navigation.map(([label, path, index, icon]) => <NavLink key={label} to={path} aria-label={label} className={() => isNavigationActive(label, path) ? 'active' : ''}><Icon name={icon} size={18} /><span className="nav-copy"><b>{label}</b><small className="mono">{index}</small></span></NavLink>)}</nav><div className="sidebar-footer"><span><i className="live-dot" />{useMock ? '受控 Mock 数据' : '真实公开数据'}</span><small>研究辅助 · 人工决策</small></div></aside>
    <div className="workspace"><header className="workspace-bar"><ResearchContextPicker theses={theses.data ?? []} value={currentThesisId} onChange={(id) => id ? navigate(`/radar?thesisId=${encodeURIComponent(id)}`) : navigate('/workbench')} /><div className="top-actions"><button className="button secondary" onClick={() => setShowUpload(true)}><Icon name="upload" size={15} />上传研究资料</button><button className="button primary" onClick={() => setShowCreate(true)}><span aria-hidden>＋</span>新建投资逻辑</button></div></header><main className="main-content" id="main-content" tabIndex={-1}><Routes><Route path="/workbench" element={<WorkbenchPage />} /><Route path="/radar" element={<RadarPage />} /><Route path="/radar/:evidenceId" element={<EvidencePage />} /><Route path="/theses" element={<ThesisListPage />} /><Route path="/theses/:thesisId" element={<ThesisPage />} /><Route path="/reviews" element={<ReviewsPage />} /><Route path="/assets" element={<AssetPage />} /><Route path="*" element={<Navigate to="/workbench" replace />} /></Routes></main></div>
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
  const progressLabel = uploadStageLabels[String(result?.stage ?? '')] ?? '后台处理中…'
  const reanalyze = useMutation({ mutationFn: () => reanalyzeProcessingJob(accepted!.jobId), onSuccess: setAccepted })
  return <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}><section className="dialog upload-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><span className="eyebrow">变化处理链</span><h2>上传研究资料</h2><p>选择证券后，系统会执行“事件抽取 → 已发布投资逻辑召回 → 候选证据 → 变化雷达”。候选结果仍需人工确认。</p>{!accepted ? <form className="form-grid" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><label>文件<input type="file" accept=".pdf,.docx,.txt" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required /></label><label>首次公开时间<input type="datetime-local" value={publishedAt} onChange={(event) => setPublishedAt(event.target.value)} required /></label><label>归属证券<select value={securityChoice} onChange={(event) => setSecurityChoice(event.target.value)}><option value="">仅入知识库（不进入雷达）</option>{securities.data?.map((item) => <option key={item.securityId} value={item.securityId}>{item.securityId} · {item.name}</option>)}<option value="__new__">＋ 新建证券档案</option></select></label>{securityChoice === '__new__' && <div className="form-grid two nested-fields"><label>证券代码<input value={newSecurityId} onChange={(event) => setNewSecurityId(event.target.value)} required /></label><label>证券名称<input value={newSecurityName} onChange={(event) => setNewSecurityName(event.target.value)} required /></label><label>所属行业<input value={newSecurityIndustry} onChange={(event) => setNewSecurityIndustry(event.target.value)} /></label></div>}<div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>取消</button><button type="submit" className="button primary" disabled={mutation.isPending}>{mutation.isPending ? '上传中…' : '上传并处理'}</button></div><InlineError error={mutation.error ?? securities.error} /></form> : <div className="job-progress"><span className={`job-state ${job.data?.success === false ? 'failed' : ''}`}>{job.data?.status === 'complete' ? (job.data.success ? '处理完成' : '处理失败') : progressLabel}</span><dl><dt>文档 ID</dt><dd>{accepted.documentId}</dd>{result && <><dt>段落</dt><dd>{String(result.segment_count ?? 0)}</dd><dt>正文事实</dt><dd>{String(result.fact_count ?? 0)}</dd><dt>事件</dt><dd>{String(result.event_count ?? 0)}</dd><dt>召回逻辑</dt><dd>{String(result.matched_thesis_count ?? 0)}</dd><dt>候选证据</dt><dd>{String(result.candidate_evidence_count ?? 0)}</dd><dt>待人工判断</dt><dd>{String(result.deferred_event_count ?? 0)}</dd><dt>重复文档</dt><dd>{result.duplicate ? '是，已复用既有记录' : '否'}</dd></>}</dl>{job.data?.success === false && <p className="inline-error">{String(result?.reason ?? result?.message ?? '处理失败，请检查任务详情。')}</p>}<div className="dialog-actions">{job.data?.success === false && Boolean(result?.parsed) && <button className="button secondary" disabled={reanalyze.isPending} onClick={() => reanalyze.mutate()}>{reanalyze.isPending ? '正在重新入队…' : '重新分析（不解析文件）'}</button>}{job.data?.success === false && !result?.parsed && <button className="button secondary" onClick={() => { setAccepted(null); mutation.reset() }}>重新提交文件</button>}<button className="button primary" onClick={onClose} disabled={!job.data || (job.data.status !== 'complete' && job.data.status !== 'not_found')}>完成</button></div></div>}</section></div>
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
  const [useRag, setUseRag] = useState(true)
  const mutation = useMutation({ mutationFn: async () => { let securityId = securityChoice; if (securityChoice === '__new__') { if (!newSecurityId.trim() || !newSecurityName.trim()) throw new Error('新证券的代码和名称必填。'); const created = await createSecurity({ securityId: newSecurityId, name: newSecurityName, industry: newSecurityIndustry }); securityId = created.securityId; await qc.invalidateQueries({ queryKey: ['securities'] }) } if (!securityId) throw new Error('请选择或新建证券。'); return createDraft({ securityId, view, useRag }) }, onSuccess: async (thesis) => { await qc.invalidateQueries({ queryKey: ['theses'] }); onClose(); navigate(`/theses/${thesis.thesisId}`) } })
  return <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}><section className="dialog create-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><span className="eyebrow">AI 候选草稿</span><h2>新建投资逻辑</h2><p>模型会根据研究问题和 RAG 历史资料生成 2–5 条可证伪假设候选；引用仍是候选，发布前必须人工确认。</p><form className="form-grid" onSubmit={(event: FormEvent) => { event.preventDefault(); mutation.mutate() }}><label>投资对象<select value={securityChoice} onChange={(event) => setSecurityChoice(event.target.value)} required><option value="">选择已建档证券</option>{securities.data?.map((item) => <option key={item.securityId} value={item.securityId}>{item.securityId} · {item.name}</option>)}<option value="__new__">＋ 新建证券档案</option></select></label>{securityChoice === '__new__' && <div className="form-grid two nested-fields"><label>证券代码<input value={newSecurityId} onChange={(event) => setNewSecurityId(event.target.value)} required /></label><label>证券名称<input value={newSecurityName} onChange={(event) => setNewSecurityName(event.target.value)} required /></label><label>所属行业<input value={newSecurityIndustry} onChange={(event) => setNewSecurityIndustry(event.target.value)} /></label></div>}<label>研究问题（可选）<textarea value={view} onChange={(event) => setView(event.target.value)} placeholder="留空则完全基于 RAG 历史资料生成" /></label><label className="checkbox-field"><input type="checkbox" checked={useRag} onChange={(event) => setUseRag(event.target.checked)} /> 使用权限过滤后的历史资料（RAG）</label><div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>取消</button><button type="submit" className="button primary" disabled={mutation.isPending}>{mutation.isPending ? '生成中…' : '生成草稿'}</button></div><InlineError error={mutation.error ?? securities.error} /></form></section></div>
}
