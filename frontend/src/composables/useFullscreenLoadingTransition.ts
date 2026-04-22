import { computed, onBeforeUnmount, ref } from 'vue'
import type { Ref } from 'vue'

type MaybeEl = Element | null | undefined

export type FullscreenLoadingTransitionOptions = {
  durationMs?: number
  easing?: string
}

export type FullscreenLoadingTransitionApi = {
  durationMs: Ref<number>
  easing: Ref<string>
  prefersReducedMotion: Ref<boolean>
  isAnimating: Ref<boolean>
  enter: (targets: { page?: MaybeEl; overlay?: MaybeEl }) => Promise<void>
  leave: (targets: { page?: MaybeEl; overlay?: MaybeEl }) => Promise<void>
  cancel: () => void
}

const DEFAULT_DURATION_MS = 560
const DEFAULT_EASING = 'cubic-bezier(0.4, 0, 0.2, 1)'

function getPrefersReducedMotion(): boolean {
  try {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

async function loadGsap() {
  const mod = await import('gsap')
  return mod.gsap
}

export function useFullscreenLoadingTransition(
  options: FullscreenLoadingTransitionOptions = {},
): FullscreenLoadingTransitionApi {
  const durationMs = ref(options.durationMs ?? DEFAULT_DURATION_MS)
  const easing = ref(options.easing ?? DEFAULT_EASING)
  const prefersReducedMotion = ref(getPrefersReducedMotion())
  const isAnimating = ref(false)

  let killed = false
  let active: { kill?: () => void } | null = null

  const durationSec = computed(() => Math.max(0.1, durationMs.value / 1000))

  const killActive = () => {
    if (active?.kill) active.kill()
    active = null
  }

  const cancel = () => {
    killed = true
    isAnimating.value = false
    killActive()
  }

  const run = async (mode: 'enter' | 'leave', targets: { page?: MaybeEl; overlay?: MaybeEl }) => {
    killed = false
    killActive()
    isAnimating.value = true

    const page = targets.page ?? null
    const overlay = targets.overlay ?? null

    if (prefersReducedMotion.value) {
      isAnimating.value = false
      return
    }

    const gsap = await loadGsap()
    if (killed) return

    const tl = gsap.timeline({
      defaults: { duration: durationSec.value, ease: 'power2.out' },
      onComplete: () => {
        isAnimating.value = false
      },
      onInterrupt: () => {
        isAnimating.value = false
      },
    })
    active = tl

    if (mode === 'enter') {
      if (page) {
        tl.to(page, { opacity: 0.24, y: -6, duration: durationSec.value * 0.85 }, 0)
      }
      if (overlay) {
        gsap.set(overlay, { opacity: 0, y: 10 })
        tl.to(overlay, { opacity: 1, y: 0, duration: durationSec.value }, 0)
      }
    } else {
      if (overlay) {
        tl.to(overlay, { opacity: 0, y: 10, duration: durationSec.value * 0.9 }, 0)
      }
      if (page) {
        tl.to(page, { opacity: 1, y: 0, duration: durationSec.value }, 0)
      }
    }
  }

  const enter = (targets: { page?: MaybeEl; overlay?: MaybeEl }) => run('enter', targets)
  const leave = (targets: { page?: MaybeEl; overlay?: MaybeEl }) => run('leave', targets)

  onBeforeUnmount(() => cancel())

  return {
    durationMs,
    easing,
    prefersReducedMotion,
    isAnimating,
    enter,
    leave,
    cancel,
  }
}

