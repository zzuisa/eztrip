import { describe, expect, it } from 'vitest'
import { getPosterTransitionPreset } from '@/utils/poster-transition-presets'

describe('poster-transition-presets', () => {
  it('returns high tier preset', () => {
    const preset = getPosterTransitionPreset('high')
    expect(preset.durationMs).toBeGreaterThan(700)
    expect(preset.kenBurnsScale).toBeGreaterThan(1)
  })

  it('downgrades to reduced motion preset', () => {
    const preset = getPosterTransitionPreset('high', true)
    expect(preset.durationMs).toBe(220)
    expect(preset.kenBurnsScale).toBe(1)
    expect(preset.translateYPx).toBe(0)
  })
})
