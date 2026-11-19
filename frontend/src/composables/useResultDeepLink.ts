import { watch, type Ref } from 'vue'
import type { TripPlan } from '@/types'
import { getDayIndex } from '@/views/result/result-helpers'
import {
  buildDayDeepLinkItems as buildDayDeepLinkItemsFromService,
  buildGoogleMapsDeepLinkUrl as buildGoogleMapsDeepLinkUrlFromService,
} from '@/services/deep-link-service'

export type DeepLinkItem = {
  key: string
  label: string
  name: string
  latitude?: number
  longitude?: number
  type: 'attraction' | 'meal'
  address?: string
}

export type DeepLinkDayOption = {
  label: string
  value: number
}

export function useResultDeepLink(params: {
  tripPlan: Ref<TripPlan | null>
  deepLinkVisible: Ref<boolean>
  currentDeepLinkDayIndex: Ref<number>
  deepLinkItems: Ref<DeepLinkItem[]>
  deepLinkDayOptions: Ref<DeepLinkDayOption[]>
  selectedPlaceKey: Ref<string>
  activeDays: Ref<number[]>
  getMealLabel: (type: string) => string
  getPlaceKey: (dayIndex: number, name: string, kind: 'attraction' | 'meal', mealType?: string) => string
  focusMapWithPageTransition: (longitude: number, latitude: number, zoom?: number) => void
  focusMapOn: (longitude: number, latitude: number) => void
  scrollCardIntoView: (id: string) => void
  getAttractionCardId: (dayIndex: number, index: number) => string
}) {
  const {
    tripPlan,
    deepLinkVisible,
    currentDeepLinkDayIndex,
    deepLinkItems,
    deepLinkDayOptions,
    selectedPlaceKey,
    activeDays,
    getMealLabel,
    getPlaceKey,
    focusMapWithPageTransition,
    focusMapOn,
    scrollCardIntoView,
    getAttractionCardId,
  } = params

  const getTripDays = (): any[] => (Array.isArray(tripPlan.value?.days) ? tripPlan.value!.days : [])

  const buildDayDeepLinkItems = (dayIndex: number) => {
    const day = getTripDays()[dayIndex]
    return buildDayDeepLinkItemsFromService({
      day,
      dayIndex,
      getMealLabel,
      getPlaceKey,
    }) as DeepLinkItem[]
  }

  const rebuildDeepLinkDayOptions = () => {
    deepLinkDayOptions.value = getTripDays().map((day: any, index: number) => ({
      label: `第${getDayIndex(day, index) + 1}天`,
      value: index,
    }))
  }

  const rebuildDeepLinkItems = () => {
    deepLinkItems.value = buildDayDeepLinkItems(currentDeepLinkDayIndex.value)
    rebuildDeepLinkDayOptions()
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

  const buildGoogleMapsDeepLinkUrl = () => {
    return buildGoogleMapsDeepLinkUrlFromService(deepLinkItems.value)
  }

  const copyDeepLinkUrl = async () => {
    const url = buildGoogleMapsDeepLinkUrl()
    await navigator.clipboard.writeText(url)
  }

  const openDeepLinkInGoogleMaps = () => {
    window.open(buildGoogleMapsDeepLinkUrl(), '_blank', 'noopener,noreferrer')
  }

  const copyDeepLinkItemAddress = async (item: any) => {
    if (!item.address) return
    await navigator.clipboard.writeText(item.address)
  }

  const removeDeepLinkItem = (index: number) => {
    deepLinkItems.value.splice(index, 1)
  }

  const addDayToDeepLink = (dayIndex: number) => {
    deepLinkItems.value = buildDayDeepLinkItems(dayIndex)
  }

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

  watch(
    () => tripPlan.value,
    () => {
      rebuildDeepLinkDayOptions()
      if (tripPlan.value) rebuildDeepLinkItems()
    },
    { deep: true },
  )

  watch(currentDeepLinkDayIndex, (dayIndex) => {
    if (!deepLinkVisible.value) return
    deepLinkItems.value = buildDayDeepLinkItems(dayIndex)
  })

  return {
    buildDayDeepLinkItems,
    rebuildDeepLinkDayOptions,
    rebuildDeepLinkItems,
    moveDeepLinkItem,
    openDeepLinkBuilder,
    addCurrentDayToDeepLink,
    buildDeepLinkFromSelection,
    buildGoogleMapsDeepLinkUrl,
    copyDeepLinkUrl,
    openDeepLinkInGoogleMaps,
    copyDeepLinkItemAddress,
    removeDeepLinkItem,
    addDayToDeepLink,
    focusPlace,
    focusAttraction,
    focusMeal,
  }
}
