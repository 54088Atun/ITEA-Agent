<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">班级管理</h2>
        <p class="page-sub">学生凭邀请码加入班级后，才能看到你绑定到该班级的课程</p>
      </div>
      <div class="page-head__actions">
        <el-button @click="openAssign">
          <el-icon><VideoCamera /></el-icon> 发布面试作业
        </el-button>
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon> 新建班级
        </el-button>
      </div>
    </div>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="课程默认仅自己可见；学生加入班级后自动获得该班级课程的访问权，退出班级则收回。"
      class="tip"
    />

    <div class="panel">
      <el-table :data="items" v-loading="loading">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="name" label="班级名称" min-width="160" />
        <el-table-column label="绑定课程" min-width="160">
          <template #default="{ row }">
            <span v-if="row.course_name">{{ row.course_name }}</span>
            <span v-else class="dim">未绑定</span>
          </template>
        </el-table-column>
        <el-table-column prop="semester" label="学期" width="110">
          <template #default="{ row }">{{ row.semester || '—' }}</template>
        </el-table-column>
        <el-table-column prop="member_count" label="学生数" width="90" />
        <el-table-column label="邀请码" width="150">
          <template #default="{ row }">
            <el-button link type="primary" @click="copyCode(row.invite_code)">
              {{ row.invite_code }}
            </el-button>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small" effect="light">
              {{ row.status === 'active' ? '进行中' : '已归档' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openMembers(row)">成员</el-button>
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="warning" @click="resetInvite(row)">重置邀请码</el-button>
            <el-button
              v-if="row.status === 'active'"
              link
              type="danger"
              @click="archive(row)"
            >
              归档
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-state">还没有班级，先新建一个并绑定课程</div>
        </template>
      </el-table>
    </div>

    <!-- 新建 / 编辑 -->
    <el-dialog v-model="formVisible" :title="form.id ? '编辑班级' : '新建班级'" width="520px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
        <el-form-item label="班级名称" prop="name">
          <el-input v-model="form.name" placeholder="如：2026 秋 软件测试 1 班" />
        </el-form-item>
        <el-form-item label="绑定课程">
          <el-select v-model="form.course_id" clearable placeholder="可选择不绑定" style="width: 100%">
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="学期">
          <el-input v-model="form.semester" placeholder="如：2026秋" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <template v-if="!form.id">
          <el-form-item label="邀请码有效">
            <el-input-number v-model="form.invite_days" :min="1" :max="365" />
            <span class="unit">天</span>
          </el-form-item>
          <el-form-item label="可用次数">
            <el-input-number v-model="form.invite_max_uses" :min="1" :max="1000" />
            <span class="unit">次</span>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 成员 -->
    <el-drawer v-model="membersVisible" :title="`成员 · ${current?.name || ''}`" size="520px">
      <div class="invite-row">
        <el-input v-model="inviteKeyword" placeholder="学生邮箱或学生 ID" />
        <el-button type="primary" :loading="inviting" @click="invite">邀请</el-button>
      </div>
      <el-table :data="members" v-loading="memberLoading" size="small">
        <el-table-column prop="student_id" label="ID" width="70" />
        <el-table-column prop="name" label="姓名" width="110" />
        <el-table-column prop="email" label="邮箱" min-width="180" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small" effect="light">
              {{ row.status === 'active' ? '在班' : '已退出' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'active'"
              link
              type="danger"
              @click="removeMember(row)"
            >
              移出
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-state">暂无成员，可复制邀请码发给学生</div>
        </template>
      </el-table>
    </el-drawer>

    <!-- 发布面试作业 -->
    <el-dialog v-model="assignVisible" title="发布面试作业" width="520px">
      <el-form label-width="96px">
        <el-form-item label="作业标题">
          <el-input v-model="assignForm.title" placeholder="如：第三章 单元面试" />
        </el-form-item>
        <el-form-item label="面向班级">
          <el-select v-model="assignForm.class_id" clearable placeholder="可选" style="width: 100%">
            <el-option v-for="c in items" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="面向课程">
          <el-select v-model="assignForm.course_id" clearable placeholder="可选" style="width: 100%">
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="assignForm.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="截止天数">
          <el-input-number v-model="assignForm.due_days" :min="1" :max="60" />
          <span class="unit">天</span>
        </el-form-item>
      </el-form>
      <p class="assign-hint">发布后，班级学生或已选该课程的学生会在「模拟面试」页看到该作业。</p>
      <template #footer>
        <el-button @click="assignVisible = false">取消</el-button>
        <el-button type="primary" :loading="assignSaving" @click="submitAssign">发布</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { classroomApi } from '../../api/classroom'
import { courseApi } from '../../api/course'
import { teacherApi } from '../../api/teacher'

const loading = ref(false)
const saving = ref(false)
const items = ref([])
const courses = ref([])

const formVisible = ref(false)
const formRef = ref()
const form = reactive({
  id: null,
  name: '',
  course_id: null,
  semester: '',
  description: '',
  invite_days: 7,
  invite_max_uses: 50,
})
const rules = {
  name: [{ required: true, message: '请输入班级名称', trigger: 'blur' }],
}

const membersVisible = ref(false)
const memberLoading = ref(false)
const inviting = ref(false)
const current = ref(null)
const members = ref([])
const inviteKeyword = ref('')

// 面试作业
const assignVisible = ref(false)
const assignSaving = ref(false)
const assignForm = reactive({
  title: '', class_id: null, course_id: null, description: '', due_days: 7,
})

onMounted(async () => {
  await Promise.all([load(), loadCourses()])
})

async function load() {
  loading.value = true
  try {
    items.value = await classroomApi.list()
  } catch { /* 拦截器已提示 */ } finally {
    loading.value = false
  }
}

async function loadCourses() {
  try {
    const data = await courseApi.list()
    courses.value = Array.isArray(data) ? data : []
  } catch { /* 拦截器已提示 */ }
}

function openAssign() {
  Object.assign(assignForm, {
    title: '',
    class_id: items.value[0]?.id || null,
    course_id: courses.value[0]?.id || null,
    description: '',
    due_days: 7,
  })
  assignVisible.value = true
}

async function submitAssign() {
  if (!assignForm.title.trim()) return ElMessage.warning('请输入作业标题')
  if (!assignForm.class_id && !assignForm.course_id) {
    return ElMessage.warning('请选择面向班级或课程')
  }
  assignSaving.value = true
  try {
    await teacherApi.createInterviewAssignment({
      title: assignForm.title.trim(),
      class_id: assignForm.class_id,
      course_id: assignForm.course_id,
      description: assignForm.description,
      due_days: assignForm.due_days,
    })
    ElMessage.success('面试作业已发布')
    assignVisible.value = false
  } catch { /* 拦截器已提示 */ } finally {
    assignSaving.value = false
  }
}

function openCreate() {
  Object.assign(form, {
    id: null,
    name: '',
    course_id: null,
    semester: '',
    description: '',
    invite_days: 7,
    invite_max_uses: 50,
  })
  formVisible.value = true
}

function openEdit(row) {
  Object.assign(form, {
    id: row.id,
    name: row.name,
    course_id: row.course_id || null,
    semester: row.semester || '',
    description: row.description || '',
    invite_days: 7,
    invite_max_uses: row.invite_max_uses,
  })
  formVisible.value = true
}

async function save() {
  await formRef.value.validate()
  saving.value = true
  try {
    if (form.id) {
      await classroomApi.update(form.id, {
        name: form.name,
        course_id: form.course_id,
        semester: form.semester,
        description: form.description,
      })
      ElMessage.success('班级已更新')
    } else {
      await classroomApi.create({
        name: form.name,
        course_id: form.course_id,
        semester: form.semester,
        description: form.description,
        invite_days: form.invite_days,
        invite_max_uses: form.invite_max_uses,
      })
      ElMessage.success('班级已创建')
    }
    formVisible.value = false
    load()
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function copyCode(code) {
  try {
    await navigator.clipboard.writeText(code)
    ElMessage.success(`邀请码 ${code} 已复制`)
  } catch {
    ElMessage.info(`邀请码：${code}`)
  }
}

async function resetInvite(row) {
  try {
    await ElMessageBox.confirm('重置后旧邀请码立即失效，确认继续？', '提示', { type: 'warning' })
  } catch { return }
  try {
    const data = await classroomApi.resetInvite(row.id)
    ElMessage.success(`新邀请码：${data.invite_code}`)
    load()
  } catch { /* 拦截器已提示 */ }
}

async function archive(row) {
  try {
    await ElMessageBox.confirm(`确认归档班级「${row.name}」？成员与学情数据保留。`, '提示', { type: 'warning' })
  } catch { return }
  try {
    await classroomApi.archive(row.id)
    ElMessage.success('已归档')
    load()
  } catch { /* 拦截器已提示 */ }
}

async function openMembers(row) {
  current.value = row
  membersVisible.value = true
  await loadMembers()
}

async function loadMembers() {
  memberLoading.value = true
  try {
    const data = await classroomApi.members(current.value.id)
    members.value = data.items || []
  } catch { /* 拦截器已提示 */ } finally {
    memberLoading.value = false
  }
}

async function invite() {
  const keyword = inviteKeyword.value.trim()
  if (!keyword) return ElMessage.warning('请输入学生邮箱或 ID')
  inviting.value = true
  try {
    const payload = /^\d+$/.test(keyword)
      ? { studentId: Number(keyword) }
      : { email: keyword }
    await classroomApi.invite(current.value.id, payload)
    ElMessage.success('已邀请加入班级')
    inviteKeyword.value = ''
    await Promise.all([loadMembers(), load()])
  } catch { /* 拦截器已提示 */ } finally {
    inviting.value = false
  }
}

async function removeMember(row) {
  try {
    await ElMessageBox.confirm(`确认将「${row.name}」移出班级？`, '提示', { type: 'warning' })
  } catch { return }
  try {
    await classroomApi.removeMember(current.value.id, row.student_id)
    ElMessage.success('已移出')
    await Promise.all([loadMembers(), load()])
  } catch { /* 拦截器已提示 */ }
}
</script>

<style scoped>
.tip { border-radius: var(--r-sm); }
.dim { color: var(--text-placeholder); font-size: var(--fs-xs); }
.unit { margin-left: var(--sp-2); color: var(--text-secondary); font-size: var(--fs-sm); }
.invite-row {
  display: flex;
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
}
.assign-hint {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  margin-top: var(--sp-2);
}
.panel :deep(.el-table__inner-wrapper::before) { display: none; }
</style>
