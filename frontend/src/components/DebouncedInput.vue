<template>
  <el-input v-bind="$attrs" :model-value="modelValue" @input="onInput" @clear="onClear">
    <template v-if="$slots.prefix" #prefix>
      <slot name="prefix" />
    </template>
  </el-input>
</template>

<script setup>
// 搜索防抖输入框：输入停止 delay 毫秒后派发 debounce 事件
// 清空时立即派发空串，组件卸载时清理未触发的定时器
import { onBeforeUnmount } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  delay: { type: Number, default: 300 },
})

const emit = defineEmits(['update:modelValue', 'debounce'])

let timer = null

function onInput(val) {
  emit('update:modelValue', val)
  clearTimeout(timer)
  timer = setTimeout(() => emit('debounce', val), props.delay)
}

function onClear() {
  clearTimeout(timer)
  emit('debounce', '')
}

onBeforeUnmount(() => clearTimeout(timer))
</script>
