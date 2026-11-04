<template>
  <section id="capabilities" class="hp-section">
    <div class="hp-container">
      <header class="hp-section-head">
        <p class="hp-eyebrow">功能</p>
        <h2 class="hp-title">平时用得最多的六件事</h2>
        <p class="hp-desc">不贪多。把老师每周都要做的事做顺，比堆一屏功能有用。</p>
      </header>

      <div class="caps">
        <article v-for="cap in capabilities" :key="cap.title" class="cap">
          <div class="cap__top">
            <span class="cap__icon">
              <el-icon><component :is="cap.icon" /></el-icon>
            </span>
            <span class="cap__tag">{{ cap.tag }}</span>
          </div>
          <h3 class="cap__title">{{ cap.title }}</h3>
          <p class="cap__desc">{{ cap.desc }}</p>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup>
import { capabilities } from '../content'
</script>

<style scoped>
.caps {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--sp-4);
}

.cap {
  position: relative;
  overflow: hidden;
  padding: var(--sp-6);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  transition: transform var(--dur) var(--ease-out), box-shadow var(--dur) var(--ease),
    border-color var(--dur) var(--ease);
}

/* 顶部渐变细线：hover 时出现，呼应工作台 KPI 卡 */
.cap::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 3px;
  background: var(--grad-brand);
  opacity: 0;
  transition: opacity var(--dur) var(--ease);
}

.cap:hover::before {
  opacity: 1;
}

.cap:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--brand-300);
}

.cap__top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
}

.cap__icon {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: var(--r-sm);
  background: var(--color-primary-soft);
  color: var(--color-primary-active);
  font-size: 18px;
}

.cap__tag {
  padding: 2px 8px;
  border-radius: var(--r-pill);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  font-size: 11px;
  color: var(--text-secondary);
}

.cap__title {
  margin-top: var(--sp-4);
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-primary);
}

.cap__desc {
  margin-top: var(--sp-2);
  font-size: var(--fs-sm);
  line-height: 1.75;
  color: var(--text-secondary);
}

@media (max-width: 1024px) {
  .caps {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 767px) {
  .caps {
    grid-template-columns: 1fr;
  }
}
</style>
