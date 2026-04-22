import type { TripFormData, TripPlanResponse } from '@/types'
import type { OptimizedItinerary, TripRequest } from '@/types/itinerary'
import { generateTravelPlanByLocation, streamTravelPlanByLocation } from '@/services/api'
import { normalizeItinerary } from '@/services/itinerary-normalizer'

export interface OptimizeHandlers {
  onProgress?: (percent: number, status: string) => void
  onLog?: (message: string) => void
  onStage?: (stage: string) => void
  onStep?: (step: { name: string; status: string; description: string }) => void
}

function toTripFormData(request: TripRequest): TripFormData {
  return {
    city: request.destination,
    start_date: request.startDate || '',
    end_date: request.endDate || '',
    travel_days: request.travelDays,
    transportation: request.transportation || '',
    accommodation: request.accommodation || '',
    preferences: request.preferences || [],
    free_text_input: '',
  }
}

function mapLegacyResponseToItinerary(resp: TripPlanResponse, source?: string): OptimizedItinerary {
  const normalized = normalizeItinerary(resp, { source })
  if (!normalized) {
    return {
      id: `trip_${Date.now()}`,
      city: '',
      days: [],
      warnings: ['行程规范化失败：返回结构不受支持'],
      source,
      updatedAtIso: new Date().toISOString(),
    }
  }
  return normalized
}

/**
 * 优化行程（当前以“后端生成 + 前端适配/规范化”为主）。
 * 后续可在此扩展：预算/偏好/天气/饮食约束的前端规则与校验。
 */
export async function optimizeItinerary(
  request: TripRequest,
  handlers: OptimizeHandlers = {},
  options: { mode?: 'stream' | 'batch'; signal?: AbortSignal } = {},
): Promise<OptimizedItinerary> {
  const mode = options.mode || 'stream'
  const payload = {
    location: request.destination,
    days: request.travelDays,
    preferences: (request.preferences || []).join('；'),
    start_date: request.startDate,
    end_date: request.endDate,
    transportation: request.transportation,
    accommodation: request.accommodation,
  }

  if (mode === 'batch') {
    const resp = await generateTravelPlanByLocation(payload as any, {
      onProgress: handlers.onProgress,
      onLog: handlers.onLog,
      onDebug: () => undefined,
    })
    return mapLegacyResponseToItinerary(resp, 'api:batch')
  }

  return await new Promise<OptimizedItinerary>((resolve, reject) => {
    streamTravelPlanByLocation(
      payload as any,
      {
        onProgress: handlers.onProgress,
        onLog: handlers.onLog,
        onStep: handlers.onStep,
        onStage: handlers.onStage,
        onDone: (resp) => resolve(mapLegacyResponseToItinerary(resp, 'api:stream')),
        onError: (message) => reject(new Error(message)),
      },
      { signal: options.signal },
    ).catch(reject)
  })
}

/**
 * 兼容：将 `TripRequest` 映射到旧表单结构（若部分 UI 仍基于 TripFormData）。
 */
export function toLegacyTripFormData(request: TripRequest): TripFormData {
  return toTripFormData(request)
}

