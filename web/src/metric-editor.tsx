import type { ReactNode } from 'react'

type Observation = { period?: unknown; value?: unknown }

export function MetricTrend({ observations, unit = '', latestPeriod }: { observations?: Observation[]; unit?: string; latestPeriod?: string }) {
  const points = (observations ?? []).map((item) => ({ period: String(item.period ?? ''), value: Number(item.value) })).filter((item) => Number.isFinite(item.value))
  if (!points.length) return <div className="metric-trend-empty">暂无历史观测</div>
  const values = points.map((point) => point.value)
  const min = Math.min(...values)
  const range = Math.max(...values) - min || 1
  const coords = points.map((point, index) => `${(index / Math.max(points.length - 1, 1)) * 160},${35 - ((point.value - min) / range) * 30}`).join(' ')
  const latest = points.at(-1)!
  const previous = points.at(-2)
  const change = previous && previous.value !== 0 ? ((latest.value - previous.value) / Math.abs(previous.value)) * 100 : null
  const formatted = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(latest.value)
  return <div className="metric-trend"><div><span>最新值</span><strong>{formatted}{unit && unit !== '未标注' ? ` ${unit}` : ''}</strong><small>{latest.period || latestPeriod || '最近一期'}</small></div><svg viewBox="0 0 160 40" preserveAspectRatio="none" aria-label="指标近期波动"><polyline points={coords} /></svg><b className={change == null ? '' : change >= 0 ? 'trend-up' : 'trend-down'}>{change == null ? '暂无环比' : `较上期 ${change >= 0 ? '+' : ''}${change.toFixed(2)}%`}</b></div>
}

export function MetricEditorCard({
  selected,
  name,
  metricId,
  meta,
  tag,
  description,
  observations,
  unit,
  latestPeriod,
  expanded = false,
  disabled = false,
  onToggleSelected,
  onToggleExpanded,
  children,
}: {
  selected: boolean
  name: string
  metricId: string
  meta?: string
  tag?: string
  description: string
  observations?: Observation[]
  unit?: string
  latestPeriod?: string
  expanded?: boolean
  disabled?: boolean
  onToggleSelected: () => void
  onToggleExpanded?: () => void
  children?: ReactNode
}) {
  return <div className={`metric-candidate ${selected ? 'selected' : ''}`}>
    <div className="metric-candidate-head">
      <button type="button" className="metric-select-button" disabled={disabled} aria-pressed={selected} onClick={onToggleSelected}><span aria-hidden>{selected ? '×' : '＋'}</span><small>{selected ? '移除' : '加入'}</small></button>
      <div><strong>{name}</strong><span>{metricId || '待匹配指标 ID'}{meta ? ` · ${meta}` : ''}</span></div>
      <em>{tag || (selected ? '已关联' : '候选指标')}</em>
    </div>
    <p>{description}</p>
    <MetricTrend observations={observations} unit={unit} latestPeriod={latestPeriod} />
    {selected && children && <><button type="button" className="metric-detail-toggle" onClick={onToggleExpanded}>{expanded ? '收起判断配置 ︿' : '展开判断配置 ﹀'}</button>{expanded && children}</>}
  </div>
}
