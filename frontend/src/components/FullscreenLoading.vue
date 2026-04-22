<template>
  <teleport to="body">
    <div
      v-show="visible"
      ref="overlayEl"
      class="fs-overlay"
      aria-live="polite"
      aria-busy="true"
      data-testid="fullscreen-loading-overlay"
    >
      <div class="fs-backdrop" />
      <div class="fs-glow" />

      <div class="fs-content fs-content-dark" data-testid="fullscreen-loading-dialog">
        <div class="stage-card" :class="`stage-${stageMeta.motion}`">
          <div class="stage-icon">{{ stageMeta.icon }}</div>
          <div class="stage-meta">
            <div class="stage-label">{{ stageMeta.label }}</div>
            <div class="stage-sub">{{ status }}</div>
          </div>
        </div>

        <ProgressRing :percent="percent" :caption="ringCaption" :size="96" />

        <div class="fs-text">
          <div class="fs-title">{{ title }}</div>
          <div class="fs-status">{{ status }}</div>
        </div>

        <div v-if="logs.length" class="fs-logs fs-logs-dark">
          <div v-for="(line, idx) in logs" :key="`line-${idx}`" class="fs-log-line">
            {{ line }}
          </div>
        </div>

        <div class="fs-actions">
          <a-button size="large" class="fs-cancel" :disabled="cancelDisabled" @click="emit('cancel')">
            取消
          </a-button>
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import ProgressRing from './ProgressRing.vue'
import { resolveStageMeta } from '@/utils/loading-stage-animation'

const props = withDefaults(
  defineProps<{
    visible: boolean
    percent: number
    title?: string
    status: string
    stage?: string
    logs?: string[]
    cancelDisabled?: boolean
  }>(),
  {
    title: '正在生成行程',
    logs: () => [],
    cancelDisabled: false,
  },
)

const emit = defineEmits<{
  (e: 'cancel'): void
}>()

const overlayEl = ref<HTMLDivElement | null>(null)
const getOverlayEl = () => overlayEl.value
defineExpose({ getOverlayEl })

watch(
  () => props.visible,
  (next) => {
    if (typeof document === 'undefined') return
    document.body.style.overflow = next ? 'hidden' : ''
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  if (typeof document !== 'undefined') document.body.style.overflow = ''
})

const ringCaption = computed(() => {
  if (!Number.isFinite(props.percent)) return ''
  if (props.percent >= 100) return '完成'
  if (props.percent <= 5) return '连接中'
  return '生成中'
})

const stageMeta = computed(() => resolveStageMeta(props.stage))
</script>

<style scoped>
.fs-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  pointer-events: auto;
  display: grid;
  place-items: center;
  padding: 24px;
  will-change: transform, opacity;
  transform: translateZ(0);
  contain: layout paint style;
}

.fs-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(15, 23, 42, 0.62);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
}

.fs-glow {
  position: absolute;
  inset: -40%;
  background:
    radial-gradient(closest-side at 30% 30%, rgba(124, 58, 237, 0.35), transparent 60%),
    radial-gradient(closest-side at 70% 20%, rgba(59, 130, 246, 0.28), transparent 58%),
    radial-gradient(closest-side at 60% 80%, rgba(6, 182, 212, 0.22), transparent 62%);
  filter: blur(18px);
  opacity: 0.9;
  animation: breathe 3.6s ease-in-out infinite;
  transform: translateZ(0);
}

@keyframes breathe {
  0% {
    transform: scale(1) translateZ(0);
    opacity: 0.85;
  }
  50% {
    transform: scale(1.05) translateZ(0);
    opacity: 1;
  }
  100% {
    transform: scale(1) translateZ(0);
    opacity: 0.85;
  }
}

.fs-content {
  position: relative;
  width: min(520px, 100%);
  border-radius: 20px;
  padding: 22px 18px 18px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  box-shadow:
    0 30px 80px rgba(0, 0, 0, 0.55),
    0 0 0 1px rgba(255, 255, 255, 0.04) inset;
  display: grid;
  justify-items: center;
  gap: 14px;
  transform: translateZ(0);
}

.fs-content-dark {
  background: linear-gradient(165deg, rgba(15, 23, 42, 0.96), rgba(30, 41, 59, 0.94));
  border: 1px solid rgba(148, 163, 184, 0.26);
  box-shadow:
    0 36px 90px rgba(2, 6, 23, 0.72),
    0 0 0 1px rgba(148, 163, 184, 0.08) inset;
}

.stage-card {
  width: 100%;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(255, 255, 255, 0.06);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  will-change: transform, opacity;
}

.stage-icon {
  width: 32px;
  height: 32px;
  border-radius: 999px;
  display: grid;
  place-items: center;
  background: rgba(255, 255, 255, 0.14);
}

.stage-meta {
  flex: 1;
  min-width: 0;
}

.stage-label {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.88);
  font-weight: 700;
}

.stage-sub {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.65);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stage-pulse {
  animation: stagePulse 1.2s ease-in-out infinite;
}

.stage-flow {
  background-image: linear-gradient(120deg, rgba(59, 130, 246, 0.12), rgba(124, 58, 237, 0.2), rgba(59, 130, 246, 0.12));
  background-size: 200% 100%;
  animation: stageFlow 2.2s linear infinite;
}

.stage-scan {
  position: relative;
  overflow: hidden;
}

.stage-scan::after {
  content: '';
  position: absolute;
  inset: 0;
  transform: translateX(-110%);
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.2), transparent);
  animation: stageScan 1.8s ease-in-out infinite;
}

.stage-spark {
  box-shadow: 0 0 0 rgba(124, 58, 237, 0.3);
  animation: stageSpark 1.4s ease-out infinite;
}

@keyframes stagePulse {
  0%, 100% { transform: scale(1); opacity: 0.92; }
  50% { transform: scale(1.01); opacity: 1; }
}

@keyframes stageFlow {
  from { background-position: 0% 50%; }
  to { background-position: 100% 50%; }
}

@keyframes stageScan {
  to { transform: translateX(110%); }
}

@keyframes stageSpark {
  0% { box-shadow: 0 0 0 rgba(124, 58, 237, 0.32); }
  70% { box-shadow: 0 0 0 10px rgba(124, 58, 237, 0); }
  100% { box-shadow: 0 0 0 rgba(124, 58, 237, 0); }
}

.fs-text {
  text-align: center;
}

.fs-title {
  font-size: 16px;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.92);
  letter-spacing: 0.2px;
}

.fs-status {
  margin-top: 6px;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.72);
}

.fs-logs {
  width: 100%;
  max-height: 170px;
  overflow: auto;
  padding: 10px 10px;
  border-radius: 14px;
  background: rgba(15, 23, 42, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.fs-logs-dark {
  background: rgba(2, 6, 23, 0.56);
  border-color: rgba(148, 163, 184, 0.24);
}

.fs-log-line {
  font-size: 12px;
  line-height: 18px;
  color: rgba(255, 255, 255, 0.74);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.fs-actions {
  margin-top: 4px;
  width: 100%;
  display: flex;
  justify-content: center;
}

.fs-cancel {
  width: min(240px, 100%);
  border-radius: 12px;
}

@media (prefers-reduced-motion: reduce) {
  .fs-glow {
    animation: none;
  }
}
</style>
