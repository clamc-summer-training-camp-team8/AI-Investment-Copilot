import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { createDraft, getJob, listTheses, uploadDocument, useMock } from './api'
import { InlineError, ResearchContextPicker } from './components'
import type { JobAccepted, ThesisDetail } from './types'
import { EvidencePage, RadarPage, ReviewsPage, ThesisListPage, ThesisPage, WorkbenchPage } from './pages'

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
    ['工作台', '/workbench', '01'],
    ['变化雷达', radarPath, '02'],
    ['投资逻辑', '/theses', '03'],
    ['复核与复盘', '/reviews', '04'],
  ] as const
  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-mark">IR</span><div><strong>权益投研</strong><span>AI Copilot</span></div></div><nav>{navigation.map(([label, path, index]) => <NavLink key={label} to={path} className={({ isActive }) => isActive || (label === '变化雷达' && location.pathname.startsWith('/radar')) || (label === '投资逻辑' && location.pathname.startsWith('/theses')) ? 'active' : ''}><span>{index}</span>{label}</NavLink>)}</nav><div className="sidebar-footer"><span className="live-dot" />{useMock ? '受控 Mock 数据' : '真实公开数据'}<small>研究辅助 · 人工决策</small></div></aside>
    <div className="workspace"><header className="topbar"><ResearchContextPicker theses={theses.data ?? []} value={currentThesisId} onChange={(id) => id ? navigate(`/radar?thesisId=${encodeURIComponent(id)}`) : navigate('/workbench')} /><div className="top-actions"><button className="button secondary" onClick={() => setShowUpload(true)}>上传研究资料</button><button className="button secondary" onClick={() => setShowCreate(true)}>＋ 新建投资逻辑</button></div></header><main className="main-content"><Routes><Route path="/workbench" element={<WorkbenchPage />} /><Route path="/radar" element={<RadarPage />} /><Route path="/radar/:evidenceId" element={<EvidencePage />} /><Route path="/theses" element={<ThesisListPage />} /><Route path="/theses/:thesisId" element={<ThesisPage />} /><Route path="/reviews" element={<ReviewsPage />} /><Route path="*" element={<Navigate to="/workbench" replace />} /></Routes></main></div>
    {showCreate && <CreateDraftDialog onClose={() => setShowCreate(false)} />}
    {showUpload && <UploadDocumentDialog theses={theses.data ?? []} initialThesisId={currentThesisId} onClose={() => setShowUpload(false)} />}
  </div>
}

function UploadDocumentDialog({ theses, initialThesisId, onClose }: { theses: ThesisDetail[]; initialThesisId?: string; onClose: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [publishedAt, setPublishedAt] = useState(() => localDateTimeValue())
  const [thesisId, setThesisId] = useState(initialThesisId ?? '')
  const [view, setView] = useState('')
  const [accepted, setAccepted] = useState<JobAccepted | null>(null)
  const selected = theses.find((item) => item.thesisId === thesisId)
  const mutation = useMutation({
    mutationFn: () => {
      if (!file) throw new Error('请选择 PDF、DOCX 或 TXT 文件。')
      return uploadDocument({ file, publishedAt, thesisId: selected?.thesisId, securityId: selected?.securityId, view })
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
  return <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}><section className="dialog upload-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><span className="eyebrow">知识底座</span><h2>上传研究资料</h2><p>文件将解析为可回查段落，并抽取营业收入、销量与交付量同比事实。首次公开时间必须准确填写。</p>{!accepted ? <form className="form-grid" onSubmit={(event) => { event.preventDefault(); mutation.mutate() }}><label>文件<input type="file" accept=".pdf,.docx,.txt" onChange={(event) => setFile(event.target.files?.[0] ?? null)} required /></label><label>首次公开时间<input type="datetime-local" value={publishedAt} onChange={(event) => setPublishedAt(event.target.value)} required /></label><label>关联投资逻辑（可选）<select value={thesisId} onChange={(event) => setThesisId(event.target.value)}><option value="">仅入知识库</option>{theses.map((item) => <option key={item.thesisId} value={item.thesisId}>{item.title}</option>)}</select></label>{selected && <label>本次研究观点（可选）<textarea value={view} onChange={(event) => setView(event.target.value)} placeholder="如需基于该资料更新草稿，可补充研究观点" /></label>}<div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>取消</button><button type="submit" className="button primary" disabled={mutation.isPending}>{mutation.isPending ? '上传中…' : '上传并处理'}</button></div><InlineError error={mutation.error} /></form> : <div className="job-progress"><span className={`job-state ${job.data?.success === false ? 'failed' : ''}`}>{job.data?.status === 'complete' ? (job.data.success ? '处理完成' : '处理失败') : '后台处理中…'}</span><dl><dt>文档 ID</dt><dd>{accepted.documentId}</dd>{result && <><dt>段落</dt><dd>{String(result.segment_count ?? 0)}</dd><dt>正文事实</dt><dd>{String(result.fact_count ?? 0)}</dd><dt>重复文档</dt><dd>{result.duplicate ? '是，已复用既有记录' : '否'}</dd></>}</dl>{job.data?.success === false && <p className="inline-error">{String(result?.reason ?? result?.message ?? '处理失败，请检查任务详情。')}</p>}<div className="dialog-actions">{job.data?.success === false && <button className="button secondary" onClick={() => { setAccepted(null); mutation.reset() }}>重新提交</button>}<button className="button primary" onClick={onClose} disabled={!job.data || (job.data.status !== 'complete' && job.data.status !== 'not_found')}>完成</button></div></div>}</section></div>
}

function CreateDraftDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const [securityId, setSecurityId] = useState('688981')
  const [view, setView] = useState('')
  const mutation = useMutation({ mutationFn: () => createDraft({ securityId, view }), onSuccess: (thesis) => { onClose(); navigate(`/theses/${thesis.thesisId}`) } })
  return <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}><section className="dialog create-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><span className="eyebrow">AI 草稿</span><h2>新建投资逻辑</h2><p>输入研究观点，由模型生成可审核草稿；发布仍需研究员人工确认。</p><form className="form-grid" onSubmit={(event: FormEvent) => { event.preventDefault(); mutation.mutate() }}><label>证券代码<input value={securityId} onChange={(event) => setSecurityId(event.target.value)} required /></label><label>研究观点<textarea value={view} onChange={(event) => setView(event.target.value)} placeholder="输入对公司、行业或关键经营变量的研究判断" required /></label><div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>取消</button><button type="submit" className="button primary" disabled={mutation.isPending}>{mutation.isPending ? '生成中…' : '生成草稿'}</button></div><InlineError error={mutation.error} /></form></section></div>
}
