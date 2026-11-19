import type { PosterAssetState } from '@/types/poster'

export type PosterImageLoadResult = {
  url: string
  ok: boolean
  width?: number
  height?: number
}

export async function preloadPosterImages(
  urls: string[],
  onState?: (state: PosterAssetState) => void,
): Promise<PosterImageLoadResult[]> {
  const list = [...new Set(urls.filter(Boolean))]
  const state: PosterAssetState = {
    status: list.length ? 'loading' : 'ready',
    loadedCount: 0,
    failedCount: 0,
    total: list.length,
  }
  onState?.(state)

  const results: PosterImageLoadResult[] = []
  for (const url of list) {
    const item = await new Promise<PosterImageLoadResult>((resolve) => {
      const img = new Image()
      img.decoding = 'async'
      img.loading = 'eager'
      img.onload = () => resolve({ url, ok: true, width: img.naturalWidth, height: img.naturalHeight })
      img.onerror = () => resolve({ url, ok: false })
      img.src = url
    })
    results.push(item)
    if (item.ok) state.loadedCount += 1
    else state.failedCount += 1
    onState?.({ ...state })
  }

  state.status = state.failedCount > 0 ? 'error' : 'ready'
  onState?.({ ...state })
  return results
}

