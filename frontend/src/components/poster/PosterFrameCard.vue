<template>
  <article :id="cardId" class="poster-frame-card" :class="motionClass" :style="cardStyle">
    <div class="poster-media-wrap">
      <img
        class="poster-media"
        :src="displayUrl"
        :alt="frame.title"
        :style="mediaStyle"
        loading="lazy"
        @error="onImageError"
      />
      <span class="poster-kind">{{ kindLabel }}</span>
    </div>
    <div class="poster-copy">
      <div class="poster-title">{{ frame.title }}</div>
      <div class="poster-meta">{{ frame.dayLabel }}<span v-if="frame.timeLabel"> · {{ frame.timeLabel }}</span></div>
      <div v-if="frame.subtitle" class="poster-subtitle">{{ frame.subtitle }}</div>
      <div v-if="frame.address" class="poster-address">{{ frame.address }}</div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { PosterFrame } from '@/types/poster'
import { buildPosterFallbackImageUrl } from '@/services/poster-data-service'

const props = defineProps<{
  frame: PosterFrame
  cardId?: string
  motionClass?: string
  cardStyle?: Record<string, string>
  mediaStyle?: Record<string, string>
}>()

const displayUrl = ref(props.frame.imageUrl)
watch(
  () => props.frame.imageUrl,
  (next) => {
    displayUrl.value = next
  },
)

const onImageError = () => {
  displayUrl.value = buildPosterFallbackImageUrl(props.frame.title, props.frame.dayLabel)
}

const kindLabel = computed(() => {
  if (props.frame.kind === 'meal') return '餐饮'
  if (props.frame.kind === 'activity') return '活动'
  return '景点'
})
</script>

<style scoped>
.poster-frame-card {
  border-radius: 14px;
  overflow: hidden;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  box-shadow: 0 10px 26px rgba(15, 23, 42, 0.08);
  transform-style: preserve-3d;
  will-change: transform, opacity;
  transition: transform 420ms cubic-bezier(0.2, 0.7, 0.2, 1), opacity 300ms ease;
}
.poster-media-wrap {
  position: relative;
  aspect-ratio: 16 / 10;
  overflow: hidden;
}
.poster-media {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  will-change: transform;
  transition: transform 520ms cubic-bezier(0.2, 0.7, 0.2, 1), filter 280ms ease;
}
.poster-kind {
  position: absolute;
  left: 10px;
  top: 10px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  color: #fff;
  background: rgba(15, 23, 42, 0.7);
}
.poster-copy {
  padding: 12px;
}
.poster-title {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}
.poster-meta,
.poster-subtitle,
.poster-address {
  margin-top: 4px;
  font-size: 12px;
  color: #475569;
}
.poster-motion--full .poster-media {
  filter: saturate(1.02) contrast(1.02);
}
.poster-motion--lite .poster-media {
  filter: none;
}
</style>

