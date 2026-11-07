<template>
  <span class="count-up">{{ display }}</span>
</template>

<script setup>
// 数字滚动微交互：值变化时从当前值缓动到目标值
// 尊重 prefers-reduced-motion，开启时直接渲染终值
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  value: { type: Number, default: 0 },
  duration: { type: Number, default: 800 },
})

const display = ref('0')
const current = ref(0)
let raf = 0

const reduced = typeof window !== 'undefined'
  && typeof window.matchMedia === 'function'
  && window.matchMedia('(prefers-reduced-motion: reduce)').matches

function format(n) {
  return String(Math.round(n))
}

function animate(to) {
  cancelAnimationFrame(raf)
  const target = Number(to) || 0
  if (reduced || props.duration <= 0) {
    current.value = target
    display.value = format(target)
    return
  }
  const begin = current.value
  const delta = target - begin
  if (!delta) {
    display.value = format(target)
    return
  }
  const start = performance.now()
  const step = (now) => {
    const t = Math.min(1, (now - start) / props.duration)
    const eased = 1 - Math.pow(1 - t, 3)
    current.value = begin + delta * eased
    display.value = format(current.value)
    if (t < 1) {
      raf = requestAnimationFrame(step)
    } else {
      current.value = target
      display.value = format(target)
    }
  }
  raf = requestAnimationFrame(step)
}

onMounted(() => animate(props.value))
watch(() => props.value, (v) => animate(v))
onBeforeUnmount(() => cancelAnimationFrame(raf))
</script>
