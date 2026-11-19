/**
 * Lightweight rAF-based FPS sampling for poster animations.
 * All work is scheduled via requestAnimationFrame — no busy loops on the main thread.
 */

export interface PosterPerformanceGuardOptions {
  /** Rolling average FPS below this triggers the low-FPS streak counter */
  lowFpsThreshold?: number
  /** Number of consecutive low-FPS evaluations required before firing onDowngrade */
  consecutiveLowFpsChecks?: number
  /** Minimum time between FPS evaluations (ms) */
  evalIntervalMs?: number
  /** Stop monitoring after this duration (ms). 0 = run until downgrade or manual stop */
  maxDurationMs?: number
  /** Minimum frame delta samples before evaluating */
  minSamples?: number
  onDowngrade: () => void
}

export function computeSmoothedFps(frameDeltasMs: number[]): number | null {
  if (frameDeltasMs.length < 3) return null
  const avg = frameDeltasMs.reduce((a, b) => a + b, 0) / frameDeltasMs.length
  if (avg <= 0 || avg > 500) return null
  return 1000 / avg
}

/** @internal exported for unit tests */
export function nextDowngradeStreak(
  prev: number,
  fps: number | null,
  threshold: number,
): number {
  if (fps == null) return Math.max(0, prev - 1)
  if (fps < threshold) return prev + 1
  return Math.max(0, prev - 1)
}

/**
 * Starts sampling frame intervals via requestAnimationFrame.
 * Pauses accumulation while the document is hidden (background tab).
 */
export function startPosterPerformanceGuard(options: PosterPerformanceGuardOptions): () => void {
  const lowFpsThreshold = options.lowFpsThreshold ?? 42
  const consecutiveLowFpsChecks = options.consecutiveLowFpsChecks ?? 3
  const evalIntervalMs = options.evalIntervalMs ?? 450
  const maxDurationMs = options.maxDurationMs ?? 10_000
  const minSamples = options.minSamples ?? 18
  const maxDeltaSamples = 48

  let stopped = false
  let rafId = 0
  let lastTs = 0
  const deltas: number[] = []
  let lowStreak = 0
  let lastEvalAt = 0
  let startAt = 0

  const stop = () => {
    stopped = true
    if (rafId) cancelAnimationFrame(rafId)
    rafId = 0
  }

  const onVisibility = () => {
    if (typeof document === 'undefined' || !document.hidden) return
    deltas.length = 0
    lowStreak = 0
    lastTs = 0
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibility)
  }

  const cleanup = () => {
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', onVisibility)
    }
    stop()
  }

  const tick = (ts: number) => {
    if (stopped) return
    if (typeof document !== 'undefined' && document.hidden) {
      rafId = requestAnimationFrame(tick)
      return
    }
    if (!startAt) startAt = ts
    if (maxDurationMs > 0 && ts - startAt >= maxDurationMs) {
      cleanup()
      return
    }
    if (lastTs) {
      const d = ts - lastTs
      if (d > 0 && d < 250) {
        deltas.push(d)
        if (deltas.length > maxDeltaSamples) deltas.shift()
      }
    }
    lastTs = ts

    if (ts - lastEvalAt >= evalIntervalMs && deltas.length >= minSamples) {
      lastEvalAt = ts
      const fps = computeSmoothedFps(deltas)
      lowStreak = nextDowngradeStreak(lowStreak, fps, lowFpsThreshold)
      if (lowStreak >= consecutiveLowFpsChecks) {
        options.onDowngrade()
        cleanup()
        return
      }
    }

    rafId = requestAnimationFrame(tick)
  }

  rafId = requestAnimationFrame(tick)
  return cleanup
}
