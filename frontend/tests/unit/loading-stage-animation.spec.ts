import { describe, expect, it } from 'vitest'
import {
  deriveStageFromProgress,
  deriveStageFromStep,
  resolveStageMeta,
} from '@/utils/loading-stage-animation'

describe('loading-stage-animation', () => {
  it('maps progress to stage', () => {
    expect(deriveStageFromProgress(2)).toBe('connecting')
    expect(deriveStageFromProgress(30)).toBe('generation')
    expect(deriveStageFromProgress(90)).toBe('normalizing')
    expect(deriveStageFromProgress(100)).toBe('done')
  })

  it('maps step name to stage', () => {
    expect(deriveStageFromStep('strategy', 'running')).toBe('strategy')
    expect(deriveStageFromStep('generation', 'running')).toBe('generation')
    expect(deriveStageFromStep('reflection', 'running')).toBe('reflection')
  })

  it('resolves stage meta', () => {
    const meta = resolveStageMeta('saving')
    expect(meta.label).toBe('保存结果')
    expect(meta.motion).toBe('flow')
  })
})

