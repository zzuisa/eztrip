export type PosterTransitionTier = 'high' | 'medium' | 'low'

export interface PosterTransitionPreset {
  durationMs: number
  easing: string
  kenBurnsScale: number
  translateYPx: number
}

const PRESETS: Record<PosterTransitionTier, PosterTransitionPreset> = {
  high: {
    durationMs: 900,
    easing: 'cubic-bezier(0.22, 0.61, 0.36, 1)',
    kenBurnsScale: 1.08,
    translateYPx: 14,
  },
  medium: {
    durationMs: 700,
    easing: 'cubic-bezier(0.25, 0.46, 0.45, 0.94)',
    kenBurnsScale: 1.05,
    translateYPx: 8,
  },
  low: {
    durationMs: 450,
    easing: 'ease-out',
    kenBurnsScale: 1.02,
    translateYPx: 4,
  },
}

export function getPosterTransitionPreset(
  tier: PosterTransitionTier,
  reducedMotion = false,
): PosterTransitionPreset {
  if (reducedMotion) {
    return {
      durationMs: 220,
      easing: 'linear',
      kenBurnsScale: 1,
      translateYPx: 0,
    }
  }
  return PRESETS[tier]
}
