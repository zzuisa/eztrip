<template>
  <div class="admin-trips-page">
    <a-card title="行程管理" :bordered="false" class="admin-card">
      <template #extra>
        <a-space>
          <a-button @click="loadTrips" :loading="loading">刷新</a-button>
        </a-space>
      </template>

      <a-alert
        v-if="errorMessage"
        type="error"
        show-icon
        :message="errorMessage"
        style="margin-bottom: 16px"
      />

      <a-empty v-if="!loading && trips.length === 0" description="暂无已保存行程" />

      <div v-else class="trip-list">
        <a-card v-for="trip in trips" :key="trip.id" size="small" class="trip-item">
          <div class="trip-item-main">
            <div class="trip-item-title">{{ trip.location }}</div>
            <div class="trip-item-meta">
              <a-tag color="blue">{{ trip.days }} 天</a-tag>
              <a-tag :color="trip.warnings_count > 0 ? 'orange' : 'green'">{{ trip.warnings_count }} 个提醒</a-tag>
              <span class="trip-item-date">更新于 {{ formatDate(trip.updated_at) }}</span>
            </div>
          </div>
          <template #extra>
            <a-space wrap>
              <a-button size="small" type="primary" @click="openTrip(trip)">打开</a-button>
              <a-button size="small" @click="copyTripId(trip.id)">复制 ID</a-button>
              <a-popconfirm title="确认删除这条行程吗？" @confirm="removeTrip(trip.id)">
                <a-button size="small" danger>删除</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </a-card>
      </div>
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { deleteStoredTravelPlan, listStoredTravelPlans, type StoredTripSummary } from '@/services/api'

const router = useRouter()
const loading = ref(false)
const trips = ref<StoredTripSummary[]>([])
const errorMessage = ref('')

const loadTrips = async () => {
  loading.value = true
  errorMessage.value = ''
  try {
    trips.value = await listStoredTravelPlans(50)
  } catch (error: any) {
    errorMessage.value = error?.message || '加载行程列表失败'
  } finally {
    loading.value = false
  }
}

const openTrip = (trip: StoredTripSummary) => {
  router.push(`/result/${encodeURIComponent(trip.id)}`)
}

const copyTripId = async (id: string) => {
  try {
    await navigator.clipboard.writeText(id)
    message.success('行程 ID 已复制')
  } catch {
    message.error('复制失败')
  }
}

const removeTrip = async (id: string) => {
  try {
    await deleteStoredTravelPlan(id)
    message.success('已删除')
    await loadTrips()
  } catch (error: any) {
    message.error(error?.message || '删除失败')
  }
}

const formatDate = (value: string) => {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

onMounted(loadTrips)
</script>

<style scoped>
.admin-trips-page {
  padding: 24px;
}
.admin-card {
  max-width: 1200px;
  margin: 0 auto;
}
.trip-list {
  display: grid;
  gap: 12px;
}
.trip-item-title {
  font-size: 16px;
  font-weight: 600;
  color: #0f172a;
}
.trip-item-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 8px;
  color: #64748b;
}
.trip-item-date {
  font-size: 12px;
}
</style>
