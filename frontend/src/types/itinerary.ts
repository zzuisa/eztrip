export type CurrencyCode = 'EUR' | 'USD' | 'GBP' | 'JPY' | 'CNY' | (string & {})

export type PlaceKind = 'attraction' | 'meal' | 'snack' | 'other'

export type MealType = 'breakfast' | 'lunch' | 'dinner' | 'snack'

export interface LatLng {
  latitude: number
  longitude: number
}

export interface BudgetRange {
  min?: number
  max?: number
  currency?: CurrencyCode
}

export interface TripRequest {
  destination: string
  travelDays: number
  budget?: BudgetRange
  preferences?: string[]
  weatherPreference?: string
  dietaryRestrictions?: string[]
  startDate?: string
  endDate?: string
  transportation?: string
  accommodation?: string
}

export interface PlaceItem {
  id: string
  kind: PlaceKind
  name: string
  address?: string
  location?: LatLng
  description?: string
  ticketPrice?: number
  estimatedCost?: number
  visitDurationMinutes?: number
  routeDescription?: string
  timeSlot?: string
  tags?: string[]
  imageUrl?: string
  rating?: number
  preferenceMatched?: boolean
  preferenceReason?: string
}

export interface TripDay {
  dayIndex: number
  date?: string
  title?: string
  description?: string
  transportation?: string
  accommodation?: string
  attractions: PlaceItem[]
  meals: PlaceItem[]
  dayCostEstimate?: number
  arrangementReason?: string
}

export interface BudgetSummary {
  attractions: number
  hotels: number
  meals: number
  transport: number
  total: number
  currency: CurrencyCode
}

export interface OptimizedItinerary {
  id: string
  city: string
  startDate?: string
  endDate?: string
  days: TripDay[]
  budgetSummary?: BudgetSummary
  suggestions?: string[]
  warnings?: string[]
  source?: string
  updatedAtIso?: string
}

export interface NavigationItem {
  name: string
  address?: string
  location?: LatLng
  kind?: PlaceKind
}

export type TravelMode = 'walking' | 'driving' | 'transit' | 'bicycling'

export interface NavigationLink {
  travelMode: TravelMode
  destination?: string
  waypoints?: string[]
  items: NavigationItem[]
  sourceContext?: string
}

export interface ResultViewState {
  activeSection: string
  activeDays: number[]
  selectedPlaceKey?: string
  editMode: boolean
  deepLinkVisible: boolean
  exportStatus?: 'idle' | 'preparing' | 'done' | 'error'
}

