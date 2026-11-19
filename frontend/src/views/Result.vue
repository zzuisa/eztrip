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
        <a-dropdown v-if="!editMode">
          <template #overlay>
            <a-menu>
              <a-menu-item key="image" @click="exportAsImage"
                >📷 导出为图片</a-menu-item
              >
              <a-menu-item key="pdf" @click="exportAsPDF"
                >📄 导出为PDF</a-menu-item
              >
            </a-menu>
          </template>
          <a-button type="default"
            >📥 导出行程
            <DownOutlined />
          </a-button>
        </a-dropdown>
      </a-space>
    </div>

    <div v-if="tripPlan" class="content-wrapper">
      <div class="side-nav">
        <a-affix :offset-top="80">
          <a-menu
            mode="inline"
            :selected-keys="[activeSection]"
            @click="scrollToSection"
          >
            <a-menu-item key="overview"><span>📋 行程概览</span></a-menu-item>
            <a-menu-item key="budget" v-if="tripPlan.budget"
              ><span>💰 预算明细</span></a-menu-item
            >
            <a-menu-item key="map"><span>📍 景点地图</span></a-menu-item>
            <a-sub-menu key="days" title="📅 每日行程">
              <a-menu-item
                v-for="(day, index) in tripPlan.days"
                :key="`day-${index}`"
                >第{{ getDayIndex(day, index) + 1 }}天</a-menu-item
              >
            </a-sub-menu>
            <a-menu-item
              key="weather"
              v-if="tripPlan.weather_info && tripPlan.weather_info.length > 0"
              ><span>🌤️ 天气信息</span></a-menu-item
            >
          </a-menu>
        </a-affix>
      </div>

      <div class="main-content">
        <div class="top-info-section">
          <div class="left-info">
            <a-card
              id="overview"
              :title="`${tripPlan.city} · RogueTrip旅行计划`"
              :bordered="false"
              class="overview-card"
            >
              <div class="overview-content">
                <div class="info-item">
                  <span class="info-label">📅 日期:</span
                  ><span class="info-value"
                    >{{ tripPlan.start_date }} 至 {{ tripPlan.end_date }}</span
                  >
                </div>
                <div class="info-item">
                  <span class="info-label">💡 建议:</span
                  ><span class="info-value">{{
                    tripPlan.overall_suggestions
                  }}</span>
                </div>
              </div>
            </a-card>

            <a-card
              id="budget"
              v-if="tripPlan.budget"
              title="💰 预算明细"
              :bordered="false"
              class="budget-card"
            >
              <div class="budget-grid">
                <div class="budget-item">
                  <div class="budget-label">景点门票</div>
                  <div class="budget-value">
                    {{ formatCurrency(tripPlan.budget.total_attractions) }}
                  </div>
                </div>
                <div class="budget-item">
                  <div class="budget-label">酒店住宿</div>
                  <div class="budget-value">
                    {{ formatCurrency(tripPlan.budget.total_hotels) }}
                  </div>
                </div>
                <div class="budget-item">
                  <div class="budget-label">餐饮费用</div>
                  <div class="budget-value">
                    {{ formatCurrency(tripPlan.budget.total_meals) }}
                  </div>
                </div>
                <div class="budget-item">
                  <div class="budget-label">交通费用</div>
                  <div class="budget-value">
                    {{ formatCurrency(tripPlan.budget.total_transportation) }}
                  </div>
                </div>
              </div>
              <div class="budget-total">
                <span class="total-label">预估总费用</span
                ><span class="total-value">{{
                  formatCurrency(tripPlan.budget.total)
                }}</span>
              </div>
            </a-card>
          </div>

          <ResultMapSection
            :days="tripPlan.days"
            :route-colors="routeColors"
            :map-story="mapStory"
            @image-error="handleImageError"
          />
        </div>

        <ResultDaysSection
          v-if="tripPlan?.days?.length"
          :days="tripPlan.days"
          :selected-place-key="selectedPlaceKey"
          :active-days="activeDays"
          @add-day-to-deep-link="addDayToDeepLink"
          @open-google-maps-collection="openGoogleMapsCollection"
          @focus-place="focusPlace"
          @toggle-favorite="toggleFavorite"
          @copy-address="copyAddress"
          @navigate="openGoogleMapsNavigate"
          @focus-meal="focusMeal"
          @image-error="handleImageError"
        />

        <ResultPosterSection
          :story="posterStory"
          :visible="lightboxVisible"
          :frames="posterPlaybackFrames"
          :guide-slides="posterGuideSlides"
          :active-index="lightboxIndex"
          :zoom-scale="zoomScale"
          :is-fullscreen="isPosterFullscreen"
          :autoplay-paused="isPosterAutoplayPaused"
          :transition-preset="posterTransitionPreset"
          @open="openPosterLightbox"
          @performance-downgrade="handlePosterPerformanceDowngrade"
          @update:active-index="setLightboxIndex"
          @request-prev="goPrevPosterFrame"
          @request-next="goNextPosterFrame"
          @toggle-zoom="togglePosterZoom"
          @toggle-fullscreen="togglePosterFullscreen"
          @toggle-autoplay="handleTogglePosterAutoplay"
          @wheel-zoom="handlePosterWheelZoom"
          @touch-start="onPosterTouchStart"
          @touch-end="onPosterTouchEnd"
          @close="closePosterLightbox"
        />
        <ResultWeatherSection :weather-info="tripPlan.weather_info || []" />
      </div>
    </div>

    <ResultDeepLinkSection
      :visible="deepLinkVisible"
      :current-day-index="currentDeepLinkDayIndex"
      :day-options="deepLinkDayOptions"
      :items="deepLinkItems"
      @update:current-day-index="
        (value) => {
          currentDeepLinkDayIndex.value = value;
        }
      "
      @add-current-day="addCurrentDayToDeepLink"
      @build-from-selection="buildDeepLinkFromSelection"
      @open-google-maps="openDeepLinkInGoogleMaps"
      @copy-url="copyDeepLinkUrl"
      @move-item="moveDeepLinkItem"
      @remove-item="removeDeepLinkItem"
      @copy-item-address="copyDeepLinkItemAddress"
      @close="deepLinkVisible = false"
    />

    <a-empty v-if="!tripPlan" description="没有找到旅行计划数据">
      <template #image>
        <div style="font-size: 80px">🗺️</div>
      </template>
      <template #description
        ><span style="color: #999"
          >暂无旅行计划数据,请先创建行程</span
        ></template
      >
      <a-button type="primary" @click="goBack">返回首页创建行程</a-button>
    </a-empty>

    <a-back-top :visibility-height="300">
      <div class="back-top-button">↑</div>
    </a-back-top>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, nextTick, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { message } from "ant-design-vue";
import { DownOutlined } from "@ant-design/icons-vue";
import type { TripPlan } from "@/types";
import { fetchTravelPlanResultById, logPosterPlaybackEvent } from "@/services/api";
import { isSessionTripPlanUsable } from "@/services/result-session-adapter";
import { buildPosterStory } from "@/services/poster-data-service";
import { buildPosterGuideSlides } from "@/services/poster-guide-script-service";
import ResultDaysSection from "@/views/result/ResultDaysSection.vue";
import ResultMapSection from "@/views/result/ResultMapSection.vue";
import ResultPosterSection from "@/views/result/ResultPosterSection.vue";
import ResultWeatherSection from "@/views/result/ResultWeatherSection.vue";
import ResultDeepLinkSection from "@/views/result/ResultDeepLinkSection.vue";
import { useItineraryEditing } from "@/composables/useItineraryEditing";
import { usePosterInteraction } from "@/composables/usePosterInteraction";
import { useResultPage } from "@/composables/useResultPage";
import { useMapState } from "@/composables/useMapState";
import { useResultMedia } from "@/composables/useResultMedia";
import { useResultDeepLink } from "@/composables/useResultDeepLink";
import {
  getDayIndex,
  getTimelineSlots as buildTimelineSlotsHelper,
  normalizeTripPlanFromSession,
} from "@/views/result/result-helpers";

const router = useRouter();
const route = useRoute();
const tripPlan = ref<TripPlan | null>(null);
const attractionPhotos = ref<Record<string, string>>({});
const {
  activeSection,
  activeDays,
  selectedPlaceKey,
  deepLinkVisible,
  currentDeepLinkDayIndex,
  deepLinkItems,
} = useResultPage();
activeDays.value = [0];
const {
  editMode,
  toggleEditMode: startEditMode,
  cancelEditMode,
  saveChanges: saveEdits,
} = useItineraryEditing(tripPlan, {
  itineraryIdHint: String(route.params.id || ""),
});
const reasonExpanded = ref<Record<number, boolean>>({});
const posterStory = computed(() =>
  buildPosterStory({
    city: tripPlan.value?.city || "",
    days: tripPlan.value?.days || [],
  }),
);
const posterGuideSlides = computed(() => buildPosterGuideSlides(posterStory.value));
const posterPlaybackFrames = computed(() => posterGuideSlides.value.map((slide) => slide.frame));
const {
  lightboxVisible,
  lightboxIndex,
  zoomScale,
  isFullscreen: isPosterFullscreen,
  activeFrame: activePosterFrame,
  autoplayPaused: isPosterAutoplayPaused,
  transitionPreset: posterTransitionPreset,
  openLightbox,
  closeLightbox,
  setLightboxIndex,
  goPrev: goPrevPosterFrame,
  goNext: goNextPosterFrame,
  toggleZoom: togglePosterZoom,
  toggleFullscreen: togglePosterFullscreen,
  handleWheelZoom: handlePosterWheelZoom,
  handleTouchStart: onPosterTouchStart,
  handleTouchEnd: onPosterTouchEnd,
  toggleAutoplay: togglePosterAutoplay,
  syncPerformanceTier: syncPosterPerformanceTier,
  syncReducedMotion: syncPosterReducedMotion,
  downgradeTransitionTierOneStep: downgradePosterTransitionTier,
  restoreAnchor: restorePosterAnchor,
} = usePosterInteraction();
const {
  loadAttractionPhotos,
  getAttractionImage,
  handleImageError,
  exportAsImage,
  exportAsPDF,
} = useResultMedia(tripPlan, () => getMapSnapshotDataUrl());
const deepLinkDayOptions = ref<Array<{ label: string; value: number }>>([]);
const posterAutoplayOpened = ref(false);

onMounted(async () => {
  const sessionData = (() => {
    const data =
      sessionStorage.getItem("tripPlan") || sessionStorage.getItem("tripeplan");
    if (!data) return null;
    try {
      return JSON.parse(data);
    } catch (error) {
      console.error("解析 tripPlan 失败:", error);
      return null;
    }
  })();
  const sessionPlan = sessionData
    ? normalizeTripPlanFromSession(sessionData)
    : null;
  const sessionUsable = isSessionTripPlanUsable(sessionPlan);
  if (sessionUsable && sessionPlan) {
    tripPlan.value = sessionPlan;
  } else {
    const resultId = String(route.params.id || "");
    if (resultId && resultId !== "fallback") {
      try {
        const resp = await fetchTravelPlanResultById(resultId);
        if (resp.success && resp.data) {
          const fetchedPlan = normalizeTripPlanFromSession(resp.data);
          tripPlan.value =
            fetchedPlan && isSessionTripPlanUsable(fetchedPlan)
              ? fetchedPlan
              : sessionPlan;
        }
      } catch (error) {
        console.error("按ID加载 tripPlan 失败:", error);
        tripPlan.value = sessionPlan;
      }
    } else {
      tripPlan.value = sessionPlan;
    }
  }
  if (!tripPlan.value) return;
  debugTripPlanState("mounted");
  rebuildDeepLinkItems();
  await loadAttractionPhotos(() => getTripDays(), attractionPhotos);
  await nextTick();
  initMap();
  syncPosterPerformanceTier({
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: (navigator as Navigator & { deviceMemory?: number }).deviceMemory,
  });
  const motionMedia = window.matchMedia("(prefers-reduced-motion: reduce)");
  syncPosterReducedMotion(motionMedia.matches);
  motionMedia.addEventListener("change", (event) => syncPosterReducedMotion(event.matches));
});

watch(
  () => posterPlaybackFrames.value.length,
  (count) => {
    if (!count && activePosterFrame.value) {
      logPosterPlaybackEvent("stop", "frames cleared");
      closePosterLightbox();
      posterAutoplayOpened.value = false;
      return;
    }
    if (count > 0 && !posterAutoplayOpened.value) {
      posterAutoplayOpened.value = true;
      logPosterPlaybackEvent("start", `frames=${count}`);
      openLightbox(posterPlaybackFrames.value, 0, "trip-poster");
    }
  },
);
watch(
  () => lightboxIndex.value,
  (index) => {
    if (!lightboxVisible.value) return;
    logPosterPlaybackEvent("frame-change", `index=${index}`);
  },
);

const goBack = () => router.push("/");
const handlePosterPerformanceDowngrade = () => {
  downgradePosterTransitionTier();
};

const openPosterLightbox = (payload: { index: number; anchorId: string }) => {
  openLightbox(posterPlaybackFrames.value, payload.index + 1, payload.anchorId);
};
const closePosterLightbox = () => {
  logPosterPlaybackEvent("stop", "manual close");
  closeLightbox();
  restorePosterAnchor();
};
const handleTogglePosterAutoplay = () => {
  togglePosterAutoplay();
  logPosterPlaybackEvent(
    isPosterAutoplayPaused.value ? "pause" : "resume",
    `index=${lightboxIndex.value}`,
  );
};
const scrollToSection = ({ key }: { key: string }) => {
  activeSection.value = key;
  const element = document.getElementById(key);
  if (element) element.scrollIntoView({ behavior: "smooth", block: "start" });
};
const toggleEditMode = () => {
  startEditMode();
  message.info("进入编辑模式");
};
const saveChanges = () => {
  const result = saveEdits();
  if (!result.ok) return message.error(result.error);
  message.success("修改已保存");
  destroyMap();
  nextTick(() => {
    initMap();
  });
};
const cancelEdit = () => {
  cancelEditMode();
  message.info("已取消编辑");
};
const getMealLabel = (type: string): string =>
  ({ breakfast: "早餐", lunch: "午餐", dinner: "晚餐", snack: "小吃" })[type] ||
  type;
const getMealDuration = (type: string): string =>
  ({
    breakfast: "30-40 分钟",
    lunch: "60-90 分钟",
    dinner: "60-90 分钟",
    snack: "20-30 分钟",
  })[type] || "30 分钟";
const getAttractionDuration = (day: any, name: string): string =>
  day?.attractions?.find((a: any) => a.name === name)?.visit_duration
    ? `${day.attractions.find((a: any) => a.name === name).visit_duration} 分钟`
    : "90-120 分钟";
const formatPrice = (value?: number): string => formatCurrency(value);
const getCurrencySymbol = (): string =>
  ({ EUR: "€", USD: "$", GBP: "£", JPY: "¥", CNY: "¥" })[
    String((tripPlan.value as any)?.budget_currency || "EUR").toUpperCase()
  ] || "€";
const formatCurrency = (value?: number): string =>
  `${getCurrencySymbol()}${value === undefined || value === null ? 0 : value}`;
const getDayMealCount = (day: any): string => `${day.meals?.length || 0} 餐`;
const getTripDays = (): any[] =>
  Array.isArray(tripPlan.value?.days) ? tripPlan.value!.days : [];
const debugTripPlanState = (tag: string) => {
  const days = getTripDays();
  const first = days[0];
  console.debug(`[Result][${tag}]`, {
    city: tripPlan.value?.city,
    days: days.length,
    firstDayTitle: first?.display_title || first?.title,
    firstDayActivities: Array.isArray(first?.activities)
      ? first.activities.length
      : 0,
    firstDayAttractions: Array.isArray(first?.attractions)
      ? first.attractions.length
      : 0,
    firstDayMeals: Array.isArray(first?.meals) ? first.meals.length : 0,
  });
};
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
    getPlaceKey: (dayIndex: number, name: string, kind: 'attraction' | 'meal', mealType?: string) => `${dayIndex}-${kind}-${mealType || ''}-${name}`,
    getMealLabel,
    getTimelineSlots: buildTimelineSlotsHelper,
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
const {
  focusPlace,
  focusAttraction,
  focusMeal,
  addDayToDeepLink,
  openDeepLinkBuilder,
  addCurrentDayToDeepLink,
  buildDeepLinkFromSelection,
  copyDeepLinkUrl,
  openDeepLinkInGoogleMaps,
  copyDeepLinkItemAddress,
  removeDeepLinkItem,
  moveDeepLinkItem,
  rebuildDeepLinkItems,
} = useResultDeepLink({
  tripPlan,
  deepLinkVisible,
  currentDeepLinkDayIndex,
  deepLinkItems,
  deepLinkDayOptions,
  selectedPlaceKey,
  activeDays,
  getMealLabel,
  getPlaceKey: (dayIndex: number, name: string, kind: 'attraction' | 'meal', mealType?: string) => `${dayIndex}-${kind}-${mealType || ''}-${name}`,
  focusMapWithPageTransition,
  focusMapOn,
  scrollCardIntoView,
  getAttractionCardId: (dayIndex: number, index: number) => `day-${dayIndex}-attraction-${index}`,
  getMealCardId: (dayIndex: number, mealType: string) => `day-${dayIndex}-meal-${mealType}`,
})
const getGoogleMapsUrl = (name: string, latitude?: number, longitude?: number) =>
  latitude !== undefined && longitude !== undefined
    ? `https://www.google.com/maps/dir/?api=1&travelmode=walking&destination=${encodeURIComponent(`${latitude},${longitude}`)}`
    : `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(name)}`
const openGoogleMapsNavigate = (name: string, latitude?: number, longitude?: number) => {
  window.open(getGoogleMapsUrl(name, latitude, longitude), '_blank', 'noopener,noreferrer')
}
const openGoogleMapsCollection = () => {
  const locations = deepLinkItems.value.filter((item) => item.latitude !== undefined && item.longitude !== undefined).map((item) => `${item.latitude},${item.longitude}`)
  if (locations.length === 0) return
  window.open(`https://www.google.com/maps/dir/?api=1&travelmode=walking&waypoints=${encodeURIComponent(locations.join('|'))}`, '_blank', 'noopener,noreferrer')
}
function scrollCardIntoView(id: string) {
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
}
const getTimelineSlots = (day: any) => buildTimelineSlotsHelper(day)
const getAttractionImageByName = (day: any, name: string): string => {
  const attractions = Array.isArray(day?.attractions) ? day.attractions : []
  const item = attractions.find((a: any) => a.name === name)
  if (!item) return getAttractionImage(attractionPhotos, { name }, 0)
  const idx = attractions.findIndex((a: any) => a.name === name)
  return getAttractionImage(attractionPhotos, item, idx >= 0 ? idx : 0)
}

</script>

<style scoped src="./result/result-styles.css"></style>
