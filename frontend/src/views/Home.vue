<template>
  <div ref="pageEl" class="home-container">
    <!-- 背景装饰 -->
    <div class="bg-decoration">
      <div class="circle circle-1"></div>
      <div class="circle circle-2"></div>
      <div class="circle circle-3"></div>
    </div>

    <!-- 页面标题 -->
    <div class="page-header">
      <div class="icon-wrapper">
        <span class="icon">✈️</span>
      </div>
      <h1 class="page-title">{{ APP_NAME }}</h1>
      <p class="page-subtitle">基于AI的个性化旅行规划,让每一次出行都完美无忧</p>
    </div>

    <a-card class="form-card" :bordered="false">
      <a-form
        :model="formData"
        layout="vertical"
        @finish="handleSubmit"
      >
        <!-- 第一步:目的地和日期 -->
        <div class="form-section">
          <div class="section-header">
            <span class="section-icon">📍</span>
            <span class="section-title">目的地与日期</span>
          </div>

          <a-row :gutter="24" class="mobile-stack-row">
            <a-col :span="8">
              <a-form-item name="city" :rules="[{ required: true, message: '请输入目的地城市' }]">
                <template #label>
                  <span class="form-label">目的地城市</span>
                </template>
                <a-input
                  v-model:value="formData.city"
                  placeholder="例如: 北京"
                  size="large"
                  class="custom-input"
                >
                  <template #prefix>
                    <span style="color: #1890ff;">🏙️</span>
                  </template>
                </a-input>
              </a-form-item>
            </a-col>
            <a-col :span="6">
              <a-form-item name="start_date" :rules="[{ required: true, message: '请选择开始日期' }]">
                <template #label>
                  <span class="form-label">开始日期</span>
                </template>
                <a-date-picker
                  v-model:value="formData.start_date"
                  style="width: 100%"
                  size="large"
                  class="custom-input"
                  placeholder="选择日期"
                />
              </a-form-item>
            </a-col>
            <a-col :span="6">
              <a-form-item name="end_date" :rules="[{ required: true, message: '请选择结束日期' }]">
                <template #label>
                  <span class="form-label">结束日期</span>
                </template>
                <a-date-picker
                  v-model:value="formData.end_date"
                  style="width: 100%"
                  size="large"
                  class="custom-input"
                  placeholder="选择日期"
                />
              </a-form-item>
            </a-col>
            <a-col :span="4">
              <a-form-item>
                <template #label>
                  <span class="form-label">旅行天数</span>
                </template>
                <div class="days-display-compact">
                  <span class="days-value">{{ formData.travel_days }}</span>
                  <span class="days-unit">天</span>
                </div>
              </a-form-item>
            </a-col>
          </a-row>
        </div>

        <!-- 第二步:偏好设置 -->
        <div class="form-section">
          <div class="section-header">
            <span class="section-icon">⚙️</span>
            <span class="section-title">偏好设置</span>
          </div>

          <a-row :gutter="24" class="mobile-stack-row">
            <a-col :span="8">
              <a-form-item name="transportation">
                <template #label>
                  <span class="form-label">交通方式</span>
                </template>
                <a-select v-model:value="formData.transportation" size="large" class="custom-select">
                  <a-select-option value="公共交通">🚇 公共交通</a-select-option>
                  <a-select-option value="自驾">🚗 自驾</a-select-option>
                  <a-select-option value="步行">🚶 步行</a-select-option>
                  <a-select-option value="混合">🔀 混合</a-select-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item name="accommodation">
                <template #label>
                  <span class="form-label">住宿偏好</span>
                </template>
                <a-select v-model:value="formData.accommodation" size="large" class="custom-select">
                  <a-select-option value="经济型酒店">💰 经济型酒店</a-select-option>
                  <a-select-option value="舒适型酒店">🏨 舒适型酒店</a-select-option>
                  <a-select-option value="豪华酒店">⭐ 豪华酒店</a-select-option>
                  <a-select-option value="民宿">🏡 民宿</a-select-option>
                </a-select>
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item name="preferences">
                <template #label>
                  <span class="form-label">旅行偏好</span>
                </template>
                <div class="preference-tags">
                  <a-checkbox-group v-model:value="formData.preferences" class="custom-checkbox-group">
                    <a-checkbox value="历史文化" class="preference-tag">🏛️ 历史文化</a-checkbox>
                    <a-checkbox value="自然风光" class="preference-tag">🏞️ 自然风光</a-checkbox>
                    <a-checkbox value="美食" class="preference-tag">🍜 美食</a-checkbox>
                    <a-checkbox value="购物" class="preference-tag">🛍️ 购物</a-checkbox>
                    <a-checkbox value="艺术" class="preference-tag">🎨 艺术</a-checkbox>
                    <a-checkbox value="休闲" class="preference-tag">☕ 休闲</a-checkbox>
                  </a-checkbox-group>
                </div>
              </a-form-item>
            </a-col>
          </a-row>
        </div>

        <!-- 第三步:额外要求 -->
        <div class="form-section">
          <div class="section-header">
            <span class="section-icon">💬</span>
            <span class="section-title">额外要求</span>
          </div>

          <a-form-item name="free_text_input">
            <a-textarea
              v-model:value="formData.free_text_input"
              placeholder="请输入您的额外要求,例如:想去看升旗、需要无障碍设施、对海鲜过敏等..."
              :rows="3"
              size="large"
              class="custom-textarea"
            />
          </a-form-item>
        </div>

        <!-- 提交按钮 -->
        <a-form-item>
          <div class="action-buttons">
            <a-button
              type="primary"
              html-type="submit"
              :loading="loading"
              size="large"
              class="submit-button"
            >
              <template v-if="!loading">
                <span class="button-icon">🚀</span>
                <span>开始规划我的旅行</span>
              </template>
              <template v-else>
                <span>正在生成中...</span>
              </template>
            </a-button>

            <a-button
              size="large"
              class="debug-button"
              :disabled="loading"
              @click="handleDebugSubmit"
            >
              <span class="button-icon">🧪</span>
              <span>调试（法国行程）</span>
            </a-button>
          </div>
        </a-form-item>
      </a-form>
    </a-card>

    <FullscreenLoading
      ref="loadingOverlayRef"
      :visible="fullscreenVisible"
      :percent="loadingProgress"
      :stage="currentStage"
      title="正在生成行程"
      :status="loadingStatus"
      :logs="displayLogs"
      :cancel-disabled="cancelDisabled"
      @cancel="handleCancel"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { streamTravelPlanByLocation } from '@/services/api'
import type { TripFormData } from '@/types'
import type { Dayjs } from 'dayjs'
import FullscreenLoading from '@/components/FullscreenLoading.vue'
import { useFullscreenLoadingTransition } from '@/composables/useFullscreenLoadingTransition'
import { formatLoadingLog } from '@/utils/loading-log-format'
import { APP_NAME } from '@/constants/brand'

const router = useRouter()
const pageEl = ref<HTMLElement | null>(null)
const loadingOverlayRef = ref<InstanceType<typeof FullscreenLoading> | null>(null)
const fullscreenVisible = ref(false)
const loading = ref(false)
const currentStage = ref('connecting')
const loadingProgress = ref(0)
const loadingStatus = ref('')
const liveLogs = ref<string[]>([])
const streamConnected = ref(false)
const stepStatus = ref<Record<string, string>>({
  strategy: 'pending',
  generation: 'pending',
  reflection: 'pending',
})
const reflectionFallbackMessage = ref('')
const stepStatusList = ref([
  { key: 'strategy', label: '搜索策略', status: 'pending' },
  { key: 'generation', label: '行程生成', status: 'pending' },
  { key: 'reflection', label: '反思优化', status: 'pending' },
])

const cancelDisabled = computed(() => !loading.value || loadingProgress.value >= 100)
const displayLogs = computed(() => [...liveLogs.value].slice(0, 5).reverse())

const transition = useFullscreenLoadingTransition({ durationMs: 560 })
const abortController = ref<AbortController | null>(null)
const navigating = ref(false)

const pushUiLog = (line: string | null) => {
  const msg = (line || '').trim()
  if (!msg) return
  if (liveLogs.value[0] === msg) return
  liveLogs.value.unshift(msg)
  liveLogs.value = liveLogs.value.slice(0, 12)
}

const showOverlay = async () => {
  fullscreenVisible.value = true
  await nextTick()
  await transition.enter({
    page: pageEl.value,
    overlay: loadingOverlayRef.value?.getOverlayEl?.(),
  })
}

const hideOverlay = async () => {
  await transition.leave({
    page: pageEl.value,
    overlay: loadingOverlayRef.value?.getOverlayEl?.(),
  })
  fullscreenVisible.value = false
}

type HomeFormData = Omit<TripFormData, 'start_date' | 'end_date'> & {
  start_date: Dayjs | null
  end_date: Dayjs | null
}

const formData = reactive<HomeFormData>({
  city: '',
  start_date: null,
  end_date: null,
  travel_days: 1,
  transportation: '公共交通',
  accommodation: '经济型酒店',
  preferences: [],
  free_text_input: ''
})

const syncStepStatusList = () => {
  stepStatusList.value = stepStatusList.value.map((item) => ({
    ...item,
    status: stepStatus.value[item.key] || 'pending',
  }))
}

const resetStepStatus = () => {
  stepStatus.value = { strategy: 'pending', generation: 'pending', reflection: 'pending' }
  reflectionFallbackMessage.value = ''
  syncStepStatusList()
}

const updateStepStatus = (name: string, status: string) => {
  if (!name) return
  stepStatus.value = { ...stepStatus.value, [name]: status || 'pending' }
  syncStepStatusList()
}

// 监听日期变化,自动计算旅行天数
watch([() => formData.start_date, () => formData.end_date], ([start, end]) => {
  if (start && end) {
    const days = end.diff(start, 'day') + 1
    if (days > 0 && days <= 30) {
      formData.travel_days = days
    } else if (days > 30) {
      message.warning('旅行天数不能超过30天')
      formData.end_date = null
    } else {
      message.warning('结束日期不能早于开始日期')
      formData.end_date = null
    }
  }
})

const handleSubmit = async () => {
  if (!formData.start_date || !formData.end_date) {
    message.error('请选择日期')
    return
  }

  loading.value = true
  navigating.value = false
  currentStage.value = 'connecting'
  loadingProgress.value = 0
  loadingStatus.value = '正在连接生成服务...'
  liveLogs.value = []
  streamConnected.value = true
  resetStepStatus()
  abortController.value = new AbortController()

  pushUiLog(formatLoadingLog({ type: 'progress', percent: 1, status: '正在连接生成服务...' }))
  await showOverlay()

  try {
    const requestData: TripFormData = {
      city: formData.city,
      start_date: formData.start_date.format('YYYY-MM-DD'),
      end_date: formData.end_date.format('YYYY-MM-DD'),
      travel_days: formData.travel_days,
      transportation: formData.transportation,
      accommodation: formData.accommodation,
      preferences: formData.preferences,
      free_text_input: formData.free_text_input
    }

    const payload = {
      location: requestData.city,
      days: requestData.travel_days,
      preferences: [...requestData.preferences, requestData.free_text_input].filter(Boolean).join('/'),
      start_date: requestData.start_date,
      end_date: requestData.end_date,
      transportation: requestData.transportation,
      accommodation: requestData.accommodation,
    }

    await streamTravelPlanByLocation(payload, {
      onProgress: (percent, status) => {
        loadingProgress.value = percent
        loadingStatus.value = status
        pushUiLog(formatLoadingLog({ type: 'progress', percent, status }))
      },
      onStage: (stage) => {
        currentStage.value = stage
      },
      onLog: (msg) => {
        pushUiLog(formatLoadingLog({ type: 'log', message: msg }) ?? null)
        if (msg.includes('反思结果无效，已回退到初稿')) {
          reflectionFallbackMessage.value = msg
          updateStepStatus('reflection', 'error')
        }
      },
      onStep: ({ name, status }) => {
        updateStepStatus(name, status)
        pushUiLog(formatLoadingLog({ type: 'step', name, status }))
      },
      onDone: (response) => {
        currentStage.value = 'done'
        loadingProgress.value = 100
        loadingStatus.value = '✅ 生成完成'
        pushUiLog(formatLoadingLog({ type: 'done', resultId: (response as any)?.result_id }))

        if (!response.success || !response.data) {
          message.error(response.message || '生成失败')
          return
        }

        sessionStorage.setItem('tripPlan', JSON.stringify(response.data))
        const resultId = (response.data as any)?.result_id || (response as any)?.result_id
        message.success('旅行计划生成成功!')

        ;(async () => {
          navigating.value = true
          await hideOverlay()
          if (resultId) router.push(`/result/${resultId}`)
          else router.push('/result/fallback')
        })()
      },
      onError: (msg) => {
        pushUiLog(formatLoadingLog({ type: 'error', message: msg || '生成失败' }))
        message.error(msg || '生成旅行计划失败，请稍后重试')
      },
    }, { signal: abortController.value.signal })
  } catch (error: any) {
    const aborted = error?.name === 'AbortError' || String(error?.message || '').toLowerCase().includes('aborted')
    if (!aborted) message.error(error.message || '生成旅行计划失败,请稍后重试')
  } finally {
    loading.value = false
    streamConnected.value = false
    abortController.value = null
    if (!navigating.value && fullscreenVisible.value) {
      void hideOverlay()
    }
  }
}

const handleCancel = async () => {
  if (!loading.value) return
  try {
    abortController.value?.abort()
  } catch {}
  navigating.value = false
  loadingStatus.value = '已取消'
  currentStage.value = 'cancelled'
  pushUiLog('已取消生成')
  await hideOverlay()
  loading.value = false
  loadingProgress.value = 0
  loadingStatus.value = ''
  streamConnected.value = false
  abortController.value = null
}

const handleDebugSubmit = async () => {
  if (loading.value) return

  const debugRequest: TripFormData = {
    city: '法国',
    start_date: '2026-04-08',
    end_date: '2026-04-09',
    travel_days: 2,
    transportation: formData.transportation || '公共交通',
    accommodation: formData.accommodation || '经济型酒店',
    preferences: formData.preferences?.length ? formData.preferences : ['历史文化'],
    free_text_input: '调试模式：请基于 mapbox 工具返回真实可执行的 2 天游玩安排。'
  }

  loading.value = true
  navigating.value = false
  currentStage.value = 'connecting'
  loadingProgress.value = 0
  loadingStatus.value = '正在连接生成服务...'

  liveLogs.value = []
  streamConnected.value = true
  resetStepStatus()
  abortController.value = new AbortController()
  pushUiLog('调试模式：开始生成示例行程')
  await showOverlay()

  try {
    await streamTravelPlanByLocation({
      location: debugRequest.city,
      days: debugRequest.travel_days,
      preferences: debugRequest.preferences.join('/'),
      start_date: debugRequest.start_date,
      end_date: debugRequest.end_date,
      transportation: debugRequest.transportation,
      accommodation: debugRequest.accommodation,
    }, {
      onProgress: (percent, status) => {
        loadingProgress.value = percent
        loadingStatus.value = status
        pushUiLog(formatLoadingLog({ type: 'progress', percent, status }))
      },
      onStage: (stage) => {
        currentStage.value = stage
      },
      onLog: (msg) => {
        pushUiLog(formatLoadingLog({ type: 'log', message: msg }) ?? null)
        if (msg.includes('反思结果无效，已回退到初稿')) {
          reflectionFallbackMessage.value = msg
          updateStepStatus('reflection', 'error')
        }
      },
      onStep: ({ name, status }) => {
        updateStepStatus(name, status)
        pushUiLog(formatLoadingLog({ type: 'step', name, status }))
      },
      onDone: (response) => {
        currentStage.value = 'done'
        loadingProgress.value = 100
        loadingStatus.value = '✅ 生成完成'
        pushUiLog(formatLoadingLog({ type: 'done', resultId: (response as any)?.result_id }))
        if (response.success && response.data) {
          sessionStorage.setItem('tripPlan', JSON.stringify(response.data))
          const resultId = (response.data as any)?.result_id || (response as any)?.result_id
          message.success('调试规划成功（法国行程）')
          ;(async () => {
            navigating.value = true
            await hideOverlay()
            if (resultId) router.push(`/result/${resultId}`)
            else router.push('/result/fallback')
          })()
        } else {
          message.error(response.message || '调试规划失败')
        }
      },
      onError: (msg) => {
        pushUiLog(formatLoadingLog({ type: 'error', message: msg || '调试失败' }))
        message.error(msg || '调试规划失败，请稍后重试')
      },
    }, { signal: abortController.value.signal })
  } catch (error: any) {
    const aborted = error?.name === 'AbortError' || String(error?.message || '').toLowerCase().includes('aborted')
    if (!aborted) message.error(error.message || '调试规划失败,请稍后重试')
  } finally {
    loading.value = false
    streamConnected.value = false
    abortController.value = null
    if (!navigating.value && fullscreenVisible.value) {
      void hideOverlay()
    }
  }
}
</script>

<style scoped>
.home-container {
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 60px 20px;
  position: relative;
  overflow: hidden;
}

/* 背景装饰 */
.bg-decoration {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  overflow: hidden;
}

.circle {
  position: absolute;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.1);
  animation: float 20s infinite ease-in-out;
}

.circle-1 {
  width: 300px;
  height: 300px;
  top: -100px;
  left: -100px;
  animation-delay: 0s;
}

.circle-2 {
  width: 200px;
  height: 200px;
  top: 50%;
  right: -50px;
  animation-delay: 5s;
}

.circle-3 {
  width: 150px;
  height: 150px;
  bottom: -50px;
  left: 30%;
  animation-delay: 10s;
}

@keyframes float {
  0%, 100% {
    transform: translateY(0) rotate(0deg);
  }
  50% {
    transform: translateY(-30px) rotate(180deg);
  }
}

/* 页面标题 */
.page-header {
  text-align: center;
  margin-bottom: 50px;
  animation: fadeInDown 0.8s ease-out;
  position: relative;
  z-index: 1;
}

.icon-wrapper {
  margin-bottom: 20px;
}

.icon {
  font-size: 80px;
  display: inline-block;
  animation: bounce 2s infinite;
}

@keyframes bounce {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-20px);
  }
}

.page-title {
  font-size: 56px;
  font-weight: 800;
  color: #ffffff;
  margin-bottom: 16px;
  text-shadow: 3px 3px 6px rgba(0, 0, 0, 0.3);
  letter-spacing: 2px;
}

.page-subtitle {
  font-size: 20px;
  color: rgba(255, 255, 255, 0.95);
  margin: 0;
  font-weight: 300;
}

/* 表单卡片 */
.form-card {
  max-width: 1400px;
  margin: 0 auto;
  border-radius: 24px;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.4);
  animation: fadeInUp 0.8s ease-out;
  position: relative;
  z-index: 1;
  backdrop-filter: blur(10px);
  background: rgba(255, 255, 255, 0.98) !important;
}

/* 表单分区 */
.form-section {
  margin-bottom: 32px;
  padding: 24px;
  background: linear-gradient(135deg, #f5f7fa 0%, #ffffff 100%);
  border-radius: 16px;
  border: 1px solid #e8e8e8;
  transition: all 0.3s ease;
}

.form-section:hover {
  box-shadow: 0 8px 24px rgba(102, 126, 234, 0.15);
  transform: translateY(-2px);
}

.section-header {
  display: flex;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 2px solid #667eea;
}

.section-icon {
  font-size: 24px;
  margin-right: 12px;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  color: #333;
}

/* 表单标签 */
.form-label {
  font-size: 15px;
  font-weight: 500;
  color: #555;
}

/* 自定义输入框 */
.custom-input :deep(.ant-input),
.custom-input :deep(.ant-picker) {
  border-radius: 12px;
  border: 2px solid #e8e8e8;
  transition: all 0.3s ease;
}

.custom-input :deep(.ant-input:hover),
.custom-input :deep(.ant-picker:hover) {
  border-color: #667eea;
}

.custom-input :deep(.ant-input:focus),
.custom-input :deep(.ant-picker-focused) {
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

/* 自定义选择框 */
.custom-select :deep(.ant-select-selector) {
  border-radius: 12px !important;
  border: 2px solid #e8e8e8 !important;
  transition: all 0.3s ease;
}

.custom-select:hover :deep(.ant-select-selector) {
  border-color: #667eea !important;
}

.custom-select :deep(.ant-select-focused .ant-select-selector) {
  border-color: #667eea !important;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1) !important;
}

/* 天数显示 - 紧凑版 */
.days-display-compact {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 40px;
  padding: 8px 16px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 12px;
  color: white;
}

.days-display-compact .days-value {
  font-size: 24px;
  font-weight: 700;
  margin-right: 4px;
}

.days-display-compact .days-unit {
  font-size: 14px;
}

/* 偏好标签 */
.preference-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.custom-checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  width: 100%;
}

.preference-tag :deep(.ant-checkbox-wrapper) {
  margin: 0 !important;
  padding: 8px 16px;
  border: 2px solid #e8e8e8;
  border-radius: 20px;
  transition: all 0.3s ease;
  background: white;
  font-size: 14px;
}

.preference-tag :deep(.ant-checkbox-wrapper:hover) {
  border-color: #667eea;
  background: #f5f7ff;
}

.preference-tag :deep(.ant-checkbox-wrapper-checked) {
  border-color: #667eea;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

/* 自定义文本域 */
.custom-textarea :deep(.ant-input) {
  border-radius: 12px;
  border: 2px solid #e8e8e8;
  transition: all 0.3s ease;
}

.custom-textarea :deep(.ant-input:hover) {
  border-color: #667eea;
}

.custom-textarea :deep(.ant-input:focus) {
  border-color: #667eea;
  box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
}

/* 提交按钮 */
.submit-button {
  height: 56px;
  border-radius: 28px;
  font-size: 18px;
  font-weight: 600;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border: none;
  box-shadow: 0 8px 24px rgba(102, 126, 234, 0.4);
  transition: all 0.3s ease;
  flex: 1;
}

.submit-button:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 32px rgba(102, 126, 234, 0.5);
}

.submit-button:active {
  transform: translateY(0);
}

.button-icon {
  margin-right: 8px;
  font-size: 20px;
}

.action-buttons {
  display: flex;
  gap: 12px;
}

.debug-button {
  height: 56px;
  border-radius: 28px;
  padding: 0 24px;
  font-size: 16px;
  font-weight: 600;
}

/* 加载容器 */
.loading-container {
  text-align: center;
  padding: 24px;
  background: linear-gradient(135deg, #f5f7fa 0%, #ffffff 100%);
  border-radius: 16px;
  border: 2px dashed #667eea;
}

.loading-status {
  margin-top: 16px;
  color: #667eea;
  font-size: 18px;
  font-weight: 500;
}

/* 动画 */
@keyframes fadeInDown {
  from {
    opacity: 0;
    transform: translateY(-30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
/* =========================
   Mobile-first visual refresh
   ========================= */
.home-container {
  padding: 24px 14px 40px;
  background:
    radial-gradient(circle at top left, rgba(255, 255, 255, 0.22), transparent 34%),
    radial-gradient(circle at bottom right, rgba(255, 255, 255, 0.14), transparent 28%),
    linear-gradient(160deg, #5b7cfa 0%, #6f4fd8 48%, #1f2937 100%);
}

.page-header {
  margin-bottom: 22px;
  padding: 8px 0 0;
}

.icon-wrapper {
  margin-bottom: 12px;
}

.icon {
  font-size: 60px;
}

.page-title {
  font-size: clamp(34px, 8vw, 48px);
  letter-spacing: 0.02em;
  margin-bottom: 8px;
  color: #fff;
}

.page-subtitle {
  max-width: 28rem;
  margin: 0 auto;
  font-size: 14px;
  line-height: 1.65;
  color: rgba(255, 255, 255, 0.86);
}

.form-card {
  border-radius: 24px;
  overflow: hidden;
  box-shadow: 0 20px 60px rgba(15, 23, 42, 0.24);
  backdrop-filter: blur(10px);
}

.form-card :deep(.ant-card-body) {
  padding: 18px 16px 8px;
}

.form-section {
  margin-bottom: 16px;
  padding: 16px;
  border-radius: 20px;
  background: linear-gradient(180deg, rgba(248, 250, 252, 0.92), rgba(255, 255, 255, 0.98));
  border: 1px solid rgba(148, 163, 184, 0.18);
}

.section-header {
  margin-bottom: 12px;
}

.section-title {
  font-size: 15px;
}

.form-label {
  font-size: 13px;
  color: #334155;
}

.custom-input,
.custom-select,
.custom-textarea {
  border-radius: 14px !important;
}

.action-buttons {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.submit-button,
.debug-button {
  width: 100%;
  height: 48px;
  border-radius: 14px;
  font-weight: 600;
}

.submit-button {
  background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%);
  border: none;
  box-shadow: 0 12px 26px rgba(37, 99, 235, 0.24);
}

.debug-button {
  background: rgba(255, 255, 255, 0.92);
}

.loading-container {
  padding: 14px;
  border-radius: 16px;
  background: rgba(15, 23, 42, 0.04);
}

.loading-status {
  margin: 10px 0 0;
  font-size: 13px;
  color: #475569;
}

.stream-badge-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.step-status-panel {
  margin-top: 10px;
  padding: 10px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.72);
}

.step-status-title {
  font-size: 13px;
  color: #334155;
  font-weight: 600;
  margin-bottom: 6px;
}

.step-status-list {
  display: grid;
  gap: 6px;
}

.step-status-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.step-name {
  font-size: 12px;
  color: #475569;
}

.reflection-fallback {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.5;
  color: #b91c1c;
}

.live-panel {
  max-height: 180px;
  overflow: auto;
  padding: 10px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.7);
}

.live-debug-panel {
  background: rgba(15, 23, 42, 0.04);
}

.live-log-item {
  font-size: 12px;
  line-height: 1.55;
  color: #334155;
  margin-bottom: 8px;
  word-break: break-word;
}

@media (min-width: 768px) {
  .home-container {
    padding: 56px 24px 64px;
  }

  .page-header {
    margin-bottom: 36px;
  }

  .page-subtitle {
    font-size: 16px;
  }

  .form-card :deep(.ant-card-body) {
    padding: 28px 28px 12px;
  }

  .form-section {
    padding: 20px;
    margin-bottom: 20px;
  }

  .mobile-stack-row {
    flex-wrap: nowrap;
  }

  .action-buttons {
    flex-direction: row;
    align-items: center;
  }

  .submit-button,
  .debug-button {
    width: auto;
    min-width: 220px;
  }

  .loading-container {
    padding: 18px;
  }

  .live-panel {
    max-height: 220px;
  }
}

@media (max-width: 767px) {
  .bg-decoration .circle-1,
  .bg-decoration .circle-2,
  .bg-decoration .circle-3 {
    opacity: 0.45;
    filter: blur(6px);
  }

  .page-header {
    text-align: left;
  }

  .icon-wrapper {
    margin-bottom: 8px;
  }

  .form-card {
    border-radius: 20px;
  }

  .mobile-stack-row {
    display: flex;
    flex-wrap: wrap;
  }

  .mobile-stack-row :deep(.ant-col) {
    flex: 0 0 100% !important;
    max-width: 100% !important;
  }

  .days-display-compact {
    padding: 10px 12px;
    border-radius: 14px;
    background: rgba(37, 99, 235, 0.08);
  }

  .preference-tags {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  .preference-tag {
    margin: 0 !important;
    padding: 6px 8px;
    border-radius: 999px;
    background: rgba(255, 255, 255, 0.9);
    border: 1px solid rgba(148, 163, 184, 0.18);
  }

  .custom-checkbox-group {
    display: contents;
  }
}
</style>

