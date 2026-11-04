<template>
  <div class="page page--fill">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">模拟面试</h2>
        <p class="page-sub">AI 面试官连续追问，结束后给出结构化评价与得分</p>
      </div>
      <div class="page-head__actions">
        <span v-if="active" class="interview-time">剩余时间 {{ formattedRemaining }}</span>
        <el-select v-model="courseId" placeholder="选择课程" filterable style="width: 220px" @change="onCourseChange">
          <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-button @click="showRecords = true" :disabled="!courseId">
          <el-icon><List /></el-icon> 历史记录
        </el-button>
        <el-button type="primary" :disabled="!courseId" @click="startNew">
          <el-icon><Plus /></el-icon> 开始新面试
        </el-button>
      </div>
    </div>

    <div v-if="assignments.length" class="panel assignment-panel">
      <div class="panel__head">
        <span class="panel__title">教师发布的面试作业</span>
      </div>
      <div v-for="a in assignments" :key="a.id" class="assignment">
        <div class="assignment__main">
          <span class="assignment__title">{{ a.title }}</span>
          <span class="assignment__meta">
            {{ a.teacher_name }} · {{ a.duration_minutes || 30 }} 分钟 · {{ a.due_at ? `截止 ${formatTime(a.due_at)}` : '不限截止' }}
          </span>
        </div>
        <el-button size="small" type="primary" plain @click="startFromAssignment(a)">去完成</el-button>
      </div>
    </div>

    <div class="chat-container">
      <ChatWindow
        v-if="active && courseId"
        :key="sessionKey"
        welcome="欢迎来到模拟面试!请先告诉我你希望练习的方向(如 Java 后端、前端、算法),以及你的简历或核心经历,我会扮演面试官对你进行提问和追问,结束后给出详细评价。"
        placeholder="例如:我想练习 Java 后端面试,我的项目经历是…"
        :course-id="courseId"
        branch="interview"
        :start-endpoint="INTERVIEW_START_URL"
        :start-body="startBody"
        :duration-minutes="durationMinutes"
        :interview-assignment-id="currentAssignment?.id || null"
        @time-update="remainingSeconds = $event"
      />
      <div v-else class="panel empty-panel">
        <div class="empty-state">
          {{ courseId ? '点击「开始新面试」启动模拟面试' : '请先选择课程后再开始面试' }}
        </div>
      </div>
    </div>

    <el-drawer v-model="showRecords" title="面试历史记录" size="560px">
      <div v-loading="loadingRecords">
        <div v-if="!records.length && !loadingRecords" class="empty-state">暂无记录</div>
        <el-timeline>
          <el-timeline-item v-for="r in records" :key="r.id" :timestamp="formatTime(r.created_at)" placement="top">
            <div class="record">
              <div class="record-round">
                <el-tag size="small" effect="light">第 {{ r.round }} 轮</el-tag>
                <el-tag
                  :type="r.score == null ? 'info' : r.score >= 80 ? 'success' : r.score >= 60 ? 'warning' : 'danger'"
                  size="small" effect="light" style="margin-left: 8px"
                >
                  综合评分：{{ r.score ?? '未评分' }}
                </el-tag>
              </div>
              <div class="record-scores">
                <span v-for="label in SCORE_LABELS" :key="label">
                  {{ label }}：{{ dimensionScore(r, label) }}
                </span>
              </div>
              <div class="record-visibility">
                <el-switch
                  :model-value="r.visibility === 'teacher'"
                  :loading="visibilitySavingId === r.id"
                  active-text="教师可见"
                  inactive-text="仅自己"
                  @change="changeVisibility(r, $event)"
                />
                <span>{{ r.visibility === 'teacher' ? '已授权课程/作业教师查看' : '私有记录，仅自己可见' }}</span>
              </div>
              <div class="record-section">
                <span class="record-label">面试官提问</span>
                <div class="record-text">{{ r.question }}</div>
              </div>
              <div class="record-section" v-if="r.answer">
                <span class="record-label">我的回答</span>
                <div class="record-text">{{ r.answer }}</div>
              </div>
              <div class="record-section" v-if="r.feedback">
                <span class="record-label">评价反馈</span>
                <div class="record-text md-body" v-html="renderMarkdown(r.feedback)"></div>
              </div>
            </div>
          </el-timeline-item>
        </el-timeline>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import ChatWindow from '../../components/ChatWindow.vue'
import { studentApi, INTERVIEW_START_URL } from '../../api/student'
import { courseApi } from '../../api/course'
import { renderMarkdown } from '../../utils/markdown'

const route = useRoute()
const SCORE_LABELS = ['专业知识', '逻辑表达', '岗位匹配', '沟通应答']

const courses = ref([])
const courseId = ref(null)
const active = ref(false)
const sessionKey = ref(0)
const showRecords = ref(false)
const records = ref([])
const assignments = ref([])
const loadingRecords = ref(false)
const currentAssignment = ref(null)
const remainingSeconds = ref(0)
const visibilitySavingId = ref(null)

const durationMinutes = computed(() => currentAssignment.value?.duration_minutes || 30)
const formattedRemaining = computed(() => formatDuration(remainingSeconds.value))

/** 面试入口必须携带课程 ID；教师作业同时关联来源作业 */
const startBody = computed(() => ({
  course_id: courseId.value,
  focus_kp_ids: [],
  ...(currentAssignment.value ? { assignment_id: currentAssignment.value.id } : {}),
}))

onMounted(async () => {
  try {
    // /course/list 直接返回数组
    const data = await courseApi.list()
    courses.value = Array.isArray(data) ? data : []
    if (courses.value.length) courseId.value = courses.value[0].id
  } catch { /* ignore */ }
  try {
    assignments.value = await studentApi.interviewAssignments()
    const assignmentId = Number(route.query.assignment_id)
    const assignment = assignments.value.find(a => a.id === assignmentId)
    if (assignment) startFromAssignment(assignment)
  } catch { /* ignore */ }
})

function startFromAssignment(assignment) {
  if (assignment.course_id) {
    courseId.value = assignment.course_id
  }
  if (!courseId.value) return ElMessage.warning('请先选择课程')
  currentAssignment.value = assignment
  beginInterview()
}

function onCourseChange() {
  active.value = false
  currentAssignment.value = null
  records.value = []
}

function startNew() {
  currentAssignment.value = null
  beginInterview()
}

function beginInterview() {
  if (!courseId.value) return ElMessage.warning('请先选择课程')
  remainingSeconds.value = durationMinutes.value * 60
  active.value = true
  sessionKey.value++
}

async function loadRecords() {
  if (!courseId.value) return
  loadingRecords.value = true
  try {
    records.value = await studentApi.interviewRecords(courseId.value)
  } catch { /* 拦截器已提示 */ } finally {
    loadingRecords.value = false
  }
}

watch(showRecords, (v) => {
  if (v && courseId.value) loadRecords()
})

async function changeVisibility(record, shared) {
  const visibility = shared ? 'teacher' : 'private'
  visibilitySavingId.value = record.id
  try {
    const data = await studentApi.updateInterviewVisibility(record.id, visibility)
    Object.assign(record, data)
    ElMessage.success(visibility === 'teacher' ? '已授权教师查看' : '已设为仅自己可见')
  } catch { /* 拦截器已提示，保持原状态 */ } finally {
    visibilitySavingId.value = null
  }
}

function dimensionScore(record, label) {
  try {
    const dimensions = typeof record.score_dimensions === 'string'
      ? JSON.parse(record.score_dimensions)
      : (record.score_dimensions || {})
    return dimensions[label] ?? '未评分'
  } catch {
    return '未评分'
  }
}

function formatDuration(totalSeconds) {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function formatTime(t) {
  if (!t) return ''
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.chat-container { flex: 1; min-height: 0; }
.interview-time {
  color: var(--brand-700);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.assignment-panel { margin-bottom: var(--sp-3); }
.assignment {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-2) 0;
  border-bottom: 1px dashed var(--border);
}
.assignment:last-child { border-bottom: none; }
.assignment__main { display: flex; flex-direction: column; gap: 2px; }
.assignment__title { font-size: var(--fs-sm); color: var(--text-primary); }
.assignment__meta { font-size: var(--fs-xs); color: var(--text-secondary); }
.empty-panel { height: 100%; display: flex; align-items: center; justify-content: center; }

.record-round { margin-bottom: var(--sp-2); }
.record-scores {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-3);
  margin-bottom: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.record-visibility {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.record-section { margin-bottom: var(--sp-2); }
.record-label {
  display: block;
  font-weight: 600;
  font-size: var(--fs-xs);
  letter-spacing: 0.06em;
  color: var(--text-secondary);
  margin-bottom: var(--sp-1);
}
.record-text {
  font-size: var(--fs-sm);
  background: var(--bg-subtle);
  border-radius: var(--r-sm);
  padding: var(--sp-2) var(--sp-3);
  color: var(--text-primary);
}
.record-text.md-body { background: var(--bg-subtle); }
</style>
