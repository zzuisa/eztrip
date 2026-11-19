import { describe, expect, it, vi } from 'vitest'
import {
  computeSmoothedFps,
  nextDowngradeStreak,
  startPosterPerformanceGuard,
} from '@/utils/poster-performance-guard'

describe('poster-performance-guard', () => {
  it('computeSmoothedFps returns null for sparse samples', () => {
    expect(computeSmoothedFps([])).toBeNull()
    expect(computeSmoothedFps([16])).toBeNull()
  })

  it('computeSmoothedFps estimates ~60fps from 16ms deltas', () => {
    const deltas = Array.from({ length: 20 }, () => 16.67)
    const fps = computeSmoothedFps(deltas)
    expect(fps).not.toBeNull()
    expect(fps!).toBeGreaterThan(58)
    expect(fps!).toBeLessThan(62)
  })

  it('nextDowngradeStreak accumulates on low fps and decays on recovery', () => {
    expect(nextDowngradeStreak(0, 30, 42)).toBe(1)
    expect(nextDowngradeStreak(2, 30, 42)).toBe(3)
    expect(nextDowngradeStreak(2, 55, 42)).toBe(1)
    expect(nextDowngradeStreak(0, null, 42)).toBe(0)
  })

  it('startPosterPerformanceGuard invokes onDowngrade after sustained low FPS (rAF timestamps)', async () => {
    vi.stubGlobal('cancelAnimationFrame', vi.fn())

    let ts = 0
    vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => {
      queueMicrotask(() => {
        ts += 40
        cb(ts)
      })
      return 1
    })

    const onDowngrade = vi.fn()
    startPosterPerformanceGuard({
      lowFpsThreshold: 45,
      consecutiveLowFpsChecks: 2,
      evalIntervalMs: 100,
      minSamples: 10,
      maxDurationMs: 200_000,
      onDowngrade,
    })

    for (let i = 0; i < 200; i++) {
      await Promise.resolve()
      if (onDowngrade.mock.calls.length) break
    }

    expect(onDowngrade).toHaveBeenCalledTimes(1)
    vi.unstubAllGlobals()
  })
})
