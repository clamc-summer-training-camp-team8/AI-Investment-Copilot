import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { listDataCenterDocuments } from '../api'
import { DataCenterDocumentsPage, DataCenterLayout } from './index'

vi.mock('../api', () => ({
  deleteDataCenterDocument: vi.fn(),
  fetchDataCenterContent: vi.fn(),
  getDataCenterDocument: vi.fn(),
  getDataCenterOverview: vi.fn(),
  getDocumentSegment: vi.fn(),
  getMarketDatasetDetail: vi.fn(),
  getQuantCatalog: vi.fn(),
  listDataCenterDocuments: vi.fn(),
  listDataCenterRuns: vi.fn(),
  listDataCenterSources: vi.fn(),
  rebuildAssetSearchIndex: vi.fn(),
  reprocessDataCenterDocument: vi.fn(),
  restoreDataCenterDocument: vi.fn(),
  updateDataCenterVisibility: vi.fn(),
}))

function renderRoute(route: string, element: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[route]}>{element}</MemoryRouter></QueryClientProvider>)
}

afterEach(cleanup)

beforeEach(() => {
  vi.mocked(listDataCenterDocuments).mockResolvedValue({
    items: [{
      documentId: 'DOC-1', title: '北方华创经营更新公告', sourceName: '公开披露', docType: '公告',
      publishedAt: '2026-08-31T09:00:00Z', ingestedAt: '2026-08-31T09:05:00Z', contentStatus: '完整正文',
      visibilityLabel: '内部', isIllustrative: false, archived: true, authorizationStatus: '公开披露已核验',
      revisionCount: 1, segmentCount: 18, latestRunStatus: 'succeeded', securityIds: ['002371'],
      securityNames: ['北方华创'], industries: ['半导体设备'],
    }],
    total: 1, limit: 20, offset: 0,
  })
})

describe('data center and workbench handoff', () => {
  it('shows the workbench origin and keeps the upload action available', () => {
    const onUpload = vi.fn()
    renderRoute('/assets?from=workbench', <Routes><Route path="/assets" element={<DataCenterLayout onUpload={onUpload} />}><Route index element={<div>总览内容</div>} /></Route></Routes>)

    expect(screen.getByText('来自工作台')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '← 返回工作台' })).toHaveAttribute('href', '/workbench')
    fireEvent.click(screen.getByRole('button', { name: '＋ 上传研究资料' }))
    expect(onUpload).toHaveBeenCalledTimes(1)
  })

  it('keeps UI origin parameters out of the API and preserves the return path on detail links', async () => {
    renderRoute('/assets/documents?security_id=002371&from=workbench', <Routes><Route path="/assets/documents" element={<DataCenterDocumentsPage />} /></Routes>)

    const documentLink = await screen.findByRole('link', { name: '北方华创经营更新公告' })
    const request = vi.mocked(listDataCenterDocuments).mock.calls[0][0]
    expect(request.get('security_id')).toBe('002371')
    expect(request.has('from')).toBe(false)
    expect(documentLink).toHaveAttribute('href', '/assets/documents/DOC-1?from=workbench')
  })
})
