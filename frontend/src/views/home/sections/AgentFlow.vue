<template>
  <section id="flow" class="hp-section flow">
    <div class="hp-container">
      <header class="hp-section-head">
        <p class="hp-eyebrow">助教怎么工作</p>
        <h2 class="hp-title">{{ flow.title }}</h2>
        <p class="hp-desc">{{ flow.desc }}</p>
      </header>

      <div class="flow__layout">
        <div class="flow__steps" role="tablist" aria-label="助教工作步骤">
          <button
            v-for="(step, index) in flow.steps"
            :id="`flow-tab-${step.key}`"
            :key="step.key"
            type="button"
            role="tab"
            :aria-selected="active === index"
            :aria-controls="`flow-panel-${step.key}`"
            :tabindex="active === index ? 0 : -1"
            :class="['step', { 'step--active': active === index }]"
            @click="active = index"
            @keydown.right.prevent="move(index, 1)"
            @keydown.left.prevent="move(index, -1)"
            @keydown.home.prevent="active = 0"
            @keydown.end.prevent="active = flow.steps.length - 1"
          >
            <span class="step__index">{{ step.index }}</span>
            <span class="step__body">
              <span class="step__title">{{ step.title }}</span>
              <span class="step__summary">{{ step.summary }}</span>
            </span>
            <el-icon class="step__icon"><component :is="step.icon" /></el-icon>
          </button>
        </div>

        <div
          v-for="(step, index) in flow.steps"
          v-show="active === index"
          :id="`flow-panel-${step.key}`"
          :key="`panel-${step.key}`"
          class="flow__panel"
          role="tabpanel"
          :aria-labelledby="`flow-tab-${step.key}`"
          tabindex="0"
        >
          <div class="flow__panel-head">
            <span class="flow__panel-index">{{ step.index }}</span>
            <div>
              <h3>{{ step.title }}</h3>
              <p>{{ step.summary }}</p>
            </div>
          </div>

          <p class="flow__detail">{{ step.detail }}</p>

          <div class="flow__sample">
            <span class="flow__sample-label">示例</span>
            <p>{{ step.sample }}</p>
          </div>

          <div class="flow__progress" aria-hidden="true">
            <span
              v-for="(item, i) in flow.steps"
              :key="item.key"
              :class="['flow__progress-dot', { 'is-on': i <= index }]"
            ></span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref } from 'vue'
import { flow } from '../content'

const active = ref(0)

function move(index, delta) {
  const next = (index + delta + flow.steps.length) % flow.steps.length
  active.value = next
}
</script>

<style scoped>
.flow {
  background: var(--bg-subtle);
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}

.flow__layout {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: var(--sp-6);
  align-items: start;
}

/* ===== 左侧步骤 ===== */
.flow__steps {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.step {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  width: 100%;
  padding: var(--sp-4);
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-md);
  cursor: pointer;
  transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease);
}

.step:hover {
  background: var(--bg-card);
  border-color: var(--border);
}

.step:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.step--active {
  background: var(--bg-card);
  border-color: var(--brand-300);
  box-shadow: var(--shadow-sm);
}

.step__index {
  flex: none;
  font-family: var(--font-serif);
  font-size: var(--fs-sm);
  letter-spacing: 0.08em;
  color: var(--text-placeholder);
}

.step--active .step__index {
  color: var(--color-accent);
}

.step__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.step__title {
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-primary);
}

.step__summary {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

.step__icon {
  margin-left: auto;
  flex: none;
  font-size: 18px;
  color: var(--text-placeholder);
  transition: color var(--dur) var(--ease);
}

.step--active .step__icon {
  color: var(--color-primary);
}

/* ===== 右侧详情 ===== */
.flow__panel {
  min-height: 268px;
  padding: var(--sp-7);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-sm);
  animation: panel-in var(--dur) var(--ease-out) both;
}

.flow__panel:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

@keyframes panel-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: none; }
}

.flow__panel-head {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-4);
}

.flow__panel-index {
  font-family: var(--font-serif);
  font-size: var(--fs-3xl);
  font-weight: 600;
  line-height: 1;
  color: var(--brand-300);
}

.flow__panel-head h3 {
  font-family: var(--font-serif);
  font-size: var(--fs-xl);
  font-weight: 600;
}

.flow__panel-head p {
  margin-top: 4px;
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.flow__detail {
  margin-top: var(--sp-5);
  font-size: var(--fs-base);
  line-height: 1.85;
  color: var(--text-primary);
}

.flow__sample {
  margin-top: var(--sp-5);
  padding: var(--sp-3) var(--sp-4);
  background: var(--brand-50);
  border-left: 3px solid var(--brand-300);
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
}

.flow__sample-label {
  display: block;
  font-size: var(--fs-xs);
  letter-spacing: 0.12em;
  color: var(--color-accent);
}

.flow__sample p {
  margin-top: 4px;
  font-size: var(--fs-sm);
  line-height: 1.7;
  color: var(--text-primary);
}

.flow__progress {
  display: flex;
  gap: 6px;
  margin-top: var(--sp-6);
}

.flow__progress-dot {
  width: 22px;
  height: 3px;
  border-radius: var(--r-pill);
  background: var(--line-200);
  transition: background var(--dur) var(--ease);
}

.flow__progress-dot.is-on {
  background: var(--color-primary);
}

@media (max-width: 960px) {
  .flow__layout {
    grid-template-columns: 1fr;
  }

  .flow__panel {
    min-height: 0;
    padding: var(--sp-6);
  }
}

@media (max-width: 767px) {
  .step {
    padding: var(--sp-3);
  }

  .flow__panel-index {
    font-size: var(--fs-2xl);
  }
}
</style>
