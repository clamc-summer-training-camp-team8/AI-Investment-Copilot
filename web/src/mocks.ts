import type { EvidenceDetail, ThesisDetail } from './types'

export const demoEvidence: EvidenceDetail = {
  evidenceId: 'EVD-SG-001',
  securityId: '300274',
  factExcerpt: '公司披露的公开资料显示，储能业务保持增长，海外市场需求仍是后续经营的重要观察变量。',
  sourceDocumentTitle: '阳光电源公开披露资料',
  disclosedAt: '2026-08-01',
  sourceUrl: 'https://www.cninfo.com.cn/',
  direction: 'support',
  strength: 'medium',
  aiConfidence: 0.82,
  aiStatus: '候选',
  modelVersion: 'mvp-rag-0.1',
  promptVersion: 'demo-v1',
  confirmationStatus: 'pending',
  sourceDocumentId: 'DOC-SG-001',
  evidenceLocator: 'DOC-SG-001#paragraph-1',
}

export const demoThesis: ThesisDetail = {
  thesisId: 'THS-SG-001',
  securityId: '300274',
  title: '阳光电源：储能出海驱动盈利改善',
  owner: 'analyst-mvp',
  status: '验证中',
  direction: '观察',
  coreView: '储能与海外需求是经营增长的主要观察变量。',
  version: 1,
  establishedOn: '2026-01-01',
  hypotheses: [],
}
