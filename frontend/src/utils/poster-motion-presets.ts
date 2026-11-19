export type PosterMotionTier = 'high' | 'medium' | 'low'

export interface PosterMotionPreset {
  parallaxOffset: number
  zoomScale: number
  flipDeg: number
  fadeMinOpacity: number
}

export const POSTER_MOTION_PRESETS: Record<PosterMotionTier, PosterMotionPreset> = {
  high: {
    parallaxOffset: 26,
    zoomScale: 0.08,
    flipDeg: 6,
    fadeMinOpacity: 0.5,
  },
  medium: {
    parallaxOffset: 16,
    zoomScale: 0.05,
    flipDeg: 4,
    fadeMinOpacity: 0.62,
  },
  low: {
    parallaxOffset: 8,
    zoomScale: 0.025,
    flipDeg: 2,
    fadeMinOpacity: 0.76,
  },
}

export function inferPosterMotionTier(input?: {
  hardwareConcurrency?: number
  deviceMemory?: number
}): PosterMotionTier {
  const cores = Number(input?.hardwareConcurrency ?? 4)
  const memory = Number(input?.deviceMemory ?? 4)
  if (cores <= 4 || memory <= 3) return 'low'
  if (cores <= 8 || memory <= 6) return 'medium'
  return 'high'
}

export function getPosterMotionPreset(tier: PosterMotionTier): PosterMotionPreset {
  return POSTER_MOTION_PRESETS[tier]
}
