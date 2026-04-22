<template>
  <div class="result-container">
    <!-- 页面头部 -->
    <div class="page-header">
      <a-button class="back-button" size="large" @click="goBack">
        ← 返回首页
      </a-button>
      <a-space size="middle" wrap>
        <a-button v-if="!editMode" @click="toggleEditMode" type="default">
          ✏️ 编辑行程
        </a-button>
        <a-button v-else @click="saveChanges" type="primary">
          💾 保存修改
        </a-button>
        <a-button v-if="editMode" @click="cancelEdit" type="default">
          ❌ 取消编辑
        </a-button>
        <a-button @click="openDeepLinkBuilder" type="primary">
          🧭 深链规划
        </a-button>

        <!-- 导出按钮 -->
        <a-dropdown v-if="!editMode">
          <template #overlay>
            <a-menu>
              <a-menu-item key="image" @click="exportAsImage">
                📷 导出为图片
              </a-menu-item>
              <a-menu-item key="pdf" @click="exportAsPDF">
                📄 导出为PDF
              </a-menu-item>
            </a-menu>
          </template>
          <a-button type="default">
            📥 导出行程 <DownOutlined />
          </a-button>
        </a-dropdown>
      </a-space>
    </div>

    <div v-if="tripPlan" class="content-wrapper">
      <!-- 侧边导航 -->
      <div class="side-nav">
        <a-affix :offset-top="80">
          <a-menu mode="inline" :selected-keys="[activeSection]" @click="scrollToSection">
            <a-menu-item key="overview">
              <span>📋 行程概览</span>
            </a-menu-item>
            <a-menu-item key="budget" v-if="tripPlan.budget">
              <span>💰 预算明细</span>
            </a-menu-item>
            <a-menu-item key="map">
              <span>📍 景点地图</span>
            </a-menu-item>
            <a-sub-menu key="days" title="📅 每日行程">
              <a-menu-item v-for="(day, index) in tripPlan.days" :key="`day-${index}`">
                第{{ day.day_index + 1 }}天
              </a-menu-item>
            </a-sub-menu>
            <a-menu-item key="weather" v-if="tripPlan.weather_info && tripPlan.weather_info.length > 0">
              <span>🌤️ 天气信息</span>
            </a-menu-item>
          </a-menu>
        </a-affix>
      </div>

      <!-- 主内容区 -->
      <div class="main-content">
        <!-- 顶部信息区:左侧概览+预算,右侧地图 -->
        <div class="top-info-section">
          <!-- 左侧:行程概览和预算明细 -->
          <div class="left-info">
            <!-- 行程概览 -->
            <a-card id="overview" :title="`${tripPlan.city} · RogueTrip旅行计划`" :bordered="false" class="overview-card">
              <div class="overview-content">
                <div class="info-item">
                  <span class="info-label">📅 日期:</span>
                  <span class="info-value">{{ tripPlan.start_date }} 至 {{ tripPlan.end_date }}</span>
                </div>
                <div class="info-item">
                  <span class="info-label">💡 建议:</span>
                  <span class="info-value">{{ tripPlan.overall_suggestions }}</span>
                </div>
              </div>
            </a-card>

            <!-- 预算明细 -->
            <a-card id="budget" v-if="tripPlan.budget" title="💰 预算明细" :bordered="false" class="budget-card">
              <div class="budget-grid">
                <div class="budget-item">
                  <div class="budget-label">景点门票</div>
                  <div class="budget-value">{{ formatCurrency(tripPlan.budget.total_attractions) }}</div>
                </div>
                <div class="budget-item">
                  <div class="budget-label">酒店住宿</div>
                  <div class="budget-value">{{ formatCurrency(tripPlan.budget.total_hotels) }}</div>
                </div>
                <div class="budget-item">
                  <div class="budget-label">餐饮费用</div>
                  <div class="budget-value">{{ formatCurrency(tripPlan.budget.total_meals) }}</div>
                </div>
                <div class="budget-item">
                  <div class="budget-label">交通费用</div>
                  <div class="budget-value">{{ formatCurrency(tripPlan.budget.total_transportation) }}</div>
                </div>
              </div>
              <div class="budget-total">
                <span class="total-label">预估总费用</span>
                <span class="total-value">{{ formatCurrency(tripPlan.budget.total) }}</span>
              </div>
            </a-card>
          </div>

          <!-- 右侧:地图 -->
          <div class="right-map">
            <a-card id="map" title="📍 景点地图" :bordered="false" class="map-card">
              <div class="map-wrap">
                <div id="mapbox-container" class="mapbox-container"></div>
                <div class="map-story-panel" v-if="mapStory.visible">
                  <div class="map-story-cards">
                    <div class="story-card current" :style="{ opacity: 1 - mapStory.transitionProgress }">
                      <img :src="mapStory.current.image" :alt="mapStory.current.name" class="story-image" @error="handleImageError" />
                      <div class="story-content">
                        <div class="story-title">{{ mapStory.current.name }}</div>
                        <div class="story-desc">{{ mapStory.current.description || '推荐停留并打卡拍照。' }}</div>
                        <div class="story-meta">{{ mapStory.current.address || '地址待补充' }}</div>
                      </div>
                    </div>
                    <div v-if="mapStory.next" class="story-card next" :style="{ opacity: mapStory.transitionProgress }">
                      <img :src="mapStory.next.image" :alt="mapStory.next.name" class="story-image" @error="handleImageError" />
                      <div class="story-content">
                        <div class="story-title">下一站：{{ mapStory.next.name }}</div>
                        <div class="story-desc">{{ mapStory.next.description || '即将抵达下一处精彩景点。' }}</div>
                        <div class="story-meta">{{ mapStory.next.address || '地址待补充' }}</div>
                      </div>
                    </div>
                  </div>
                </div>
                <div class="map-legend" v-if="tripPlan?.days?.length">
                  <div
                    v-for="(day, idx) in tripPlan.days"
                    :key="`legend-${idx}`"
                    class="legend-item"
                  >
                    <span class="legend-dot" :style="{ backgroundColor: routeColors[idx % routeColors.length] }"></span>
                    <span>第{{ day.day_index + 1 }}天路线</span>
                  </div>
                </div>
              </div>
            </a-card>
          </div>
        </div>

        <!-- 每日行程:可折叠 -->
        <a-card title="📅 每日行程" :bordered="false" class="days-card">
          <a-collapse v-model:activeKey="activeDays" accordion>
            <a-collapse-panel
              v-for="(day, index) in tripPlan.days"
              :key="index"
              :id="`day-${index}`"
            >
              <template #header>
                <div class="day-header">
                  <span class="day-title">{{ day.display_title || `第${day.day_index + 1}天` }}</span>
                  <span class="day-date">{{ day.date }}</span>
                  <span class="day-meals-count">{{ getDayMealCount(day) }}</span>
                </div>
              </template>

              <!-- 行程基本信息 -->
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

              <!-- 行程总览（合并时间轴 + 经典安排） -->
              <a-divider orientation="left">🕒 行程总览</a-divider>
              <div class="mobile-action-strip">
                <a-space wrap>
                  <a-button type="primary" @click="addDayToDeepLink(index)">一键加入当天行程</a-button>
                  <a-button @click="openGoogleMapsCollection">生成当前深链</a-button>
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
                            @click="focusPlace(entry)"
                          >
                            <div class="entry-layout">
                              <div class="entry-image-wrap" v-if="entry.kind === 'attraction'">
                                <img
                                  :src="getAttractionImageByName(day, entry.title)"
                                  :alt="entry.title"
                                  class="entry-image"
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
                                    <a-button size="small" type="primary" ghost @click.stop="openGoogleMapsNavigate(entry.title, entry.latitude, entry.longitude)">
                                      导航
                                    </a-button>
                                    <a-button size="small" @click.stop="toggleFavorite(entry)">收藏</a-button>
                                    <a-button size="small" @click.stop="copyAddress(entry.address)">复制地址</a-button>
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

              <!-- 酒店推荐 -->
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

              <!-- 餐饮安排 -->
              <a-divider orientation="left">🍽️ 餐饮安排</a-divider>
              <a-list :data-source="day.meals" :grid="{ gutter: 16, column: 1 }">
                <template #renderItem="{ item }">
                  <a-list-item>
                    <a-card
                      :id="getMealCardId(day.day_index, item.type)"
                      size="small"
                      class="meal-card"
                      :class="{ 'meal-card-active': selectedPlaceKey === getPlaceKey(day.day_index, item.name, 'meal', item.type) }"
                      @click="focusMeal(day.day_index, item)"
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

        <a-card id="trip-poster" :bordered="false" class="poster-card">
          <TripPosterGallery :story="posterStory" />
        </a-card>

        <a-card id="weather" v-if="tripPlan.weather_info && tripPlan.weather_info.length > 0" title="天气信息" style="margin-top: 20px" :bordered="false">
        <a-list
          :data-source="tripPlan.weather_info"
          :grid="{ gutter: 16, column: 3 }"
        >
          <template #renderItem="{ item }">
            <a-list-item>
              <a-card size="small" class="weather-card">
                <div class="weather-date">{{ item.date }}</div>
                <div class="weather-info-row">
                  <span class="weather-icon">☀️</span>
                  <div>
                    <div class="weather-label">白天</div>
                    <div class="weather-value">{{ item.day_weather }} {{ item.day_temp }}°C</div>
                  </div>
                </div>
                <div class="weather-info-row">
                  <span class="weather-icon">🌙</span>
                  <div>
                    <div class="weather-label">夜间</div>
                    <div class="weather-value">{{ item.night_weather }} {{ item.night_temp }}°C</div>
                  </div>
                </div>
                <div class="weather-wind">
                  💨 {{ item.wind_direction }} {{ item.wind_power }}
                </div>
              </a-card>
            </a-list-item>
          </template>
        </a-list>
        </a-card>
      </div>
    </div>

    <a-modal v-model:open="deepLinkVisible" title="Google Maps 深链规划" width="900px" :footer="null">
      <div class="deep-link-builder">
        <div class="deep-link-actions">
          <a-space wrap>
            <a-button type="primary" @click="addCurrentDayToDeepLink(currentDeepLinkDayIndex)">一键加入当天行程</a-button>
            <a-button @click="buildDeepLinkFromSelection">根据当前选择生成</a-button>
            <a-button @click="openDeepLinkInGoogleMaps" :disabled="deepLinkItems.length === 0">打开 Google Maps</a-button>
            <a-button @click="copyDeepLinkUrl" :disabled="deepLinkItems.length === 0">复制深链</a-button>
          </a-space>
        </div>

        <a-select v-model:value="currentDeepLinkDayIndex" style="width: 180px; margin: 16px 0" :options="deepLinkDayOptions" />

        <a-list :data-source="deepLinkItems" bordered>
          <template #renderItem="{ item, index }">
            <a-list-item>
              <div class="deep-link-item-row">
                <div class="deep-link-item-main">
                  <div class="deep-link-item-title">{{ index + 1 }}. {{ item.name }}</div>
                  <div class="deep-link-item-sub">{{ item.address || '未提供地址' }}</div>
                </div>
                <a-space wrap>
                  <a-button size="small" @click="moveDeepLinkItem(index, 'up')" :disabled="index === 0">↑</a-button>
                  <a-button size="small" @click="moveDeepLinkItem(index, 'down')" :disabled="index === deepLinkItems.length - 1">↓</a-button>
                  <a-button size="small" danger @click="removeDeepLinkItem(index)">删除</a-button>
                  <a-button size="small" @click="copyDeepLinkItemAddress(item)">复制地址</a-button>
                </a-space>
              </div>
            </a-list-item>
          </template>
        </a-list>
      </div>
    </a-modal>

    <a-empty v-if="!tripPlan" description="没有找到旅行计划数据">
      <template #image>
        <div style="font-size: 80px;">🗺️</div>
      </template>
      <template #description>
        <span style="color: #999;">暂无旅行计划数据,请先创建行程</span>
      </template>
      <a-button type="primary" @click="goBack">返回首页创建行程</a-button>
    </a-empty>

    <!-- 回到顶部按钮 -->
    <a-back-top :visibility-height="300">
      <div class="back-top-button">
        ↑
      </div>
    </a-back-top>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { DownOutlined } from '@ant-design/icons-vue'
import mapboxgl from 'mapbox-gl'
import html2canvas from 'html2canvas'
import jsPDF from 'jspdf'
import type { TripPlan } from '@/types'
import { fetchTravelPlanResultById } from '@/services/api'
import { buildPosterStory } from '@/services/poster-data-service'
import TripPosterGallery from '@/components/poster/TripPosterGallery.vue'
import { useItineraryEditing } from '@/composables/useItineraryEditing'
import { useResultPage } from '@/composables/useResultPage'

const router = useRouter()
const route = useRoute()
const tripPlan = ref<TripPlan | null>(null)
const attractionPhotos = ref<Record<string, string>>({})
const {
  activeSection,
  activeDays,
  selectedPlaceKey,
  deepLinkVisible,
  currentDeepLinkDayIndex,
  deepLinkItems,
} = useResultPage()
activeDays.value = [0] // 默认展开第一天（与旧行为保持一致）

const {
  editMode,
  toggleEditMode: startEditMode,
  cancelEdit: cancelEditMode,
  saveChanges: saveEdits,
} = useItineraryEditing(tripPlan, { itineraryIdHint: String(route.params.id || '') })
let map: any = null
let popup: any = null
const routeColors = ['#1890ff', '#52c41a', '#fa8c16', '#722ed1', '#eb2f96', '#13c2c2']
const MAP_DEFAULT_ZOOM = 12
const MAP_FOCUS_ZOOM = 15
const MAP_MEAL_FOCUS_ZOOM = 15.5
const MAP_STORY_ZOOM = 14.5
let markerInstances: any[] = []
let routeLayerIds: string[] = []
let routeSourceIds: string[] = []
const reasonExpanded = ref<Record<number, boolean>>({})
const posterStory = computed(() => buildPosterStory({
  city: tripPlan.value?.city || '',
  days: tripPlan.value?.days || [],
}))

const getFirstSentence = (text: string): string => {
  const normalized = String(text || '').trim()
  if (!normalized) return ''
  const parts = normalized.split(/[。！？.!?]/).map((part) => part.trim()).filter(Boolean)
  return parts[0] || normalized
}

const simplifyTheme = (rawTitle: string): string => {
  const normalized = String(rawTitle || '').replace(/第\d+天[｜|·:\-]?\s*/g, '').trim()
  if (!normalized) return '区域串联'
  return normalized.split(/[（(]/)[0].trim() || '区域串联'
}

const summarizeReason = (routeSummary: string): string => {
  const firstSentence = getFirstSentence(routeSummary)
  if (!firstSentence) return '区域串联与步行优化'
  return firstSentence.length > 22 ? `${firstSentence.slice(0, 22)}...` : firstSentence
}

const buildDisplayTitle = (dayIndex: number, title: string, routeSummary: string): string => {
  const theme = simplifyTheme(title)
  const reason = summarizeReason(routeSummary)
  return `第${dayIndex + 1}天｜${theme}（${reason}）`
}

const normalizeArrangementReason = (title: string, routeSummary: string): string => {
  const summary = String(routeSummary || '').trim()
  if (summary) return summary
  const theme = simplifyTheme(title)
  return `本日围绕${theme}安排，优先考虑景点连贯性与步行效率。`
}

const ensureArray = <T = any>(value: unknown): T[] => {
  if (Array.isArray(value)) return value as T[]
  if (value && typeof value === 'object') return Object.values(value as Record<string, T>)
  return []
}

const normalizeLocation = (raw: any): { latitude: number; longitude: number } | undefined => {
  if (!raw || typeof raw !== 'object') return undefined
  const latitude = Number(raw.latitude ?? raw.lat)
  const longitude = Number(raw.longitude ?? raw.lng)
  if (Number.isFinite(latitude) && Number.isFinite(longitude)) {
    return { latitude, longitude }
  }
  return undefined
}

const normalizeMeals = (meals: unknown) => {
  return ensureArray<any>(meals).map((meal) => ({
    ...meal,
    location: normalizeLocation(meal?.location ?? meal),
  }))
}

const normalizeAttractions = (attractions: unknown) => {
  return ensureArray<any>(attractions)
    .map((attraction) => ({
      ...attraction,
      address: attraction?.address || attraction?.formatted_address || '',
      description: attraction?.description || attraction?.editorial_summary || attraction?.route_desc || '',
      location: normalizeLocation(attraction?.location ?? attraction),
      ticket_price: attraction?.ticket_price ?? 0,
    }))
    .filter((attraction) => attraction?.name)
}

const normalizeActivities = (activities: unknown) => {
  return ensureArray<any>(activities)
    .map((activity) => ({
      ...activity,
      name: activity?.name || '',
      time: activity?.time || '',
      description: activity?.description || '',
      route_desc: activity?.route_desc || '',
      ticket_price: activity?.ticket_price ?? 0,
      address: activity?.address || '',
      latitude: activity?.latitude,
      longitude: activity?.longitude,
    }))
    .filter((activity) => activity.name)
}

const normalizeTripPlan = (raw: unknown): TripPlan | null => {
  if (!raw || typeof raw !== 'object') return null
  const plan = raw as Record<string, any>
  const rootAttractions = normalizeAttractions(plan.attractions)
  const sourceDays = Array.isArray(plan.days) ? plan.days : plan.itinerary
  const days = ensureArray(sourceDays).map((day: any, index: number) => {
    const dayIndex = typeof day?.day_index === 'number' ? day.day_index : index
    const title = String(day?.title || '')
    const routeSummary = String(day?.route_summary || '')
    const arrangementReason = normalizeArrangementReason(title, routeSummary)
    return {
      ...day,
      day_index: dayIndex,
      date: day?.date || `第${(day?.day ?? index + 1)}天`,
      display_title: buildDisplayTitle(dayIndex, title, routeSummary),
      arrangement_reason: arrangementReason,
      description: day?.description || routeSummary || title || '',
      transportation: day?.transportation || '公共交通',
      accommodation: day?.accommodation || '',
      activities: normalizeActivities(day?.activities),
      attractions: normalizeAttractions(day?.attractions ?? day?.activities),
      meals: normalizeMeals(day?.meals),
    }
  })

  days.forEach((day, index) => {
    if (day.attractions.length > 0) return
    // 兼容 itinerary.activities 为文本/弱结构时，按景点名进行匹配
    const activityText = ensureArray<any>(sourceDays[index]?.activities)
      .map((activity: any) => [activity?.name, activity?.description, activity?.route_desc].filter(Boolean).join(' '))
      .join(' ')
    const matched = rootAttractions.filter((attraction) => activityText.includes(attraction.name))
    if (matched.length > 0) {
      day.attractions = matched
      return
    }
    // 无法匹配时按天切片兜底，保证页面有可展示景点
    const fallbackStart = index * 3
    day.attractions = rootAttractions.slice(fallbackStart, fallbackStart + 3)
  })

  return {
    ...(plan as TripPlan),
    city: plan.city || plan.location || '',
    start_date: plan.start_date || '待定',
    end_date: plan.end_date || `${plan.days || days.length || 0}天行程`,
    overall_suggestions:
      plan.overall_suggestions ||
      ensureArray<string>(plan.tips).join('；') ||
      '',
    budget: plan.budget || (plan.total_budget
      ? {
          total_attractions: plan.total_budget.tickets ?? 0,
          total_hotels: plan.total_budget.hotels ?? 0,
          total_meals: plan.total_budget.food ?? 0,
          total_transportation: plan.total_budget.transport ?? 0,
          total: plan.total_budget.total ?? 0,
        }
      : undefined),
    budget_currency: plan?.total_budget?.currency || plan?.budget_currency || 'EUR',
    days,
  }
}

const shouldShowReasonToggle = (day: any): boolean => {
  const reason = String(day?.arrangement_reason || '')
  return reason.length > 80
}

const getDisplayedArrangementReason = (day: any, dayIndex: number): string => {
  const reason = String(day?.arrangement_reason || '')
  if (!reason) return '基于当天候选景点的空间连贯性与节奏平衡进行安排。'
  if (reasonExpanded.value[dayIndex] || reason.length <= 80) return reason
  return `${reason.slice(0, 80)}...`
}

const getArrangementReasonBullets = (day: any, dayIndex: number): string[] => {
  const reasonText = getDisplayedArrangementReason(day, dayIndex)
  const theme = simplifyTheme(String(day?.display_title || day?.title || ''))
  const attractionCount = Array.isArray(day?.attractions) ? day.attractions.length : 0
  const mealCount = Array.isArray(day?.meals) ? day.meals.length : 0
  const rhythm = attractionCount >= 6 ? '高密度短停留' : attractionCount >= 4 ? '中等节奏' : '轻松节奏'

  const preferenceHint = reasonText.includes('偏好')
    ? '优先匹配你的偏好关键词与主题标签'
    : reasonText.includes('citywalk') || reasonText.includes('城市漫步') || reasonText.includes('走马观花')
      ? '优先按城市漫步方式串联可步行点位'
      : '优先兼顾体验完整度与舒适度'

  return [
    `地理连贯性：围绕“${theme}”就近串联点位，减少来回折返。`,
    `节奏控制：当天约 ${attractionCount} 个景点、${mealCount} 餐，采用${rhythm}安排。`,
    `偏好匹配：${preferenceHint}。`,
  ]
}

const toggleReasonExpanded = (dayIndex: number) => {
  reasonExpanded.value = { ...reasonExpanded.value, [dayIndex]: !reasonExpanded.value[dayIndex] }
}

onMounted(async () => {
  const resultId = String(route.params.id || '')
  if (resultId && resultId !== 'fallback') {
    try {
      const resp = await fetchTravelPlanResultById(resultId)
      if (resp.success && resp.data) {
        tripPlan.value = normalizeTripPlan(resp.data)
      }
    } catch (error) {
      console.error('按ID加载 tripPlan 失败:', error)
      tripPlan.value = null
    }
  }
  if (!tripPlan.value) {
    const data = sessionStorage.getItem('tripPlan') || sessionStorage.getItem('tripeplan')
    if (data) {
      try {
        tripPlan.value = normalizeTripPlan(JSON.parse(data))
      } catch (error) {
        console.error('解析 tripPlan 失败:', error)
        tripPlan.value = null
      }
    }
  }
  if (!tripPlan.value) return
  rebuildDeepLinkItems()
  await loadAttractionPhotos()
  await nextTick()
  initMap()
})

const goBack = () => {
  router.push('/')
}

// 滚动到指定区域
const scrollToSection = ({ key }: { key: string }) => {
  activeSection.value = key
  const element = document.getElementById(key)
  if (element) {
    element.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

// 切换编辑模式
const toggleEditMode = () => {
  startEditMode()
  message.info('进入编辑模式')
}

// 保存修改
const saveChanges = () => {
  const result = saveEdits()
  if (!result.ok) {
    message.error(result.error)
    return
  }
  message.success('修改已保存')

  // 重新初始化地图以反映更改
  if (map) {
    map.remove()
  }
  nextTick(() => {
    initMap()
  })
}

// 取消编辑
const cancelEdit = () => {
  cancelEditMode()
  message.info('已取消编辑')
}


const getMealLabel = (type: string): string => {
  const labels: Record<string, string> = {
    breakfast: '早餐',
    lunch: '午餐',
    dinner: '晚餐',
    snack: '小吃'
  }
  return labels[type] || type
}

const getMealDuration = (type: string): string => {
  const labels: Record<string, string> = {
    breakfast: '30-40 分钟',
    lunch: '60-90 分钟',
    dinner: '60-90 分钟',
    snack: '20-30 分钟'
  }
  return labels[type] || '30 分钟'
}

const getAttractionDuration = (day: any, name: string): string => {
  const attraction = day?.attractions?.find((a: any) => a.name === name)
  return attraction?.visit_duration ? `${attraction.visit_duration} 分钟` : '90-120 分钟'
}

const formatPrice = (value?: number): string => {
  return formatCurrency(value)
}

const getCurrencySymbol = (): string => {
  const currency = String((tripPlan.value as any)?.budget_currency || 'EUR').toUpperCase()
  if (currency === 'EUR') return '€'
  if (currency === 'USD') return '$'
  if (currency === 'GBP') return '£'
  if (currency === 'JPY') return '¥'
  if (currency === 'CNY') return '¥'
  return '€'
}

const formatCurrency = (value?: number): string => {
  const amount = value === undefined || value === null ? 0 : value
  return `${getCurrencySymbol()}${amount}`
}

const getDayMealCount = (day: any): string => {
  const count = day.meals?.length || 0
  return `${count} 餐`
}

const deepLinkDayOptions = ref<Array<{ label: string; value: number }>>([])

const getTripDays = (): any[] => {
  return Array.isArray(tripPlan.value?.days) ? tripPlan.value!.days : []
}

const rebuildDeepLinkDayOptions = () => {
  deepLinkDayOptions.value = getTripDays().map((day: any, index: number) => ({
    label: `第${day.day_index + 1}天`,
    value: index,
  }))
}

const rebuildDeepLinkItems = () => {
  deepLinkItems.value = buildDayDeepLinkItems(currentDeepLinkDayIndex.value)
  rebuildDeepLinkDayOptions()
}

const buildDayDeepLinkItems = (dayIndex: number) => {
  const day = getTripDays()[dayIndex]
  if (!day) return []
  const items: Array<{ key: string; label: string; name: string; latitude?: number; longitude?: number; type: 'attraction' | 'meal'; address?: string }> = []
  ;(day.attractions || []).forEach((a: any, index: number) => {
    items.push({
      key: getPlaceKey(dayIndex, a.name, 'attraction'),
      label: `第${dayIndex + 1}天 · 景点${index + 1}`,
      name: a.name,
      latitude: a.location?.latitude,
      longitude: a.location?.longitude,
      type: 'attraction',
      address: a.address,
    })
  })
  ;(day.meals || []).forEach((m: any) => {
    items.push({
      key: getPlaceKey(dayIndex, m.name, 'meal', m.type),
      label: `第${dayIndex + 1}天 · ${getMealLabel(m.type)}`,
      name: m.name,
      latitude: m.location?.latitude,
      longitude: m.location?.longitude,
      type: 'meal',
      address: m.address,
    })
  })
  return items
}

const moveDeepLinkItem = (index: number, direction: 'up' | 'down') => {
  const target = deepLinkItems.value[index]
  if (!target) return
  const swapIndex = direction === 'up' ? index - 1 : index + 1
  if (swapIndex < 0 || swapIndex >= deepLinkItems.value.length) return
  ;[deepLinkItems.value[index], deepLinkItems.value[swapIndex]] = [deepLinkItems.value[swapIndex], deepLinkItems.value[index]]
}

const openDeepLinkBuilder = () => {
  deepLinkVisible.value = true
  rebuildDeepLinkItems()
}

const addCurrentDayToDeepLink = (dayIndex: number) => {
  addDayToDeepLink(dayIndex)
  deepLinkVisible.value = true
}

const buildDeepLinkFromSelection = () => {
  deepLinkItems.value = buildDayDeepLinkItems(currentDeepLinkDayIndex.value)
}

const copyDeepLinkUrl = async () => {
  const url = buildGoogleMapsDeepLinkUrl()
  await navigator.clipboard.writeText(url)
  message.success('深链已复制')
}

const openDeepLinkInGoogleMaps = () => {
  const url = buildGoogleMapsDeepLinkUrl()
  window.open(url, '_blank', 'noopener,noreferrer')
}

const copyDeepLinkItemAddress = async (item: any) => {
  if (!item.address) return message.warning('暂无地址可复制')
  await navigator.clipboard.writeText(item.address)
  message.success('地址已复制')
}

const buildGoogleMapsDeepLinkUrl = () => {
  const locations = deepLinkItems.value.filter((item) => item.latitude !== undefined && item.longitude !== undefined)
  if (locations.length === 0) return 'https://www.google.com/maps'
  const [first, ...rest] = locations
  const waypointParts = rest.map((item) => `${item.latitude},${item.longitude}`)
  const base = `https://www.google.com/maps/dir/?api=1&travelmode=walking&destination=${encodeURIComponent(`${first.latitude},${first.longitude}`)}`
  if (waypointParts.length === 0) return base
  return `${base}&waypoints=${encodeURIComponent(waypointParts.join('|'))}`
}

const removeDeepLinkItem = (index: number) => {
  deepLinkItems.value.splice(index, 1)
}

const addDayToDeepLink = (dayIndex: number) => {
  deepLinkItems.value = buildDayDeepLinkItems(dayIndex)
}

watch(currentDeepLinkDayIndex, (dayIndex) => {
  if (!deepLinkVisible.value) return
  deepLinkItems.value = buildDayDeepLinkItems(dayIndex)
})

watch(activeDays, () => {
  if (!map) return
  window.setTimeout(() => {
    startDayStoryAnimation(getActiveDayIndex())
  }, 180)
})

const copyAddress = async (address?: string) => {
  if (!address) return message.warning('暂无地址可复制')
  await navigator.clipboard.writeText(address)
  message.success('地址已复制')
}

const toggleFavorite = (item: any) => {
  message.success(`已收藏 ${item.name}`)
}

const getPlaceKey = (dayIndex: number, name: string, kind: 'attraction' | 'meal', mealType?: string) => {
  return `${dayIndex}-${kind}-${mealType || ''}-${name}`
}

const getAttractionCardId = (dayIndex: number, index: number) => `day-${dayIndex}-attraction-${index}`
const getMealCardId = (dayIndex: number, mealType: string) => `day-${dayIndex}-meal-${mealType}`
const mapStory = ref<{
  visible: boolean
  current: { name: string; description: string; address: string; image: string }
  next: { name: string; description: string; address: string; image: string } | null
  transitionProgress: number
}>({
  visible: false,
  current: { name: '', description: '', address: '', image: '' },
  next: null,
  transitionProgress: 0,
})
let walkerMarker: any = null
let walkerAnimationFrame: number | null = null
let walkerPauseTimer: number | null = null

const focusMapOn = (lng: number, lat: number, zoom = MAP_FOCUS_ZOOM) => {
  if (!map) return
  if (map.isStyleLoaded()) {
    map.resize()
  }
  map.flyTo({ center: [lng, lat], zoom, essential: true })
}

const focusMapWithPageTransition = (lng: number, lat: number, zoom = MAP_FOCUS_ZOOM) => {
  const mapElement = document.getElementById('map')
  if (mapElement) {
    mapElement.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  window.setTimeout(() => {
    focusMapOn(lng, lat, zoom)
  }, 420)
}

// 停止“小人导览动画”的所有异步任务（逐帧动画 + 定时停留）。
const stopWalkerAnimation = () => {
  // 如果当前存在 requestAnimationFrame 句柄，则取消它，避免重复渲染。
  if (walkerAnimationFrame !== null) {
    // 取消上一帧注册的动画回调。
    cancelAnimationFrame(walkerAnimationFrame)
    // 重置句柄，表示当前没有进行中的帧动画。
    walkerAnimationFrame = null
  }
  // 如果当前存在“到站停留”的定时器，则清理它，避免串场。
  if (walkerPauseTimer !== null) {
    // 清理 setTimeout，防止旧回调在未来时刻触发。
    window.clearTimeout(walkerPauseTimer)
    // 重置定时器句柄。
    walkerPauseTimer = null
  }
}

// 删除地图上的小人 marker（切天、重播、销毁时会调用）。
const removeWalkerMarker = () => {
  // 容错处理：防止 marker.remove() 在异常场景抛错导致流程中断。
  try {
    // 如果 marker 存在，则从地图上移除。
    if (walkerMarker) walkerMarker.remove()
  } catch (_) {}
  // 无论成功与否都清空引用，避免悬挂对象。
  walkerMarker = null
}

// 创建一个新的小人 marker，并返回实例。
const createWalkerMarker = () => {
  // 没有地图实例时无法创建 marker，直接返回空。
  if (!map) return null
  // 创建 DOM 元素作为 marker 的视觉承载。
  const markerEl = document.createElement('div')
  // 绑定样式类，用于控制小人图标外观。
  markerEl.className = 'walker-marker'
  // 设置小人 emoji，可直观看到导览角色。
  markerEl.textContent = '🚶'
  // 使用 Mapbox Marker 创建地图标记，并将锚点放在底部更自然贴地。
  walkerMarker = new mapboxgl.Marker({ element: markerEl, anchor: 'bottom' })
  // 返回创建好的 marker 供后续 setLngLat/addTo 使用。
  return walkerMarker
}

// 基于“当天时间轴条目”构造动画站点（包含景点 + 餐饮）。
const getAnimatedStopsByDay = (dayIndex: number) => {
  // 按索引取当天数据。
  const day = getTripDays()[dayIndex]
  // 如果当天不存在，返回空数组，外层会直接退出动画。
  if (!day) return []
  // 拉平当天时间槽位，得到按时段排序的条目数组。
  const timelineEntries = getTimelineSlots(day).flatMap((slot: any) => slot.entries || [])
  // 过滤掉没有经纬度的条目，并映射成动画所需统一结构。
  return timelineEntries
    // 仅保留可定位的条目（有 longitude/latitude）。
    .filter((entry: any) => entry?.longitude !== undefined && entry?.latitude !== undefined)
    // 把原始条目转换为动画站点对象。
    .map((entry: any, idx: number) => {
      // 判断当前条目是否为景点，用于选择图片来源。
      const isAttraction = entry.kind === 'attraction'
      // 景点使用真实/占位图；餐饮生成绿色餐饮 SVG 占位图。
      const image = isAttraction
        ? getAttractionImageByName(day, entry.title)
        : `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(
            `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">
              <defs>
                <linearGradient id="mealGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" style="stop-color:#34d399;stop-opacity:1" />
                  <stop offset="100%" style="stop-color:#059669;stop-opacity:1" />
                </linearGradient>
              </defs>
              <rect width="400" height="300" fill="url(#mealGrad)"/>
              <text x="50%" y="45%" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="42" fill="white">🍽️</text>
              <text x="50%" y="62%" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="22" fill="white">${entry.title || `餐饮${idx + 1}`}</text>
            </svg>`
          )))}`
      // 返回统一站点结构：名称、文案、地址、坐标、图片。
      return {
        // 标题优先用条目标题，没有则兜底“站点X”。
        name: entry.title || `站点${idx + 1}`,
        // 描述优先 description，再回退 route_desc。
        description: entry.description || entry.route_desc || '',
        // 地址字段兜底为空串，避免模板显示 undefined。
        address: entry.address || '',
        // 经度。
        lng: entry.longitude,
        // 纬度。
        lat: entry.latitude,
        // 当前站点展示图。
        image,
      }
    })
}

// 将折叠面板 activeKey 统一解析成“当前天索引”。
const getActiveDayIndex = (): number => {
  // 读取 collapse 的 active key（可能是数组/数字/字符串）。
  const value = activeDays.value as any
  // 如果是数组（常见场景），取第一个 active key。
  if (Array.isArray(value)) {
    // 取第一个元素作为当前天。
    const first = value[0]
    // 如果本来就是数字直接返回，否则强转数字并兜底 0。
    return typeof first === 'number' ? first : Number(first || 0)
  }
  // 如果是数字直接返回。
  if (typeof value === 'number') return value
  // 如果是字符串，转数字并兜底 0。
  if (typeof value === 'string') return Number(value || 0)
  // 兜底返回第 0 天。
  return 0
}

// 启动某一天的地图故事动画（会自动循环）。
const startDayStoryAnimation = (dayIndex: number) => {
  // 无地图实例则无法播放动画。
  if (!map) return
  // 开始前先停止旧动画，避免双实例并行。
  stopWalkerAnimation()
  // 开始前移除旧小人 marker，确保只有一个角色在地图上。
  removeWalkerMarker()
  // 取当天可播放站点。
  const stops = getAnimatedStopsByDay(dayIndex)
  // 无站点时隐藏故事卡片并退出。
  if (stops.length === 0) {
    // 关闭左上角故事卡片。
    mapStory.value.visible = false
    // 结束函数。
    return
  }

  // 创建小人 marker。
  const marker = createWalkerMarker()
  // 创建失败（极端情况）则退出。
  if (!marker) return
  // 小人放到第一站，并挂到地图上。
  marker.setLngLat([stops[0].lng, stops[0].lat]).addTo(map)

  // 打开故事卡片层。
  mapStory.value.visible = true
  // 设置当前卡片为第一站。
  mapStory.value.current = {
    // 当前站标题。
    name: stops[0].name,
    // 当前站描述。
    description: stops[0].description,
    // 当前站地址。
    address: stops[0].address,
    // 当前站图片。
    image: stops[0].image,
  }
  // 如果存在第二站，则先作为“下一站”预告卡片。
  mapStory.value.next = stops[1]
    ? {
        // 下一站标题。
        name: stops[1].name,
        // 下一站描述。
        description: stops[1].description,
        // 下一站地址。
        address: stops[1].address,
        // 下一站图片。
        image: stops[1].image,
      }
    // 没有下一站则置空。
    : null
  // 初始化卡片过渡进度为 0（仅显示当前卡片）。
  mapStory.value.transitionProgress = 0

  // 开场先飞到第一站，给用户一个明确起点。
  map.flyTo({ center: [stops[0].lng, stops[0].lat], zoom: MAP_STORY_ZOOM, essential: true })
  // 如果只有一个站点，无需段动画，停在当前即可。
  if (stops.length === 1) return

  // 全部站点走完后，循环前的短停留时长（毫秒）。
  const loopPauseDuration = 900
  // 缓动函数：前后慢、中间快，移动更自然。
  const easeInOut = (t: number) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2)
  // 计算两点球面距离（公里），用于动态速度控制。
  const calcDistanceKm = (from: { lng: number; lat: number }, to: { lng: number; lat: number }) => {
    // 角度转弧度函数。
    const toRad = (v: number) => (v * Math.PI) / 180
    // 地球半径（km）。
    const earthRadiusKm = 6371
    // 纬度差（弧度）。
    const dLat = toRad(to.lat - from.lat)
    // 经度差（弧度）。
    const dLng = toRad(to.lng - from.lng)
    // Haversine 公式中间值 a。
    const a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(toRad(from.lat)) * Math.cos(toRad(to.lat)) * Math.sin(dLng / 2) * Math.sin(dLng / 2)
    // Haversine 公式中间值 c。
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
    // 返回球面距离（km）。
    return earthRadiusKm * c
  }
  // 根据两点距离计算“移动时长”（ms）：近距不闪，远距不拖。
  const calcSegmentDuration = (from: { lng: number; lat: number }, to: { lng: number; lat: number }) => {
    // 先算公里距离。
    const distanceKm = calcDistanceKm(from, to)
    // 次线性增长，防止远距离时长爆炸。
    const dynamic = 2400 + Math.sqrt(distanceKm + 0.02) * 2100
    // 限制在 [2600, 5600] 区间。
    return Math.min(5600, Math.max(2600, dynamic))
  }
  // 根据两点距离计算“到站停留时长”（ms）：确保读卡片有时间。
  const calcStopDuration = (from: { lng: number; lat: number }, to: { lng: number; lat: number }) => {
    // 先算公里距离。
    const distanceKm = calcDistanceKm(from, to)
    // 次线性增长，远距离适度多停留。
    const dynamic = 1200 + Math.sqrt(distanceKm + 0.02) * 700
    // 限制在 [1100, 2300] 区间。
    return Math.min(2300, Math.max(1100, dynamic))
  }

  // 播放某一段（from -> to）的移动动画。
  const runSegment = (segmentIndex: number) => {
    // 当前段起点站。
    const from = stops[segmentIndex]
    // 当前段终点站。
    const to = stops[segmentIndex + 1]
    // 若段数据不完整，则清空“下一站”状态并结束。
    if (!from || !to) {
      // 过渡进度归零。
      mapStory.value.transitionProgress = 0
      // 下一站清空。
      mapStory.value.next = null
      // 退出当前段。
      return
    }
    // 计算本段移动时长。
    const segmentDuration = calcSegmentDuration(from, to)
    // 计算到站后停留时长。
    const stopDuration = calcStopDuration(from, to)
    // 记录本段开始时间戳。
    const startTime = performance.now()

    // 每一帧回调：计算当前进度并更新小人位置/镜头/卡片过渡。
    const tick = (now: number) => {
      // 线性进度，范围 [0,1]。
      const rawProgress = Math.min((now - startTime) / segmentDuration, 1)
      // 应用缓动后的进度，移动更平滑。
      const eased = easeInOut(rawProgress)
      // 插值得到当前经度。
      const lng = from.lng + (to.lng - from.lng) * eased
      // 插值得到当前纬度。
      const lat = from.lat + (to.lat - from.lat) * eased
      // 更新小人 marker 到当前坐标。
      marker.setLngLat([lng, lat])
      // 移动过程中镜头持续跟随小人。
      map.easeTo({
        // 跟随中心点。
        center: [lng, lat],
        // 跟随缩放等级。
        zoom: MAP_STORY_ZOOM,
        // 每次小步跟随的动画时长。
        duration: 180,
        // 线性 easing，避免镜头二次变速。
        easing: (v: number) => v,
        // 声明此动画为关键动画。
        essential: true,
      })

      // 小人离站后即展示下一站：这里 0~0.25 迅速将过渡推到 1。
      mapStory.value.transitionProgress = Math.min(rawProgress / 0.25, 1)

      // 若还没到终点，继续请求下一帧。
      if (rawProgress < 1) {
        // 存储 rAF 句柄，方便外部随时停止。
        walkerAnimationFrame = requestAnimationFrame(tick)
        // 本帧结束。
        return
      }

      // 到站时把“下一站卡片”保持为完整可见，避免突兀切换。
      mapStory.value.transitionProgress = 1
      // 预取“未来站点”（下一段的终点），用于更新 next 卡片。
      const future = stops[segmentIndex + 2]
      // 到站后先短暂停顿，再执行卡片切换。
      walkerPauseTimer = window.setTimeout(() => {
        // 定时器触发后先清空句柄。
        walkerPauseTimer = null
        // 把当前卡片切换为刚到达的 to 站。
        mapStory.value.current = {
          // 新当前站标题。
          name: to.name,
          // 新当前站描述。
          description: to.description,
          // 新当前站地址。
          address: to.address,
          // 新当前站图片。
          image: to.image,
        }
        // 更新下一站卡片（如果 future 存在）。
        mapStory.value.next = future
          ? {
              // future 标题。
              name: future.name,
              // future 描述。
              description: future.description,
              // future 地址。
              address: future.address,
              // future 图片。
              image: future.image,
            }
          // 没有 future 时置空。
          : null
        // 当前段切换完成后，过渡进度重置。
        mapStory.value.transitionProgress = 0

        // 如果后面还有段，则按停留时长后播放下一段。
        if (segmentIndex + 1 < stops.length - 1) {
          // 创建下一段启动定时器。
          walkerPauseTimer = window.setTimeout(() => {
            // 触发后清空句柄。
            walkerPauseTimer = null
            // 递归播放下一段。
            runSegment(segmentIndex + 1)
          }, stopDuration)
        } else {
          // 末站处理：短暂停留后从第一站重播，实现循环。
          walkerPauseTimer = window.setTimeout(() => {
            // 触发后清空句柄。
            walkerPauseTimer = null
            // 从 dayIndex 重新启动整天动画。
            startDayStoryAnimation(dayIndex)
          }, loopPauseDuration)
        }
      }, 700)
    }

    // 启动当前段第一帧。
    walkerAnimationFrame = requestAnimationFrame(tick)
  }

  // 从第 0 段开始播放整天路线。
  runSegment(0)
}

const focusPlace = (entry: any) => {
  selectedPlaceKey.value = entry.key
  if (entry.longitude && entry.latitude) {
    focusMapWithPageTransition(entry.longitude, entry.latitude, entry.kind === 'meal' ? MAP_MEAL_FOCUS_ZOOM : MAP_FOCUS_ZOOM)
  }
}

const focusAttraction = (dayIndex: number, index: number) => {
  const day = getTripDays()[dayIndex]
  const attraction = day?.attractions?.[index]
  if (!day || !attraction) return
  selectedPlaceKey.value = getPlaceKey(dayIndex, attraction.name, 'attraction')
  scrollCardIntoView(getAttractionCardId(dayIndex, index))
  if (attraction.location?.longitude && attraction.location?.latitude) {
    focusMapOn(attraction.location.longitude, attraction.location.latitude)
  }
}

const focusMeal = (dayIndex: number, meal: any) => {
  selectedPlaceKey.value = getPlaceKey(dayIndex, meal.name, 'meal', meal.type)
  if (meal.location?.longitude && meal.location?.latitude) {
    focusMapWithPageTransition(meal.location.longitude, meal.location.latitude, MAP_MEAL_FOCUS_ZOOM)
  }
}

const getGoogleMapsUrl = (name: string, latitude?: number, longitude?: number) => {
  const destination = latitude !== undefined && longitude !== undefined ? `${latitude},${longitude}` : name
  if (latitude !== undefined && longitude !== undefined) {
    return `https://www.google.com/maps/dir/?api=1&travelmode=walking&destination=${encodeURIComponent(destination)}`
  }
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(name)}`
}

const openGoogleMapsNavigate = (name: string, latitude?: number, longitude?: number) => {
  window.open(getGoogleMapsUrl(name, latitude, longitude), '_blank', 'noopener,noreferrer')
}

const openGoogleMapsCollection = () => {
  const locations = deepLinkItems.value
    .filter((item) => item.latitude !== undefined && item.longitude !== undefined)
    .map((item) => `${item.latitude},${item.longitude}`)
  if (locations.length === 0) return
  const url = `https://www.google.com/maps/dir/?api=1&travelmode=walking&waypoints=${encodeURIComponent(locations.join('|'))}`
  window.open(url, '_blank', 'noopener,noreferrer')
}

const scrollCardIntoView = (id: string) => {
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

const getTimelineSlots = (day: any) => {
  const attractions = day.attractions || []
  const meals = day.meals || []
  const activities = ensureArray<any>(day.activities)
  const slots = [
    { key: 'morning', label: '上午', entries: [] as any[] },
    { key: 'noon', label: '中午', entries: [] as any[] },
    { key: 'afternoon', label: '下午', entries: [] as any[] },
    { key: 'evening', label: '晚上', entries: [] as any[] },
  ]

  const parseStartHour = (timeText: string): number => {
    const text = String(timeText || '').trim()
    if (!text) return 14
    const start = text.split('-')[0]?.trim() || text
    const match = start.match(/(\d{1,2}):(\d{2})/)
    if (!match) return 14
    return Number(match[1])
  }

  const getSlotIndexByHour = (hour: number): number => {
    if (hour < 11) return 0
    if (hour < 14) return 1
    if (hour < 18) return 2
    return 3
  }

  const getMealSlotIndex = (mealType: string, mealTime?: string): number => {
    if (mealType === 'breakfast') return 0
    if (mealType === 'lunch') return 1
    if (mealType === 'dinner') return 3
    const hour = parseStartHour(String(mealTime || ''))
    return getSlotIndexByHour(hour)
  }

  const attractionIndexMap = new Map<string, number>()
  attractions.forEach((item: any, idx: number) => attractionIndexMap.set(String(item.name || ''), idx))

  activities
    .map((activity: any, idx: number) => ({ activity, idx, hour: parseStartHour(String(activity?.time || '')) }))
    .sort((a, b) => a.hour - b.hour || a.idx - b.idx)
    .forEach(({ activity }) => {
      const slotIndex = getSlotIndexByHour(parseStartHour(String(activity?.time || '')))
      const attraction = attractions.find((a: any) => a.name === activity.name)
      const attractionCardIndex = attractionIndexMap.get(String(activity.name || '')) ?? 0
      slots[slotIndex].entries.push({
        key: getPlaceKey(day.day_index, activity.name, 'attraction'),
        kind: 'attraction',
        title: activity.name,
        time: activity.time || '',
        address: activity.address || attraction?.address || '',
        description: activity.description || attraction?.description || '',
        route_desc: activity.route_desc || attraction?.description || '',
        ticket_price: activity.ticket_price ?? attraction?.ticket_price ?? 0,
        preference_matched: Boolean(activity.preference_matched),
        preference_reason: String(activity.preference_reason || ''),
        latitude: activity.latitude ?? attraction?.location?.latitude,
        longitude: activity.longitude ?? attraction?.location?.longitude,
        cardId: getAttractionCardId(day.day_index, attractionCardIndex),
      })
    })

  meals
    .map((meal: any, idx: number) => ({ meal, idx, hour: parseStartHour(String(meal?.time || '')) }))
    .sort((a: { hour: number; idx: number }, b: { hour: number; idx: number }) => a.hour - b.hour || a.idx - b.idx)
    .forEach(({ meal }: { meal: any }) => {
      const slotIndex = getMealSlotIndex(String(meal?.type || ''), String(meal?.time || ''))
      slots[slotIndex].entries.push({
        key: getPlaceKey(day.day_index, meal.name, 'meal', meal.type),
        kind: 'meal',
        mealType: meal.type,
        title: `${getMealLabel(meal.type)} · ${meal.name}`,
        time: meal.time || '',
        address: meal.address,
        description: meal.description,
        route_desc: meal.route_desc,
        latitude: meal.location?.latitude,
        longitude: meal.location?.longitude,
        cardId: getMealCardId(day.day_index, meal.type),
      })
    })
  return slots
}

const getAttractionImageByName = (day: any, name: string): string => {
  const attractions = Array.isArray(day?.attractions) ? day.attractions : []
  const item = attractions.find((a: any) => a.name === name)
  if (!item) return getAttractionImage({ name }, 0)
  const idx = attractions.findIndex((a: any) => a.name === name)
  return getAttractionImage(item, idx >= 0 ? idx : 0)
}

// 加载所有景点图片
const loadAttractionPhotos = async () => {
  if (!tripPlan.value) return

  const promises: Promise<void>[] = []

  getTripDays().forEach((day: any) => {
    ;(day.attractions || []).forEach((attraction: any) => {
      // 优先使用 travel-plan 返回的真实 photo_references/image_url
      if (attraction.image_url) {
        attractionPhotos.value[attraction.name] = attraction.image_url
        return
      }

      const refs = attraction.photo_references || []
      if (refs.length > 0) {
        attractionPhotos.value[attraction.name] = refs[0]
        return
      }

      const apiBase = (import.meta as any).env?.VITE_API_BASE_URL || 'http://localhost:8881'
      const promise = fetch(`${apiBase}/api/poi/photo?name=${encodeURIComponent(attraction.name)}`)
        .then(res => res.json())
        .then(data => {
          if (data.success && data.data.photo_url) {
            attractionPhotos.value[attraction.name] = data.data.photo_url
          }
        })
        .catch(err => {
          console.error(`获取${attraction.name}图片失败:`, err)
        })

      promises.push(promise)
    })
  })

  await Promise.all(promises)
}

// 获取景点图片
const getAttractionImage = (attraction: any, index: number): string => {
  const name = attraction?.name || `景点${index + 1}`
  // 如果已加载真实图片,返回真实图片
  if (attractionPhotos.value[name]) {
    return attractionPhotos.value[name]
  }

  // 返回一个纯色占位图(避免跨域问题)
  const colors = [
    { start: '#667eea', end: '#764ba2' },
    { start: '#f093fb', end: '#f5576c' },
    { start: '#4facfe', end: '#00f2fe' },
    { start: '#43e97b', end: '#38f9d7' },
    { start: '#fa709a', end: '#fee140' }
  ]
  const colorIndex = index % colors.length
  const { start, end } = colors[colorIndex]

  // 使用base64编码避免中文问题
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300">
    <defs>
      <linearGradient id="grad${index}" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" style="stop-color:${start};stop-opacity:1" />
        <stop offset="100%" style="stop-color:${end};stop-opacity:1" />
      </linearGradient>
    </defs>
    <rect width="400" height="300" fill="url(#grad${index})"/>
    <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="24" font-weight="bold" fill="white">${name}</text>
  </svg>`

  return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`
}

// 图片加载失败时的处理
const handleImageError = (event: Event) => {
  const img = event.target as HTMLImageElement
  // 使用灰色占位图
  img.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="400" height="300"%3E%3Crect width="400" height="300" fill="%23f0f0f0"/%3E%3Ctext x="50%25" y="50%25" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="18" fill="%23999"%3E图片加载失败%3C/text%3E%3C/svg%3E'
}



// 导出为图片
const exportAsImage = async () => {
  try {
    message.loading({ content: '正在生成图片...', key: 'export', duration: 0 })

    const element = document.querySelector('.main-content') as HTMLElement
    if (!element) {
      throw new Error('未找到内容元素')
    }

    // 创建一个独立的容器
    const exportContainer = document.createElement('div')
    exportContainer.style.width = element.offsetWidth + 'px'
    exportContainer.style.backgroundColor = '#f5f7fa'
    exportContainer.style.padding = '20px'

    // 复制所有内容
    exportContainer.innerHTML = element.innerHTML

    // 处理地图截图
    const mapContainer = document.getElementById('mapbox-container')
    if (mapContainer && map) {
      const mapCanvas = mapContainer.querySelector('canvas')
      if (mapCanvas) {
        const mapSnapshot = mapCanvas.toDataURL('image/png')
        const exportMapContainer = exportContainer.querySelector('#mapbox-container')
        if (exportMapContainer) {
          exportMapContainer.innerHTML = `<img src="${mapSnapshot}" style="width:100%;height:100%;object-fit:cover;" />`
        }
      }
    }

    // 移除所有ant-card类,替换为纯div
    const cards = exportContainer.querySelectorAll('.ant-card')
    cards.forEach((card) => {
      const cardEl = card as HTMLElement
      try {
        cardEl.className = '' // 移除所有类
        cardEl.style.setProperty('background-color', '#ffffff')
        cardEl.style.setProperty('border-radius', '12px')
        cardEl.style.setProperty('box-shadow', '0 4px 12px rgba(0, 0, 0, 0.1)')
        cardEl.style.setProperty('margin-bottom', '20px')
        cardEl.style.setProperty('overflow', 'hidden')
      } catch (err) {
        console.error('设置卡片样式失败:', err)
      }
    })

    // 处理卡片头部
    const cardHeads = exportContainer.querySelectorAll('.ant-card-head')
    cardHeads.forEach((head) => {
      const headEl = head as HTMLElement
      try {
        headEl.style.setProperty('background-color', '#667eea')
        headEl.style.setProperty('color', '#ffffff')
        headEl.style.setProperty('padding', '16px 24px')
        headEl.style.setProperty('font-size', '18px')
        headEl.style.setProperty('font-weight', '600')
      } catch (err) {
        console.error('设置卡片头部样式失败:', err)
      }
    })

    // 处理卡片内容
    const cardBodies = exportContainer.querySelectorAll('.ant-card-body')
    cardBodies.forEach((body) => {
      const bodyEl = body as HTMLElement
      bodyEl.style.setProperty('background-color', '#ffffff')
      bodyEl.style.setProperty('padding', '24px')
    })

    // 处理酒店卡片头部
    const hotelCards = exportContainer.querySelectorAll('.hotel-card')
    hotelCards.forEach((card) => {
      const head = card.querySelector('.ant-card-head') as HTMLElement
      if (head) {
        head.style.setProperty('background-color', '#1976d2')
      }
      (card as HTMLElement).style.setProperty('background-color', '#e3f2fd')
    })

    // 处理天气卡片
    const weatherCards = exportContainer.querySelectorAll('.weather-card')
    weatherCards.forEach((card) => {
      (card as HTMLElement).style.setProperty('background-color', '#e0f7fa')
    })

    // 处理预算总计
    const budgetTotal = exportContainer.querySelector('.budget-total')
    if (budgetTotal) {
      const el = budgetTotal as HTMLElement
      el.style.setProperty('background-color', '#667eea')
      el.style.setProperty('color', '#ffffff')
      el.style.setProperty('padding', '20px')
      el.style.setProperty('border-radius', '12px')
      el.style.setProperty('margin-bottom', '20px')
    }

    // 处理预算项
    const budgetItems = exportContainer.querySelectorAll('.budget-item')
    budgetItems.forEach((item) => {
      const el = item as HTMLElement
      el.style.setProperty('background-color', '#f5f7fa')
      el.style.setProperty('padding', '16px')
      el.style.setProperty('border-radius', '8px')
      el.style.setProperty('margin-bottom', '12px')
    })

    // 添加到body(隐藏)
    exportContainer.style.position = 'absolute'
    exportContainer.style.left = '-9999px'
    document.body.appendChild(exportContainer)

    const canvas = await html2canvas(exportContainer, {
      backgroundColor: '#f5f7fa',
      scale: 2,
      logging: false,
      useCORS: true,
      allowTaint: true
    })

    // 移除容器
    document.body.removeChild(exportContainer)

    // 转换为图片并下载
    const link = document.createElement('a')
    link.download = `旅行计划_${tripPlan.value?.city}_${new Date().getTime()}.png`
    link.href = canvas.toDataURL('image/png')
    link.click()

    message.success({ content: '图片导出成功!', key: 'export' })
  } catch (error: any) {
    console.error('导出图片失败:', error)
    message.error({ content: `导出图片失败: ${error.message}`, key: 'export' })
  }
}

// 导出为PDF
const exportAsPDF = async () => {
  try {
    message.loading({ content: '正在生成PDF...', key: 'export', duration: 0 })

    const element = document.querySelector('.main-content') as HTMLElement
    if (!element) {
      throw new Error('未找到内容元素')
    }

    // 创建一个独立的容器
    const exportContainer = document.createElement('div')
    exportContainer.style.width = element.offsetWidth + 'px'
    exportContainer.style.backgroundColor = '#f5f7fa'
    exportContainer.style.padding = '20px'

    // 复制所有内容
    exportContainer.innerHTML = element.innerHTML

    // 处理地图截图
    const mapContainer = document.getElementById('mapbox-container')
    if (mapContainer && map) {
      const mapCanvas = mapContainer.querySelector('canvas')
      if (mapCanvas) {
        const mapSnapshot = mapCanvas.toDataURL('image/png')
        const exportMapContainer = exportContainer.querySelector('#mapbox-container')
        if (exportMapContainer) {
          exportMapContainer.innerHTML = `<img src="${mapSnapshot}" style="width:100%;height:100%;object-fit:cover;" />`
        }
      }
    }

    // 移除所有ant-card类,替换为纯div
    const cards = exportContainer.querySelectorAll('.ant-card')
    cards.forEach((card) => {
      const cardEl = card as HTMLElement
      try {
        cardEl.className = ''
        cardEl.style.setProperty('background-color', '#ffffff')
        cardEl.style.setProperty('border-radius', '12px')
        cardEl.style.setProperty('box-shadow', '0 4px 12px rgba(0, 0, 0, 0.1)')
        cardEl.style.setProperty('margin-bottom', '20px')
        cardEl.style.setProperty('overflow', 'hidden')
      } catch (err) {
        console.error('设置卡片样式失败:', err)
      }
    })

    // 处理卡片头部
    const cardHeads = exportContainer.querySelectorAll('.ant-card-head')
    cardHeads.forEach((head) => {
      const headEl = head as HTMLElement
      try {
        headEl.style.setProperty('background-color', '#667eea')
        headEl.style.setProperty('color', '#ffffff')
        headEl.style.setProperty('padding', '16px 24px')
        headEl.style.setProperty('font-size', '18px')
        headEl.style.setProperty('font-weight', '600')
      } catch (err) {
        console.error('设置卡片头部样式失败:', err)
      }
    })

    // 处理卡片内容
    const cardBodies = exportContainer.querySelectorAll('.ant-card-body')
    cardBodies.forEach((body) => {
      const bodyEl = body as HTMLElement
      bodyEl.style.setProperty('background-color', '#ffffff')
      bodyEl.style.setProperty('padding', '24px')
    })

    // 处理酒店卡片头部
    const hotelCards = exportContainer.querySelectorAll('.hotel-card')
    hotelCards.forEach((card) => {
      const head = card.querySelector('.ant-card-head') as HTMLElement
      if (head) {
        head.style.setProperty('background-color', '#1976d2')
      }
      (card as HTMLElement).style.setProperty('background-color', '#e3f2fd')
    })

    // 处理天气卡片
    const weatherCards = exportContainer.querySelectorAll('.weather-card')
    weatherCards.forEach((card) => {
      (card as HTMLElement).style.setProperty('background-color', '#e0f7fa')
    })

    // 处理预算总计
    const budgetTotal = exportContainer.querySelector('.budget-total')
    if (budgetTotal) {
      const el = budgetTotal as HTMLElement
      el.style.setProperty('background-color', '#667eea')
      el.style.setProperty('color', '#ffffff')
      el.style.setProperty('padding', '20px')
      el.style.setProperty('border-radius', '12px')
      el.style.setProperty('margin-bottom', '20px')
    }

    // 处理预算项
    const budgetItems = exportContainer.querySelectorAll('.budget-item')
    budgetItems.forEach((item) => {
      const el = item as HTMLElement
      el.style.setProperty('background-color', '#f5f7fa')
      el.style.setProperty('padding', '16px')
      el.style.setProperty('border-radius', '8px')
      el.style.setProperty('margin-bottom', '12px')
    })

    // 添加到body(隐藏)
    exportContainer.style.position = 'absolute'
    exportContainer.style.left = '-9999px'
    document.body.appendChild(exportContainer)

    const canvas = await html2canvas(exportContainer, {
      backgroundColor: '#f5f7fa',
      scale: 2,
      logging: false,
      useCORS: true,
      allowTaint: true
    })

    // 移除容器
    document.body.removeChild(exportContainer)

    const imgData = canvas.toDataURL('image/png')
    const pdf = new jsPDF({
      orientation: 'portrait',
      unit: 'mm',
      format: 'a4'
    })

    const imgWidth = 210 // A4宽度(mm)
    const imgHeight = (canvas.height * imgWidth) / canvas.width

    // 如果内容高度超过一页,分页处理
    let heightLeft = imgHeight
    let position = 0

    pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight)
    heightLeft -= 297 // A4高度

    while (heightLeft > 0) {
      position = heightLeft - imgHeight
      pdf.addPage()
      pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight)
      heightLeft -= 297
    }

    pdf.save(`旅行计划_${tripPlan.value?.city}_${new Date().getTime()}.pdf`)

    message.success({ content: 'PDF导出成功!', key: 'export' })
  } catch (error: any) {
    console.error('导出PDF失败:', error)
    message.error({ content: `导出PDF失败: ${error.message}`, key: 'export' })
  }
}

// 截取地图图片
// 初始化地图
const initMap = async () => {
  try {
    const token = (import.meta as any).env?.VITE_MAPBOX_ACCESS_TOKEN
    if (!token) {
      message.error('缺少 VITE_MAPBOX_ACCESS_TOKEN，无法加载地图')
      return
    }
    mapboxgl.accessToken = token

    const container = document.getElementById('mapbox-container')
    if (!container) {
      message.error('地图容器未找到')
      return
    }

    if (map) {
      try { map.remove() } catch (_) {}
      map = null
    }

    map = new mapboxgl.Map({
      container: 'mapbox-container',
      style: 'mapbox://styles/mapbox/streets-v12',
      center: [116.397128, 39.916527],
      zoom: MAP_DEFAULT_ZOOM
    })

    map.on('load', () => {
      map?.resize()
      addAttractionMarkers()
    })

    window.setTimeout(() => {
      map?.resize()
    }, 120)
    window.setTimeout(() => {
      map?.resize()
    }, 420)

    message.success('地图加载成功')
  } catch (error) {
    console.error('地图加载失败:', error)
    message.error('地图加载失败')
  }
}

const clearMapOverlays = () => {
  stopWalkerAnimation()
  removeWalkerMarker()
  mapStory.value.visible = false
  markerInstances.forEach((m) => {
    try { m.remove() } catch (_) {}
  })
  markerInstances = []
  routeLayerIds.forEach((id) => {
    try {
      if (map?.getLayer(id)) map.removeLayer(id)
    } catch (_) {}
  })
  routeSourceIds.forEach((id) => {
    try {
      if (map?.getSource(id)) map.removeSource(id)
    } catch (_) {}
  })
  routeLayerIds = []
  routeSourceIds = []
}

// 添加景点标记
const addAttractionMarkers = () => {
  if (!tripPlan.value) return

  clearMapOverlays()

  const markerBounds = new mapboxgl.LngLatBounds()
  const allAttractions: any[] = []
  const allMeals: any[] = []

  // 收集所有景点
  tripPlan.value.days.forEach((day, dayIndex) => {
    day.attractions.forEach((attraction, attrIndex) => {
      if (attraction.location && attraction.location.longitude && attraction.location.latitude) {
        allAttractions.push({
          ...attraction,
          dayIndex,
          attrIndex
        })
      }
    })
    ;(day.meals || []).forEach((meal) => {
      if (meal.location && meal.location.longitude && meal.location.latitude) {
        allMeals.push({
          ...meal,
          dayIndex,
        })
      }
    })
  })

  // 创建标记
  allAttractions.forEach((attraction) => {
    const markerEl = document.createElement('div')
    const dayColor = routeColors[attraction.dayIndex % routeColors.length]
    markerEl.style.background = dayColor
    markerEl.style.color = 'white'
    markerEl.style.width = '28px'
    markerEl.style.height = '28px'
    markerEl.style.display = 'inline-flex'
    markerEl.style.alignItems = 'center'
    markerEl.style.justifyContent = 'center'
    markerEl.style.borderRadius = '50%'
    markerEl.style.fontSize = '11px'
    markerEl.style.fontWeight = '700'
    markerEl.style.cursor = 'pointer'
    markerEl.style.border = '2px solid #fff'
    markerEl.style.boxShadow = '0 2px 8px rgba(0,0,0,0.3)'
    markerEl.style.whiteSpace = 'nowrap'
    markerEl.textContent = `${attraction.attrIndex + 1}`

    const lngLat: [number, number] = [attraction.location.longitude, attraction.location.latitude]

    const marker = new mapboxgl.Marker({ element: markerEl, anchor: 'center' })
      .setLngLat(lngLat)
      .addTo(map)
    markerInstances.push(marker)

    markerBounds.extend(lngLat)

    const html = `
      <div style="padding: 8px; min-width: 220px;">
        <h4 style="margin: 0 0 8px 0;">${attraction.name}</h4>
        <p style="margin: 4px 0;"><strong>地址:</strong> ${attraction.address || '暂无'}</p>
        <p style="margin: 4px 0;"><strong>游览时长:</strong> ${attraction.visit_duration || 0}分钟</p>
        <p style="margin: 4px 0;"><strong>描述:</strong> ${attraction.description || '暂无描述'}</p>
        <p style="margin: 4px 0; color: #1890ff;"><strong>第${attraction.dayIndex + 1}天 · 第${attraction.attrIndex + 1}站</strong></p>
      </div>
    `
    const markerPopup = new mapboxgl.Popup({ offset: 24 }).setHTML(html)
    marker.setPopup(markerPopup)
    markerEl.addEventListener('click', () => {
      if (popup && popup !== markerPopup) popup.remove()
      popup = markerPopup
      selectedPlaceKey.value = getPlaceKey(attraction.dayIndex, attraction.name, 'attraction')
      marker.togglePopup()
      focusAttraction(attraction.dayIndex, attraction.attrIndex)
    })
  })

  // 创建餐饮标记（早餐/午餐/晚餐使用不同图案）
  allMeals.forEach((meal) => {
    const markerEl = document.createElement('div')
    const dayColor = routeColors[meal.dayIndex % routeColors.length]
    markerEl.style.background = '#ffffff'
    markerEl.style.color = dayColor
    markerEl.style.width = '26px'
    markerEl.style.height = '26px'
    markerEl.style.display = 'inline-flex'
    markerEl.style.alignItems = 'center'
    markerEl.style.justifyContent = 'center'
    markerEl.style.borderRadius = '8px'
    markerEl.style.fontSize = '11px'
    markerEl.style.fontWeight = '700'
    markerEl.style.cursor = 'pointer'
    markerEl.style.border = `2px solid ${dayColor}`
    markerEl.style.boxShadow = '0 2px 8px rgba(0,0,0,0.2)'

    const mealMarkerMap: Record<string, string> = {
      breakfast: 'B',
      lunch: 'L',
      dinner: 'D',
      snack: 'S',
    }
    markerEl.textContent = mealMarkerMap[meal.type] || 'M'

    const lngLat: [number, number] = [meal.location.longitude, meal.location.latitude]
    const marker = new mapboxgl.Marker({ element: markerEl, anchor: 'center' })
      .setLngLat(lngLat)
      .addTo(map)
    markerInstances.push(marker)
    markerBounds.extend(lngLat)

    const html = `
      <div style="padding: 8px; min-width: 220px;">
        <h4 style="margin: 0 0 8px 0;">${meal.name}</h4>
        <p style="margin: 4px 0;"><strong>类型:</strong> ${getMealLabel(meal.type)}</p>
        <p style="margin: 4px 0;"><strong>时间:</strong> ${meal.time || '待定'}</p>
        <p style="margin: 4px 0;"><strong>地址:</strong> ${meal.address || '暂无'}</p>
        <p style="margin: 4px 0;"><strong>描述:</strong> ${meal.description || '暂无描述'}</p>
        <p style="margin: 4px 0; color: #1890ff;"><strong>第${meal.dayIndex + 1}天</strong></p>
      </div>
    `
    const markerPopup = new mapboxgl.Popup({ offset: 24 }).setHTML(html)
    marker.setPopup(markerPopup)
    markerEl.addEventListener('click', () => {
      if (popup && popup !== markerPopup) popup.remove()
      popup = markerPopup
      selectedPlaceKey.value = getPlaceKey(meal.dayIndex, meal.name, 'meal', meal.type)
      marker.togglePopup()
      focusMeal(meal.dayIndex, meal)
    })
  })

  if (allAttractions.length > 0) {
    map.fitBounds(markerBounds, { padding: 40 })
  }

  drawRoutes()
  window.setTimeout(() => {
    startDayStoryAnimation(getActiveDayIndex())
  }, 280)
}

// 绘制路线
const drawRoutes = () => {
  if (!tripPlan.value) return

  tripPlan.value.days.forEach((day, dayIndex) => {
    const timelineEntries = getTimelineSlots(day).flatMap((slot: any) => slot.entries || [])
    const coordinates = timelineEntries
      .filter((entry: any) => entry.longitude !== undefined && entry.latitude !== undefined)
      .map((entry: any) => [entry.longitude, entry.latitude] as [number, number])

    if (coordinates.length < 2) return

    const sourceId = `route-source-${dayIndex}`
    const layerId = `route-layer-${dayIndex}`
    const dayColor = routeColors[dayIndex % routeColors.length]

    if (map.getLayer(layerId)) map.removeLayer(layerId)
    if (map.getSource(sourceId)) map.removeSource(sourceId)
    routeLayerIds.push(layerId)
    routeSourceIds.push(sourceId)

    map.addSource(sourceId, {
      type: 'geojson',
      data: {
        type: 'Feature',
        geometry: {
          type: 'LineString',
          coordinates
        },
        properties: {}
      }
    })

    map.addLayer({
      id: layerId,
      type: 'line',
      source: sourceId,
      paint: {
        'line-color': dayColor,
        'line-width': 5,
        'line-opacity': 0.85
      },
      layout: {
        'line-cap': 'round',
        'line-join': 'round'
      }
    })
  })
}
</script>

<style scoped>
.result-container {
  min-height: 100vh;
  background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%);
  padding: 18px;
}

.page-header {
  display: flex;
  gap: 12px;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 16px;
}

.content-wrapper {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.side-nav {
  width: 240px;
  flex-shrink: 0;
}

.main-content {
  flex: 1;
  min-width: 0;
}

.poster-card {
  margin-top: 16px;
}

.top-info-section {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}

.left-info {
  flex: 0 0 420px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.right-map {
  flex: 1;
  min-width: 0;
}

.map-card,
.map-wrap,
.mapbox-container {
  width: 100%;
}

.map-card {
  min-height: 520px;
}

.map-wrap {
  position: relative;
  min-height: 460px;
  overflow: hidden;
  border-radius: 14px;
}

.mapbox-container {
  min-height: 460px;
}

.map-story-panel {
  position: absolute;
  left: 12px;
  top: 12px;
  z-index: 3;
  width: min(360px, calc(100% - 24px));
}

.map-story-cards {
  position: relative;
  min-height: 120px;
}

.story-card {
  position: absolute;
  inset: 0;
  display: flex;
  gap: 10px;
  padding: 10px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 12px;
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.16);
  overflow: hidden;
}

.story-image {
  width: 92px;
  height: 92px;
  flex: 0 0 92px;
  border-radius: 10px;
  object-fit: cover;
  background: #e5e7eb;
}

.story-content {
  min-width: 0;
}

.story-title {
  font-weight: 700;
  font-size: 15px;
  color: #111827;
}

.story-desc,
.story-meta {
  font-size: 12px;
  line-height: 1.45;
  color: #4b5563;
  margin-top: 4px;
}

.entry-layout {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.entry-image-wrap {
  width: 168px;
  height: 112px;
  flex: 0 0 168px;
  position: relative;
  overflow: hidden;
  border-radius: 12px;
  background: #e5e7eb;
}

.entry-image {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
}

.price-tag {
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
  gap: 8px;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
}

.entry-title {
  font-weight: 700;
}

.entry-meta {
  margin-top: 10px;
  color: #334155;
}

.reason-row {
  align-items: flex-start;
}

.reason-value {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.reason-toggle {
  padding: 0;
  height: auto;
  align-self: flex-start;
}

.reason-bullet-list {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 4px;
}

@media (max-width: 768px) {
  .result-container {
    padding: 12px;
  }

  .content-wrapper,
  .top-info-section {
    flex-direction: column;
  }

  .side-nav,
  .left-info,
  .right-map {
    width: 100%;
    flex: 1 1 auto;
  }

  .map-card {
    min-height: 360px;
  }

  .map-wrap,
  .mapbox-container {
    min-height: 320px;
  }

  .map-story-panel {
    width: calc(100% - 24px);
  }

  .story-card {
    flex-direction: column;
  }

  .story-image {
    width: 100%;
    height: 120px;
    flex-basis: auto;
  }

  .entry-layout {
    flex-direction: column;
  }

  .entry-image-wrap {
    width: 100%;
    height: 180px;
    flex-basis: auto;
  }
}
</style>

undefined
