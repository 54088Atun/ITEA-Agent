<template>
  <div class="page page--fill">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">模拟面试</h2>
        <p class="page-sub">AI 面试官连续追问，结束后给出结构化评价与得分</p>
      </div>
      <div class="page-head__actions">
        <el-select v-model="courseId" placeholder="选择课程" style="width: 220px" @change="onCourseChange">
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
            {{ a.teacher_name }} · {{ a.due_at ? `截止 ${formatTime(a.due_at)}` : '不限截止' }}
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
                <el-tag v-if="r.score != null" :type="r.score >= 80 ? 'success' : r.score >= 60 ? 'warning' : 'danger'" size="small" effect="light" style="margin-left: 8px">
                  得分:{{ r.score }}
                </el-tag>
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
import ChatWindow from '../../components/ChatWindow.vue'
import { studentApi, INTERVIEW_START_URL } from '../../api/student'
import { courseApi } from '../../api/course'
import { renderMarkdown } from '../../utils/markdown'

const courses = ref([])
const courseId = ref(null)
const active = ref(false)
const sessionKey = ref(0)
const showRecords = ref(false)
const records = ref([])
const assignments = ref([])
const loadingRecords = ref(false)

/** 面试入口必须携带课程 ID */
const startBody = computed(() => ({
  course_id: courseId.value,
  focus_kp_ids: [],
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
  } catch { /* ignore */ }
})

function startFromAssignment(assignment) {
  if (assignment.course_id) {
    courseId.value = assignment.course_id
  }
  if (!courseId.value) return ElMessage.warning('请先选择课程')
  startNew()
}

function onCourseChange() {
  active.value = false
  records.value = []
}

function startNew() {
  if (!courseId.value) return ElMessage.warning('请先选择课程')
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

function formatTime(t) {
  if (!t) return ''
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.chat-container { flex: 1; min-height: 0; }
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
