import { onBeforeUnmount, ref } from 'vue'

interface UsePosterAutoplayOptions {
  initialDelayMs?: number
  intervalMs?: number
  loop?: boolean
}

export function usePosterAutoplay(options: UsePosterAutoplayOptions = {}) {
  const initialDelayMs = options.initialDelayMs ?? 300
  const intervalMs = options.intervalMs ?? 3400
  const loop = options.loop ?? true

  const running = ref(false)
  const paused = ref(false)
  const currentIndex = ref(0)
  const total = ref(0)

  let startTimer: ReturnType<typeof setTimeout> | null = null
  let loopTimer: ReturnType<typeof setInterval> | null = null

  const clearTimers = () => {
    if (startTimer) clearTimeout(startTimer)
    if (loopTimer) clearInterval(loopTimer)
    startTimer = null
    loopTimer = null
  }

  const stop = () => {
    clearTimers()
    running.value = false
    paused.value = false
  }

  const tick = (onFrame: (nextIndex: number) => void) => {
    if (paused.value || total.value <= 1) return
    const isLast = currentIndex.value >= total.value - 1
    if (isLast && !loop) {
      stop()
      return
    }
    currentIndex.value = isLast ? 0 : currentIndex.value + 1
    onFrame(currentIndex.value)
  }

  const start = (onFrame: (nextIndex: number) => void) => {
    stop()
    if (total.value <= 1) return
    running.value = true
    paused.value = false
    startTimer = setTimeout(() => {
      onFrame(currentIndex.value)
      loopTimer = setInterval(() => tick(onFrame), intervalMs)
    }, initialDelayMs)
  }

  const pause = () => {
    if (!running.value) return
    paused.value = true
  }

  const resume = () => {
    if (!running.value) return
    paused.value = false
  }

  const setFrameTotal = (count: number) => {
    total.value = Math.max(0, count)
    currentIndex.value = Math.min(currentIndex.value, Math.max(0, total.value - 1))
  }

  const setCurrentIndex = (index: number) => {
    currentIndex.value = Math.max(0, Math.min(index, Math.max(0, total.value - 1)))
  }

  onBeforeUnmount(stop)

  return {
    running,
    paused,
    currentIndex,
    total,
    start,
    stop,
    pause,
    resume,
    setFrameTotal,
    setCurrentIndex,
  }
}
