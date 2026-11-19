import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import TripPosterLightbox from '@/components/poster/TripPosterLightbox.vue'

describe('trip poster guide mode', () => {
  it('shows overview then guided narration step', async () => {
    const frames = [
      {
        id: 'guide-overview',
        dayIndex: -1,
        dayLabel: '旅程总览',
        timeLabel: '',
        title: 'Paris · 定制化海报',
        subtitle: '总览介绍',
        imageUrl: 'https://a.test/overview.jpg',
        kind: 'activity',
        address: '',
      },
      {
        id: 'spot-1',
        dayIndex: 0,
        dayLabel: '第1天',
        timeLabel: '09:00',
        title: 'Louvre',
        subtitle: '景点讲解',
        imageUrl: 'https://a.test/1.jpg',
        kind: 'attraction',
        address: 'Paris',
      },
    ]
    const wrapper = mount(TripPosterLightbox, {
      props: {
        visible: true,
        frames,
        guideSlides: [
          { stage: 'overview', narration: '先看总览', stepLabel: '旅程总览' },
          { stage: 'highlight', narration: '现在介绍 Louvre', stepLabel: '重点讲解' },
        ],
        activeIndex: 0,
        zoomScale: 1,
        isFullscreen: true,
        autoplayPaused: false,
        transitionPreset: {
          durationMs: 700,
          easing: 'ease-out',
          kenBurnsScale: 1.05,
          translateYPx: 8,
        },
      },
      attachTo: document.body,
    })

    expect(document.body.textContent || '').toContain('旅程总览')
    await wrapper.setProps({ activeIndex: 1 })
    expect(document.body.textContent || '').toContain('重点讲解')
    wrapper.unmount()
  })
})
