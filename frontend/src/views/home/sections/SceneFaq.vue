<template>
  <section id="faq" class="hp-section">
    <div class="hp-container">
      <header class="hp-section-head">
        <p class="hp-eyebrow">一学期的大概样子</p>
        <h2 class="hp-title">开学、学期中、期末</h2>
        <p class="hp-desc">不用先学一套新流程，原来怎么上课，还怎么上。</p>
      </header>

      <div class="scenes">
        <article v-for="(scene, index) in scenes" :key="scene.title" class="scene">
          <span class="scene__index">0{{ index + 1 }}</span>
          <h3 class="scene__title">{{ scene.title }}</h3>
          <ol class="scene__steps">
            <li v-for="(step, i) in scene.steps" :key="step">
              <span>{{ i + 1 }}</span>
              {{ step }}
            </li>
          </ol>
        </article>
      </div>

      <div class="faq">
        <header class="faq__head">
          <h2 class="hp-title">常见问题</h2>
          <p class="hp-desc">大家问得最多的几个问题。</p>
        </header>

        <div class="faq__list">
          <details v-for="item in faqs" :key="item.q" class="faq__item">
            <summary>
              <span>{{ item.q }}</span>
              <el-icon class="faq__chevron"><ArrowRight /></el-icon>
            </summary>
            <p>{{ item.a }}</p>
          </details>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { scenes, faqs } from '../content'
</script>

<style scoped>
.scenes {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--sp-4);
}

.scene {
  padding: var(--sp-5) var(--sp-6);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
}

.scene__index {
  font-family: var(--font-serif);
  font-size: var(--fs-xs);
  letter-spacing: 0.1em;
  color: var(--color-accent);
}

.scene__title {
  margin-top: var(--sp-2);
  font-size: var(--fs-md);
  font-weight: 600;
}

.scene__steps {
  list-style: none;
  margin-top: var(--sp-4);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.scene__steps li {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
  line-height: 1.7;
  color: var(--text-secondary);
}

.scene__steps span {
  flex: none;
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  margin-top: 2px;
  border-radius: 50%;
  background: var(--bg-subtle);
  color: var(--text-secondary);
  font-size: 10px;
}

/* ===== FAQ ===== */
.faq {
  display: grid;
  grid-template-columns: minmax(0, 4fr) minmax(0, 8fr);
  gap: var(--sp-8);
  margin-top: 88px;
  padding-top: var(--sp-8);
  border-top: 1px solid var(--border);
}

.faq__head .hp-title {
  font-size: var(--fs-xl);
}

.faq__list {
  border-top: 1px solid var(--border);
}

.faq__item {
  border-bottom: 1px solid var(--border);
}

.faq__item summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  padding: var(--sp-4) 0;
  cursor: pointer;
  font-size: var(--fs-base);
  font-weight: 600;
  color: var(--text-primary);
  list-style: none;
}

.faq__item summary::-webkit-details-marker {
  display: none;
}

.faq__item summary:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.faq__chevron {
  flex: none;
  font-size: 13px;
  color: var(--text-placeholder);
  transition: transform var(--dur) var(--ease);
}

.faq__item[open] .faq__chevron {
  transform: rotate(90deg);
  color: var(--color-primary);
}

.faq__item p {
  padding: 0 var(--sp-6) var(--sp-4) 0;
  font-size: var(--fs-sm);
  line-height: 1.85;
  color: var(--text-secondary);
}

@media (max-width: 1024px) {
  .faq {
    grid-template-columns: 1fr;
    gap: var(--sp-5);
    margin-top: 64px;
  }
}

@media (max-width: 767px) {
  .scenes {
    grid-template-columns: 1fr;
  }

  .faq {
    margin-top: 48px;
  }
}
</style>
