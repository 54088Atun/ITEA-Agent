<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">在线考试</h2>
        <p class="page-sub">教师发布后可在线作答，客观题提交即自动判分</p>
      </div>
    </div>

    <div class="panel">
      <el-table :data="exams" v-loading="loading">
        <el-table-column prop="title" label="试卷" min-width="220" />
        <el-table-column label="课程" width="160">
          <template #default="{ row }">{{ row.course_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="题数" width="80">
          <template #default="{ row }">{{ row.question_count }}</template>
        </el-table-column>
        <el-table-column label="总分" width="80">
          <template #default="{ row }">{{ row.total_score }}</template>
        </el-table-column>
        <el-table-column label="截止" width="170">
          <template #default="{ row }">{{ formatTime(row.due_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="stateTag(row.state)" size="small" effect="light">
              {{ stateLabel(row.state) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="得分" width="90">
          <template #default="{ row }">
            <span v-if="row.score != null">{{ row.score }}</span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openExam(row)">查看 / 作答</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-state">暂无考试，教师发布后会出现在这里</div>
        </template>
      </el-table>
    </div>

    <el-drawer v-model="drawerVisible" :title="detail?.title || '试卷'" size="680px">
      <div v-if="detail" class="exam" v-loading="detailLoading">
        <div class="exam__meta">
          <el-tag size="small" effect="light">总分 {{ detail.total_score }}</el-tag>
          <el-tag size="small" effect="light">时长 {{ detail.duration_minutes }} 分钟</el-tag>
          <span class="dim">截止：{{ formatTime(detail.due_at) }}</span>
          <el-tag v-if="!detail.my_record && remaining > 0" type="warning" size="small" effect="dark">
            剩余 {{ countdownText }}
          </el-tag>
          <el-tag v-if="!detail.my_record && violations" type="danger" size="small" effect="light">
            切屏 {{ violations }} 次
          </el-tag>
          <el-tag v-if="!detail.my_record && copyCount" type="warning" size="small" effect="light">
            复制 {{ copyCount }} 次
          </el-tag>
          <el-tag v-if="!detail.my_record && pasteCount" type="warning" size="small" effect="light">
            粘贴 {{ pasteCount }} 次
          </el-tag>
          <el-tag v-if="detail.my_record" type="success" size="small" effect="light">
            得分 {{ detail.my_record.score }}
          </el-tag>
          <el-tag v-if="detail.my_record?.pending_manual" type="warning" size="small" effect="light">
            待批改 {{ detail.my_record.pending_manual }} 题
          </el-tag>
          <el-tag v-if="detail.my_record?.violations" type="danger" size="small" effect="light">
            切屏 {{ detail.my_record.violations }} 次
          </el-tag>
          <el-tag v-if="detail.my_record?.copy_count" type="warning" size="small" effect="light">
            复制 {{ detail.my_record.copy_count }} 次
          </el-tag>
          <el-tag v-if="detail.my_record?.paste_count" type="warning" size="small" effect="light">
            粘贴 {{ detail.my_record.paste_count }} 次
          </el-tag>
          <el-tag v-if="detail.my_record?.timed_out" type="warning" size="small" effect="plain">
            超时提交
          </el-tag>
        </div>
        <p v-if="detail.description" class="exam__desc">{{ detail.description }}</p>

        <div v-for="(q, i) in detail.questions" :key="q.id" class="question">
          <div class="question__head">
            <span class="question__no">{{ i + 1 }}.</span>
            <el-tag :type="typeTag(q.type)" size="small" effect="plain">{{ typeLabel(q.type) }}</el-tag>
            <span class="question__stem">{{ q.stem }}</span>
            <span class="question__score">{{ q.score }} 分</span>
          </div>

          <el-radio-group
            v-if="q.type === 'single'"
            v-model="answers[q.id]" class="question__options" :disabled="submitted"
          >
            <el-radio v-for="op in q.options" :key="op.key" :label="op.key">
              {{ op.key }}. {{ op.text }}
            </el-radio>
          </el-radio-group>

          <el-checkbox-group
            v-else-if="q.type === 'multiple'"
            v-model="answers[q.id]" class="question__options" :disabled="submitted"
          >
            <el-checkbox v-for="op in q.options" :key="op.key" :label="op.key">
              {{ op.key }}. {{ op.text }}
            </el-checkbox>
          </el-checkbox-group>

          <el-radio-group
            v-else-if="q.type === 'judge'"
            v-model="answers[q.id]" class="question__options" :disabled="submitted"
          >
            <el-radio label="true">正确</el-radio>
            <el-radio label="false">错误</el-radio>
          </el-radio-group>

          <el-input
            v-else-if="q.type === 'short'"
            v-model="answers[q.id]"
            type="textarea"
            :rows="4"
            :disabled="submitted"
            placeholder="请输入简答内容"
            class="question__textarea"
          />

          <div v-if="detail.my_record" class="question__result">
            <template v-if="q.type === 'short'">
              <el-tag
                :type="resultOf(q.id)?.awarded == null ? 'warning' : 'success'"
                size="small" effect="light"
              >
                {{ resultOf(q.id)?.awarded == null ? '待教师批改' : '已批改' }}
              </el-tag>
              <span class="dim">你的答案：{{ displayAnswer(q, resultOf(q.id)?.my_answer) || '未作答' }}</span>
              <span v-if="resultOf(q.id)?.awarded != null" class="dim">
                得分：{{ resultOf(q.id).awarded }} / {{ q.score }}
              </span>
            </template>
            <template v-else>
              <el-tag
                :type="resultOf(q.id)?.correct ? 'success' : (q.type === 'multiple' && resultOf(q.id)?.awarded > 0 ? 'warning' : 'danger')"
                size="small" effect="light"
              >
                {{ resultOf(q.id)?.correct ? '正确' : (q.type === 'multiple' && resultOf(q.id)?.awarded > 0 ? '部分正确' : '错误') }}
              </el-tag>
              <span class="dim">你的答案：{{ displayAnswer(q, resultOf(q.id)?.my_answer) || '未作答' }}</span>
              <span v-if="q.type === 'multiple'" class="dim">
                得分：{{ resultOf(q.id)?.awarded || 0 }} / {{ q.score }}
              </span>
            </template>
          </div>

          <div v-if="detail.reveal_answers" class="question__answer">
            <div>正确答案：{{ displayAnswer(q, q.answer) }}</div>
            <div v-if="q.analysis" class="question__analysis">解析：{{ q.analysis }}</div>
          </div>
        </div>

        <div class="exam__actions">
          <el-button
            v-if="!detail.my_record && !detail.due_passed && detail.status === 'published'"
            type="primary" :loading="submitting" @click="submit"
          >
            提交答卷
          </el-button>
          <span v-if="!detail.my_record && remaining > 0" class="dim">
            剩余时间 {{ countdownText }}，超时将自动提交
          </span>
          <span v-if="detail.my_record" class="dim">
            已提交（{{ formatTime(detail.my_record.submitted_at) }}），得分
            {{ detail.my_record.score }} / {{ detail.total_score }}
            <template v-if="detail.my_record.pending_manual">
              ，{{ detail.my_record.pending_manual }} 道简答待教师批改
            </template>
          </span>
          <span v-else-if="detail.due_passed" class="dim">已过截止时间</span>
        </div>

        <p v-if="detail.my_record && !detail.reveal_answers" class="hint">
          答案与解析将在考试截止或教师关闭后展示。
        </p>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { examApi } from '../../api/exams'

const exams = ref([])
const loading = ref(false)
const drawerVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)
const answers = ref({})
const submitting = ref(false)

const remaining = ref(0)
const violations = ref(0)
const copyCount = ref(0)
const pasteCount = ref(0)
const activeExamId = ref(null)
let activeClientId = ''
let timer = null
let heartbeatTimer = null
let autoSubmitted = false

const countdownText = computed(() => {
  const total = Math.max(0, remaining.value)
  const m = String(Math.floor(total / 60)).padStart(2, '0')
  const s = String(total % 60).padStart(2, '0')
  return `${m}:${s}`
})

const TYPE_LABELS = { single: '单选', multiple: '多选', judge: '判断', short: '简答' }

onMounted(load)

async function load() {
  loading.value = true
  try {
    const rows = await examApi.myExams()
    exams.value = Array.isArray(rows) ? rows : []
  } catch { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

function formatTime(t) {
  if (!t) return '不限'
  return String(t).replace('T', ' ').slice(0, 16)
}

function stateLabel(s) {
  return {
    not_started: '待作答', submitted: '已提交',
    overdue: '已逾期', closed: '已结束',
  }[s] || s
}

function stateTag(s) {
  return {
    not_started: 'warning', submitted: 'success',
    overdue: 'danger', closed: 'info',
  }[s] || 'info'
}

function typeLabel(t) {
  return TYPE_LABELS[t] || t
}

function typeTag(t) {
  return { single: '', multiple: 'success', judge: 'warning' }[t] || 'info'
}

async function openExam(row) {
  drawerVisible.value = true
  detail.value = null
  detailLoading.value = true
  stopTimers()
  try {
    const data = await examApi.myExam(row.id)
    detail.value = data
    initAnswers(data)
    if (!data.my_record && !data.due_passed && data.status === 'published') {
      await beginSession(data.id)
    }
  } catch { /* 拦截器已提示 */ } finally {
    detailLoading.value = false
  }
}

// ---------- 服务端计时与切屏统计 ----------

function examClientId(examId) {
  const key = `itea_exam_client_${examId}`
  let value = localStorage.getItem(key)
  if (!value) {
    value = globalThis.crypto?.randomUUID?.()
      || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
    localStorage.setItem(key, value)
  }
  return value
}

function monitoringPayload() {
  return {
    client_id: activeClientId,
    violations: violations.value,
    copy_count: copyCount.value,
    paste_count: pasteCount.value,
  }
}

async function beginSession(examId) {
  try {
    activeClientId = examClientId(examId)
    const session = await examApi.startExam(examId, activeClientId)
    activeExamId.value = examId
    remaining.value = session.remaining_seconds || 0
    violations.value = session.violations || 0
    copyCount.value = session.copy_count || 0
    pasteCount.value = session.paste_count || 0
    autoSubmitted = false
    startTimers()
  } catch { /* 拦截器已提示 */ }
}

function startTimers() {
  clearTimers()
  timer = setInterval(() => {
    remaining.value = Math.max(0, remaining.value - 1)
    if (remaining.value === 0 && !autoSubmitted) {
      autoSubmitted = true
      ElMessage.warning('考试时间已到，正在自动提交')
      submit(true)
    }
  }, 1000)
  heartbeatTimer = setInterval(reportHeartbeat, 30000)
  document.addEventListener('visibilitychange', onVisibility)
  document.addEventListener('copy', onCopy)
  document.addEventListener('paste', onPaste)
}

function clearTimers() {
  if (timer) { clearInterval(timer); timer = null }
  if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null }
}

function stopTimers() {
  clearTimers()
  document.removeEventListener('visibilitychange', onVisibility)
  document.removeEventListener('copy', onCopy)
  document.removeEventListener('paste', onPaste)
  activeExamId.value = null
  activeClientId = ''
  autoSubmitted = false
  remaining.value = 0
  violations.value = 0
  copyCount.value = 0
  pasteCount.value = 0
}

function monitoringActive() {
  return drawerVisible.value && !detail.value?.my_record && activeExamId.value
}

function onVisibility() {
  if (document.hidden && monitoringActive()) {
    violations.value += 1
    reportHeartbeat()
  }
}

function onCopy() {
  if (!monitoringActive()) return
  copyCount.value += 1
  reportHeartbeat()
}

function onPaste() {
  if (!monitoringActive()) return
  pasteCount.value += 1
  reportHeartbeat()
}

async function reportHeartbeat() {
  if (!activeExamId.value || detail.value?.my_record) return
  try {
    const res = await examApi.heartbeat(activeExamId.value, monitoringPayload())
    remaining.value = res.remaining_seconds ?? remaining.value
  } catch { /* 静默,不打断作答 */ }
}

watch(drawerVisible, (visible) => {
  if (!visible) stopTimers()
})

onBeforeUnmount(stopTimers)

function initAnswers(data) {
  const init = {}
  const givenMap = {}
  ;(data.results || []).forEach((r) => { givenMap[r.question_id] = r.my_answer })
  for (const q of data.questions) {
    const given = givenMap[q.id] || ''
    if (q.type === 'multiple') {
      init[q.id] = given ? given.split(',') : []
    } else {
      init[q.id] = given
    }
  }
  answers.value = init
}

const submitted = computed(() => !!detail.value?.my_record)

function resultOf(questionId) {
  return (detail.value?.results || []).find((r) => r.question_id === questionId)
}

function displayAnswer(q, value) {
  if (!value) return ''
  if (q.type === 'judge') return value === 'true' ? '正确' : '错误'
  return value
}

async function submit(auto = false) {
  if (!auto) {
    try {
      await ElMessageBox.confirm('提交后不可修改，确定提交答卷？', '提交确认', { type: 'warning' })
    } catch { return }
  }
  const payload = {}
  for (const q of detail.value.questions) {
    const value = answers.value[q.id]
    payload[q.id] = Array.isArray(value) ? value.join(',') : (value || '')
  }
  submitting.value = true
  try {
    const res = await examApi.submitExam(detail.value.id, payload, monitoringPayload())
    stopTimers()
    const extra = res.pending_manual ? `，${res.pending_manual} 道简答待教师批改` : ''
    ElMessage.success(`提交成功，客观题得分 ${res.score} / ${res.total_score}${extra}`)
    await openExam({ id: detail.value.id })
    load()
  } catch { /* 拦截器已提示 */ } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.dim { color: var(--text-placeholder); }
.exam { display: flex; flex-direction: column; gap: var(--sp-3); }
.exam__meta { display: flex; align-items: center; gap: var(--sp-2); flex-wrap: wrap; font-size: var(--fs-xs); }
.exam__desc { font-size: var(--fs-sm); color: var(--text-secondary); white-space: pre-wrap; }
.question { padding: var(--sp-3) 0; border-bottom: 1px dashed var(--border); }
.question__head { display: flex; align-items: baseline; gap: var(--sp-2); }
.question__no { color: var(--text-secondary); font-size: var(--fs-sm); }
.question__stem { flex: 1; font-size: var(--fs-sm); color: var(--text-primary); }
.question__score { font-size: var(--fs-xs); color: var(--text-secondary); }
.question__options { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; margin: var(--sp-2) 0 0 20px; }
.question__textarea { margin: var(--sp-2) 0 0 20px; width: calc(100% - 20px); }
.question__result { display: flex; align-items: center; gap: var(--sp-2); margin: 6px 0 0 20px; font-size: var(--fs-xs); }
.question__answer {
  margin: 6px 0 0 20px;
  padding: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-primary);
  background: var(--bg-subtle);
  border-radius: var(--r-sm);
}
.question__analysis { margin-top: 4px; color: var(--text-secondary); }
.exam__actions { display: flex; align-items: center; gap: var(--sp-3); padding-top: var(--sp-2); }
.hint { font-size: var(--fs-xs); color: var(--text-secondary); }
</style>
