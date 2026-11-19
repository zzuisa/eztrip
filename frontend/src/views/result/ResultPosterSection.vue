<template>
  <a-card id="trip-poster" :bordered="false" class="poster-card">
    <TripPosterGallery
      :story="story"
      @open="$emit('open', $event)"
      @performance-downgrade="$emit('performance-downgrade')"
    />
    <TripPosterLightbox
      :visible="visible"
      :frames="frames"
      :guide-slides="guideSlides"
      :active-index="activeIndex"
      :zoom-scale="zoomScale"
      :is-fullscreen="isFullscreen"
      :autoplay-paused="autoplayPaused"
      :transition-preset="transitionPreset"
      @update:active-index="$emit('update:active-index', $event)"
      @request-prev="$emit('request-prev')"
      @request-next="$emit('request-next')"
      @toggle-zoom="$emit('toggle-zoom')"
      @toggle-fullscreen="$emit('toggle-fullscreen')"
      @toggle-autoplay="$emit('toggle-autoplay')"
      @wheel-zoom="$emit('wheel-zoom', $event)"
      @touch-start="$emit('touch-start', $event)"
      @touch-end="$emit('touch-end', $event)"
      @close="$emit('close')"
    />
  </a-card>
</template>

<script setup lang="ts">
import TripPosterGallery from '@/components/poster/TripPosterGallery.vue'
import TripPosterLightbox from '@/components/poster/TripPosterLightbox.vue'
import type { PosterTransitionPreset } from '@/utils/poster-transition-presets'

defineProps<{
  story: any
  visible: boolean
  frames: any[]
  guideSlides: any[]
  activeIndex: number
  zoomScale: number
  isFullscreen: boolean
  autoplayPaused: boolean
  transitionPreset: PosterTransitionPreset
}>()
defineEmits([
  'open',
  'performance-downgrade',
  'update:active-index',
  'request-prev',
  'request-next',
  'toggle-zoom',
  'toggle-fullscreen',
  'toggle-autoplay',
  'wheel-zoom',
  'touch-start',
  'touch-end',
  'close',
])
</script>
