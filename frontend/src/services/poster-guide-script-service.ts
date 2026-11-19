import type { PosterFrame, PosterGuideSlide, PosterStory } from '@/types/poster'
import { getGuideStepCopy } from '@/utils/poster-guide-steps'

function buildOverviewImage(city: string, days: number): string {
  const title = `${city || 'RogueTrip'} 行程总览`
  const subtitle = `${Math.max(days, 1)} 天故事导览`
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800">
    <defs>
      <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#0ea5e9"/>
        <stop offset="100%" stop-color="#7c3aed"/>
      </linearGradient>
    </defs>
    <rect width="1200" height="800" fill="url(#g)"/>
    <rect x="92" y="92" width="1016" height="616" rx="34" fill="rgba(255,255,255,0.08)"/>
    <text x="120" y="220" fill="white" font-size="42" font-weight="700" font-family="sans-serif">RogueTrip Guide</text>
    <text x="120" y="320" fill="white" font-size="72" font-weight="800" font-family="sans-serif">${title}</text>
    <text x="120" y="390" fill="rgba(255,255,255,0.92)" font-size="38" font-weight="600" font-family="sans-serif">${subtitle}</text>
  </svg>`
  return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`
}

function buildOverviewFrame(story: PosterStory): PosterFrame {
  const days = story.days.length || 1
  return {
    id: 'guide-overview',
    dayIndex: -1,
    dayLabel: '旅程总览',
    timeLabel: '',
    title: story.tripTitle || '旅行导览',
    subtitle: `本次行程共 ${days} 天，将按顺序逐站讲解。`,
    imageUrl: buildOverviewImage(story.tripTitle || 'RogueTrip', days),
    kind: 'activity',
    address: '',
  }
}

export function buildPosterGuideSlides(story: PosterStory): PosterGuideSlide[] {
  const slides: PosterGuideSlide[] = []
  const overview = buildOverviewFrame(story)
  slides.push({
    frame: overview,
    stage: 'overview',
    narration: '欢迎进入导游模式，先看本次旅程总览。',
    stepLabel: getGuideStepCopy('overview'),
  })

  story.frames.forEach((frame, index) => {
    const isLast = index === story.frames.length - 1
    const stage = index === 0 ? 'introduction' : isLast ? 'closing' : 'highlight'
    const narration = isLast
      ? `最后一站：${frame.title}。讲解结束后可继续自由浏览。`
      : `${frame.dayLabel} · ${frame.title}，${frame.address || '请查看详情信息'}。`
    slides.push({
      frame,
      stage,
      narration,
      stepLabel: getGuideStepCopy(stage),
    })
  })
  return slides
}
