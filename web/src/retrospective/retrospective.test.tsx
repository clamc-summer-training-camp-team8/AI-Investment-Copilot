import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import {
  getRetrospective,
  getRetrospectiveOverview,
  listRetrospectives,
  saveRetrospectiveDraft,
} from './api'
import { RetrospectiveCenterPage, RetrospectiveEditorPage } from './index'
import type { RetrospectiveDetail, RetrospectiveRecord } from './types'

vi.mock('../api', () => ({ listTheses: vi.fn().mockResolvedValue([]) }))
vi.mock('./api', () => ({
  archiveRetrospective: vi.fn(), createRetrospective: vi.fn(), exportRetrospective: vi.fn(),
  generateRetrospectiveAiDraft: vi.fn(), getRetrospective: vi.fn(),
  getRetrospectiveOverview: vi.fn(), getRetrospectiveTimeline: vi.fn(),
  listRetrospectives: vi.fn(), previewRetrospectiveSources: vi.fn(),
  publishRetrospective: vi.fn(), returnRetrospective: vi.fn(), reviseRetrospective: vi.fn(),
  saveRetrospectiveDraft: vi.fn(), submitRetrospective: vi.fn(),
}))

const report: RetrospectiveRecord = {
  retrospective_id: 'RTP-1', thesis_id: 'THS-1', thesis_title: '新能源周期',
  security_id: '0175.HK', retrospective_type: '周期', title: '真实复盘报告',
  period_start: '2026-01-01', period_end: '2026-06-30',
  data_cutoff_at: '2026-06-30T15:59:00Z', owner: 'analyst', state: '草稿',
  visibility: '团队', team: 'alpha', source_fingerprint: 'a'.repeat(64), source_count: 1,
  completeness_completed: 3, completeness_applicable: 3, completeness_score: 1,
  current_version: 0, lock_version: 1, ai_status: '未生成',
  hypothesis_result_counts: { 证据不足: 1 }, strong_conflicts_handled: 0,
  strong_conflicts_total: 0,
}

const detail: RetrospectiveDetail = {
  retrospective: report,
  content: {
    summary: '服务端原草稿', original_judgement: '原判断', errors_and_omissions: '',
    conflict_resolution: '', source_gaps_acknowledgement: '无缺口', limitations: '',
    next_actions: '', citations: [], hypothesis_assessments: [{
      hypothesis_id: 'H1', statement: '销量持续增长', result: '证据不足',
      rationale: '', source_ids: [],
    }],
  },
  sources: [], versions: [], allowed_actions: ['view', 'edit', 'submit', 'publish'],
}

function wrapper(route: string, element: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[route]}><Routes><Route path="*" element={element} /></Routes></MemoryRouter></QueryClientProvider>)
}

afterEach(cleanup)

beforeEach(() => {
  vi.mocked(getRetrospectiveOverview).mockResolvedValue({
    total: 1, state_counts: { 草稿: 1 }, logic_changes: 1, validated_hypotheses: 0,
    pending_hypotheses: 1, strong_conflicts_handled: 0, strong_conflicts_total: 0,
    average_completeness: 1, pending_reports: 1, is_truncated: false, definitions: {},
  })
  vi.mocked(listRetrospectives).mockResolvedValue({ items: [report], total: 1, limit: 20, offset: 0 })
  vi.mocked(getRetrospective).mockResolvedValue(detail)
})

describe('retrospective P0 pages', () => {
  it('renders the API-backed overview and report directory', async () => {
    wrapper('/retrospective?state=草稿', <RetrospectiveCenterPage />)
    expect(await screen.findByRole('link', { name: '真实复盘报告' })).toBeInTheDocument()
    expect(screen.getByText('待完成复盘')).toBeInTheDocument()
    expect(screen.getByRole('complementary', { name: '复盘工作区' })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /返回工作台/ })[0]).toHaveAttribute('href', '/workbench')
    expect(screen.getByRole('link', { name: /工作台定位现行逻辑/ })).toHaveAttribute('href', '/workbench')
    expect(vi.mocked(listRetrospectives).mock.calls[0][0].get('state')).toBe('草稿')
    expect(screen.queryByText('经验已确认并沉淀')).not.toBeInTheDocument()
  })

  it('keeps local draft text when an optimistic-lock save fails', async () => {
    vi.mocked(saveRetrospectiveDraft).mockRejectedValue(new Error('复盘已被其他操作更新，请刷新后重试'))
    wrapper('/retrospective/RTP-1/edit', <RetrospectiveEditorPage />)
    const textboxes = await screen.findAllByRole('textbox')
    const summary = textboxes[1]
    fireEvent.change(summary, { target: { value: '本地尚未提交的修改' } })
    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }))
    expect(await screen.findByText('复盘已被其他操作更新，请刷新后重试')).toBeInTheDocument()
    expect(summary).toHaveValue('本地尚未提交的修改')
    expect(saveRetrospectiveDraft).toHaveBeenCalledTimes(1)
  })
})
