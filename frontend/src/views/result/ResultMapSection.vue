<template>
  <div class="right-map">
    <a-card id="map" title="📍 景点地图" :bordered="false" class="map-card">
      <div class="map-wrap">
        <div id="mapbox-container" class="mapbox-container"></div>
        <div class="map-story-panel" v-if="mapStory.visible">
          <div class="map-story-cards">
            <div class="story-card current" :style="{ opacity: 1 - mapStory.transitionProgress }">
              <img :src="resolveImage(mapStory.current.image)" :alt="mapStory.current.name" class="story-image" @error="$emit('image-error', $event)" />
              <div class="story-content">
                <div class="story-title">{{ mapStory.current.name }}</div>
                <div class="story-desc">{{ mapStory.current.description || '推荐停留并打卡拍照。' }}</div>
                <div class="story-meta">{{ mapStory.current.address || '地址待补充' }}</div>
              </div>
            </div>
            <div v-if="mapStory.next" class="story-card next" :style="{ opacity: mapStory.transitionProgress }">
              <img :src="resolveImage(mapStory.next.image)" :alt="mapStory.next.name" class="story-image" @error="$emit('image-error', $event)" />
              <div class="story-content">
                <div class="story-title">下一站：{{ mapStory.next.name }}</div>
                <div class="story-desc">{{ mapStory.next.description || '即将抵达下一处精彩景点。' }}</div>
                <div class="story-meta">{{ mapStory.next.address || '地址待补充' }}</div>
              </div>
            </div>
          </div>
        </div>
        <div class="map-legend" v-if="days?.length">
          <div
            v-for="(day, idx) in days"
            :key="`legend-${idx}`"
            class="legend-item"
          >
            <span class="legend-dot" :style="{ backgroundColor: routeColors[idx % routeColors.length] }"></span>
            <span>第{{ getDayIndex(day, idx) + 1 }}天路线</span>
          </div>
        </div>
      </div>
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { getDayIndex } from './result-helpers'

const props = defineProps<{
  days: any[]
  routeColors: string[]
  mapStory: any
}>()

defineEmits(['image-error'])

const resolveImage = (image?: string) => image || 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="320" height="180"%3E%3Crect width="320" height="180" fill="%23e5e7eb"/%3E%3Ctext x="50%25" y="50%25" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="16" fill="%239ca3af"%3E暂无图片%3C/text%3E%3C/svg%3E'
</script>

<style scoped>
.right-map { flex: 1; min-width: 0; }
.map-card, .map-wrap, .mapbox-container { width: 100%; }
.map-card { min-height: 520px; }
.map-wrap { position: relative; min-height: 460px; overflow: hidden; border-radius: 14px; }
.mapbox-container { min-height: 460px; background: #edf2f7; }
.map-story-panel { position: absolute; left: 12px; top: 12px; z-index: 3; width: min(360px, calc(100% - 24px)); }
.map-story-cards { position: relative; min-height: 120px; }
.story-card { position: absolute; inset: 0; display: flex; gap: 10px; padding: 10px; background: rgba(255,255,255,.95); border-radius: 12px; box-shadow: 0 8px 24px rgba(15,23,42,.16); overflow: hidden; transition: opacity .25s ease; }
.story-image { width: 92px; height: 92px; flex: 0 0 92px; border-radius: 10px; object-fit: cover; background: #e5e7eb; }
.story-content { min-width: 0; }
.story-title { font-weight: 700; font-size: 15px; color: #111827; }
.story-desc, .story-meta { font-size: 12px; line-height: 1.45; color: #4b5563; margin-top: 4px; }
.map-legend { position: absolute; right: 12px; bottom: 12px; z-index: 3; display: grid; gap: 8px; background: rgba(255,255,255,.92); padding: 10px 12px; border-radius: 12px; box-shadow: 0 8px 24px rgba(15,23,42,.16); }
.legend-item { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #334155; }
.legend-dot { width: 10px; height: 10px; border-radius: 999px; flex: 0 0 10px; }
@media (max-width: 768px) {
  .right-map { width: 100%; flex: 1 1 auto; }
  .map-card { min-height: 360px; }
  .map-wrap, .mapbox-container { min-height: 320px; }
  .map-story-panel { width: calc(100% - 24px); }
  .story-card { flex-direction: column; }
  .story-image { width: 100%; height: 120px; flex-basis: auto; }
}
</style>
