import type { DayPlan } from '@/types'
import type { PosterBuildInput, PosterFrame, PosterStory } from '@/types/poster'

const TIME_RE = /(\d{1,2}:\d{2})/

function normalizeText(value: unknown): string {
  return String(value || '').trim()
}

function isLikelyPlaceholder(url: string): boolean {
  const v = url.toLowerCase()
  return v.startsWith('data:image/svg+xml') || v.includes('placeholder') || v.includes('image loading failed')
}

function isRealImageUrl(url: string): boolean {
  const v = normalizeText(url)
  if (!v) return false
  if (isLikelyPlaceholder(v)) return false
  return /^https?:\/\//i.test(v)
}

function extractTimeLabel(day: DayPlan, attractionName: string): string {
  const activities = Array.isArray(day.activities) ? day.activities : []
  const matched = activities.find((a) => normalizeText(a?.name) === attractionName)
  const raw = normalizeText(matched?.time)
  if (!raw) return ''
  const hit = raw.match(TIME_RE)
  return hit ? hit[1] : raw
}

function buildFrameId(dayIndex: number, kind: string, name: string): string {
  return `${dayIndex}-${kind}-${name}`.toLowerCase().replace(/\s+/g, '-')
}

export function buildPosterStory(input: PosterBuildInput): PosterStory {
  const frames: PosterFrame[] = []
  const seenImage = new Set<string>()
  const city = normalizeText(input.city) || 'RogueTrip'

  ;(input.days || []).forEach((day, idx) => {
    const dayIndex = Number(day?.day_index ?? idx)
    const dayLabel = normalizeText(day?.display_title) || `第${dayIndex + 1}天`

    ;(day.attractions || []).forEach((attraction) => {
      const name = normalizeText(attraction?.name)
      const imageUrl = normalizeText(attraction?.image_url)
      if (!name || !isRealImageUrl(imageUrl)) return
      if (seenImage.has(imageUrl)) return
      seenImage.add(imageUrl)
      frames.push({
        id: buildFrameId(dayIndex, 'attraction', name),
        dayIndex,
        dayLabel,
        timeLabel: extractTimeLabel(day, name),
        title: name,
        subtitle: normalizeText(attraction?.description),
        imageUrl,
        kind: 'attraction',
        address: normalizeText(attraction?.address),
      })
    })
  })

  const days = [...new Set(frames.map((f) => f.dayIndex))]
    .sort((a, b) => a - b)
    .map((dayIndex) => {
      const items = frames.filter((f) => f.dayIndex === dayIndex)
      return {
        dayIndex,
        dayTitle: items[0]?.dayLabel || `第${dayIndex + 1}天`,
        frames: items,
      }
    })

  return {
    tripTitle: `${city} · 定制化海报`,
    frames,
    days,
  }
}

export function hasPosterFrames(days: DayPlan[]): boolean {
  return buildPosterStory({ city: '', days }).frames.length > 0
}

