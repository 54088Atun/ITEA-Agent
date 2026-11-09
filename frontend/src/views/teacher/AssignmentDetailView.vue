<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <el-button link class="back-link" @click="router.push('/teacher/assignments')">
          <el-icon><ArrowLeft /></el-icon> 返回作业与考试
        </el-button>
        <h2 class="page-title">{{ detail?.title || '作业详情' }}</h2>
        <p class="page-sub">
          {{ detail?.kind === 'exam' ? '考试' : '作业' }}
          · {{ scopeText }}
        </p>
      </div>
      <div v-if="detail" class="page-head__actions">
        <el-tag :type="statusTag(detail.status)" size="small" effect="light">
          {{ statusLabel(detail.status) }}
        </el-tag>
        <el-button v-if="detail.status === 'draft'" type="success" @click="publish">发布</el-button>
        <el-button v-if="detail.status !== 'closed'" type="warning" @click="close">关闭</el-button>
      </div>
    </div>

    <div v-if="loading" class="panel">
      <SkeletonTable :rows="5" :cols="4" />
    </div>
    <StateBlock v-else-if="error" state="error" title="作业详情加载失败" @retry="load" />
    <template v-else-if="detail">
      <div class="kpi-grid">
        <div class="kpi-card">
          <span>提交份数</span>
          <strong>{{ detail.submission_count }}</strong>
        </div>
        <div class="kpi-card">
          <span>待确认</span>
          <strong>{{ detail.pending_count }}</strong>
        </div>
        <div class="kpi-card">
          <span>截止时间</span>
          <strong class="kpi-card__text">{{ detail.due_at ? formatTime(detail.due_at) : '不限' }}</strong>
        </div>
        <div class="kpi-card">
          <span>允许补交</span>
          <strong class="kpi-card__text">{{ detail.allow_late ? '是' : '否' }}</strong>
        </div>
      </div>

      <div class="panel">
        <div class="panel__head">
          <span class="panel__title">作业要求</span>
        </div>
        <p class="text-block">{{ detail.description || '暂无作业要求' }}</p>
      </div>

      <div class="panel">
        <div class="panel__head">
          <span class="panel__title">参考答案（仅教师可见）</span>
        </div>
        <p class="text-block">{{ detail.reference_answer || '未设置参考答案' }}</p>
      </div>

      <div class="panel">
        <div class="panel__head">
          <span class="panel__title">学生提交</span>
          <span class="panel__hint">AI 只给建议，确认后才写入正式成绩</span>
        </div>
        <el-table :data="detail.submissions || []" v-loading="gradingId !== null">
          <el-table-column prop="student_name" label="学生" width="110" />
          <el-table-column label="提交内容" min-width="220">
            <template #default="{ row }">
              <div class="answer">{{ row.content || '—' }}</div>
            </template>
          </el-table-column>
          <el-table-column label="AI 建议" width="150">
            <template #default="{ row }">
              <div v-if="row.ai_score != null">
                <el-tag type="warning" size="small" effect="light">{{ row.ai_score }} 分 · 建议</el-tag>
                <div class="ai-note">待教师确认</div>
              </div>
              <span v-else class="dim">未生成</span>
            </template>
          </el-table-column>
          <el-table-column label="正式成绩" width="110">
            <template #default="{ row }">
              <el-tag v-if="row.confirmed" type="success" size="small" effect="light">{{ row.score }} 分</el-tag>
              <el-tag v-else type="info" size="small" effect="plain">未生效</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="提交时间" width="150">
            <template #default="{ row }">{{ formatTime(row.submitted_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button link type="primary" :loading="gradingId === row.id" @click="aiGrade(row)">
                AI 批改
              </el-button>
              <el-button link type="success" @click="openConfirm(row)">确认评分</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <StateBlock state="empty" title="暂无学生提交" />
          </template>
        </el-table>
      </div>
    </template>

    <el-dialog v-model="confirmVisible" title="确认评分（确认后学生可见）" width="min(520px, 92vw)">
      <el-form label-width="88px">
        <el-form-item label="正式分数">
          <el-input-number v-model="confirmForm.score" :min="0" :max="100" />
        </el-form-item>
        <el-form-item label="评语">
          <el-input v-model="confirmForm.feedback" type="textarea" :rows="4" placeholder="可沿用 AI 建议后修改" />
        </el-form-item>
      </el-form>
      <p class="confirm-hint">未确认前学生学习端只显示「待教师确认」，不会看到 AI 建议分数。</p>
      <template #footer>
        <el-button @click="confirmVisible = false">取消</el-button>
        <el-button type="primary" :loading="confirming" @click="submitConfirm">确认并发布成绩</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { teacherApi } from '../../api/teacher'
import { classroomApi } from '../../api/classroom'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'

const route = useRoute()
const router = useRouter()
const assignmentId = Number(route.params.id)

const loading = ref(true)
const error = ref(false)
const detail = ref(null)
const courses = ref([])
const classes = ref([])
const gradingId = ref(null)

const confirmVisible = ref(false)
const confirming = ref(false)
const confirmForm = reactive({ submissionId: null, score: 60, feedback: '' })

const scopeText = computed(() => {
  const classId = detail.value?.class_id
  const courseId = detail.value?.course_id
  const className = classes.value.find((c) => c.id === classId)?.name
  const courseName = courses.value.find((c) => c.id === courseId)?.name
  return [className && `${className}（班级）`, courseName && `${courseName}（课程）`]
    .filter(Boolean).join(' · ') || '未设置发放范围'
})

onMounted(load)

async function load() {
  loading.value = true
  error.value = false
  try {
    const [data, courseRows, classRows] = await Promise.all([
      teacherApi.assignment(assignmentId),
      teacherApi.courses(),
      classroomApi.list(),
    ])
    detail.value = data
    courses.value = Array.isArray(courseRows) ? courseRows : []
    classes.value = Array.isArray(classRows) ? classRows : []
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

function formatTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

function statusLabel(status) {
  return { draft: '草稿', published: '已发布', closed: '已关闭' }[status] || status
}

function statusTag(status) {
  return { draft: 'info', published: 'success', closed: 'warning' }[status] || 'info'
}

async function publish() {
  try {
    await ElMessageBox.confirm('发布后学生将收到通知并可提交，确定发布？', '发布作业', { type: 'warning' })
  } catch { return }
  try {
    await teacherApi.publishAssignment(assignmentId, true)
    ElMessage.success('已发布')
    load()
  } catch { /* 拦截器已提示 */ }
}

async function close() {
  try {
    await ElMessageBox.confirm('关闭后学生将无法再提交，确定关闭？', '关闭作业', { type: 'warning' })
  } catch { return }
  try {
    await teacherApi.closeAssignment(assignmentId, true)
    ElMessage.success('已关闭')
    load()
  } catch { /* 拦截器已提示 */ }
}

async function aiGrade(row) {
  gradingId.value = row.id
  try {
    const res = await teacherApi.aiGradeSubmission(row.id)
    row.ai_score = res.ai_score
    row.ai_feedback = res.ai_feedback
    ElMessage.success(res.source === 'llm' ? 'AI 建议已生成' : 'AI 不可用，已生成规则初评')
  } catch { /* 拦截器已提示 */ } finally {
    gradingId.value = null
  }
}

function openConfirm(row) {
  confirmForm.submissionId = row.id
  confirmForm.score = row.ai_score ?? 60
  confirmForm.feedback = row.ai_feedback || ''
  confirmVisible.value = true
}

async function submitConfirm() {
  confirming.value = true
  try {
    const res = await teacherApi.confirmSubmission(confirmForm.submissionId, {
      score: confirmForm.score,
      feedback: confirmForm.feedback || null,
    })
    const row = (detail.value?.submissions || []).find((s) => s.id === confirmForm.submissionId)
    if (row) {
      row.score = res.score
      row.feedback = res.feedback
      row.confirmed = true
    }
    ElMessage.success('成绩已确认，学生端可见')
    confirmVisible.value = false
    load()
  } catch { /* 拦截器已提示 */ } finally {
    confirming.value = false
  }
}
</script>

<style scoped>
.back-link { padding: 0; margin-bottom: var(--sp-1); color: var(--text-secondary); }
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
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
.text-block {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.8;
  color: var(--text-primary);
}
.answer {
  max-height: 120px;
  overflow: auto;
  white-space: pre-wrap;
  font-size: var(--fs-xs);
  color: var(--text-primary);
}
.dim { color: var(--text-placeholder); }
.ai-note { margin-top: 2px; font-size: var(--fs-xs); color: var(--text-secondary); }
.confirm-hint { margin-top: var(--sp-2); font-size: var(--fs-xs); color: var(--text-secondary); }
</style>
