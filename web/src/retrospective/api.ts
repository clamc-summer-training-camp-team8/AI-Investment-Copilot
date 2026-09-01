import { request, requestBlob } from '../api'
import type {
  AiDraftResult,
  RetrospectiveContent,
  RetrospectiveDetail,
  RetrospectiveOverview,
  RetrospectivePage,
  RetrospectiveRecord,
  SourcePreview,
  TimelineItem,
} from './types'

export interface CreateInput {
  thesis_id: string
  retrospective_type: string
  title: string
  period_start: string
  period_end: string
  data_cutoff_at: string
  reviewer?: string
}

export const getRetrospectiveOverview = () => request<RetrospectiveOverview>('/api/retrospectives/overview')

export const listRetrospectives = (params: URLSearchParams) =>
  request<RetrospectivePage>(`/api/retrospectives?${params.toString()}`)

export const previewRetrospectiveSources = (payload: Omit<CreateInput, 'retrospective_type' | 'title' | 'reviewer'>) =>
  request<SourcePreview>('/api/retrospectives/source-preview', { method: 'POST', body: JSON.stringify(payload) })

export const createRetrospective = (payload: CreateInput) =>
  request<RetrospectiveRecord>('/api/retrospectives', { method: 'POST', body: JSON.stringify(payload) })

export const getRetrospective = (id: string) =>
  request<RetrospectiveDetail>(`/api/retrospectives/${encodeURIComponent(id)}`)

export const getRetrospectiveTimeline = (id: string) =>
  request<TimelineItem[]>(`/api/retrospectives/${encodeURIComponent(id)}/timeline`)

export const saveRetrospectiveDraft = (id: string, content: RetrospectiveContent, lockVersion: number, title?: string) =>
  request<RetrospectiveRecord>(`/api/retrospectives/${encodeURIComponent(id)}/draft`, {
    method: 'PATCH', body: JSON.stringify({ content, lock_version: lockVersion, title }),
  })

export const generateRetrospectiveAiDraft = (id: string, lockVersion: number) =>
  request<AiDraftResult>(`/api/retrospectives/${encodeURIComponent(id)}/ai-drafts`, {
    method: 'POST', body: JSON.stringify({ lock_version: lockVersion }),
  })

const action = (id: string, name: string, body: Record<string, unknown>) =>
  request<RetrospectiveRecord>(`/api/retrospectives/${encodeURIComponent(id)}/${name}`, {
    method: 'POST', body: JSON.stringify(body),
  })

export const submitRetrospective = (id: string, reviewer: string, lockVersion: number) => action(id, 'submit', { reviewer, lock_version: lockVersion })
export const returnRetrospective = (id: string, reason: string, lockVersion: number) => action(id, 'return', { reason, lock_version: lockVersion })
export const publishRetrospective = (id: string, publishReason: string, lockVersion: number) => action(id, 'publish', { publish_reason: publishReason, lock_version: lockVersion })
export const reviseRetrospective = (id: string, reason: string, lockVersion: number) => action(id, 'revisions', { reason, lock_version: lockVersion })
export const archiveRetrospective = (id: string, reason: string, lockVersion: number) => action(id, 'archive', { reason, lock_version: lockVersion })

export async function exportRetrospective(id: string, format: 'markdown' | 'json') {
  const blob = await requestBlob(`/api/retrospectives/${encodeURIComponent(id)}/exports/${format}`)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `${id}.${format === 'markdown' ? 'md' : 'json'}`
  link.click()
  URL.revokeObjectURL(url)
}
