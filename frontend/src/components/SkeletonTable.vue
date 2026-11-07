<template>
  <div
    class="skeleton-table"
    role="status"
    aria-live="polite"
    aria-label="列表加载中"
  >
    <div
      class="skeleton-table__row skeleton-table__row--head"
      :style="gridStyle"
    >
      <span
        v-for="c in cols"
        :key="`h-${c}`"
        class="skeleton-bar skeleton-bar--head"
        :style="{ width: widthOf(c) }"
      />
    </div>
    <div
      v-for="r in rows"
      :key="r"
      class="skeleton-table__row"
      :style="gridStyle"
    >
      <span
        v-for="c in cols"
        :key="`${r}-${c}`"
        class="skeleton-bar"
        :style="{ width: widthOf(c) }"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  rows: { type: Number, default: 6 },
  cols: { type: Number, default: 4 },
})

const gridStyle = computed(() => ({
  gridTemplateColumns: `repeat(${props.cols}, minmax(0, 1fr))`,
}))

const WIDTHS = ['92%', '76%', '86%', '64%', '72%', '58%']
const widthOf = (index) => WIDTHS[(index - 1) % WIDTHS.length]
</script>

<style scoped>
.skeleton-table {
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--bg-card);
}

.skeleton-table__row {
  display: grid;
  gap: var(--sp-5);
  align-items: center;
  min-height: 48px;
  padding: var(--sp-3) var(--sp-5);
  border-top: 1px solid var(--border);
}

.skeleton-table__row--head {
  min-height: 42px;
  border-top: none;
  background: var(--bg-subtle);
}

.skeleton-bar {
  display: block;
  height: 12px;
  border-radius: var(--r-pill);
  background: linear-gradient(
    90deg,
    var(--bg-subtle) 25%,
    var(--line-100) 37%,
    var(--bg-subtle) 63%
  );
  background-size: 400% 100%;
  animation: skeleton-shimmer 1.4s ease infinite;
}

.skeleton-bar--head {
  height: 10px;
  opacity: 0.75;
}

@keyframes skeleton-shimmer {
  0% { background-position: 100% 50%; }
  100% { background-position: 0 50%; }
}

@media (prefers-reduced-motion: reduce) {
  .skeleton-bar {
    animation: none;
  }
}
</style>
