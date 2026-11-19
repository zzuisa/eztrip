import { describe, expect, it } from 'vitest'
import { usePosterStoryMotion } from '@/composables/usePosterStoryMotion'

describe('usePosterStoryMotion', () => {
  it('updates active frame and style by progress', () => {
    const motion = usePosterStoryMotion(3)
    motion.syncMotionTierFromDevice({ hardwareConcurrency: 12, deviceMemory: 8 })
    motion.setActiveFrame(1)
    motion.setFrameProgress(1, 0.9)

    const frame = motion.getFrameMotion(1)
    expect(frame.cardClass).toBe('poster-motion--full')
    expect(frame.cardStyle.opacity).toBeDefined()
    expect(frame.mediaStyle.transform).toContain('scale(')
  })

  it('downgrades to low tier for weaker devices', () => {
    const motion = usePosterStoryMotion(2)
    motion.syncMotionTierFromDevice({ hardwareConcurrency: 2, deviceMemory: 2 })
    expect(motion.motionTier.value).toBe('low')
  })

  it('uses lite motion when reduced-motion is enabled', () => {
    const motion = usePosterStoryMotion(2)
    motion.syncReducedMotionFromMediaQuery(true)
    motion.setFrameProgress(0, 0.4)
    const frame = motion.getFrameMotion(0)
    expect(frame.cardClass).toBe('poster-motion--lite')
    expect(frame.cardStyle.transform).toBe('translate3d(0, 0, 0)')
  })

  it('downgradeMotionTierOneStep steps high to medium to low', () => {
    const motion = usePosterStoryMotion(1)
    motion.syncMotionTierFromDevice({ hardwareConcurrency: 16, deviceMemory: 8 })
    expect(motion.motionTier.value).toBe('high')
    motion.downgradeMotionTierOneStep()
    expect(motion.motionTier.value).toBe('medium')
    motion.downgradeMotionTierOneStep()
    expect(motion.motionTier.value).toBe('low')
    motion.downgradeMotionTierOneStep()
    expect(motion.motionTier.value).toBe('low')
  })

  it('does not step motion tier when reduced-motion is on', () => {
    const motion = usePosterStoryMotion(1)
    motion.syncMotionTierFromDevice({ hardwareConcurrency: 16, deviceMemory: 8 })
    motion.syncReducedMotionFromMediaQuery(true)
    motion.downgradeMotionTierOneStep()
    expect(motion.motionTier.value).toBe('low')
  })
})
