import type { Attraction, DayPlan, Meal, TripPlan } from '@/types'
import type { BudgetSummary, OptimizedItinerary, PlaceItem, TripDay } from '@/types/itinerary'
import { buildPlaceId, computeBudgetSummary, dedupePlaces, ensureItineraryId, normalizeLatLng, safeNumber } from '@/utils/itinerary-helpers'

function ensureArray<T = any>(value: unknown): T[] {
  if (Array.isArray(value)) return value as T[]
  if (value && typeof value === 'object') return Object.values(value as Record<string, T>)
  return []
}

function normalizeText(value: unknown): string | undefined {
  const s = typeof value === 'string' ? value : value === null || value === undefined ? '' : String(value)
  const trimmed = s.trim()
  return trimmed ? trimmed : undefined
}

function toPlaceItem(params: {
  dayIndex: number
  kind: PlaceItem['kind']
  name: unknown
  address?: unknown
  location?: unknown
  description?: unknown
  ticketPrice?: unknown
  estimatedCost?: unknown
  visitDurationMinutes?: unknown
  routeDescription?: unknown
  timeSlot?: unknown
  imageUrl?: unknown
  rating?: unknown
  preferenceMatched?: unknown
  preferenceReason?: unknown
  idSuffix?: string
}): PlaceItem | null {
  const name = normalizeText(params.name)
  if (!name) return null
  const dayIndex = params.dayIndex
  const kind = params.kind
  const id = buildPlaceId(dayIndex, kind, name, params.idSuffix)
  return {
    id,
    kind,
    name,
    address: normalizeText(params.address),
    location: normalizeLatLng(params.location),
    description: normalizeText(params.description),
    ticketPrice: params.ticketPrice === undefined ? undefined : safeNumber(params.ticketPrice, 0),
    estimatedCost: params.estimatedCost === undefined ? undefined : safeNumber(params.estimatedCost, 0),
    visitDurationMinutes: params.visitDurationMinutes === undefined ? undefined : safeNumber(params.visitDurationMinutes, 0),
    routeDescription: normalizeText(params.routeDescription),
    timeSlot: normalizeText(params.timeSlot),
    imageUrl: normalizeText(params.imageUrl),
    rating: params.rating === undefined ? undefined : safeNumber(params.rating, 0),
    preferenceMatched: typeof params.preferenceMatched === 'boolean' ? params.preferenceMatched : undefined,
    preferenceReason: normalizeText(params.preferenceReason),
  }
}

function normalizeDaysFromTripPlan(plan: TripPlan): TripDay[] {
  const days: TripDay[] = ensureArray<DayPlan>(plan.days).map((day, idx) => {
    const dayIndex = typeof (day as any)?.day_index === 'number' ? (day as any).day_index : idx

    const attractions = dedupePlaces(
      ensureArray<Attraction>((day as any)?.attractions).map((a) => {
        return toPlaceItem({
          dayIndex,
          kind: 'attraction',
          name: (a as any)?.name,
          address: (a as any)?.address || (a as any)?.formatted_address,
          location: (a as any)?.location ?? a,
          description: (a as any)?.description || (a as any)?.editorial_summary || (a as any)?.route_desc,
          ticketPrice: (a as any)?.ticket_price,
          estimatedCost: (a as any)?.estimated_cost,
          visitDurationMinutes: (a as any)?.visit_duration,
          routeDescription: (a as any)?.route_desc,
          imageUrl: (a as any)?.image_url,
          rating: (a as any)?.rating,
        })
      }).filter(Boolean) as PlaceItem[],
    )

    const meals = dedupePlaces(
      ensureArray<Meal>((day as any)?.meals).map((m) => {
        return toPlaceItem({
          dayIndex,
          kind: 'meal',
          name: (m as any)?.name,
          address: (m as any)?.address,
          location: (m as any)?.location ?? m,
          description: (m as any)?.description,
          estimatedCost: (m as any)?.estimated_cost,
          routeDescription: (m as any)?.route_desc,
          timeSlot: (m as any)?.time,
          idSuffix: (m as any)?.type,
        })
      }).filter(Boolean) as PlaceItem[],
    )

    return {
      dayIndex,
      date: normalizeText((day as any)?.date),
      title: normalizeText((day as any)?.display_title || (day as any)?.title),
      description: normalizeText((day as any)?.description),
      transportation: normalizeText((day as any)?.transportation),
      accommodation: normalizeText((day as any)?.accommodation),
      attractions,
      meals,
      arrangementReason: normalizeText((day as any)?.arrangement_reason),
      dayCostEstimate: safeNumber((day as any)?.dayCostEstimate, undefined as any),
    }
  })

  return days.sort((a, b) => a.dayIndex - b.dayIndex)
}

function mapBudgetToSummary(raw: any, currencyFallback?: string): BudgetSummary | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const currency = String(raw.currency || currencyFallback || 'EUR').toUpperCase()
  const total = safeNumber(raw.total, 0)
  const transport = safeNumber(raw.transport ?? raw.total_transportation, 0)
  const attractions = safeNumber(raw.tickets ?? raw.total_attractions, 0)
  const meals = safeNumber(raw.food ?? raw.total_meals, 0)
  const hotels = safeNumber(raw.hotels ?? raw.total_hotels, 0)
  if (total === 0 && transport === 0 && attractions === 0 && meals === 0 && hotels === 0) return undefined
  return { attractions, hotels, meals, transport, total: total || transport + attractions + meals + hotels, currency }
}

/**
 * 将各种来源的行程结构规范化为统一 `OptimizedItinerary`。
 * 支持场景（至少 5 类）：
 * - 现有 `TripPlan`（Result.vue 运行时结构）
 * - `/api/travel-plan` v1/v2 常见字段（city/location, days/itinerary, tips/warnings, budget/total_budget）
 * - `TripPlanResponse` / `TravelPlanResponseV2` 包裹结构（data 字段）
 * - sessionStorage 持久化字符串（调用方可先 JSON.parse）
 * - 弱结构 day/activities/meals/attractions 混合结构（尽量降级展示）
 */
export function normalizeItinerary(raw: unknown, options: { source?: string } = {}): OptimizedItinerary | null {
  if (!raw) return null

  const obj = typeof raw === 'object' ? (raw as Record<string, any>) : null
  if (!obj) return null

  const data = obj.data && typeof obj.data === 'object' ? (obj.data as Record<string, any>) : obj

  const city = normalizeText(data.city || data.location || data.destination) || ''
  const startDate = normalizeText(data.start_date || data.startDate || data.start_date_iso)
  const endDate = normalizeText(data.end_date || data.endDate || data.end_date_iso)

  const tripPlanLike: TripPlan = data as any
  const days = data.days || data.itinerary ? normalizeDaysFromTripPlan({
    ...(tripPlanLike as any),
    days: data.days ?? data.itinerary,
  }) : []

  const suggestions = ensureArray<string>(data.suggestions || data.tips || data.overall_suggestions)
    .flatMap((v) => (typeof v === 'string' ? v.split('；') : []))
    .map((v) => v.trim())
    .filter(Boolean)

  const warnings = ensureArray<string>(data.warnings).map((v) => String(v)).filter(Boolean)

  const budgetSummary =
    mapBudgetToSummary(data.budget, data.budget_currency) ||
    mapBudgetToSummary(data.total_budget, data.budget_currency) ||
    computeBudgetSummary({ days, currency: (data.budget_currency || data?.total_budget?.currency) as any, explicit: null })

  const itinerary: OptimizedItinerary = ensureItineraryId({
    id: '',
    city,
    startDate,
    endDate,
    days,
    budgetSummary,
    suggestions: suggestions.length ? suggestions : undefined,
    warnings: warnings.length ? warnings : undefined,
    source: options.source || normalizeText(data.source) || undefined,
    updatedAtIso: new Date().toISOString(),
  })

  return itinerary
}

