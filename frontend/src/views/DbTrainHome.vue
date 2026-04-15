<template>
  <div class="db-home">
    <a-card title="德铁车次查询（对话模式）" :bordered="false">
      <div class="chat">
        <div v-for="m in messages" :key="m.id" class="msg-row" :class="m.role">
          <div class="bubble">
            <div class="text">{{ m.text }}</div>
            <div v-if="m.role === 'assistant' && m.kind === 'trips'">
              <a-divider style="margin: 12px 0" />
              <a-table
                :data-source="trips"
                :pagination="{ pageSize: 8 }"
                size="small"
                row-key="train_name"
              >
                <a-table-column title="车次" data-index="train_name" key="train_name" />
                <a-table-column title="出发" data-index="origin" key="origin" />
                <a-table-column title="目的" data-index="destination" key="destination" />
                <a-table-column title="出发时间" data-index="departure_time" key="departure_time">
                  <template #default="{ text }">
                    {{ formatDbTime(text) }}
                  </template>
                </a-table-column>
                <a-table-column title="到达时间" data-index="arrival_time" key="arrival_time">
                  <template #default="{ text }">
                    {{ formatDbTime(text) }}
                  </template>
                </a-table-column>
                <a-table-column title="站台" data-index="platform" key="platform" />
                <a-table-column title="状态" data-index="status" key="status" />
              </a-table>
            </div>
          </div>
        </div>
      </div>

      <div class="composer">
        <a-input
          v-model:value="draft"
          placeholder="直接提问：例如 2026-04-02 14点 Frankfurt Hbf 到 Berlin Hbf 有哪些车次？"
          size="large"
          :disabled="loading"
          @pressEnter="send"
        />
        <a-button type="primary" size="large" :loading="loading" @click="send">
          发送
        </a-button>
        <a-button size="large" :disabled="loading" @click="resetConversation">
          重置
        </a-button>
      </div>
    </a-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { nlqTrips } from '@/services/deutscheBahn'
import type { DbTrip } from '@/types'

const loading = ref(false)
const draft = ref('')
const trips = ref<DbTrip[]>([])

type ChatMessage = {
  id: string
  role: 'assistant' | 'user'
  text: string
  kind?: 'text' | 'trips'
}

const messages = ref<ChatMessage[]>([
  {
    id: 'a-1',
    role: 'assistant',
    text: '你可以直接提问（包含出发地、目的地、日期、时间），我会自动抽取信息并查询德铁车次。',
    kind: 'text'
  }
])

const formatDbTime = (value: any) => {
  const s = String(value ?? '').trim()
  if (!s) return '-'

  // DB timetables 常见：YYMMDDHHmm，例如 2604021817
  if (/^\d{10}$/.test(s)) {
    const yy = Number(s.slice(0, 2))
    const yyyy = 2000 + yy
    const mm = s.slice(2, 4)
    const dd = s.slice(4, 6)
    const HH = s.slice(6, 8)
    const Min = s.slice(8, 10)
    return `${yyyy}-${mm}-${dd} ${HH}:${Min}`
  }

  return s
}

const extractLimit = (q: string): number | null => {
  const text = (q || '').trim()
  const m = text.match(/(?:最近|只看|展示|显示)?\s*(\d{1,2})\s*(?:个|条)/)
  if (!m) return null
  const n = Number(m[1])
  if (!Number.isFinite(n) || n <= 0) return null
  return Math.min(n, 50)
}

const pushAssistant = (text: string, kind: 'text' | 'trips' = 'text') => {
  messages.value.push({ id: `a-${Date.now()}-${Math.random()}`, role: 'assistant', text, kind })
}

const pushUser = (text: string) => {
  messages.value.push({ id: `u-${Date.now()}-${Math.random()}`, role: 'user', text, kind: 'text' })
}

const resetConversation = () => {
  trips.value = []
  draft.value = ''
  messages.value = [
    {
      id: 'a-1',
      role: 'assistant',
      text: '你可以直接提问（包含出发地、目的地、日期、时间），我会自动抽取信息并查询德铁车次。',
      kind: 'text'
    }
  ]
}

const fetchTrips = async (query: string) => {
  loading.value = true
  try {
    const resp = await nlqTrips(query)
    const limit = extractLimit(query)
    const all = resp.data || []
    trips.value = limit ? all.slice(0, limit) : all
    if (resp.parsed) {
      pushAssistant(
        `已解析：${resp.parsed.origin} -> ${resp.parsed.destination}（${resp.parsed.date} ${resp.parsed.hour}:00）。`,
        'text'
      )
    }
    pushAssistant('查询结果如下：', 'trips')
    if (!trips.value.length) {
      message.info('该时间段暂无匹配车次')
    }
  } catch (err: any) {
    pushAssistant(`查询失败：${err.message || '未知错误'}`)
  } finally {
    loading.value = false
  }
}

const send = async () => {
  if (loading.value) return
  const text = draft.value.trim()
  if (!text) return

  pushUser(text)
  draft.value = ''
  await fetchTrips(text)
}
</script>

<style scoped>
.db-home {
  max-width: 1100px;
  margin: 0 auto;
}

.chat {
  max-height: 65vh;
  overflow: auto;
  padding: 8px 4px;
}

.msg-row {
  display: flex;
  margin: 10px 0;
}

.msg-row.assistant {
  justify-content: flex-start;
}

.msg-row.user {
  justify-content: flex-end;
}

.bubble {
  max-width: 900px;
  padding: 12px 14px;
  border-radius: 12px;
  border: 1px solid #f0f0f0;
  background: #ffffff;
}

.msg-row.user .bubble {
  background: #e6f4ff;
  border-color: #91caff;
}

.text {
  white-space: pre-wrap;
  line-height: 1.6;
}

.composer {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}
</style>

