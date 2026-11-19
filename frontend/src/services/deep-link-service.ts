export type DeepLinkItem = {
  key: string
  label: string
  name: string
  latitude?: number
  longitude?: number
  type: 'attraction' | 'meal'
  address?: string
}

export function buildDayDeepLinkItems(params: {
  day: any
  dayIndex: number
  getMealLabel: (type: string) => string
  getPlaceKey: (dayIndex: number, name: string, kind: 'attraction' | 'meal', mealType?: string) => string
}): DeepLinkItem[] {
  const { day, dayIndex, getMealLabel, getPlaceKey } = params
  if (!day) return []
  const items: DeepLinkItem[] = []
  ;(day.attractions || []).forEach((a: any, index: number) => {
    items.push({
      key: getPlaceKey(dayIndex, a.name, 'attraction'),
      label: `第${dayIndex + 1}天 · 景点${index + 1}`,
      name: a.name,
      latitude: a.location?.latitude,
      longitude: a.location?.longitude,
      type: 'attraction',
      address: a.address,
    })
  })
  ;(day.meals || []).forEach((m: any) => {
    items.push({
      key: getPlaceKey(dayIndex, m.name, 'meal', m.type),
      label: `第${dayIndex + 1}天 · ${getMealLabel(m.type)}`,
      name: m.name,
      latitude: m.location?.latitude,
      longitude: m.location?.longitude,
      type: 'meal',
      address: m.address,
    })
  })
  return items
}

export function buildGoogleMapsDeepLinkUrl(items: DeepLinkItem[]): string {
  const locations = items.filter((item) => item.latitude !== undefined && item.longitude !== undefined)
  if (locations.length === 0) return 'https://www.google.com/maps'
  const [first, ...rest] = locations
  const waypointParts = rest.map((item) => `${item.latitude},${item.longitude}`)
  const base = `https://www.google.com/maps/dir/?api=1&travelmode=walking&destination=${encodeURIComponent(`${first.latitude},${first.longitude}`)}`
  return waypointParts.length === 0 ? base : `${base}&waypoints=${encodeURIComponent(waypointParts.join('|'))}`
}

