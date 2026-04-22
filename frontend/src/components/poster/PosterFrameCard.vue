<template>
  <article class="poster-frame-card">
    <div class="poster-media-wrap">
      <img class="poster-media" :src="frame.imageUrl" :alt="frame.title" loading="lazy" />
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
import { computed } from 'vue'
import type { PosterFrame } from '@/types/poster'

const props = defineProps<{
  frame: PosterFrame
}>()

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
</style>

