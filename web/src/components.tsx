import { useState, type ReactNode } from 'react'
import { NavLink } from 'react-router-dom'
import type { ConfirmationState, Direction, EvidenceFeedItem, Priority, ThesisSummary, ValidationItem } from './types'
import { directionText, formatDate, priorityText, stateText } from './ui'

export function StatusBadge({ state }: { state: ConfirmationState }) {
  return <span className={`badge status-${state}`}><i />{stateText[state]}</span>
}

export function DirectionBadge({ direction }: { direction: Direction }) {
  return <span className={`badge direction-${direction}`}>{directionText[direction]}</span>
}

export function PriorityBadge({ priority }: { priority: Priority }) {
  return <span className={`badge priority-${priority}`}>{priorityText[priority]}</span>
}

export function PageTitle({ eyebrow, title, description, actions }: { eyebrow?: string; title: string; description: string; actions?: ReactNode }) {
  return <header className="page-title"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{actions && <div className="page-actions">{actions}</div>}</header>
}

export function ResearchContextPicker({ theses, value, onChange }: { theses: ThesisSummary[]; value?: string; onChange: (id: string) => void }) {
  return <label className="context-picker"><span>当前研究逻辑</span><select value={value ?? ''} onChange={(event) => onChange(event.target.value)}><option value="">选择投资逻辑</option>{theses.map((item) => <option key={item.thesisId} value={item.thesisId}>{item.title} · {item.status}</option>)}</select></label>
}

export function EvidenceEventRow({ item, featured = false }: { item: EvidenceFeedItem; featured?: boolean }) {
  return <article className={`evidence-row ${featured ? 'featured' : ''}`}>
    <div className="evidence-main">
      <div className="badge-row"><PriorityBadge priority={item.priority} /><StatusBadge state={item.confirmationStatus} /><DirectionBadge direction={item.direction} /></div>
      <h3>{item.sourceDocumentTitle}</h3>
      <p className="excerpt">{item.factExcerpt}</p>
      <div className="source-meta"><span>{item.securityName} · {item.securityId}</span><span>公开披露 · {formatDate(item.disclosedAt)}</span></div>
      <div className="hypothesis-line"><span>影响假设</span><strong>{item.hypothesisStatement}</strong></div>
    </div>
    <div className="evidence-side">
      <div className="confidence"><span>AI 置信度</span><strong>{Math.round(item.aiConfidence * 100)}%</strong></div>
      <NavLink className="primary-link" to={`/radar/${item.evidenceId}?thesisId=${encodeURIComponent(item.thesisId)}&relationId=${encodeURIComponent(item.relationId)}`}>去核验 <span>→</span></NavLink>
      <NavLink className="secondary-link" to={`/theses/${item.thesisId}`}>查看逻辑</NavLink>
    </div>
  </article>
}

export function ValidationChain({ items }: { items: ValidationItem[] }) {
  return <div className="validation-chain">{items.map((item, index) => <div className={`validation-step validation-${item.status}`} key={item.code}><div className="validation-marker">{item.status === 'passed' ? '✓' : item.status === 'warning' ? '!' : '×'}</div><div><strong>{item.label}</strong><p>{item.message}</p></div>{index < items.length - 1 && <span className="validation-line" />}</div>)}</div>
}

export function LoadingState({ text = '正在加载研究数据…' }: { text?: string }) {
  return <div className="page-state"><span className="spinner" /><strong>{text}</strong></div>
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="page-state empty"><span className="state-icon">◇</span><strong>{title}</strong><p>{description}</p>{action}</div>
}

export function ErrorState({ error }: { error: Error | null }) {
  return <div className="page-state error"><span className="state-icon">!</span><strong>数据加载失败</strong><p>{error?.message ?? '请刷新页面或联系管理员。'}</p><button onClick={() => window.location.reload()}>刷新页面</button></div>
}

export function InlineError({ error }: { error: Error | null }) {
  return error ? <p className="inline-error">{error.message}</p> : null
}

export function ConfirmDialog({ title, description, confirmText, danger = false, requireReason = false, onConfirm, onClose }: { title: string; description: string; confirmText: string; danger?: boolean; requireReason?: boolean; onConfirm: (reason: string) => void; onClose: () => void }) {
  return <div className="dialog-backdrop" role="presentation" onMouseDown={onClose}><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title" onMouseDown={(event) => event.stopPropagation()}><h2 id="dialog-title">{title}</h2><p>{description}</p><DialogForm confirmText={confirmText} danger={danger} requireReason={requireReason} onConfirm={onConfirm} onClose={onClose} /></section></div>
}

function DialogForm({ confirmText, danger, requireReason, onConfirm, onClose }: { confirmText: string; danger: boolean; requireReason: boolean; onConfirm: (reason: string) => void; onClose: () => void }) {
  const [reason, setReason] = useState('')
  return <form onSubmit={(event) => { event.preventDefault(); onConfirm(reason) }}><textarea name="reason" value={reason} required={requireReason} placeholder={requireReason ? '请输入原因（必填）' : '补充判断理由（可选）'} onChange={(event) => setReason(event.target.value)} /><div className="dialog-actions"><button type="button" className="button secondary" onClick={onClose}>取消</button><button type="submit" className={`button ${danger ? 'danger' : 'primary'}`}>{confirmText}</button></div></form>
}
