import type { ConfirmationState, Direction, Priority } from './types'

export const directionText: Record<Direction, string> = { support: '支持', conflict: '冲突', neutral: '中性' }
export const stateText: Record<ConfirmationState, string> = { pending: '待确认', confirmed: '已确认', rejected: '已驳回', deactivated: '已解除' }
export const priorityText: Record<Priority, string> = { high: '高优先级', medium: '中优先级', low: '低优先级' }
export const strengthText = { high: '高', medium: '中', low: '低' } as const

export function formatDate(value?: string): string {
  if (!value) return '未设置'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(date).replaceAll('/', '-')
}
