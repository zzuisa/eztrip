import { describe, expect, it } from 'vitest'
import { buildPosterStory, hasPosterFrames } from '@/services/poster-data-service'

describe('poster-data-service', () => {
  it('filters non-real images and deduplicates', () => {
    const story = buildPosterStory({
      city: 'Paris',
      days: [
        {
          day_index: 0,
          date: '2026-01-01',
          description: '',
          transportation: '',
          accommodation: '',
          attractions: [
            { name: 'A', address: 'x', location: { latitude: 1, longitude: 1 }, visit_duration: 60, description: '', image_url: 'https://a.test/img.jpg' },
            { name: 'B', address: 'x', location: { latitude: 1, longitude: 1 }, visit_duration: 60, description: '', image_url: 'data:image/svg+xml;base64,abc' },
            { name: 'C', address: 'x', location: { latitude: 1, longitude: 1 }, visit_duration: 60, description: '', image_url: 'https://a.test/img.jpg' },
          ],
          meals: [],
          activities: [{ name: 'A', time: '09:00-10:00', description: '', route_desc: '', estimated_cost: 0 }],
        },
      ] as any,
    })

    expect(story.frames.length).toBe(1)
    expect(story.frames[0].title).toBe('A')
    expect(story.frames[0].timeLabel).toBe('09:00')
  })

  it('supports no-image days', () => {
    const ok = hasPosterFrames([
      {
        day_index: 0,
        date: '2026-01-01',
        description: '',
        transportation: '',
        accommodation: '',
        attractions: [
          { name: 'A', address: '', location: { latitude: 1, longitude: 1 }, visit_duration: 60, description: '', image_url: '' },
        ],
        meals: [],
      } as any,
    ])
    expect(ok).toBe(false)
  })
})

