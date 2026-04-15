import apiClient from './api'
import type { DbNlqResponse } from '@/types'

export async function nlqTrips(query: string): Promise<DbNlqResponse> {
  try {
    const response = await apiClient.post<DbNlqResponse>('/api/transport/db/nlq', { query })
    return response.data
  } catch (error: any) {
    throw new Error(error.response?.data?.detail || error.message || '自然语言查询失败')
  }
}

