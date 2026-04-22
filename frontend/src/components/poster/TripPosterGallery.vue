<template>
  <section class="trip-poster-gallery">
    <header class="poster-header">
      <h3 class="poster-heading">定制化海报</h3>
      <p class="poster-description">基于本次行程真实景点图片生成的故事流海报，可在移动端流畅浏览。</p>
    </header>

    <a-empty v-if="!story.frames.length" description="当前行程暂无可用实景图" />

    <div v-else class="poster-grid">
      <PosterFrameCard
        v-for="frame in story.frames"
        :key="frame.id"
        :frame="frame"
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import PosterFrameCard from './PosterFrameCard.vue'
import type { PosterStory } from '@/types/poster'

defineProps<{
  story: PosterStory
}>()
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
}
</style>

