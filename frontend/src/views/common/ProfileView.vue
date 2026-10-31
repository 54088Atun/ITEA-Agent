<template>
  <div class="profile-page">
    <div class="profile-card">
      <div class="profile-head">
        <el-button link @click="router.back()">
          <el-icon><ArrowLeft /></el-icon> 返回
        </el-button>
        <h2 class="profile-title">个人中心</h2>
      </div>

      <div class="profile-meta">
        <div class="profile-avatar">{{ initial }}</div>
        <div>
          <p class="profile-name">{{ form.name || '未命名' }}</p>
          <p class="profile-role">{{ roleLabel }}</p>
        </div>
      </div>

      <el-form :model="form" label-width="90px" class="profile-form">
        <el-form-item label="姓名">
          <el-input v-model="form.name" maxlength="50" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="saveProfile">保存资料</el-button>
        </el-form-item>
      </el-form>

      <el-divider />

      <p class="profile-sub">修改密码</p>
      <el-form :model="pwd" label-width="90px" class="profile-form">
        <el-form-item label="原密码">
          <el-input v-model="pwd.old" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwd.next" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="pwd.confirm" type="password" show-password />
        </el-form-item>
        <el-form-item>
          <el-button :loading="changing" @click="changePassword">修改密码</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 学生:学习记录 -->
    <div v-if="userStore.isStudent" class="profile-card">
      <p class="card-title">学习记录</p>
      <div v-loading="recordsLoading" class="timeline-wrap">
        <el-timeline v-if="records.length">
          <el-timeline-item
            v-for="(e, i) in records" :key="i"
            :timestamp="formatTime(e.created_at)" placement="top"
          >
            <div class="record">
              <div class="record__head">
                <el-tag :type="typeTag(e.type)" size="small" effect="light">
                  {{ typeLabel(e.type) }}
                </el-tag>
                <span class="record__title">{{ e.title }}</span>
              </div>
              <div v-if="e.detail" class="record__detail">{{ e.detail }}</div>
              <div v-if="e.course_name" class="record__meta">{{ e.course_name }}</div>
            </div>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else-if="!recordsLoading" description="暂无学习记录" />
      </div>
    </div>

    <!-- 教师:发布记录 -->
    <div v-if="userStore.isTeacher" class="profile-card">
      <div class="card-head">
        <p class="card-title">发布记录</p>
        <el-select
          v-model="classFilter" clearable placeholder="全部班级"
          size="small" style="width: 180px" @change="loadPublish"
        >
          <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
      </div>
      <el-table :data="publishRows" size="small" v-loading="publishLoading">
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag :type="publishTag(row)" size="small" effect="light">
              {{ publishLabel(row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="180" />
        <el-table-column label="课程" width="130">
          <template #default="{ row }">{{ row.course_name || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">{{ statusLabel(row.status) }}</template>
        </el-table-column>
        <el-table-column label="提交 / 已批改" width="130">
          <template #default="{ row }">
            <span v-if="row.submission_count != null">
              {{ row.submission_count }} / {{ row.graded_count }}
            </span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="截止" width="160">
          <template #default="{ row }">{{ formatTime(row.due_at) }}</template>
        </el-table-column>
        <template #empty>
          <div class="empty-state">暂无发布记录</div>
        </template>
      </el-table>
    </div>

    <!-- 账号与数据 -->
    <div class="profile-card">
      <p class="card-title">账号与数据</p>
      <div class="data-actions">
        <el-button :loading="exporting" @click="exportData">
          <el-icon><Download /></el-icon> 导出我的数据
        </el-button>
        <el-button v-if="!userStore.isAdmin" type="danger" plain @click="deactivateVisible = true">
          注销账号
        </el-button>
      </div>
      <p class="hint">
        导出为 JSON，包含账号、课程关系、学习记录与发布记录，不含密码与他人数据。
        注销后个人学习数据、会话与提交记录将被删除且不可恢复。
      </p>
    </div>

    <!-- 注销确认 -->
    <el-dialog v-model="deactivateVisible" title="注销账号" width="480px">
      <el-alert
        type="error" :closable="false" show-icon
        title="注销不可恢复：个人学习数据、会话与提交记录将被删除，账号将被禁用并匿名化。"
      />
      <el-form label-width="88px" class="mt">
        <el-form-item label="登录密码">
          <el-input v-model="deactivateForm.password" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认输入">
          <el-input v-model="deactivateForm.confirm" placeholder="请输入「注销」" maxlength="20" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deactivateVisible = false">取消</el-button>
        <el-button type="danger" :loading="deactivating" @click="doDeactivate">确认注销</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { meApi } from '../../api/me'
import { recordsApi } from '../../api/records'
import { classroomApi } from '../../api/classroom'
import { useUserStore } from '../../stores/user'

const router = useRouter()
const userStore = useUserStore()

const form = reactive({ name: '', email: '' })
const pwd = reactive({ old: '', next: '', confirm: '' })
const saving = ref(false)
const changing = ref(false)

const records = ref([])
const recordsLoading = ref(false)
const publishRows = ref([])
const publishLoading = ref(false)
const classes = ref([])
const classFilter = ref(null)

const exporting = ref(false)
const deactivateVisible = ref(false)
const deactivating = ref(false)
const deactivateForm = reactive({ password: '', confirm: '' })

const initial = computed(() => (form.name || '?').slice(0, 1))
const roleLabel = computed(() => {
  const map = { teacher: '教师', student: '学生', admin: '管理员' }
  return map[userStore.role] || userStore.role
})

onMounted(async () => {
  try {
    const data = await meApi.profile()
    form.name = data.name || ''
    form.email = data.email || ''
  } catch { /* 拦截器已提示 */ }

  if (userStore.isStudent) loadRecords()
  if (userStore.isTeacher) {
    loadClasses()
    loadPublish()
  }
})

async function saveProfile() {
  if (!form.name.trim()) return ElMessage.warning('姓名不能为空')
  saving.value = true
  try {
    const data = await meApi.update({ name: form.name.trim(), email: form.email.trim() })
    userStore.user = { ...(userStore.user || {}), ...data }
    localStorage.setItem('itea_user', JSON.stringify(userStore.user))
    ElMessage.success('资料已保存')
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function changePassword() {
  if (!pwd.old || !pwd.next) return ElMessage.warning('请填写原密码与新密码')
  if (pwd.next.length < 6) return ElMessage.warning('新密码至少 6 位')
  if (pwd.next !== pwd.confirm) return ElMessage.warning('两次输入的新密码不一致')
  changing.value = true
  try {
    await meApi.changePassword(pwd.old, pwd.next)
    ElMessage.success('密码已修改')
    pwd.old = ''
    pwd.next = ''
    pwd.confirm = ''
  } catch { /* 拦截器已提示 */ } finally {
    changing.value = false
  }
}

// ---------- 学习记录 ----------

async function loadRecords() {
  recordsLoading.value = true
  try {
    const rows = await recordsApi.studentRecords(50)
    records.value = Array.isArray(rows) ? rows : []
  } catch { /* 拦截器已提示 */ } finally {
    recordsLoading.value = false
  }
}

function typeLabel(t) {
  return {
    enrollment: '课程', practice: '练习', wrong: '错题',
    review: '复习', interview: '面试', assignment: '作业',
  }[t] || t
}

function typeTag(t) {
  return {
    enrollment: 'info', practice: 'success', wrong: 'danger',
    review: 'warning', interview: 'danger', assignment: '',
  }[t] || 'info'
}

// ---------- 发布记录 ----------

async function loadClasses() {
  try {
    const rows = await classroomApi.list()
    classes.value = Array.isArray(rows) ? rows : []
  } catch { /* 拦截器已提示 */ }
}

async function loadPublish() {
  publishLoading.value = true
  try {
    const rows = await recordsApi.teacherPublishRecords(classFilter.value, 50)
    publishRows.value = Array.isArray(rows) ? rows : []
  } catch { /* 拦截器已提示 */ } finally {
    publishLoading.value = false
  }
}

function publishLabel(row) {
  if (row.type === 'interview') return '面试'
  return row.kind === 'exam' ? '考试' : '作业'
}

function publishTag(row) {
  if (row.type === 'interview') return 'warning'
  return row.kind === 'exam' ? 'danger' : ''
}

function statusLabel(s) {
  return {
    draft: '草稿', published: '已发布', closed: '已关闭',
    active: '进行中', archived: '已归档',
  }[s] || s
}

// ---------- 导出与注销 ----------

async function exportData() {
  exporting.value = true
  try {
    const blob = await meApi.exportData()
    const url = URL.createObjectURL(new Blob([blob], { type: 'application/json' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `itea_export_${userStore.user?.id || 'me'}.json`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    ElMessage.success('已开始下载')
  } catch { /* 拦截器已提示 */ } finally {
    exporting.value = false
  }
}

async function doDeactivate() {
  if (!deactivateForm.password) return ElMessage.warning('请输入登录密码')
  if (deactivateForm.confirm.trim() !== '注销') {
    return ElMessage.warning('请输入「注销」以确认')
  }
  deactivating.value = true
  try {
    await meApi.deactivate(deactivateForm.password, deactivateForm.confirm.trim())
    ElMessage.success('账号已注销')
    userStore.logout()
    router.push('/login')
  } catch { /* 拦截器已提示 */ } finally {
    deactivating.value = false
  }
}

function formatTime(t) {
  if (!t) return '—'
  const d = new Date(t)
  return Number.isNaN(d.getTime()) ? String(t) : d.toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.profile-page {
  min-height: 100vh;
  padding: 48px 16px;
  background: var(--bg-page);
}
.profile-card {
  max-width: 760px;
  margin: 0 auto var(--sp-4);
  padding: 28px 32px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
}
.profile-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin-bottom: var(--sp-5);
}
.profile-title {
  font-family: var(--font-serif);
  font-size: var(--fs-lg);
  color: var(--text-primary);
}
.profile-meta {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin-bottom: var(--sp-5);
}
.profile-avatar {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--grad-brand);
  color: #fff;
  font-size: 18px;
}
.profile-name {
  font-size: var(--fs-md);
  color: var(--text-primary);
}
.profile-role {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.profile-form {
  max-width: 420px;
}
.profile-sub {
  font-size: var(--fs-sm);
  color: var(--text-secondary);
  margin-bottom: var(--sp-3);
}
.card-title {
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: var(--sp-3);
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--sp-3);
}
.timeline-wrap { min-height: 80px; }
.record__head { display: flex; align-items: center; gap: var(--sp-2); }
.record__title { font-size: var(--fs-sm); color: var(--text-primary); }
.record__detail {
  margin-top: 4px;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  white-space: pre-wrap;
}
.record__meta { margin-top: 4px; font-size: var(--fs-xs); color: var(--text-placeholder); }
.data-actions { display: flex; gap: var(--sp-2); margin-bottom: var(--sp-2); }
.hint { font-size: var(--fs-xs); color: var(--text-secondary); line-height: var(--lh-base); }
.dim { color: var(--text-placeholder); }
.mt { margin-top: var(--sp-4); }
</style>
