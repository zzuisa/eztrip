<template>
  <div>
    <a-card title="RogueTrip 行程管理" :bordered="false">
      <a-space style="margin-bottom: 12px">
        <a-button type="primary" @click="loadTrips" :loading="loading">刷新</a-button>
      </a-space>
      <a-table
        :data-source="trips"
        :loading="loading"
        row-key="id"
        :pagination="{ pageSize: 10 }"
      >
        <a-table-column title="ID" data-index="id" key="id" />
        <a-table-column title="目的地" data-index="location" key="location" />
        <a-table-column title="天数" data-index="days" key="days" />
        <a-table-column title="创建时间" data-index="created_at" key="created_at" />
        <a-table-column title="操作" key="actions">
          <template #default="{ record }">
            <a-space>
              <a-button size="small" type="link" @click="openResult(record.id)">查看</a-button>
              <a-popconfirm title="确认删除该行程？" @confirm="removeTrip(record.id)">
                <a-button size="small" danger type="link">删除</a-button>
              </a-popconfirm>
            </a-space>
          </template>
        </a-table-column>
      </a-table>
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

const loadTrips = async () => {
  loading.value = true
  try {
    trips.value = await listStoredTravelPlans()
  } catch (error: any) {
    message.error(error?.message || '加载行程失败')
  } finally {
    loading.value = false
  }
}

const openResult = (id: string) => {
  router.push(`/result/${id}`)
}

const removeTrip = async (id: string) => {
  try {
    await deleteStoredTravelPlan(id)
    message.success('删除成功')
    await loadTrips()
  } catch (error: any) {
    message.error(error?.message || '删除失败')
  }
}

onMounted(() => {
  loadTrips()
})
</script>

