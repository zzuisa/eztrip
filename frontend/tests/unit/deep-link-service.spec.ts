import { describe, expect, it } from 'vitest'
import { buildDayDeepLinkItems, buildGoogleMapsDeepLinkUrl } from '@/services/deep-link-service'

describe('deep-link-service', () => {
  const getMealLabel = (type: string) => ({ breakfast: '早餐', lunch: '午餐', dinner: '晚餐', snack: '小吃' }[type] || type)
  const getPlaceKey = (dayIndex: number, name: string, kind: 'attraction' | 'meal', mealType?: string) =>
    `${dayIndex}-${kind}-${mealType || ''}-${name}`

  it('按顺序构建当天深链条目', () => {
    const items = buildDayDeepLinkItems({
      dayIndex: 0,
      getMealLabel,
      getPlaceKey,
      day: {
        attractions: [{ name: '卢浮宫', location: { latitude: 48.86, longitude: 2.33 }, address: 'A' }],
        meals: [{ name: '午餐店', type: 'lunch', location: { latitude: 48.87, longitude: 2.34 }, address: 'B' }],
      },
    })
    expect(items.map((x) => x.name)).toEqual(['卢浮宫', '午餐店'])
  })

  it('缺失坐标项会在 URL 生成时被自动跳过', () => {
    const url = buildGoogleMapsDeepLinkUrl([
      { key: '1', label: 'a', name: 'A', type: 'attraction', latitude: 1, longitude: 2 },
      { key: '2', label: 'b', name: 'B', type: 'meal' },
    ])
    expect(url).toContain('google.com/maps/dir/')
    expect(url).toContain('destination=')
  })

  it('空列表返回 Google Maps 首页', () => {
    expect(buildGoogleMapsDeepLinkUrl([])).toBe('https://www.google.com/maps')
  })
})

