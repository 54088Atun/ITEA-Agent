<template>
  <section id="showcase" class="hp-section showcase">
    <div class="hp-container">
      <header class="hp-section-head showcase__head">
        <div>
          <p class="hp-eyebrow">{{ showcase.eyebrow }}</p>
          <h2 class="hp-title">{{ showcase.title }}</h2>
          <p class="hp-desc">{{ showcase.desc }}</p>
        </div>
        <div class="showcase__counter" aria-hidden="true">
          <strong>{{ String(active + 1).padStart(2, '0') }}</strong>
          <span>/ {{ String(showcase.slides.length).padStart(2, '0') }}</span>
        </div>
      </header>

      <div
        class="carousel"
        role="region"
        aria-roledescription="轮播"
        aria-label="教学场景展示"
        tabindex="0"
        @mouseenter="paused = true"
        @mouseleave="paused = false"
        @focusin="paused = true"
        @focusout="paused = false"
        @keydown.left.prevent="prev"
        @keydown.right.prevent="next"
      >
        <div class="carousel__viewport">
          <div class="carousel__track" :style="{ transform: `translate3d(-${active * 100}%, 0, 0)` }">
            <article
              v-for="(slide, index) in showcase.slides"
              :key="slide.title"
              class="slide"
              :class="{ 'is-art': failed[index] }"
              role="group"
              aria-roledescription="幻灯片"
              :aria-label="`第 ${index + 1} 张，共 ${showcase.slides.length} 张：${slide.title}`"
              :aria-hidden="active !== index"
            >
              <!-- 兜底插画：远程图片不可用时仍保留完整的视觉层次 -->
              <div class="slide__art" :class="`slide__art--${index % 4}`" aria-hidden="true">
                <span class="slide__art-num">{{ String(index + 1).padStart(2, '0') }}</span>
                <el-icon class="slide__art-icon"><component :is="slide.icon" /></el-icon>
                <span class="slide__art-glow"></span>
              </div>

              <img
                class="slide__img"
                :class="{ 'is-loaded': loaded[index] }"
                :src="slide.image"
                :alt="slide.alt"
                :loading="index === 0 ? 'eager' : 'lazy'"
                decoding="async"
                @load="loaded[index] = true"
                @error="failed[index] = true"
              />
              <div class="slide__scrim"></div>

              <div class="slide__content">
                <span class="slide__tag">{{ slide.tag }}</span>
                <h3 class="slide__title">{{ slide.title }}</h3>
                <p class="slide__desc">{{ slide.desc }}</p>
                <span class="slide__metric">
                  <el-icon><CircleCheck /></el-icon>
                  {{ slide.metric }}
                </span>
              </div>
            </article>
          </div>
        </div>

        <div class="carousel__bar">
          <div class="carousel__dots">
            <button
              v-for="(slide, index) in showcase.slides"
              :key="`dot-${slide.title}`"
              type="button"
              class="carousel__dot"
              :class="{ 'is-active': active === index }"
              :aria-label="`查看第 ${index + 1} 张：${slide.title}`"
              :aria-current="active === index"
              @click="go(index)"
            >
              <span class="carousel__dot-label">{{ slide.tag }}</span>
            </button>
          </div>

          <div class="carousel__arrows">
            <button type="button" class="carousel__arrow" aria-label="上一张" @click="prev">
              <el-icon><ArrowLeft /></el-icon>
            </button>
            <button type="button" class="carousel__arrow" aria-label="下一张" @click="next">
              <el-icon><ArrowRight /></el-icon>
            </button>
          </div>
        </div>

        <div class="carousel__progress" aria-hidden="true">
          <span :key="active" :class="{ 'is-paused': paused }"></span>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { showcase } from '../content'

const DURATION = 6000
const active = ref(0)
const paused = ref(false)
const loaded = ref(showcase.slides.map(() => false))
const failed = ref(showcase.slides.map(() => false))
const reducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches

let timer = null

function stop() {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

function start() {
  if (reducedMotion || paused.value) return
  stop()
  timer = setInterval(() => {
    active.value = (active.value + 1) % showcase.slides.length
  }, DURATION)
}

function go(index) {
  active.value = index
  start()
}

function next() {
  go((active.value + 1) % showcase.slides.length)
}

function prev() {
  go((active.value - 1 + showcase.slides.length) % showcase.slides.length)
}

function onVisibility() {
  if (document.hidden) stop()
  else start()
}

watch(paused, (value) => (value ? stop() : start()))

onMounted(() => {
  start()
  document.addEventListener('visibilitychange', onVisibility)
})

onBeforeUnmount(() => {
  stop()
  document.removeEventListener('visibilitychange', onVisibility)
})
</script>

<style scoped>
.showcase__head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--sp-6);
  max-width: none;
}

.showcase__counter {
  flex: none;
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding-bottom: 4px;
  font-family: var(--font-serif);
  color: var(--text-placeholder);
}

.showcase__counter strong {
  font-size: var(--fs-2xl);
  font-weight: 600;
  color: var(--text-primary);
}

.showcase__counter span {
  font-size: var(--fs-sm);
}

.carousel {
  position: relative;
  border-radius: 20px;
  overflow: hidden;
  background: var(--brand-900);
  box-shadow: var(--shadow-lg);
}

.carousel:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 3px;
}

.carousel__viewport {
  overflow: hidden;
}

.carousel__track {
  display: flex;
  transition: transform 620ms cubic-bezier(0.22, 0.61, 0.36, 1);
}

.slide {
  position: relative;
  flex: 0 0 100%;
  height: clamp(380px, 44vw, 540px);
  overflow: hidden;
  /* 图片加载前的兜底底色，避免白闪 */
  background: linear-gradient(135deg, var(--brand-800), var(--brand-900));
}

/* 兜底插画：四种配色的编辑感场景，图片加载成功后覆盖 */
.slide__art {
  position: absolute;
  inset: 0;
  overflow: hidden;
}

.slide__art::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: repeating-linear-gradient(
      to right,
      rgba(255, 255, 255, 0.05) 0 1px,
      transparent 1px 72px
    ),
    repeating-linear-gradient(
      to bottom,
      rgba(255, 255, 255, 0.05) 0 1px,
      transparent 1px 72px
    );
  mask-image: radial-gradient(120% 100% at 70% 30%, #000 20%, transparent 78%);
}

.slide__art--0 {
  background:
    radial-gradient(120% 100% at 82% 16%, rgba(201, 154, 91, 0.42), transparent 56%),
    linear-gradient(135deg, #1b5382, #0b2a42);
}

.slide__art--1 {
  background:
    radial-gradient(100% 90% at 18% 20%, rgba(122, 178, 221, 0.45), transparent 58%),
    linear-gradient(150deg, #24689e, #0e3350);
}

.slide__art--2 {
  background:
    radial-gradient(110% 100% at 76% 76%, rgba(91, 155, 208, 0.38), transparent 60%),
    linear-gradient(120deg, #133f63, #0b2a42);
}

.slide__art--3 {
  background:
    radial-gradient(110% 100% at 24% 78%, rgba(201, 154, 91, 0.34), transparent 58%),
    linear-gradient(160deg, #1b5382, #16212c);
}

.slide__art-num {
  position: absolute;
  right: 4%;
  bottom: -8%;
  font-family: var(--font-serif);
  font-size: 240px;
  font-weight: 600;
  line-height: 1;
  color: rgba(255, 255, 255, 0.08);
  letter-spacing: -0.04em;
}

.slide__art-icon {
  position: absolute;
  top: 16%;
  right: 9%;
  font-size: 104px;
  color: rgba(255, 255, 255, 0.18);
}

.slide__art-glow {
  position: absolute;
  top: -30%;
  right: -10%;
  width: 520px;
  height: 520px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.14);
  box-shadow: inset 0 0 0 60px rgba(255, 255, 255, 0.03);
}

.slide__img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  opacity: 0;
  transform: scale(1.02);
  transition: opacity 600ms var(--ease), transform 1200ms var(--ease-out);
}

.slide__img.is-loaded {
  opacity: 1;
}

.slide:hover .slide__img {
  transform: scale(1.05);
}

.slide__scrim {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(90deg, rgba(10, 26, 40, 0.86) 0%, rgba(10, 26, 40, 0.5) 46%, rgba(10, 26, 40, 0.1) 78%),
    linear-gradient(0deg, rgba(10, 26, 40, 0.55), transparent 46%);
}

/* 走兜底插画时压暗稍弱，让插画层次透出来 */
.slide.is-art .slide__scrim {
  background:
    linear-gradient(90deg, rgba(10, 26, 40, 0.62) 0%, rgba(10, 26, 40, 0.26) 52%, transparent 84%),
    linear-gradient(0deg, rgba(10, 26, 40, 0.48), transparent 46%);
}

.slide__content {
  position: absolute;
  left: clamp(24px, 5vw, 64px);
  bottom: clamp(88px, 7vw, 104px);
  max-width: 520px;
  color: #fff;
}

.slide__tag {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: var(--r-pill);
  border: 1px solid rgba(201, 154, 91, 0.5);
  background: rgba(201, 154, 91, 0.16);
  font-size: 11px;
  letter-spacing: 0.14em;
  color: var(--accent-100);
}

.slide__title {
  margin-top: var(--sp-3);
  font-family: var(--font-serif);
  font-size: clamp(24px, 3vw, 34px);
  font-weight: 600;
  line-height: 1.3;
  color: #fff;
}

.slide__desc {
  margin-top: var(--sp-2);
  font-size: var(--fs-sm);
  line-height: 1.8;
  color: rgba(255, 255, 255, 0.78);
}

.slide__metric {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: var(--sp-4);
  font-size: var(--fs-xs);
  color: var(--accent-100);
}

.slide__metric .el-icon {
  font-size: 14px;
  color: var(--accent-600);
}

/* ===== 控件 ===== */
.carousel__bar {
  position: absolute;
  right: clamp(16px, 3vw, 36px);
  bottom: clamp(20px, 3vw, 32px);
  left: clamp(16px, 3vw, 36px);
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--sp-4);
  pointer-events: none;
}

.carousel__dots {
  display: flex;
  gap: var(--sp-2);
  margin-right: auto;
  pointer-events: auto;
}

.carousel__dot {
  display: inline-flex;
  align-items: center;
  padding: 5px 12px;
  border-radius: var(--r-pill);
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: rgba(12, 23, 33, 0.35);
  backdrop-filter: blur(6px);
  color: rgba(255, 255, 255, 0.66);
  font-size: 11px;
  cursor: pointer;
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease),
    border-color var(--dur) var(--ease);
}

.carousel__dot:hover {
  color: #fff;
  border-color: rgba(255, 255, 255, 0.4);
}

.carousel__dot.is-active {
  background: #fff;
  border-color: #fff;
  color: var(--brand-900);
  font-weight: 600;
}

.carousel__dot:focus-visible,
.carousel__arrow:focus-visible {
  outline: 2px solid #fff;
  outline-offset: 2px;
}

.carousel__arrows {
  display: flex;
  gap: var(--sp-2);
  pointer-events: auto;
}

.carousel__arrow {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.24);
  background: rgba(12, 23, 33, 0.4);
  backdrop-filter: blur(6px);
  color: #fff;
  cursor: pointer;
  transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease);
}

.carousel__arrow:hover {
  background: rgba(255, 255, 255, 0.16);
  border-color: rgba(255, 255, 255, 0.5);
}

.carousel__progress {
  position: absolute;
  inset: auto 0 0 0;
  height: 2px;
  background: rgba(255, 255, 255, 0.14);
}

.carousel__progress span {
  display: block;
  height: 100%;
  background: var(--accent-600);
  animation: carousel-progress 6000ms linear forwards;
}

.carousel__progress span.is-paused {
  animation-play-state: paused;
}

@keyframes carousel-progress {
  from { width: 0; }
  to { width: 100%; }
}

@media (max-width: 960px) {
  .showcase__counter {
    display: none;
  }

  .slide {
    height: clamp(360px, 70vw, 460px);
  }

  /* 文案抬到控件之上，避免与圆点/箭头重叠 */
  .slide__content {
    left: var(--sp-5);
    right: var(--sp-5);
    bottom: 88px;
    max-width: none;
  }

  .slide__desc {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }

  .carousel__dots {
    max-width: 100%;
    overflow-x: auto;
    scrollbar-width: none;
  }

  .carousel__dots::-webkit-scrollbar {
    display: none;
  }
}

@media (max-width: 600px) {
  .carousel__bar {
    gap: var(--sp-2);
  }

  .carousel__dot {
    padding: 5px 9px;
  }

  .carousel__arrow {
    width: 34px;
    height: 34px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .carousel__track,
  .slide__img {
    transition: none;
  }

  .carousel__progress span {
    animation: none;
    width: 100%;
  }
}
</style>
