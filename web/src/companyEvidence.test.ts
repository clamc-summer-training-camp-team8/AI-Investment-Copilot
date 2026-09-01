import { describe, expect, it } from 'vitest'

import { buildCompanyEvidenceCards, getConfirmedHypothesisEvidenceState } from './companyEvidence'
import type { EvidenceFeedItem } from './types'

function evidence(overrides: Partial<EvidenceFeedItem>): EvidenceFeedItem {
  return {
    evidenceId: 'EVD-1', relationId: 'REL-1', securityId: '300274', securityName: '阳光电源',
    thesisId: 'THS-1', thesisTitle: '盈利改善', thesisCoreView: '盈利能力持续改善',
    hypothesisId: 'HYP-1', hypothesisStatement: '海外毛利率持续改善', sourceDocumentId: 'DOC-1',
    sourceDocumentTitle: '年度报告', factExcerpt: '海外毛利率有所改善。', disclosedAt: '2026-08-30T10:00:00+08:00',
    ingestedAt: '2026-08-30T10:05:00+08:00', sourceUrl: 'https://example.com/report', direction: 'support',
    strength: 'medium', aiConfidence: .8, confirmationStatus: 'pending', priority: 'medium', canManage: true,
    validationItems: [], atomicEvidenceCount: 1, sourceDocumentCount: 1, supportEvidenceCount: 1,
    conflictEvidenceCount: 0, affectedHypothesisCount: 1, secondaryHypotheses: [], themeImpacts: [],
    ...overrides,
  }
}

describe('buildCompanyEvidenceCards', () => {
  it('同一资料在同一假设下只生成一张卡片，并合并方向和证据数', () => {
    const cards = buildCompanyEvidenceCards([
      evidence({ evidenceId: 'EVD-1', direction: 'support', confirmationStatus: 'confirmed' }),
      evidence({ evidenceId: 'EVD-2', relationId: 'REL-2', direction: 'conflict', factExcerpt: '价格竞争带来压力。', confirmationStatus: 'confirmed' }),
      evidence({ evidenceId: 'EVD-3', relationId: 'REL-3', hypothesisId: 'HYP-2', confirmationStatus: 'confirmed' }),
    ], 'HYP-1')

    expect(cards).toHaveLength(1)
    expect(cards[0]).toMatchObject({ documentKey: 'DOC-1', direction: 'mixed', evidenceCount: 2 })
    expect(cards[0].summary).toContain('另含 1 条关联事实')
  })

  it('资料 ID 缺失时以资料链接作为去重键', () => {
    const cards = buildCompanyEvidenceCards([
      evidence({ sourceDocumentId: '', evidenceId: 'EVD-1', confirmationStatus: 'confirmed' }),
      evidence({ sourceDocumentId: '', evidenceId: 'EVD-2', relationId: 'REL-2', confirmationStatus: 'confirmed' }),
    ], 'HYP-1')

    expect(cards).toHaveLength(1)
    expect(cards[0].documentKey).toBe('https://example.com/report')
  })

  it('同一资料下仍有未确认事实时不展示整张资料卡', () => {
    const cards = buildCompanyEvidenceCards([
      evidence({ confirmationStatus: 'confirmed' }),
      evidence({ evidenceId: 'EVD-2', relationId: 'REL-2', confirmationStatus: 'pending' }),
    ], 'HYP-1')

    expect(cards).toHaveLength(0)
  })
})

describe('getConfirmedHypothesisEvidenceState', () => {
  it('只使用已确认的证据，并区分支持、冲突、分歧、中性和待验证', () => {
    expect(getConfirmedHypothesisEvidenceState([
      evidence({ confirmationStatus: 'confirmed', direction: 'support' }),
      evidence({ evidenceId: 'EVD-2', confirmationStatus: 'pending', direction: 'conflict' }),
    ], 'HYP-1')).toEqual({ label: '支持', tone: 'support' })
    expect(getConfirmedHypothesisEvidenceState([
      evidence({ confirmationStatus: 'confirmed', direction: 'support' }),
      evidence({ evidenceId: 'EVD-2', confirmationStatus: 'confirmed', direction: 'conflict' }),
    ], 'HYP-1')).toEqual({ label: '证据分歧', tone: 'mixed' })
    expect(getConfirmedHypothesisEvidenceState([
      evidence({ confirmationStatus: 'confirmed', direction: 'conflict' }),
    ], 'HYP-1')).toEqual({ label: '冲突', tone: 'conflict' })
    expect(getConfirmedHypothesisEvidenceState([
      evidence({ confirmationStatus: 'confirmed', direction: 'neutral' }),
    ], 'HYP-1')).toEqual({ label: '中性', tone: 'neutral' })
    expect(getConfirmedHypothesisEvidenceState([], 'HYP-1')).toEqual({ label: '待验证', tone: 'pending' })
  })
})
