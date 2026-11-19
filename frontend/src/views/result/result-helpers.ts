import type { TripPlan } from '@/types'

export type TimelineEntry = {
  key: string
  kind: 'attraction' | 'meal'
  mealType?: string
  title: string
  time: string
  address?: string
  description?: string
  route_desc?: string
  ticket_price?: number
  preference_matched?: boolean
  preference_reason?: string
  latitude?: number
  longitude?: number
  cardId: string
}

export type TimelineSlot = {
  key: 'morning' | 'noon' | 'afternoon' | 'evening'
  label: string
  entries: TimelineEntry[]
}

export function ensureArray<T = any>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[]
  if (value && typeof value === 'object') return Object.values(value as Record<string, T>)
  return []
}

export function getDayIndex(day: any, fallbackIndex: number): number {
  if (!day || typeof day !== 'object') return fallbackIndex
  if (typeof day.day_index === 'number' && Number.isFinite(day.day_index)) return day.day_index
  if (typeof day.dayIndex === 'number' && Number.isFinite(day.dayIndex)) return day.dayIndex
  if (typeof day.day === 'number' && Number.isFinite(day.day)) return Math.max(0, day.day - 1)
  return fallbackIndex
}

export function normalizeLocation(raw: any): { latitude: number; longitude: number } | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const latitude = Number(raw.latitude ?? raw.lat)
  const longitude = Number(raw.longitude ?? raw.lng)
  if (Number.isFinite(latitude) && Number.isFinite(longitude)) return { latitude, longitude }
  return undefined
}

export function normalizeMeals(meals: unknown) {
  return ensureArray<any>(meals)
    .map((meal) => {
      const lat = Number(meal?.latitude ?? meal?.lat ?? meal?.location?.latitude)
      const lng = Number(meal?.longitude ?? meal?.lng ?? meal?.location?.longitude)
      return {
        ...meal,
        name: meal?.name || meal?.title || meal?.display_name || '',
        location: normalizeLocation(meal?.location ?? meal) || (Number.isFinite(lat) && Number.isFinite(lng) ? { latitude: lat, longitude: lng } : undefined),
      }
    })
    .filter((meal) => meal.name)
}

export function normalizeAttractions(attractions: unknown) {
  return ensureArray<any>(attractions)
    .map((attraction) => {
      const lat = Number(attraction?.lat ?? attraction?.latitude ?? attraction?.location?.latitude)
      const lng = Number(attraction?.lng ?? attraction?.longitude ?? attraction?.location?.longitude)
      return {
        ...attraction,
        name: attraction?.name || attraction?.title || attraction?.display_name || attraction?.place_name || '',
        address: attraction?.address || attraction?.formatted_address || '',
        description: attraction?.description || attraction?.editorial_summary || attraction?.route_desc || '',
        location: normalizeLocation(attraction?.location ?? attraction) || (Number.isFinite(lat) && Number.isFinite(lng) ? { latitude: lat, longitude: lng } : undefined),
        ticket_price: attraction?.ticket_price ?? 0,
        image_url: attraction?.image_url || attraction?.photo_url || attraction?.thumbnail || attraction?.image,
        photo_url: attraction?.photo_url || attraction?.image_url,
        thumbnail: attraction?.thumbnail,
        image: attraction?.image,
      }
    })
    .filter((attraction) => attraction?.name)
}

export function normalizeActivities(activities: unknown) {
  return ensureArray<any>(activities)
    .map((activity) => {
      const lat = Number(activity?.latitude ?? activity?.lat ?? activity?.location?.latitude)
      const lng = Number(activity?.longitude ?? activity?.lng ?? activity?.location?.longitude)
      return {
        ...activity,
        name: activity?.name || activity?.title || activity?.display_name || activity?.place_name || '',
        time: activity?.time || activity?.time_slot || '',
        description: activity?.description || activity?.route_desc || '',
        route_desc: activity?.route_desc || '',
        ticket_price: activity?.ticket_price ?? activity?.estimated_cost ?? 0,
        address: activity?.address || '',
        latitude: Number.isFinite(lat) ? lat : undefined,
        longitude: Number.isFinite(lng) ? lng : undefined,
      }
    })
    .filter((activity) => activity.name)
}

export function normalizeTripPlanFromSession(raw: unknown): TripPlan | null {
  if (!raw || typeof raw !== 'object') return null
  const root = raw as Record<string, any>
  const data = root.data && typeof root.data === 'object' ? root.data : root
  const daysSource = ensureArray<any>(data.itinerary || data.days)
  if (!daysSource.length) return null

  const days = daysSource.map((day: any, index: number) => {
    const dayIndex = typeof day?.day === 'number' ? Math.max(0, day.day - 1) : index
    const activities = normalizeActivities(day?.activities)
    const meals = normalizeMeals(day?.meals)
    const attractions = activities.length
      ? activities.map((activity: any) => ({
          name: activity.name,
          address: activity.address || '',
          location: activity.latitude !== undefined && activity.longitude !== undefined ? { latitude: activity.latitude, longitude: activity.longitude } : undefined,
          visit_duration: 0,
          description: activity.description || activity.route_desc || '',
          rating: undefined,
          ticket_price: activity.ticket_price ?? activity.estimated_cost ?? 0,
        }))
      : normalizeAttractions(data.attractions).map((attraction: any) => ({
          ...attraction,
          location: attraction.location,
          description: attraction.description || attraction.route_desc || attraction.editorial_summary || '',
          visit_duration: 0,
          ticket_price: attraction.ticket_price ?? 0,
        }))

    return {
      day_index: dayIndex,
      date: `第${dayIndex + 1}天`,
      display_title: day?.title || `第${dayIndex + 1}天`,
      arrangement_reason: String(day?.route_summary || '').trim() || '',
      description: String(day?.route_summary || '').trim() || '',
      transportation: '公共交通',
      accommodation: '',
      activities,
      attractions,
      meals,
    }
  })

  const plan: TripPlan = {
    city: String(data.location || ''),
    start_date: '',
    end_date: `${days.length}天行程`,
    budget_currency: data.total_budget?.currency || 'EUR',
    days,
    weather_info: [],
    overall_suggestions: Array.isArray(data.tips) ? data.tips.join('；') : '',
    budget: data.total_budget ? {
      total_attractions: data.total_budget.tickets || 0,
      total_hotels: 0,
      total_meals: data.total_budget.food || 0,
      total_transportation: data.total_budget.transport || 0,
      total: data.total_budget.total || 0,
    } : undefined,
  }

  return plan
}

export function getFirstSentence(text: string): string {
  const normalized = String(text || '').trim()
  if (!normalized) return ''
  const parts = normalized.split(/[。！？.!?]/).map((part) => part.trim()).filter(Boolean)
  return parts[0] || normalized
}

export function simplifyTheme(rawTitle: string): string {
  const normalized = String(rawTitle || '').replace(/第\d+天[｜|·:\-]?\s*/g, '').trim()
  if (!normalized) return '区域串联'
  return normalized.split(/[（(]/)[0].trim() || '区域串联'
}

export function summarizeReason(routeSummary: string): string {
  const firstSentence = getFirstSentence(routeSummary)
  if (!firstSentence) return '区域串联与步行优化'
  return firstSentence.length > 22 ? `${firstSentence.slice(0, 22)}...` : firstSentence
}

export function buildDisplayTitle(dayIndex: number, title: string, routeSummary: string): string {
  const theme = simplifyTheme(title)
  const reason = summarizeReason(routeSummary)
  return `第${dayIndex + 1}天｜${theme}（${reason}）`
}

export function normalizeArrangementReason(title: string, routeSummary: string): string {
  const summary = String(routeSummary || '').trim()
  if (summary) return summary
  const theme = simplifyTheme(title)
  return `本日围绕${theme}安排，优先考虑景点连贯性与步行效率。`
}

function getPlaceKey(dayIndex: number, name: string, kind: 'attraction' | 'meal', mealType?: string): string {
  return `${dayIndex}-${kind}-${mealType || ''}-${name}`
}

function getMealCardId(dayIndex: number, mealType: string): string {
  return `day-${dayIndex}-meal-${mealType}`
}

function getAttractionCardId(dayIndex: number, index: number): string {
  return `day-${dayIndex}-attraction-${index}`
}

export function getTimelineSlots(day: any): TimelineSlot[] {
  const attractions = ensureArray<any>(day?.attractions)
  const meals = ensureArray<any>(day?.meals)
  const activities = ensureArray<any>(day?.activities)
  const sourceHasUsableEntries = activities.length > 0 || attractions.length > 0 || meals.length > 0
  const activitySource = [
    ...activities,
    ...attractions.map((attraction: any) => ({
      name: attraction?.name,
      time: attraction?.time || attraction?.time_slot || attraction?.visit_time || '',
      description: attraction?.description || attraction?.editorial_summary || attraction?.route_desc || '',
      route_desc: attraction?.route_desc || attraction?.description || attraction?.editorial_summary || '',
      ticket_price: attraction?.ticket_price ?? 0,
      address: attraction?.address || attraction?.formatted_address || '',
      latitude: attraction?.location?.latitude ?? attraction?.lat,
      longitude: attraction?.location?.longitude ?? attraction?.lng,
      preference_matched: attraction?.preferenceMatched,
      preference_reason: attraction?.preferenceReason,
    })),
  ].filter((item, index, self) => item?.name && self.findIndex((candidate) => candidate?.name === item.name) === index)

  const slots: TimelineSlot[] = [
    { key: 'morning', label: '上午', entries: [] },
    { key: 'noon', label: '中午', entries: [] },
    { key: 'afternoon', label: '下午', entries: [] },
    { key: 'evening', label: '晚上', entries: [] },
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

  if (!sourceHasUsableEntries) {
    const fallbackDayIndex = 0
    const fallbackTitle = day?.display_title || day?.title || `第${fallbackDayIndex + 1}天`
    slots[1].entries.push({
      key: getPlaceKey(fallbackDayIndex, fallbackTitle, 'attraction'),
      kind: 'attraction',
      title: fallbackTitle,
      time: '',
      address: day?.description || '',
      description: day?.arrangement_reason || day?.description || '每日行程待补充',
      route_desc: day?.arrangement_reason || day?.description || '',
      ticket_price: 0,
      preference_matched: false,
      preference_reason: '',
      latitude: undefined,
      longitude: undefined,
      cardId: getAttractionCardId(fallbackDayIndex, 0),
    })
  }

  activitySource
    .filter((activity: any) => String(activity?.name || '').trim())
    .map((activity: any, idx: number) => ({ activity, idx, hour: parseStartHour(String(activity?.time || '')) }))
    .sort((a, b) => a.hour - b.hour || a.idx - b.idx)
    .forEach(({ activity }) => {
      const slotIndex = getSlotIndexByHour(parseStartHour(String(activity?.time || '')))
      const attraction = attractions.find((a: any) => a.name === activity.name)
      const attractionCardIndex = attractionIndexMap.get(String(activity.name || '')) ?? 0
      slots[slotIndex].entries.push({
        key: getPlaceKey(0, activity.name, 'attraction'),
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
        cardId: getAttractionCardId(0, attractionCardIndex),
      })
    })

  meals.forEach((meal: any) => {
    const slotIndex = getMealSlotIndex(String(meal?.type || ''), String(meal?.time || ''))
    slots[slotIndex].entries.push({
      key: getPlaceKey(0, meal.name, 'meal', meal.type),
      kind: 'meal',
      mealType: meal.type,
      title: `${getMealLabel(meal.type)} · ${meal.name}`,
      time: meal.time || '',
      address: meal.address,
      description: meal.description,
      route_desc: meal.route_desc,
      latitude: meal.location?.latitude,
      longitude: meal.location?.longitude,
      cardId: getMealCardId(0, meal.type),
    })
  })

  return slots
}

function getMealLabel(type: string): string {
  return type === 'breakfast' ? '早餐' : type === 'lunch' ? '午餐' : type === 'dinner' ? '晚餐' : '餐饮'
}
