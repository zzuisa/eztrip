import { computed, ref } from 'vue'

export type ExportStatus = 'idle' | 'preparing' | 'done' | 'error'

export function useResultPage() {
  const activeSection = ref('overview')
  const activeDays = ref<number[]>([0])
  const selectedPlaceKey = ref('')

  const deepLinkVisible = ref(false)
  const currentDeepLinkDayIndex = ref(0)

  const exportStatus = ref<ExportStatus>('idle')

  const deepLinkItems = ref<Array<{
    key: string
    label: string
    name: string
    latitude?: number
    longitude?: number
    type: 'attraction' | 'meal'
    address?: string
  }>>([])

  const hasDeepLinkItems = computed(() => deepLinkItems.value.length > 0)

  return {
    activeSection,
    activeDays,
    selectedPlaceKey,
    deepLinkVisible,
    currentDeepLinkDayIndex,
    deepLinkItems,
    hasDeepLinkItems,
    exportStatus,
  }
}

