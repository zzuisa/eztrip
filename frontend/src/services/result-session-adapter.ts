import type { TripPlan } from '@/types'

function ensureArray<T = any>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[]
  if (value && typeof value === 'object') return Object.values(value as Record<string, T>)
  return []
}

function toNumber(value: unknown): number | undefined {
  const n = Number(value)
  return Number.isFinite(n) ? n : undefined
}

function normalizeLocation(raw: any): { latitude: number; longitude: number } | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const latitude = toNumber(raw.latitude ?? raw.lat)
  const longitude = toNumber(raw.longitude ?? raw.lng)
  if (latitude === undefined || longitude === undefined) return undefined
  return { latitude, longitude }
}

function normalizeAttraction(raw: any) {
  const lat = toNumber(raw?.lat ?? raw?.latitude ?? raw?.location?.latitude)
  const lng = toNumber(raw?.lng ?? raw?.longitude ?? raw?.location?.longitude)
  return {
    name: raw?.name || raw?.title || raw?.display_name || raw?.place_name || '',
    address: raw?.address || raw?.formatted_address || '',
    location: normalizeLocation(raw?.location ?? raw) || { latitude: lat ?? 0, longitude: lng ?? 0 },
    visit_duration: raw?.visit_duration ?? raw?.estimated_cost ?? 90,
    description: raw?.description || raw?.editorial_summary || raw?.route_desc || '',
    rating: raw?.rating,
    ticket_price: raw?.ticket_price ?? 0,
    image_url: raw?.image_url,
  }
}

function normalizeActivity(raw: any) {
  const lat = toNumber(raw?.latitude ?? raw?.lat ?? raw?.location?.latitude)
  const lng = toNumber(raw?.longitude ?? raw?.lng ?? raw?.location?.longitude)
  return {
    name: raw?.name || raw?.title || raw?.display_name || raw?.place_name || '',
    time: raw?.time || raw?.time_slot || '',
    description: raw?.description || raw?.editorial_summary || raw?.route_desc || '',
    route_desc: raw?.route_desc || raw?.editorial_summary || '',
    estimated_cost: raw?.estimated_cost ?? raw?.ticket_price ?? 0,
    ticket_price: raw?.ticket_price ?? raw?.estimated_cost ?? 0,
    address: raw?.address || raw?.formatted_address || '',
    latitude: lat,
    longitude: lng,
    preference_matched: raw?.preference_matched,
    preference_reason: raw?.preference_reason,
  }
}

function normalizeMeal(raw: any) {
  const lat = toNumber(raw?.latitude ?? raw?.lat ?? raw?.location?.latitude)
  const lng = toNumber(raw?.longitude ?? raw?.lng ?? raw?.location?.longitude)
  return {
    type: raw?.type || 'snack',
    name: raw?.name || raw?.title || raw?.display_name || '',
    time: raw?.time || raw?.time_slot || '',
    description: raw?.description || raw?.editorial_summary || '',
    route_desc: raw?.route_desc || raw?.editorial_summary || '',
    estimated_cost: raw?.estimated_cost ?? raw?.ticket_price ?? 0,
    address: raw?.address || raw?.formatted_address || '',
    latitude: lat,
    longitude: lng,
  }
}

export function adaptTripPlanFromSession(raw: unknown): TripPlan | null {
  if (!raw || typeof raw !== 'object') return null
  const root = raw as Record<string, any>
  const plan = root.data && typeof root.data === 'object' ? (root.data as Record<string, any>) : root
  const daysSource = ensureArray<any>(plan.days || plan.itinerary || root.days || root.itinerary)
  const days: TripPlan['days'] = daysSource.map((day, index) => {
    const dayIndex = typeof day?.day_index === 'number' ? day.day_index : typeof day?.day === 'number' ? day.day - 1 : index
    const title = day?.display_title || day?.title || `第${dayIndex + 1}天`
    const routeSummary = day?.arrangement_reason || day?.route_summary || day?.description || ''
    const attractionsSource = ensureArray<any>(day?.attractions)
    const activitiesSource = ensureArray<any>(day?.activities)
    const mealsSource = ensureArray<any>(day?.meals)

    const attractions = (attractionsSource.length ? attractionsSource : activitiesSource).map(normalizeAttraction).filter((item) => item.name)
    const activities = activitiesSource.map(normalizeActivity).filter((item) => item.name)
    const meals = mealsSource.map(normalizeMeal).filter((item) => item.name)

    return {
      day_index: dayIndex,
      date: day?.date || `第${dayIndex + 1}天`,
      display_title: title,
      arrangement_reason: routeSummary,
      description: day?.description || routeSummary || '',
      transportation: day?.transportation || '公共交通',
      accommodation: day?.accommodation || '',
      activities,
      attractions,
      meals,
    }
  })

  return {
    city: plan.city || plan.location || root.city || root.location || '',
    start_date: plan.start_date || root.start_date || '',
    end_date: plan.end_date || root.end_date || '',
    budget_currency: plan.budget_currency || plan.total_budget?.currency || root.budget_currency,
    days,
    weather_info: ensureArray(plan.weather_info || root.weather_info),
    overall_suggestions: Array.isArray(plan.tips || root.tips) ? (plan.tips || root.tips).join('；') : String(plan.overall_suggestions || root.overall_suggestions || ''),
    budget: plan.budget || root.budget || (plan.total_budget || root.total_budget ? {
      total_attractions: (plan.total_budget || root.total_budget)?.tickets || 0,
      total_hotels: (plan.total_budget || root.total_budget)?.hotels || 0,
      total_meals: (plan.total_budget || root.total_budget)?.food || 0,
      total_transportation: (plan.total_budget || root.total_budget)?.transport || 0,
      total: (plan.total_budget || root.total_budget)?.total || 0,
    } : undefined),
  }
}

export function isSessionTripPlanUsable(plan: TripPlan | null): boolean {
  if (!plan) return false
  if (!Array.isArray(plan.days) || plan.days.length === 0) return false
  return plan.days.some((day) => (day.attractions?.length || 0) > 0 || (day.activities?.length || 0) > 0 || (day.meals?.length || 0) > 0)
}
