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

export function buildPosterFallbackImageUrl(title: string, dayLabel: string): string {
  const seed = `${dayLabel}-${title}`
  const hue = Math.abs(seed.split('').reduce((acc, ch) => acc + ch.charCodeAt(0), 0)) % 360
  const hue2 = (hue + 38) % 360
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800">
    <defs>
      <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="hsl(${hue} 78% 54%)"/>
        <stop offset="100%" stop-color="hsl(${hue2} 72% 38%)"/>
      </linearGradient>
    </defs>
    <rect width="1200" height="800" fill="url(#g)"/>
    <rect x="80" y="80" width="1040" height="640" rx="36" fill="rgba(255,255,255,0.08)"/>
    <text x="80" y="170" fill="white" font-size="42" font-weight="700" font-family="sans-serif">${dayLabel}</text>
    <text x="80" y="270" fill="white" font-size="68" font-weight="800" font-family="sans-serif">${title}</text>
  </svg>`
  return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`
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
      if (!name) return
      const finalImageUrl = isRealImageUrl(imageUrl) ? imageUrl : buildPosterFallbackImageUrl(name, dayLabel)
      if (seenImage.has(finalImageUrl)) return
      seenImage.add(finalImageUrl)
      frames.push({
        id: buildFrameId(dayIndex, 'attraction', name),
        dayIndex,
        dayLabel,
        timeLabel: extractTimeLabel(day, name),
        title: name,
        subtitle: normalizeText(attraction?.description),
        imageUrl: finalImageUrl,
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

