export type LoadingStageKey =
  | 'connecting'
  | 'strategy'
  | 'generation'
  | 'reflection'
  | 'normalizing'
  | 'saving'
  | 'done'
  | 'cancelled'

export type LoadingStageMeta = {
  key: LoadingStageKey
  icon: string
  label: string
  motion: 'pulse' | 'flow' | 'scan' | 'spark' | 'calm'
  durationMs: number
}

const STAGE_META: Record<LoadingStageKey, LoadingStageMeta> = {
  connecting: { key: 'connecting', icon: '🌐', label: '连接服务', motion: 'scan', durationMs: 560 },
  strategy: { key: 'strategy', icon: '🧭', label: '生成策略', motion: 'flow', durationMs: 560 },
  generation: { key: 'generation', icon: '🧩', label: '生成初稿', motion: 'pulse', durationMs: 560 },
  reflection: { key: 'reflection', icon: '🔍', label: '反思优化', motion: 'spark', durationMs: 560 },
  normalizing: { key: 'normalizing', icon: '🧼', label: '规范化', motion: 'scan', durationMs: 540 },
  saving: { key: 'saving', icon: '💾', label: '保存结果', motion: 'flow', durationMs: 540 },
  done: { key: 'done', icon: '✅', label: '完成', motion: 'calm', durationMs: 480 },
  cancelled: { key: 'cancelled', icon: '🛑', label: '已取消', motion: 'calm', durationMs: 420 },
}

export function resolveStageMeta(stage: string | undefined | null): LoadingStageMeta {
  if (!stage) return STAGE_META.connecting
  const key = String(stage).toLowerCase() as LoadingStageKey
  return STAGE_META[key] || STAGE_META.connecting
}

export function deriveStageFromStep(stepName: string, _status: string): LoadingStageKey {
  const name = String(stepName || '').toLowerCase()
  if (name.includes('strategy')) return 'strategy'
  if (name.includes('reflection')) return 'reflection'
  if (name.includes('generation') || name.includes('draft')) return 'generation'
  return 'generation'
}

export function deriveStageFromProgress(percent: number): LoadingStageKey {
  const p = Number.isFinite(percent) ? percent : 0
  if (p >= 100) return 'done'
  if (p >= 95) return 'saving'
  if (p >= 85) return 'normalizing'
  if (p >= 60) return 'reflection'
  if (p >= 25) return 'generation'
  if (p >= 8) return 'strategy'
  return 'connecting'
}

