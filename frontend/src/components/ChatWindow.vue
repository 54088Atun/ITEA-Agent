<template>
  <div class="chat-shell">
    <!-- 窄屏历史抽屉遮罩 -->
    <div
      v-if="historyEnabled && historyDrawerVisible"
      class="chat-side__backdrop"
      @click="historyDrawerVisible = false"
    ></div>
    <!-- 历史对话侧栏:桌面固定,900px 以下切换为抽屉 -->
    <aside
      v-if="historyEnabled"
      :class="['chat-side', { 'is-open': historyDrawerVisible }]"
    >
      <button class="chat-side__new" type="button" @click="newConversation">
        <el-icon><Plus /></el-icon> 新对话
      </button>
      <div class="chat-side__search">
        <DebouncedInput
          v-model="searchKeyword" :delay="300" size="small" clearable
          placeholder="搜索标题或内容"
          @debounce="loadConversations"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </DebouncedInput>
      </div>
      <div class="chat-side__tools">
        <template v-if="sessionId">
          <button type="button" @click="summarizeCurrent(false)">摘要</button>
          <button type="button" @click="exportCurrent">导出</button>
        </template>
        <button type="button" @click="openMemories">记忆</button>
      </div>
      <ul class="chat-side__list">
        <li
          v-for="c in visibleConversations"
          :key="c.session_id"
          :class="['chat-side__item', { 'is-active': c.session_id === sessionId }]"
          @click="openConversation(c)"
        >
          <span class="chat-side__title">{{ c.title || '新对话' }}</span>
          <button
            class="chat-side__star"
            :class="{ 'is-on': c.is_favorite }"
            type="button"
            :title="c.is_favorite ? '取消收藏' : '收藏'"
            @click.stop="toggleFavorite(c)"
          >
            <el-icon><StarFilled v-if="c.is_favorite" /><Star v-else /></el-icon>
          </button>
          <button
            class="chat-side__del"
            type="button"
            title="删除对话"
            @click.stop="removeConversation(c)"
          >
            <el-icon><Delete /></el-icon>
          </button>
        </li>
        <li v-if="visibleCount < conversations.length" ref="sentinelRef" class="chat-side__sentinel"></li>
      </ul>
      <p v-if="!conversations.length" class="chat-side__empty">
        {{ searchKeyword ? '没有匹配的对话' : '暂无历史对话' }}
      </p>
    </aside>

    <div class="chat">
    <!-- 窄屏历史入口 -->
    <div v-if="historyEnabled" class="chat__mobile-bar">
      <button type="button" class="chat__history-btn" @click="historyDrawerVisible = true">
        <el-icon><Clock /></el-icon> 历史对话
      </button>
    </div>
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
          <div v-if="msg.role === 'user'" class="msg__bubble">
            {{ msg.content }}
            <div v-if="msg.attachments?.length" class="msg__files">
              <span v-for="(file, fi) in msg.attachments" :key="fi" class="msg__file">
                <em class="msg__file-type">{{ file.type === 'audio' ? '语音' : '图片' }}</em>
                <span v-if="file.filename" class="msg__file-name">{{ file.filename }}</span>
                <span v-if="file.size" class="msg__file-size">{{ Math.ceil(file.size / 1024) }} KB</span>
              </span>
            </div>
            <div v-if="msg.sources?.length" class="msg__sources">
              <span v-for="source in msg.sources" :key="source">{{ source }}</span>
            </div>
          </div>

          <!-- 助手消息：文档式排版 -->
          <template v-else>
            <div class="msg__who">
              <span>{{ assistantName }}</span>
              <span v-if="msg.streaming" class="msg__live">生成中</span>
            </div>
            <div v-if="msg.securityLevel" class="msg__security" :title="securityDesc(msg.securityLevel)">
              信息级别：{{ securityLabel(msg.securityLevel) }}
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

            <!-- 正文：流式走段落缓存，避免逐 token 全文重渲染 -->
            <div v-if="msgBodyHtml(msg)" class="md-body msg__md" v-html="msgBodyHtml(msg)"></div>
            <span v-if="msg.streaming && msgBodyHtml(msg)" class="msg__cursor"></span>

            <!-- 写操作确认卡片:确认前不产生任何变更 -->
            <div v-if="msg.confirm" :class="['confirm-card', `is-${msg.confirm.status}`]">
              <div class="confirm-card__head">
                <el-icon><WarningFilled /></el-icon>
                <span class="confirm-card__title">待确认：{{ msg.confirm.label }}</span>
                <em :class="['confirm-card__risk', `is-${msg.confirm.riskLevel}`]">
                  {{ riskLabel(msg.confirm.riskLevel) }}
                </em>
              </div>
              <p class="confirm-card__summary">{{ msg.confirm.message }}</p>
              <ul v-if="msg.confirm.items.length" class="confirm-card__list">
                <li v-for="(item, ci) in msg.confirm.items.slice(0, 5)" :key="ci">
                  <span>{{ item.name || item.email || item.config_key || `#${item.id}` }}</span>
                  <em v-if="item.skip_reason">{{ item.skip_reason }}</em>
                </li>
              </ul>
              <p v-if="msg.confirm.truncated" class="confirm-card__hint">
                列表仅展示前 {{ msg.confirm.items.length }} 个对象，确认后按单批上限处理。
              </p>
              <p v-if="msg.confirm.status === 'done'" class="confirm-card__state">
                已执行：{{ msg.confirm.result }}
              </p>
              <p v-else-if="msg.confirm.status === 'cancelled'" class="confirm-card__state">
                已取消，未做任何变更。
              </p>
              <p v-else-if="msg.confirm.status === 'error'" class="confirm-card__state is-error">
                {{ msg.confirm.error }}
              </p>
              <div v-else class="confirm-card__actions">
                <el-button
                  type="danger" size="small"
                  :loading="msg.confirm.loading" @click="confirmAction(msg)"
                >确认执行</el-button>
                <el-button
                  size="small" :disabled="msg.confirm.loading" @click="cancelConfirm(msg)"
                >取消</el-button>
              </div>
            </div>

            <!-- 空流式占位 -->
            <div v-if="msg.streaming && !msgBodyHtml(msg)" class="msg__skeleton">
              <span></span><span></span><span></span>
            </div>

            <!-- 断线自动恢复中 -->
            <div v-if="msg.reconnecting" class="msg__reconnecting">
              连接中断，正在重连…
            </div>

            <!-- 错误：内联重试，不弹全局提示 -->
            <div v-if="msg.error" class="msg__error">
              <span>{{ msg.error }}</span>
              <el-button
                v-if="!interviewExpired || msg.interviewSummary"
                link type="primary" size="small" @click="retry(msg)"
              >重试</el-button>
            </div>

            <!-- 操作条 -->
            <div v-if="!msg.streaming && msg.content" class="msg__actions">
              <button class="msg__action" @click="copy(msg.content)">
                <el-icon><CopyDocument /></el-icon>复制
              </button>
              <button class="msg__action" type="button" @click="toggleSpeech(msg, i)">
                {{ speakingIndex === i ? '停止朗读' : '朗读' }}
              </button>
              <button
                v-if="i === messages.length - 1 && !interviewExpired"
                class="msg__action"
                @click="regenerate(msg)"
              >
                <el-icon><RefreshRight /></el-icon>重新生成
              </button>
              <button v-if="msg.runId" class="msg__action" type="button" @click="openTimeline(msg)">
                执行时间线
              </button>
              <button
                v-if="msg.runId" class="msg__action" type="button"
                :disabled="!!msg.feedback" @click="sendFeedback(msg, 'up')"
              >
                {{ msg.feedback === 'up' ? '已点赞' : '有用' }}
              </button>
              <button
                v-if="msg.runId" class="msg__action" type="button"
                :disabled="!!msg.feedback" @click="sendFeedback(msg, 'down')"
              >
                {{ msg.feedback === 'down' ? '已反馈' : '没用' }}
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
      <div v-if="pendingImages.length" class="chat__images">
        <div v-for="(img, idx) in pendingImages" :key="img.path" class="chat__image">
          <img :src="resolveAsset(img.path)" :alt="`待发送图片${idx + 1}`" />
          <span class="chat__image-state" :title="img.description || ''">
            {{ img.error ? '识别失败，请补充文字描述' : ((img.text || img.description) ? '已识别图片内容' : '识图未启用，请补充文字描述') }}
          </span>
          <button type="button" class="chat__image-del" @click="removeImage(idx)">移除</button>
        </div>
      </div>
      <el-input
        v-model="input"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 6 }"
        :placeholder="placeholder"
        resize="none"
        :disabled="streaming || interviewExpired"
        @keydown.enter.exact="onEnter"
        @paste="onPaste"
      />
      <div class="chat__composer-foot">
        <div class="chat__foot-left">
          <span
            v-if="durationMinutes > 0"
            :class="['chat__timer', { 'is-expired': interviewExpired }]"
          >
            {{ interviewExpired ? '面试已结束' : `面试剩余 ${formatDuration(remainingSeconds)}` }}
          </span>
          <label v-if="canCollaborate" class="chat__collab" title="开启后由多个专家 Agent 分工协作并汇总回答">
            <el-switch v-model="collaborate" size="small" :disabled="streaming" />
            <span>多 Agent 协作</span>
          </label>
          <span class="chat__hint">
            <template v-if="input.length">{{ input.length }} 字 · </template>Enter 发送 / Shift+Enter 换行 · 可粘贴截图
          </span>
        </div>
        <div class="chat__composer-actions">
          <span v-if="recording" class="chat__recording">录音中 {{ recordingSeconds }}s</span>
          <el-button
            text :loading="uploadingAudio"
            :title="recording ? '结束录音并转写' : (features.asr_ready ? '语音输入' : '语音识别未配置，请使用文字输入')"
            :aria-label="recording ? '结束录音并转写' : '语音输入'"
            :disabled="streaming || interviewExpired || !features.asr_ready" @click="toggleRecording"
          >
            <el-icon :class="{ 'is-recording': recording }"><Microphone /></el-icon>
          </el-button>
          <el-button
            text :loading="uploadingImage"
            :title="features.vision_ready ? '上传图片识题' : '识图未配置，请直接输入题目文字'"
            aria-label="上传图片识题"
            :disabled="streaming || interviewExpired || !features.vision_ready" @click="pickImage"
          >
            <el-icon><Picture /></el-icon>
          </el-button>
          <input
            ref="imageInput"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            multiple
            hidden
            @change="onImageChange"
          />
          <el-button
            text :loading="uploadingImage"
            :title="features.vision_ready ? '拍照上传' : '识图未配置，请直接输入题目文字'"
            aria-label="拍照上传"
            :disabled="streaming || interviewExpired || !features.vision_ready" @click="pickCameraImage"
          >
            <el-icon><Camera /></el-icon>
          </el-button>
          <input
            ref="cameraInput"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            capture="environment"
            hidden
            @change="onImageChange"
          />
          <el-button v-if="streaming" plain :disabled="!currentRunId" @click="openPlanDialog">
            <el-icon><EditPen /></el-icon>调整计划
          </el-button>
          <el-button
            v-if="streaming" circle plain title="停止生成" aria-label="停止生成"
            class="chat__send" @click="abort"
          >
            <el-icon><VideoPause /></el-icon>
          </el-button>
          <el-button
            v-else type="primary" circle title="发送" aria-label="发送" class="chat__send"
            :disabled="interviewExpired || (!input.trim() && !pendingImages.length)"
            @click="send"
          >
            <el-icon><Promotion /></el-icon>
          </el-button>
        </div>
      </div>
    </div>
    </div>

    <el-dialog v-model="summaryVisible" title="会话摘要" width="520px">
      <p v-loading="summarizing" class="chat-summary">
        {{ summaryText || '正在生成摘要…' }}
      </p>
      <template #footer>
        <el-button @click="summaryVisible = false">关闭</el-button>
        <el-button type="primary" :loading="summarizing" @click="summarizeCurrent(true)">
          重新生成
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="timelineVisible" title="执行时间线" width="min(560px, 92vw)">
      <div v-loading="timelineLoading" class="run-timeline">
        <p v-if="timelineRun" class="run-timeline__meta">
          {{ timelineRun.branch || '未知分支' }} · {{ timelineRun.status }}
          · {{ timelineRun.duration_ms || 0 }} ms
          <template v-if="timelineSummary">
            · {{ timelineSummary.steps }} 步 · {{ timelineSummary.tokens }} tokens
          </template>
        </p>
        <p v-if="timelineRun?.error" class="run-timeline__error">{{ timelineRun.error }}</p>
        <p v-if="!timelineItems.length && !timelineLoading" class="run-timeline__empty">
          该次运行暂无步骤记录
        </p>
        <ul class="run-timeline__list">
          <li
            v-for="item in timelineItems" :key="item.seq"
            :class="['run-timeline__item', `is-${item.status}`]"
          >
            <button type="button" class="run-timeline__row" @click="toggleTimeline(item)">
              <span class="run-timeline__seq">{{ item.seq }}</span>
              <span class="run-timeline__kind">{{ item.kind_label }}</span>
              <span class="run-timeline__name">{{ item.name }}</span>
              <span class="run-timeline__cost">{{ item.duration_ms || 0 }} ms</span>
            </button>
            <div v-if="isTimelineOpen(item)" class="run-timeline__body">
              <p v-if="item.error" class="run-timeline__error">{{ item.error }}</p>
              <template v-if="item.payload !== null && item.payload !== undefined">
                <p class="run-timeline__label">输入</p>
                <pre class="run-timeline__pre">{{ formatSpanValue(item.payload) }}</pre>
              </template>
              <template v-if="item.result !== null && item.result !== undefined">
                <p class="run-timeline__label">输出</p>
                <pre class="run-timeline__pre">{{ formatSpanValue(item.result) }}</pre>
              </template>
              <p v-if="!item.payload && !item.result && !item.error" class="run-timeline__label">
                该步骤无附加数据
              </p>
            </div>
          </li>
        </ul>
      </div>
      <template #footer>
        <el-button @click="timelineVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="planVisible" title="调整执行计划" width="480px">
      <p class="run-timeline__meta">
        提交后会在下一步生效：保留当前问题，按新要求重新组织答案。
      </p>
      <el-input
        v-model="planInstruction"
        type="textarea"
        :rows="3"
        maxlength="500"
        show-word-limit
        placeholder="例如：只看 3 班的提交率，不要再检索原始明细"
      />
      <template #footer>
        <el-button @click="planVisible = false">取消</el-button>
        <el-button
          type="primary" :loading="planSubmitting"
          :disabled="!planInstruction.trim()" @click="submitPlanRevision"
        >
          提交调整
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="memoryVisible" title="我的记忆" width="560px">
      <p class="run-timeline__meta">记忆会按有效期自动过期，可随时删除错误记忆。</p>
      <div v-loading="memoryLoading" class="memory-list">
        <div v-for="m in memories" :key="m.id" class="memory-item">
          <div class="memory-item__main">
            <p class="memory-item__content">{{ m.content }}</p>
            <span class="memory-item__meta">
              {{ m.memory_type }} · {{ m.source_type }}
              <template v-if="m.course_id"> · 课程 {{ m.course_id }}</template>
              <template v-if="m.expires_at"> · 到期 {{ formatClock(m.expires_at) }}</template>
            </span>
          </div>
          <el-button link type="danger" size="small" @click="removeMemory(m.id)">删除</el-button>
        </div>
      </div>
      <p v-if="!memories.length && !memoryLoading" class="run-timeline__empty">
        还没有记录任何记忆
      </p>
      <template #footer>
        <el-button @click="memoryVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, nextTick, watch, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  User, MagicStick, Loading, CircleCheck, ArrowDown, Plus, Delete,
  CopyDocument, RefreshRight, VideoPause, Promotion, Microphone, Camera,
  Search, Star, StarFilled, Connection, EditPen, WarningFilled, Clock,
} from '@element-plus/icons-vue'
import DOMPurify from 'dompurify'
import 'katex/dist/katex.min.css'
import {
  ssePost, isRecoverableError, nextBackoffMs, recoveryDeadline,
  remainingBudgetMs, resolveRequestId, MAX_RECOVERY_ATTEMPTS,
} from '../utils/sse'
import { renderMarkdown, highlightAiTag } from '../utils/markdown'
import { isSpeechSupported, speakMarkdown, stopSpeech } from '../utils/speech.js'
import { microphoneErrorMessage } from '../utils/media.js'
import { resolveAsset } from '../utils/asset.js'
import { chatApi } from '../api/chat'
import { agentApi } from '../api/agent'
import { adminApi } from '../api/admin'
import { uploadApi } from '../api/uploads'
import { features, loadFeatures } from '../stores/features'
import DebouncedInput from './DebouncedInput.vue'

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
  /** 可选面试约束：分钟数与来源作业，0 表示普通对话不计时 */
  durationMinutes: { type: Number, default: 0 },
  interviewAssignmentId: { type: Number, default: null },
  /** 空态快捷提问 */
  suggestions: { type: Array, default: () => [] },
  /** 错题复盘:true 表示本次消息作为错题提交并写入学情 */
  reviewSubmit: { type: Boolean, default: false },
})

const emit = defineEmits(['time-update', 'sent'])

const messages = ref([])
const input = ref('')
const streaming = ref(false)
const msgBoxRef = ref()
const sessionId = ref('')
const conversations = ref([])
// 900px 以下历史侧栏切换为抽屉
const historyDrawerVisible = ref(false)
const atBottom = ref(true)
const imageInput = ref()
const cameraInput = ref()
const pendingImages = ref([])
const MAX_IMAGES = 3
const uploadingImage = ref(false)
const recording = ref(false)
const recordingSeconds = ref(0)
const uploadingAudio = ref(false)
const audioSource = ref('')
const speakingIndex = ref(-1)
const searchKeyword = ref('')
const collaborate = ref(false)
// 面试有计时/评分状态机、管理端有写操作确认,这两个入口不支持协作模式
const canCollaborate = computed(
  () => !props.branch || !['interview', 'admin'].includes(props.branch),
)
const summaryVisible = ref(false)
const summaryText = ref('')
const summarizing = ref(false)
let recorder = null
let audioChunks = []
let audioTimer = null
let controller = null
// 取消当前消息的续答轮询(停止生成/切换会话/卸载时调用)
let cancelRecovery = null
const remainingSeconds = ref(0)
const interviewExpired = ref(false)
let interviewTimer = null
let interviewDeadline = 0
let autoSummaryStarted = false

// 用户可控:执行时间线 / 记忆管理
const timelineVisible = ref(false)
const timelineLoading = ref(false)
const timelineRun = ref(null)
const timelineSummary = ref(null)
const timelineItems = ref([])
// 展开的步骤序号:时间线默认折叠,点开后展示参数/结果/错误
const expandedTimeline = ref([])
const memoryVisible = ref(false)
const memoryLoading = ref(false)
const memories = ref([])

// 运行中途调整计划
const planVisible = ref(false)
const planInstruction = ref('')
const planSubmitting = ref(false)
const currentRunId = computed(() => {
  if (!streaming.value) return null
  const last = messages.value[messages.value.length - 1]
  return last?.runId || null
})

function renderHtml(text) {
  return highlightAiTag(renderMarkdown(text))
}

// ---------- 流式正文段落缓冲 ----------
// 逐 token 全文重渲染 markdown 会导致代码块/公式反复闪烁；改为按段落缓冲：
// 遇到完整段落（\n\n）才渲染并追加进 closedHtml 缓存，尾部半截段落单独实时渲染。

/** 初始化某条消息的流式缓冲状态（新建与重试共用） */
function streamReset(msg) {
  msg._draft = ''
  msg._fullText = ''
  msg.closedHtml = ''
  msg.tailHtml = ''
}

/** 检测文本是否落在未闭合的代码块/块级公式内，返回类型或空串 */
function unclosedBlock(text) {
  if ((text.match(/```/g) || []).length % 2 === 1) return 'code'
  if ((text.match(/\$\$/g) || []).length % 2 === 1) return 'math'
  return ''
}

/** 未闭合块占位：浅灰提示，避免半截代码/公式闪烁 */
const streamPendingHtml = (kind) => (
  `<p class="stream-pending">${kind === 'code' ? '代码块输出中…' : '公式输出中…'}</p>`
)

/** 冲刷草稿：把完整段落渲染入缓存；final 时收尾并清空尾部 */
function streamFlush(msg, final) {
  let draft = msg._draft
  let searchFrom = 0
  let idx
  while ((idx = draft.indexOf('\n\n', searchFrom)) >= 0) {
    const head = draft.slice(0, idx)
    // 分割点落在未闭合的 ```/$$ 块内部时跳过（闭合代码块内部含空行属正常）
    if (unclosedBlock(head)) { searchFrom = idx + 2; continue }
    if (head.trim()) msg.closedHtml += renderHtml(head)
    draft = draft.slice(idx + 2)
    searchFrom = 0
  }
  msg._draft = draft
  if (final) {
    if (draft.trim()) msg.closedHtml += renderHtml(draft)
    msg._draft = ''
    msg.tailHtml = ''
  } else if (draft.trim()) {
    const kind = unclosedBlock(draft)
    msg.tailHtml = kind ? streamPendingHtml(kind) : renderHtml(draft)
  } else {
    msg.tailHtml = ''
  }
}

/** 消息正文 HTML：流式消息走段落缓存，其余消息按 content 变化做全文渲染缓存 */
function msgBodyHtml(msg) {
  if (msg.closedHtml !== undefined && msg.closedHtml !== null) {
    return (msg.closedHtml || '') + (msg.tailHtml || '')
  }
  if (msg._bodySrc === msg.content) return msg._bodyHtml
  msg._bodySrc = msg.content
  msg._bodyHtml = renderHtml(msg.content)
  return msg._bodyHtml
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

// ---------- 公式与 Mermaid(按需懒加载,避免首屏体积膨胀) ----------

let katexPromise = null
let mermaidPromise = null
let mermaidSeq = 0

function paintRich() {
  paintCharts()
  paintMath()
  paintMermaid()
}

async function paintMath() {
  const box = msgBoxRef.value
  if (!box) return
  const slots = [...box.querySelectorAll('.math-slot:not([data-painted])')]
  if (!slots.length) return
  try {
    katexPromise = katexPromise || import('katex').then((mod) => mod.default)
    const katex = await katexPromise
    slots.forEach((el) => {
      el.setAttribute('data-painted', '1')
      try {
        const tex = decodeURIComponent(el.dataset.tex || '')
        const html = katex.renderToString(tex, {
          displayMode: el.dataset.display === '1',
          throwOnError: false,
          trust: false,
          strict: 'ignore',
        })
        el.innerHTML = DOMPurify.sanitize(html, {
          USE_PROFILES: { html: true, svg: true, mathMl: true },
        })
      } catch {
        // 保留原始 TeX 文本作为降级
      }
    })
  } catch {
    // KaTeX 加载失败时保留原始 TeX
  }
}

async function paintMermaid() {
  const box = msgBoxRef.value
  if (!box) return
  const slots = [...box.querySelectorAll('.mermaid-slot:not([data-painted])')]
  if (!slots.length) return
  try {
    mermaidPromise = mermaidPromise || import('mermaid').then((mod) => mod.default)
    const mermaid = await mermaidPromise
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: document.documentElement.classList.contains('dark') ? 'dark' : 'neutral',
      fontFamily: 'inherit',
    })
    for (const el of slots) {
      el.setAttribute('data-painted', '1')
      const code = decodeURIComponent(el.dataset.mermaid || '')
      try {
        const { svg } = await mermaid.render(`mermaid-${++mermaidSeq}`, code)
        el.innerHTML = DOMPurify.sanitize(svg, {
          USE_PROFILES: { svg: true, svgFilters: true, html: true },
        })
      } catch {
        // 语法不完整/错误时保留源码兜底
        el.setAttribute('data-error', '1')
      }
    }
  } catch {
    // Mermaid 加载失败时保留源码兜底
  }
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
  if (streaming.value || interviewExpired.value) return
  input.value = text
  send()
}

// ---------- 可选面试倒计时 ----------
function formatDuration(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function isInterviewSummary(message = '') {
  return ['结束面试', '面试结束', '总结', '打分', '结束吧']
    .some(keyword => message.includes(keyword))
}

function startAutoSummary() {
  if (autoSummaryStarted || !interviewExpired.value || streaming.value) return
  autoSummaryStarted = true
  const content = '结束面试，请总结本次面试并给出四维评分和综合评分。'
  messages.value.push({ role: 'user', content, sources: [], attachments: [] })
  const body = {
    message: content,
    attachments: [],
    session_id: sessionId.value || undefined,
    course_id: props.courseId,
    collaborate: false,
    branch: props.branch || 'interview',
  }
  if (props.interviewAssignmentId != null) {
    body.interview_assignment_id = props.interviewAssignmentId
  }
  runStream(props.endpoint, body)
}

function expireInterview() {
  if (interviewExpired.value) return
  clearInterval(interviewTimer)
  interviewTimer = null
  interviewExpired.value = true
  startAutoSummary()
}

function tickInterviewTimer() {
  const next = Math.max(0, Math.ceil((interviewDeadline - Date.now()) / 1000))
  if (next !== remainingSeconds.value) {
    remainingSeconds.value = next
    emit('time-update', next)
  }
  if (next <= 0) expireInterview()
}

function startInterviewTimer() {
  if (!Number.isFinite(props.durationMinutes) || props.durationMinutes <= 0) return
  const totalSeconds = Math.max(1, Math.round(props.durationMinutes * 60))
  remainingSeconds.value = totalSeconds
  interviewDeadline = Date.now() + totalSeconds * 1000
  emit('time-update', totalSeconds)
  interviewTimer = setInterval(tickInterviewTimer, 1000)
}

// ---------- 图片识题 ----------

function pickImage() {
  if (streaming.value || uploadingImage.value || interviewExpired.value) return
  if (!features.vision_ready) {
    ElMessage.warning('识图服务未配置，请直接输入题目文字')
    return
  }
  imageInput.value?.click()
}

function pickCameraImage() {
  if (streaming.value || uploadingImage.value || interviewExpired.value) return
  if (!features.vision_ready) {
    ElMessage.warning('识图服务未配置，请直接输入题目文字')
    return
  }
  cameraInput.value?.click()
}

function removeImage(index) {
  pendingImages.value.splice(index, 1)
}

/** 上传前压缩:长边不超过 1600，转 JPEG；小图保持原样 */
function compressImage(file) {
  return new Promise((resolve) => {
    if (!file.type.startsWith('image/') || file.size < 300 * 1024) {
      resolve(file)
      return
    }
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      URL.revokeObjectURL(url)
      const maxSide = 1600
      const scale = Math.min(1, maxSide / Math.max(img.width, img.height))
      if (scale >= 1 && file.size < 1024 * 1024) {
        resolve(file)
        return
      }
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(img.width * scale))
      canvas.height = Math.max(1, Math.round(img.height * scale))
      const ctx = canvas.getContext('2d')
      ctx.fillStyle = '#fff'
      ctx.fillRect(0, 0, canvas.width, canvas.height)
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height)
      canvas.toBlob((blob) => {
        if (!blob) {
          resolve(file)
          return
        }
        const name = (file.name || 'image').replace(/\.[^.]+$/, '') + '.jpg'
        resolve(new File([blob], name, { type: 'image/jpeg' }))
      }, 'image/jpeg', 0.9)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      resolve(file)
    }
    img.src = url
  })
}

async function onImageChange(event) {
  const files = [...(event.target.files || [])]
  event.target.value = ''
  await addImageFiles(files)
}

function onPaste(event) {
  if (interviewExpired.value) return
  const items = [...(event.clipboardData?.items || [])]
  const files = items
    .filter((item) => item.type && item.type.startsWith('image/'))
    .map((item) => item.getAsFile())
    .filter(Boolean)
  if (!files.length) return
  event.preventDefault()
  addImageFiles(files)
}

async function addImageFiles(files) {
  if (!files.length || interviewExpired.value) return
  if (!features.vision_ready) {
    ElMessage.warning('识图服务未配置，请直接输入题目文字')
    return
  }

  const room = MAX_IMAGES - pendingImages.value.length
  if (room <= 0) {
    ElMessage.warning(`一次最多上传 ${MAX_IMAGES} 张图片`)
    return
  }
  const selected = files.slice(0, room)
  if (files.length > room) {
    ElMessage.warning(`一次最多 ${MAX_IMAGES} 张，已忽略多余图片`)
  }

  uploadingImage.value = true
  try {
    const prepared = []
    for (const file of selected) {
      prepared.push(await compressImage(file))
    }
    const data = await uploadApi.images(prepared)
    if (!data.vision_enabled) {
      ElMessage.warning('识图服务未配置，图片未加入待发送列表，请直接输入题目文字')
      return
    }
    const items = data.items || []
    items.forEach((item, idx) => {
      if (item.path) {
        pendingImages.value.push({
          path: item.path,
          filename: selected[idx]?.name || '',
          size: selected[idx]?.size || 0,
          text: item.text || '',
          description: item.description || '',
          visionEnabled: true,
          error: item.error || '',
        })
      }
      if (item.error) ElMessage.warning(item.error)
    })
  } catch { /* 拦截器已提示 */ } finally {
    uploadingImage.value = false
  }
}

// ---------- 语音输入 ----------

async function toggleRecording() {
  if (uploadingAudio.value || streaming.value || interviewExpired.value) return
  if (!features.asr_ready) {
    ElMessage.warning('语音识别未配置，请使用文字输入')
    return
  }
  if (recording.value) {
    stopRecording()
    return
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    ElMessage.warning('当前浏览器不支持录音，请改用文字输入')
    return
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mr = new MediaRecorder(stream)
    audioChunks = []
    mr.ondataavailable = (event) => {
      if (event.data?.size) audioChunks.push(event.data)
    }
    mr.onstop = async () => {
      stream.getTracks().forEach((track) => track.stop())
      clearInterval(audioTimer)
      audioTimer = null
      recording.value = false
      recordingSeconds.value = 0
      const type = mr.mimeType || 'audio/webm'
      const blob = new Blob(audioChunks, { type })
      if (!blob.size) return
      const ext = type.includes('ogg') ? 'ogg' : 'webm'
      await uploadVoice(new File([blob], `voice.${ext}`, { type }))
    }
    mr.start()
    recorder = mr
    recording.value = true
    recordingSeconds.value = 0
    audioTimer = setInterval(() => {
      recordingSeconds.value += 1
      // 单次录音上限 120 秒，避免超长音频拖垮识别
      if (recordingSeconds.value >= 120) stopRecording()
    }, 1000)
  } catch (error) {
    ElMessage.warning(microphoneErrorMessage(error))
  }
}

function stopRecording() {
  if (recorder && recorder.state === 'recording') recorder.stop()
}

async function uploadVoice(file) {
  uploadingAudio.value = true
  try {
    const data = await uploadApi.audio(file)
    const text = (data.text || '').trim()
    if (text) {
      input.value = input.value ? `${input.value} ${text}` : text
      audioSource.value = audioSource.value ? `${audioSource.value} ${text}` : text
      ElMessage.success('语音已转文字，请确认后发送')
    }
  } catch { /* 拦截器已提示(未配置/超时/失败) */ } finally {
    uploadingAudio.value = false
  }
}

function releaseRecorder() {
  clearInterval(audioTimer)
  audioTimer = null
  if (recorder && recorder.state === 'recording') {
    recorder.stream?.getTracks?.().forEach((track) => track.stop())
    recorder.stop()
  }
  recorder = null
}

// ---------- AI 回答朗读 ----------

function stopAnswerSpeech() {
  stopSpeech()
  speakingIndex.value = -1
}

async function toggleSpeech(msg, index) {
  if (speakingIndex.value === index) {
    stopAnswerSpeech()
    return
  }
  if (!isSpeechSupported()) {
    ElMessage.warning('当前浏览器不支持朗读，请更换浏览器后重试')
    return
  }
  speakingIndex.value = index
  await speakMarkdown(msg.content, {
    onEnd() {
      if (speakingIndex.value === index) speakingIndex.value = -1
    },
    onError() {
      if (speakingIndex.value === index) speakingIndex.value = -1
      ElMessage.warning('朗读失败，请稍后重试')
    },
  })
}

// ---------- 历史对话侧栏 ----------

// 会话列表接口全量返回,条数可能超百,分批增量挂载避免长列表一次性渲染卡顿
const LIST_INITIAL = 60
const LIST_STEP = 40
const visibleCount = ref(LIST_INITIAL)
const visibleConversations = computed(() => conversations.value.slice(0, visibleCount.value))
const sentinelRef = ref(null)
let listObserver = null

watch(conversations, () => { visibleCount.value = LIST_INITIAL })

watch(sentinelRef, (el) => {
  if (!el) return
  if (!listObserver) {
    listObserver = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) visibleCount.value += LIST_STEP
    }, { rootMargin: '120px' })
  }
  listObserver.disconnect()
  listObserver.observe(el)
})

async function loadConversations() {
  if (!props.historyEnabled) return
  try {
    const keyword = searchKeyword.value.trim()
    const data = await chatApi.conversations(keyword ? { keyword } : {})
    conversations.value = data.items || []
  } catch { /* 历史列表失败不影响当前对话 */ }
}

async function toggleFavorite(item) {
  const next = !item.is_favorite
  try {
    const data = await chatApi.setFavorite(item.session_id, next)
    item.is_favorite = data.is_favorite
  } catch { /* 拦截器已提示 */ }
}

async function summarizeCurrent(refresh = false) {
  if (!sessionId.value) return ElMessage.warning('请先在左侧选择一条历史对话')
  summaryVisible.value = true
  summarizing.value = true
  if (!refresh) summaryText.value = ''
  try {
    const data = await chatApi.summarize(sessionId.value, refresh)
    summaryText.value = data.summary
    const item = conversations.value.find((c) => c.session_id === sessionId.value)
    if (item) item.has_summary = true
  } catch {
    summaryVisible.value = false
  } finally {
    summarizing.value = false
  }
}

async function exportCurrent() {
  if (!sessionId.value) return ElMessage.warning('请先在左侧选择一条历史对话')
  try {
    const blob = await chatApi.exportConversation(sessionId.value)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `itea_chat_${sessionId.value}.md`
    link.click()
    URL.revokeObjectURL(url)
    ElMessage.success('已导出 Markdown')
  } catch { /* 拦截器已提示 */ }
}

async function openConversation(item) {
  historyDrawerVisible.value = false
  if (streaming.value) return
  stopAnswerSpeech()
  try {
    const data = await chatApi.history(item.session_id)
    sessionId.value = item.session_id
    messages.value = (data.messages || []).map((m) => ({
      role: m.role,
      content: m.content,
      // 历史回填:run_id 恢复时间线/反馈入口,security_level 恢复信息级别徽标
      ...(m.run_id ? { runId: m.run_id } : {}),
      ...(m.security_level ? { securityLevel: m.security_level } : {}),
    }))
    input.value = ''
    pendingImages.value = []
    audioSource.value = ''
    scrollToBottom(true)
    nextTick(paintRich)
  } catch { /* 拦截器已提示 */ }
}

function newConversation() {
  historyDrawerVisible.value = false
  stopAnswerSpeech()
  cancelRecovery?.()
  cancelRecovery = null
  controller?.abort()
  controller = null
  streaming.value = false
  sessionId.value = ''
  messages.value = []
  input.value = ''
  audioSource.value = ''
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

function onEnter(event) {
  // 中文输入法组合态下回车用于上屏候选词,不触发发送
  if (event?.isComposing || event?.keyCode === 229) return
  event?.preventDefault?.()
  send()
}

function send() {
  const text = input.value.trim()
  const images = pendingImages.value
  if ((!text && !images.length && !audioSource.value) || streaming.value || interviewExpired.value) return

  const attachments = images.map((img) => ({
    type: 'image',
    path: img.path,
    filename: img.filename || '',
    size: img.size || 0,
    text: img.text || '',
    description: img.description || '',
  }))
  if (audioSource.value) {
    attachments.push({ type: 'audio', text: audioSource.value })
  }

  const sources = []
  if (images.length) sources.push(`${images.length} 张图片`)
  if (audioSource.value) sources.push('语音转写')
  const bubble = text || (sources.length ? '（多模态输入）' : '')

  messages.value.push({ role: 'user', content: bubble, sources, attachments })
  input.value = ''
  pendingImages.value = []
  audioSource.value = ''

  const body = {
    message: text,
    attachments,
    session_id: sessionId.value || undefined,
    course_id: props.courseId,
    collaborate: collaborate.value,
  }
  if (props.branch) body.branch = props.branch
  if (props.reviewSubmit) body.review_submit = true
  if (props.interviewAssignmentId != null) {
    body.interview_assignment_id = props.interviewAssignmentId
  }
  runStream(props.endpoint, body)
  emit('sent', body)
}

function agentLabel(agent) {
  return {
    teacher: '备课专家',
    tutor: '答疑专家',
    review: '错题复盘专家',
    interview: '面试实训专家',
    admin: '平台管理专家',
  }[agent] || agent
}

function formatClock(value) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

/** 查看一次运行的步骤时间线 */
async function openTimeline(msg) {
  if (!msg.runId) return
  timelineVisible.value = true
  timelineLoading.value = true
  timelineRun.value = null
  timelineSummary.value = null
  timelineItems.value = []
  expandedTimeline.value = []
  try {
    const data = await agentApi.timeline(msg.runId)
    timelineRun.value = data.run
    timelineSummary.value = data.summary
    timelineItems.value = data.timeline || []
  } catch {
    timelineRun.value = null
  } finally {
    timelineLoading.value = false
  }
}

function isTimelineOpen(item) {
  return expandedTimeline.value.includes(item?.seq)
}

function toggleTimeline(item) {
  if (!item || item.seq === undefined) return
  const index = expandedTimeline.value.indexOf(item.seq)
  if (index >= 0) expandedTimeline.value.splice(index, 1)
  else expandedTimeline.value.push(item.seq)
}

/** 时间线明细只做可读化,单条截断防止超长 payload 撑爆弹窗 */
function formatSpanValue(value) {
  if (value === null || value === undefined) return ''
  const text = typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  return text.length > 2000 ? `${text.slice(0, 2000)}…` : text
}

/** 对回答点赞/点踩,关联当前运行便于后续评估 */
async function sendFeedback(msg, rating) {
  if (!msg.runId || msg.feedback) return
  try {
    await agentApi.feedback({
      rating,
      run_id: msg.runId,
      session_id: sessionId.value || undefined,
    })
    msg.feedback = rating
    ElMessage.success('感谢反馈')
  } catch {
    // http 拦截器已提示错误
  }
}

/** 运行中途调整计划:提交后在下一步生效 */
function openPlanDialog() {
  if (!currentRunId.value) {
    ElMessage.warning('当前没有可调整的运行')
    return
  }
  planInstruction.value = ''
  planVisible.value = true
}

async function submitPlanRevision() {
  const text = planInstruction.value.trim()
  if (!text || !currentRunId.value) return
  planSubmitting.value = true
  try {
    await agentApi.revisePlan(currentRunId.value, text)
    const last = messages.value[messages.value.length - 1]
    last?.statusList?.push({
      type: 'info', icon: 'EditPen', text: `计划调整已提交:${text}`,
    })
    planVisible.value = false
    ElMessage.success('已提交,将在下一步生效')
  } catch {
    // http 拦截器已提示(任务已结束/超出次数等)
  } finally {
    planSubmitting.value = false
  }
}

/** 查看并删除自己的长期记忆 */
async function openMemories() {
  memoryVisible.value = true
  memoryLoading.value = true
  try {
    const data = await agentApi.memories({ limit: 100 })
    memories.value = data.items || []
  } catch {
    memories.value = []
  } finally {
    memoryLoading.value = false
  }
}

async function removeMemory(id) {
  try {
    await ElMessageBox.confirm(
      '删除后该条长期记忆不可恢复，确认删除？', '提示', { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await agentApi.deleteMemory(id)
    memories.value = memories.value.filter((item) => item.id !== id)
    ElMessage.success('已删除该条记忆')
  } catch {
    // http 拦截器已提示错误
  }
}

// 信息级别的文案与说明共用同一 key 集合,避免徽标有值而悬浮提示为空
const SECURITY_META = {
  full: { label: '完全审批', desc: '公开或低敏内容，直接输出' },
  auto: { label: '自动审批', desc: '内部内容，规则校验后输出' },
  manual: { label: '手动审批', desc: '敏感或机密内容，需授权角色查看' },
  public: { label: '完全审批', desc: '公开内容，直接输出' },
  internal: { label: '自动审批', desc: '内部内容，规则校验后输出' },
  sensitive: { label: '手动审批', desc: '敏感内容，需授权角色查看' },
  confidential: { label: '手动审批', desc: '机密内容，仅授权角色可查看' },
}

function securityLabel(level) {
  return SECURITY_META[level]?.label || level
}

function securityDesc(level) {
  return SECURITY_META[level]?.desc || ''
}

function riskLabel(level) {
  return { high: '高风险', medium: '中风险', low: '低风险' }[level] || '中风险'
}

/** 确认执行预览中的写动作:凭令牌调用后端,成功后卡片转为已执行 */
async function confirmAction(msg) {
  const card = msg.confirm
  if (!card || card.status !== 'pending' || card.loading) return
  card.loading = true
  card.error = ''
  try {
    let data
    if (card.kind === 'tool') {
      // 通用高危工具(如复习提醒):令牌绑定会话/参数,确认后才执行
      if (!sessionId.value) {
        card.status = 'error'
        card.error = '会话尚未建立，请重新发起'
        return
      }
      data = await chatApi.confirmTool({
        session_id: sessionId.value,
        tool: card.tool,
        arguments: card.arguments || {},
        token: card.token,
      })
    } else {
      data = await adminApi.executeAction({
        action: card.action,
        params: card.params,
        confirmation_token: card.token,
        idempotency_key: card.idempotencyKey,
      })
    }
    if (data?.ok) {
      card.status = 'done'
      card.result = data.message || '已完成'
    } else {
      card.status = 'error'
      card.error = data?.message || '执行失败，请重新发起'
    }
  } catch (err) {
    card.status = 'error'
    card.error = err.response?.data?.detail || err.message || '执行失败，请重新发起'
  } finally {
    card.loading = false
  }
}

/** 取消:只关闭卡片,不发送任何写请求,数据保持原样 */
function cancelConfirm(msg) {
  if (!msg.confirm || msg.confirm.status !== 'pending') return
  msg.confirm.loading = false
  msg.confirm.status = 'cancelled'
}

function runStream(url, body) {
  const assistantMsg = reactive({
    role: 'assistant',
    content: '',
    streaming: true,
    stepsOpen: true,
    statusList: [],
    securityLevel: '',
    error: '',
    reconnecting: false,
    confirm: null,
    interviewSummary: isInterviewSummary(body.message),
  })
  messages.value.push(assistantMsg)
  attachStream(assistantMsg, url, body)
}

/** 生成前端幂等键:同一次提问的新建/重试/断线续答共用 */
function newRequestId() {
  return window.crypto?.randomUUID?.()
    || `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

/** 把 SSE 事件写入指定助手消息(新建与重试共用) */
function attachStream(assistantMsg, url, body) {
  assistantMsg.requestId = resolveRequestId(body, newRequestId)
  streamReset(assistantMsg)
  streaming.value = true
  atBottom.value = true
  scrollToBottom()

  let recovering = false
  let pending = false
  let cancelled = false
  const cancelThis = () => { cancelled = true }
  cancelRecovery = cancelThis
  const finish = () => {
    // 收尾：冲刷剩余草稿进段落缓存，并把全文回写 content 供复制/朗读等使用
    streamFlush(assistantMsg, true)
    assistantMsg.content = assistantMsg._fullText || assistantMsg.content
    assistantMsg.reconnecting = false
    assistantMsg.streaming = false
    // 结束后收起处理过程，正文保持主视觉
    if (assistantMsg.statusList.length) assistantMsg.stepsOpen = false
    streaming.value = false
    atBottom.value = true
    scrollToBottom()
    nextTick(paintRich)
    if (cancelRecovery === cancelThis) cancelRecovery = null
    if (interviewExpired.value && !autoSummaryStarted) startAutoSummary()
  }

  const wait = (ms) => new Promise(resolve => setTimeout(resolve, Math.max(0, ms)))

  /** 连接中断或重复请求仍在生成时，按同一幂等键在预算内恢复完整答案 */
  const recoverAnswer = async (showReconnectHint = false) => {
    if (recovering) return
    recovering = true
    assistantMsg.error = ''
    if (showReconnectHint) assistantMsg.reconnecting = true
    assistantMsg.streaming = true
    streaming.value = true
    const deadline = recoveryDeadline()
    try {
      let attempt = 0
      let polls = 0
      while (
        !cancelled && polls < MAX_RECOVERY_ATTEMPTS
        && remainingBudgetMs(deadline) > 0
      ) {
        polls += 1
        try {
          const data = await chatApi.answer(assistantMsg.requestId)
          if (data.session_id) sessionId.value = data.session_id
          if (data.security_level) assistantMsg.securityLevel = data.security_level
          if (data.status === 'done' || data.status === 'blocked') {
            // 整段回放：先清空流式缓冲，正文走 content 渲染路径
            assistantMsg.closedHtml = undefined
            assistantMsg.tailHtml = undefined
            assistantMsg._draft = ''
            assistantMsg._fullText = ''
            assistantMsg.content = data.content || '(未收到回复,请重试)'
            finish()
            loadConversations()
            return
          }
          if (data.status === 'cancelled') {
            assistantMsg.closedHtml = undefined
            assistantMsg.tailHtml = undefined
            assistantMsg._draft = ''
            assistantMsg._fullText = ''
            assistantMsg.content = data.content || '(任务已取消)'
            finish()
            return
          }
          if (data.status === 'error') {
            throw new Error(data.error || '回答生成失败，请重试')
          }
        } catch (err) {
          // 401/403 等确定性错误不重试，交由调用方统一处理
          if (!isRecoverableError(err)) throw err
          const backoff = Math.min(
            nextBackoffMs(attempt), remainingBudgetMs(deadline),
          )
          if (backoff <= 0) break
          attempt += 1
          await wait(backoff)
          continue
        }
        const pause = Math.min(2000, remainingBudgetMs(deadline))
        if (pause <= 0) break
        await wait(pause)
      }
      if (cancelled) return
      throw new Error('连接中断，自动恢复超时，请点击重试')
    } catch (err) {
      if (cancelled) return
      assistantMsg.reconnecting = false
      assistantMsg.error = err.response?.data?.detail || err.message || '连接失败，请检查网络后重试'
      finish()
    } finally {
      recovering = false
    }
  }

  controller = ssePost(url, body, {
    onEvent(evt) {
      const { type, data } = evt
      if (type === 'run') {
        assistantMsg.runId = data.run_id
      } else if (type === 'branch') {
        const labels = {
          teacher: '备课模式', tutor: '课程助教', review: '错题复盘',
          interview: '面试实训', admin: '管理助手', block: '风控拦截',
          team: '多 Agent 协作',
        }
        assistantMsg.statusList.push({
          type: data.branch === 'block' ? 'danger' : 'info',
          icon: 'Guide',
          text: labels[data.branch] || data.branch,
        })
      } else if (type === 'collab_plan' && data.source === 'single') {
        assistantMsg.statusList.push({
          type: 'info', icon: 'Guide',
          text: `单 Agent 处理：${agentLabel(data.branch)}`,
        })
      } else if (type === 'collab_plan') {
        const labels = (data.plan || [])
          .map((p) => p.label || agentLabel(p.agent))
          .join(' + ')
        assistantMsg.statusList.push({
          type: 'info', icon: 'Connection', text: `协作计划：${labels || '多专家'}`,
        })
      } else if (type === 'collab_step') {
        const label = data.label || agentLabel(data.agent)
        if (data.status === 'start') {
          const waiting = (data.depends_on || []).map(agentLabel).join('、')
          assistantMsg.statusList.push({
            type: 'info', icon: 'Loading',
            text: waiting ? `排队中：${label}（等待 ${waiting}）` : `协作中：${label}`,
            agent: data.agent, phase: 'start',
          })
        } else {
          const item = [...assistantMsg.statusList]
            .reverse()
            .find((s) => s.agent === data.agent && s.phase === 'start')
          const failed = data.status === 'error'
          if (item) {
            item.phase = 'end'
            item.type = failed ? 'warning' : 'success'
            item.icon = failed ? 'WarnTriangleFilled' : 'CircleCheck'
            item.text = `${label} ${failed ? '执行失败' : '已完成'}`
          } else {
            assistantMsg.statusList.push({
              type: failed ? 'warning' : 'success',
              icon: failed ? 'WarnTriangleFilled' : 'CircleCheck',
              text: `${label} ${failed ? '执行失败' : '已完成'}`,
            })
          }
        }
      } else if (type === 'risk') {
        assistantMsg.statusList.push({
          type: 'warning', icon: 'WarnTriangleFilled', text: `风控:${data.risk_type}`,
        })
      } else if (type === 'tool_call') {
        assistantMsg.statusList.push({
          type: 'success', icon: 'Tools', text: `调用工具:${data.name}`,
        })
      } else if (type === 'tool_result') {
        assistantMsg.statusList.push({
          type: data.ok ? 'success' : 'warning',
          icon: data.ok ? 'CircleCheck' : 'WarnTriangleFilled',
          text: data.message || (data.ok ? '任务已完成' : '任务未执行'),
        })
      } else if (type === 'confirm_required') {
        // 批量/高危写动作:先展示影响范围,确认后才真正执行
        assistantMsg.confirm = {
          kind: data.kind || '',
          tool: data.tool || '',
          arguments: data.arguments || {},
          action: data.action,
          params: data.params || {},
          label: data.label || '写操作',
          message: data.message || '',
          count: data.count,
          items: data.items || [],
          skipped: data.skipped || [],
          riskLevel: data.risk_level || 'medium',
          truncated: !!data.truncated,
          token: data.confirmation_token || '',
          idempotencyKey: data.idempotency_key || '',
          status: data.confirmation_token ? 'pending' : 'error',
          error: data.confirmation_token ? '' : '确认令牌缺失，请重新发起',
          result: '',
          loading: false,
        }
      } else if (type === 'reflect') {
        assistantMsg.statusList.push({
          type: 'warning', icon: 'Refresh', text: `反思校验(第${data.round}轮)`,
        })
      } else if (type === 'plan_revised') {
        const text = (data.instructions || []).join('；')
        assistantMsg.statusList.push({
          type: 'success', icon: 'EditPen', text: `计划已调整:${text}`,
        })
      } else if (type === 'token') {
        // 段落级缓冲：token 只进草稿，遇到完整段落才渲染，避免全文重渲染闪烁
        assistantMsg._draft += data.content
        assistantMsg._fullText += data.content
        streamFlush(assistantMsg, false)
        if (atBottom.value) scrollToBottom()
      } else if (type === 'reset') {
        // 反思校验未通过：后端会带意见重写，先丢弃已流出的草稿
        streamReset(assistantMsg)
      } else if (type === 'security') {
        assistantMsg.securityLevel = data.level || ''
        if (data.blocked) {
          ElMessage.warning('该回答包含受限信息，已按权限隐藏')
        }
      } else if (type === 'done') {
        if (data.session_id) sessionId.value = data.session_id
        if (data.security_level) assistantMsg.securityLevel = data.security_level
      } else if (type === 'error') {
        if (data.message?.includes('相同请求正在处理中')) {
          pending = true
        } else {
          assistantMsg._draft += `\n\n> ⚠️ ${data.message}`
          assistantMsg._fullText += `\n\n> ⚠️ ${data.message}`
          streamFlush(assistantMsg, false)
        }
      }
    },
    onDone() {
      if (pending) {
        recoverAnswer()
        return
      }
      if (!assistantMsg._fullText && !assistantMsg.content) {
        assistantMsg.content = '(未收到回复,请重试)'
      }
      finish()
      loadConversations()
    },
    onError(err) {
      // 401 与全局拦截器一致:清除登录态并跳转登录
      if (err?.status === 401) {
        localStorage.removeItem('itea_token')
        localStorage.removeItem('itea_user')
        assistantMsg.error = '登录已失效，请重新登录'
        finish()
        if (location.pathname !== '/login') location.href = '/login'
        return
      }
      // 403 及其余确定性 4xx 不自动恢复,避免无意义轮询
      if (!isRecoverableError(err)) {
        assistantMsg.error = err?.message || '请求失败，请稍后重试'
        finish()
        return
      }
      // 网络断开/5xx:显示重连提示,预算内自动恢复
      recoverAnswer(true)
    },
  })
}

/** 供外部（如管理端任务快捷入口）直接发起一轮提问 */
defineExpose({ ask: quickSend })

onMounted(() => {
  if (!features.loaded) loadFeatures()
  startInterviewTimer()
  loadConversations()
  // 面试实训等场景:进入即由后端结构化入口开启首轮流式输出
  if (props.startEndpoint) {
    runStream(props.startEndpoint, props.startBody || {})
  }
})

// 离开页面（切路由 / 关闭标签）时必须断开 SSE：
// 否则请求会在后端继续生成，长时间占用 LLM 调用与数据库连接，最终拖垮整个服务。
onBeforeUnmount(() => {
  stopAnswerSpeech()
  cancelRecovery?.()
  cancelRecovery = null
  controller?.abort()
  controller = null
  clearInterval(interviewTimer)
  releaseRecorder()
  listObserver?.disconnect()
})

function abort() {
  const last = messages.value[messages.value.length - 1]
  // 通知后端真正取消运行,而不只是断开前端连接
  if (last?.runId) {
    agentApi.cancelRun(last.runId).catch(() => {})
  }
  cancelRecovery?.()
  cancelRecovery = null
  controller?.abort()
  streaming.value = false
  if (last?.streaming) {
    last.streaming = false
    last.reconnecting = false
    if (last.statusList?.length) last.stepsOpen = false
    // ssePost 捕获 AbortError 后直接返回不触发 finish，需自行冲刷缓冲并回写全文
    if (last.closedHtml !== undefined && last.closedHtml !== null) {
      streamFlush(last, true)
      last.content = last._fullText || '(已停止生成)'
    } else if (!last.content) {
      last.content = '(已停止生成)'
    }
  }
  if (interviewExpired.value && !autoSummaryStarted) startAutoSummary()
}

/** 重试：复用同一幂等键，已完成回答直接回放，避免重复生成与落库 */
function retry(msg) {
  if (streaming.value || (interviewExpired.value && !msg.interviewSummary)) return
  msg.error = ''
  msg.content = ''
  msg.confirm = null
  msg.statusList.splice(0)
  const body = lastBody()
  body.request_id = msg.requestId || newRequestId()
  const hasUserMessage = messages.value.some(m => m.role === 'user')
  const url = hasUserMessage ? props.endpoint : (props.startEndpoint || props.endpoint)
  attachStream(msg, url, body)
}

/** 重新生成最后一条回复：丢弃末尾助手消息，用最后一条用户提问重跑 */
function regenerate(msg) {
  if (streaming.value || interviewExpired.value) return
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
    collaborate: collaborate.value,
    ...(props.branch ? { branch: props.branch } : {}),
    ...(props.reviewSubmit ? { review_submit: true } : {}),
    ...(props.interviewAssignmentId != null
      ? { interview_assignment_id: props.interviewAssignmentId } : {}),
  })
}

function lastBody() {
  const lastUser = [...messages.value].reverse().find(m => m.role === 'user')
  if (!lastUser) return props.startBody || {}
  return {
    message: lastUser.content,
    session_id: sessionId.value || undefined,
    course_id: props.courseId,
    collaborate: collaborate.value,
    ...(props.branch ? { branch: props.branch } : {}),
    ...(props.reviewSubmit ? { review_submit: true } : {}),
    ...(props.interviewAssignmentId != null
      ? { interview_assignment_id: props.interviewAssignmentId } : {}),
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
.chat-side__sentinel { height: 1px; }
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
  opacity: 0.45;
  transition: opacity var(--dur-fast) var(--ease);
}
.chat-side__item:hover .chat-side__del {
  opacity: 1;
}
@media (hover: none) {
  .chat-side__del {
    opacity: 1;
  }
}
.chat-side__del:hover {
  color: var(--danger-600);
}
.chat-side__search {
  padding: 0 8px 8px;
}
.chat-side__tools {
  display: flex;
  gap: 6px;
  padding: 0 8px 8px;
}
.chat-side__tools button {
  flex: 1;
  padding: 6px 0;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--bg-card);
  color: var(--text-secondary);
  font-size: var(--fs-xs);
  cursor: pointer;
}
.chat-side__tools button:hover {
  color: var(--brand-700);
  border-color: var(--brand-300);
}
.chat-side__star {
  display: grid;
  place-items: center;
  padding: 0;
  border: none;
  background: none;
  color: var(--text-placeholder);
  cursor: pointer;
  opacity: 0.45;
  transition: opacity var(--dur-fast) var(--ease);
}
.chat-side__item:hover .chat-side__star,
.chat-side__star.is-on {
  opacity: 1;
}
@media (hover: none) {
  .chat-side__star {
    opacity: 1;
  }
}
.chat-side__star.is-on {
  color: var(--color-warning, #d48806);
}
.chat-summary {
  margin: 0;
  min-height: 60px;
  font-size: var(--fs-sm);
  line-height: var(--lh-base);
  color: var(--text-primary);
  white-space: pre-wrap;
}
.chat-side__empty {
  padding: var(--sp-4) 0;
  text-align: center;
  font-size: var(--fs-xs);
  color: var(--text-placeholder);
}

.chat__images {
  display: flex;
  flex-direction: column;
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
.msg__sources {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.msg__sources span {
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.18);
  font-size: 11px;
  letter-spacing: 0.02em;
}
/* 用户消息的附件卡片（AG-15） */
.msg__files {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.msg__file {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 100%;
  padding: 3px 8px;
  border-radius: var(--r-sm);
  background: rgba(255, 255, 255, 0.9);
  color: var(--text-secondary);
  font-size: 11px;
  line-height: 1.4;
}
.msg__file-type {
  font-style: normal;
  font-weight: 600;
  color: var(--color-primary);
}
.msg__file-name {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.msg__file-size {
  color: var(--text-placeholder);
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
.msg__security {
  margin-bottom: var(--sp-1);
  font-size: var(--fs-xs);
  color: var(--text-tertiary, var(--text-secondary));
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
  /* 方案 2.4：打字光标呼吸闪烁，比硬切 blink 更柔和 */
  animation: cursorBreath 1s var(--ease) infinite;
}
@keyframes cursorBreath {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.15; }
}
@media (prefers-reduced-motion: reduce) {
  .msg__cursor { animation: none; }
}

/* 未闭合代码块/公式的流式占位：浅灰提示，避免半截内容闪烁 */
.stream-pending {
  margin: var(--sp-2) 0;
  font-size: var(--fs-xs);
  color: var(--text-tertiary, var(--text-secondary));
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

/* ===== 写操作确认卡片 ===== */
.confirm-card {
  margin-top: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  background: var(--bg-card);
  border: 1px solid var(--border-strong);
  border-left: 3px solid var(--warning-600);
  border-radius: var(--r-md);
}
.confirm-card.is-done { border-left-color: var(--success-600); }
.confirm-card.is-cancelled { border-left-color: var(--text-placeholder); opacity: 0.75; }
.confirm-card.is-error { border-left-color: var(--danger-600); }
.confirm-card__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-weight: 600;
}
.confirm-card__title { font-size: var(--fs-sm); }
.confirm-card__risk {
  margin-left: auto;
  padding: 1px 8px;
  font-size: var(--fs-xs);
  font-style: normal;
  border-radius: var(--r-pill);
}
.confirm-card__risk.is-high { color: var(--danger-600); background: var(--color-danger-soft); }
.confirm-card__risk.is-medium { color: var(--warning-600); background: var(--color-warning-soft); }
.confirm-card__risk.is-low { color: var(--success-600); background: var(--bg-subtle); }
.confirm-card__summary {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-sm);
  color: var(--text-primary);
}
.confirm-card__list {
  margin: var(--sp-2) 0 0;
  padding-left: var(--sp-4);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.confirm-card__list li { display: flex; gap: var(--sp-2); }
.confirm-card__list em { font-style: normal; color: var(--text-placeholder); }
.confirm-card__hint,
.confirm-card__state {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.confirm-card__state.is-error { color: var(--danger-600); }
.confirm-card__actions {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-3);
}

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
/* 断线自动恢复中的进行时提示 */
.msg__reconnecting {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--fs-xs);
  color: var(--warning-600);
  background: var(--color-warning-soft);
  border-radius: var(--r-sm);
}
.msg__actions {
  display: flex;
  gap: var(--sp-1);
  margin-top: var(--sp-3);
  /* 触屏没有 hover,操作条必须常显;桌面端弱化存在感,悬浮恢复 */
  opacity: 0.6;
  transition: opacity var(--dur-fast) var(--ease);
}
.msg:hover .msg__actions {
  opacity: 1;
}
@media (hover: none) {
  .msg__actions {
    opacity: 1;
  }
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
.chat__foot-left {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  min-width: 0;
}
.chat__collab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  cursor: pointer;
  white-space: nowrap;
}
.chat__hint {
  font-size: var(--fs-xs);
  color: var(--text-placeholder);
}
.chat__timer {
  flex: 0 0 auto;
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
  color: var(--brand-700);
  white-space: nowrap;
}
.chat__timer.is-expired { color: var(--danger-600); }
.chat__composer-actions {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
}
.chat__recording {
  font-size: var(--fs-xs);
  color: var(--color-danger, #d9534f);
}
.chat__composer-actions .is-recording {
  color: var(--color-danger, #d9534f);
}

.chat-side__backdrop,
.chat__mobile-bar {
  display: none;
}
.chat__mobile-bar {
  padding: 8px 12px 0;
}

@media (max-width: 900px) {
  /* 历史侧栏切换为抽屉:复用同一列表与加载/切换逻辑 */
  .chat-side {
    position: fixed;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 2001;
    width: min(86vw, 320px);
    flex: none;
    border-radius: 0;
    transform: translateX(-100%);
    transition: transform var(--dur) var(--ease);
  }
  .chat-side.is-open {
    transform: translateX(0);
  }
  .chat-side__backdrop {
    position: fixed;
    inset: 0;
    z-index: 2000;
    background: rgba(0, 0, 0, 0.42);
  }
  .chat__mobile-bar {
    display: flex;
  }
  .chat__history-btn {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    min-height: 36px;
    padding: 0 12px;
    border: 1px solid var(--border);
    border-radius: var(--r-sm);
    background: var(--bg-topbar);
    color: var(--text-secondary);
    font-size: var(--fs-xs);
    cursor: pointer;
  }
  .chat__scroll { padding: var(--sp-4); }
  .msg--assistant .msg__main { max-width: 100%; }
  .msg__bubble { max-width: 88%; }
}

@media (max-width: 600px) {
  .chat__composer-foot {
    flex-wrap: wrap;
  }
  .chat__composer-actions {
    flex-wrap: wrap;
  }
  .chat__hint {
    display: none;
  }
  .chat__composer-actions :deep(.el-button) {
    min-width: 44px;
    min-height: 44px;
  }
  .msg__actions {
    opacity: 1;
  }
  .msg__action {
    min-height: 44px;
  }
}
.run-timeline__meta {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.run-timeline__empty {
  padding: 18px 0;
  text-align: center;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.run-timeline__error {
  font-size: 13px;
  color: var(--el-color-danger);
}
.run-timeline__list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 360px;
  overflow-y: auto;
}
.run-timeline__item {
  padding: 2px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
  font-size: 13px;
}
.run-timeline__row {
  display: grid;
  grid-template-columns: 24px minmax(56px, auto) 1fr 64px;
  gap: 8px;
  align-items: center;
  width: 100%;
  padding: 8px 10px;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.run-timeline__row:hover { background: var(--el-fill-color-lighter); }
.run-timeline__item.is-error { color: var(--el-color-danger); }
.run-timeline__item.is-blocked { color: var(--el-color-warning); }
.run-timeline__body {
  padding: 4px 10px 10px 42px;
  color: var(--el-text-color-regular);
}
.run-timeline__label {
  margin: 6px 0 2px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.run-timeline__pre {
  margin: 0;
  padding: 8px;
  max-height: 200px;
  overflow: auto;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  background: var(--el-fill-color-lighter);
  border-radius: 6px;
}
.run-timeline__seq { color: var(--el-text-color-placeholder); }
.run-timeline__kind { color: var(--el-text-color-secondary); }
.run-timeline__name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-timeline__cost {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.memory-list {
  max-height: 360px;
  overflow-y: auto;
}
.memory-item {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.memory-item__content {
  margin: 0 0 4px;
  font-size: 13px;
  line-height: 1.6;
}
.memory-item__meta {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* 类 DeepSeek / 千问 / 豆包的对话界面:轻量侧栏、无气泡助手消息、大圆角输入区 */
.chat-shell {
  gap: 0;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--bg-card);
}

/* ---------- 侧栏 ---------- */
.chat-side {
  width: 256px;
  flex: 0 0 256px;
  padding: 10px;
  gap: 8px;
  background: var(--bg-subtle);
  border: none;
  border-right: 1px solid var(--border);
  border-radius: 0;
}
@media (max-width: 900px) {
  .chat-side {
    width: min(86vw, 320px);
    flex: none;
  }
}
.chat-side__new {
  justify-content: flex-start;
  gap: 8px;
  padding: 9px 12px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 10px;
}
.chat-side__new:hover {
  border-color: var(--brand-300);
  color: var(--brand-700);
}
.chat-side__search {
  padding: 0;
}
.chat-side__search :deep(.el-input__wrapper) {
  background: transparent;
  box-shadow: none;
  border: 1px solid transparent;
  border-radius: 8px;
  padding: 2px 8px;
}
.chat-side__search :deep(.el-input__wrapper:hover) {
  border-color: var(--border);
  background: var(--bg-card);
}
.chat-side__tools {
  gap: 4px;
  padding: 0;
}
.chat-side__tools button {
  padding: 5px 0;
  font-size: 12px;
  color: var(--text-placeholder);
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
}
.chat-side__tools button:hover {
  color: var(--text-primary);
  background: var(--bg-card);
  border-color: var(--border);
}
.chat-side__list {
  padding: 2px 0;
}
.chat-side__item {
  gap: 6px;
  padding: 9px 10px;
  margin-bottom: 2px;
  font-size: 13px;
  border-radius: 9px;
  color: var(--text-secondary);
}
.chat-side__item:hover {
  background: var(--bg-card);
}
.chat-side__item.is-active {
  background: var(--bg-card);
  color: var(--text-primary);
  font-weight: 500;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}
.chat-side__empty {
  padding: 24px 0;
  font-size: 12px;
}

/* ---------- 主区域 ---------- */
.chat {
  background: var(--bg-card);
  border: none;
  border-radius: 0;
}
.chat__scroll {
  padding: 26px 20px 10px;
}
.chat__scroll > * {
  width: 100%;
  max-width: 760px;
  margin-left: auto;
  margin-right: auto;
}

/* ---------- 空态 ---------- */
.chat__empty {
  max-width: 680px;
  margin: 12vh auto 0;
}
.chat__empty-mark {
  width: 54px;
  height: 54px;
  margin-bottom: 18px;
  border: none;
  border-radius: 50%;
  background: var(--grad-brand);
  color: #fff;
  font-family: inherit;
  font-size: 24px;
  font-weight: 600;
  box-shadow: var(--shadow-sm);
}
.chat__empty-title {
  font-family: inherit;
  font-size: 26px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.chat__empty-sub {
  margin-top: 8px;
  font-size: 14px;
  color: var(--text-placeholder);
}
.chat__chips {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 28px;
  text-align: left;
}
.chat__chip {
  padding: 12px 14px;
  font-size: 13px;
  line-height: 1.5;
  text-align: left;
  color: var(--text-secondary);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.chat__chip:hover {
  color: var(--text-primary);
  background: var(--bg-subtle);
  border-color: var(--border);
  transform: none;
  box-shadow: none;
}

/* ---------- 消息 ---------- */
.msg {
  gap: 12px;
  margin-bottom: 26px;
}
.msg__avatar {
  width: 26px;
  height: 26px;
  flex: 0 0 26px;
  border: none;
  border-radius: 50%;
  background: var(--brand-50);
  color: var(--brand-700);
}
.msg--user .msg__avatar {
  background: var(--grad-brand);
  color: #fff;
  box-shadow: none;
}
.msg__bubble {
  max-width: 78%;
  padding: 10px 14px;
  background: var(--bg-subtle);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 16px;
  border-top-right-radius: 16px;
  box-shadow: none;
  font-size: 15px;
  line-height: 1.7;
}
.msg__sources span {
  background: var(--bg-card);
  color: var(--text-secondary);
  border: 1px solid var(--border);
}
.msg__file {
  background: var(--bg-card);
  border: 1px solid var(--border);
}
.msg__who {
  margin-bottom: 6px;
  font-size: 12px;
  letter-spacing: 0;
  color: var(--text-placeholder);
}
.msg__live {
  color: var(--text-placeholder);
  background: transparent;
}
.msg__security {
  font-size: 11px;
  color: var(--text-placeholder);
}
.msg__md {
  font-size: 15px;
  line-height: 1.75;
}
.msg--assistant .msg__main {
  max-width: 100%;
}

/* 处理过程:弱化为一行可展开的轻量信息 */
.steps {
  max-width: 100%;
  margin-bottom: 10px;
  background: transparent;
  border: none;
  border-radius: 0;
}
.steps__head {
  padding: 3px 0;
  font-size: 12px;
  color: var(--text-placeholder);
}
.steps__head:hover {
  color: var(--text-secondary);
}
.steps__title em {
  margin-left: 6px;
  color: var(--text-placeholder);
}
.steps__list {
  padding: 4px 0 2px 2px;
  border-top: none;
}
.steps__item {
  padding: 3px 0;
  font-size: 12px;
  color: var(--text-placeholder);
}

/* ---------- 操作条 ---------- */
.msg__actions {
  gap: 2px;
  margin-top: 8px;
}
.msg__action {
  padding: 4px 8px;
  border: none;
  border-radius: 8px;
  color: var(--text-placeholder);
}
.msg__action:hover {
  color: var(--text-primary);
  background: var(--bg-subtle);
  border-color: transparent;
}
.msg__error {
  margin-top: 8px;
  font-size: 13px;
}

/* ---------- 输入区 ---------- */
.chat__composer {
  width: 100%;
  max-width: 800px;
  margin: 0 auto;
  padding: 6px 20px 18px;
  background: var(--bg-card);
  border-top: none;
}
.chat__composer :deep(.el-textarea__inner) {
  min-height: 56px !important;
  padding: 14px 16px;
  font-size: 15px;
  line-height: 1.6;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.05);
}
.chat__composer :deep(.el-textarea__inner:focus) {
  border-color: var(--brand-300);
  box-shadow: 0 2px 14px rgba(36, 104, 158, 0.12);
}
.chat__composer-foot {
  margin-top: 8px;
}
.chat__composer-actions {
  gap: 4px;
}
.chat__composer-actions :deep(.el-button) {
  border-radius: 9px;
}
.chat__composer-actions :deep(.chat__send) {
  width: 34px !important;
  height: 34px !important;
  margin-left: 4px;
  border-radius: 50%;
}
.chat__send {
  flex: 0 0 auto;
}
.chat__hint {
  font-size: 12px;
  color: var(--text-placeholder);
}
.chat__jump {
  bottom: 116px;
  border-radius: 999px;
  box-shadow: var(--shadow-sm);
}

@media (max-width: 900px) {
  .chat-shell { border-radius: 0; border-left: none; border-right: none; }
  .chat__scroll { padding: 18px 14px 8px; }
  .chat__composer { padding: 4px 12px 14px; }
  .chat__chips { grid-template-columns: 1fr; }
  .chat__empty-title { font-size: 22px; }
}
</style>
