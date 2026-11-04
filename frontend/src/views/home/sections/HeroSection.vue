<template>
  <section class="hero">
    <div class="hp-container hero__inner">
      <div class="hero__copy">
        <p class="hp-eyebrow">{{ hero.eyebrow }}</p>
        <h1 class="hero__title">
          {{ hero.titleLead }}<br />
          <em>{{ hero.titleAccent }}</em>
        </h1>
        <p class="hero__lead">{{ hero.lead }}</p>

        <div class="hero__actions">
          <router-link
            v-for="action in hero.actions"
            :key="action.label"
            :to="action.to"
            :class="['hp-btn', action.primary ? 'hp-btn--primary' : 'hp-btn--ghost']"
          >
            {{ action.label }}
            <el-icon v-if="action.primary"><ArrowRight /></el-icon>
          </router-link>
        </div>

        <p class="hero__note">{{ hero.note }}</p>

        <ul class="hero__features">
          <li v-for="item in hero.features" :key="item">
            <el-icon><Check /></el-icon>
            {{ item }}
          </li>
        </ul>
      </div>

      <div class="hero__visual">
        <!-- 产品界面示意：用真实排版复刻对话结构，不使用占位图片 -->
        <div
          class="preview"
          role="img"
          :aria-label="`学生与 AI 助教对话界面：提问「${hero.preview.question}」，回答底部显示${hero.preview.sourceLabel}${hero.preview.source}`"
        >
          <header class="preview__bar">
            <span class="preview__dots"><i></i><i></i><i></i></span>
            <span class="preview__course">{{ hero.preview.course }}</span>
            <span class="preview__level">{{ hero.preview.level }}</span>
          </header>

          <div class="preview__body">
            <div class="bubble bubble--user">{{ hero.preview.question }}</div>

            <div class="bubble bubble--ai">
              <div class="bubble__meta">
                <span class="bubble__dot"></span>
                ITEA 助教
              </div>
              <p v-for="(line, i) in hero.preview.answer" :key="i">{{ line.text }}</p>

              <div class="bubble__source">
                <span class="bubble__source-label">{{ hero.preview.sourceLabel }}</span>
                <span class="bubble__source-link">{{ hero.preview.source }}</span>
              </div>
              <span class="ai-tag">{{ hero.preview.aiTag }}</span>
            </div>
          </div>
        </div>

        <div class="approval">
          <div class="approval__head">
            <span class="approval__badge">待确认</span>
            <span class="approval__title">{{ hero.preview.approval.title }}</span>
          </div>
          <p class="approval__action">{{ hero.preview.approval.action }}</p>
          <p class="approval__meta">{{ hero.preview.approval.meta }}</p>
          <div class="approval__actions">
            <span class="approval__btn approval__btn--ok">{{ hero.preview.approval.confirm }}</span>
            <span class="approval__btn">{{ hero.preview.approval.cancel }}</span>
          </div>
        </div>

        <div class="hero__badge">
          <el-icon><Lock /></el-icon>
          <div>
            <strong>越权直接拒绝</strong>
            <span>课程范围与工具能力双重校验</span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { hero } from '../content'
</script>

<style scoped>
.hero {
  position: relative;
  padding: 76px 0 92px;
  overflow: hidden;
}

/* 两层柔和光斑，替代大图背景 */
.hero::before {
  content: '';
  position: absolute;
  inset: -260px -160px auto auto;
  width: 760px;
  height: 600px;
  background: radial-gradient(closest-side, rgba(36, 104, 158, 0.16), transparent 72%);
  pointer-events: none;
}

.hero::after {
  content: '';
  position: absolute;
  inset: auto auto -220px -180px;
  width: 620px;
  height: 480px;
  background: radial-gradient(closest-side, rgba(169, 118, 47, 0.1), transparent 72%);
  pointer-events: none;
}

.hero__inner {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 7fr);
  gap: var(--sp-9);
  align-items: center;
}

/* ===== 左侧文案 ===== */
.hero__title {
  margin-top: var(--sp-4);
  font-family: var(--font-serif);
  font-size: clamp(40px, 4.4vw, 64px);
  font-weight: 600;
  line-height: 1.14;
  letter-spacing: -0.01em;
  color: var(--text-primary);
}

.hero__title em {
  font-style: normal;
  color: var(--accent-600);
  background: linear-gradient(120deg, #c99a5b 0%, #a9762f 70%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
}

.hero__lead {
  margin-top: var(--sp-5);
  max-width: 480px;
  font-size: var(--fs-lg);
  line-height: var(--lh-relaxed);
  color: var(--text-secondary);
}

.hero__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
  margin-top: var(--sp-7);
}

.hero__note {
  margin-top: var(--sp-3);
  font-size: var(--fs-xs);
  color: var(--text-placeholder);
}

.hero__features {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin-top: var(--sp-6);
  padding-top: 0;
  border-top: 0;
  list-style: none;
}

.hero__features li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: var(--r-pill);
  border: 1px solid var(--border);
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(6px);
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.hero__features .el-icon {
  color: var(--color-success);
  font-size: 14px;
}

/* ===== 右侧产品示意 ===== */
.hero__visual {
  position: relative;
  padding: 0 8px 24px 0;
}

/* 预览卡外的柔光，让界面像浮在页面上 */
.hero__visual::before {
  content: '';
  position: absolute;
  inset: 40px 30px 40px 40px;
  border-radius: 28px;
  background: linear-gradient(135deg, rgba(36, 104, 158, 0.28), rgba(169, 118, 47, 0.18));
  filter: blur(38px);
  opacity: 0.55;
  pointer-events: none;
}

.preview {
  position: relative;
  z-index: 1;
  overflow: hidden;
  background: var(--bg-card);
  border: 1px solid rgba(255, 255, 255, 0.8);
  border-radius: 18px;
  box-shadow:
    0 2px 6px rgba(16, 33, 48, 0.05),
    0 28px 64px rgba(16, 33, 48, 0.16);
  transform: translateY(-4px);
}

.preview__bar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--border);
  background: var(--bg-subtle);
}

.preview__dots {
  display: inline-flex;
  gap: 5px;
}

.preview__dots i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--line-200);
}

.preview__course {
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--text-primary);
}

.preview__level {
  margin-left: auto;
  padding: 2px 8px;
  border-radius: var(--r-pill);
  background: var(--color-primary-soft);
  color: var(--color-primary-active);
  font-size: 11px;
}

.preview__body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-5) var(--sp-4) var(--sp-4);
}

.bubble {
  border-radius: var(--r-md);
  font-size: var(--fs-sm);
  line-height: 1.75;
}

.bubble--user {
  align-self: flex-end;
  max-width: 78%;
  padding: var(--sp-2) var(--sp-3);
  background: var(--color-primary);
  color: var(--text-on-brand);
  border-bottom-right-radius: 4px;
}

.bubble--ai {
  padding: var(--sp-3) var(--sp-4);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
  color: var(--text-primary);
}

.bubble__meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: var(--sp-2);
  font-size: 11px;
  letter-spacing: 0.06em;
  color: var(--text-secondary);
}

.bubble__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--color-primary);
}

.bubble--ai p + p {
  margin-top: 6px;
}

.bubble--ai p:nth-of-type(2) {
  color: var(--text-secondary);
}

.bubble__source {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-3);
  padding-top: var(--sp-2);
  border-top: 1px dashed var(--border-strong);
  font-size: 11px;
}

.bubble__source-label {
  color: var(--text-placeholder);
}

.bubble__source-link {
  color: var(--color-primary);
  font-weight: 600;
}

/* 审批浮层：体现"写操作先确认" */
.approval {
  position: absolute;
  right: -18px;
  bottom: 18px;
  z-index: 2;
  width: 240px;
  padding: var(--sp-3) var(--sp-4);
  background: var(--bg-card);
  border: 1px solid var(--brand-300);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-md);
}

.approval__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.approval__badge {
  padding: 1px 7px;
  border-radius: var(--r-pill);
  background: var(--color-warning-soft);
  color: var(--warning-700);
  font-size: 10px;
  font-weight: 600;
}

.approval__title {
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--text-primary);
}

.approval__action {
  margin-top: var(--sp-2);
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--text-primary);
}

.approval__meta {
  margin-top: 2px;
  font-size: 10px;
  color: var(--text-placeholder);
}

.approval__actions {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-3);
}

.approval__btn {
  flex: 1;
  padding: 4px 0;
  text-align: center;
  border-radius: var(--r-sm);
  border: 1px solid var(--border-strong);
  font-size: 11px;
  color: var(--text-secondary);
}

.approval__btn--ok {
  background: var(--color-primary);
  border-color: var(--color-primary);
  color: var(--text-on-brand);
  font-weight: 600;
}

.hero__badge {
  position: absolute;
  left: -14px;
  bottom: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-4);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-pill);
  box-shadow: var(--shadow-sm);
}

.hero__badge .el-icon {
  color: var(--color-accent);
  font-size: 16px;
}

.hero__badge div {
  display: flex;
  flex-direction: column;
  line-height: 1.4;
}

.hero__badge strong {
  font-size: 11px;
  color: var(--text-primary);
}

.hero__badge span {
  font-size: 10px;
  color: var(--text-placeholder);
}

@media (max-width: 1199px) {
  .hero__inner {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: var(--sp-7);
  }

  .approval {
    right: -8px;
    width: 210px;
  }
}

@media (max-width: 960px) {
  .hero {
    padding: 40px 0 56px;
  }

  .hero__inner {
    grid-template-columns: 1fr;
    gap: var(--sp-8);
  }

  .hero__title {
    font-size: var(--fs-display);
  }

  .hero__lead {
    font-size: var(--fs-md);
  }
}

@media (max-width: 767px) {
  .hero {
    padding: 28px 0 44px;
  }

  .hero__title {
    font-size: 32px;
  }

  .hero__actions {
    flex-direction: column;
  }

  .hero__actions .hp-btn {
    width: 100%;
  }

  .hero__features {
    gap: var(--sp-3);
  }

  .hero__visual {
    padding: 0;
  }

  /* 移动端只保留主对话，隐藏浮层避免遮挡正文 */
  .approval,
  .hero__badge {
    display: none;
  }

  .preview__level {
    display: none;
  }
}
</style>
