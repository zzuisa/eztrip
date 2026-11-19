import { computed, ref } from 'vue'
import type { PosterFrame } from '@/types/poster'
import { usePosterAutoplay } from '@/composables/usePosterAutoplay'
import {
  getPosterTransitionPreset,
  type PosterTransitionTier,
} from '@/utils/poster-transition-presets'

export function usePosterInteraction() {
  const lightboxVisible = ref(false)
  const lightboxIndex = ref(0)
  const frames = ref<PosterFrame[]>([])
  const zoomScale = ref(1)
  const isFullscreen = ref(false)
  const touchStartPoint = ref<{ x: number; y: number } | null>(null)
  const returnAnchorId = ref('trip-poster')
  const autoplayReady = ref(false)
  const transitionTier = ref<PosterTransitionTier>('medium')
  const reducedMotion = ref(false)
  const maxZoom = 2.4
  const minZoom = 1

  const activeFrame = computed(() => frames.value[lightboxIndex.value] || null)
  const transitionPreset = computed(() =>
    getPosterTransitionPreset(transitionTier.value, reducedMotion.value),
  )
  const autoplay = usePosterAutoplay({ initialDelayMs: 300, intervalMs: 3400, loop: true })

  const clampIndex = (index: number) => Math.max(0, Math.min(index, frames.value.length - 1))
  const clampZoom = (value: number) => Math.min(maxZoom, Math.max(minZoom, value))

  const openLightbox = (nextFrames: PosterFrame[], index = 0, anchorId = 'trip-poster') => {
    frames.value = nextFrames
    lightboxIndex.value = Math.max(0, Math.min(index, nextFrames.length - 1))
    autoplay.setFrameTotal(nextFrames.length)
    autoplay.setCurrentIndex(lightboxIndex.value)
    returnAnchorId.value = anchorId
    zoomScale.value = 1
    isFullscreen.value = true
    lightboxVisible.value = nextFrames.length > 0
    autoplayReady.value = false
    autoplay.start((nextIndex) => {
      lightboxIndex.value = nextIndex
    })
    autoplayReady.value = true
  }

  const closeLightbox = () => {
    lightboxVisible.value = false
    autoplay.stop()
    autoplayReady.value = false
    zoomScale.value = 1
    isFullscreen.value = false
  }

  const setLightboxIndex = (index: number) => {
    lightboxIndex.value = clampIndex(index)
    autoplay.setCurrentIndex(lightboxIndex.value)
    zoomScale.value = 1
  }

  const goPrev = () => {
    setLightboxIndex(lightboxIndex.value - 1)
  }

  const goNext = () => {
    setLightboxIndex(lightboxIndex.value + 1)
  }

  const setZoomScale = (next: number) => {
    zoomScale.value = clampZoom(next)
  }

  const zoomIn = () => setZoomScale(zoomScale.value + 0.2)
  const zoomOut = () => setZoomScale(zoomScale.value - 0.2)
  const toggleZoom = () => setZoomScale(zoomScale.value > 1 ? 1 : 1.8)

  const handleWheelZoom = (deltaY: number) => {
    if (deltaY < 0) {
      zoomIn()
    } else {
      zoomOut()
    }
  }

  const handleTouchStart = (x: number, y: number) => {
    touchStartPoint.value = { x, y }
  }

  const handleTouchEnd = (x: number, y: number) => {
    const start = touchStartPoint.value
    touchStartPoint.value = null
    if (!start) return
    const deltaX = x - start.x
    const deltaY = y - start.y
    if (Math.abs(deltaX) < 40 || Math.abs(deltaY) > 80) return
    if (deltaX > 0) {
      goPrev()
    } else {
      goNext()
    }
  }

  const toggleFullscreen = () => {
    isFullscreen.value = !isFullscreen.value
  }

  const pauseAutoplay = () => autoplay.pause()
  const resumeAutoplay = () => autoplay.resume()
  const toggleAutoplay = () => {
    if (autoplay.paused.value) {
      resumeAutoplay()
    } else {
      pauseAutoplay()
    }
  }

  const syncPerformanceTier = (input?: { hardwareConcurrency?: number; deviceMemory?: number }) => {
    const cores = Number(input?.hardwareConcurrency ?? 6)
    const memory = Number(input?.deviceMemory ?? 4)
    if (cores <= 4 || memory <= 3) {
      transitionTier.value = 'low'
      return
    }
    if (cores <= 8 || memory <= 6) {
      transitionTier.value = 'medium'
      return
    }
    transitionTier.value = 'high'
  }

  const syncReducedMotion = (value: boolean) => {
    reducedMotion.value = value
    if (value) {
      transitionTier.value = 'low'
    }
  }

  const downgradeTransitionTierOneStep = () => {
    if (reducedMotion.value) return
    if (transitionTier.value === 'high') transitionTier.value = 'medium'
    else if (transitionTier.value === 'medium') transitionTier.value = 'low'
  }

  const restoreAnchor = () => {
    if (typeof document === 'undefined') return
    const el = document.getElementById(returnAnchorId.value)
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  return {
    lightboxVisible,
    lightboxIndex,
    frames,
    activeFrame,
    zoomScale,
    isFullscreen,
    autoplayReady,
    autoplayPaused: autoplay.paused,
    transitionPreset,
    openLightbox,
    closeLightbox,
    setLightboxIndex,
    goPrev,
    goNext,
    zoomIn,
    zoomOut,
    toggleZoom,
    handleWheelZoom,
    handleTouchStart,
    handleTouchEnd,
    toggleFullscreen,
    pauseAutoplay,
    resumeAutoplay,
    toggleAutoplay,
    syncPerformanceTier,
    syncReducedMotion,
    downgradeTransitionTierOneStep,
    restoreAnchor,
  }
}
