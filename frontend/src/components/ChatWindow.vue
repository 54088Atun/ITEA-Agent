<template>
  <div class="chat-shell">
    <!-- 历史对话固定侧栏 -->
    <aside v-if="historyEnabled" class="chat-side">
      <button class="chat-side__new" type="button" @click="newConversation">
        <el-icon><Plus /></el-icon> 新对话
      </button>
      <ul class="chat-side__list">
        <li
          v-for="c in conversations"
          :key="c.session_id"
          :class="['chat-side__item', { 'is-active': c.session_id === sessionId }]"
          @click="openConversation(c)"
        >
          <span class="chat-side__title">{{ c.title || '新对话' }}</span>
          <button
            class="chat-side__del"
            type="button"
            title="删除对话"
            @click.stop="removeConversation(c)"
          >
            <el-icon><Delete /></el-icon>
          </button>
        </li>
      </ul>
      <p v-if="!conversations.length" class="chat-side__empty">暂无历史对话</p>
    </aside>

    <div class="chat">
    <!-- ===== 消息流 ===== -->
    <div ref="msgBoxRef" class="chat__scroll" @scroll="onScroll">
      <!-- 空态：只给角色说明 + 快捷提问，不放插画 -->
      <div v-if="messages.length === 0" class="chat__empty">
        <div class="chat__empty-mark">I</div>
        <p class="chat__empty-title">{{ welcome }}</p>
        <p class="chat__empty-sub">可以直接提问，也可以从下面的常见问题开始。</p>
        <div v-if="suggestions.length" class="chat__chips">
          <button v-for="(s, i) in suggestions" :key="i" class="chat__chip" @click="quickSend(s)">
            {{ s }}
          </button>
        </div>
      </div>

      <article
        v-for="(msg, i) in messages"
        :key="i"
        :class="['msg', msg.role === 'user' ? 'msg--user' : 'msg--assistant']"
      >
        <!-- 头像 -->
        <div class="msg__avatar">
          <el-icon v-if="msg.role === 'user'" :size="15"><User /></el-icon>
          <el-icon v-else :size="15"><MagicStick /></el-icon>
        </div>

        <div class="msg__main">
          <!-- 用户消息：右对齐气泡 -->
          <div v-if="msg.role === 'user'" class="msg__bubble">{{ msg.content }}</div>

          <!-- 助手消息：文档式排版 -->
          <template v-else>
            <div class="msg__who">
              <span>{{ assistantName }}</span>
              <span v-if="msg.streaming" class="msg__live">生成中</span>
            </div>

            <!-- 处理过程（思考/工具/风控）：流式时展开，结束后自动收起 -->
            <div v-if="msg.statusList?.length" class="steps" :class="{ 'steps--open': msg.stepsOpen }">
              <button class="steps__head" type="button" @click="msg.stepsOpen = !msg.stepsOpen">
                <el-icon class="steps__spin" v-if="msg.streaming"><Loading /></el-icon>
                <el-icon v-else><CircleCheck /></el-icon>
                <span class="steps__title">
                  {{ msg.streaming ? '正在处理' : '处理过程' }}
                  <em>{{ msg.statusList.length }} 步</em>
                </span>
                <el-icon class="steps__chev"><ArrowDown /></el-icon>
              </button>
              <ul v-show="msg.stepsOpen" class="steps__list">
                <li v-for="(s, j) in msg.statusList" :key="j" :class="['steps__item', `is-${s.type}`]">
                  <span class="steps__dot"></span>
                  <span class="steps__text">{{ s.text }}</span>
                </li>
              </ul>
            </div>

            <!-- 正文 -->
            <div v-if="msg.content" class="md-body msg__md" v-html="renderHtml(msg.content)"></div>
            <span v-if="msg.streaming && msg.content" class="msg__cursor"></span>

            <!-- 空流式占位 -->
            <div v-if="msg.streaming && !msg.content" class="msg__skeleton">
              <span></span><span></span><span></span>
            </div>

            <!-- 错误：内联重试，不弹全局提示 -->
            <div v-if="msg.error" class="msg__error">
              <span>{{ msg.error }}</span>
              <el-button link type="primary" size="small" @click="retry(msg)">重试</el-button>
            </div>

            <!-- 操作条 -->
            <div v-if="!msg.streaming && msg.content" class="msg__actions">
              <button class="msg__action" @click="copy(msg.content)">
                <el-icon><CopyDocument /></el-icon>复制
              </button>
              <button
                v-if="i === messages.length - 1"
                class="msg__action"
                @click="regenerate(msg)"
              >
                <el-icon><RefreshRight /></el-icon>重新生成
              </button>
            </div>
          </template>
        </div>
      </article>
    </div>

    <!-- 回到最新 -->
    <transition name="fade">
      <button v-if="!atBottom && messages.length" class="chat__jump" @click="scrollToBottom(true)">
        <el-icon><ArrowDown /></el-icon>回到最新
      </button>
    </transition>

    <!-- ===== 输入区 ===== -->
    <div class="chat__composer">
      <div v-if="pendingImage" class="chat__image">
        <img :src="pendingImage.path" alt="待发送图片" />
        <span class="chat__image-state">
          {{ pendingImage.text ? '已识别图片内容' : '识图未启用，请补充文字描述' }}
        </span>
        <button type="button" class="chat__image-del" @click="pendingImage = null">移除</button>
      </div>
      <el-input
        v-model="input"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 6 }"
        :placeholder="placeholder"
        resize="none"
        :disabled="streaming"
        @keydown.enter.exact.prevent="send"
      />
      <div class="chat__composer-foot">
        <span class="chat__hint">
          <template v-if="input.length">{{ input.length }} 字 · </template>Enter 发送 / Shift+Enter 换行
        </span>
        <div class="chat__composer-actions">
          <el-button text :loading="uploadingImage" title="上传图片识题" @click="pickImage">
            <el-icon><Picture /></el-icon>
          </el-button>
          <input
            ref="imageInput"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            hidden
            @change="onImageChange"
          />
          <el-button v-if="streaming" plain @click="abort">
            <el-icon><VideoPause /></el-icon>停止生成
          </el-button>
          <el-button v-else type="primary" :disabled="!input.trim() && !pendingImage" @click="send">
            <el-icon><Promotion /></el-icon>发送
          </el-button>
        </div>
      </div>
    </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, nextTick, watch, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  User, MagicStick, Loading, CircleCheck, ArrowDown,
  CopyDocument, RefreshRight, VideoPause, Promotion,
} from '@element-plus/icons-vue'
import { ssePost } from '../utils/sse'
import { renderMarkdown, highlightAiTag } from '../utils/markdown'
import { chatApi } from '../api/chat'
import { uploadApi } from '../api/uploads'

const props = defineProps({
  welcome: { type: String, default: '你好!我是你的智能助教,有什么可以帮你?' },
  placeholder: { type: String, default: '输入你的问题...' },
  courseId: { type: Number, default: null },
  /** 指定业务分支(interview 等),随对话请求一并提交 */
  branch: { type: String, default: '' },
  /** 对话接口地址,管理端小助手指向 /api/admin/chat/stream */
  endpoint: { type: String, default: '/api/agent/chat' },
  /** 助手署名,区分备课助手 / 平台管理助手 */
  assistantName: { type: String, default: 'AI 助教' },
  /** 左侧历史对话侧栏 */
  historyEnabled: { type: Boolean, default: true },
  /** 可选:进入时先流式调用该入口(如 /api/student/interview/start),作为首条助手消息 */
  startEndpoint: { type: String, default: '' },
  startBody: { type: Object, default: null },
  /** 空态快捷提问 */
  suggestions: { type: Array, default: () => [] },
})

const messages = ref([])
const input = ref('')
const streaming = ref(false)
const msgBoxRef = ref()
const sessionId = ref('')
const conversations = ref([])
const atBottom = ref(true)
const imageInput = ref()
const pendingImage = ref(null)
const uploadingImage = ref(false)
let controller = null

function renderHtml(text) {
  return highlightAiTag(renderMarkdown(text))
}

// ---------- 图表渲染(无第三方依赖,输出 SVG) ----------

const CHART_COLORS = ['#2f6fb3', '#c9a227', '#2e8b57', '#b4553b', '#6b5bb5', '#4a90a4']

function paintCharts() {
  const box = msgBoxRef.value
  if (!box) return
  box.querySelectorAll('.chart-slot:not([data-painted])').forEach((el) => {
    try {
      paintChart(el, decodeURIComponent(el.dataset.chart || ''))
      el.setAttribute('data-painted', '1')
    } catch {
      el.textContent = '图表数据格式有误，已省略'
    }
  })
}

function paintChart(el, raw) {
  const spec = JSON.parse(raw || '{}')
  const type = String(spec.type || 'bar').toLowerCase()
  const labels = Array.isArray(spec.labels) ? spec.labels.map(String) : []
  const values = Array.isArray(spec.values) ? spec.values.map(Number) : []
  if (!labels.length || !values.length) throw new Error('empty chart')

  const W = 520
  const H = 240
  const pad = { t: 34, r: 16, b: 34, l: 44 }
  const innerW = W - pad.l - pad.r
  const innerH = H - pad.t - pad.b

  let body = ''
  if (type === 'pie') {
    const total = values.reduce((a, b) => a + b, 0) || 1
    let angle = -Math.PI / 2
    const cx = W / 2 - 60
    const cy = H / 2 + 6
    const r = 78
    body = values.map((v, i) => {
      const slice = (v / total) * Math.PI * 2
      const x1 = cx + r * Math.cos(angle)
      const y1 = cy + r * Math.sin(angle)
      angle += slice
      const x2 = cx + r * Math.cos(angle)
      const y2 = cy + r * Math.sin(angle)
      const large = slice > Math.PI ? 1 : 0
      return `<path d="M${cx},${cy} L${x1},${y1} A${r},${r} 0 ${large} 1 ${x2},${y2} Z" fill="${CHART_COLORS[i % CHART_COLORS.length]}" opacity="0.85"/>`
    }).join('')
    const legend = labels.map((l, i) => (
      `<rect x="${W - 150}" y="${58 + i * 22}" width="10" height="10" fill="${CHART_COLORS[i % CHART_COLORS.length]}"/>` +
      `<text x="${W - 134}" y="${67 + i * 22}" font-size="11" fill="#5b6770">${escapeXml(l)} ${values[i]}</text>`
    )).join('')
    body += legend
  } else {
    const max = Math.max(...values, 1)
    const step = innerW / labels.length
    const barW = Math.min(38, step * 0.55)
    const axis = `<line x1="${pad.l}" y1="${pad.t + innerH}" x2="${W - pad.r}" y2="${pad.t + innerH}" stroke="#d8dee4"/>`
    if (type === 'line') {
      const points = values.map((v, i) => {
        const x = pad.l + step * i + step / 2
        const y = pad.t + innerH - (v / max) * innerH
        return { x, y }
      })
      const poly = points.map((p) => `${p.x},${p.y}`).join(' ')
      body = axis +
        `<polyline points="${poly}" fill="none" stroke="${CHART_COLORS[0]}" stroke-width="2"/>` +
        points.map((p, i) => (
          `<circle cx="${p.x}" cy="${p.y}" r="3" fill="${CHART_COLORS[0]}"/>` +
          `<text x="${p.x}" y="${p.y - 8}" font-size="10" text-anchor="middle" fill="#5b6770">${values[i]}</text>`
        )).join('')
    } else {
      body = axis + values.map((v, i) => {
        const h = (v / max) * innerH
        const x = pad.l + step * i + (step - barW) / 2
        const y = pad.t + innerH - h
        return `<rect x="${x}" y="${y}" width="${barW}" height="${h}" rx="2" fill="${CHART_COLORS[i % CHART_COLORS.length]}" opacity="0.85"/>` +
          `<text x="${x + barW / 2}" y="${y - 6}" font-size="10" text-anchor="middle" fill="#5b6770">${v}</text>`
      }).join('')
    }
    body += labels.map((l, i) => (
      `<text x="${pad.l + step * i + step / 2}" y="${H - 12}" font-size="10" text-anchor="middle" fill="#5b6770">${escapeXml(l)}</text>`
    )).join('')
  }

  const title = spec.title
    ? `<text x="${W / 2}" y="20" font-size="13" font-weight="600" text-anchor="middle" fill="#33404a">${escapeXml(String(spec.title))}</text>`
    : ''
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${escapeXml(String(spec.title || '数据图表'))}">${title}${body}</svg>`
}

function escapeXml(text) {
  return String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function scrollToBottom(force = false) {
  nextTick(() => {
    const box = msgBoxRef.value
    if (!box) return
    box.scrollTop = box.scrollHeight
    if (force) atBottom.value = true
  })
}

function onScroll() {
  const box = msgBoxRef.value
  if (!box) return
  atBottom.value = box.scrollHeight - box.scrollTop - box.clientHeight < 48
}

watch(() => messages.value.length, () => scrollToBottom())

function quickSend(text) {
  if (streaming.value) return
  input.value = text
  send()
}

// ---------- 图片识题 ----------

function pickImage() {
  if (streaming.value || uploadingImage.value) return
  imageInput.value?.click()
}

async function onImageChange(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  uploadingImage.value = true
  try {
    const data = await uploadApi.image(file)
    pendingImage.value = {
      path: data.path,
      text: data.text || '',
      visionEnabled: !!data.vision_enabled,
    }
    if (data.error) {
      ElMessage.warning(data.error)
    } else if (!data.vision_enabled) {
      ElMessage.info('当前未启用识图，图片将随消息发送，请补充文字描述')
    }
  } catch { /* 拦截器已提示 */ } finally {
    uploadingImage.value = false
  }
}

// ---------- 历史对话侧栏 ----------

async function loadConversations() {
  if (!props.historyEnabled) return
  try {
    const data = await chatApi.conversations()
    conversations.value = data.items || []
  } catch { /* 历史列表失败不影响当前对话 */ }
}

async function openConversation(item) {
  if (streaming.value) return
  try {
    const data = await chatApi.history(item.session_id)
    sessionId.value = item.session_id
    messages.value = (data.messages || []).map((m) => ({
      role: m.role, content: m.content,
    }))
    input.value = ''
    scrollToBottom(true)
    nextTick(paintCharts)
  } catch { /* 拦截器已提示 */ }
}

function newConversation() {
  controller?.abort()
  controller = null
  streaming.value = false
  sessionId.value = ''
  messages.value = []
  input.value = ''
}

async function removeConversation(item) {
  try {
    await ElMessageBox.confirm('删除后该对话记录不可恢复，确认删除？', '提示', { type: 'warning' })
  } catch { return }
  try {
    await chatApi.remove(item.session_id)
    if (sessionId.value === item.session_id) newConversation()
    await loadConversations()
  } catch { /* 拦截器已提示 */ }
}

function send() {
  const text = input.value.trim()
  const image = pendingImage.value
  if ((!text && !image) || streaming.value) return

  let content = text
  if (image) {
    const prefix = image.text
      ? `【图片内容】\n${image.text}`
      : '（已上传图片，但当前未启用识图，请结合我的文字描述作答）'
    content = text ? `${prefix}\n\n${text}` : prefix
  }

  messages.value.push({ role: 'user', content })
  input.value = ''
  pendingImage.value = null

  const body = {
    message: content,
    session_id: sessionId.value || undefined,
    course_id: props.courseId,
  }
  if (props.branch) body.branch = props.branch
  runStream(props.endpoint, body)
}

/** 新增一条助手消息并挂载 SSE 流 */
function runStream(url, body) {
  const assistantMsg = reactive({
    role: 'assistant',
    content: '',
    streaming: true,
    stepsOpen: true,
    statusList: [],
    error: '',
  })
  messages.value.push(assistantMsg)
  attachStream(assistantMsg, url, body)
}

/** 把 SSE 事件写入指定助手消息(新建与重试共用) */
function attachStream(assistantMsg, url, body) {
  streaming.value = true
  atBottom.value = true
  scrollToBottom()

  const finish = () => {
    assistantMsg.streaming = false
    // 结束后收起处理过程，正文保持主视觉
    if (assistantMsg.statusList.length) assistantMsg.stepsOpen = false
    streaming.value = false
    atBottom.value = true
    scrollToBottom()
    nextTick(paintCharts)
  }

  controller = ssePost(url, body, {
    onEvent(evt) {
      const { type, data } = evt
      if (type === 'branch') {
        const labels = {
          teacher: '备课模式', tutor: '课程助教', review: '错题复盘',
          interview: '面试实训', admin: '管理助手', block: '风控拦截',
        }
        assistantMsg.statusList.push({
          type: data.branch === 'block' ? 'danger' : 'info',
          icon: 'Guide',
          text: labels[data.branch] || data.branch,
        })
      } else if (type === 'risk') {
        assistantMsg.statusList.push({
          type: 'warning', icon: 'WarnTriangleFilled', text: `风控:${data.risk_type}`,
        })
      } else if (type === 'tool_call') {
        assistantMsg.statusList.push({
          type: 'success', icon: 'Tools', text: `调用工具:${data.name}`,
        })
      } else if (type === 'reflect') {
        assistantMsg.statusList.push({
          type: 'warning', icon: 'Refresh', text: `反思校验(第${data.round}轮)`,
        })
      } else if (type === 'token') {
        assistantMsg.content += data.content
        if (atBottom.value) scrollToBottom()
      } else if (type === 'reset') {
        // 反思校验未通过：后端会带意见重写，先丢弃已流出的草稿
        assistantMsg.content = ''
      } else if (type === 'done') {
        if (data.session_id) sessionId.value = data.session_id
      } else if (type === 'error') {
        assistantMsg.content += `\n\n> ⚠️ ${data.message}`
      }
    },
    onDone() {
      if (!assistantMsg.content) {
        assistantMsg.content = '(未收到回复,请重试)'
      }
      finish()
      loadConversations()
    },
    onError(err) {
      assistantMsg.error = err.message || '连接失败，请检查网络后重试'
      finish()
    },
  })
}

onMounted(() => {
  loadConversations()
  // 面试实训等场景:进入即由后端结构化入口开启首轮流式输出
  if (props.startEndpoint) {
    runStream(props.startEndpoint, props.startBody || {})
  }
})

// 离开页面（切路由 / 关闭标签）时必须断开 SSE：
// 否则请求会在后端继续生成，长时间占用 LLM 调用与数据库连接，最终拖垮整个服务。
onBeforeUnmount(() => {
  controller?.abort()
  controller = null
})

function abort() {
  controller?.abort()
  streaming.value = false
  const last = messages.value[messages.value.length - 1]
  if (last?.streaming) {
    last.streaming = false
    if (last.statusList?.length) last.stepsOpen = false
    if (!last.content) last.content = '(已停止生成)'
  }
}

/** 重试：连接失败时复用同一入口 */
function retry(msg) {
  if (streaming.value) return
  msg.error = ''
  msg.content = ''
  msg.statusList.splice(0)
  attachStream(msg, props.startEndpoint || props.endpoint, lastBody())
}

/** 重新生成最后一条回复：丢弃末尾助手消息，用最后一条用户提问重跑 */
function regenerate(msg) {
  if (streaming.value) return
  const lastUser = [...messages.value].reverse().find(m => m.role === 'user')
  if (!lastUser) {
    // 首轮由入口触发（如面试开场），直接重跑入口
    if (!props.startEndpoint) return
    messages.value = messages.value.filter(m => m !== msg)
    runStream(props.startEndpoint, props.startBody || {})
    return
  }
  const idx = messages.value.lastIndexOf(lastUser)
  messages.value = messages.value.slice(0, idx + 1)
  runStream(props.endpoint, {
    message: lastUser.content,
    session_id: sessionId.value || undefined,
    course_id: props.courseId,
    ...(props.branch ? { branch: props.branch } : {}),
  })
}

function lastBody() {
  const lastUser = [...messages.value].reverse().find(m => m.role === 'user')
  if (!lastUser) return props.startBody || {}
  return {
    message: lastUser.content,
    session_id: sessionId.value || undefined,
    course_id: props.courseId,
    ...(props.branch ? { branch: props.branch } : {}),
  }
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}
</script>

<style scoped>
.chat-shell {
  display: flex;
  height: 100%;
  min-height: 0;
  gap: var(--sp-3);
}

/* ===== 历史对话侧栏 ===== */
.chat-side {
  width: 200px;
  flex: 0 0 200px;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  min-height: 0;
  padding: var(--sp-2);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  overflow: hidden;
}
.chat-side__new {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 8px 10px;
  font-family: inherit;
  font-size: var(--fs-xs);
  color: var(--brand-700);
  background: var(--brand-50);
  border: 1px solid var(--brand-100);
  border-radius: var(--r-sm);
  cursor: pointer;
}
.chat-side__new:hover {
  border-color: var(--brand-300);
}
.chat-side__list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  margin: 0;
  padding: 0;
  list-style: none;
}
.chat-side__item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 7px 8px;
  margin-bottom: 2px;
  border-radius: var(--r-sm);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  cursor: pointer;
}
.chat-side__item:hover {
  background: var(--bg-subtle);
}
.chat-side__item.is-active {
  background: var(--brand-50);
  color: var(--brand-700);
  font-weight: 600;
}
.chat-side__title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.chat-side__del {
  display: grid;
  place-items: center;
  padding: 0;
  border: none;
  background: none;
  color: var(--text-placeholder);
  cursor: pointer;
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease);
}
.chat-side__item:hover .chat-side__del {
  opacity: 1;
}
.chat-side__del:hover {
  color: var(--danger-600);
}
.chat-side__empty {
  padding: var(--sp-4) 0;
  text-align: center;
  font-size: var(--fs-xs);
  color: var(--text-placeholder);
}

.chat__image {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2);
  margin-bottom: var(--sp-2);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
}
.chat__image img {
  width: 56px;
  height: 56px;
  object-fit: cover;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
}
.chat__image-state {
  flex: 1;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.chat__image-del {
  border: none;
  background: none;
  font-size: var(--fs-xs);
  color: var(--danger-600);
  cursor: pointer;
}

.chart-slot {
  margin: var(--sp-3) 0;
  max-width: 560px;
}
.chart-slot svg {
  display: block;
  width: 100%;
  height: auto;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  padding: var(--sp-2);
}

.chat {
  position: relative;
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  overflow: hidden;
}

/* ===== 滚动区 ===== */
.chat__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--sp-6) var(--sp-7);
  scroll-behavior: smooth;
}

/* ===== 空态 ===== */
.chat__empty {
  max-width: 520px;
  margin: 8vh auto 0;
  text-align: center;
}
.chat__empty-mark {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  margin: 0 auto var(--sp-4);
  border-radius: var(--r-md);
  border: 1px solid var(--brand-300);
  background: var(--brand-50);
  font-family: var(--font-serif);
  font-size: 22px;
  color: var(--brand-700);
}
.chat__empty-title {
  font-family: var(--font-serif);
  font-size: var(--fs-lg);
  color: var(--text-primary);
}
.chat__empty-sub {
  margin-top: var(--sp-2);
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}
.chat__chips {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--sp-2);
  margin-top: var(--sp-5);
}
.chat__chip {
  padding: 6px 12px;
  font-size: var(--fs-sm);
  color: var(--text-secondary);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-pill);
  cursor: pointer;
  transition: all var(--dur) var(--ease-out);
}
.chat__chip:hover {
  color: var(--brand-600);
  border-color: var(--brand-300);
  background: var(--brand-50);
  transform: translateY(-1px);
  box-shadow: var(--shadow-sm);
}

/* ===== 消息 ===== */
@keyframes msg-in {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}
.msg {
  display: flex;
  gap: var(--sp-3);
  margin-bottom: var(--sp-6);
  animation: msg-in var(--dur) var(--ease-out) both;
}
.msg--user {
  flex-direction: row-reverse;
}
.msg__avatar {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  border-radius: var(--r-sm);
  background: var(--bg-subtle);
  color: var(--brand-600);
  border: 1px solid var(--border);
}
.msg--user .msg__avatar {
  background: var(--grad-brand);
  border-color: transparent;
  color: #fff;
  box-shadow: var(--glow-primary);
}
.msg__main {
  min-width: 0;
  flex: 1;
}
.msg--user .msg__main {
  display: flex;
  justify-content: flex-end;
}
.msg__bubble {
  max-width: 76%;
  padding: var(--sp-3) var(--sp-4);
  background: var(--grad-brand);
  color: #fff;
  border-radius: var(--r-md);
  border-top-right-radius: 4px;
  box-shadow: 0 2px 10px rgba(36, 104, 158, 0.18);
  font-size: var(--fs-base);
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg--assistant .msg__main {
  max-width: calc(100% - 44px);
}
.msg__who {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-bottom: var(--sp-2);
  font-size: var(--fs-xs);
  letter-spacing: 0.05em;
  color: var(--text-secondary);
}
.msg__live {
  color: var(--brand-600);
  background: var(--brand-50);
  border-radius: 3px;
  padding: 0 5px;
}
.msg__md {
  font-size: var(--fs-base);
}
.msg__cursor {
  display: inline-block;
  width: 2px;
  height: 15px;
  margin-left: 2px;
  vertical-align: text-bottom;
  background: var(--brand-600);
  animation: blink 1s steps(2, start) infinite;
}
@keyframes blink {
  50% { opacity: 0; }
}

/* 流式占位：三点呼吸，避免空白闪烁 */
.msg__skeleton {
  display: flex;
  gap: 5px;
  padding: var(--sp-2) 0;
}
.msg__skeleton span {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--brand-300);
  animation: pulse 1.2s var(--ease) infinite;
}
.msg__skeleton span:nth-child(2) { animation-delay: 0.15s; }
.msg__skeleton span:nth-child(3) { animation-delay: 0.3s; }
@keyframes pulse {
  0%, 100% { opacity: 0.25; }
  50% { opacity: 1; }
}

/* ===== 处理过程面板 ===== */
.steps {
  margin-bottom: var(--sp-3);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--bg-subtle);
  overflow: hidden;
  max-width: 620px;
}
.steps__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  padding: var(--sp-2) var(--sp-3);
  background: none;
  border: none;
  font-family: inherit;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  cursor: pointer;
  text-align: left;
}
.steps__title em {
  font-style: normal;
  color: var(--text-placeholder);
  margin-left: var(--sp-2);
}
.steps__spin {
  animation: spin 1s linear infinite;
  color: var(--brand-600);
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.steps__chev {
  margin-left: auto;
  transition: transform var(--dur-fast) var(--ease);
}
.steps--open .steps__chev {
  transform: rotate(180deg);
}
.steps__list {
  list-style: none;
  padding: 0 var(--sp-3) var(--sp-2);
  border-top: 1px solid var(--border);
}
.steps__item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 5px 0;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.steps__dot {
  width: 5px;
  height: 5px;
  flex: 0 0 5px;
  border-radius: 50%;
  background: var(--ink-300);
}
.steps__item.is-success .steps__dot { background: var(--success-600); }
.steps__item.is-warning .steps__dot { background: var(--warning-600); }
.steps__item.is-danger .steps__dot { background: var(--danger-600); }
.steps__item.is-info .steps__dot { background: var(--brand-500); }

/* ===== 错误与操作条 ===== */
.msg__error {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--fs-xs);
  color: var(--danger-600);
  background: var(--color-danger-soft);
  border-radius: var(--r-sm);
}
.msg__actions {
  display: flex;
  gap: var(--sp-1);
  margin-top: var(--sp-3);
  opacity: 0;
  transition: opacity var(--dur-fast) var(--ease);
}
.msg--assistant:hover .msg__actions {
  opacity: 1;
}
.msg__action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  font-family: inherit;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  background: none;
  border: 1px solid transparent;
  border-radius: 4px;
  cursor: pointer;
}
.msg__action:hover {
  color: var(--brand-600);
  border-color: var(--border);
  background: var(--brand-50);
}

/* ===== 回到最新 ===== */
.chat__jump {
  position: absolute;
  left: 50%;
  bottom: 148px;
  transform: translateX(-50%);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  font-family: inherit;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-pill);
  box-shadow: var(--shadow-sm);
  cursor: pointer;
  z-index: 2;
}
.chat__jump:hover {
  color: var(--brand-600);
  border-color: var(--brand-300);
}

/* ===== 输入区 ===== */
.chat__composer {
  flex: 0 0 auto;
  padding: var(--sp-3) var(--sp-5) var(--sp-4);
  border-top: 1px solid var(--border);
  background: var(--bg-card);
}
.chat__composer :deep(.el-textarea__inner) {
  box-shadow: none;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  padding: var(--sp-3) var(--sp-4);
  font-size: var(--fs-base);
  line-height: 1.6;
}
.chat__composer :deep(.el-textarea__inner:focus) {
  background: var(--bg-card);
  border-color: var(--brand-300);
}
.chat__composer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-top: var(--sp-2);
}
.chat__hint {
  font-size: var(--fs-xs);
  color: var(--text-placeholder);
}
.chat__composer-actions {
  display: flex;
  gap: var(--sp-2);
}

@media (max-width: 900px) {
  .chat-side { display: none; }
  .chat__scroll { padding: var(--sp-4); }
  .msg--assistant .msg__main { max-width: 100%; }
  .msg__bubble { max-width: 88%; }
}
</style>
