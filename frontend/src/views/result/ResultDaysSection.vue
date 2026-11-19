<template>
  <a-card title="📅 每日行程" :bordered="false" class="days-card">
    <a-collapse v-model:activeKey="activeDays" accordion>
      <a-collapse-panel
        v-for="(day, index) in days"
        :key="index"
        :id="`day-${index}`"
      >
        <template #header>
          <div class="day-header">
            <span class="day-title">{{ day.display_title || `第${getDayIndex(day, index) + 1}天` }}</span>
            <span class="day-date">{{ day.date }}</span>
            <span class="day-meals-count">{{ getDayMealCount(day) }}</span>
          </div>
        </template>

        <div class="day-info">
          <div class="info-row">
            <span class="label">📝 行程描述:</span>
            <span class="value">{{ day.description }}</span>
          </div>
          <div class="info-row reason-row">
            <span class="label">🧭 安排依据:</span>
            <div class="value reason-value">
              <ul class="reason-bullet-list">
                <li v-for="(bullet, bulletIdx) in getArrangementReasonBullets(day, index)" :key="`reason-${index}-${bulletIdx}`">
                  {{ bullet }}
                </li>
              </ul>
              <a-button
                v-if="shouldShowReasonToggle(day)"
                type="link"
                size="small"
                class="reason-toggle"
                @click="toggleReasonExpanded(index)"
              >
                {{ reasonExpanded[index] ? '收起' : '展开' }}
              </a-button>
            </div>
          </div>
          <div class="info-row">
            <span class="label">🚗 交通方式:</span>
            <span class="value">{{ day.transportation }}</span>
          </div>
          <div class="info-row">
            <span class="label">🏨 住宿:</span>
            <span class="value">{{ day.accommodation }}</span>
          </div>
        </div>

        <div class="timeline-header-row">
          <a-divider orientation="left" class="timeline-divider">🕒 行程总览</a-divider>
          <a-space wrap class="day-actions">
            <a-button type="primary" @click="$emit('add-day-to-deep-link', index)">一键加入当天行程</a-button>
            <a-button @click="$emit('open-google-maps-collection')">生成当前深链</a-button>
          </a-space>
        </div>
        <a-list :data-source="getTimelineSlots(day)" :grid="{ gutter: 16, column: 1 }">
          <template #renderItem="{ item: slot }">
            <a-list-item>
              <a-card size="small" class="timeline-card timeline-card-group">
                <template #title>
                  <span>{{ slot.label }}</span>
                </template>
                <div v-if="slot.entries.length === 0" class="timeline-empty">暂无安排</div>
                <div v-else class="timeline-slot-content compact-slot-content">
                  <template v-for="entry in slot.entries" :key="entry.key">
                    <a-card
                      :id="entry.cardId"
                      size="small"
                      class="timeline-card compact-entry-card"
                      :class="{ 'timeline-card-active': selectedPlaceKey === entry.key }"
                      @click="$emit('focus-place', entry)"
                    >
                      <div class="entry-layout">
                        <div class="entry-image-wrap" v-if="entry.kind === 'attraction'">
                          <img
                            :src="resolveAttractionImage(day, entry.title) || fallbackImage"
                            :alt="entry.title"
                            class="entry-image"
                            loading="lazy"
                            decoding="async"
                            @error="handleImageError"
                          />
                          <div class="price-tag price-tag-badge">门票 {{ formatPrice(entry.ticket_price) }}</div>
                        </div>
                        <div class="entry-body">
                          <div class="entry-head">
                            <span class="entry-title">{{ entry.title }}</span>
                            <a-space wrap>
                              <a-tag v-if="entry.kind === 'attraction'" color="gold">{{ formatPrice(entry.ticket_price) }}</a-tag>
                              <a-tag v-if="entry.kind === 'attraction' && entry.preference_matched" color="magenta">偏好匹配</a-tag>
                              <a-tag v-if="entry.kind !== 'attraction'" color="blue">{{ getMealLabel(entry.mealType) }}</a-tag>
                              <a-button size="small" type="primary" ghost @click.stop="$emit('navigate', entry.title, entry.latitude, entry.longitude)">
                                导航
                              </a-button>
                              <a-button size="small" @click.stop="$emit('toggle-favorite', entry)">收藏</a-button>
                              <a-button size="small" @click.stop="$emit('copy-address', entry.address)">复制地址</a-button>
                            </a-space>
                          </div>
                          <div class="entry-meta">
                            <div><strong>时间:</strong> {{ entry.time }}</div>
                            <div><strong>停留:</strong> {{ entry.kind === 'attraction' ? getAttractionDuration(day, entry.title) : getMealDuration(entry.mealType) }}</div>
                            <div><strong>位置:</strong> {{ entry.address || '未提供' }}</div>
                            <div><strong>说明:</strong> {{ entry.description }}</div>
                            <div v-if="entry.kind === 'attraction' && entry.preference_reason">
                              <strong>偏好说明:</strong> {{ entry.preference_reason }}
                            </div>
                            <div v-if="entry.route_desc"><strong>路线:</strong> {{ entry.route_desc }}</div>
                          </div>
                        </div>
                      </div>
                    </a-card>
                  </template>
                </div>
              </a-card>
            </a-list-item>
          </template>
        </a-list>

        <a-divider v-if="day.hotel" orientation="left">🏨 住宿推荐</a-divider>
        <a-card v-if="day.hotel" size="small" class="hotel-card">
          <template #title>
            <span class="hotel-title">{{ day.hotel.name }}</span>
          </template>
          <a-descriptions :column="2" size="small">
            <a-descriptions-item label="地址">{{ day.hotel.address }}</a-descriptions-item>
            <a-descriptions-item label="类型">{{ day.hotel.type }}</a-descriptions-item>
            <a-descriptions-item label="价格范围">{{ day.hotel.price_range }}</a-descriptions-item>
            <a-descriptions-item label="评分">{{ day.hotel.rating }}⭐</a-descriptions-item>
            <a-descriptions-item label="距离" :span="2">{{ day.hotel.distance }}</a-descriptions-item>
          </a-descriptions>
        </a-card>

        <a-divider orientation="left">🍽️ 餐饮安排</a-divider>
        <a-list :data-source="day.meals" :grid="{ gutter: 16, column: 1 }">
          <template #renderItem="{ item }">
            <a-list-item>
              <a-card
                :id="getMealCardId(getDayIndex(day, index), item.type)"
                size="small"
                class="meal-card"
                :class="{ 'meal-card-active': selectedPlaceKey === getPlaceKey(getDayIndex(day, index), item.name, 'meal', item.type) }"
                @click="$emit('focus-meal', getDayIndex(day, index), item)"
              >
                <template #title>
                  <span>{{ getMealLabel(item.type) }} · {{ item.name }}</span>
                </template>
                <template #extra>
                  <a-tag color="blue">{{ item.time }}</a-tag>
                </template>
                <div class="meal-meta">
                  <a-tag color="purple">{{ item.address || '未提供地址' }}</a-tag>
                  <a-tag color="gold">{{ formatPrice(item.estimated_cost) }}</a-tag>
                </div>
                <p><strong>描述:</strong> {{ item.description }}</p>
                <p><strong>路线:</strong> {{ item.route_desc }}</p>
              </a-card>
            </a-list-item>
          </template>
        </a-list>
      </a-collapse-panel>
    </a-collapse>
  </a-card>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { getDayIndex, getTimelineSlots as buildTimelineSlots } from './result-helpers'

const props = defineProps<{ days: any[]; selectedPlaceKey: string }>()
const emit = defineEmits(['add-day-to-deep-link', 'open-google-maps-collection', 'focus-place', 'toggle-favorite', 'copy-address', 'navigate', 'focus-meal', 'image-error'])
const activeDays = defineModel<number[]>('activeDays', { default: [0] })
const reasonExpanded = ref<Record<number, boolean>>({})

const getTimelineSlots = (day: any) => buildTimelineSlots(day)
const shouldShowReasonToggle = (day: any) => String(day?.arrangement_reason || '').length > 80
const toggleReasonExpanded = (dayIndex: number) => { reasonExpanded.value = { ...reasonExpanded.value, [dayIndex]: !reasonExpanded.value[dayIndex] } }
const getArrangementReasonBullets = (day: any, dayIndex: number) => {
  const reason = String(day?.arrangement_reason || '')
  const theme = String(day?.display_title || day?.title || '').replace(/第\d+天[｜|·:\-]?\s*/g, '').trim() || '区域串联'
  const attractionCount = Array.isArray(day?.attractions) ? day.attractions.length : 0
  const mealCount = Array.isArray(day?.meals) ? day.meals.length : 0
  const rhythm = attractionCount >= 6 ? '高密度短停留' : attractionCount >= 4 ? '中等节奏' : '轻松节奏'
  const preferenceHint = reason.includes('偏好') ? '优先匹配你的偏好关键词与主题标签' : '优先兼顾体验完整度与舒适度'
  return [
    `地理连贯性：围绕“${theme}”就近串联点位，减少来回折返。`,
    `节奏控制：当天约 ${attractionCount} 个景点、${mealCount} 餐，采用${rhythm}安排。`,
    `偏好匹配：${preferenceHint}。`,
  ]
}
const getDayMealCount = (day: any) => Array.isArray(day?.meals) ? `${day.meals.length} 餐` : '0 餐'
const formatPrice = (value: any) => value === undefined || value === null || value === '' ? '免费' : `€${Number(value)}`
const getAttractionDuration = (_day: any, _title: string) => '—'
const getMealDuration = (_mealType: string) => '—'
const getMealLabel = (type: string) => type === 'breakfast' ? '早餐' : type === 'lunch' ? '午餐' : type === 'dinner' ? '晚餐' : '餐饮'
const getPlaceKey = (dayIndex: number, name: string, kind: 'attraction' | 'meal', mealType?: string) => `${dayIndex}-${kind}-${mealType || ''}-${name}`
const getMealCardId = (dayIndex: number, mealType: string) => `day-${dayIndex}-meal-${mealType}`
const getAttractionCardId = (dayIndex: number, index: number) => `day-${dayIndex}-attraction-${index}`
const resolveAttractionImage = (day: any, name: string) => {
  const item = (Array.isArray(day?.attractions) ? day.attractions : []).find((a: any) => a.name === name)
  return item?.image_url || item?.image || item?.photo_url || item?.thumbnail || ''
}
const fallbackImage = 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI0MDAiIGhlaWdodD0iMzAwIj48cmVjdCB3aWR0aD0iNDAwIiBoZWlnaHQ9IjMwMCIgZmlsbD0iI2U1ZTdlYiIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBkb21pbmFudC1iYXNlbGluZT0ibWlkZGxlIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmb250LWZhbWlseT0ic2Fucy1zZXJpZiIgZm9udC1zaXplPSIxOCIiIGZpbGw9IiM5Y2E0YWYiPuaVsOa1i+aJgOaKpeWtlOeUqDwvdGV4dD48L3N2Zz4='
const handleImageError = (event: Event) => {
  const img = event.target as HTMLImageElement
  if (img?.dataset?.fallbackApplied) return
  img.dataset.fallbackApplied = '1'
  img.src = fallbackImage
}
</script>

<style scoped>
.timeline-card-group {
  border-radius: 14px;
  overflow: hidden;
}

.compact-slot-content {
  display: grid;
  gap: 14px;
}

.compact-entry-card {
  border-radius: 16px;
  overflow: hidden;
  border: 1px solid #e8edf5;
  box-shadow: 0 6px 18px rgba(15, 23, 42, 0.05);
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.compact-entry-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.10);
  border-color: #c7d2fe;
}

.entry-image-wrap {
  width: 200px;
  min-height: 132px;
  flex: 0 0 200px;
  position: relative;
  overflow: hidden;
  border-radius: 12px;
  background: linear-gradient(135deg, #e8f0ff, #f6f8fc);
}

.entry-image {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
}

.price-tag-badge {
  position: absolute;
  right: 8px;
  top: 8px;
}

.entry-body {
  min-width: 0;
  flex: 1;
}

.entry-head {
  display: flex;
  gap: 10px;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
}

.entry-title {
  font-weight: 700;
  font-size: 15px;
  color: #0f172a;
}

.entry-meta {
  margin-top: 10px;
  color: #334155;
  display: grid;
  gap: 6px;
}

.meal-card,
.hotel-card {
  border-radius: 14px;
  overflow: hidden;
}

.timeline-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin: 12px 0 6px;
}

.timeline-divider {
  flex: 1 1 auto;
  min-width: 180px;
  margin: 0;
}

.day-actions {
  margin-bottom: 20px !important; 
}

.meal-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}

.timeline-empty {
  padding: 18px 0;
  text-align: center;
  color: #94a3b8;
}

@media (max-width: 768px) {
  .entry-layout {
    flex-direction: column;
  }

  .entry-image-wrap {
    width: 100%;
    min-height: 180px;
    flex-basis: auto;
  }
}
</style>
