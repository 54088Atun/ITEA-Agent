<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <el-button link class="back-link" @click="router.push('/teacher/questions')">
          <el-icon><ArrowLeft /></el-icon> 返回题库与组卷
        </el-button>
        <h2 class="page-title">{{ exam?.title || '试卷详情' }}</h2>
        <p class="page-sub">{{ scopeText }}</p>
      </div>
      <div v-if="exam" class="page-head__actions">
        <el-tag :type="statusTag(exam.status)" size="small" effect="light">{{ statusLabel(exam.status) }}</el-tag>
        <el-button v-if="exam.status === 'draft'" type="success" @click="publish">发布</el-button>
        <el-button v-if="exam.status === 'published'" type="warning" @click="close">关闭</el-button>
      </div>
    </div>

    <div v-if="loading" class="panel">
      <SkeletonTable :rows="5" :cols="4" />
    </div>
    <StateBlock v-else-if="error" state="error" title="试卷详情加载失败" @retry="load" />
    <template v-else-if="exam">
      <div class="kpi-grid">
        <div class="kpi-card">
          <span>题目数</span>
          <strong>{{ exam.question_count }}</strong>
        </div>
        <div class="kpi-card">
          <span>总分</span>
          <strong>{{ exam.total_score }}</strong>
        </div>
        <div class="kpi-card">
          <span>考试时长</span>
          <strong>{{ exam.duration_minutes }} 分钟</strong>
        </div>
        <div class="kpi-card">
          <span>提交人数</span>
          <strong>{{ exam.submission_count }}</strong>
        </div>
        <div class="kpi-card">
          <span>截止时间</span>
          <strong class="kpi-card__text">{{ exam.due_at ? formatTime(exam.due_at) : '不限' }}</strong>
        </div>
      </div>

      <div v-if="exam.description" class="panel">
        <div class="panel__head">
          <span class="panel__title">组卷说明</span>
        </div>
        <p class="text-block">{{ exam.description }}</p>
      </div>

      <div class="panel">
        <div class="panel__head">
          <span class="panel__title">试卷题目</span>
        </div>
        <div v-if="exam.questions && exam.questions.length" class="question-list">
          <article v-for="(q, index) in exam.questions" :key="q.id" class="question-item">
            <div class="question-item__head">
              <span class="question-item__index">{{ index + 1 }}</span>
              <el-tag :type="typeTag(q.type)" size="small" effect="light">{{ typeLabel(q.type) }}</el-tag>
              <span class="question-item__stem">{{ q.stem }}</span>
              <span class="dim">{{ q.score }} 分</span>
            </div>
            <ul v-if="q.options && q.options.length" class="option-list">
              <li v-for="op in q.options" :key="op.key" class="option-item">
                <span class="option-key">{{ op.key }}</span>
                <span>{{ op.text }}</span>
              </li>
            </ul>
            <p class="question-item__answer">答案：{{ answerText(q) }}</p>
            <p v-if="q.analysis" class="question-item__analysis">解析：{{ q.analysis }}</p>
          </article>
        </div>
        <StateBlock v-else state="empty" title="试卷暂无题目" />
      </div>

      <div class="panel">
        <div class="panel__head">
          <span class="panel__title">学生成绩</span>
          <span class="panel__hint">简答题需教师确认后才计入总分</span>
        </div>
        <el-table :data="results.items || []" v-loading="resultsLoading">
          <el-table-column prop="student_name" label="学生" min-width="110" />
          <el-table-column label="得分" width="100">
            <template #default="{ row }">
              <strong>{{ row.score }}</strong>
              <span class="dim"> / {{ results.total_score }}</span>
            </template>
          </el-table-column>
          <el-table-column label="正确题数" width="110">
            <template #default="{ row }">{{ row.correct_count }} / {{ row.question_count }}</template>
          </el-table-column>
          <el-table-column label="待批改" width="100">
            <template #default="{ row }">
              <el-tag v-if="row.pending_manual" type="warning" size="small" effect="light">
                {{ row.pending_manual }} 题
              </el-tag>
              <span v-else class="dim">—</span>
            </template>
          </el-table-column>
          <el-table-column label="切屏" width="80">
            <template #default="{ row }">
              <el-tag v-if="row.violations" type="danger" size="small" effect="light">{{ row.violations }}</el-tag>
              <span v-else class="dim">0</span>
            </template>
          </el-table-column>
          <el-table-column label="复制 / 粘贴" width="110">
            <template #default="{ row }">{{ row.copy_count || 0 }} / {{ row.paste_count || 0 }}</template>
          </el-table-column>
          <el-table-column label="提交时间" width="150">
            <template #default="{ row }">{{ formatTime(row.submitted_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button link type="primary" @click="openRecord(row)">查看答卷</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <StateBlock state="empty" title="暂无学生提交" />
          </template>
        </el-table>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, reactive, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { examApi } from '../../api/exams'
import { teacherApi } from '../../api/teacher'
import { classroomApi } from '../../api/classroom'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'

const route = useRoute()
const router = useRouter()
const examId = Number(route.params.id)

const loading = ref(true)
const error = ref(false)
const exam = ref(null)
const courses = ref([])
const classes = ref([])

const resultsLoading = ref(false)
const results = reactive({ total_score: 0, submission_count: 0, items: [] })

const TYPE_LABELS = { single: '单选', multiple: '多选', judge: '判断', short: '简答' }

const scopeText = computed(() => {
  const className = classes.value.find((c) => c.id === exam.value?.class_id)?.name
  const courseName = courses.value.find((c) => c.id === exam.value?.course_id)?.name
  return [className && `${className}（班级）`, courseName && `${courseName}（课程）`]
    .filter(Boolean).join(' · ') || '未设置发布范围'
})

onMounted(load)

async function load() {
  loading.value = true
  error.value = false
  try {
    const [data, courseRows, classRows] = await Promise.all([
      examApi.exam(examId),
      teacherApi.courses(),
      classroomApi.list(),
    ])
    exam.value = data
    courses.value = Array.isArray(courseRows) ? courseRows : []
    classes.value = Array.isArray(classRows) ? classRows : []
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
  loadResults()
}

async function loadResults() {
  resultsLoading.value = true
  try {
    const data = await examApi.examResults(examId)
    Object.assign(results, {
      total_score: data.total_score,
      submission_count: data.submission_count,
      items: data.items || [],
    })
  } catch { /* 拦截器已提示 */ } finally {
    resultsLoading.value = false
  }
}

function typeLabel(type) {
  return TYPE_LABELS[type] || type
}

function typeTag(type) {
  return { single: '', multiple: 'success', judge: 'warning', short: 'info' }[type] || 'info'
}

function answerText(q) {
  if (q.type === 'judge') return String(q.answer).toLowerCase() === 'true' ? '正确' : '错误'
  return q.answer || '—'
}

function statusLabel(status) {
  return { draft: '草稿', published: '已发布', closed: '已关闭' }[status] || status
}

function statusTag(status) {
  return { draft: 'info', published: 'success', closed: 'warning' }[status] || 'info'
}

function formatTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

async function publish() {
  try {
    await ElMessageBox.confirm('发布后学生将收到通知并可开始作答，确定发布？', '发布试卷', { type: 'warning' })
  } catch { return }
  try {
    await examApi.publishExam(examId, true)
    ElMessage.success('已发布')
    load()
  } catch { /* 拦截器已提示 */ }
}

async function close() {
  try {
    await ElMessageBox.confirm('关闭后学生不能再提交，并会展示答案与解析，确定关闭？', '关闭试卷', { type: 'warning' })
  } catch { return }
  try {
    await examApi.closeExam(examId, true)
    ElMessage.success('已关闭')
    load()
  } catch { /* 拦截器已提示 */ }
}

function openRecord(row) {
  router.push(`/teacher/exam-records/${row.record_id}`)
}
</script>

<style scoped>
.back-link { padding: 0; margin-bottom: var(--sp-1); color: var(--text-secondary); }
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--sp-3);
  margin-bottom: var(--sp-4);
}
.kpi-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--sp-4);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-xs);
}
.kpi-card span { font-size: var(--fs-xs); color: var(--text-secondary); }
.kpi-card strong { font-size: var(--fs-xl); color: var(--text-primary); }
.kpi-card__text { font-size: var(--fs-md) !important; }
.panel { margin-bottom: var(--sp-4); }
.panel__hint { margin-left: auto; font-size: var(--fs-xs); color: var(--text-secondary); }
.text-block { margin: 0; white-space: pre-wrap; line-height: 1.8; color: var(--text-primary); }
.question-list { display: flex; flex-direction: column; gap: var(--sp-3); }
.question-item {
  padding: var(--sp-3);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--bg-elevated);
}
.question-item__head { display: flex; align-items: baseline; gap: var(--sp-2); }
.question-item__index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--color-primary-wash);
  color: var(--color-primary);
  font-size: var(--fs-xs);
  font-weight: 600;
}
.question-item__stem { flex: 1; color: var(--text-primary); line-height: 1.7; white-space: pre-wrap; }
.question-item__answer,
.question-item__analysis {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-sm);
  color: var(--text-secondary);
  white-space: pre-wrap;
}
.option-list { display: flex; flex-direction: column; gap: 6px; margin: var(--sp-2) 0 0; padding: 0; list-style: none; }
.option-item { display: flex; gap: var(--sp-2); font-size: var(--fs-sm); color: var(--text-primary); }
.option-key { color: var(--text-secondary); font-weight: 600; }
.dim { font-size: var(--fs-xs); color: var(--text-placeholder); }
</style>
