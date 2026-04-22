import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createRouter, createWebHistory } from 'vue-router'

let lastSignal: AbortSignal | undefined

vi.mock('@/services/api', () => ({
  streamTravelPlanByLocation: vi.fn(async (_payload: any, _handlers: any, options: any) => {
    lastSignal = options?.signal
    _handlers?.onStage?.('generation')
    _handlers?.onProgress?.(35, '生成中')
    await new Promise<void>((resolve, reject) => {
      if (!lastSignal) return resolve()
      if (lastSignal.aborted) return reject(new DOMException('Aborted', 'AbortError'))
      lastSignal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')), { once: true })
    })
  }),
}))

vi.mock('@/composables/useFullscreenLoadingTransition', () => ({
  useFullscreenLoadingTransition: () => ({
    durationMs: { value: 560 },
    easing: { value: 'cubic-bezier(0.4, 0, 0.2, 1)' },
    prefersReducedMotion: { value: true },
    isAnimating: { value: false },
    enter: async () => {},
    leave: async () => {},
    cancel: () => {},
  }),
}))

import Home from '@/views/Home.vue'

describe('home fullscreen loading transition', () => {
  it('can start and cancel generation via AbortController', async () => {
    const router = createRouter({
      history: createWebHistory(),
      routes: [{ path: '/', component: Home }],
    })
    router.push('/')
    await router.isReady()

    const wrapper = mount(Home, {
      attachTo: document.body,
      global: {
        plugins: [router],
        stubs: {
          'a-card': true,
          'a-form': true,
          'a-form-item': true,
          'a-row': true,
          'a-col': true,
          'a-input': true,
          'a-date-picker': true,
          'a-select': true,
          'a-select-option': true,
          'a-checkbox-group': true,
          'a-checkbox': true,
          'a-textarea': true,
          'a-button': true,
        },
      },
    })

    ;(wrapper.vm as any).formData.city = 'Berlin'
    ;(wrapper.vm as any).formData.start_date = { format: () => '2026-04-20', diff: () => 0 }
    ;(wrapper.vm as any).formData.end_date = { format: () => '2026-04-21', diff: () => 1 }

    const p = (wrapper.vm as any).handleSubmit()
    for (let i = 0; i < 10; i++) {
      if (lastSignal) break
      await new Promise((r) => setTimeout(r, 0))
    }

    expect((wrapper.vm as any).fullscreenVisible).toBe(true)
    expect((wrapper.vm as any).currentStage).toBe('generation')
    expect(lastSignal).toBeTruthy()
    expect(lastSignal?.aborted).toBe(false)
    expect(document.querySelector('[data-testid="fullscreen-loading-overlay"]')).toBeTruthy()
    expect(document.querySelector('[data-testid="fullscreen-loading-dialog"]')?.className).toContain('fs-content-dark')
    expect(document.body.style.overflow).toBe('hidden')

    await (wrapper.vm as any).handleCancel()
    expect(lastSignal?.aborted).toBe(true)
    expect(document.body.style.overflow).toBe('')

    await expect(p).resolves.toBeUndefined()
    wrapper.unmount()
  }, 15000)
})

