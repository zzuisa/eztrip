import { computed, onBeforeUnmount, ref, watch, type Ref } from 'vue'
import mapboxgl from 'mapbox-gl'
import { message } from 'ant-design-vue'
import type { TripPlan } from '@/types'

export interface UseMapStateOptions {
  routeColors?: string[]
  getPlaceKey: (dayIndex: number, name: string, kind: 'attraction' | 'meal', mealType?: string) => string
  getMealLabel: (type: string) => string
  /**
   * Result.vue 现有的时间轴分组函数，用于绘制路线与故事动画站点顺序。
   */
  getTimelineSlots: (day: any) => Array<{ key: string; label: string; entries: any[] }>
  /**
   * 点击 marker 后，如果希望额外滚动/高亮，可在这里处理。
   */
  onMarkerSelected?: (payload: { kind: 'attraction' | 'meal'; dayIndex: number; name: string; mealType?: string }) => void
}

export function useMapState(params: {
  tripPlan: Ref<TripPlan | null>
  activeDays: Ref<any>
  selectedPlaceKey: Ref<string>
}, options: UseMapStateOptions) {
  const routeColors = options.routeColors || ['#1890ff', '#52c41a', '#fa8c16', '#722ed1', '#eb2f96', '#13c2c2']

  const MAP_DEFAULT_ZOOM = 12
  const MAP_FOCUS_ZOOM = 15
  const MAP_MEAL_FOCUS_ZOOM = 15.5
  const MAP_STORY_ZOOM = 14.5

  // Mapbox 的类型定义在某些版本下会触发 vue-tsc “类型实例化过深”。
  // 这里对地图对象采用弱类型，保证构建稳定。
  const map = ref<any>(null)
  let popup: any = null
  let markerInstances: any[] = []
  let routeLayerIds: string[] = []
  let routeSourceIds: string[] = []

  const mapReady = ref(false)
  const mapFailed = ref(false)

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

  const hasTripPlan = computed(() => Boolean(params.tripPlan.value))

  const getActiveDayIndex = (): number => {
    const value = params.activeDays.value as any
    if (Array.isArray(value)) {
      const first = value[0]
      return typeof first === 'number' ? first : Number(first || 0)
    }
    if (typeof value === 'number') return value
    if (typeof value === 'string') return Number(value || 0)
    return 0
  }

  const stopWalkerAnimation = () => {
    if (walkerAnimationFrame !== null) {
      cancelAnimationFrame(walkerAnimationFrame)
      walkerAnimationFrame = null
    }
    if (walkerPauseTimer !== null) {
      window.clearTimeout(walkerPauseTimer)
      walkerPauseTimer = null
    }
  }

  const removeWalkerMarker = () => {
    try {
      walkerMarker?.remove()
    } catch (_) {}
    walkerMarker = null
  }

  const createWalkerMarker = () => {
    if (!map.value) return null
    const markerEl = document.createElement('div')
    markerEl.className = 'walker-marker'
    markerEl.textContent = '🚶'
    walkerMarker = new (mapboxgl as any).Marker({ element: markerEl, anchor: 'bottom' })
    return walkerMarker
  }

  const clearMapOverlays = () => {
    stopWalkerAnimation()
    removeWalkerMarker()
    mapStory.value.visible = false
    markerInstances.forEach((m) => {
      try {
        m.remove()
      } catch (_) {}
    })
    markerInstances = []
    routeLayerIds.forEach((id) => {
      try {
        if (map.value?.getLayer(id)) map.value.removeLayer(id)
      } catch (_) {}
    })
    routeSourceIds.forEach((id) => {
      try {
        if (map.value?.getSource(id)) map.value.removeSource(id)
      } catch (_) {}
    })
    routeLayerIds = []
    routeSourceIds = []
  }

  const destroyMap = () => {
    clearMapOverlays()
    try {
      popup?.remove()
    } catch (_) {}
    popup = null
    try {
      map.value?.remove()
    } catch (_) {}
    map.value = null
    mapReady.value = false
  }

  const focusMapOn = (lng: number, lat: number, zoom = MAP_FOCUS_ZOOM) => {
    if (!map.value) return
    try {
      if (map.value.isStyleLoaded?.()) {
        map.value.resize?.()
      }
      map.value.flyTo?.({ center: [lng, lat], zoom, essential: true })
    } catch (_) {}
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

  const getLatLng = (item: any): { lng: number; lat: number } | null => {
    const lat = Number(item?.latitude ?? item?.lat ?? item?.location?.latitude)
    const lng = Number(item?.longitude ?? item?.lng ?? item?.location?.longitude)
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null
    return { lng, lat }
  }

  const buildMealImage = (title: string) => {
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><defs><linearGradient id="mealGrad" x1="0%" y1="0%" x2="100%" y2="100%"><stop offset="0%" style="stop-color:#34d399;stop-opacity:1" /><stop offset="100%" style="stop-color:#059669;stop-opacity:1" /></linearGradient></defs><rect width="400" height="300" fill="url(#mealGrad)"/><text x="50%" y="45%" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="42" fill="white">🍽️</text><text x="50%" y="62%" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="22" fill="white">${String(title)}</text></svg>`
    return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`
  }

  const getAnimatedStopsByDay = (dayIndex: number) => {
    const day = params.tripPlan.value?.days?.[dayIndex]
    if (!day) return []
    const timelineEntries = options.getTimelineSlots(day).flatMap((slot: any) => slot.entries || [])
    return timelineEntries
      .map((entry: any, idx: number) => {
        const coords = getLatLng(entry)
        if (!coords) return null
        const isAttraction = entry.kind === 'attraction'
        const image = isAttraction ? entry.image || '' : buildMealImage(entry.title || `餐饮${idx + 1}`)
        return {
          name: entry.title || `站点${idx + 1}`,
          description: entry.description || entry.route_desc || '',
          address: entry.address || '',
          lng: coords.lng,
          lat: coords.lat,
          image,
        }
      })
      .filter((item): item is { name: string; description: string; address: string; lng: number; lat: number; image: string } => item !== null)
  }

  const startDayStoryAnimation = (dayIndex: number) => {
    if (!map.value) return
    stopWalkerAnimation()
    removeWalkerMarker()
    const stops = getAnimatedStopsByDay(dayIndex)
    if (stops.length === 0) {
      mapStory.value.visible = false
      return
    }

    const marker = createWalkerMarker()
    if (!marker) return
    marker.setLngLat([stops[0].lng, stops[0].lat]).addTo(map.value)

    mapStory.value.visible = true
    mapStory.value.current = {
      name: stops[0].name,
      description: stops[0].description,
      address: stops[0].address,
      image: stops[0].image,
    }
    mapStory.value.next = stops[1]
      ? { name: stops[1].name, description: stops[1].description, address: stops[1].address, image: stops[1].image }
      : null
    mapStory.value.transitionProgress = 0

    map.value.flyTo({ center: [stops[0].lng, stops[0].lat], zoom: MAP_STORY_ZOOM, essential: true })
    if (stops.length === 1) return

    const loopPauseDuration = 900
    const easeInOut = (t: number) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2)
    const toRad = (v: number) => (v * Math.PI) / 180
    const calcDistanceKm = (from: { lng: number; lat: number }, to: { lng: number; lat: number }) => {
      const earthRadiusKm = 6371
      const dLat = toRad(to.lat - from.lat)
      const dLng = toRad(to.lng - from.lng)
      const a =
        Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(toRad(from.lat)) * Math.cos(toRad(to.lat)) * Math.sin(dLng / 2) * Math.sin(dLng / 2)
      const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
      return earthRadiusKm * c
    }
    const calcSegmentDuration = (from: { lng: number; lat: number }, to: { lng: number; lat: number }) => {
      const distanceKm = calcDistanceKm(from, to)
      const dynamic = 2400 + Math.sqrt(distanceKm + 0.02) * 2100
      return Math.min(5600, Math.max(2600, dynamic))
    }
    const calcStopDuration = (from: { lng: number; lat: number }, to: { lng: number; lat: number }) => {
      const distanceKm = calcDistanceKm(from, to)
      const dynamic = 1200 + Math.sqrt(distanceKm + 0.02) * 700
      return Math.min(2300, Math.max(1100, dynamic))
    }

    const runSegment = (segmentIndex: number) => {
      const from = stops[segmentIndex]
      const to = stops[segmentIndex + 1]
      if (!from || !to || !map.value) {
        mapStory.value.transitionProgress = 0
        mapStory.value.next = null
        return
      }
      const segmentDuration = calcSegmentDuration(from, to)
      const stopDuration = calcStopDuration(from, to)
      const startTime = performance.now()

      const tick = (now: number) => {
        if (!map.value) return
        const rawProgress = Math.min((now - startTime) / segmentDuration, 1)
        const eased = easeInOut(rawProgress)
        const lng = from.lng + (to.lng - from.lng) * eased
        const lat = from.lat + (to.lat - from.lat) * eased
        marker.setLngLat([lng, lat])
        map.value.easeTo({
          center: [lng, lat],
          zoom: MAP_STORY_ZOOM,
          duration: 180,
          easing: (v: number) => v,
          essential: true,
        })
        mapStory.value.transitionProgress = Math.min(rawProgress / 0.25, 1)
        if (rawProgress < 1) {
          walkerAnimationFrame = requestAnimationFrame(tick)
          return
        }
        mapStory.value.transitionProgress = 1
        const future = stops[segmentIndex + 2]
        walkerPauseTimer = window.setTimeout(() => {
          walkerPauseTimer = null
          mapStory.value.current = { name: to.name, description: to.description, address: to.address, image: to.image }
          mapStory.value.next = future
            ? { name: future.name, description: future.description, address: future.address, image: future.image }
            : null
          mapStory.value.transitionProgress = 0

          if (segmentIndex + 1 < stops.length - 1) {
            walkerPauseTimer = window.setTimeout(() => {
              walkerPauseTimer = null
              runSegment(segmentIndex + 1)
            }, stopDuration)
          } else {
            walkerPauseTimer = window.setTimeout(() => {
              walkerPauseTimer = null
              startDayStoryAnimation(dayIndex)
            }, loopPauseDuration)
          }
        }, 700)
      }

      walkerAnimationFrame = requestAnimationFrame(tick)
    }

    runSegment(0)
  }

  const drawRoutes = () => {
    if (!params.tripPlan.value || !map.value) return

    params.tripPlan.value.days.forEach((day: any, dayIndex: number) => {
      const timelineEntries = options.getTimelineSlots(day).flatMap((slot: any) => slot.entries || [])
      const coordinates = timelineEntries
        .filter((entry: any) => entry.longitude !== undefined && entry.latitude !== undefined)
        .map((entry: any) => [entry.longitude, entry.latitude] as [number, number])

      if (coordinates.length < 2) return

      const sourceId = `route-source-${dayIndex}`
      const layerId = `route-layer-${dayIndex}`
      const dayColor = routeColors[dayIndex % routeColors.length]

      try {
        if (map.value.getLayer(layerId)) map.value.removeLayer(layerId)
        if (map.value.getSource(sourceId)) map.value.removeSource(sourceId)
      } catch (_) {}

      routeLayerIds.push(layerId)
      routeSourceIds.push(sourceId)

      map.value.addSource(sourceId, {
        type: 'geojson',
        data: {
          type: 'Feature',
          geometry: { type: 'LineString', coordinates },
          properties: {},
        },
      })

      map.value.addLayer({
        id: layerId,
        type: 'line',
        source: sourceId,
        paint: {
          'line-color': dayColor,
          'line-width': 5,
          'line-opacity': 0.85,
        },
        layout: { 'line-cap': 'round', 'line-join': 'round' },
      })
    })
  }

  const addAttractionMarkers = () => {
    if (!params.tripPlan.value || !map.value) return

    clearMapOverlays()

    const markerBounds = new mapboxgl.LngLatBounds()
    const allAttractions: any[] = []
    const allMeals: any[] = []

    const getLatLng = (item: any): { lng: number; lat: number } | null => {
      const lat = Number(item?.location?.latitude ?? item?.latitude ?? item?.lat)
      const lng = Number(item?.location?.longitude ?? item?.longitude ?? item?.lng)
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null
      return { lat, lng }
    }

    params.tripPlan.value.days.forEach((day: any, dayIndex: number) => {
      ;(day.attractions || []).forEach((attraction: any, attrIndex: number) => {
        const coords = getLatLng(attraction)
        if (coords) {
          allAttractions.push({ ...attraction, dayIndex, attrIndex, location: { latitude: coords.lat, longitude: coords.lng } })
        }
      })
      ;(day.meals || []).forEach((meal: any) => {
        const coords = getLatLng(meal)
        if (coords) {
          allMeals.push({ ...meal, dayIndex, location: { latitude: coords.lat, longitude: coords.lng } })
        }
      })
    })

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
      const marker = new (mapboxgl as any).Marker({ element: markerEl, anchor: 'center' }).setLngLat(lngLat).addTo(map.value)
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
      const markerPopup = new (mapboxgl as any).Popup({ offset: 24 }).setHTML(html)
      marker.setPopup(markerPopup)

      markerEl.addEventListener('click', () => {
        if (popup && popup !== markerPopup) popup.remove()
        popup = markerPopup
        params.selectedPlaceKey.value = options.getPlaceKey(attraction.dayIndex, attraction.name, 'attraction')
        options.onMarkerSelected?.({ kind: 'attraction', dayIndex: attraction.dayIndex, name: attraction.name })
        marker.togglePopup()
        focusMapWithPageTransition(lngLat[0], lngLat[1], MAP_FOCUS_ZOOM)
      })
    })

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

      const mealMarkerMap: Record<string, string> = { breakfast: 'B', lunch: 'L', dinner: 'D', snack: 'S' }
      markerEl.textContent = mealMarkerMap[meal.type] || 'M'

      const lngLat: [number, number] = [meal.location.longitude, meal.location.latitude]
      const marker = new (mapboxgl as any).Marker({ element: markerEl, anchor: 'center' }).setLngLat(lngLat).addTo(map.value)
      markerInstances.push(marker)
      markerBounds.extend(lngLat)

      const html = `
        <div style="padding: 8px; min-width: 220px;">
          <h4 style="margin: 0 0 8px 0;">${meal.name}</h4>
          <p style="margin: 4px 0;"><strong>类型:</strong> ${options.getMealLabel(meal.type)}</p>
          <p style="margin: 4px 0;"><strong>时间:</strong> ${meal.time || '待定'}</p>
          <p style="margin: 4px 0;"><strong>地址:</strong> ${meal.address || '暂无'}</p>
          <p style="margin: 4px 0;"><strong>描述:</strong> ${meal.description || '暂无描述'}</p>
          <p style="margin: 4px 0; color: #1890ff;"><strong>第${meal.dayIndex + 1}天</strong></p>
        </div>
      `
      const markerPopup = new (mapboxgl as any).Popup({ offset: 24 }).setHTML(html)
      marker.setPopup(markerPopup)

      markerEl.addEventListener('click', () => {
        if (popup && popup !== markerPopup) popup.remove()
        popup = markerPopup
        params.selectedPlaceKey.value = options.getPlaceKey(meal.dayIndex, meal.name, 'meal', meal.type)
        options.onMarkerSelected?.({ kind: 'meal', dayIndex: meal.dayIndex, name: meal.name, mealType: meal.type })
        marker.togglePopup()
        focusMapWithPageTransition(lngLat[0], lngLat[1], MAP_MEAL_FOCUS_ZOOM)
      })
    })

    if (allAttractions.length > 0) {
      map.value.fitBounds(markerBounds, { padding: 40 })
    }

    drawRoutes()
    window.setTimeout(() => {
      startDayStoryAnimation(getActiveDayIndex())
    }, 280)
  }

  const initMap = async () => {
    mapFailed.value = false
    mapReady.value = false
    try {
      const token = (import.meta as any).env?.VITE_MAPBOX_ACCESS_TOKEN
      if (!token) {
        mapFailed.value = true
        message.error('缺少 VITE_MAPBOX_ACCESS_TOKEN，无法加载地图')
        return
      }
      mapboxgl.accessToken = token

      const container = document.getElementById('mapbox-container')
      if (!container) {
        mapFailed.value = true
        message.error('地图容器未找到')
        return
      }

      if (map.value) {
        destroyMap()
      }

      map.value = new (mapboxgl as any).Map({
        container: 'mapbox-container',
        style: 'mapbox://styles/mapbox/streets-v12',
        center: [116.397128, 39.916527],
        zoom: MAP_DEFAULT_ZOOM,
      })

      map.value.on?.('load', () => {
        map.value?.resize?.()
        mapReady.value = true
        addAttractionMarkers()
      })

      window.setTimeout(() => map.value?.resize?.(), 120)
      window.setTimeout(() => map.value?.resize?.(), 420)
    } catch (error) {
      console.error('地图加载失败:', error)
      mapFailed.value = true
      message.error('地图加载失败')
    }
  }

  const getMapSnapshotDataUrl = (): string | null => {
    try {
      const mapContainer = document.getElementById('mapbox-container')
      if (!mapContainer || !map.value) return null
      const canvas = mapContainer.querySelector('canvas') as HTMLCanvasElement | null
      if (!canvas) return null
      return canvas.toDataURL('image/png')
    } catch {
      return null
    }
  }

  const rebuild = () => {
    if (!map.value || !hasTripPlan.value) return
    addAttractionMarkers()
  }

  watch(
    () => params.tripPlan.value,
    () => {
      if (!map.value) return
      rebuild()
    },
  )

  watch(
    () => params.activeDays.value,
    () => {
      if (!map.value) return
      window.setTimeout(() => {
        startDayStoryAnimation(getActiveDayIndex())
      }, 180)
    },
  )

  onBeforeUnmount(() => {
    destroyMap()
  })

  return {
    routeColors,
    mapReady,
    mapFailed,
    mapStory,
    initMap,
    destroyMap,
    rebuild,
    clearMapOverlays,
    focusMapOn,
    focusMapWithPageTransition,
    startDayStoryAnimation,
    getMapSnapshotDataUrl,
  }
}

