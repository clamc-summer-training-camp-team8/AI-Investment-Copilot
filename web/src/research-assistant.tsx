import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { askKnowledge, getDocumentSegment, globalSearch, submitAnswerFeedback } from './api'
import type { AnswerCitation, DocumentSegment, GlobalSearchItem, KnowledgeAnswer, ThesisDetail } from './types'

const groupLabels = {
  security: '公司 / 证券', industry: '行业', thesis: '投资逻辑', event: '事件', document: '知识资料',
} as const

function createClientMessageId() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  return `MSG-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function isTypingTarget(target: EventTarget | null) {
  const element = target as HTMLElement | null
  return Boolean(element?.closest('input, textarea, select, [contenteditable="true"]'))
}

export function GlobalSearch({
  userId, onAsk, onOpenSource,
}: {
  userId: string
  onAsk?: (question: string) => void
  onOpenSource: (locator: string) => void
}) {
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [selected, setSelected] = useState(-1)
  const [recent, setRecent] = useState<string[]>([])
  const search = useQuery({
    queryKey: ['global-search', userId, submitted],
    queryFn: ({ signal }) => globalSearch(submitted, signal),
    enabled: open && Boolean(submitted),
    staleTime: 30_000,
  })
  const results = search.data?.groups.flatMap((group) => group.items) ?? []

  useEffect(() => {
    const handler = (event: globalThis.KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setOpen(true); requestAnimationFrame(() => inputRef.current?.focus())
      } else if (event.key === '/' && !isTypingTarget(event.target)) {
        event.preventDefault(); setOpen(true); requestAnimationFrame(() => inputRef.current?.focus())
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  useEffect(() => {
    if (!open) return
    const normalized = value.trim()
    if (normalized.length < 2) { setSubmitted(''); return }
    const timer = window.setTimeout(() => setSubmitted(normalized), 250)
    return () => window.clearTimeout(timer)
  }, [open, value])

  useEffect(() => { setSelected(results.length ? 0 : -1) }, [results.length])

  const remember = (query: string) => setRecent((items) => [query, ...items.filter((item) => item !== query)].slice(0, 5))
  const close = () => { setOpen(false); setSelected(-1) }
  const openResult = (item: GlobalSearchItem) => {
    remember(value.trim())
    close()
    if (item.target.kind === 'thesis') navigate(`/theses/${encodeURIComponent(item.target.id)}`)
    else if (item.target.kind === 'industry') navigate(`/coverage?industry=${encodeURIComponent(item.target.id)}`)
    else if (item.target.kind === 'security') navigate(`/coverage?securityId=${encodeURIComponent(item.target.id)}`)
    else if (item.target.kind === 'event') navigate(`/radar?eventId=${encodeURIComponent(item.target.id)}`)
    else onOpenSource(item.target.id)
  }
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown' && results.length) { event.preventDefault(); setSelected((index) => (index + 1) % results.length) }
    else if (event.key === 'ArrowUp' && results.length) { event.preventDefault(); setSelected((index) => (index - 1 + results.length) % results.length) }
    else if (event.key === 'Enter') {
      event.preventDefault()
      if (selected >= 0 && results[selected]) openResult(results[selected])
      else if (value.trim()) { setSubmitted(value.trim()); remember(value.trim()) }
    } else if (event.key === 'Escape') {
      event.preventDefault()
      if (value) { setValue(''); setSubmitted('') } else close()
    }
  }

  return <>
    <button className="global-search global-search-trigger" onClick={() => { setOpen(true); requestAnimationFrame(() => inputRef.current?.focus()) }} aria-label="打开全局搜索">
      <span aria-hidden>⌕</span><span>搜索公司、行业、事件或输入投研问题</span><kbd>⌘ K</kbd>
    </button>
    {open && <div className="search-overlay" role="presentation" onMouseDown={close}>
      <section className="search-dialog" role="dialog" aria-modal="true" aria-label="全局搜索" onMouseDown={(event) => event.stopPropagation()}>
        <div className="search-input-row"><span aria-hidden>⌕</span><input ref={inputRef} value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={onKeyDown} placeholder="搜索公司、行业、事件、投资逻辑或资料" aria-controls="global-search-results" aria-activedescendant={selected >= 0 ? `search-result-${selected}` : undefined} /><button onClick={close}>ESC</button></div>
        <div className="search-results" id="global-search-results" aria-live="polite">
          {!submitted && <div className="search-start"><strong>从研究对象或问题开始</strong><p>{onAsk ? '搜索不会调用模型。需要综合回答时，可将完整问题发送给 AI 研究助手。' : '搜索不会调用模型。'}</p>{recent.length > 0 && <div className="recent-searches"><span>最近搜索</span>{recent.map((item) => <button key={item} onClick={() => { setValue(item); setSubmitted(item) }}>{item}</button>)}</div>}</div>}
          {submitted && search.isFetching && <div className="search-state">正在检索有权访问的研究资料…</div>}
          {submitted && search.error && <div className="search-state error"><strong>搜索暂时不可用</strong><span>{search.error.message}</span><button onClick={() => search.refetch()}>重新搜索</button></div>}
          {submitted && !search.isFetching && !search.error && results.length === 0 && <div className="search-state"><strong>没有匹配结果</strong><span>尝试输入更具体的公司、代码、指标或事件。</span></div>}
          {search.data?.groups.map((group) => group.items.length > 0 && <section className="search-group" key={group.type}><header><strong>{groupLabels[group.type]}</strong><span>{group.items.length}</span></header>{group.items.map((item) => { const index = results.indexOf(item); return <button id={`search-result-${index}`} className={selected === index ? 'active' : ''} key={`${group.type}-${item.id}`} onMouseEnter={() => setSelected(index)} onClick={() => openResult(item)}><i>{group.type === 'document' ? '文' : group.type === 'thesis' ? '辑' : group.type === 'event' ? '事' : group.type === 'industry' ? '行' : '企'}</i><span><strong>{item.title}</strong><small>{item.subtitle}</small>{item.excerpt && <p>{item.contentStatus === '标题索引' ? '公告标题（非正文）：' : ''}{item.excerpt}</p>}</span>{item.contentStatus && <em className={item.contentStatus === '标题索引' ? 'title-only' : ''}>{item.contentStatus}</em>}<b>↗</b></button>})}</section>)}
        </div>
        {value.trim() && onAsk && <footer className="search-ask"><span>需要综合多个来源？</span><button onClick={() => { remember(value.trim()); close(); onAsk(value.trim()) }}>✦ 向 AI 研究助手提问</button></footer>}
      </section>
    </div>}
  </>
}

type ChatMessage = { id: string; role: 'user' | 'assistant'; content: string; result?: KnowledgeAnswer }

export function KnowledgeAssistant({
  currentThesisId, theses, prefill, onOpenSource,
}: {
  currentThesisId?: string
  theses: ThesisDetail[]
  prefill?: { text: string; nonce: number }
  onOpenSource: (locator: string) => void
}) {
  const navigate = useNavigate()
  const activeThesis = theses.find((item) => item.thesisId === currentThesisId)
  const hasActiveThesis = Boolean(activeThesis)
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [useContext, setUseContext] = useState(hasActiveThesis)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  const messagesEnd = useRef<HTMLDivElement>(null)
  const openCitation = (citation: AnswerCitation) => {
    if (citation.contentKind === 'structured_thesis') navigate(`/theses/${encodeURIComponent(citation.documentId)}`)
    else if (citation.contentKind === 'structured_portfolio') navigate('/theses')
    else onOpenSource(citation.locator)
  }

  useEffect(() => {
    if (!prefill) return
    setDraft(prefill.text); setOpen(true)
  }, [prefill])
  useEffect(() => {
    setUseContext(hasActiveThesis); setMessages([]); setError('')
  }, [currentThesisId, hasActiveThesis])
  useEffect(() => { messagesEnd.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, loading])

  const submit = async (event?: FormEvent) => {
    event?.preventDefault()
    const question = draft.trim()
    if (question.length < 2 || loading) return
    const history = messages.slice(-6).map((item) => ({ role: item.role, content: item.content }))
    const userMessage: ChatMessage = { id: createClientMessageId(), role: 'user', content: question }
    setMessages((items) => [...items, userMessage]); setDraft(''); setError(''); setLoading(true)
    const nextController = new AbortController(); controller.current = nextController
    try {
      const result = await askKnowledge({
        question,
        context: useContext && activeThesis ? { thesisId: activeThesis.thesisId, securityId: activeThesis.securityId } : undefined,
        history,
      }, nextController.signal)
      setMessages((items) => [...items, { id: result.answerId, role: 'assistant', content: result.answer, result }])
    } catch (caught) {
      if ((caught as Error).name !== 'AbortError') setError((caught as Error).message)
    } finally { setLoading(false); controller.current = null }
  }

  return <>
    <button className={`assistant-fab ${open ? 'open' : ''}`} onClick={() => setOpen(!open)} aria-label={open ? '关闭 AI 研究助手' : '打开 AI 研究助手'}><span>✦</span><b>AI 研究助手</b></button>
    {open && <aside className="assistant-panel" aria-label="AI 研究助手">
      <header><div><span>KNOWLEDGE COPILOT</span><strong>AI 研究助手</strong></div><button onClick={() => setOpen(false)} aria-label="关闭">×</button></header>
      <div className="assistant-context"><span>研究范围</span>{activeThesis ? <button className={useContext ? 'active' : ''} onClick={() => { if (messages.length && useContext) setMessages([]); setUseContext(!useContext) }}>{useContext ? '✓ ' : ''}{activeThesis.securityId} · {activeThesis.title}</button> : <em>当前可见知识库</em>}</div>
      <div className="assistant-messages" aria-live="polite">
        {messages.length === 0 && <section className="assistant-welcome"><i>✦</i><strong>基于可回查资料辅助研究</strong><p>事实回答会附原文引用；只有标题或证据不足时，我会明确说明。</p><div>{['最近有哪些证据挑战核心假设？', '总结当前公司毛利率相关资料', '哪些问题还缺少正文证据？'].map((item) => <button key={item} onClick={() => setDraft(item)}>{item}</button>)}</div></section>}
        {messages.map((message) => <article className={`assistant-message ${message.role}`} key={message.id}><span>{message.role === 'user' ? '你' : 'AI'}</span><div><p>{message.content}</p>{message.result?.inferences.length ? <section className="assistant-inferences"><strong>需要验证的推断</strong>{message.result.inferences.map((item) => <p key={item}>{item}</p>)}</section> : null}{message.result?.citations.length ? <section className="assistant-sources"><strong>可回查来源</strong>{message.result.citations.map((citation) => <button key={citation.locator} onClick={() => openCitation(citation)}><b>{citation.ref}</b><span><strong>{citation.title}</strong><small>{citation.contentStatus} · {citation.retrievalMode}</small><p>{citation.excerpt}</p></span></button>)}</section> : null}{message.result && <footer><span>{message.result.answerStatus === 'insufficient_evidence' ? '证据不足' : 'AI 候选 · 需人工复核'}</span><button onClick={() => navigator.clipboard.writeText(message.content)}>复制</button><button onClick={() => submitAnswerFeedback(message.result!.answerId, 'helpful')}>有帮助</button><button onClick={() => submitAnswerFeedback(message.result!.answerId, 'not_helpful')}>无帮助</button></footer>}</div></article>)}
        {loading && <article className="assistant-message assistant loading"><span>AI</span><div><p>正在检索可见知识并校验引用<span className="thinking-dots">…</span></p><button onClick={() => controller.current?.abort()}>停止</button></div></article>}
        {error && <div className="assistant-error"><strong>本次回答未完成</strong><span>{error}</span><button onClick={() => setError('')}>关闭</button></div>}
        <div ref={messagesEnd} />
      </div>
      <form className="assistant-composer" onSubmit={submit}><textarea value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submit() } }} maxLength={1000} placeholder="输入投研问题；Shift + Enter 换行" disabled={loading} /><div><small>{draft.length}/1000 · 不生成交易指令</small><button type="submit" disabled={draft.trim().length < 2 || loading}>发送 ↑</button></div></form>
      <footer className="assistant-disclaimer">回答仅基于当前可见知识库，AI 生成内容需由研究员核验。</footer>
    </aside>}
  </>
}

export function SourceDrawer({ locator, onClose }: { locator: string | null; onClose: () => void }) {
  const source = useQuery({ queryKey: ['document-segment', locator], queryFn: () => getDocumentSegment(locator!), enabled: Boolean(locator) })
  if (!locator) return null
  const segment: DocumentSegment | undefined = source.data
  return <div className="source-drawer-backdrop" role="presentation" onMouseDown={onClose}><aside className="source-drawer" role="dialog" aria-modal="true" aria-label="原文片段" onMouseDown={(event) => event.stopPropagation()}><header><div><span>TRACEABLE SOURCE</span><strong>{segment?.title ?? '原文片段'}</strong></div><button onClick={onClose}>×</button></header>{source.isLoading && <div className="source-state">正在读取有权访问的原文…</div>}{source.error && <div className="source-state error">{source.error.message}</div>}{segment && <main><div className="source-metadata"><span>{segment.locator}</span>{segment.page && <span>第 {segment.page} 页</span>}<span>{segment.contentKind}</span><span>{segment.extractionMethod}</span></div><p>{segment.content}</p><footer><span>该片段已由服务端再次执行权限检查。</span></footer></main>}</aside></div>
}
