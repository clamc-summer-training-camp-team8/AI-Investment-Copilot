import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ActionLink,
  DirectionBadge,
  Icon,
  Metric,
  MobileNav,
  PageIntro,
  QueryState,
  SourceLabel,
} from './components'
import { scenario } from './scenario'
import type { DecisionAction, TimelineDimension } from './types'

const configuredThesisId = import.meta.env.VITE_DEMO_THESIS_ID || 'THS-688981-2023FY'
const displaySecurityId = (securityId: string) =>
  !securityId ? '—' : securityId.includes('.') ? securityId : `${securityId}.SH`
const thesisKey = (id: string) => ['demo', 'thesis', id] as const
const analysisKey = (evidenceId: string, relationId: string) =>
  ['demo', 'analysis', evidenceId, relationId] as const
const suggestionsKey = (id: string) => ['demo', 'suggestions', id] as const
const timelineKey = (id: string) => ['demo', 'timeline', id] as const

export function DemoEntryPage() {
  return <Navigate replace to={`/theses/${configuredThesisId}`} />
}

export function ThesisOverviewPage() {
  const id = useParams().thesisId ?? configuredThesisId
  const query = useQuery({ queryKey: thesisKey(id), queryFn: () => scenario.getThesis(id) })
  const suggestions = useQuery({ queryKey: suggestionsKey(id), queryFn: () => scenario.getSuggestions(id) })

  return (
    <div className="page overview-page">
      <QueryState loading={query.isPending} error={query.error} onRetry={() => query.refetch()}>
        {query.data && (
          <>
            <PageIntro
              eyebrow="INVESTMENT THESIS / 核心投资逻辑"
              title={query.data.title}
              description={query.data.coreView}
              aside={
                <div className="thesis-stamp">
                  <span>当前状态</span>
                  <strong>{query.data.status}</strong>
                  <small className="mono">VERSION {String(query.data.version).padStart(2, '0')}</small>
                </div>
              }
            />

            <section className="logic-canvas reveal delay-1" aria-label="投资逻辑证据链">
              <div className="logic-origin">
                <span className="node-code mono">{displaySecurityId(query.data.securityId)}</span>
                <h2>{query.data.securityName}</h2>
                <p>{query.data.direction}</p>
                <div className="origin-meta">
                  <span>负责人<b>{query.data.owner}</b></span>
                  <span>建卡日<b>{query.data.establishedOn}</b></span>
                </div>
              </div>

              <div className="hypothesis-network">
                <div className="network-label mono">HYPOTHESIS NETWORK / 03</div>
                {query.data.hypotheses.map((hypothesis, index) => (
                  <article className="hypothesis-branch" key={hypothesis.hypothesisId} id={hypothesis.hypothesisId}>
                    <div className="branch-connector"><span>{String(index + 1).padStart(2, '0')}</span></div>
                    <div className="hypothesis-main">
                      <div className="hypothesis-heading">
                        <span className="mono">{hypothesis.hypothesisId}</span>
                        <span className={`health health-${index}`}>{hypothesis.health}</span>
                      </div>
                      <h3>{hypothesis.statement}</h3>
                      <div className="evidence-counts">
                        <span className="support">支持 <b>{hypothesis.supportConfirmed}</b></span>
                        <span className="conflict">冲突 <b>{hypothesis.conflictConfirmed}</b></span>
                        <span className="pending">待确认 <b>{hypothesis.pending}</b></span>
                        <SourceLabel kind="computed" />
                      </div>
                    </div>
                    <div className="branch-satellites">
                      <div className="indicator-node">
                        <small>跟踪指标</small>
                        <strong>{hypothesis.metric.name}</strong>
                        <span>{hypothesis.metric.value}</span>
                        <em>{hypothesis.metric.trend}</em>
                      </div>
                      <div className="invalidation-node">
                        <small>失效条件</small>
                        <p>{hypothesis.invalidation}</p>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </section>

            <section className="overview-actions reveal delay-2">
              <div className="next-action">
                <span className="mono">NEXT VALIDATION</span>
                <h2>用新增事实，挑战核心假设</h2>
                <p>上传固定公开资料，由后端将解析结果、证据候选和指标观测写入 PostgreSQL。</p>
                <ActionLink to={`/theses/${id}/upload`}>上传新资料</ActionLink>
              </div>
              <div className="secondary-actions">
                {suggestions.data?.length ? (
                  <Link to={`/theses/${id}/decision`} className="signal-strip">
                    <SourceLabel kind="computed" />
                    <span><b>发现 1 条待处置状态建议</b><small>规则引擎已生成，等待负责人决策</small></span>
                    <Icon name="arrow" />
                  </Link>
                ) : (
                  <div className="signal-strip muted">
                    <Icon name="check" />
                    <span><b>暂无待处置建议</b><small>逻辑状态维持当前判断</small></span>
                  </div>
                )}
                <ActionLink to={`/theses/${id}/timeline`}>查看完整证据时间线</ActionLink>
              </div>
            </section>
            <MobileNav thesisId={id} />
          </>
        )}
      </QueryState>
    </div>
  )
}

export function MaterialUploadPage() {
  const id = useParams().thesisId ?? configuredThesisId
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const thesis = useQuery({ queryKey: thesisKey(id), queryFn: () => scenario.getThesis(id) })
  const upload = useMutation({
    mutationFn: () => {
      if (!file) throw new Error('请选择固定演示资料。')
      return scenario.uploadMaterial(id, file)
    },
    onSuccess: (result) => {
      if (!result.nextUrl.startsWith('/evidence/')) {
        setError('服务端返回了不安全的跳转地址。')
        return
      }
      navigate(result.nextUrl)
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : '上传失败'),
  })

  return (
    <div className="page">
      <PageIntro
        backTo={`/theses/${id}`}
        eyebrow="MATERIAL INTAKE / 资料接入"
        title="只上传 1 份年报，同时检验 3 项假设"
        description="本流程只有一次资料上传：提交《中芯国际 2023 年年度报告》后，程序从同一份报告提取三项指标，并分别检验需求、盈利与产能假设。"
        aside={<div className="step-number"><span>STEP</span><strong>02</strong><small>/ 06</small></div>}
      />

      <QueryState loading={thesis.isPending} error={thesis.error} onRetry={() => thesis.refetch()}>
        {thesis.data && (
          <section className="pre-upload-thesis reveal delay-1" aria-label="上传前投资逻辑摘要">
            <div className="pre-upload-view">
              <span className="eyebrow">THESIS IN SCOPE / 待验证投资逻辑</span>
              <h2>{thesis.data.title}</h2>
              <p>{thesis.data.coreView}</p>
              <div className="scope-flow" aria-label="一份年报同时检验三项假设">
                <span><b>01</b> 份年报</span>
                <i aria-hidden>→</i>
                <span><b>03</b> 项假设</span>
              </div>
            </div>
            <div className="pre-upload-hypotheses">
              {thesis.data.hypotheses.map((hypothesis, index) => (
                <article key={hypothesis.hypothesisId}>
                  <span className="mono">{String(index + 1).padStart(2, '0')} / {hypothesis.hypothesisId}</span>
                  <h3>{hypothesis.statement}</h3>
                  <p><b>失效阈值</b>{hypothesis.invalidation}</p>
                </article>
              ))}
            </div>
          </section>
        )}
      </QueryState>

      <section className="upload-layout reveal delay-1">
        <input
          ref={inputRef}
          id="demo-material-file"
          className="visually-hidden"
          type="file"
          accept=".pdf,application/pdf"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null)
            setError('')
          }}
        />
        <button
          type="button"
          className={`drop-zone ${file ? 'has-file' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault()
            setFile(event.dataTransfer.files[0] ?? null)
            setError('')
          }}
          aria-describedby="material-upload-help"
        >
          <div className="drop-symbol"><Icon name={file ? 'check' : 'upload'} size={30} /></div>
          <span className="mono">{file ? 'FILE LOCKED' : 'DROP MATERIAL'}</span>
          <h2>{file?.name ?? '拖入或选择固定演示资料'}</h2>
          <p id="material-upload-help">{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB · 等待内容哈希校验` : 'PDF · 单文件 · 内容 SHA-256 匹配；按 Enter 或空格选择文件'}</p>
        </button>

        <aside className="material-manifest">
          <div className="manifest-head"><span>唯一上传资料</span><b className="mono">1 FILE ONLY</b></div>
          <h3>《中芯国际 2023 年年度报告》</h3>
          <dl>
            <div><dt>文件名</dt><dd className="mono">smic_2023_annual_report.pdf</dd></div>
            <div><dt>资料类型</dt><dd>年度报告</dd></div>
            <div><dt>证券</dt><dd className="mono">688981.SH</dd></div>
            <div><dt>演示重点</dt><dd>三项失效条件共同触发重大风险候选</dd></div>
            <div><dt>数据来源</dt><dd>官方年报 / Real API / PostgreSQL</dd></div>
          </dl>
          <div className="truth-note">
            <SourceLabel kind="fact" />
            <p>年报原文是事实来源；阈值命中由程序计算；“重大风险”仅为规则候选，必须由负责人显式决策后才改变正式状态。</p>
          </div>
          {error && <div className="inline-error" role="alert"><Icon name="alert" />{error}</div>}
          <button className="button primary wide" disabled={!file || upload.isPending} onClick={() => upload.mutate()}>
            {upload.isPending ? '正在校验并装载…' : '上传这 1 份年报并开始分析'}<Icon name="arrow" />
          </button>
        </aside>
      </section>
      <MobileNav thesisId={id} />
    </div>
  )
}

export function AnalysisReviewPage() {
  const { evidenceId = '' } = useParams()
  const [search] = useSearchParams()
  const thesisId = search.get('thesisId') ?? configuredThesisId
  const relationId = search.get('relationId') ?? ''
  const qc = useQueryClient()
  const [citationOpen, setCitationOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [actionError, setActionError] = useState('')
  const citationTriggerRef = useRef<HTMLButtonElement>(null)
  const citationDrawerRef = useRef<HTMLElement>(null)
  const citationCloseRef = useRef<HTMLButtonElement>(null)
  const query = useQuery({
    queryKey: analysisKey(evidenceId, relationId),
    queryFn: () => scenario.getAnalysis(evidenceId, relationId),
    enabled: Boolean(evidenceId && relationId),
  })
  const statusSuggestions = useQuery({
    queryKey: suggestionsKey(thesisId),
    queryFn: () => scenario.getSuggestions(thesisId),
  })
  const citationQuery = useQuery({
    queryKey: ['demo', 'citation', query.data?.documentId, query.data?.evidenceLocator],
    queryFn: () => scenario.getCitation(query.data!.documentId, query.data!.evidenceLocator),
    enabled: citationOpen && Boolean(query.data?.documentId && query.data?.evidenceLocator),
  })
  const review = useMutation({
    mutationFn: (action: '确认' | '驳回' | '暂不判断') => {
      if (action !== '确认' && !reason.trim()) {
        throw new Error(`${action}时必须填写人工判断依据。`)
      }
      return scenario.reviewRelation(evidenceId, relationId, action, reason)
    },
    onSuccess: async (result) => {
      qc.setQueryData(analysisKey(evidenceId, relationId), result)
      await Promise.all([
        qc.invalidateQueries({ queryKey: thesisKey(thesisId) }),
        qc.invalidateQueries({ queryKey: suggestionsKey(thesisId) }),
        qc.invalidateQueries({ queryKey: timelineKey(thesisId) }),
      ])
      setActionError('')
    },
    onError: (value) => setActionError(value instanceof Error ? value.message : '复核失败'),
  })

  useEffect(() => {
    if (!citationOpen) return
    const trigger = citationTriggerRef.current
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    citationCloseRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        setCitationOpen(false)
        return
      }
      if (event.key !== 'Tab' || !citationDrawerRef.current) return
      const focusable = Array.from(
        citationDrawerRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      )
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
      trigger?.focus()
    }
  }, [citationOpen])

  return (
    <div className="page">
      <PageIntro
        backTo={`/theses/${thesisId}`}
        eyebrow="EVIDENCE ANALYSIS / 证据影响分析"
        title="从来源事实到投资逻辑"
        description="事实、程序计算、AI 候选与人工判断各自保留来源，不在界面上混写为一个结论。"
        aside={<div className="step-number"><span>STEP</span><strong>03—04</strong><small>/ 06</small></div>}
      />
      <QueryState loading={query.isPending} error={query.error} onRetry={() => query.refetch()}>
        {query.data && (
          <>
            <section className="evidence-workbench reveal delay-1">
              <article className="fact-plane">
                <div className="plane-head"><SourceLabel kind="fact" /><span className="mono">{query.data.evidenceLocator}</span></div>
                <blockquote>“{query.data.factExcerpt}”</blockquote>
                <div className="fact-source">
                  <span><small>来源</small><b>{query.data.documentTitle}</b></span>
                  <span><small>披露日</small><b>{query.data.disclosedAt}</b></span>
                  <button
                    ref={citationTriggerRef}
                    className="text-button"
                    onClick={() => setCitationOpen(true)}
                    aria-haspopup="dialog"
                    aria-expanded={citationOpen}
                  ><Icon name="quote" />查看原文上下文</button>
                </div>
              </article>

              <div className="inference-bridge">
                <span>IMPACT MAPPING</span>
                <i />
                <DirectionBadge direction={query.data.direction} />
              </div>

              <article className="ai-plane">
                <div className="plane-head"><SourceLabel kind="ai" /><span className="mono">CONF. {query.data.aiConfidence}</span></div>
                <div className="ai-target">
                  <small>影响既有假设 / {query.data.affectedHypotheses.length || 1}</small>
                  <div className="affected-hypotheses">
                    {(query.data.affectedHypotheses.length
                      ? query.data.affectedHypotheses
                      : [{
                          hypothesisId: query.data.hypothesisId,
                          statement: query.data.hypothesisStatement,
                          metricName: '',
                          actualValue: '',
                          invalidationThreshold: '',
                          direction: query.data.direction,
                        }]
                    ).map((hypothesis, index) => (
                      <div className="affected-hypothesis" key={hypothesis.hypothesisId}>
                        <span className="mono">{String(index + 1).padStart(2, '0')}</span>
                        <div>
                          <h2>{hypothesis.statement}</h2>
                          {hypothesis.metricName && (
                            <p>
                              {hypothesis.metricName}
                              <b>{hypothesis.actualValue}</b>
                              <em>失效阈值 {hypothesis.invalidationThreshold}</em>
                            </p>
                          )}
                          <small className="mono">{hypothesis.hypothesisId}</small>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="ai-judgement">
                  <Metric label="方向" value={query.data.direction === 'support' ? '支持' : query.data.direction === 'conflict' ? '冲突' : '中性'} />
                  <Metric label="强度" value={query.data.strength.toUpperCase()} />
                  <Metric label="置信度" value={query.data.aiConfidence} />
                </div>
                <div className="transmission">
                  <small>传导路径</small>
                  <p>{query.data.transmissionPath}</p>
                </div>
                <div className="model-stamp mono">{query.data.modelVersion} · {query.data.promptVersion}</div>
              </article>
            </section>

            <section className="review-dock reveal delay-2" aria-live="polite">
              <div className="review-context">
                <SourceLabel kind="human" />
                <div><h2>{query.data.relationStatus === 'pending' ? '等待负责人复核' : '本关系已完成复核'}</h2>
                  <p>{query.data.relationStatus === 'pending' ? 'AI 只提出影响候选。确认后才计入假设统计并触发状态建议。' : query.data.reviewReason}</p></div>
              </div>
              {query.data.relationStatus === 'pending' && query.data.canManage ? (
                <div className="review-form">
                  <label className="field-label" htmlFor="review-reason">人工判断依据 <span>确认选填；驳回或暂不判断必填</span></label>
                  <textarea id="review-reason" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="确认可直接提交；其他动作请填写判断依据" aria-describedby={actionError ? 'review-error' : undefined} />
                  {actionError && <span className="form-error" id="review-error" role="alert">{actionError}</span>}
                  <div className="review-actions">
                    <button className="button primary" disabled={review.isPending} onClick={() => review.mutate('确认')}>确认关系</button>
                    <button className="button secondary" disabled={!reason.trim() || review.isPending} onClick={() => review.mutate('驳回')}>驳回</button>
                    <button className="button ghost" disabled={!reason.trim() || review.isPending} onClick={() => review.mutate('暂不判断')}>暂不判断</button>
                  </div>
                </div>
              ) : (
                <div className="review-complete">
                  <Icon name="check" /><span>人工状态</span><strong>{query.data.relationStatus === 'confirmed' ? '已确认' : '已驳回'}</strong>
                  {statusSuggestions.data?.length ? (
                    <ActionLink to={`/theses/${thesisId}/decision`}>处理状态变化建议</ActionLink>
                  ) : (
                    <ActionLink to={`/theses/${thesisId}`}>返回投资逻辑</ActionLink>
                  )}
                </div>
              )}
            </section>
          </>
        )}
      </QueryState>

      {citationOpen && (
        <div className="drawer-backdrop">
          <aside
            ref={citationDrawerRef}
            className="citation-drawer"
            role="dialog"
            aria-modal="true"
            aria-labelledby="citation-title"
          >
            <button ref={citationCloseRef} className="drawer-close" aria-label="关闭原文引用抽屉" onClick={() => setCitationOpen(false)}>关闭 ×</button>
            <SourceLabel kind="fact" />
            <h2 id="citation-title">原文引用上下文</h2>
            <QueryState loading={citationQuery.isPending} error={citationQuery.error} onRetry={() => citationQuery.refetch()}>
              {citationQuery.data && (
                <>
                  <div className="citation-meta"><b>{citationQuery.data.documentTitle}</b><span>第 {citationQuery.data.page} 页 · {citationQuery.data.locator}</span></div>
                  <div className="document-context">
                    <p>{citationQuery.data.previous}</p>
                    <mark>{citationQuery.data.target}</mark>
                    <p>{citationQuery.data.next}</p>
                  </div>
                  {citationQuery.data.sourceUrl && <a className="action-link" href={citationQuery.data.sourceUrl} target="_blank" rel="noopener noreferrer">查看公开来源<Icon name="arrow" /></a>}
                </>
              )}
            </QueryState>
          </aside>
        </div>
      )}
      <MobileNav thesisId={thesisId} />
    </div>
  )
}

export function StatusDecisionPage() {
  const id = useParams().thesisId ?? configuredThesisId
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [action, setAction] = useState<DecisionAction | null>(null)
  const [reason, setReason] = useState('')
  const [targetStatus, setTargetStatus] = useState('')
  const [error, setError] = useState('')
  const thesis = useQuery({ queryKey: thesisKey(id), queryFn: () => scenario.getThesis(id) })
  const suggestions = useQuery({ queryKey: suggestionsKey(id), queryFn: () => scenario.getSuggestions(id) })
  const suggestion = suggestions.data?.[0]
  const decision = useMutation({
    mutationFn: () => {
      if (!suggestion) throw new Error('没有可处置的状态建议。')
      if (!action) throw new Error('请先选择接受、拒绝或修改。')
      if (action !== '接受' && !reason.trim()) throw new Error(`${action}时必须填写负责人决策理由。`)
      if (action === '修改' && !targetStatus) throw new Error('请选择修改后的合法状态。')
      return scenario.decideStatus(id, suggestion.suggestionId, action, reason, targetStatus)
    },
    onSuccess: async (result) => {
      qc.setQueryData(thesisKey(id), result)
      await Promise.all([
        qc.invalidateQueries({ queryKey: suggestionsKey(id) }),
        qc.invalidateQueries({ queryKey: timelineKey(id) }),
      ])
      setError('')
      navigate(`/theses/${id}/timeline`)
    },
    onError: (value) => setError(value instanceof Error ? value.message : '决策提交失败'),
  })

  return (
    <div className="page">
      <PageIntro backTo={`/theses/${id}`} eyebrow="HUMAN GATE / 状态决策" title="重大风险候选到此为止" description="同一份真实年报可触发多项阈值计算，但程序只生成候选；只有逻辑负责人显式选择并填写理由，才能改变正式状态并生成新版本。" aside={<div className="step-number"><span>STEP</span><strong>05</strong><small>/ 06</small></div>} />
      <QueryState loading={thesis.isPending || suggestions.isPending} error={thesis.error || suggestions.error} onRetry={() => { thesis.refetch(); suggestions.refetch() }}>
        {thesis.data && (
          <section className="decision-layout reveal delay-1" aria-live="polite">
            <div className="status-comparison">
              <div className="status-node current"><SourceLabel kind="human" /><small>当前正式状态</small><strong>{thesis.data.status}</strong><span className="mono">VERSION {thesis.data.version}</span></div>
              <div className="status-arrow"><span>规则评估</span><Icon name="arrow" size={28} /></div>
              <div className="status-node suggested"><SourceLabel kind="computed" /><small>程序建议状态</small><strong>{suggestion?.suggestedStatus ?? '无新增建议'}</strong><span className="mono">{suggestion?.ruleVersion ?? 'NO OPEN SIGNAL'}</span></div>
            </div>
            {suggestion ? (
              <div className="decision-panel">
                <div className="decision-reasons">
                  <span className="eyebrow">TRIGGER / 触发依据</span>
                  <div className="decision-boundary">
                    <SourceLabel kind="fact" />
                    <p>事实来源仅为《中芯国际 2023 年年度报告》。</p>
                    <SourceLabel kind="computed" />
                    <p>程序同时命中：营业收入同比 &lt; 0、毛利率 &lt; 25%、产能利用率 &lt; 80%。</p>
                    <SourceLabel kind="human" />
                    <p>接受、拒绝或修改候选均由负责人决定，程序不代替人工结论。</p>
                  </div>
                  {suggestion.reasons.map((item) => <p key={item}><i />{item}</p>)}
                  <small>涉及假设：{suggestion.triggeredHypotheses.join('、')}</small>
                </div>
                <div className="decision-form">
                  <p className="decision-prompt">
                    规则候选为“{suggestion.suggestedStatus}”。接受会将正式状态从“{thesis.data.status}”变为“{suggestion.suggestedStatus}”；拒绝会维持当前状态；修改可选择其他合法状态。
                  </p>
                  <div className="segmented">
                    {(['接受', '拒绝', '修改'] as DecisionAction[]).map((item) => <button key={item} className={action === item ? 'active' : ''} aria-pressed={action === item} onClick={() => setAction(item)}>{item}</button>)}
                  </div>
                  {action === '修改' && <label><span>目标状态</span><select value={targetStatus} onChange={(event) => setTargetStatus(event.target.value)}><option value="" disabled>请选择目标状态</option><option>验证中</option><option>出现分歧</option><option>重大风险</option><option>已关闭</option></select></label>}
                  <label>
                    <span>负责人决策理由 · {action === '接受' ? '选填' : '拒绝或修改时必填'}</span>
                    <textarea value={reason} onChange={(event) => setReason(event.target.value)} placeholder={action === '接受' ? '可直接接受，或补充决策说明' : '请填写拒绝或修改建议的依据'} />
                  </label>
                  {error && <span className="form-error" role="alert">{error}</span>}
                  <button className="button primary wide" disabled={!action || (action !== '接受' && !reason.trim()) || (action === '修改' && !targetStatus) || decision.isPending} onClick={() => decision.mutate()}>提交人工决策并生成版本<Icon name="arrow" /></button>
                </div>
              </div>
            ) : (
              <div className="completed-state"><Icon name="check" size={32} /><h2>状态建议已处置</h2><p>当前没有待处理的程序建议，可以查看完整证据链。</p><ActionLink to={`/theses/${id}/timeline`}>查看完整时间线</ActionLink></div>
            )}
          </section>
        )}
      </QueryState>
      <MobileNav thesisId={id} />
    </div>
  )
}

const dimensionLabels: Record<TimelineDimension, [string, string]> = {
  material: ['资料变化', 'MATERIAL'],
  ai_analysis: ['AI 判断', 'AI ANALYSIS'],
  human_review: ['人工复核', 'HUMAN REVIEW'],
  hypothesis_health: ['假设变化', 'HYPOTHESIS'],
  logic_decision: ['逻辑决策', 'DECISION'],
}

export function TimelinePage() {
  const id = useParams().thesisId ?? configuredThesisId
  const [filter, setFilter] = useState<TimelineDimension | 'all'>('all')
  const query = useQuery({ queryKey: timelineKey(id), queryFn: () => scenario.getTimeline(id) })
  const items = useMemo(() => query.data?.filter((item) => filter === 'all' || item.dimension === filter) ?? [], [query.data, filter])

  return (
    <div className="page">
      <PageIntro backTo={`/theses/${id}`} eyebrow="AUDIT TRAIL / 结构化时间线" title="每一次判断，都能回到证据" description="按服务端业务时间正序串联资料、AI 候选、人工复核、假设变化与逻辑决策。" aside={<div className="step-number"><span>STEP</span><strong>06</strong><small>/ 06</small></div>} />
      <div className="timeline-filters reveal delay-1">
        <button className={filter === 'all' ? 'active' : ''} aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>全部事件</button>
        {(Object.keys(dimensionLabels) as TimelineDimension[]).map((key) => <button key={key} className={filter === key ? 'active' : ''} aria-pressed={filter === key} onClick={() => setFilter(key)}>{dimensionLabels[key][0]}</button>)}
      </div>
      <QueryState loading={query.isPending} error={query.error} onRetry={() => query.refetch()}>
        <section className="timeline reveal delay-2">
          {items.map((item, index) => (
            <article className={`timeline-event dimension-${item.dimension}`} key={item.eventId}>
              <div className="event-index mono">{String(index + 1).padStart(2, '0')}</div>
              <div className="event-marker"><i /></div>
              <div className="event-body">
                <div className="event-top"><span>{dimensionLabels[item.dimension][0]}<small>{dimensionLabels[item.dimension][1]}</small></span><time className="mono">{item.occurredAt}</time></div>
                <h2>{item.summary}</h2>
                <div className="event-actor"><span className={`actor actor-${item.actorType}`}>{item.actorType === 'preset_ai' ? 'AI' : item.actorType === 'system' ? 'ƒ' : 'H'}</span>{item.actorName}{item.reason && <p>“{item.reason}”</p>}</div>
                {(item.before || item.after) && <div className="change-set">{item.before && <div><small>BEFORE</small>{Object.entries(item.before).map(([key, value]) => <span key={key}>{key}<b>{value}</b></span>)}</div>}{item.after && <div><small>AFTER</small>{Object.entries(item.after).map(([key, value]) => <span key={key}>{key}<b>{value}</b></span>)}</div>}</div>}
                {item.detailUrl && <Link className="event-link" to={item.detailUrl}>查看关联对象<Icon name="arrow" /></Link>}
              </div>
            </article>
          ))}
          {!items.length && <div className="completed-state"><Icon name="clock" /><h2>暂无该维度事件</h2><p>完成对应业务动作后，真实事件会出现在这里。</p></div>}
        </section>
      </QueryState>
      <MobileNav thesisId={id} />
    </div>
  )
}

export function NotFoundPage() {
  return <div className="page not-found"><span className="mono">404 / UNRESOLVED NODE</span><h1>这条证据链不存在</h1><p>对象不存在或当前身份无权访问。系统不会透露未授权对象信息。</p><ActionLink to={`/theses/${configuredThesisId}`}>返回固定投资逻辑</ActionLink></div>
}
