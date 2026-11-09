<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <el-button link class="back-link" @click="router.push('/teacher/classes')">
          <el-icon><ArrowLeft /></el-icon> 返回班级列表
        </el-button>
        <h2 class="page-title">{{ classroom?.name || '班级详情' }}</h2>
        <p class="page-sub">
          {{ classroom?.course_name || '未绑定课程' }} · {{ classroom?.semester || '未设置学期' }}
        </p>
      </div>
      <div v-if="classroom" class="page-head__actions">
        <el-tag :type="classroom.status === 'active' ? 'success' : 'info'" size="small" effect="light">
          {{ classroom.status === 'active' ? '进行中' : '已归档' }}
        </el-tag>
        <el-button @click="copyCode">复制课程码 {{ classroom.invite_code }}</el-button>
      </div>
    </div>

    <div v-if="loading && !classroom" class="panel">
      <SkeletonTable :rows="5" :cols="4" />
    </div>
    <StateBlock v-else-if="error && !classroom" state="error" title="班级详情加载失败" @retry="load" />
    <template v-else>
      <div class="kpi-grid">
        <div class="kpi-card">
          <span>学生人数</span>
          <strong>{{ classroom.member_count }} / {{ classroom.max_students }}</strong>
        </div>
        <div class="kpi-card">
          <span>平均学习进度</span>
          <strong>{{ report?.avg_progress ?? 0 }}%</strong>
        </div>
        <div class="kpi-card">
          <span>待确认作业</span>
          <strong>{{ pendingAssignments }}</strong>
        </div>
        <div class="kpi-card">
          <span>待批改考试</span>
          <strong>{{ pendingExams }}</strong>
        </div>
      </div>

      <el-tabs v-model="tab">
        <el-tab-pane label="班级概况" name="info">
          <div class="tab-body">
            <div class="panel">
              <div class="panel__head">
                <span class="panel__title">基本信息</span>
              </div>
              <el-descriptions :column="descColumns" border size="small">
                <el-descriptions-item label="班级名称">{{ classroom.name }}</el-descriptions-item>
                <el-descriptions-item label="班主任">{{ classroom.teacher_name || '—' }}</el-descriptions-item>
                <el-descriptions-item label="绑定课程">{{ classroom.course_name || '未绑定' }}</el-descriptions-item>
                <el-descriptions-item label="学期">{{ classroom.semester || '—' }}</el-descriptions-item>
                <el-descriptions-item label="课程码">{{ classroom.invite_code }}</el-descriptions-item>
                <el-descriptions-item label="创建时间">{{ formatTime(classroom.created_at) }}</el-descriptions-item>
                <el-descriptions-item label="班级说明" :span="2">
                  {{ classroom.description || '暂无说明' }}
                </el-descriptions-item>
              </el-descriptions>
            </div>

            <div class="panel">
              <div class="panel__head">
                <span class="panel__title">班级公告</span>
              </div>
              <div v-if="announcements.length" class="ann-list">
                <article v-for="a in announcements" :key="a.id" class="ann-item">
                  <div class="ann-item__head">
                    <strong>{{ a.author_name }}</strong>
                    <span>{{ formatTime(a.created_at) }}</span>
                  </div>
                  <p>{{ a.content }}</p>
                </article>
              </div>
              <StateBlock v-else state="empty" title="暂无公告" />
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane :label="`成员（${members.length}）`" name="members">
          <div class="filter-bar">
            <el-input
              v-model="memberKeyword"
              clearable
              placeholder="搜索姓名 / 邮箱 / ID"
              style="max-width: 260px"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <template v-if="isHead">
              <el-button type="primary" @click="openInvite">
                <el-icon><Plus /></el-icon> 新增成员
              </el-button>
              <el-button :loading="importing" @click="triggerImport">批量导入</el-button>
              <input
                ref="importInput"
                type="file"
                accept=".csv,.xlsx"
                hidden
                @change="onImportFile"
              />
            </template>
            <div class="filter-bar__spacer"></div>
            <span class="filter-bar__count">{{ filteredMembers.length }} / {{ members.length }} 人</span>
          </div>

          <div class="panel">
            <el-table :data="filteredMembers" v-loading="membersLoading">
              <el-table-column prop="name" label="姓名" min-width="110">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openMember(row)">{{ row.name }}</el-button>
                </template>
              </el-table-column>
              <el-table-column prop="email" label="邮箱" min-width="180" show-overflow-tooltip />
              <el-table-column label="角色" width="110">
                <template #default="{ row }">
                  <el-tag size="small" effect="light" :type="row.member_type === 'teacher' ? 'warning' : 'info'">
                    {{ roleLabel(row.role) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="头衔" min-width="120">
                <template #default="{ row }">{{ row.title || '—' }}</template>
              </el-table-column>
              <el-table-column label="学习进度" width="110">
                <template #default="{ row }">{{ progressOf(row) }}%</template>
              </el-table-column>
              <el-table-column label="薄弱知识点" width="110">
                <template #default="{ row }">{{ weakOf(row) }}</template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small" effect="light">
                    {{ row.status === 'active' ? '在班' : '已退出' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" :width="actionWidth">
                <template #default="{ row }">
                  <el-button link type="primary" @click="openMember(row)">详情</el-button>
                  <template v-if="isHead">
                    <el-button link type="primary" @click="openRole(row)">编辑</el-button>
                    <el-button link type="danger" @click="removeMember(row)">移出</el-button>
                  </template>
                  <el-button
                    v-else-if="isTeacher && row.member_type === 'student'"
                    link type="primary"
                    @click="setRepresentative(row)"
                  >设为课代表</el-button>
                </template>
              </el-table-column>
              <template #empty>
                <StateBlock state="empty" title="没有匹配的成员" hint="可调整搜索关键词，或复制课程码邀请学生加入" />
              </template>
            </el-table>
          </div>
        </el-tab-pane>

        <el-tab-pane label="学情与任务" name="stats">
          <div class="tab-body">
            <div class="panel">
              <div class="panel__head">
                <span class="panel__title">薄弱知识点</span>
              </div>
              <el-table :data="report?.weak_points || []" size="small" empty-text="暂无掌握度数据">
                <el-table-column prop="kp_name" label="知识点" min-width="180" />
                <el-table-column prop="avg_mastery" label="平均掌握度" width="120" />
                <el-table-column prop="wrong_count" label="错题数" width="100" />
              </el-table>
            </div>

            <div class="panel">
              <div class="panel__head">
                <span class="panel__title">作业统计</span>
              </div>
              <el-table :data="report?.assignments || []" size="small" empty-text="本班暂无作业">
                <el-table-column label="作业" min-width="180">
                  <template #default="{ row }">
                    <el-button link type="primary" @click="openAssignment(row)">{{ row.title }}</el-button>
                  </template>
                </el-table-column>
                <el-table-column prop="submitted" label="提交" width="80" />
                <el-table-column prop="confirmed" label="已确认" width="90" />
                <el-table-column prop="pending" label="待批改" width="90" />
                <el-table-column label="平均分" width="90">
                  <template #default="{ row }">{{ row.avg_score ?? '—' }}</template>
                </el-table-column>
              </el-table>
            </div>

            <div class="panel">
              <div class="panel__head">
                <span class="panel__title">考试统计</span>
              </div>
              <el-table :data="report?.exams || []" size="small" empty-text="本班暂无考试">
                <el-table-column label="试卷" min-width="180">
                  <template #default="{ row }">
                    <el-button link type="primary" @click="openExam(row)">{{ row.title }}</el-button>
                  </template>
                </el-table-column>
                <el-table-column prop="submitted" label="提交" width="80" />
                <el-table-column prop="pending_manual" label="待批改" width="90" />
                <el-table-column label="平均分" width="90">
                  <template #default="{ row }">{{ row.avg_score ?? '—' }}</template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </template>

    <el-dialog v-model="inviteVisible" title="新增成员" width="min(480px, 92vw)">
      <el-form label-width="88px">
        <el-form-item label="邮箱 / ID">
          <el-input v-model="inviteForm.keyword" placeholder="注册邮箱或用户 ID" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="inviteForm.role" style="width: 100%">
            <el-option
              v-for="item in inviteRoleOptions"
              :key="item.value" :label="item.label" :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="头衔">
          <el-input v-model="inviteForm.title" placeholder="如：班长 / 课代表（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="inviteVisible = false">取消</el-button>
        <el-button type="primary" :loading="inviting" @click="submitInvite">添加</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="roleVisible" title="修改成员角色" width="min(480px, 92vw)">
      <el-form label-width="88px">
        <el-form-item label="成员">{{ roleForm.name }}</el-form-item>
        <el-form-item label="角色">
          <el-select v-model="roleForm.role" style="width: 100%">
            <el-option
              v-for="item in assignableRoles"
              :key="item.value" :label="item.label" :value="item.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="头衔">
          <el-input v-model="roleForm.title" placeholder="如：班长 / 课代表" />
        </el-form-item>
        <el-form-item v-if="roleForm.role === 'custom'" label="权限">
          <el-checkbox-group v-model="roleForm.permissions" class="perm-group">
            <el-checkbox v-for="p in permissionOptions" :key="p.key" :label="p.key">
              {{ p.label }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="roleVisible = false">取消</el-button>
        <el-button type="primary" :loading="roleSaving" @click="saveRole">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { classroomApi } from '../../api/classroom'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'

const route = useRoute()
const router = useRouter()
const classId = Number(route.params.id)
const descColumns = window.matchMedia('(max-width: 767px)').matches ? 1 : 2

const loading = ref(true)
const error = ref(false)
const tab = ref('info')
const classroom = ref(null)
const members = ref([])
const membersLoading = ref(false)
const report = ref(null)
const announcements = ref([])

// 成员管理
const memberKeyword = ref('')
const inviteVisible = ref(false)
const inviting = ref(false)
const inviteForm = reactive({ keyword: '', role: 'student', title: '' })
const roleVisible = ref(false)
const roleSaving = ref(false)
const roleForm = reactive({
  studentId: null,
  name: '',
  memberType: 'student',
  role: 'student',
  title: '',
  permissions: [],
})
const permissionOptions = ref([])
const importInput = ref()
const importing = ref(false)

const INVITE_ROLE_OPTIONS = [
  { value: 'student', label: '普通学生' },
  { value: 'monitor', label: '班长' },
  { value: 'representative', label: '课代表' },
  { value: 'custom', label: '自定义' },
  { value: 'teacher', label: '任课教师' },
]

const ROLE_LABELS = {
  head_teacher: '班主任',
  teacher: '任课教师',
  monitor: '班长',
  representative: '课代表',
  student: '普通学生',
  custom: '自定义',
}

const progressMap = computed(() => {
  const map = {}
  for (const row of report.value?.students || []) map[row.user_id] = row
  return map
})

const pendingAssignments = computed(() =>
  (report.value?.assignments || []).reduce((sum, row) => sum + (row.pending || 0), 0),
)
const pendingExams = computed(() =>
  (report.value?.exams || []).reduce((sum, row) => sum + (row.pending_manual || 0), 0),
)

const isHead = computed(() =>
  ['head_teacher', 'admin'].includes(classroom.value?.my_role),
)
const isTeacher = computed(() => classroom.value?.my_role === 'teacher')

const filteredMembers = computed(() => {
  const text = memberKeyword.value.trim().toLowerCase()
  if (!text) return members.value
  return members.value.filter((row) =>
    String(row.name || '').toLowerCase().includes(text)
    || String(row.email || '').toLowerCase().includes(text)
    || String(row.student_id).includes(text),
  )
})

const actionWidth = computed(() => (isHead.value || isTeacher.value ? 200 : 80))

const inviteRoleOptions = computed(() =>
  INVITE_ROLE_OPTIONS.filter((item) => isHead.value || item.value !== 'teacher'),
)

const assignableRoles = computed(() => {
  if (roleForm.memberType === 'teacher') {
    return [{ value: 'teacher', label: '任课教师' }]
  }
  return [
    { value: 'student', label: '普通学生' },
    { value: 'monitor', label: '班长' },
    { value: 'representative', label: '课代表' },
    { value: 'custom', label: '自定义' },
  ]
})

onMounted(() => {
  load()
  loadPermissions()
})

async function load() {
  error.value = false
  loading.value = true
  try {
    classroom.value = await classroomApi.detail(classId)
  } catch {
    error.value = true
    loading.value = false
    return
  }
  loading.value = false
  loadAux()
}

async function loadAux() {
  membersLoading.value = true
  const [memberRes, reportRes, annRes] = await Promise.allSettled([
    classroomApi.members(classId),
    classroomApi.report(classId),
    classroomApi.announcements(classId),
  ])
  if (memberRes.status === 'fulfilled') members.value = memberRes.value.items || []
  if (reportRes.status === 'fulfilled') report.value = reportRes.value
  if (annRes.status === 'fulfilled') announcements.value = Array.isArray(annRes.value) ? annRes.value : []
  membersLoading.value = false
}

function roleLabel(role) {
  return ROLE_LABELS[role] || role || '—'
}

function progressOf(row) {
  return progressMap.value[row.student_id]?.overall_progress ?? 0
}

function weakOf(row) {
  const value = progressMap.value[row.student_id]?.weak_count
  return value === undefined ? '—' : value
}

function formatTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

async function copyCode() {
  const code = classroom.value?.invite_code
  if (!code) return
  try {
    await navigator.clipboard.writeText(code)
    ElMessage.success(`课程码 ${code} 已复制`)
  } catch {
    ElMessage.info(`课程码：${code}`)
  }
}

async function loadPermissions() {
  try {
    const data = await classroomApi.permissions()
    permissionOptions.value = data.permissions || []
  } catch { /* 拦截器已提示 */ }
}

function openInvite() {
  Object.assign(inviteForm, { keyword: '', role: 'student', title: '' })
  inviteVisible.value = true
}

async function submitInvite() {
  const keyword = inviteForm.keyword.trim()
  if (!keyword) return ElMessage.warning('请输入邮箱或用户 ID')
  inviting.value = true
  try {
    const payload = {
      ...(/^\d+$/.test(keyword) ? { studentId: Number(keyword) } : { email: keyword }),
      role: inviteForm.role,
      title: inviteForm.title.trim() || undefined,
    }
    await classroomApi.invite(classId, payload)
    ElMessage.success('成员已加入班级')
    inviteVisible.value = false
    await load()
  } catch { /* 拦截器已提示 */ } finally {
    inviting.value = false
  }
}

function triggerImport() {
  importInput.value?.click()
}

async function onImportFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  importing.value = true
  try {
    const res = await classroomApi.importMembers(classId, file)
    ElMessage.success(`导入完成：成功 ${res.imported}，跳过 ${res.skipped}，失败 ${res.failed}`)
    const firstFail = (res.items || []).find((item) => item.status === 'failed')
    if (firstFail) ElMessage.warning(`第 ${firstFail.row} 行：${firstFail.message}`)
    await load()
  } catch { /* 拦截器已提示 */ } finally {
    importing.value = false
    event.target.value = ''
  }
}

function openRole(row) {
  Object.assign(roleForm, {
    studentId: row.student_id,
    name: row.name,
    memberType: row.member_type,
    role: row.role,
    title: row.title || '',
    permissions: [...(row.permissions || [])],
  })
  roleVisible.value = true
}

async function saveRole() {
  roleSaving.value = true
  try {
    await classroomApi.assignRole(classId, roleForm.studentId, {
      role: roleForm.role,
      title: roleForm.title.trim() || undefined,
      permissions: roleForm.role === 'custom' ? roleForm.permissions : undefined,
    })
    ElMessage.success('成员角色已更新')
    roleVisible.value = false
    await loadAux()
  } catch { /* 拦截器已提示 */ } finally {
    roleSaving.value = false
  }
}

async function removeMember(row) {
  try {
    await ElMessageBox.confirm(`确认将「${row.name}」移出班级？`, '移出成员', { type: 'warning' })
  } catch { return }
  try {
    await classroomApi.removeMember(classId, row.student_id)
    ElMessage.success('已移出班级')
    await load()
  } catch { /* 拦截器已提示 */ }
}

async function setRepresentative(row) {
  const title = classroom.value?.course_name
    ? `${classroom.value.course_name}课代表`
    : '课代表'
  try {
    await classroomApi.assignRole(classId, row.student_id, {
      role: 'representative',
      title,
    })
    ElMessage.success(`已将「${row.name}」设为${title}`)
    await loadAux()
  } catch { /* 拦截器已提示 */ }
}

function openMember(row) {
  router.push(`/teacher/classes/${classId}/members/${row.student_id}`)
}

function openAssignment(row) {
  router.push(`/teacher/assignments/${row.assignment_id}`)
}

function openExam(row) {
  router.push(`/teacher/exams/${row.exam_id}`)
}
</script>

<style scoped>
.back-link { padding: 0; margin-bottom: var(--sp-1); color: var(--text-secondary); }
.tab-body { display: flex; flex-direction: column; gap: var(--sp-4); }
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
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
.ann-list { display: flex; flex-direction: column; gap: var(--sp-3); }
.ann-item {
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  padding: var(--sp-3);
  background: var(--bg-elevated);
}
.ann-item__head {
  display: flex;
  justify-content: space-between;
  gap: var(--sp-2);
  margin-bottom: var(--sp-1);
  font-size: var(--fs-xs);
  color: var(--text-secondary);
}
.ann-item p { margin: 0; white-space: pre-wrap; line-height: 1.7; color: var(--text-primary); }
.perm-group { display: flex; flex-wrap: wrap; gap: var(--sp-1) var(--sp-3); }
</style>
