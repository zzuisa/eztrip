// 类型定义

export interface Location {
  longitude: number
  latitude: number
}

export interface Attraction {
  name: string
  address: string
  location: Location
  mapbox_id?: string
  visit_duration: number
  description: string
  category?: string
  rating?: number
  image_url?: string
  ticket_price?: number
}

export interface Meal {
  type: 'breakfast' | 'lunch' | 'dinner' | 'snack'
  name: string
  address?: string
  location?: Location
  description?: string
  estimated_cost?: number
}

export interface TravelPlanActivity {
  name: string
  time: string
  description: string
  route_desc: string
  estimated_cost: number
  ticket_price?: number
  address?: string
  latitude?: number
  longitude?: number
}

export interface TravelPlanMeal {
  type: 'breakfast' | 'lunch' | 'dinner' | 'snack'
  name: string
  time: string
  description: string
  route_desc: string
  estimated_cost: number
  address?: string
  latitude?: number
  longitude?: number
}

export interface TravelPlanDayV2 {
  day: number
  title: string
  route_summary: string
  activities: TravelPlanActivity[]
  meals: TravelPlanMeal[]
}

export interface TravelPlanBudgetV2 {
  transport: number
  tickets: number
  food: number
  total: number
  currency: string
}

export interface TravelPlanAttractionV2 {
  name: string
  lat: number
  lng: number
  route_desc: string
  formatted_address: string
  rating?: number
  editorial_summary?: string
  place_id?: string
  ticket_price?: number
}

export interface TravelPlanDataV2 {
  location: string
  days: number
  attractions: TravelPlanAttractionV2[]
  itinerary: TravelPlanDayV2[]
  total_budget: TravelPlanBudgetV2
  tips: string[]
  warnings?: string[]
}

export interface TravelPlanResponseV2 {
  success: boolean
  message: string
  data: TravelPlanDataV2
}

export interface Hotel {
  name: string
  address: string
  location?: Location
  price_range: string
  rating: string
  distance: string
  type: string
  estimated_cost?: number
}

export interface Budget {
  total_attractions: number
  total_hotels: number
  total_meals: number
  total_transportation: number
  total: number
}

export interface DayPlan {
  date: string
  day_index: number
  description: string
  transportation: string
  accommodation: string
  hotel?: Hotel
  attractions: Attraction[]
  meals: Meal[]
}

export interface WeatherInfo {
  date: string
  day_weather: string
  night_weather: string
  day_temp: number
  night_temp: number
  wind_direction: string
  wind_power: string
}

export interface TripPlan {
  city: string
  start_date: string
  end_date: string
  days: DayPlan[]
  weather_info: WeatherInfo[]
  overall_suggestions: string
  budget?: Budget
}

export interface TripFormData {
  city: string
  start_date: string
  end_date: string
  travel_days: number
  transportation: string
  accommodation: string
  preferences: string[]
  free_text_input: string
}

export interface TripPlanResponse {
  success: boolean
  message: string
  data?: TripPlan
}

export * from './db'

