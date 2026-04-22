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
import html2canvas from 'html2canvas'
import jsPDF from 'jspdf'
import type { TripPlan } from '@/types'
import { fetchTravelPlanResultById } from '@/services/api'
import { buildPosterStory } from '@/services/poster-data-service'
import TripPosterGallery from '@/components/poster/TripPosterGallery.vue'
import { useItineraryEditing } from '@/composables/useItineraryEditing'
import { useResultPage } from '@/composables/useResultPage'
import { useMapState } from '@/composables/useMapState'

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
  destroyMap()
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

// activeDays 的地图故事切换已由 useMapState 内部 watch 处理

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
const {
  routeColors,
  mapStory,
  initMap,
  destroyMap,
  focusMapOn,
  focusMapWithPageTransition,
  getMapSnapshotDataUrl,
} = useMapState(
  { tripPlan, activeDays, selectedPlaceKey },
  {
    getPlaceKey,
    getMealLabel,
    getTimelineSlots,
    onMarkerSelected: ({ kind, dayIndex, name, mealType }) => {
      if (kind === 'attraction') {
        const day = getTripDays()[dayIndex]
        const idx = day?.attractions?.findIndex((a: any) => a?.name === name) ?? -1
        if (idx >= 0) focusAttraction(dayIndex, idx)
        return
      }
      const day = getTripDays()[dayIndex]
      const meal = day?.meals?.find((m: any) => String(m?.name || '') === name && String(m?.type || '') === String(mealType || ''))
      if (meal) focusMeal(dayIndex, meal)
    },
  },
)
const focusPlace = (entry: any) => {
  selectedPlaceKey.value = entry.key
  if (entry.longitude && entry.latitude) {
    focusMapWithPageTransition(entry.longitude, entry.latitude, entry.kind === 'meal' ? 15.5 : 15)
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
    focusMapWithPageTransition(meal.location.longitude, meal.location.latitude, 15.5)
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

function scrollCardIntoView(id: string) {
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

function getTimelineSlots(day: any) {
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
    const mapSnapshot = getMapSnapshotDataUrl()
    if (mapSnapshot) {
      const exportMapContainer = exportContainer.querySelector('#mapbox-container')
      if (exportMapContainer) {
        exportMapContainer.innerHTML = `<img src="${mapSnapshot}" style="width:100%;height:100%;object-fit:cover;" />`
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
    const mapSnapshot = getMapSnapshotDataUrl()
    if (mapSnapshot) {
      const exportMapContainer = exportContainer.querySelector('#mapbox-container')
      if (exportMapContainer) {
        exportMapContainer.innerHTML = `<img src="${mapSnapshot}" style="width:100%;height:100%;object-fit:cover;" />`
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

// 地图初始化与 overlay 绘制已由 useMapState 接管
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
