<template>
  <section class="facts" aria-label="平台能力事实">
    <div class="hp-container">
      <ul class="facts__grid">
        <li v-for="item in facts" :key="item.label" class="facts__item">
          <div class="facts__value">
            {{ item.value }}<span v-if="item.unit">{{ item.unit }}</span>
          </div>
          <div class="facts__label">{{ item.label }}</div>
          <div class="facts__hint">{{ item.hint }}</div>
        </li>
      </ul>
    </div>
  </section>
</template>

<script setup>
import { facts } from '../content'
</script>

<style scoped>
.facts {
  padding: var(--sp-7) 0;
  background: var(--bg-subtle);
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}

.facts__grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--sp-6);
  list-style: none;
}

.facts__item {
  position: relative;
  padding-left: var(--sp-4);
}

.facts__item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 4px;
  bottom: 4px;
  width: 2px;
  border-radius: var(--r-pill);
  background: var(--grad-accent);
  opacity: 0.6;
}

.facts__value {
  font-family: var(--font-serif);
  font-size: var(--fs-3xl);
  font-weight: 600;
  line-height: 1.1;
  color: var(--text-primary);
}

.facts__value span {
  margin-left: 2px;
  font-size: var(--fs-md);
  font-weight: 400;
  color: var(--text-secondary);
}

.facts__label {
  margin-top: var(--sp-2);
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-primary);
}

.facts__hint {
  margin-top: 2px;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

@media (max-width: 960px) {
  .facts__grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--sp-5);
  }

  .facts__value {
    font-size: var(--fs-2xl);
  }
}
</style>
