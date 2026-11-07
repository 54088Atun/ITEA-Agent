<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">作业与考试</h2>
        <p class="page-sub">发布作业或考试后目标学生可见；AI 只给建议，成绩需你确认后才生效</p>
      </div>
      <div class="page-head__actions">
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon> 发布作业 / 考试
        </el-button>
      </div>
    </div>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="截止前学生无法查看参考答案；AI 建议分数不会写入正式成绩，必须由你确认。"
      class="tip"
    />

    <div class="panel">
      <SkeletonTable v-if="loading && !items.length" :rows="6" :cols="6" />
      <StateBlock v-else-if="error" state="error" @retry="load" />
      <el-table v-else :data="items">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="标题" min-width="200">
          <template #default="{ row }">
            <div class="cell-title">
              <el-tag :type="row.kind === 'exam' ? 'danger' : ''" size="small" effect="light">
                {{ row.kind === 'exam' ? '考试' : '作业' }}
              </el-tag>
              <span>{{ row.title }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="面向对象" min-width="160">
          <template #default="{ row }">
            <span v-if="row.class_id">{{ className(row.class_id) }}（班级）</span>
            <span v-else-if="row.course_id">{{ courseName(row.course_id) }}（课程）</span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="截止时间" width="170">
          <template #default="{ row }">{{ formatTime(row.due_at) }}</template>
        </el-table-column>
        <el-table-column label="允许补交" width="110">
          <template #default="{ row }">
            <el-switch
              :model-value="row.allow_late"
              :loading="allowLateId === row.id"
              @change="setAllowLate(row, $event)"
            />
          </template>
        </el-table-column>
        <el-table-column label="提交 / 待确认" width="130">
          <template #default="{ row }">
            <span class="count">{{ row.submission_count }}</span>
            <span v-if="row.pending_count" class="pending">（{{ row.pending_count }} 待确认）</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status)" size="small" effect="light">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openSubmissions(row)">提交情况</el-button>
            <el-button v-if="row.status === 'draft'" link type="success" @click="publish(row)">发布</el-button>
            <el-button v-if="row.status !== 'closed'" link type="warning" @click="close(row)">关闭</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <StateBlock
            state="empty"
            title="还没有作业"
            hint="点击右上角发布第一份作业或考试"
          />
        </template>
      </el-table>
    </div>

    <!-- 发布 -->
    <el-dialog v-model="createVisible" title="发布作业 / 考试" width="560px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
        <el-form-item label="类型">
          <el-radio-group v-model="form.kind">
            <el-radio-button value="homework">作业</el-radio-button>
            <el-radio-button value="exam">考试</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="标题" prop="title">
          <el-input v-model="form.title" placeholder="如：第三章 等价类划分练习" />
        </el-form-item>
        <el-form-item label="面向班级">
          <el-select v-model="form.class_id" clearable filterable placeholder="可选，仅限所选课程下的班级" style="width: 100%">
            <el-option v-for="c in classes" :key="c.id" :label="`${c.name}（${c.member_count} 人）`" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属课程" prop="course_id">
          <el-select v-model="form.course_id" filterable placeholder="必选，作业必须绑定课程" style="width: 100%">
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="作业要求">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="学生可见的题干与要求" />
        </el-form-item>
        <el-form-item label="参考答案">
          <el-input
            v-model="form.reference_answer"
            type="textarea"
            :rows="3"
            placeholder="用于 AI 批改参考；截止前不会下发给学生"
          />
        </el-form-item>
        <el-form-item label="截止天数">
          <el-input-number v-model="form.due_days" :min="1" :max="365" />
          <span class="unit">天（不填则长期有效）</span>
        </el-form-item>
        <el-form-item label="允许补交">
          <el-switch v-model="form.allow_late" active-text="截止后允许正式补交" />
        </el-form-item>
        <el-form-item label="发布状态">
          <el-switch v-model="form.publish" active-text="立即发布" inactive-text="存为草稿" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitCreate">确定</el-button>
      </template>
    </el-dialog>

    <!-- 提交情况 -->
    <el-drawer v-model="drawerVisible" :title="`提交情况 · ${current?.title || ''}`" size="760px">
      <div v-loading="detailLoading" class="drawer-body">
        <div v-if="detail" class="detail-meta">
          <span>截止：{{ formatTime(detail.due_at) }}</span>
          <span>提交 {{ detail.submission_count }} 份 / 待确认 {{ detail.pending_count }} 份</span>
        </div>
        <el-table :data="detail?.submissions || []" size="small">
          <el-table-column prop="student_name" label="学生" width="110" />
          <el-table-column label="提交内容" min-width="180">
            <template #default="{ row }">
              <div class="answer">{{ row.content }}</div>
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
          <el-table-column label="操作" width="170" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" :loading="gradingId === row.id" @click="aiGrade(row)">
                AI 批改
              </el-button>
              <el-button link type="success" @click="openConfirm(row)">确认评分</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <div class="empty-state">暂无学生提交</div>
          </template>
        </el-table>
      </div>
    </el-drawer>

    <!-- 确认评分 -->
    <el-dialog v-model="confirmVisible" title="确认评分（确认后学生可见）" width="520px">
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
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { teacherApi } from '../../api/teacher'
import { classroomApi } from '../../api/classroom'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'

const items = ref([])
const courses = ref([])
const classes = ref([])
const loading = ref(false)
const error = ref(false)

const createVisible = ref(false)
const saving = ref(false)
const formRef = ref()
const form = reactive({
  kind: 'homework',
  title: '',
  course_id: null,
  class_id: null,
  description: '',
  reference_answer: '',
  due_days: 7,
  allow_late: false,
  publish: true,
})
const rules = {
  title: [{ required: true, message: '请输入标题', trigger: 'blur' }],
  course_id: [{ required: true, message: '请选择课程', trigger: 'change' }],
}

const drawerVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)
const current = ref(null)
const gradingId = ref(null)
const allowLateId = ref(null)

const confirmVisible = ref(false)
const confirming = ref(false)
const confirmForm = reactive({ submissionId: null, score: 60, feedback: '' })

onMounted(load)

async function load() {
  loading.value = true
  error.value = false
  try {
    const [rows, cs, cls] = await Promise.all([
      teacherApi.assignments(),
      teacherApi.courses(),
      classroomApi.list(),
    ])
    items.value = Array.isArray(rows) ? rows : []
    courses.value = Array.isArray(cs) ? cs : []
    classes.value = Array.isArray(cls) ? cls : []
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

function courseName(id) {
  return courses.value.find((c) => c.id === id)?.name || `课程 #${id}`
}

function className(id) {
  return classes.value.find((c) => c.id === id)?.name || `班级 #${id}`
}

function formatTime(t) {
  if (!t) return '不限'
  return String(t).replace('T', ' ').slice(0, 16)
}

function statusLabel(s) {
  return { draft: '草稿', published: '已发布', closed: '已关闭' }[s] || s
}

function statusTag(s) {
  return { draft: 'info', published: 'success', closed: 'warning' }[s] || 'info'
}

function openCreate() {
  Object.assign(form, {
    kind: 'homework', title: '', course_id: null, class_id: null,
    description: '', reference_answer: '', due_days: 7, allow_late: false, publish: true,
  })
  createVisible.value = true
}

async function submitCreate() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  if (!form.course_id) {
    return ElMessage.warning('作业必须绑定课程，请先选择课程')
  }
  saving.value = true
  try {
    await teacherApi.createAssignment({
      title: form.title,
      kind: form.kind,
      course_id: form.course_id || null,
      class_id: form.class_id || null,
      description: form.description || null,
      reference_answer: form.reference_answer || null,
      due_days: form.due_days || null,
      allow_late: form.allow_late,
      publish: form.publish,
    })
    ElMessage.success(form.publish ? '已发布' : '已存为草稿')
    createVisible.value = false
    load()
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function publish(row) {
  try {
    await ElMessageBox.confirm('发布后学生将收到通知并可提交，确定发布？', '发布作业', { type: 'warning' })
  } catch { return }
  try {
    await teacherApi.publishAssignment(row.id, true)
    ElMessage.success('已发布')
    load()
  } catch { /* 拦截器已提示 */ }
}

async function close(row) {
  try {
    await ElMessageBox.confirm('关闭后学生将无法再提交，确定关闭？', '关闭作业', { type: 'warning' })
  } catch { return }
  try {
    await teacherApi.closeAssignment(row.id, true)
    ElMessage.success('已关闭')
    load()
  } catch { /* 拦截器已提示 */ }
}

async function setAllowLate(row, enabled) {
  allowLateId.value = row.id
  try {
    await teacherApi.setAssignmentAllowLate(row.id, enabled)
    row.allow_late = enabled
    ElMessage.success(enabled ? '已开放正式补交' : '已关闭补交')
  } catch { /* 拦截器已提示 */ } finally {
    allowLateId.value = null
  }
}

async function openSubmissions(row) {
  current.value = row
  drawerVisible.value = true
  detail.value = null
  detailLoading.value = true
  try {
    detail.value = await teacherApi.assignment(row.id)
  } catch { /* 拦截器已提示 */ } finally {
    detailLoading.value = false
  }
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
.tip { margin-bottom: var(--sp-3); }
.cell-title { display: flex; align-items: center; gap: var(--sp-2); }
.count { color: var(--text-primary); }
.pending { color: var(--color-warning, #b26a00); font-size: var(--fs-xs); }
.dim { color: var(--text-placeholder); }
.drawer-body { display: flex; flex-direction: column; gap: var(--sp-3); }
.detail-meta { display: flex; gap: var(--sp-4); font-size: var(--fs-xs); color: var(--text-secondary); }
.answer {
  max-height: 96px;
  overflow: auto;
  white-space: pre-wrap;
  font-size: var(--fs-xs);
  color: var(--text-primary);
}
.ai-note { font-size: var(--fs-xs); color: var(--text-secondary); margin-top: 2px; }
.confirm-hint { margin-top: var(--sp-2); font-size: var(--fs-xs); color: var(--text-secondary); }
.unit { margin-left: var(--sp-2); font-size: var(--fs-xs); color: var(--text-secondary); }
</style>
