<template>
  <div class="state-block" :class="`state-block--${state}`">
    <template v-if="state === 'loading'">
      <slot>
        <SkeletonCard :rows="3" />
      </slot>
    </template>

    <template v-else>
      <svg
        v-if="state === 'empty'"
        class="state-block__art"
        viewBox="0 0 96 72"
        fill="none"
        aria-hidden="true"
      >
        <rect x="10" y="12" width="52" height="48" rx="6" stroke="currentColor" stroke-width="2" />
        <path d="M22 26h28M22 36h28M22 46h18" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
        <circle cx="72" cy="48" r="14" fill="var(--bg-subtle)" stroke="currentColor" stroke-width="2" />
        <path d="M72 41v8M72 54v.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
      </svg>
      <el-icon v-else class="state-block__icon"><WarningFilled /></el-icon>

      <h3 class="state-block__title">{{ resolvedTitle }}</h3>
      <p v-if="resolvedHint" class="state-block__hint">{{ resolvedHint }}</p>

      <el-button
        v-if="actionLabel"
        type="primary"
        plain
        @click="$emit('retry')"
      >
        {{ actionLabel }}
      </el-button>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { WarningFilled } from '@element-plus/icons-vue'
import SkeletonCard from './SkeletonCard.vue'

const props = defineProps({
  state: {
    type: String,
    default: 'empty',
    validator: (value) => ['empty', 'error', 'loading'].includes(value),
  },
  title: { type: String, default: '' },
  hint: { type: String, default: '' },
  actionLabel: { type: String, default: '' },
})

defineEmits(['retry'])

const DEFAULTS = {
  empty: { title: '暂无数据', hint: '' },
  error: { title: '加载失败', hint: '请检查网络后重试' },
  loading: { title: '', hint: '' },
}

const resolvedTitle = computed(() => props.title || DEFAULTS[props.state].title)
const resolvedHint = computed(() => props.hint || DEFAULTS[props.state].hint)
</script>

<style scoped>
.state-block {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-3);
  padding: var(--sp-8) var(--sp-5);
  text-align: center;
  color: var(--text-secondary);
}

.state-block--loading {
  display: block;
  padding: 0;
}

.state-block__art {
  width: 96px;
  height: 72px;
  color: var(--brand-300);
}

.state-block__icon {
  font-size: 34px;
  color: var(--color-warning);
}

.state-block__title {
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-primary);
}

.state-block__hint {
  max-width: 420px;
  font-size: var(--fs-sm);
  color: var(--text-placeholder);
  line-height: var(--lh-base);
}
</style>
