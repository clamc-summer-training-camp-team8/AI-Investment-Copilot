import type { ConfirmationState, EvidenceFeedItem } from './types'

export type CompanyEvidenceDirection = EvidenceFeedItem['direction'] | 'mixed'

export type ConfirmedHypothesisEvidenceState = {
  label: '支持' | '冲突' | '证据分歧' | '中性' | '待验证'
  tone: 'support' | 'conflict' | 'mixed' | 'neutral' | 'pending'
}

export interface CompanyEvidenceCard {
  documentKey: string
  evidenceId: string
  relationId: string
  title: string
  summary: string
  disclosedAt: string
  ingestedAt: string
  sourceUrl: string
  direction: CompanyEvidenceDirection
  confirmationStatus: ConfirmationState
  evidenceCount: number
  aiConfidence: number
}

function documentKey(item: EvidenceFeedItem) {
  const documentId = item.sourceDocumentId.trim()
  if (documentId) return documentId
  const sourceUrl = item.sourceUrl.trim().toLowerCase()
  if (sourceUrl) return sourceUrl
  return `${item.sourceDocumentTitle.trim().toLowerCase()}::${item.disclosedAt.slice(0, 10)}`
}

function timestamp(item: EvidenceFeedItem) {
  return Date.parse(item.ingestedAt || item.disclosedAt) || 0
}

export function getConfirmedHypothesisEvidenceState(items: EvidenceFeedItem[], hypothesisId: string): ConfirmedHypothesisEvidenceState {
  const directions = new Set(items
    .filter((item) => item.hypothesisId === hypothesisId && item.confirmationStatus === 'confirmed')
    .map((item) => item.direction))
  if (directions.has('support') && directions.has('conflict')) return { label: '证据分歧', tone: 'mixed' }
  if (directions.has('support')) return { label: '支持', tone: 'support' }
  if (directions.has('conflict')) return { label: '冲突', tone: 'conflict' }
  if (directions.has('neutral')) return { label: '中性', tone: 'neutral' }
  return { label: '待验证', tone: 'pending' }
}

export function buildCompanyEvidenceCards(items: EvidenceFeedItem[], hypothesisId: string): CompanyEvidenceCard[] {
  const groups = new Map<string, EvidenceFeedItem[]>()
  for (const item of items) {
    if (item.hypothesisId !== hypothesisId || item.confirmationStatus === 'deactivated') continue
    const key = documentKey(item)
    groups.set(key, [...(groups.get(key) ?? []), item])
  }

  return [...groups.entries()]
    // 资料卡是“资料级”审核单元：只要同一资料下仍有一条事实未确认，
    // 就不在“已确认资料证据”区域展示，避免部分确认被误读为整份资料已确认。
    .filter(([, group]) => group.every((item) => item.confirmationStatus === 'confirmed'))
    .map(([key, group]) => {
      const ordered = [...group].sort((left, right) => timestamp(right) - timestamp(left))
      const primary = ordered[0]
      const directions = new Set(group.map((item) => item.direction))
      const direction: CompanyEvidenceDirection = directions.has('support') && directions.has('conflict')
        ? 'mixed'
        : directions.has('conflict')
          ? 'conflict'
          : directions.has('support')
            ? 'support'
            : 'neutral'
      const confirmationStatus: ConfirmationState = group.some((item) => item.confirmationStatus === 'pending')
        ? 'pending'
        : group.some((item) => item.confirmationStatus === 'confirmed')
          ? 'confirmed'
          : primary.confirmationStatus
      const excerpts = [...new Set(group.map((item) => item.factExcerpt.trim()).filter(Boolean))]
      const summary = primary.aggregationSummary
        ?? `${excerpts[0] || '该资料已关联当前假设，事实摘要待补充。'}${excerpts.length > 1 ? `（另含 ${excerpts.length - 1} 条关联事实）` : ''}`

      return {
        documentKey: key,
        evidenceId: primary.evidenceId,
        relationId: primary.relationId,
        title: primary.sourceDocumentTitle,
        summary,
        disclosedAt: primary.disclosedAt,
        ingestedAt: primary.ingestedAt,
        sourceUrl: primary.sourceUrl,
        direction,
        confirmationStatus,
        evidenceCount: new Set(group.map((item) => item.evidenceId)).size,
        aiConfidence: Math.max(...group.map((item) => item.aiConfidence)),
      }
    }).sort((left, right) => Date.parse(right.ingestedAt || right.disclosedAt) - Date.parse(left.ingestedAt || left.disclosedAt))
}
