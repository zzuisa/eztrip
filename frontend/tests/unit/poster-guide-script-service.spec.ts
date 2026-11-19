import { describe, expect, it } from 'vitest'
import { buildPosterGuideSlides } from '@/services/poster-guide-script-service'

describe('poster-guide-script-service', () => {
  it('creates overview-first guide sequence', () => {
    const slides = buildPosterGuideSlides({
      tripTitle: 'Paris · 定制化海报',
      days: [{ dayIndex: 0, dayTitle: '第1天', frames: [] }],
      frames: [
        {
          id: 'a',
          dayIndex: 0,
          dayLabel: '第1天',
          timeLabel: '09:00',
          title: 'Louvre',
          subtitle: 'museum',
          imageUrl: 'https://a.test/1.jpg',
          kind: 'attraction',
          address: 'Paris',
        },
      ],
    })

    expect(slides.length).toBe(2)
    expect(slides[0].stage).toBe('overview')
    expect(slides[0].stepLabel).toContain('总览')
    expect(slides[1].frame.title).toBe('Louvre')
  })
})
