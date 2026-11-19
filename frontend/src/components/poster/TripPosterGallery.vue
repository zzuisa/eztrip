<template>
  <section class="trip-poster-gallery">
    <header class="poster-header">
      <h3 class="poster-heading">定制化海报</h3>
      <p class="poster-description">基于本次行程真实景点图片生成的故事流海报，可在移动端流畅浏览。</p>
    </header>

    <a-empty v-if="!story.frames.length">
      <template #description>
        <span>当前行程暂无可用实景图。若行程含景点，保存后将尝试拉取配图；也可直接进入全屏故事模式浏览文案行程。</span>
      </template>
    </a-empty>

    <div v-else>
      <div :class="['poster-grid', { 'poster-grid--single': isSingleFrame }]">
        <PosterFrameCard
          v-for="(frame, index) in displayFrames"
          :key="frame.id"
          :ref="(el) => setFrameRef(el as HTMLElement | null, index)"
          :frame="frame"
          :card-id="`poster-frame-${frame.id}`"
          :motion-class="getFrameMotion(index).cardClass"
          :card-style="getFrameMotion(index).cardStyle"
          :media-style="getFrameMotion(index).mediaStyle"
          @click="emit('open', { index, anchorId: `poster-frame-${frame.id}` })"
        />
      </div>
      <p v-if="hiddenFrameCount > 0" class="poster-gallery-more" role="status">
        还有 {{ hiddenFrameCount }} 个行程点在列表中已折叠，请使用全屏故事播放查看完整路线。
      </p>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import PosterFrameCard from './PosterFrameCard.vue'
import type { PosterStory } from '@/types/poster'
import { usePosterStoryMotion } from '@/composables/usePosterStoryMotion'
import { startPosterPerformanceGuard } from '@/utils/poster-performance-guard'

const MAX_VISIBLE_POSTER_FRAMES = 48

const props = defineProps<{
  story: PosterStory
}>()

const emit = defineEmits<{
  (e: 'open', payload: { index: number; anchorId: string }): void
  (e: 'performance-downgrade'): void
}>()

const displayFrames = computed(() => props.story.frames.slice(0, MAX_VISIBLE_POSTER_FRAMES))
const hiddenFrameCount = computed(() => Math.max(0, props.story.frames.length - displayFrames.value.length))
const isSingleFrame = computed(() => props.story.frames.length === 1)

const frameElements: Array<HTMLElement | null> = []
const {
  setFrameCount,
  setActiveFrame,
  setFrameProgress,
  getFrameMotion,
  syncMotionTierFromDevice,
  syncReducedMotionFromMediaQuery,
  downgradeMotionTierOneStep,
} = usePosterStoryMotion(0)

let rafId = 0
let removeMotionListener: (() => void) | null = null
let stopPerfGuard: (() => void) | null = null

const updateMotionProgress = () => {
  if (typeof window === 'undefined') return
  const viewportCenter = window.innerHeight * 0.5
  let bestIndex = 0
  let bestScore = -1
  frameElements.forEach((el, index) => {
    if (!el) return
    const rect = el.getBoundingClientRect()
    const center = rect.top + rect.height / 2
    const score = Math.max(0, 1 - Math.abs(center - viewportCenter) / (window.innerHeight * 0.8))
    setFrameProgress(index, score)
    if (score > bestScore) {
      bestScore = score
      bestIndex = index
    }
  })
  setActiveFrame(bestIndex)
}

const queueMotionUpdate = () => {
  if (rafId) cancelAnimationFrame(rafId)
  rafId = requestAnimationFrame(() => {
    updateMotionProgress()
    rafId = 0
  })
}

const setFrameRef = (el: HTMLElement | null, index: number) => {
  frameElements[index] = el
  queueMotionUpdate()
}

onMounted(() => {
  syncMotionTierFromDevice({
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: (navigator as Navigator & { deviceMemory?: number }).deviceMemory,
  })
  const media = window.matchMedia('(prefers-reduced-motion: reduce)')
  const handler = (event: MediaQueryList | MediaQueryListEvent) =>
    syncReducedMotionFromMediaQuery(event.matches)
  handler(media)
  media.addEventListener('change', handler)
  removeMotionListener = () => media.removeEventListener('change', handler)
  window.addEventListener('scroll', queueMotionUpdate, { passive: true })
  window.addEventListener('resize', queueMotionUpdate)
  stopPerfGuard = startPosterPerformanceGuard({
    onDowngrade: () => {
      downgradeMotionTierOneStep()
      emit('performance-downgrade')
    },
  })
  queueMotionUpdate()
})

onBeforeUnmount(() => {
  stopPerfGuard?.()
  stopPerfGuard = null
  if (rafId) cancelAnimationFrame(rafId)
  removeMotionListener?.()
  window.removeEventListener('scroll', queueMotionUpdate)
  window.removeEventListener('resize', queueMotionUpdate)
})

watch(
  () => displayFrames.value.length,
  (next) => {
    setFrameCount(next)
    frameElements.length = next
    queueMotionUpdate()
  },
  { immediate: true },
)

watch(
  () => props.story.frames.length,
  () => queueMotionUpdate(),
)
</script>

<style scoped>
.trip-poster-gallery {
  margin-top: 18px;
}
.poster-header {
  margin-bottom: 12px;
}
.poster-heading {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
}
.poster-description {
  margin: 6px 0 0;
  font-size: 13px;
  color: #64748b;
}
.poster-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}
.poster-grid--single {
  max-width: 520px;
  margin: 0 auto;
}
.poster-gallery-more {
  margin: 12px 0 0;
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}
@media (max-width: 980px) {
  .poster-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 640px) {
  .poster-grid {
    grid-template-columns: 1fr;
    gap: 10px;
  }
  .poster-grid--single {
    max-width: none;
  }
}
</style>
