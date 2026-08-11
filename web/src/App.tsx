import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { FormEvent } from 'react'
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { createDraft, listTheses, useMock } from './api'
import { InlineError, ResearchContextPicker } from './components'
import { EvidencePage, RadarPage, ReviewsPage, ThesisListPage, ThesisPage, WorkbenchPage } from './pages'

export function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const [showCreate, setShowCreate] = useState(false)
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
    <div className="workspace"><header className="topbar"><ResearchContextPicker theses={theses.data ?? []} value={currentThesisId} onChange={(id) => id ? navigate(`/radar?thesisId=${encodeURIComponent(id)}`) : navigate('/workbench')} /><div className="top-actions"><button className="button secondary" onClick={() => setShowCreate(true)}>＋ 新建投资逻辑</button><button className="button ghost" disabled>全局搜索（P1）</button></div></header><main className="main-content"><Routes><Route path="/workbench" element={<WorkbenchPage />} /><Route path="/radar" element={<RadarPage />} /><Route path="/radar/:evidenceId" element={<EvidencePage />} /><Route path="/theses" element={<ThesisListPage />} /><Route path="/theses/:thesisId" element={<ThesisPage />} /><Route path="/reviews" element={<ReviewsPage />} /><Route path="*" element={<Navigate to="/workbench" replace />} /></Routes></main></div>
    {showCreate && <CreateDraftDialog onClose={() => setShowCreate(false)} />}
  </div>
}

function CreateDraftDialog({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate()
  const [securityId, setSecurityId] = useState('688981')
  const [view, setView] = useState('')
  const mutation = useMutation({ mutationFn: () => createDraft({ securityId, view }), onSuccess: (thesis) => { onClose(); navigate(`/theses/${thesis.thesisId}`) } })
  return <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}><section className="dialog create-dialog" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}><span className="eyebrow">AI 草稿</span><h2>新建投资逻辑</h2><p>输入研究观点，由模型生成可审核草稿；发布仍需研究员人工确认。</p><form className="form-grid" onSubmit={(event: FormEvent) => { event.preventDefault(); mutation.mutate() }}><label>证券代码<input value={securityId} onChange={(event) => setSecurityId(event.target.value)} required /></label><label>研究观点<textarea value={view} onChange={(event) => setView(event.target.value)} placeholder="输入对公司、行业或关键经营变量的研究判断" required /></label><div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>取消</button><button type="submit" className="button primary" disabled={mutation.isPending}>{mutation.isPending ? '生成中…' : '生成草稿'}</button></div><InlineError error={mutation.error} /></form></section></div>
}
