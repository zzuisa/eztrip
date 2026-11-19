import { computed, ref } from 'vue'
import {
  getPosterMotionPreset,
  inferPosterMotionTier,
  type PosterMotionTier,
} from '@/utils/poster-motion-presets'

function clamp(value: number, min = 0, max = 1): number {
  return Math.min(max, Math.max(min, value))
}

export interface PosterFrameMotion {
  cardClass: string
  cardStyle: Record<string, string>
  mediaStyle: Record<string, string>
}

export function usePosterStoryMotion(initialFrameCount = 0) {
  const frameCount = ref(Math.max(0, initialFrameCount))
  const activeIndex = ref(0)
  const reducedMotion = ref(false)
  const motionTier = ref<PosterMotionTier>('medium')
  const progressByFrame = ref<Record<number, number>>({})

  const preset = computed(() => getPosterMotionPreset(motionTier.value))

  const syncMotionTierFromDevice = (input?: {
    hardwareConcurrency?: number
    deviceMemory?: number
  }) => {
    motionTier.value = inferPosterMotionTier(input)
  }

  const syncReducedMotionFromMediaQuery = (matches: boolean) => {
    reducedMotion.value = matches
    if (matches) motionTier.value = 'low'
  }

  const downgradeMotionTierOneStep = () => {
    if (reducedMotion.value) return
    if (motionTier.value === 'high') motionTier.value = 'medium'
    else if (motionTier.value === 'medium') motionTier.value = 'low'
  }

  const setFrameCount = (nextCount: number) => {
    frameCount.value = Math.max(0, nextCount)
    activeIndex.value = Math.min(activeIndex.value, Math.max(0, frameCount.value - 1))
  }

  const setActiveFrame = (index: number) => {
    if (!frameCount.value) {
      activeIndex.value = 0
      return
    }
    activeIndex.value = Math.min(Math.max(index, 0), frameCount.value - 1)
  }

  const setFrameProgress = (index: number, value: number) => {
    progressByFrame.value[index] = clamp(value)
  }

  const getFrameMotion = (index: number): PosterFrameMotion => {
    const progress = clamp(progressByFrame.value[index] ?? 0)
    const distance = index - activeIndex.value
    const p = preset.value
    const styleKey =
      reducedMotion.value || motionTier.value === 'low' ? 'poster-motion--lite' : 'poster-motion--full'

    if (reducedMotion.value) {
      return {
        cardClass: styleKey,
        cardStyle: {
          opacity: String(0.88 + progress * 0.12),
          transform: 'translate3d(0, 0, 0)',
        },
        mediaStyle: {
          transform: 'scale(1)',
        },
      }
    }

    const opacity = clamp(Math.max(p.fadeMinOpacity, 1 - Math.abs(distance) * 0.18 + progress * 0.2), p.fadeMinOpacity, 1)
    const offsetY = ((1 - progress) * p.parallaxOffset) * (distance <= 0 ? -1 : 1)
    const rotateY = clamp(-distance * p.flipDeg, -12, 12)
    const scale = 1 + progress * p.zoomScale

    return {
      cardClass: styleKey,
      cardStyle: {
        opacity: opacity.toFixed(3),
        transform: `translate3d(0, ${offsetY.toFixed(2)}px, 0) rotateY(${rotateY.toFixed(2)}deg)`,
      },
      mediaStyle: {
        transform: `scale(${scale.toFixed(3)})`,
      },
    }
  }

  return {
    frameCount,
    activeIndex,
    reducedMotion,
    motionTier,
    preset,
    setFrameCount,
    setActiveFrame,
    setFrameProgress,
    getFrameMotion,
    syncMotionTierFromDevice,
    syncReducedMotionFromMediaQuery,
    downgradeMotionTierOneStep,
  }
}
