import { describe, expect, it, vi, beforeEach } from 'vitest'
import { useFullscreenLoadingTransition } from '@/composables/useFullscreenLoadingTransition'

beforeEach(() => {
  // @ts-expect-error test shim
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes('prefers-reduced-motion') ? false : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
})

describe('useFullscreenLoadingTransition', () => {
  it('exposes defaults', () => {
    const api = useFullscreenLoadingTransition()
    expect(api.durationMs.value).toBeGreaterThanOrEqual(500)
    expect(api.durationMs.value).toBeLessThanOrEqual(600)
    expect(typeof api.easing.value).toBe('string')
  })

  it('respects prefers-reduced-motion branch', async () => {
    // @ts-expect-error test shim
    window.matchMedia = vi.fn().mockImplementation(() => ({
      matches: true,
      media: '(prefers-reduced-motion: reduce)',
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))

    const api = useFullscreenLoadingTransition()
    await api.enter({ page: document.createElement('div'), overlay: document.createElement('div') })
    expect(api.isAnimating.value).toBe(false)
  })
})

