import type { PosterGuideStage } from '@/types/poster'

export function getGuideStepCopy(stage: PosterGuideStage): string {
  if (stage === 'overview') return '旅程总览'
  if (stage === 'introduction') return '导游介绍'
  if (stage === 'highlight') return '重点讲解'
  return '收尾总结'
}
