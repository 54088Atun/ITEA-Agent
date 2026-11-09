<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <el-button link class="back-link" @click="router.back()">
          <el-icon><ArrowLeft /></el-icon> 返回
        </el-button>
        <h2 class="page-title">题目详情</h2>
        <p class="page-sub">
          {{ courseName || '课程题库' }} · 题目 #{{ question?.id }}
        </p>
      </div>
      <div v-if="question" class="page-head__actions">
        <el-button type="danger" plain @click="archive">归档题目</el-button>
      </div>
    </div>

    <div v-if="loading" class="panel">
      <SkeletonTable :rows="5" :cols="3" />
    </div>
    <StateBlock v-else-if="error" state="error" title="题目详情加载失败" @retry="load" />
    <template v-else-if="question">
      <div class="panel">
        <div class="meta-row">
          <el-tag :type="typeTag(question.type)" size="small" effect="light">{{ typeLabel(question.type) }}</el-tag>
          <el-tag :type="question.source === 'agent' ? 'warning' : 'info'" size="small" effect="plain">
            {{ question.source === 'agent' ? 'AI 生成' : '手动录入' }}
          </el-tag>
          <el-tag :type="question.status === 'active' ? 'success' : 'info'" size="small" effect="light">
            {{ question.status === 'active' ? '使用中' : '已归档' }}
          </el-tag>
          <span class="dim">难度</span>
          <el-rate :model-value="question.difficulty" disabled :max="5" size="small" />
          <span class="dim meta-row__time">{{ formatTime(question.created_at) }}</span>
        </div>
        <p class="stem">{{ question.stem }}</p>
      </div>

      <div v-if="question.options && question.options.length" class="panel">
        <div class="panel__head">
          <span class="panel__title">选项</span>
        </div>
        <ul class="option-list">
          <li
            v-for="op in question.options"
            :key="op.key"
            class="option-item"
            :class="{ 'option-item--correct': isCorrect(op.key) }"
          >
            <span class="option-key">{{ op.key }}</span>
            <span class="option-text">{{ op.text }}</span>
            <el-tag v-if="isCorrect(op.key)" type="success" size="small" effect="light">正确答案</el-tag>
          </li>
        </ul>
      </div>

      <div class="panel">
        <div class="panel__head">
          <span class="panel__title">答案</span>
        </div>
        <p class="answer">{{ answerText }}</p>
      </div>

      <div class="panel">
        <div class="panel__head">
          <span class="panel__title">解析</span>
        </div>
        <p class="answer">{{ question.analysis || '暂无解析' }}</p>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { examApi } from '../../api/exams'
import { teacherApi } from '../../api/teacher'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'

const route = useRoute()
const router = useRouter()
const questionId = Number(route.params.id)

const loading = ref(true)
const error = ref(false)
const question = ref(null)
const courses = ref([])

const TYPE_LABELS = { single: '单选题', multiple: '多选题', judge: '判断题', short: '简答题' }

const courseName = computed(() =>
  courses.value.find((c) => c.id === question.value?.course_id)?.name || '',
)

const correctKeys = computed(() => {
  const answer = String(question.value?.answer || '').toUpperCase()
  return new Set(answer.split(',').map((item) => item.trim()).filter(Boolean))
})

const answerText = computed(() => {
  const q = question.value
  if (!q) return '—'
  if (q.type === 'judge') {
    return String(q.answer).toLowerCase() === 'true' ? '正确' : '错误'
  }
  return q.answer || '—'
})

onMounted(load)

async function load() {
  loading.value = true
  error.value = false
  try {
    const [data, courseRows] = await Promise.all([
      examApi.question(questionId),
      teacherApi.courses(),
    ])
    question.value = data
    courses.value = Array.isArray(courseRows) ? courseRows : []
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

function isCorrect(key) {
  return correctKeys.value.has(String(key).toUpperCase())
}

function typeLabel(type) {
  return TYPE_LABELS[type] || type
}

function typeTag(type) {
  return { single: '', multiple: 'success', judge: 'warning', short: 'info' }[type] || 'info'
}

function formatTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

async function archive() {
  try {
    await ElMessageBox.confirm('归档后不再出现在组卷列表，确定归档？', '归档题目', { type: 'warning' })
  } catch { return }
  try {
    await examApi.archiveQuestion(questionId)
    ElMessage.success('已归档')
    router.push('/teacher/questions')
  } catch { /* 拦截器已提示 */ }
}
</script>

<style scoped>
.back-link { padding: 0; margin-bottom: var(--sp-1); color: var(--text-secondary); }
.panel { margin-bottom: var(--sp-4); }
.meta-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
}
.meta-row__time { margin-left: auto; }
.dim { font-size: var(--fs-xs); color: var(--text-placeholder); }
.stem { margin: 0; font-size: var(--fs-md); line-height: 1.8; color: var(--text-primary); white-space: pre-wrap; }
.option-list { display: flex; flex-direction: column; gap: var(--sp-2); margin: 0; padding: 0; list-style: none; }
.option-item {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--bg-elevated);
}
.option-item--correct { border-color: var(--brand-300); background: var(--color-primary-wash); }
.option-key {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--bg-subtle);
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--text-secondary);
}
.option-item--correct .option-key { background: var(--color-primary); color: #fff; }
.option-text { flex: 1; color: var(--text-primary); line-height: 1.7; word-break: break-word; }
.answer { margin: 0; white-space: pre-wrap; line-height: 1.8; color: var(--text-primary); }
</style>
