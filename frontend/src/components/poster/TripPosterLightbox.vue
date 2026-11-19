<template>
  <Teleport to="body">
    <Transition name="poster-lightbox-fade">
      <div v-if="visible" class="poster-lightbox" @click.self="close">
        <button class="poster-lightbox-close" type="button" @click="close" aria-label="关闭海报查看器">×</button>

        <button
          class="poster-lightbox-nav poster-lightbox-nav--prev"
          type="button"
          :disabled="activeIndex <= 0"
          @click.stop="emit('request-prev')"
          aria-label="上一张"
        >
          ‹
        </button>

        <figure
          class="poster-lightbox-panel"
          :class="{ 'poster-lightbox-panel--fullscreen': isFullscreen }"
          @dblclick.stop="emit('toggle-zoom')"
          @wheel.prevent="onWheel"
          @touchstart.passive="onTouchStart"
          @touchend.passive="onTouchEnd"
        >
          <Transition name="poster-frame-fade" mode="out-in">
            <img
              :key="activeFrame?.id || 'empty'"
              class="poster-lightbox-image"
              :style="{
                transform: `scale(${zoomScale * transitionPreset.kenBurnsScale}) translateY(${transitionPreset.translateYPx}px)`,
                transition: `transform ${transitionPreset.durationMs}ms ${transitionPreset.easing}`,
              }"
              :src="activeFrame?.imageUrl"
              :alt="activeFrame?.title || '海报图片'"
            />
          </Transition>
          <figcaption class="poster-lightbox-caption">
            <div class="poster-lightbox-kicker">{{ activeFrame?.dayLabel }}</div>
            <h4 class="poster-lightbox-title">{{ activeFrame?.title }}</h4>
            <p v-if="activeFrame?.subtitle" class="poster-lightbox-subtitle">{{ activeFrame.subtitle }}</p>
            <p v-if="activeFrame?.address" class="poster-lightbox-address">{{ activeFrame.address }}</p>
            <div v-if="activeGuide" class="poster-lightbox-guide">
              <div class="poster-lightbox-guide-step">
                {{ activeGuide.stepLabel }} · 第 {{ activeIndex + 1 }} / {{ frames.length }} 站
              </div>
              <p class="poster-lightbox-guide-copy">{{ activeGuide.narration }}</p>
            </div>
          </figcaption>
        </figure>

        <div class="poster-lightbox-actions">
          <button class="poster-lightbox-action" type="button" @click.stop="emit('toggle-zoom')">
            {{ zoomScale > 1 ? '缩小' : '放大' }}
          </button>
          <button class="poster-lightbox-action" type="button" @click.stop="emit('toggle-fullscreen')">
            {{ isFullscreen ? '退出全屏' : '全屏预览' }}
          </button>
          <button class="poster-lightbox-action" type="button" @click.stop="emit('toggle-autoplay')">
            {{ autoplayPaused ? '继续播放' : '暂停播放' }}
          </button>
        </div>

        <button
          class="poster-lightbox-nav poster-lightbox-nav--next"
          type="button"
          :disabled="activeIndex >= frames.length - 1"
          @click.stop="emit('request-next')"
          aria-label="下一张"
        >
          ›
        </button>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import type { PosterFrame } from '@/types/poster'
import type { PosterTransitionPreset } from '@/utils/poster-transition-presets'

const props = defineProps<{
  visible: boolean
  frames: PosterFrame[]
  guideSlides: Array<{ stage: string; narration: string; stepLabel: string }>
  activeIndex: number
  zoomScale: number
  isFullscreen: boolean
  autoplayPaused: boolean
  transitionPreset: PosterTransitionPreset
}>()

const emit = defineEmits<{
  (e: 'update:activeIndex', value: number): void
  (e: 'request-prev'): void
  (e: 'request-next'): void
  (e: 'toggle-zoom'): void
  (e: 'toggle-fullscreen'): void
  (e: 'toggle-autoplay'): void
  (e: 'wheel-zoom', deltaY: number): void
  (e: 'touch-start', point: { x: number; y: number }): void
  (e: 'touch-end', point: { x: number; y: number }): void
  (e: 'close'): void
}>()

const activeFrame = computed(() => props.frames[props.activeIndex] || props.frames[0])
const activeGuide = computed(() => props.guideSlides[props.activeIndex] || null)

const close = () => emit('close')
const onWheel = (event: WheelEvent) => emit('wheel-zoom', event.deltaY)
const onTouchStart = (event: TouchEvent) => {
  const touch = event.changedTouches[0]
  if (!touch) return
  emit('touch-start', { x: touch.clientX, y: touch.clientY })
}
const onTouchEnd = (event: TouchEvent) => {
  const touch = event.changedTouches[0]
  if (!touch) return
  emit('touch-end', { x: touch.clientX, y: touch.clientY })
}

watch(
  () => props.visible,
  (visible) => {
    if (!visible) return
    document.body.style.overflow = 'hidden'
  },
)

watch(
  () => props.visible,
  (visible) => {
    if (visible) return
    document.body.style.overflow = ''
  },
)
</script>

<style scoped>
.poster-lightbox-fade-enter-active,
.poster-lightbox-fade-leave-active {
  transition: opacity 180ms ease;
}
.poster-lightbox-fade-enter-from,
.poster-lightbox-fade-leave-to {
  opacity: 0;
}
.poster-frame-fade-enter-active,
.poster-frame-fade-leave-active {
  transition: opacity 360ms ease;
}
.poster-frame-fade-enter-from,
.poster-frame-fade-leave-to {
  opacity: 0.08;
}
.poster-lightbox {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(2, 6, 23, 0.88);
  backdrop-filter: blur(16px);
}
.poster-lightbox-close,
.poster-lightbox-nav {
  position: absolute;
  border: 0;
  background: rgba(15, 23, 42, 0.7);
  color: #fff;
  cursor: pointer;
}
.poster-lightbox-close {
  top: 16px;
  right: 16px;
  width: 42px;
  height: 42px;
  border-radius: 999px;
  font-size: 26px;
}
.poster-lightbox-nav {
  width: 48px;
  height: 48px;
  border-radius: 999px;
  font-size: 30px;
  top: 50%;
  transform: translateY(-50%);
}
.poster-lightbox-nav:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}
.poster-lightbox-nav--prev { left: 14px; }
.poster-lightbox-nav--next { right: 14px; }
.poster-lightbox-actions {
  position: absolute;
  right: 14px;
  bottom: 16px;
  display: flex;
  gap: 8px;
}
.poster-lightbox-action {
  border: 0;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.78);
  color: #e2e8f0;
  padding: 8px 12px;
  font-size: 12px;
  cursor: pointer;
}
.poster-lightbox-panel {
  width: min(92vw, 980px);
  margin: 0;
  background: rgba(15, 23, 42, 0.92);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 24px;
  overflow: hidden;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.45);
}
.poster-lightbox-panel--fullscreen {
  width: min(98vw, 1200px);
}
.poster-lightbox-image {
  width: 100%;
  max-height: 72vh;
  object-fit: cover;
  display: block;
  transition: transform 220ms ease;
  transform-origin: center center;
}
.poster-lightbox-caption {
  padding: 16px 18px 18px;
  color: #e2e8f0;
}
.poster-lightbox-kicker {
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: #94a3b8;
}
.poster-lightbox-title {
  margin: 6px 0 0;
  font-size: 20px;
}
.poster-lightbox-subtitle,
.poster-lightbox-address {
  margin: 8px 0 0;
  color: #cbd5e1;
  line-height: 1.6;
}
.poster-lightbox-guide {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(148, 163, 184, 0.25);
}
.poster-lightbox-guide-step {
  font-size: 12px;
  color: #93c5fd;
  letter-spacing: 0.04em;
}
.poster-lightbox-guide-copy {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.6;
  color: #e2e8f0;
}
@media (max-width: 640px) {
  .poster-lightbox-panel { width: 100%; border-radius: 18px; }
  .poster-lightbox-nav { width: 40px; height: 40px; }
}
</style>
