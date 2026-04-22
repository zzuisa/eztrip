import type { BudgetSummary, CurrencyCode, LatLng, OptimizedItinerary, PlaceItem, TripDay } from '@/types/itinerary'

export function safeNumber(value: unknown, fallback = 0): number {
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : fallback
}

export function normalizeLatLng(raw: unknown): LatLng | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const obj = raw as Record<string, unknown>
  const latitude = safeNumber(obj.latitude ?? obj.lat, Number.NaN)
  const longitude = safeNumber(obj.longitude ?? obj.lng, Number.NaN)
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return undefined
  return { latitude, longitude }
}

export function buildPlaceId(dayIndex: number, kind: string, name: string, suffix?: string): string {
  const normalizedName = String(name || '').trim()
  const normalizedSuffix = suffix ? String(suffix).trim() : ''
  return [dayIndex, kind, normalizedSuffix, normalizedName].filter(Boolean).join(':')
}

export function dedupePlaces(items: PlaceItem[]): PlaceItem[] {
  const seen = new Set<string>()
  const out: PlaceItem[] = []
  for (const item of items) {
    const key = item.id || `${item.kind}:${item.name}`
    if (seen.has(key)) continue
    seen.add(key)
    out.push(item)
  }
  return out
}

export function computeBudgetSummary(params: {
  days: TripDay[]
  currency?: CurrencyCode
  explicit?: Partial<BudgetSummary> | null
}): BudgetSummary | undefined {
  const currency: CurrencyCode = (params.currency || params.explicit?.currency || 'EUR') as CurrencyCode
  const explicit = params.explicit || undefined
  if (explicit && typeof explicit.total === 'number') {
    return {
      attractions: safeNumber(explicit.attractions),
      hotels: safeNumber(explicit.hotels),
      meals: safeNumber(explicit.meals),
      transport: safeNumber(explicit.transport),
      total: safeNumber(explicit.total),
      currency,
    }
  }

  const totalMeals = params.days.reduce((sum, d) => sum + d.meals.reduce((s2, m) => s2 + safeNumber(m.estimatedCost), 0), 0)
  const totalAttractions = params.days.reduce(
    (sum, d) => sum + d.attractions.reduce((s2, a) => s2 + safeNumber(a.ticketPrice ?? a.estimatedCost), 0),
    0,
  )
  const total = totalMeals + totalAttractions
  if (total === 0) return undefined

  return {
    attractions: totalAttractions,
    hotels: 0,
    meals: totalMeals,
    transport: 0,
    total,
    currency,
  }
}

export function ensureItineraryId(itinerary: OptimizedItinerary): OptimizedItinerary {
  if (itinerary.id) return itinerary
  const seed = `${itinerary.city || 'trip'}:${itinerary.startDate || ''}:${itinerary.endDate || ''}:${itinerary.days.length}`
  const compact = seed.replace(/\s+/g, '').slice(0, 64)
  return { ...itinerary, id: `trip_${compact || Date.now()}` }
}

