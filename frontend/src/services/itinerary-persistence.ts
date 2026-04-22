import type { OptimizedItinerary } from '@/types/itinerary'

const STORAGE_PREFIX = 'eztrip:itinerary:'
const INDEX_KEY = 'eztrip:itinerary:index'
const VERSION = 1

export interface PersistedItineraryEnvelope {
  version: number
  id: string
  savedAtIso: string
  itinerary: OptimizedItinerary
}

function safeParse<T>(text: string | null): T | null {
  if (!text) return null
  try {
    return JSON.parse(text) as T
  } catch {
    return null
  }
}

function getStorage(): Storage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

function readIndex(storage: Storage): string[] {
  const idx = safeParse<string[]>(storage.getItem(INDEX_KEY))
  if (Array.isArray(idx)) return idx.filter((x) => typeof x === 'string' && x.trim())
  return []
}

function writeIndex(storage: Storage, ids: string[]) {
  storage.setItem(INDEX_KEY, JSON.stringify(Array.from(new Set(ids)).slice(0, 50)))
}

export function saveItinerary(itinerary: OptimizedItinerary): { ok: true } | { ok: false; error: string } {
  const storage = getStorage()
  if (!storage) return { ok: false, error: '浏览器存储不可用' }
  if (!itinerary?.id) return { ok: false, error: '缺少 itinerary.id，无法保存' }

  const envelope: PersistedItineraryEnvelope = {
    version: VERSION,
    id: itinerary.id,
    savedAtIso: new Date().toISOString(),
    itinerary: { ...itinerary, updatedAtIso: new Date().toISOString() },
  }

  try {
    storage.setItem(`${STORAGE_PREFIX}${itinerary.id}`, JSON.stringify(envelope))
    const ids = readIndex(storage)
    writeIndex(storage, [itinerary.id, ...ids])
    return { ok: true }
  } catch (e: any) {
    return { ok: false, error: e?.message || '保存失败' }
  }
}

export function loadItinerary(id: string): OptimizedItinerary | null {
  const storage = getStorage()
  if (!storage) return null
  const env = safeParse<PersistedItineraryEnvelope>(storage.getItem(`${STORAGE_PREFIX}${id}`))
  if (!env?.itinerary) return null
  return env.itinerary
}

export function loadLatestItinerary(): OptimizedItinerary | null {
  const storage = getStorage()
  if (!storage) return null
  const ids = readIndex(storage)
  for (const id of ids) {
    const hit = loadItinerary(id)
    if (hit) return hit
  }
  return null
}

export function deleteItinerary(id: string): void {
  const storage = getStorage()
  if (!storage) return
  try {
    storage.removeItem(`${STORAGE_PREFIX}${id}`)
    const ids = readIndex(storage).filter((x) => x !== id)
    writeIndex(storage, ids)
  } catch {
    // ignore
  }
}

