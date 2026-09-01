import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { getInvestodayCollectionStatus, getResearchUpdates, listSecurities, listTheses } from './api'
import { WorkbenchPage } from './pages'
import { getRetrospectiveOverview } from './retrospective/api'

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()
  return {
    ...actual,
    getInvestodayCollectionStatus: vi.fn(),
    getResearchUpdates: vi.fn(),
    listSecurities: vi.fn(),
    listTheses: vi.fn(),
  }
})

vi.mock('./retrospective/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./retrospective/api')>()
  return { ...actual, getRetrospectiveOverview: vi.fn() }
})

function renderWorkbench() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter><WorkbenchPage retrospectiveEnabled quantEnabled /></MemoryRouter></QueryClientProvider>)
}

afterEach(cleanup)

beforeEach(() => {
  vi.mocked(listTheses).mockResolvedValue([{
    thesisId: 'THS-1', securityId: '000001', title: '盈利质量持续改善', status: '验证中',
    hypotheses: [{ hypothesisId: 'H-1', importance: '核心', mappings: [] }],
  }] as unknown as Awaited<ReturnType<typeof listTheses>>)
  vi.mocked(listSecurities).mockResolvedValue([{
    securityId: '000001', name: '示例公司', industry: '先进制造',
  }] as Awaited<ReturnType<typeof listSecurities>>)
  vi.mocked(getResearchUpdates).mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 })
  vi.mocked(getInvestodayCollectionStatus).mockResolvedValue({
    businessDate: '2026-09-01', workerReady: true, overallStatus: 'completed',
    news: { kind: 'news', status: 'completed', businessDate: '2026-09-01', isCurrent: true },
    reports: { kind: 'report', status: 'completed', businessDate: '2026-09-01', isCurrent: true },
  })
  vi.mocked(getRetrospectiveOverview).mockResolvedValue({
    total: 7, state_counts: { 草稿: 2, 待评审: 1, 已发布: 4 }, logic_changes: 5,
    validated_hypotheses: 6, pending_hypotheses: 2, strong_conflicts_handled: 1,
    strong_conflicts_total: 1, average_completeness: 0.8, pending_reports: 3,
    is_truncated: false, definitions: {},
  })
})

describe('workbench retrospective handoff', () => {
  it('shows live retrospective progress and starts from the selected thesis', async () => {
    renderWorkbench()

    expect(await screen.findByRole('heading', { name: '复盘进度' })).toBeInTheDocument()
    expect(screen.getByText('份待完成复盘')).toBeInTheDocument()
    expect(screen.getByText('80% 平均完整度')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '发起复盘' })).toHaveAttribute('href', '/retrospective/new?thesisId=THS-1')
    expect(screen.getByRole('link', { name: '进入中心 ›' })).toHaveAttribute('href', '/retrospective')
    expect(screen.getByRole('link', { name: /模型与因子/ })).toHaveAttribute('href', '/quant')
    expect(getRetrospectiveOverview).toHaveBeenCalledTimes(1)
  })
})
