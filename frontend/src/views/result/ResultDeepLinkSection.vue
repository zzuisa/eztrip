<template>
  <a-modal :open="visible" title="Google Maps 深链规划" width="900px" :footer="null" @cancel="$emit('close')">
    <div class="deep-link-builder">
      <div class="deep-link-actions">
        <a-space wrap>
          <a-button type="primary" @click="$emit('add-current-day', currentDayIndex)">一键加入当天行程</a-button>
          <a-button @click="$emit('build-from-selection')">根据当前选择生成</a-button>
          <a-button @click="$emit('open-google-maps')" :disabled="items.length === 0">打开 Google Maps</a-button>
          <a-button @click="$emit('copy-url')" :disabled="items.length === 0">复制深链</a-button>
        </a-space>
      </div>

      <a-select
        :value="currentDayIndex"
        @update:value="$emit('update:current-day-index', $event)"
        style="width: 180px; margin: 16px 0"
        :options="dayOptions"
      />

      <a-list :data-source="items" bordered>
        <template #renderItem="{ item, index }">
          <a-list-item>
            <div class="deep-link-item-row">
              <div class="deep-link-item-main">
                <div class="deep-link-item-title">{{ index + 1 }}. {{ item.name }}</div>
                <div class="deep-link-item-sub">{{ item.address || '未提供地址' }}</div>
              </div>
              <a-space wrap>
                <a-button size="small" @click="$emit('move-item', index, 'up')" :disabled="index === 0">↑</a-button>
                <a-button size="small" @click="$emit('move-item', index, 'down')" :disabled="index === items.length - 1">↓</a-button>
                <a-button size="small" danger @click="$emit('remove-item', index)">删除</a-button>
                <a-button size="small" @click="$emit('copy-item-address', item)">复制地址</a-button>
              </a-space>
            </div>
          </a-list-item>
        </template>
      </a-list>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
defineProps<{ visible: boolean; currentDayIndex: number; dayOptions: any[]; items: any[] }>()
defineEmits(['add-current-day', 'build-from-selection', 'open-google-maps', 'copy-url', 'move-item', 'remove-item', 'copy-item-address', 'update:current-day-index', 'close'])
</script>
