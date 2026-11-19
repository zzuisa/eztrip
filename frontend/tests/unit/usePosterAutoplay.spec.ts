import { describe, expect, it, vi } from 'vitest'
import { usePosterAutoplay } from '@/composables/usePosterAutoplay'

describe('usePosterAutoplay', () => {
  it('starts, ticks, pauses and resumes', () => {
    vi.useFakeTimers()
    const autoplay = usePosterAutoplay({ initialDelayMs: 200, intervalMs: 1000, loop: true })
    autoplay.setFrameTotal(3)
    const visited: number[] = []
    autoplay.start((idx) => visited.push(idx))

    vi.advanceTimersByTime(200)
    expect(visited[0]).toBe(0)
    vi.advanceTimersByTime(1000)
    expect(visited[1]).toBe(1)

    autoplay.pause()
    vi.advanceTimersByTime(2000)
    expect(visited.length).toBe(2)

    autoplay.resume()
    vi.advanceTimersByTime(1000)
    expect(visited[2]).toBe(2)

    autoplay.stop()
    expect(autoplay.running.value).toBe(false)
    vi.useRealTimers()
  })
})
