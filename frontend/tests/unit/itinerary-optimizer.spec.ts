import { beforeEach, describe, expect, it, vi } from 'vitest'

const generateTravelPlanByLocation = vi.fn()
const streamTravelPlanByLocation = vi.fn()

vi.mock('@/services/api', () => ({
  generateTravelPlanByLocation,
  streamTravelPlanByLocation,
}))

describe('itinerary-optimizer', () => {
  beforeEach(() => {
    generateTravelPlanByLocation.mockReset()
    streamTravelPlanByLocation.mockReset()
  })

  it('预算超限时会压缩费用并附带警告', async () => {
    generateTravelPlanByLocation.mockResolvedValueOnce({
      success: true,
      message: 'ok',
      data: {
        city: 'Paris',
        start_date: '2026-01-01',
        end_date: '2026-01-02',
        budget_currency: 'EUR',
        budget: { total_attractions: 120, total_hotels: 0, total_meals: 80, total_transportation: 0, total: 200 },
        days: [
          {
            day_index: 0,
            attractions: [{ name: 'A', ticket_price: 120, location: { latitude: 1, longitude: 2 } }],
            meals: [{ type: 'lunch', name: 'M', estimated_cost: 80, location: { latitude: 1, longitude: 2 } }],
          },
        ],
      },
    })
    const { optimizeItinerary } = await import('@/services/itinerary-optimizer')
    const itinerary = await optimizeItinerary(
      { destination: 'Paris', travelDays: 2, budget: { max: 100 } },
      {},
      { mode: 'batch' },
    )

    expect(itinerary.budgetSummary?.total).toBe(100)
    expect(itinerary.warnings?.join('')).toContain('已按预算上限自动压缩费用预估')
  })

  it('天气与饮食限制会补充软约束文案', async () => {
    generateTravelPlanByLocation.mockResolvedValueOnce({
      success: true,
      message: 'ok',
      data: {
        city: 'Paris',
        days: [{ day_index: 0, attractions: [], meals: [] }],
      },
    })
    const { optimizeItinerary } = await import('@/services/itinerary-optimizer')
    const itinerary = await optimizeItinerary(
      {
        destination: 'Paris',
        travelDays: 1,
        weatherPreference: 'indoor-friendly',
        dietaryRestrictions: ['nut-free'],
      },
      {},
      { mode: 'batch' },
    )
    expect(itinerary.suggestions?.join('')).toContain('室内活动')
    expect(itinerary.warnings?.join('')).toContain('饮食限制')
  })

  it('stream 模式会等待 done 回调并返回规范化结果', async () => {
    streamTravelPlanByLocation.mockImplementationOnce(async (_payload: any, handlers: any) => {
      handlers.onDone?.({
        success: true,
        message: 'ok',
        data: {
          city: 'Paris',
          days: [{ day_index: 0, attractions: [], meals: [] }],
        },
      })
    })
    const { optimizeItinerary } = await import('@/services/itinerary-optimizer')
    const itinerary = await optimizeItinerary({ destination: 'Paris', travelDays: 1 }, {}, { mode: 'stream' })
    expect(itinerary.city).toBe('Paris')
    expect(itinerary.days.length).toBe(1)
  })
})

