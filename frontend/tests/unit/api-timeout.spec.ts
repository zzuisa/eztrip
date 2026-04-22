import { beforeEach, describe, expect, it, vi } from 'vitest'

const postMock = vi.fn()
const getMock = vi.fn()
const deleteMock = vi.fn()

vi.mock('axios', () => {
  const create = vi.fn(() => ({
    post: postMock,
    get: getMock,
    delete: deleteMock,
    interceptors: {
      request: { use: vi.fn() },
      response: { use: vi.fn() },
    },
  }))
  return {
    default: { create },
  }
})

describe('api long trip timeout strategy', () => {
  beforeEach(() => {
    postMock.mockReset()
    getMock.mockReset()
    deleteMock.mockReset()
  })

  it('3 天游程使用默认超时并可成功返回', async () => {
    postMock.mockResolvedValueOnce({
      data: {
        success: true,
        message: 'ok',
        data: {
          location: 'Paris',
          days: 3,
          attractions: [],
          itinerary: [],
          total_budget: { transport: 10, tickets: 20, food: 30, total: 60, currency: 'EUR' },
          tips: [],
        },
      },
    })
    const { generateTravelPlanByLocation } = await import('@/services/api')
    const result = await generateTravelPlanByLocation({ location: 'Paris', days: 3 })

    expect(result.success).toBe(true)
    expect(postMock).toHaveBeenCalledWith(
      '/api/travel-plan',
      expect.objectContaining({ location: 'Paris', days: 3 }),
      expect.objectContaining({ timeout: 120000 }),
    )
  })

  it('4 天游程使用长超时并触发进度提示', async () => {
    postMock.mockResolvedValueOnce({
      data: {
        success: true,
        message: 'ok',
        data: {
          location: 'Paris',
          days: 4,
          attractions: [],
          itinerary: [],
          total_budget: { transport: 10, tickets: 20, food: 30, total: 60, currency: 'EUR' },
          tips: [],
        },
      },
    })
    const onProgress = vi.fn()
    const onLog = vi.fn()
    const { generateTravelPlanByLocation } = await import('@/services/api')
    await generateTravelPlanByLocation({ location: 'Paris', days: 4 }, { onProgress, onLog })

    expect(onProgress).toHaveBeenCalledWith(5, '长行程生成中，预计耗时较长...')
    expect(onLog).toHaveBeenCalledWith('已启用长行程超时与稳定性策略')
    expect(postMock).toHaveBeenCalledWith(
      '/api/travel-plan',
      expect.objectContaining({ location: 'Paris', days: 4 }),
      expect.objectContaining({ timeout: 420000 }),
    )
  })

  it('长行程超时失败时返回清晰兜底文案', async () => {
    postMock.mockRejectedValueOnce({
      code: 'ECONNABORTED',
      message: 'timeout of 420000ms exceeded',
      response: undefined,
    })
    const { generateTravelPlanByLocation } = await import('@/services/api')

    await expect(
      generateTravelPlanByLocation({ location: 'Paris', days: 5 }),
    ).rejects.toThrow('行程较长，生成耗时较久，请稍后重试或切换为流式生成。')
  })
})
