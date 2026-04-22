export type LoadingLogLocale = 'zh' | 'en'

export type LoadingUiEvent =
  | { type: 'progress'; percent: number; status?: string }
  | { type: 'step'; name: string; status: string; description?: string }
  | { type: 'log'; message: string }
  | { type: 'done'; resultId?: string }
  | { type: 'error'; message: string }

export type LoadingLogFormatOptions = {
  locale?: LoadingLogLocale
  useEmoji?: boolean
}

const ZH = {
  connecting: '正在连接生成服务',
  strategy: '正在生成搜索策略',
  generation: '正在生成行程初稿',
  reflection: '正在进行反思优化',
  normalizing: '正在规范化与校验结果',
  saving: '正在保存结果',
  done: '已完成，正在跳转',
  cancelled: '已取消生成',
} as const

function clampPercent(p: number): number {
  if (!Number.isFinite(p)) return 0
  return Math.max(0, Math.min(100, Math.round(p)))
}

function pickPrefix(useEmoji: boolean, kind: 'ok' | 'run' | 'warn'): string {
  if (!useEmoji) return ''
  if (kind === 'ok') return '✅ '
  if (kind === 'warn') return '⚠️ '
  return '⏳ '
}

export function formatLoadingLog(event: LoadingUiEvent, opts: LoadingLogFormatOptions = {}): string | null {
  const locale: LoadingLogLocale = opts.locale ?? 'zh'
  const useEmoji = Boolean(opts.useEmoji)

  if (locale !== 'zh') {
    // 当前仅实现中文：保持一致性，后续可扩展
    return null
  }

  if (event.type === 'progress') {
    const p = clampPercent(event.percent)
    if (p <= 5) return `${pickPrefix(useEmoji, 'run')}${ZH.connecting}`
    if (p >= 98) return `${pickPrefix(useEmoji, 'ok')}${ZH.done}`
    if (event.status) return `${pickPrefix(useEmoji, 'run')}${event.status}`
    return null
  }

  if (event.type === 'step') {
    const name = String(event.name || '').toLowerCase()
    const status = String(event.status || '').toLowerCase()

    if (name === 'strategy' && status === 'running') return `${pickPrefix(useEmoji, 'run')}${ZH.strategy}`
    if (name === 'generation' && status === 'running') return `${pickPrefix(useEmoji, 'run')}${ZH.generation}`
    if (name === 'reflection' && status === 'running') return `${pickPrefix(useEmoji, 'run')}${ZH.reflection}`

    if (status === 'completed' || status === 'done') {
      return `${pickPrefix(useEmoji, 'ok')}${event.description || '阶段完成'}`
    }
    if (status === 'fallback' || status === 'skipped') {
      return `${pickPrefix(useEmoji, 'warn')}${event.description || '已使用兜底流程'}`
    }
    if (status === 'error' || status === 'failed') {
      return `${pickPrefix(useEmoji, 'warn')}${event.description || '阶段失败'}`
    }
    return null
  }

  if (event.type === 'done') return `${pickPrefix(useEmoji, 'ok')}${ZH.done}`
  if (event.type === 'error') return `${pickPrefix(useEmoji, 'warn')}${event.message}`

  if (event.type === 'log') {
    const msg = String(event.message || '').trim()
    if (!msg) return null
    if (msg.includes('llm') || msg.includes('prompt') || msg.includes('thought')) return null
    return msg
  }

  return null
}

