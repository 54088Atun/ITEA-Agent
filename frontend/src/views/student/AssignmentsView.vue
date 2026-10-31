<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">我的作业</h2>
        <p class="page-sub">教师发布的作业与考试；提交后待教师确认评分才显示成绩</p>
      </div>
    </div>

    <div class="panel">
      <el-table :data="items" v-loading="loading">
        <el-table-column label="标题" min-width="220">
          <template #default="{ row }">
            <div class="cell-title">
              <el-tag :type="row.kind === 'exam' ? 'danger' : ''" size="small" effect="light">
                {{ row.kind === 'exam' ? '考试' : '作业' }}
              </el-tag>
              <span>{{ row.title }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="course_name" label="课程" width="160">
          <template #default="{ row }">{{ row.course_name || '—' }}</template>
        </el-table-column>
        <el-table-column prop="teacher_name" label="发布教师" width="120" />
        <el-table-column label="截止时间" width="170">
          <template #default="{ row }">{{ formatTime(row.due_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="{ row }">
            <el-tag :type="stateTag(row.state)" size="small" effect="light">
              {{ stateLabel(row.state) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="成绩" width="100">
          <template #default="{ row }">
            <span v-if="row.state === 'graded'">{{ row.score }} 分</span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">查看 / 提交</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-state">暂无作业，加入班级或选课后即可看到教师发布的作业</div>
        </template>
      </el-table>
    </div>

    <!-- 详情 -->
    <el-drawer v-model="drawerVisible" :title="detail?.title || '作业详情'" size="560px">
      <div v-if="detail" class="detail" v-loading="detailLoading">
        <div class="detail__meta">
          <el-tag :type="detail.kind === 'exam' ? 'danger' : ''" size="small" effect="light">
            {{ detail.kind === 'exam' ? '考试' : '作业' }}
          </el-tag>
          <el-tag :type="stateTag(detail.state)" size="small" effect="light">
            {{ stateLabel(detail.state) }}
          </el-tag>
          <span class="dim">截止：{{ formatTime(detail.due_at) }}</span>
        </div>

        <section class="block">
          <h4 class="block__title">作业要求</h4>
          <div class="block__text">{{ detail.description || '教师未填写额外说明' }}</div>
        </section>

        <section v-if="detail.my_submission" class="block">
          <h4 class="block__title">我的提交</h4>
          <div class="block__text">{{ detail.my_submission.content }}</div>
        </section>

        <section v-if="detail.my_submission?.confirmed" class="block">
          <h4 class="block__title">教师评分</h4>
          <div class="score-row">
            <span class="score">{{ detail.my_submission.score }}</span>
            <span class="dim">分</span>
          </div>
          <div class="block__text">{{ detail.my_submission.feedback || '教师未填写评语' }}</div>
        </section>

        <el-alert
          v-else-if="detail.my_submission"
          type="warning"
          :closable="false"
          show-icon
          title="已提交，待教师确认评分"
          description="AI 仅提供批改建议，正式成绩以教师确认为准。"
        />

        <section v-if="detail.reference_answer" class="block">
          <h4 class="block__title">参考答案（已截止）</h4>
          <div class="block__text">{{ detail.reference_answer }}</div>
        </section>

        <div class="detail__actions">
          <el-button
            type="primary"
            :disabled="detail.due_passed || detail.state === 'graded'"
            @click="openSubmit"
          >
            {{ detail.my_submission ? '重新提交' : '提交作业' }}
          </el-button>
          <span v-if="detail.due_passed" class="dim">已过截止时间，无法提交</span>
        </div>
      </div>
    </el-drawer>

    <!-- 提交 -->
    <el-dialog v-model="submitVisible" title="提交作业" width="560px">
      <el-input
        v-model="answer"
        type="textarea"
        :rows="8"
        placeholder="请输入你的作答内容"
      />
      <p class="hint">提交后可在截止前修改；教师确认评分后不可再改。</p>
      <template #footer>
        <el-button @click="submitVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="doSubmit">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { studentApi } from '../../api/student'

const items = ref([])
const loading = ref(false)
const drawerVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)
const submitVisible = ref(false)
const submitting = ref(false)
const answer = ref('')

onMounted(load)

async function load() {
  loading.value = true
  try {
    const rows = await studentApi.assignments()
    items.value = Array.isArray(rows) ? rows : []
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
    not_submitted: '未提交',
    pending_review: '待教师确认',
    graded: '已批改',
    overdue: '已逾期',
  }[s] || s
}

function stateTag(s) {
  return {
    not_submitted: 'info',
    pending_review: 'warning',
    graded: 'success',
    overdue: 'danger',
  }[s] || 'info'
}

async function openDetail(row) {
  drawerVisible.value = true
  detail.value = null
  detailLoading.value = true
  try {
    detail.value = await studentApi.assignment(row.id)
  } catch { /* 拦截器已提示 */ } finally {
    detailLoading.value = false
  }
}

function openSubmit() {
  answer.value = detail.value?.my_submission?.content || ''
  submitVisible.value = true
}

async function doSubmit() {
  if (!answer.value.trim()) return ElMessage.warning('请输入作答内容')
  submitting.value = true
  try {
    await studentApi.submitAssignment(detail.value.id, { content: answer.value.trim() })
    ElMessage.success('提交成功，等待教师确认评分')
    submitVisible.value = false
    await openDetail({ id: detail.value.id })
    load()
  } catch { /* 拦截器已提示 */ } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.cell-title { display: flex; align-items: center; gap: var(--sp-2); }
.dim { color: var(--text-placeholder); }
.detail { display: flex; flex-direction: column; gap: var(--sp-4); }
.detail__meta { display: flex; align-items: center; gap: var(--sp-3); font-size: var(--fs-xs); }
.block { display: flex; flex-direction: column; gap: var(--sp-2); }
.block__title { margin: 0; font-size: var(--fs-sm); font-weight: 600; color: var(--text-primary); }
.block__text {
  font-size: var(--fs-sm);
  line-height: var(--lh-base);
  color: var(--text-primary);
  white-space: pre-wrap;
  background: var(--bg-subtle);
  border-radius: var(--r-sm);
  padding: var(--sp-3);
}
.score-row { display: flex; align-items: baseline; gap: var(--sp-1); }
.score { font-size: 28px; font-weight: 700; color: var(--color-primary); }
.detail__actions { display: flex; align-items: center; gap: var(--sp-3); }
.hint { margin-top: var(--sp-2); font-size: var(--fs-xs); color: var(--text-secondary); }
</style>
