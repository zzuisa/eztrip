import { ref, type Ref } from 'vue'
import type { TripPlan } from '@/types'
import { normalizeItinerary } from '@/services/itinerary-normalizer'
import { saveItinerary } from '@/services/itinerary-persistence'

export interface UseItineraryEditingOptions {
  /**
   * 用于持久化/区分不同结果页（例如 result_id）。
   * 不提供则仅用规范化后的默认 id。
   */
  itineraryIdHint?: string
}

export function useItineraryEditing(
  tripPlan: Ref<TripPlan | null>,
  options: UseItineraryEditingOptions = {},
) {
  const editMode = ref(false)
  const originalPlan = ref<TripPlan | null>(null)
  const saving = ref(false)

  const toggleEditMode = () => {
    editMode.value = true
    originalPlan.value = tripPlan.value ? JSON.parse(JSON.stringify(tripPlan.value)) : null
  }

  const cancelEdit = () => {
    if (originalPlan.value) {
      tripPlan.value = JSON.parse(JSON.stringify(originalPlan.value))
    }
    editMode.value = false
  }

  const saveChanges = (): { ok: true } | { ok: false; error: string } => {
    if (!tripPlan.value) return { ok: false, error: '当前没有可保存的行程数据' }
    saving.value = true
    try {
      editMode.value = false
      sessionStorage.setItem('tripPlan', JSON.stringify(tripPlan.value))

      // 同步保存一份标准化后的行程到 localStorage（用于跨刷新恢复/离线兜底）。
      const normalized = normalizeItinerary(tripPlan.value, { source: 'result:save' })
      if (normalized) {
        const id = options.itineraryIdHint ? `${normalized.id}:${options.itineraryIdHint}` : normalized.id
        saveItinerary({ ...normalized, id })
      }
      return { ok: true }
    } catch (e: any) {
      return { ok: false, error: e?.message || '保存失败' }
    } finally {
      saving.value = false
    }
  }

  return {
    editMode,
    originalPlan,
    saving,
    toggleEditMode,
    cancelEdit,
    saveChanges,
  }
}

