<template>
  <section id="trust" class="trust">
    <div class="hp-container trust__inner">
      <header class="trust__head">
        <p class="trust__eyebrow">{{ trust.eyebrow }}</p>
        <h2 class="trust__title">{{ trust.title }}</h2>
        <p class="trust__desc">{{ trust.desc }}</p>
      </header>

      <div class="trust__cols">
        <div class="trust__col">
          <h3 class="trust__col-title">数据怎么保护</h3>
          <ul>
            <li v-for="item in trust.data" :key="item.title">
              <span class="trust__check"><el-icon><Lock /></el-icon></span>
              <div>
                <strong>{{ item.title }}</strong>
                <p>{{ item.desc }}</p>
              </div>
            </li>
          </ul>
        </div>

        <div class="trust__col">
          <h3 class="trust__col-title">系统怎么守规矩</h3>
          <ul>
            <li v-for="item in trust.ai" :key="item.title">
              <span class="trust__check"><el-icon><CircleCheck /></el-icon></span>
              <div>
                <strong>{{ item.title }}</strong>
                <p>{{ item.desc }}</p>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { trust } from '../content'
</script>

<style scoped>
.trust {
  position: relative;
  padding: 96px 0;
  background: var(--grad-sidebar);
  color: var(--text-on-brand);
  overflow: hidden;
}

/* 极淡讲义横线，延续登录页品牌区的纹理语言 */
.trust::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: repeating-linear-gradient(
    to bottom,
    rgba(255, 255, 255, 0.04) 0 1px,
    transparent 1px 48px
  );
  pointer-events: none;
}

.trust::after {
  content: '';
  position: absolute;
  inset: -180px -120px auto auto;
  width: 620px;
  height: 460px;
  border-radius: 50%;
  background: radial-gradient(closest-side, rgba(122, 178, 221, 0.24), transparent 72%);
  pointer-events: none;
}

.trust__inner {
  position: relative;
  z-index: 1;
}

.trust__head {
  max-width: 680px;
}

.trust__eyebrow {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-xs);
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--accent-100);
}

.trust__eyebrow::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-600);
}

.trust__title {
  margin-top: var(--sp-3);
  font-family: var(--font-serif);
  font-size: var(--fs-2xl);
  font-weight: 600;
  line-height: var(--lh-tight);
  color: #fff;
}

.trust__desc {
  margin-top: var(--sp-3);
  font-size: var(--fs-md);
  line-height: var(--lh-relaxed);
  color: rgba(255, 255, 255, 0.68);
}

.trust__cols {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-8);
  margin-top: var(--sp-8);
  padding-top: var(--sp-7);
  border-top: 1px solid rgba(255, 255, 255, 0.14);
}

.trust__col-title {
  font-size: var(--fs-md);
  font-weight: 600;
  color: #fff;
}

.trust__col ul {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
  margin-top: var(--sp-5);
}

.trust__col li {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
}

.trust__check {
  flex: none;
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(201, 154, 91, 0.4);
  color: var(--accent-600);
  font-size: 13px;
}

.trust__col strong {
  display: block;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: #fff;
}

.trust__col p {
  margin-top: 2px;
  font-size: var(--fs-xs);
  line-height: 1.75;
  color: rgba(255, 255, 255, 0.62);
}

@media (max-width: 960px) {
  .trust {
    padding: 72px 0;
  }

  .trust__cols {
    grid-template-columns: 1fr;
    gap: var(--sp-7);
  }
}

@media (max-width: 767px) {
  .trust {
    padding: 56px 0;
  }

  .trust__title {
    font-size: var(--fs-xl);
  }

  .trust__desc {
    font-size: var(--fs-sm);
  }
}
</style>
