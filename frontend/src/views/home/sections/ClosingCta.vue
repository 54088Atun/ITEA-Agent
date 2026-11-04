<template>
  <section class="closing">
    <div class="hp-container closing__inner">
      <h2 class="closing__title">{{ closing.title }}</h2>
      <p class="closing__desc">{{ closing.desc }}</p>
      <div class="closing__actions">
        <router-link
          v-for="action in closing.actions"
          :key="action.label"
          :to="action.to"
          :class="['hp-btn', action.primary ? 'hp-btn--primary' : 'hp-btn--ghost']"
        >
          {{ action.label }}
        </router-link>
      </div>
    </div>
  </section>
</template>

<script setup>
import { closing } from '../content'
</script>

<style scoped>
.closing {
  position: relative;
  padding: 88px 0;
  overflow: hidden;
}

.closing::before {
  content: '';
  position: absolute;
  inset: auto -140px -260px auto;
  width: 620px;
  height: 460px;
  border-radius: 50%;
  background: radial-gradient(closest-side, rgba(169, 118, 47, 0.1), transparent 72%);
  pointer-events: none;
}

.closing__inner {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}

.closing__title {
  max-width: 720px;
  font-family: var(--font-serif);
  font-size: var(--fs-2xl);
  font-weight: 600;
  line-height: var(--lh-tight);
}

.closing__desc {
  max-width: 560px;
  margin-top: var(--sp-3);
  font-size: var(--fs-md);
  line-height: var(--lh-relaxed);
  color: var(--text-secondary);
}

.closing__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--sp-3);
  margin-top: var(--sp-6);
}

@media (max-width: 767px) {
  .closing {
    padding: 56px 0;
  }

  .closing__title {
    font-size: var(--fs-xl);
  }

  .closing__desc {
    font-size: var(--fs-base);
  }

  .closing__actions {
    width: 100%;
    flex-direction: column;
  }

  .closing__actions .hp-btn {
    width: 100%;
  }
}
</style>
