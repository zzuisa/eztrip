<template>
  <div v-if="rows.length" class="agent-timeline" data-testid="agent-timeline">
    <div class="at-head">
      <span class="at-title">Agent 协作</span>
      <span class="at-count">{{ doneCount }}/{{ rows.length }}</span>
    </div>

    <ul class="at-list">
      <li
        v-for="row in rows"
        :key="row.key"
        class="at-row"
        :class="`at-${row.status}`"
      >
        <span class="at-icon">{{ row.icon }}</span>
        <span class="at-body">
          <span class="at-agent">{{ row.label }}</span>
          <span class="at-detail">{{ row.detail }}</span>
        </span>
        <span class="at-state">
          <span v-if="row.status === 'done'" class="at-tick">✓</span>
          <span v-else-if="row.status === 'error'" class="at-err">!</span>
          <span v-else class="at-spin" />
        </span>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

export interface AgentPhase {
  agent: string
  status: string
  detail: string
}

const props = withDefaults(defineProps<{ phases?: AgentPhase[] }>(), {
  phases: () => [],
})

// 各 Agent 的展示元信息（与后端 agents/ 里的工具名一一对应）
const META: Record<string, { icon: string; label: string }> = {
  supervisor: { icon: '🧭', label: '总调度' },
  xhs_insight: { icon: '📕', label: '小红书灵感' },
  poi_scout: { icon: '📍', label: '景点侦察' },
  food_scout: { icon: '🍽️', label: '餐饮侦察' },
  composer: { icon: '✍️', label: '行程编排' },
  search_places: { icon: '🔎', label: '地点检索' },
  search_places_near_anchor: { icon: '🔎', label: '就近检索' },
}

/**
 * 后端对同一个 agent 会先后发 running / done。
 * 这里按「agent + detail」折叠成一行，后到的状态覆盖先到的，避免时间轴刷屏。
 */
const rows = computed(() => {
  const byKey = new Map<string, { key: string; icon: string; label: string; detail: string; status: string }>()
  for (const p of props.phases || []) {
    const meta = META[p.agent] || { icon: '⚙️', label: p.agent || 'agent' }
    // 同一个 agent 的同一件事（detail 里通常带「第N天」）折叠成一行
    const key = `${p.agent}::${p.detail.replace(/[（(].*$/, '')}`
    byKey.set(key, {
      key,
      icon: meta.icon,
      label: meta.label,
      detail: p.detail || meta.label,
      status: p.status || 'running',
    })
  }
  return Array.from(byKey.values())
})

const doneCount = computed(() => rows.value.filter((r) => r.status === 'done').length)
</script>

<style scoped>
.agent-timeline {
  width: 100%;
  max-height: 220px;
  overflow-y: auto;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.at-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.at-title {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: rgba(255, 255, 255, 0.86);
}

.at-count {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
  font-variant-numeric: tabular-nums;
}

.at-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.at-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  line-height: 1.35;
  color: rgba(255, 255, 255, 0.72);
}

.at-icon {
  flex: 0 0 auto;
  font-size: 14px;
}

.at-body {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.at-agent {
  font-weight: 600;
  color: rgba(255, 255, 255, 0.9);
}

.at-detail {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgba(255, 255, 255, 0.6);
}

.at-state {
  flex: 0 0 auto;
  width: 16px;
  text-align: center;
}

.at-tick {
  color: #52d17c;
  font-weight: 700;
}

.at-err {
  color: #ff9a62;
  font-weight: 700;
}

.at-spin {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 2px solid rgba(255, 255, 255, 0.25);
  border-top-color: rgba(255, 255, 255, 0.85);
  animation: at-rotate 0.8s linear infinite;
}

.at-done .at-detail {
  color: rgba(255, 255, 255, 0.5);
}

@keyframes at-rotate {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .at-spin {
    animation: none;
  }
}
</style>
