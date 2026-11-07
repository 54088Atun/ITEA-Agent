<template>
  <div class="skeleton-card" role="status" aria-live="polite" aria-label="内容加载中">
    <span class="skeleton-card__avatar" />
    <div class="skeleton-card__body">
      <span class="skeleton-bar skeleton-bar--title" />
      <span
        v-for="r in rows"
        :key="r"
        class="skeleton-bar"
        :style="{ width: lineWidth(r) }"
      />
    </div>
  </div>
</template>

<script setup>
defineProps({
  rows: { type: Number, default: 3 },
})

const WIDTHS = ['96%', '88%', '72%', '60%']
const lineWidth = (index) => WIDTHS[(index - 1) % WIDTHS.length]
</script>

<style scoped>
.skeleton-card {
  display: flex;
  gap: var(--sp-4);
  padding: var(--sp-5);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--bg-card);
  box-shadow: var(--shadow-xs);
}

.skeleton-card__avatar {
  flex: none;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--bg-subtle);
}

.skeleton-card__body {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: var(--sp-3);
  padding-top: 4px;
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

.skeleton-bar--title {
  width: 42%;
  height: 16px;
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
