<template>
  <div class="ring" :style="{ width: `${size}px`, height: `${size}px` }" role="img" aria-label="loading progress">
    <svg :width="size" :height="size" :viewBox="`0 0 ${viewBox} ${viewBox}`" class="ring-svg">
      <defs>
        <linearGradient :id="gradientId" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="#7c3aed" />
          <stop offset="50%" stop-color="#3b82f6" />
          <stop offset="100%" stop-color="#06b6d4" />
        </linearGradient>
      </defs>

      <circle
        class="ring-track"
        :cx="center"
        :cy="center"
        :r="radius"
        fill="none"
        :stroke-width="strokeWidth"
      />
      <circle
        class="ring-progress"
        :cx="center"
        :cy="center"
        :r="radius"
        fill="none"
        :stroke="`url(#${gradientId})`"
        :stroke-width="strokeWidth"
        stroke-linecap="round"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="dashOffset"
      />
    </svg>

    <div class="ring-label">
      <div class="ring-percent">{{ displayPercent }}%</div>
      <div v-if="caption" class="ring-caption">{{ caption }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    percent: number
    size?: number
    strokeWidth?: number
    caption?: string
  }>(),
  {
    size: 92,
    strokeWidth: 10,
    caption: '',
  },
)

const viewBox = 100
const center = viewBox / 2
const radius = computed(() => (viewBox - props.strokeWidth) / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)

const gradientId = `ring-grad-${Math.random().toString(36).slice(2)}`

const displayPercent = ref(0)
watch(
  () => props.percent,
  (next) => {
    const v = Number.isFinite(next) ? next : 0
    const clamped = Math.max(0, Math.min(100, Math.round(v)))
    displayPercent.value = clamped
  },
  { immediate: true },
)

const dashOffset = computed(() => {
  const p = displayPercent.value / 100
  return circumference.value * (1 - p)
})
</script>

<style scoped>
.ring {
  position: relative;
  display: grid;
  place-items: center;
  contain: layout paint style;
  will-change: transform, opacity;
}

.ring-svg {
  transform: rotate(-90deg);
  overflow: visible;
}

.ring-track {
  stroke: rgba(255, 255, 255, 0.16);
}

.ring-progress {
  transition: stroke-dashoffset 320ms cubic-bezier(0.4, 0, 0.2, 1);
  filter: drop-shadow(0 10px 20px rgba(59, 130, 246, 0.2));
  will-change: stroke-dashoffset;
}

.ring-label {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  text-align: center;
  padding-top: 2px;
}

.ring-percent {
  font-weight: 800;
  font-size: 20px;
  letter-spacing: 0.3px;
  color: rgba(255, 255, 255, 0.92);
  text-shadow: 0 10px 30px rgba(0, 0, 0, 0.28);
}

.ring-caption {
  margin-top: 2px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.62);
}
</style>
