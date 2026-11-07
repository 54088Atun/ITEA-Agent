<template>
  <div class="contact-page">
    <header class="contact-nav">
      <div class="hp-container contact-nav__inner">
        <router-link to="/" class="contact-nav__brand" aria-label="ITEA-Agent 首页">
          <span class="contact-nav__mark">I</span>
          <span class="contact-nav__name">ITEA-Agent</span>
        </router-link>

        <nav class="contact-nav__links" aria-label="联系我们导航">
          <a href="#channels">联系方式</a>
          <a href="#message">在线留言</a>
          <a href="#departments">对接人</a>
          <a href="#contact-faq">常见问题</a>
        </nav>

        <div class="contact-nav__actions">
          <router-link
            v-if="userStore.isLoggedIn"
            :to="userStore.homePath"
            class="hp-btn hp-btn--ghost"
          >返回工作台</router-link>
          <template v-else>
            <router-link to="/login" class="hp-btn hp-btn--quiet">登录</router-link>
            <router-link to="/login?mode=register" class="hp-btn hp-btn--primary">免费试用</router-link>
          </template>
        </div>
      </div>
    </header>

    <main>
      <section class="contact-hero">
        <div class="hp-container contact-hero__inner">
          <div class="contact-hero__copy" v-reveal>
            <span class="hp-eyebrow">{{ contact.eyebrow }}</span>
            <h1 class="contact-hero__title">{{ contact.title }}</h1>
            <p class="contact-hero__lead">{{ contact.lead }}</p>
            <div class="contact-hero__actions">
              <a class="hp-btn hp-btn--primary" :href="primaryMailto">发邮件给我们</a>
              <a class="hp-btn hp-btn--ghost" href="#departments">找对应负责人</a>
            </div>
          </div>

          <aside class="contact-hero__card" v-reveal>
            <h2>处理时效</h2>
            <p>按问题类型分给不同的人，工作日内回复。</p>
            <dl class="contact-sla">
              <div>
                <dt>账号与登录</dt>
                <dd>1 个工作日内</dd>
              </div>
              <div>
                <dt>课程与教学使用</dt>
                <dd>1–2 个工作日</dd>
              </div>
              <div>
                <dt>部署与接口对接</dt>
                <dd>3 个工作日内</dd>
              </div>
              <div>
                <dt>数据删除与授权</dt>
                <dd>按合规流程处理</dd>
              </div>
            </dl>
            <p class="contact-hero__note">紧急故障请直接拨打电话，并在邮件标题注明“紧急”。</p>
          </aside>
        </div>
      </section>

      <section id="channels" class="contact-section">
        <div class="hp-container">
          <div class="contact-channels" v-reveal>
            <component
              :is="channel.href ? 'a' : 'div'"
              v-for="channel in contact.channels"
              :key="channel.label"
              :href="channel.href || undefined"
              class="contact-channel"
            >
              <span class="contact-channel__icon">
                <el-icon :size="18"><component :is="channel.icon" /></el-icon>
              </span>
              <span class="contact-channel__label">{{ channel.label }}</span>
              <strong class="contact-channel__value">{{ channel.value }}</strong>
              <small class="contact-channel__hint">{{ channel.hint }}</small>
            </component>
          </div>
        </div>
      </section>

      <!-- 在线留言：左侧联系方式，右侧留言表单（无写接口，提交生成邮件草稿） -->
      <section id="message" class="contact-section">
        <div class="hp-container">
          <div class="hp-section-head" v-reveal>
            <span class="hp-eyebrow">在线留言</span>
            <h2 class="hp-title">写下来，我们按类转交</h2>
            <p class="hp-desc">提交后会为你打开邮件客户端并填好内容，确认无误后发送即可。</p>
          </div>

          <div class="contact-message" v-reveal>
            <aside class="contact-message__info">
              <h3>联系方式</h3>
              <ul>
                <li v-for="channel in contact.channels" :key="channel.label">
                  <span class="contact-message__label">{{ channel.label }}</span>
                  <a v-if="channel.href" :href="channel.href">{{ channel.value }}</a>
                  <strong v-else>{{ channel.value }}</strong>
                  <small>{{ channel.hint }}</small>
                </li>
              </ul>
              <p class="contact-message__tip">留言按问题类型转给对应负责人，工作日内回复；紧急问题建议直接打电话。</p>
            </aside>

            <form class="contact-message__form" @submit.prevent="submitMessage">
              <div class="contact-message__row">
                <label>
                  <span>称呼</span>
                  <input v-model.trim="messageForm.name" type="text" placeholder="怎么称呼你" required />
                </label>
                <label>
                  <span>邮箱</span>
                  <input v-model.trim="messageForm.email" type="email" placeholder="name@campus.edu" required />
                </label>
              </div>
              <label>
                <span>问题类型</span>
                <select v-model="messageForm.type">
                  <option v-for="dept in contact.departments" :key="dept.name" :value="dept.name">
                    {{ dept.name }} · {{ dept.desc }}
                  </option>
                </select>
              </label>
              <label>
                <span>留言内容</span>
                <textarea
                  v-model.trim="messageForm.content"
                  rows="5"
                  placeholder="问题、所在页面和时间，越具体越好"
                  required
                ></textarea>
              </label>
              <button type="submit" class="hp-btn hp-btn--primary contact-message__submit" :disabled="messageSending">
                {{ messageSending ? '正在生成邮件…' : '提交留言' }}
              </button>
            </form>
          </div>
        </div>
      </section>

      <section id="departments" class="contact-section contact-section--subtle">
        <div class="hp-container">
          <div class="hp-section-head" v-reveal>
            <span class="hp-eyebrow">找对人，更快</span>
            <h2 class="hp-title">四个方向，分别有人负责</h2>
            <p class="hp-desc">不确定该找谁，就发总邮箱，我们会转给对应的人。</p>
          </div>

          <div class="contact-depts" v-reveal>
            <article v-for="dept in contact.departments" :key="dept.name" class="contact-dept">
              <h3>{{ dept.name }}</h3>
              <p>{{ dept.desc }}</p>
              <a :href="`mailto:${dept.contact}`">{{ dept.contact }}</a>
            </article>
          </div>
        </div>
      </section>

      <section id="contact-faq" class="contact-section">
        <div class="hp-container">
          <div class="hp-section-head" v-reveal>
            <span class="hp-eyebrow">常见问题</span>
            <h2 class="hp-title">先看看这里有没有答案</h2>
          </div>

          <div class="contact-faqs" v-reveal>
            <details v-for="faq in contact.faqs" :key="faq.q" class="contact-faq">
              <summary>
                <span>{{ faq.q }}</span>
                <el-icon class="contact-faq__chev"><ArrowDown /></el-icon>
              </summary>
              <p>{{ faq.a }}</p>
            </details>
          </div>
        </div>
      </section>

      <section class="contact-cta">
        <div class="hp-container contact-cta__inner" v-reveal>
          <div>
            <h2>没找到要问的？</h2>
            <p>把问题、所在页面和时间发到邮箱，我们会按操作日志查。</p>
          </div>
          <div class="contact-cta__actions">
            <a class="hp-btn hp-btn--primary" :href="primaryMailto">发送邮件</a>
            <button type="button" class="hp-btn hp-btn--ghost" @click="copyEmail">复制邮箱</button>
          </div>
        </div>
      </section>
    </main>

    <footer class="contact-foot">
      <div class="hp-container contact-foot__inner">
        <span>ITEA-Agent · 给高校老师和学生的教学助手</span>
        <span>{{ copyright }}</span>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useSiteStore } from '../../stores/site'
import { useUserStore } from '../../stores/user'
import { contact } from './content'
import { reveal } from '../../directives/reveal'
import { footer } from '../home/content'
import '../home/home.css'

const vReveal = reveal
const siteStore = useSiteStore()
const userStore = useUserStore()

const copyright = computed(() => footer.copyright || '© 2026 ITEA-Agent')

const primaryMailto = computed(() => {
  const channel = contact.channels.find((item) => item.href?.startsWith('mailto:'))
  return channel?.href || 'mailto:support@itea-agent.cn'
})

const primaryEmail = computed(() => primaryMailto.value.replace(/^mailto:/, ''))

// 在线留言：后端无提交接口，提交时生成对应负责人邮箱的邮件草稿
const messageForm = reactive({
  name: '',
  email: '',
  type: contact.departments[0]?.name || '',
  content: '',
})
const messageSending = ref(false)

function submitMessage() {
  if (messageSending.value) return
  messageSending.value = true
  const dept = contact.departments.find((item) => item.name === messageForm.type)
  const to = dept?.contact || primaryEmail.value
  const subject = `[${messageForm.type}] ${messageForm.name} 的留言`
  const body = [
    `称呼：${messageForm.name}`,
    `邮箱：${messageForm.email}`,
    `问题类型：${messageForm.type}`,
    '',
    messageForm.content,
  ].join('\n')
  window.setTimeout(() => {
    messageSending.value = false
    window.location.href = `mailto:${to}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
    ElMessage.success('已为你打开邮件客户端，确认内容后发送即可')
  }, 400)
}

async function copyEmail() {
  try {
    await navigator.clipboard.writeText(primaryEmail.value)
    ElMessage.success('邮箱已复制')
  } catch {
    ElMessage.warning(`请手动复制：${primaryEmail.value}`)
  }
}

onMounted(() => {
  siteStore.ensure()
})
</script>

<style scoped>
.contact-page {
  min-height: 100%;
  background: var(--bg-page);
}

/* ===== 顶部导航 ===== */
.contact-nav {
  position: sticky;
  top: 0;
  z-index: 20;
  background: var(--bg-topbar);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
}

.contact-nav__inner {
  display: flex;
  align-items: center;
  gap: var(--sp-6);
  height: 64px;
}

.contact-nav__brand {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  color: var(--text-primary);
}

.contact-nav__mark {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: var(--r-sm);
  border: 1px solid rgba(169, 118, 47, 0.55);
  background: var(--brand-900);
  font-family: var(--font-serif);
  font-size: 17px;
  color: var(--accent-100);
}

.contact-nav__name {
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: 600;
  letter-spacing: 0.02em;
}

.contact-nav__links {
  display: flex;
  gap: var(--sp-6);
  margin-left: var(--sp-4);
}

.contact-nav__links a {
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.contact-nav__links a:hover {
  color: var(--color-primary);
}

.contact-nav__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-left: auto;
}

.contact-nav__actions .hp-btn {
  height: 36px;
  padding: 0 var(--sp-4);
  font-size: var(--fs-sm);
}

/* ===== 首屏 ===== */
.contact-hero {
  position: relative;
  padding: 88px 0 72px;
  background:
    radial-gradient(680px 320px at 18% 0%, rgba(36, 104, 158, 0.1), transparent 70%),
    radial-gradient(520px 280px at 88% 18%, rgba(169, 118, 47, 0.1), transparent 72%),
    var(--bg-page);
}

.contact-hero__inner {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 0.8fr);
  gap: var(--sp-9);
  align-items: center;
}

.contact-hero__title {
  margin-top: var(--sp-4);
  font-family: var(--font-serif);
  font-size: var(--fs-hero);
  line-height: var(--lh-display);
  letter-spacing: -0.02em;
  color: var(--text-primary);
}

.contact-hero__lead {
  max-width: 560px;
  margin-top: var(--sp-4);
  font-size: var(--fs-md);
  line-height: var(--lh-relaxed);
  color: var(--text-secondary);
}

.contact-hero__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
  margin-top: var(--sp-7);
}

.contact-hero__card {
  padding: var(--sp-6);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: var(--shadow-md);
}

.contact-hero__card h2 {
  font-family: var(--font-serif);
  font-size: var(--fs-lg);
  color: var(--text-primary);
}

.contact-hero__card > p {
  margin-top: var(--sp-2);
  font-size: var(--fs-sm);
  line-height: var(--lh-base);
  color: var(--text-secondary);
}

.contact-sla {
  margin-top: var(--sp-4);
}

.contact-sla div {
  display: flex;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-3) 0;
  border-bottom: 1px dashed var(--border);
}

.contact-sla div:last-child {
  border-bottom: none;
}

.contact-sla dt {
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}

.contact-sla dd {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-primary);
  white-space: nowrap;
}

.contact-hero__note {
  margin-top: var(--sp-4);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--border);
  font-size: var(--fs-xs) !important;
  color: var(--text-placeholder) !important;
}

/* ===== 联系方式 ===== */
.contact-section {
  padding: 72px 0;
}

.contact-section--subtle {
  background: var(--bg-subtle);
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}

.contact-channels {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--sp-4);
}

.contact-channel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--sp-5);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 14px;
  transition: transform var(--dur) var(--ease-out), box-shadow var(--dur) var(--ease),
    border-color var(--dur-fast) var(--ease);
}

a.contact-channel:hover {
  transform: translateY(-3px);
  border-color: var(--brand-300);
  box-shadow: var(--shadow-md);
}

.contact-channel__icon {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  margin-bottom: var(--sp-2);
  border-radius: 10px;
  background: var(--color-primary-wash);
  color: var(--color-primary);
}

.contact-channel__label {
  font-size: var(--fs-xs);
  letter-spacing: 0.08em;
  color: var(--text-placeholder);
}

.contact-channel__value {
  font-size: var(--fs-base);
  font-weight: 600;
  color: var(--text-primary);
  word-break: break-all;
}

.contact-channel__hint {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

/* ===== 在线留言 ===== */
.contact-message {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
  gap: var(--sp-8);
  max-width: 960px;
  margin: 0 auto;
  padding: var(--sp-7);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 18px;
  box-shadow: var(--shadow-md);
}

.contact-message__info h3 {
  font-family: var(--font-serif);
  font-size: var(--fs-lg);
  color: var(--text-primary);
}

.contact-message__info ul {
  margin-top: var(--sp-4);
  list-style: none;
}

.contact-message__info li {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--sp-3) 0;
  border-bottom: 1px dashed var(--border);
}

.contact-message__info li:last-child {
  border-bottom: none;
}

.contact-message__label {
  font-size: var(--fs-xs);
  letter-spacing: 0.08em;
  color: var(--text-placeholder);
}

.contact-message__info a,
.contact-message__info strong {
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-primary);
}

.contact-message__info a {
  color: var(--color-primary);
}

.contact-message__info small {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

.contact-message__tip {
  margin-top: var(--sp-4);
  font-size: var(--fs-xs);
  line-height: var(--lh-base);
  color: var(--text-secondary);
}

.contact-message__form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.contact-message__row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-4);
}

.contact-message__form label {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.contact-message__form label > span {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

.contact-message__form input,
.contact-message__form select,
.contact-message__form textarea {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-sm);
  background: var(--bg-page);
  color: var(--text-primary);
  font-size: var(--fs-sm);
  font-family: inherit;
  transition: border-color var(--dur-fast) var(--ease), box-shadow var(--dur-fast) var(--ease);
}

.contact-message__form input:focus,
.contact-message__form select:focus,
.contact-message__form textarea:focus {
  outline: none;
  border-color: var(--brand-500);
  box-shadow: 0 0 0 3px var(--color-primary-wash);
}

.contact-message__form textarea {
  resize: vertical;
  min-height: 120px;
}

.contact-message__submit {
  align-self: flex-start;
  height: 40px;
  padding: 0 var(--sp-6);
}

.contact-message__submit[disabled] {
  opacity: 0.6;
  cursor: not-allowed;
}

@media (max-width: 960px) {
  .contact-message {
    grid-template-columns: 1fr;
    gap: var(--sp-6);
    padding: var(--sp-5);
  }
}

/* ===== 对接人 ===== */
.contact-depts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-4);
}

.contact-dept {
  padding: var(--sp-6);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 14px;
}

.contact-dept h3 {
  font-family: var(--font-serif);
  font-size: var(--fs-lg);
  color: var(--text-primary);
}

.contact-dept p {
  margin-top: var(--sp-2);
  font-size: var(--fs-sm);
  line-height: var(--lh-base);
  color: var(--text-secondary);
}

.contact-dept a {
  display: inline-block;
  margin-top: var(--sp-3);
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--color-primary);
}

.contact-dept a:hover {
  color: var(--color-primary-active);
}

/* ===== 常见问题 ===== */
.contact-faqs {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  max-width: 880px;
}

.contact-faq {
  padding: var(--sp-4) var(--sp-5);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
}

.contact-faq summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  font-size: var(--fs-base);
  font-weight: 600;
  color: var(--text-primary);
  cursor: pointer;
  list-style: none;
}

.contact-faq summary::-webkit-details-marker {
  display: none;
}

.contact-faq__chev {
  flex: 0 0 auto;
  color: var(--text-placeholder);
  transition: transform var(--dur-fast) var(--ease);
}

.contact-faq[open] .contact-faq__chev {
  transform: rotate(180deg);
}

.contact-faq p {
  margin-top: var(--sp-3);
  padding-top: var(--sp-3);
  border-top: 1px dashed var(--border);
  font-size: var(--fs-sm);
  line-height: var(--lh-relaxed);
  color: var(--text-secondary);
}

/* ===== 结尾 ===== */
.contact-cta {
  padding: 64px 0;
  background: var(--brand-900);
  color: var(--text-on-brand);
}

.contact-cta__inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-6);
}

.contact-cta h2 {
  font-family: var(--font-serif);
  font-size: var(--fs-2xl);
  color: #fff;
}

.contact-cta p {
  margin-top: var(--sp-2);
  font-size: var(--fs-sm);
  color: rgba(255, 255, 255, 0.66);
}

.contact-cta__actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
}

.contact-cta :deep(.hp-btn--ghost) {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.24);
  color: #fff;
}

/* ===== 页脚 ===== */
.contact-foot {
  background: var(--bg-page);
}

.contact-foot__inner {
  display: flex;
  justify-content: space-between;
  gap: var(--sp-3);
  padding-top: var(--sp-6);
  padding-bottom: var(--sp-7);
  font-size: var(--fs-xs);
  color: var(--text-placeholder);
}

@media (max-width: 1024px) {
  .contact-hero__inner {
    grid-template-columns: 1fr;
    gap: var(--sp-7);
  }

  .contact-channels {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 767px) {
  .contact-nav__links {
    display: none;
  }

  .contact-nav__actions .hp-btn--quiet {
    display: none;
  }

  .contact-hero {
    padding: 56px 0 48px;
  }

  .contact-hero__title {
    font-size: var(--fs-3xl);
  }

  .contact-section {
    padding: 48px 0;
  }

  .contact-channels,
  .contact-depts,
  .contact-message__row {
    grid-template-columns: 1fr;
  }

  .contact-cta__inner {
    flex-direction: column;
    align-items: flex-start;
  }

  .contact-foot__inner {
    flex-direction: column;
  }
}
</style>
