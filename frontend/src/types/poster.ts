import type { DayPlan } from './index'

export type PosterFrameKind = 'attraction' | 'meal' | 'activity'

export interface PosterFrame {
  id: string
  dayIndex: number
  dayLabel: string
  timeLabel: string
  title: string
  subtitle?: string
  imageUrl: string
  kind: PosterFrameKind
  address?: string
}

export interface PosterStory {
  tripTitle: string
  frames: PosterFrame[]
  days: Array<{
    dayIndex: number
    dayTitle: string
    frames: PosterFrame[]
  }>
}

export interface PosterAssetState {
  status: 'idle' | 'loading' | 'ready' | 'error'
  loadedCount: number
  failedCount: number
  total: number
}

export interface PosterBuildInput {
  city: string
  days: DayPlan[]
}

export type PosterGuideStage = 'overview' | 'introduction' | 'highlight' | 'closing'

export interface PosterGuideSlide {
  frame: PosterFrame
  stage: PosterGuideStage
  narration: string
  stepLabel: string
}

