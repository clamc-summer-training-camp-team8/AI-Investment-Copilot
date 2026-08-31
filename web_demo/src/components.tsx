import { useEffect, useRef, type ReactNode } from 'react'
import { Link, NavLink, useLocation, useParams } from 'react-router-dom'
import { scenario } from './scenario'
import type { Direction, SourceKind } from './types'

const configuredThesisId = import.meta.env.VITE_DEMO_THESIS_ID || 'THS-688981-2023FY'

const steps = [
  { label: '逻辑', match: /^\/theses\/[^/]+$/ },
  { label: '资料', match: /\/upload$/ },
  { label: '分析', match: /\/evidence\// },
  { label: '复核', match: /\/evidence\// },
  { label: '决策', match: /\/decision$/ },
  { label: '时间线', match: /\/timeline$/ },
]

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    graph: <><circle cx="5" cy="6" r="2" /><circle cx="19" cy="5" r="2" /><circle cx="17" cy="19" r="2" /><path d="M7 6l10-1M6 8l10 9m2-10-1 10" /></>,
    upload: <><path d="M12 16V4m0 0L7 9m5-5 5 5" /><path d="M5 15v4h14v-4" /></>,
    arrow: <><path d="M5 12h14m-5-5 5 5-5 5" /></>,
    back: <><path d="M19 12H5m5 5-5-5 5-5" /></>,
    quote: <><path d="M7 10h4v8H5v-6c0-4 2-6 6-6M17 10h4v8h-6v-6c0-4 2-6 6-6" /></>,
    check: <path d="M5 12l4 4L19 6" />,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v6l4 2" /></>,
    shield: <><path d="M12 3l8 3v6c0 5-3 8-8 10-5-2-8-5-8-10V6l8-3z" /><path d="M9 12l2 2 4-5" /></>,
    alert: <><path d="M12 3L2.5 20h19L12 3z" /><path d="M12 9v5m0 3h.01" /></>,
  }
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      {paths[name]}
    </svg>
  )
}

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { thesisId } = useParams()
  const mainRef = useRef<HTMLElement>(null)
  const previousPath = useRef(location.pathname)
  const id = thesisId || new URLSearchParams(location.search).get('thesisId') || configuredThesisId
  const matchedIndex = steps.findIndex((step) => step.match.test(location.pathname))
  const activeIndex = Math.max(0, matchedIndex)
  const isAnalysisReviewRoute = /\/evidence\//.test(location.pathname)

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'auto' })
    if (previousPath.current !== location.pathname) {
      mainRef.current?.focus({ preventScroll: true })
      previousPath.current = location.pathname
    }
  }, [location.pathname])

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳到主要内容</a>
      <header className="topbar">
        <Link to={`/theses/${id}`} className="brand" aria-label="返回投资逻辑">
          <span className="brand-mark"><Icon name="graph" size={20} /></span>
          <span><b>RESEARCH GRAPH</b><small>AI INVESTMENT COPILOT</small></span>
        </Link>
        <div className="terminal-meta">
          <span className="live-dot" />
          <span>{scenario.mode === 'real' ? 'DEMO DB · LIVE' : 'CONTROLLED MOCK'}</span>
          <span className="mono">688981.SH</span>
        </div>
      </header>

      <aside className="rail" aria-label="演示流程">
        <div className="rail-index mono">{isAnalysisReviewRoute ? '03—04' : `0${activeIndex + 1}`}</div>
        <div className="rail-line" />
        <span className="rail-label">LOGIC VALIDATION</span>
      </aside>

      <main ref={mainRef} className="main-stage" id="main-content" tabIndex={-1}>
        <div className="scenario-bar">
          <div>
            <span className="scenario-kicker">真实年报案例 · 中芯国际</span>
            <span className="scenario-note">
              <Icon name="shield" size={14} />
              数据库既有 AI 候选 · 人工闸门 · 真实业务状态
            </span>
          </div>
          <nav className="stepper" aria-label="流程步骤">
            {steps.map((step, index) => (
              <span
                key={step.label}
                className={
                  index < activeIndex
                    ? 'done'
                    : index === activeIndex || (isAnalysisReviewRoute && index === 3)
                      ? 'active'
                      : ''
                }
                aria-current={index === activeIndex ? 'step' : undefined}
              >
                <i>{index < activeIndex ? '✓' : index + 1}</i>
                <b>{step.label}</b>
              </span>
            ))}
          </nav>
        </div>
        {children}
      </main>

      <footer className="disclaimer">
        《中芯国际 2023 年年度报告》重大风险演示 · 不构成交易、评级、调仓或收益建议
        <span className="mono">{configuredThesisId} / 688981.SH / LIVE</span>
      </footer>
    </div>
  )
}

export function PageIntro({
  eyebrow,
  title,
  description,
  backTo,
  aside,
}: {
  eyebrow: string
  title: string
  description: string
  backTo?: string
  aside?: ReactNode
}) {
  return (
    <header className="page-intro reveal">
      <div className="intro-copy">
        {backTo && <Link className="back-link" to={backTo}><Icon name="back" />返回逻辑</Link>}
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {aside && <div className="intro-aside">{aside}</div>}
    </header>
  )
}

export function SourceLabel({ kind }: { kind: SourceKind }) {
  const map = {
    fact: ['来源事实', 'F'],
    ai: ['预置 AI 候选', 'AI'],
    computed: ['程序计算', 'ƒ'],
    human: ['人工确认', 'H'],
  }
  return <span className={`source-label ${kind}`}><i>{map[kind][1]}</i>{map[kind][0]}</span>
}

export function DirectionBadge({ direction }: { direction: Direction }) {
  const labels = { support: '支持', conflict: '冲突', neutral: '中性' }
  return <span className={`direction ${direction}`}>{labels[direction]}</span>
}

export function Metric({ label, value, note }: { label: string; value: string; note?: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>
}

export function QueryState({
  loading,
  error,
  onRetry,
  children,
}: {
  loading: boolean
  error: Error | null
  onRetry?: () => void
  children: ReactNode
}) {
  if (loading) return <div className="loading-frame" role="status" aria-live="polite" aria-label="正在加载数据"><span /><span /><span /></div>
  if (error) return (
    <div className="error-frame" role="alert">
      <Icon name="alert" />
      <div><strong>数据暂不可用</strong><p>{error.message}</p></div>
      {onRetry && <button className="button ghost" onClick={onRetry}>重新查询</button>}
    </div>
  )
  return <>{children}</>
}

export function ActionLink({ to, children }: { to: string; children: ReactNode }) {
  return <Link className="action-link" to={to}>{children}<Icon name="arrow" /></Link>
}

export function MobileNav({ thesisId }: { thesisId: string }) {
  return (
    <nav className="mobile-nav" aria-label="移动端主导航">
      <NavLink to={`/theses/${thesisId}`}>逻辑</NavLink>
      <NavLink to={`/theses/${thesisId}/upload`}>资料</NavLink>
      <NavLink to={`/theses/${thesisId}/decision`}>决策</NavLink>
      <NavLink to={`/theses/${thesisId}/timeline`}>时间线</NavLink>
    </nav>
  )
}
