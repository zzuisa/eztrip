import axios from 'axios'
import type { TripFormData, TripPlanResponse, TripPlan, Attraction, DayPlan, TravelPlanResponseV2, TravelPlanDataV2, TravelPlanAttractionV2, TravelPlanDayV2, TravelPlanActivity, TravelPlanMeal } from '@/types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8881'

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000, // 2分钟超时
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
apiClient.interceptors.request.use(
  (config) => {
    console.log('发送请求:', config.method?.toUpperCase(), config.url)
    return config
  },
  (error) => {
    console.error('请求错误:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器
apiClient.interceptors.response.use(
  (response) => {
    console.log('收到响应:', response.status, response.config.url)
    return response
  },
  (error) => {
    console.error('响应错误:', error.response?.status, error.message)
    return Promise.reject(error)
  }
)

/**
 * 生成旅行计划
 */
export async function generateTripPlan(formData: TripFormData): Promise<TripPlanResponse> {
  try {
    const response = await apiClient.post<TripPlanResponse>('/api/travel-plan', {
      location: formData.city,
      days: formData.travel_days,
      preferences: [...(formData.preferences || []), formData.free_text_input].filter(Boolean).join('；'),
    })
    return response.data
  } catch (error: any) {
    console.error('生成旅行计划失败:', error)
    throw new Error(error.response?.data?.detail || error.message || '生成旅行计划失败')
  }
}

/**
 * 健康检查
 */
export async function healthCheck(): Promise<any> {
  try {
    const response = await apiClient.get('/health')
    return response.data
  } catch (error: any) {
    console.error('健康检查失败:', error)
    throw new Error(error.message || '健康检查失败')
  }
}

interface TravelPlanAttractionApi {
  name: string
  lat: number
  lng: number
  route_desc: string
  formatted_address?: string
  rating?: number
  editorial_summary?: string
  place_id?: string
  ticket_price?: number
}

interface TravelPlanActivityApi {
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

interface TravelPlanMealApi {
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

interface TravelPlanDayApi {
  day: number
  title: string
  route_summary: string
  activities: TravelPlanActivityApi[]
  meals: TravelPlanMealApi[]
}

interface TravelPlanApiData {
  location: string
  days: number
  attractions: TravelPlanAttractionApi[]
  itinerary: TravelPlanDayApi[]
  total_budget: {
    transport: number
    tickets: number
    food: number
    total: number
    currency: string
  }
  tips: string[]
  warnings?: string[]
}

interface TravelPlanApiResponse {
  success: boolean
  message: string
  data: TravelPlanApiData
}

function normalizeActivityText(activity: unknown): string {
  if (typeof activity === 'string') return activity
  if (activity === null || activity === undefined) return ''
  if (typeof activity === 'object') {
    if (Array.isArray(activity)) return activity.map(normalizeActivityText).filter(Boolean).join(' ')
    const obj = activity as Record<string, unknown>
    // 优先提取常见文本字段，避免出现 [object Object]
    const candidates = [obj.name, obj.title, obj.description, obj.text]
    const textHit = candidates.find((v) => typeof v === 'string' && v.trim())
    if (typeof textHit === 'string') return textHit
    try {
      return JSON.stringify(activity)
    } catch {
      return String(activity)
    }
  }
  return String(activity)
}

/**
 * Google Places 结构化旅行规划（适配现有 Result UI 数据结构）
 */
export async function generateTravelPlanByLocation(payload: {
  location: string
  days: number
  preferences?: string
  start_date?: string
  end_date?: string
  transportation?: string
  accommodation?: string
}): Promise<TripPlanResponse> {
  try {
    const response = await apiClient.post<TravelPlanApiResponse>('/api/travel-plan', payload, {
      timeout: 300000,
    })
    const resp = response.data

    const attractions: Attraction[] = (resp.data.attractions || []).map((a) => ({
      name: a.name,
      address: a.formatted_address || '',
      location: { longitude: a.lng, latitude: a.lat },
      visit_duration: 120,
      description: a.route_desc || a.editorial_summary || '推荐景点',
      rating: a.rating,
      ticket_price: a.ticket_price ?? 0,
      image_url: undefined,
    }))

    const days: DayPlan[] = (resp.data.itinerary || []).map((d, idx) => {
      const matched: Attraction[] = []
      const activityTexts = (d.activities || []).map(normalizeActivityText).filter(Boolean)
      activityTexts.forEach((act) => {
        const hit = attractions.find((a) => act.includes(a.name))
        if (hit && !matched.some((m) => m.name === hit.name)) matched.push(hit)
      })
      const dayAttrs = matched.length ? matched : attractions.slice(idx * 3, idx * 3 + 3)
      const meals = (d.meals || []).map((meal) => ({
        type: meal.type,
        name: meal.name,
        address: meal.address,
        location: meal.latitude !== undefined && meal.longitude !== undefined ? { latitude: meal.latitude, longitude: meal.longitude } : undefined,
        description: meal.description,
        estimated_cost: meal.estimated_cost,
      }))
      return {
        date: `第${d.day}天`,
        day_index: idx,
        description: `${d.title}（${d.route_summary}）`,
        transportation: payload.transportation || '公共交通',
        accommodation: payload.accommodation || '市中心酒店',
        attractions: dayAttrs,
        meals,
      }
    })

    const mappedPlan: TripPlan = {
      city: resp.data.location,
      start_date: payload.start_date || '待定',
      end_date: payload.end_date || `${resp.data.days}天行程`,
      days,
      weather_info: [],
      overall_suggestions: (resp.data.tips || []).join('；'),
      budget: {
        total_attractions: resp.data.total_budget.tickets,
        total_hotels: 0,
        total_meals: resp.data.total_budget.food,
        total_transportation: resp.data.total_budget.transport,
        total: resp.data.total_budget.total,
      },
    }

    return {
      success: resp.success,
      message: resp.message,
      data: mappedPlan,
    }
  } catch (error: any) {
    console.error('Google Places旅行规划失败:', error)
    throw new Error(error.response?.data?.detail || error.message || 'Google Places旅行规划失败')
  }
}

export async function streamTravelPlanByLocation(
  payload: {
    location: string
    days: number
    preferences?: string
    start_date?: string
    end_date?: string
    transportation?: string
    accommodation?: string
  },
  handlers: {
    onProgress?: (percent: number, status: string) => void
    onLog?: (message: string) => void
    onDebug?: (stage: string, content: string) => void
    onDone?: (response: TripPlanResponse) => void
    onError?: (message: string) => void
  },
) {
  const response = await fetch(`${API_BASE_URL}/api/travel-plan/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!response.ok || !response.body) {
    throw new Error(`流式请求失败: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let eventName = 'message'

  const flush = (chunk: string) => {
    const lines = chunk.split('\n')
    for (const line of lines) {
      if (line.startsWith('event:')) {
        eventName = line.replace(/^event:\s*/, '').trim()
      } else if (line.startsWith('data:')) {
        const dataText = line.replace(/^data:\s*/, '').trim()
        try {
          const data = JSON.parse(dataText)
          if (eventName === 'progress') handlers.onProgress?.(data.percent ?? 0, data.status ?? '')
          else if (eventName === 'log') handlers.onLog?.(data.message ?? '')
          else if (eventName === 'llm_debug') handlers.onDebug?.(data.stage ?? 'debug', data.raw ? String(data.raw) : data.prompt ? String(data.prompt) : JSON.stringify(data))
          else if (eventName === 'done') handlers.onDone?.(data as TripPlanResponse)
          else if (eventName === 'error') handlers.onError?.(data.message ?? '生成失败')
        } catch (e) {
          console.error('解析 SSE 失败:', e)
        }
      }
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() || ''
    parts.forEach(flush)
  }
}

export default apiClient

