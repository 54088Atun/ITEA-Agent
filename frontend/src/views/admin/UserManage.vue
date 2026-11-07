<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">用户管理</h2>
        <p class="page-sub">账号、角色与状态维护；批量启用/禁用仅影响登录权限，不删除数据</p>
      </div>
      <div class="page-head__actions">
        <el-button v-if="userStore.canAdminWrite" type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon> 新建账号
        </el-button>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <DebouncedInput v-model="filters.keyword" placeholder="姓名 / 邮箱" clearable style="width: 200px" @keyup.enter="reload" @debounce="reload" />
      <el-select v-model="filters.role" placeholder="全部角色" clearable style="width: 140px">
        <el-option label="教师" value="teacher" />
        <el-option label="学生" value="student" />
        <el-option label="管理员" value="admin" />
      </el-select>
      <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 140px">
        <el-option label="正常" value="active" />
        <el-option label="已禁用" value="disabled" />
      </el-select>
      <el-button type="primary" @click="reload">
        <el-icon><Search /></el-icon> 查询
      </el-button>
      <div class="filter-bar__spacer"></div>
      <span class="filter-bar__count">共 {{ total }} 个账号</span>
    </div>

    <!-- 批量操作条：选中后才出现，避免常驻占位 -->
    <transition name="fade">
      <div v-if="selectedIds.length" class="batch-bar">
        <span class="batch-bar__text">已选 {{ selectedIds.length }} 项</span>
        <el-button size="small" @click="clearSelection">取消选择</el-button>
        <el-button size="small" type="success" plain @click="batchStatus('active')">批量启用</el-button>
        <el-button size="small" type="danger" plain @click="batchStatus('disabled')">批量禁用</el-button>
      </div>
    </transition>

    <div class="panel">
      <SkeletonTable v-if="loading && !items.length" :rows="8" :cols="6" />
      <StateBlock v-else-if="error" state="error" @retry="load" />
      <el-table
        v-else
        ref="tableRef"
        :data="items"
        v-loading="loading"
        row-key="id"
        stripe
        @selection-change="onSelectionChange"
      >
        <el-table-column v-if="userStore.canAdminWrite" type="selection" width="46" />
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="name" label="姓名" width="140" />
        <el-table-column prop="email" label="邮箱" min-width="200" />
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag :type="roleTag(row.role)" size="small" effect="light">{{ roleLabel(row.role) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="管理员级别" width="120">
          <template #default="{ row }">
            <el-tag
              v-if="row.role === 'admin'"
              :type="levelTag(row.admin_level)"
              size="small"
              effect="light"
            >
              {{ levelLabel(row.admin_level) }}
            </el-tag>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'danger'" size="small" effect="light">
              {{ row.status === 'active' ? '正常' : '已禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <template v-if="userStore.canAdminWrite && (userStore.isSuperAdmin || row.role !== 'admin')">
              <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
              <el-button link type="warning" @click="openReset(row)">重置密码</el-button>
            </template>
            <el-button
              v-if="userStore.isSuperAdmin && row.role === 'admin'"
              link
              type="primary"
              @click="openLevel(row)"
            >
              级别
            </el-button>
            <el-button
              v-if="userStore.canAdminWrite && (userStore.isSuperAdmin || row.role !== 'admin')"
              link
              :type="row.status === 'active' ? 'danger' : 'success'"
              @click="toggleStatus(row)"
            >
              {{ row.status === 'active' ? '禁用' : '启用' }}
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <StateBlock
            state="empty"
            title="没有符合条件的账号"
            hint="调整角色、状态或关键词后重试"
          />
        </template>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @current-change="load"
          @size-change="reload"
        />
      </div>
    </div>

    <!-- 新建 -->
    <el-dialog v-model="createVisible" title="新建账号" width="460px">
      <el-form ref="createRef" :model="createForm" :rules="rules" label-width="80px">
        <el-form-item label="角色" prop="role">
          <el-select v-model="createForm.role" style="width: 100%">
            <el-option label="教师" value="teacher" />
            <el-option label="学生" value="student" />
            <el-option v-if="userStore.isSuperAdmin" label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="createForm.role === 'admin'" label="管理员级别">
          <el-select v-model="createForm.admin_level" style="width: 100%">
            <el-option label="超级管理员" value="super" />
            <el-option label="普通管理员" value="normal" />
            <el-option label="观察者" value="observer" />
          </el-select>
        </el-form-item>
        <el-form-item label="姓名" prop="name">
          <el-input v-model="createForm.name" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="createForm.email" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="createForm.password" type="password" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="createUser">创建</el-button>
      </template>
    </el-dialog>

    <!-- 编辑 -->
    <el-dialog v-model="editVisible" title="编辑用户" width="460px">
      <el-form :model="editForm" label-width="80px">
        <el-form-item label="角色">
          <el-select v-model="editForm.role" style="width: 100%">
            <el-option label="教师" value="teacher" />
            <el-option label="学生" value="student" />
            <el-option v-if="userStore.isSuperAdmin" label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="editForm.name" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="editForm.email" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="updateUser">保存</el-button>
      </template>
    </el-dialog>

    <!-- 重置密码 -->
    <el-dialog v-model="resetVisible" title="重置密码" width="420px">
      <el-form label-width="90px">
        <el-form-item label="用户">
          <span>{{ resetTarget?.name }} ({{ resetTarget?.email }})</span>
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="newPassword" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="resetPassword">确认重置</el-button>
      </template>
    </el-dialog>
    <!-- 设置管理员级别 -->
    <el-dialog v-model="levelVisible" title="设置管理员级别" width="440px">
      <el-form label-width="96px">
        <el-form-item label="管理员">
          <span>{{ levelTarget?.name }} ({{ levelTarget?.email }})</span>
        </el-form-item>
        <el-form-item label="级别">
          <el-radio-group v-model="levelForm.admin_level">
            <el-radio value="super">超级管理员</el-radio>
            <el-radio value="normal">普通管理员</el-radio>
            <el-radio value="observer">观察者</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <p class="level-hint">超级管理员拥有全部权限；普通管理员负责日常管理但不能管理管理员账号；观察者仅可查看。</p>
      <template #footer>
        <el-button @click="levelVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveLevel">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi } from '../../api/admin'
import { useUserStore } from '../../stores/user'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'
import DebouncedInput from '../../components/DebouncedInput.vue'

const userStore = useUserStore()

const loading = ref(false)
const error = ref(false)
const saving = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)

const filters = reactive({ keyword: '', role: '', status: '' })

const tableRef = ref()
const selectedIds = ref([])

const createVisible = ref(false)
const createRef = ref()
const createForm = reactive({ role: 'student', admin_level: 'normal', name: '', email: '', password: '' })
const rules = {
  role: [{ required: true, message: '请选择角色', trigger: 'change' }],
  name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }],
  password: [{ required: true, min: 6, message: '密码至少 6 位', trigger: 'blur' }],
}

const editVisible = ref(false)
const editForm = reactive({ id: null, role: '', name: '', email: '' })

const resetVisible = ref(false)
const resetTarget = ref(null)
const newPassword = ref('')

const levelVisible = ref(false)
const levelTarget = ref(null)
const levelForm = reactive({ admin_level: 'normal' })

onMounted(load)

async function load() {
  loading.value = true
  error.value = false
  try {
    const data = await adminApi.users({
      page: page.value,
      size: size.value,
      role: filters.role || undefined,
      keyword: filters.keyword || undefined,
      status: filters.status || undefined,
    })
    items.value = data.items || []
    total.value = data.total || 0
  } catch {
    // 保留页面内可重试错误态,不只依赖全局提示
    error.value = true
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

function onSelectionChange(rows) {
  selectedIds.value = rows.map((r) => r.id)
}

function clearSelection() {
  tableRef.value?.clearSelection()
  selectedIds.value = []
}

function roleLabel(r) {
  return { teacher: '教师', student: '学生', admin: '管理员' }[r] || r
}
function roleTag(r) {
  return { teacher: 'warning', student: '', admin: 'danger' }[r] || 'info'
}
// 空级别视为超管(与后端兼容口径一致)
function levelLabel(l) {
  return { super: '超级管理员', normal: '普通管理员', observer: '观察者' }[l || 'super'] || l
}
function levelTag(l) {
  return { super: 'danger', normal: 'warning', observer: 'info' }[l || 'super'] || 'info'
}
function formatTime(t) {
  if (!t) return '—'
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}

function openCreate() {
  Object.assign(createForm, { role: 'student', admin_level: 'normal', name: '', email: '', password: '' })
  createVisible.value = true
}

async function createUser() {
  const valid = await createRef.value.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    const payload = { ...createForm }
    if (payload.role !== 'admin') delete payload.admin_level
    await adminApi.createUser(payload)
    ElMessage.success('账号已创建')
    createVisible.value = false
    reload()
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

function openEdit(row) {
  Object.assign(editForm, { id: row.id, role: row.role, name: row.name, email: row.email })
  editVisible.value = true
}

async function updateUser() {
  saving.value = true
  try {
    await adminApi.updateUser(editForm.id, {
      role: editForm.role,
      name: editForm.name,
      email: editForm.email,
    })
    ElMessage.success('已保存')
    editVisible.value = false
    load()
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

async function toggleStatus(row) {
  const target = row.status === 'active' ? 'disabled' : 'active'
  try {
    await ElMessageBox.confirm(
      `确认${target === 'disabled' ? '禁用' : '启用'}账号「${row.name}」?`,
      '提示',
      { type: 'warning' }
    )
  } catch { return }
  try {
    await adminApi.setUserStatus(row.id, target)
    ElMessage.success('状态已更新')
    load()
  } catch { /* 拦截器已提示 */ }
}

/** 批量启停：逐条调用现有单条接口，统计成功数 */
async function batchStatus(target) {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  const label = target === 'active' ? '启用' : '禁用'
  try {
    await ElMessageBox.confirm(`确认${label}选中的 ${ids.length} 个账号?`, '批量操作', { type: 'warning' })
  } catch { return }

  let ok = 0
  for (const id of ids) {
    try {
      await adminApi.setUserStatus(id, target)
      ok++
    } catch { /* 单条失败不中断 */ }
  }
  if (ok === ids.length) {
    ElMessage.success(`已${label} ${ok} 个账号`)
  } else {
    ElMessage.warning(`${label}成功 ${ok} 个，失败 ${ids.length - ok} 个`)
  }
  clearSelection()
  load()
}

function openReset(row) {
  resetTarget.value = row
  newPassword.value = ''
  resetVisible.value = true
}

async function resetPassword() {
  if (!newPassword.value || newPassword.value.length < 6) {
    return ElMessage.warning('新密码至少 6 位')
  }
  saving.value = true
  try {
    await adminApi.resetPassword(resetTarget.value.id, newPassword.value)
    ElMessage.success('密码已重置')
    resetVisible.value = false
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

function openLevel(row) {
  levelTarget.value = row
  levelForm.admin_level = row.admin_level || 'super'
  levelVisible.value = true
}

async function saveLevel() {
  saving.value = true
  try {
    await adminApi.setAdminLevel(levelTarget.value.id, levelForm.admin_level)
    ElMessage.success('管理员级别已更新')
    levelVisible.value = false
    load()
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.filter-bar__count {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}

.dim { color: var(--text-placeholder); font-size: var(--fs-xs); }
.level-hint {
  margin: 0 0 var(--sp-2);
  font-size: var(--fs-xs);
  line-height: 1.6;
  color: var(--text-secondary);
}

.batch-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-4);
  background: var(--color-primary-wash);
  border: 1px solid var(--brand-100);
  border-radius: var(--r-md);
}
.batch-bar__text {
  font-size: var(--fs-sm);
  color: var(--color-primary);
  font-weight: 600;
  margin-right: var(--sp-2);
}

.panel :deep(.el-table__inner-wrapper::before) { display: none; }
.panel :deep(.el-table) { border-radius: var(--r-md); }

.pager {
  display: flex;
  justify-content: flex-end;
  padding: var(--sp-3) var(--sp-5);
  border-top: 1px solid var(--border);
}
</style>
