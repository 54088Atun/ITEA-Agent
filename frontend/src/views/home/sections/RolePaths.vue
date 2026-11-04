<template>
  <section id="roles" class="hp-section">
    <div class="hp-container">
      <header class="hp-section-head">
        <p class="hp-eyebrow">老师与学生</p>
        <h2 class="hp-title">老师看到的，和学生看到的</h2>
        <p class="hp-desc">用的是同一套课程和作业数据，但能看到的范围不一样。</p>
      </header>

      <div class="roles">
        <article
          v-for="(role, index) in roles"
          :key="role.key"
          :class="['role', `role--${role.tone}`]"
        >
          <header class="role__head">
            <span class="role__index">0{{ index + 1 }}</span>
            <h3 class="role__name">{{ role.name }}</h3>
          </header>
          <p class="role__tagline">{{ role.tagline }}</p>

          <ul class="role__points">
            <li v-for="point in role.points" :key="point">
              <el-icon><Check /></el-icon>
              <span>{{ point }}</span>
            </li>
          </ul>

          <router-link :to="role.to" class="role__link hp-link">
            {{ role.linkLabel }}
            <el-icon><ArrowRight /></el-icon>
          </router-link>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup>
import { roles } from '../content'
</script>

<style scoped>
.roles {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-5);
}

.role {
  display: flex;
  flex-direction: column;
  padding: var(--sp-6);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  background: var(--bg-card);
  box-shadow: var(--shadow-xs);
  transition: transform var(--dur) var(--ease-out), box-shadow var(--dur) var(--ease),
    border-color var(--dur) var(--ease);
}

.role:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--brand-300);
}

/* 两种语气：教师学院蓝、学生纸白 */
.role--brand {
  background: linear-gradient(180deg, var(--brand-50), var(--bg-card) 46%);
  border-color: var(--brand-300);
}

.role__head {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
}

.role__index {
  font-family: var(--font-serif);
  font-size: var(--fs-xs);
  letter-spacing: 0.1em;
  color: var(--color-accent);
}

.role__name {
  font-family: var(--font-serif);
  font-size: var(--fs-xl);
  font-weight: 600;
}

.role__tagline {
  margin-top: var(--sp-3);
  min-height: 48px;
  font-size: var(--fs-sm);
  line-height: 1.75;
  color: var(--text-secondary);
}

.role__points {
  flex: 1;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  margin-top: var(--sp-5);
  padding-top: var(--sp-5);
  border-top: 1px solid var(--border);
}

.role__points li {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
  line-height: 1.65;
  color: var(--text-primary);
}

.role__points .el-icon {
  flex: none;
  margin-top: 3px;
  font-size: 14px;
  color: var(--color-success);
}

.role__link {
  margin-top: var(--sp-6);
}

@media (max-width: 1024px) {
  .roles {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .role__tagline {
    min-height: 0;
  }
}

@media (max-width: 767px) {
  .roles {
    grid-template-columns: 1fr;
  }
}
</style>
