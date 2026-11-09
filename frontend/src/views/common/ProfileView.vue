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
        <div class="profile-avatar">
          <img v-if="avatarUrl" :src="resolveAsset(avatarUrl)" alt="头像" />
          <span v-else>{{ initial }}</span>
        </div>
        <div>
          <p class="profile-name">{{ form.name || '未命名' }}</p>
          <p class="profile-role">{{ roleLabel }}</p>
          <el-button
            size="small" text type="primary"
            :loading="uploadingAvatar" @click="pickAvatar"
          >更换头像</el-button>
          <input
            ref="avatarInput" type="file" accept="image/png,image/jpeg,image/webp"
            class="avatar-input" @change="onAvatarChange"
          />
        </div>
      </div>

      <div class="profile-overview">
        <div class="profile-overview__item">
          <span class="profile-overview__label">用户 ID</span>
          <strong>#{{ userStore.user?.id || '—' }}</strong>
        </div>
        <div class="profile-overview__item">
          <span class="profile-overview__label">账号角色</span>
          <strong>{{ roleLabel }}</strong>
        </div>
        <div class="profile-overview__item">
          <span class="profile-overview__label">账号状态</span>
          <strong>{{ accountStatusLabel }}</strong>
        </div>
        <div class="profile-overview__item">
          <span class="profile-overview__label">邮箱</span>
          <strong>{{ form.email || '未填写' }}</strong>
        </div>
        <template v-if="userStore.isTeacher">
          <div class="profile-overview__item">
            <span class="profile-overview__label">我的班级</span>
            <strong>{{ classes.length }}</strong>
          </div>
          <div class="profile-overview__item">
            <span class="profile-overview__label">发布记录</span>
            <strong>{{ publishRows.length }}</strong>
          </div>
          <div class="profile-overview__item">
            <span class="profile-overview__label">待批改</span>
            <strong>{{ pendingGradeCount }}</strong>
          </div>
        </template>
        <template v-else-if="userStore.isStudent">
          <div class="profile-overview__item">
            <span class="profile-overview__label">学习记录</span>
            <strong>{{ records.length }}</strong>
          </div>
        </template>
      </div>

      <el-form :model="form" label-width="90px" class="profile-form">
        <el-form-item label="姓名">
          <el-input v-model="form.name" maxlength="50" />
        </el-form-item>
        <el-form-item label="邮箱">
          <div class="email-row">
            <span class="email-row__text">{{ form.email || '未填写' }}</span>
            <el-button size="small" text type="primary" @click="openEmailChange">
              更换邮箱
            </el-button>
          </div>
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
          <el-button :loading="loggingOutAll" @click="logoutAllDevices">退出全部设备</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 隐私设置 -->
    <div class="profile-card">
      <p class="card-title">隐私设置</p>
      <el-form label-width="110px" class="profile-form">
        <el-form-item label="姓名可见范围">
          <el-select v-model="privacy.name_visibility" style="width: 220px">
            <el-option label="仅自己" value="private" />
            <el-option label="教师可见" value="teachers" />
            <el-option label="同学可见" value="classmates" />
          </el-select>
        </el-form-item>
        <el-form-item label="邮箱可见范围">
          <el-select v-model="privacy.email_visibility" style="width: 220px">
            <el-option label="仅自己" value="private" />
            <el-option label="教师可见" value="teachers" />
            <el-option label="同学可见" value="classmates" />
          </el-select>
        </el-form-item>
        <el-form-item label="学习记录">
          <el-select v-model="privacy.learning_visibility" style="width: 220px">
            <el-option label="仅自己" value="private" />
            <el-option label="教师可见" value="teachers" />
            <el-option label="同学可见" value="classmates" />
          </el-select>
          <span class="privacy-tip">设为「仅自己」后，教师报表不再展示你的学习明细</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="privacySaving" @click="savePrivacy">保存隐私设置</el-button>
        </el-form-item>
      </el-form>
    </div>

    <!-- 学生:学习记录 -->
    <div v-if="userStore.isStudent" class="profile-card">
      <p class="card-title">学习记录</p>
      <div class="timeline-wrap">
        <div v-if="recordsLoading && !records.length" class="timeline-skeleton">
          <SkeletonCard v-for="n in 3" :key="n" :rows="2" />
        </div>
        <StateBlock
          v-else-if="recordsError"
          state="error"
          title="学习记录加载失败"
          @retry="loadRecords"
        />
        <el-timeline v-else-if="records.length">
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
        <StateBlock v-else state="empty" title="暂无学习记录" hint="完成作业、考试或复习后会记录在这里" />
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
      <SkeletonTable v-if="publishLoading && !publishRows.length" :rows="5" :cols="5" />
      <StateBlock
        v-else-if="publishError"
        state="error"
        title="发布记录加载失败"
        @retry="loadPublish"
      />
      <el-table v-else :data="publishRows" size="small">
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
          <StateBlock state="empty" title="暂无发布记录" hint="发布作业或考试后会出现在这里" />
        </template>
      </el-table>
    </div>

    <!-- 我的识图图片 -->
    <div class="profile-card">
      <div class="card-head">
        <p class="card-title">我的识图图片</p>
        <el-button text size="small" :loading="imagesLoading" @click="loadImages">刷新</el-button>
      </div>
      <div>
        <div v-if="imagesLoading && !images.length" class="image-grid">
          <SkeletonCard v-for="n in 4" :key="n" :rows="2" />
        </div>
        <StateBlock
          v-else-if="imagesError"
          state="error"
          title="识图图片加载失败"
          @retry="loadImages"
        />
        <div v-else-if="images.length" class="image-grid">
          <div v-for="img in images" :key="img.filename" class="image-item">
            <img :src="resolveAsset(img.path)" :alt="img.filename" />
            <div class="image-meta">
              <span>{{ formatTime(img.created_at) }}</span>
              <el-button text type="danger" size="small" @click="removeImage(img)">删除</el-button>
            </div>
          </div>
        </div>
        <StateBlock v-else state="empty" title="暂无识图图片" hint="在对话中拍照识图后会出现在这里" />
      </div>
      <p class="hint">识图原图保留 30 天后自动清理，也可在此提前删除。</p>
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

    <!-- 更换邮箱 -->
    <el-dialog v-model="emailChangeVisible" title="更换邮箱" width="420px" @closed="resetEmailChange">
      <el-alert
        type="info" :closable="false" show-icon
        title="验证码将发送到新邮箱，验证通过后立即生效；新邮箱不能已被其他账号使用。"
      />
      <el-form label-position="top" class="mt">
        <el-form-item label="当前邮箱">
          <el-input :model-value="form.email" disabled />
        </el-form-item>
        <el-form-item label="新邮箱">
          <el-input v-model="emailChange.email" placeholder="name@campus.edu" />
        </el-form-item>
        <el-form-item label="邮箱验证码">
          <div class="email-code-row">
            <el-input v-model="emailChange.code" maxlength="6" placeholder="6 位验证码" />
            <el-button
              :loading="emailCodeSending"
              :disabled="emailCodeCountdown > 0"
              @click="sendEmailChangeCode"
            >
              {{ emailCodeCountdown > 0 ? `${emailCodeCountdown}s 后重发` : '发送验证码' }}
            </el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="emailChangeVisible = false">取消</el-button>
        <el-button type="primary" :loading="emailChanging" @click="submitEmailChange">
          确认更换
        </el-button>
      </template>
    </el-dialog>

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
import { ref, reactive, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { authApi } from '../../api/auth'
import { meApi } from '../../api/me'
import { recordsApi } from '../../api/records'
import { classroomApi } from '../../api/classroom'
import { uploadApi } from '../../api/uploads'
import { resolveAsset } from '../../utils/asset.js'
import { useUserStore } from '../../stores/user'
import SkeletonCard from '../../components/SkeletonCard.vue'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'

const router = useRouter()
const userStore = useUserStore()

const form = reactive({ name: '', email: '' })
const avatarUrl = ref('')
const avatarInput = ref(null)
const uploadingAvatar = ref(false)
const privacy = reactive({
  name_visibility: 'classmates',
  email_visibility: 'private',
  learning_visibility: 'teachers',
})
const privacySaving = ref(false)
const pwd = reactive({ old: '', next: '', confirm: '' })
const saving = ref(false)
const changing = ref(false)
const loggingOutAll = ref(false)

const records = ref([])
const recordsLoading = ref(false)
const recordsError = ref(false)
const publishRows = ref([])
const publishLoading = ref(false)
const publishError = ref(false)
const classes = ref([])
const classFilter = ref(null)

const images = ref([])
const imagesLoading = ref(false)
const imagesError = ref(false)

const exporting = ref(false)
const deactivateVisible = ref(false)
const deactivating = ref(false)
const deactivateForm = reactive({ password: '', confirm: '' })

// 更换邮箱:验证码发送到新邮箱,验证通过后生效
const emailChangeVisible = ref(false)
const emailChange = reactive({ email: '', code: '' })
const emailCodeSending = ref(false)
const emailChanging = ref(false)
const emailCodeCountdown = ref(0)
let emailCodeTimer = null

onUnmounted(() => {
  if (emailCodeTimer) clearInterval(emailCodeTimer)
})

const initial = computed(() => (form.name || '?').slice(0, 1))
const roleLabel = computed(() => {
  const map = { teacher: '教师', student: '学生', admin: '管理员' }
  return map[userStore.role] || userStore.role
})
const accountStatusLabel = computed(() => (
  { active: '正常', disabled: '已禁用' }[userStore.user?.status] || '正常'
))
const pendingGradeCount = computed(() => publishRows.value.reduce((sum, row) => {
  if (row.submission_count == null) return sum
  return sum + Math.max(0, Number(row.submission_count) - Number(row.graded_count || 0))
}, 0))

onMounted(async () => {
  try {
    const data = await meApi.profile()
    form.name = data.name || ''
    form.email = data.email || ''
    avatarUrl.value = data.avatar_url || ''
  } catch { /* 拦截器已提示 */ }

  loadPrivacy()
  loadImages()

  if (userStore.isStudent) loadRecords()
  if (userStore.isTeacher) {
    loadClasses()
    loadPublish()
  }
})

function pickAvatar() {
  avatarInput.value?.click()
}

async function onAvatarChange(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (!/image\/(png|jpe?g|webp)/.test(file.type)) {
    return ElMessage.warning('仅支持 PNG / JPG / WEBP 图片')
  }
  if (file.size > 2 * 1024 * 1024) {
    return ElMessage.warning('头像不能超过 2MB')
  }
  uploadingAvatar.value = true
  try {
    const data = await meApi.uploadAvatar(file)
    avatarUrl.value = data.avatar_url
    userStore.user = { ...(userStore.user || {}), avatar_url: data.avatar_url }
    localStorage.setItem('itea_user', JSON.stringify(userStore.user))
    ElMessage.success('头像已更新')
  } catch { /* 拦截器已提示 */ } finally {
    uploadingAvatar.value = false
  }
}

async function loadPrivacy() {
  try {
    Object.assign(privacy, await meApi.privacy())
  } catch { /* 拦截器已提示 */ }
}

async function savePrivacy() {
  privacySaving.value = true
  try {
    Object.assign(privacy, await meApi.updatePrivacy({ ...privacy }))
    ElMessage.success('隐私设置已保存')
  } catch { /* 拦截器已提示 */ } finally {
    privacySaving.value = false
  }
}

async function saveProfile() {
  if (!form.name.trim()) return ElMessage.warning('姓名不能为空')
  saving.value = true
  try {
    // 邮箱变更必须走验证码流程,这里只保存姓名
    const data = await meApi.update({ name: form.name.trim() })
    userStore.user = { ...(userStore.user || {}), ...data }
    localStorage.setItem('itea_user', JSON.stringify(userStore.user))
    ElMessage.success('资料已保存')
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

function errorText(err, fallback) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) return detail[0]?.msg || fallback
  if (!err?.response) return '无法连接服务器，请稍后重试'
  return fallback
}

function startEmailCountdown(seconds, previous) {
  if (previous) clearInterval(previous)
  emailCodeCountdown.value = Math.max(1, Number(seconds) || 60)
  const handle = setInterval(() => {
    emailCodeCountdown.value -= 1
    if (emailCodeCountdown.value <= 0) clearInterval(handle)
  }, 1000)
  return handle
}

function openEmailChange() {
  emailChange.email = ''
  emailChange.code = ''
  emailCodeCountdown.value = 0
  emailChangeVisible.value = true
}

function resetEmailChange() {
  emailChange.email = ''
  emailChange.code = ''
}

async function sendEmailChangeCode() {
  const email = emailChange.email.trim()
  if (!email) return ElMessage.warning('请输入新邮箱')
  if (email.toLowerCase() === (form.email || '').trim().toLowerCase()) {
    return ElMessage.warning('新邮箱与当前邮箱相同')
  }
  emailCodeSending.value = true
  try {
    const data = await authApi.sendEmailChangeCode({ email })
    emailCodeTimer = startEmailCountdown(data.resend_after, emailCodeTimer)
    ElMessage.success(`验证码已发送至 ${data.masked_email || email}`)
  } catch (err) {
    ElMessage.error(errorText(err, '发送失败，请稍后重试'))
  } finally {
    emailCodeSending.value = false
  }
}

async function submitEmailChange() {
  const email = emailChange.email.trim()
  if (!email) return ElMessage.warning('请输入新邮箱')
  if (!emailChange.code.trim()) return ElMessage.warning('请输入邮箱验证码')
  emailChanging.value = true
  try {
    const data = await authApi.changeEmail({ email, code: emailChange.code.trim() })
    form.email = data.email
    userStore.user = { ...(userStore.user || {}), ...data }
    localStorage.setItem('itea_user', JSON.stringify(userStore.user))
    emailChangeVisible.value = false
    ElMessage.success('邮箱已更换')
  } catch (err) {
    ElMessage.error(errorText(err, '更换失败，请稍后重试'))
  } finally {
    emailChanging.value = false
  }
}

async function changePassword() {
  if (!pwd.old || !pwd.next) return ElMessage.warning('请填写原密码与新密码')
  if (pwd.next.length < 6) return ElMessage.warning('新密码至少 6 位')
  if (pwd.next !== pwd.confirm) return ElMessage.warning('两次输入的新密码不一致')
  changing.value = true
  try {
    await meApi.changePassword(pwd.old, pwd.next)
    ElMessage.success('密码已修改，请重新登录')
    userStore.logout()
    await router.push('/login')
  } catch { /* 拦截器已提示 */ } finally {
    changing.value = false
  }
}

async function logoutAllDevices() {
  try {
    await ElMessageBox.confirm(
      '退出后所有设备上的登录状态都会立即失效，需要重新登录。',
      '退出全部设备',
      { type: 'warning', confirmButtonText: '退出全部', cancelButtonText: '取消' },
    )
  } catch { return }
  loggingOutAll.value = true
  try {
    await meApi.logoutAll()
    userStore.logout()
    ElMessage.success('已退出全部设备')
    await router.push('/login')
  } catch { /* 拦截器已提示 */ } finally {
    loggingOutAll.value = false
  }
}

// ---------- 学习记录 ----------

async function loadRecords() {
  recordsError.value = false
  recordsLoading.value = true
  try {
    const rows = await recordsApi.studentRecords(50)
    records.value = Array.isArray(rows) ? rows : []
  } catch { recordsError.value = true } finally {
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
  publishError.value = false
  publishLoading.value = true
  try {
    const rows = await recordsApi.teacherPublishRecords(classFilter.value, 50)
    publishRows.value = Array.isArray(rows) ? rows : []
  } catch { publishError.value = true } finally {
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

// ---------- 识图图片自助管理 ----------

async function loadImages() {
  imagesError.value = false
  imagesLoading.value = true
  try {
    const data = await uploadApi.listMine()
    images.value = data.items || []
  } catch { imagesError.value = true } finally {
    imagesLoading.value = false
  }
}

async function removeImage(img) {
  try {
    await ElMessageBox.confirm('删除后无法恢复，确定删除这张识图图片？', '删除图片', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch { return }
  try {
    await uploadApi.removeMine(img.filename)
    images.value = images.value.filter((item) => item.filename !== img.filename)
    ElMessage.success('已删除')
  } catch { /* 拦截器已提示 */ }
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
  overflow: hidden;
}
.profile-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.avatar-input { display: none; }
.privacy-tip {
  margin-left: var(--sp-3);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
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
.email-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
}
.email-row__text {
  flex: 1;
  font-size: var(--fs-sm);
  color: var(--text-primary);
}
.email-code-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
}
.email-code-row :deep(.el-button) {
  flex: 0 0 auto;
  min-width: 108px;
}
.profile-overview {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
  margin-top: 18px;
}
.profile-overview__item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--bg-subtle);
}
.profile-overview__label {
  color: var(--text-secondary);
  font-size: var(--fs-xs);
}
.profile-overview__item strong {
  overflow: hidden;
  color: var(--text-primary);
  font-size: var(--fs-sm);
  text-overflow: ellipsis;
  white-space: nowrap;
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
.timeline-skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: var(--sp-3);
  margin-bottom: var(--sp-2);
}
.image-item {
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  overflow: hidden;
}
.image-item img {
  display: block;
  width: 100%;
  height: 110px;
  object-fit: cover;
  background: var(--bg-page);
}
.image-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-1);
  padding: 4px 8px;
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
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

/* 窄屏收紧卡片留白，保证居中卡片列不挤压内容 */
@media (max-width: 640px) {
  .profile-page { padding: 24px 12px; }
  .profile-card { padding: 20px 16px; }
  .data-actions { flex-wrap: wrap; }
}
</style>
