<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">班级管理</h2>
        <p class="page-sub">课程码学生用可加入班级，教师用可复制该班绑定课程</p>
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

    <div v-if="loading && !items.length" class="class-grid">
      <SkeletonCard v-for="n in 4" :key="n" :rows="3" />
    </div>
    <StateBlock v-else-if="error" state="error" @retry="load" />
    <div v-else-if="items.length" class="class-grid">
      <article v-for="row in items" :key="row.id" class="class-card">
        <header class="class-card__head">
          <span class="class-card__seal"><el-icon><Notebook /></el-icon></span>
          <div class="class-card__title-wrap">
            <h3 class="class-card__title">{{ row.name }}</h3>
            <span class="class-card__sub">
              {{ row.course_name || '未绑定课程' }} · {{ row.semester || '未设置学期' }}
            </span>
          </div>
          <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small" effect="light">
            {{ row.status === 'active' ? '进行中' : '已归档' }}
          </el-tag>
        </header>

        <div class="class-card__meta">
          <span class="class-card__stat">学生 {{ row.member_count }} / {{ row.max_students }}</span>
          <el-tag
            size="small" effect="plain"
            :type="row.my_role === 'head_teacher' ? 'success' : row.my_role === 'teacher' ? 'warning' : 'info'"
          >
            {{ roleLabel(row.my_role) }}
          </el-tag>
          <span class="class-card__code">
            课程码
            <el-button link type="primary" @click="copyCode(row.invite_code)">
              {{ row.invite_code }}
            </el-button>
          </span>
        </div>

        <footer class="class-card__actions">
          <el-button link type="primary" size="small" @click="openDetail(row)">详情</el-button>
          <el-button link type="primary" size="small" @click="openReport(row)">学情</el-button>
          <el-button link type="primary" size="small" @click="openAnnouncements(row)">公告</el-button>
          <el-button v-if="isHead(row)" link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="isHead(row)" link type="warning" size="small" @click="resetInvite(row)">重置课程码</el-button>
          <el-button
            v-if="isHead(row) && row.status === 'active'"
            link type="danger" size="small" @click="archive(row)"
          >归档</el-button>
        </footer>
      </article>
    </div>
    <div v-else class="panel">
      <StateBlock state="empty" title="还没有班级" hint="先新建一个班级并绑定课程" />
    </div>

    <div class="panel interview-panel">
      <div class="panel__head">
        <span class="panel__title">面试作业与授权记录</span>
      </div>
      <el-table :data="interviewAssignments" v-loading="interviewAssignmentsLoading" size="small">
        <el-table-column prop="title" label="作业标题" min-width="180" />
        <el-table-column label="面向范围" min-width="180">
          <template #default="{ row }">{{ assignmentScope(row) }}</template>
        </el-table-column>
        <el-table-column label="面试时长" width="100">
          <template #default="{ row }">{{ row.duration_minutes || 30 }} 分钟</template>
        </el-table-column>
        <el-table-column label="截止时间" min-width="160">
          <template #default="{ row }">{{ row.due_at ? formatTime(row.due_at) : '不限' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small" effect="light">
              {{ row.status === 'active' ? '进行中' : '已关闭' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" :fixed="isNarrow ? false : 'right'">
          <template #default="{ row }">
            <el-button link type="primary" @click="openInterviewRecords(row)">授权记录</el-button>
          </template>
        </el-table-column>
        <template #empty><div class="empty-state">暂无面试作业</div></template>
      </el-table>
    </div>

    <!-- 新建 / 编辑 -->
    <el-dialog v-model="formVisible" :title="form.id ? '编辑班级' : '新建班级'" width="520px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
        <el-form-item label="班级名称" prop="name">
          <el-input v-model="form.name" placeholder="如：2026 秋 软件测试 1 班" />
        </el-form-item>
        <el-form-item label="绑定课程">
          <el-select v-model="form.course_id" clearable filterable placeholder="可选择不绑定" style="width: 100%">
            <el-option v-for="c in courses" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="学期">
          <el-input v-model="form.semester" placeholder="如：2026秋" />
        </el-form-item>
        <el-form-item label="说明">
          <el-input v-model="form.description" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="班级容量">
          <el-input-number v-model="form.max_students" :min="1" :max="1000" />
          <span class="unit">人</span>
        </el-form-item>
        <template v-if="!form.id">
          <el-form-item label="课程码有效">
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
    <el-drawer v-model="membersVisible" :title="`成员 · ${current?.name || ''}`" size="560px">
      <div class="invite-row">
        <el-input v-model="inviteKeyword" placeholder="邮箱或 ID" />
        <el-select v-model="inviteRole" style="width: 120px">
          <el-option
            v-for="r in inviteRoleOptions"
            :key="r.value" :label="r.label" :value="r.value"
          />
        </el-select>
        <el-input v-model="inviteTitle" placeholder="头衔（可选）" style="width: 130px" />
        <el-button type="primary" :loading="inviting" @click="invite">邀请</el-button>
      </div>
      <div v-if="isHead(current)" class="invite-row">
        <el-button :loading="importing" @click="triggerImport">批量导入学生</el-button>
        <input
          ref="importInput"
          type="file"
          accept=".csv,.xlsx"
          hidden
          @change="onImportFile"
        />
      </div>
      <div v-if="current?.my_role === 'teacher'" class="invite-row">
        <el-input v-model="myTitle" placeholder="我的头衔，如：数据结构教师" />
        <el-button @click="saveMyTitle">保存头衔</el-button>
      </div>
      <el-table :data="members" v-loading="memberLoading" size="small">
        <el-table-column prop="student_id" label="ID" width="60" />
        <el-table-column prop="name" label="姓名" width="100" />
        <el-table-column label="角色" width="100">
          <template #default="{ row }">
            <el-tag size="small" effect="light" :type="row.member_type === 'teacher' ? 'warning' : 'info'">
              {{ roleLabel(row.role) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="头衔" min-width="110">
          <template #default="{ row }">{{ row.title || '—' }}</template>
        </el-table-column>
        <el-table-column prop="email" label="邮箱" min-width="160" />
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small" effect="light">
              {{ row.status === 'active' ? '在班' : '已退出' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'active' && canAssign(row)"
              link type="primary" @click="openRole(row)"
            >
              设角色
            </el-button>
            <el-button
              v-if="row.status === 'active' && isHead(current)"
              link type="warning" @click="openTransfer(row)"
            >
              转班
            </el-button>
            <el-button
              v-if="row.status === 'active' && isHead(current)"
              link type="danger" @click="removeMember(row)"
            >
              移出
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty-state">暂无成员，可复制课程码发给学生，或直接邀请教师</div>
        </template>
      </el-table>
    </el-drawer>

    <!-- 设置班级角色 -->
    <el-dialog v-model="roleVisible" title="设置班级角色" width="480px">
      <el-form label-width="80px">
        <el-form-item label="成员">{{ roleForm.name }}</el-form-item>
        <el-form-item label="角色">
          <el-select v-model="roleForm.role" style="width: 100%">
            <el-option
              v-for="r in assignableRoles"
              :key="r.value" :label="r.label" :value="r.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="头衔">
          <el-input v-model="roleForm.title" placeholder="如：班长 / 课代表 / 学习委员" />
        </el-form-item>
        <el-form-item v-if="roleForm.role === 'custom'" label="权限">
          <el-checkbox-group v-model="roleForm.permissions" class="perm-group">
            <el-checkbox
              v-for="p in permissionOptions" :key="p.key" :label="p.key"
            >
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

    <!-- 学生转班 -->
    <el-dialog v-model="transferVisible" title="学生转班" width="440px">
      <el-form label-width="80px">
        <el-form-item label="学生">{{ transferForm.name }}</el-form-item>
        <el-form-item label="目标班级">
          <el-select v-model="transferForm.target_class_id" placeholder="选择目标班级" style="width: 100%">
            <el-option
              v-for="c in transferTargets"
              :key="c.id" :label="`${c.name}（${c.member_count}/${c.max_students}）`" :value="c.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <p class="assign-hint">转班后原班级课程可见性会收回，并自动获得目标班级课程权限。</p>
      <template #footer>
        <el-button @click="transferVisible = false">取消</el-button>
        <el-button type="primary" :loading="transferSaving" @click="saveTransfer">确认转班</el-button>
      </template>
    </el-dialog>

    <!-- 班级公告 -->
    <el-drawer
      v-model="announcementVisible"
      :title="`班级公告 · ${current?.name || ''}`"
      size="520px"
    >
      <div v-loading="announcementLoading" class="ann-list">
        <el-empty v-if="!announcements.length" description="暂无公告" />
        <article v-for="a in announcements" :key="a.id" class="ann-item">
          <div class="ann-item__head">
            <strong>{{ a.author_name }}</strong>
            <span>{{ formatTime(a.created_at) }}</span>
          </div>
          <p>{{ a.content }}</p>
        </article>
      </div>
      <div v-if="isHead(current)" class="ann-composer">
        <el-input
          v-model="announcementText"
          type="textarea"
          :rows="3"
          maxlength="2000"
          show-word-limit
          placeholder="发布班级公告，学生与任课教师都能看到"
        />
        <el-button
          type="primary"
          :loading="posting"
          :disabled="!announcementText.trim()"
          @click="postAnnouncement"
        >
          发布公告
        </el-button>
      </div>
      <p v-else class="assign-hint">仅班主任或拥有“发布公告”权限的角色可发布。</p>
    </el-drawer>

    <!-- 班级学情 -->
    <el-drawer v-model="reportVisible" :title="`班级学情 · ${report?.class_name || ''}`" size="780px">
      <div v-loading="reportLoading" class="report">
        <el-alert
          v-if="report && !report.course_id"
          type="info" :closable="false"
          title="未绑定课程：学情聚合该班成员的全部课程档案"
        />
        <div v-if="report" class="report-kpis">
          <div class="kpi"><span>学生数</span><strong>{{ report.student_count }}</strong></div>
          <div class="kpi"><span>平均进度</span><strong>{{ report.avg_progress }}%</strong></div>
          <div class="kpi"><span>绑定课程</span><strong>{{ report.course_name || '—' }}</strong></div>
        </div>

        <h4>薄弱知识点</h4>
        <el-table :data="report?.weak_points || []" size="small" empty-text="暂无掌握度数据">
          <el-table-column prop="kp_name" label="知识点" min-width="180" />
          <el-table-column prop="avg_mastery" label="平均掌握度" width="110" />
          <el-table-column prop="wrong_count" label="错题数" width="90" />
        </el-table>

        <h4>学生学情</h4>
        <el-table :data="report?.students || []" size="small" empty-text="暂无学生">
          <el-table-column prop="user_id" label="ID" width="70" />
          <el-table-column prop="name" label="姓名" min-width="120" />
          <el-table-column prop="overall_progress" label="进度" width="90">
            <template #default="{ row }">{{ row.overall_progress }}%</template>
          </el-table-column>
          <el-table-column prop="weak_count" label="薄弱知识点" width="110" />
        </el-table>

        <h4>作业统计</h4>
        <el-table :data="report?.assignments || []" size="small" empty-text="本班暂无作业">
          <el-table-column prop="title" label="作业" min-width="180" />
          <el-table-column prop="submitted" label="提交" width="80" />
          <el-table-column prop="confirmed" label="已确认" width="90" />
          <el-table-column prop="pending" label="待批改" width="90" />
          <el-table-column label="平均分" width="90">
            <template #default="{ row }">{{ row.avg_score ?? '—' }}</template>
          </el-table-column>
        </el-table>

        <h4>考试统计</h4>
        <el-table :data="report?.exams || []" size="small" empty-text="本班暂无考试">
          <el-table-column prop="title" label="试卷" min-width="180" />
          <el-table-column prop="submitted" label="提交" width="80" />
          <el-table-column prop="pending_manual" label="待批改" width="90" />
          <el-table-column label="平均分" width="90">
            <template #default="{ row }">{{ row.avg_score ?? '—' }}</template>
          </el-table-column>
        </el-table>
      </div>
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
          <el-select v-model="assignForm.course_id" clearable filterable placeholder="可选" style="width: 100%">
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
        <el-form-item label="面试时长">
          <el-input-number v-model="assignForm.duration_minutes" :min="1" :max="120" />
          <span class="unit">分钟</span>
        </el-form-item>
      </el-form>
      <p class="assign-hint">发布后，班级学生或已选该课程的学生会在「模拟面试」页看到该作业。</p>
      <template #footer>
        <el-button @click="assignVisible = false">取消</el-button>
        <el-button type="primary" :loading="assignSaving" @click="submitAssign">发布</el-button>
      </template>
    </el-dialog>

    <!-- 学生授权的面试记录：数据完全由教师只读接口返回 -->
    <el-drawer v-model="interviewRecordsVisible" title="学生授权面试记录" size="760px">
      <el-select
        v-model="recordAssignmentId"
        clearable
        placeholder="全部面试作业"
        class="record-filter"
        @change="loadInterviewRecords"
      >
        <el-option
          v-for="a in interviewAssignments"
          :key="a.id"
          :label="a.title"
          :value="a.id"
        />
      </el-select>
      <div v-loading="interviewRecordsLoading" class="interview-records">
        <el-empty
          v-if="!interviewRecords.length && !interviewRecordsLoading"
          description="暂无学生授权的面试记录"
        />
        <article v-for="r in interviewRecords" :key="r.id" class="interview-record">
          <div class="interview-record__head">
            <strong>{{ r.student_name }}</strong>
            <span>{{ r.course_name }} · {{ r.assignment_title || '自选面试' }} · 第 {{ r.round }} 轮</span>
            <time>{{ formatTime(r.created_at) }}</time>
          </div>
          <div class="interview-record__scores">
            <span>综合评分：{{ r.score ?? '未评分' }}</span>
            <span v-for="label in SCORE_LABELS" :key="label">
              {{ label }}：{{ dimensionScore(r, label) }}
            </span>
          </div>
          <div class="interview-record__section">
            <span>面试问题</span>
            <p>{{ r.question }}</p>
          </div>
          <div v-if="r.answer" class="interview-record__section">
            <span>学生回答</span>
            <p>{{ r.answer }}</p>
          </div>
          <div v-if="r.feedback" class="interview-record__section">
            <span>评价反馈</span>
            <p>{{ r.feedback }}</p>
          </div>
        </article>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { classroomApi } from '../../api/classroom'
import { courseApi } from '../../api/course'
import { teacherApi } from '../../api/teacher'
import { useUserStore } from '../../stores/user'
import SkeletonCard from '../../components/SkeletonCard.vue'
import StateBlock from '../../components/StateBlock.vue'

const userStore = useUserStore()
const router = useRouter()

const ROLE_LABELS = {
  head_teacher: '班主任',
  teacher: '任课教师',
  monitor: '班长',
  representative: '课代表',
  student: '普通学生',
  custom: '自定义',
}
const INVITE_ROLE_OPTIONS = [
  { value: 'student', label: '学生' },
  { value: 'teacher', label: '教师' },
  { value: 'monitor', label: '班长' },
  { value: 'representative', label: '课代表' },
  { value: 'custom', label: '自定义' },
]

const loading = ref(false)
const error = ref(false)
const saving = ref(false)
const items = ref([])
const courses = ref([])

// 窄屏取消操作列固定，让表格整体横向滚动
const isNarrow = ref(false)
const narrowQuery = window.matchMedia('(max-width: 900px)')
function syncNarrow(e) { isNarrow.value = e.matches }

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
  max_students: 100,
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
const inviteRole = ref('student')
const inviteTitle = ref('')
const myTitle = ref('')
const permissionOptions = ref([])

const roleVisible = ref(false)
const roleSaving = ref(false)
const roleForm = reactive({
  userId: null,
  name: '',
  memberType: 'student',
  role: 'student',
  title: '',
  permissions: [],
})

const inviteRoleOptions = computed(() => {
  if (current.value?.my_role === 'teacher') {
    return INVITE_ROLE_OPTIONS.filter(r => ['student', 'teacher', 'representative'].includes(r.value))
  }
  return INVITE_ROLE_OPTIONS
})

const assignableRoles = computed(() => {
  if (roleForm.memberType === 'teacher') {
    return [{ value: 'teacher', label: '任课教师' }]
  }
  if (current.value?.my_role === 'teacher') {
    return [{ value: 'representative', label: '课代表' }]
  }
  return [
    { value: 'student', label: '普通学生' },
    { value: 'monitor', label: '班长' },
    { value: 'representative', label: '课代表' },
    { value: 'custom', label: '自定义' },
  ]
})

// 班级学情
const reportVisible = ref(false)
const reportLoading = ref(false)
const report = ref(null)

// 班级公告
const announcementVisible = ref(false)
const announcementLoading = ref(false)
const announcements = ref([])
const announcementText = ref('')
const posting = ref(false)

// 批量导入 / 转班
const importInput = ref()
const importing = ref(false)
const transferVisible = ref(false)
const transferSaving = ref(false)
const transferForm = reactive({ studentId: null, name: '', target_class_id: null })

const transferTargets = computed(() =>
  items.value.filter(c => c.id !== current.value?.id && c.status === 'active'),
)

// 面试作业
const assignVisible = ref(false)
const assignSaving = ref(false)
const assignForm = reactive({
  title: '', class_id: null, course_id: null, description: '', due_days: 7,
  duration_minutes: 30,
})

const SCORE_LABELS = ['专业知识', '逻辑表达', '岗位匹配', '沟通应答']
const interviewAssignments = ref([])
const interviewAssignmentsLoading = ref(false)
const interviewRecordsVisible = ref(false)
const interviewRecordsLoading = ref(false)
const interviewRecords = ref([])
const recordAssignmentId = ref(null)

onMounted(async () => {
  isNarrow.value = narrowQuery.matches
  narrowQuery.addEventListener('change', syncNarrow)
  await Promise.all([load(), loadCourses(), loadPermissions(), loadInterviewAssignments()])
})

onBeforeUnmount(() => narrowQuery.removeEventListener('change', syncNarrow))

async function load() {
  loading.value = true
  error.value = false
  try {
    items.value = await classroomApi.list()
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

async function loadCourses() {
  try {
    const data = await courseApi.list()
    courses.value = Array.isArray(data) ? data : []
  } catch { /* 拦截器已提示 */ }
}

async function loadPermissions() {
  try {
    const data = await classroomApi.permissions()
    permissionOptions.value = data.permissions || []
  } catch { /* 拦截器已提示 */ }
}

function roleLabel(role) {
  return ROLE_LABELS[role] || role || '—'
}

function isHead(row) {
  return !!row && ['head_teacher', 'admin'].includes(row.my_role)
}

function canAssign(row) {
  if (!current.value || row.member_type === 'teacher') return false
  return isHead(current.value) || current.value.my_role === 'teacher'
}

function openAssign() {
  Object.assign(assignForm, {
    title: '',
    class_id: items.value[0]?.id || null,
    course_id: courses.value[0]?.id || null,
    description: '',
    due_days: 7,
    duration_minutes: 30,
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
      duration_minutes: assignForm.duration_minutes,
    })
    ElMessage.success('面试作业已发布')
    assignVisible.value = false
    await loadInterviewAssignments()
  } catch { /* 拦截器已提示 */ } finally {
    assignSaving.value = false
  }
}

async function loadInterviewAssignments() {
  interviewAssignmentsLoading.value = true
  try {
    interviewAssignments.value = await teacherApi.interviewAssignments()
  } catch { /* 拦截器已提示 */ } finally {
    interviewAssignmentsLoading.value = false
  }
}

function assignmentScope(assignment) {
  const className = items.value.find(c => c.id === assignment.class_id)?.name
  const courseName = courses.value.find(c => c.id === assignment.course_id)?.name
  return [className, courseName].filter(Boolean).join(' / ') || '—'
}

function openInterviewRecords(assignment) {
  recordAssignmentId.value = assignment.id
  interviewRecordsVisible.value = true
  loadInterviewRecords()
}

async function loadInterviewRecords() {
  interviewRecordsLoading.value = true
  try {
    const params = recordAssignmentId.value
      ? { assignment_id: recordAssignmentId.value }
      : {}
    interviewRecords.value = await teacherApi.interviewRecords(params)
  } catch { /* 拦截器已提示 */ } finally {
    interviewRecordsLoading.value = false
  }
}

function dimensionScore(record, label) {
  try {
    const dimensions = typeof record.score_dimensions === 'string'
      ? JSON.parse(record.score_dimensions)
      : (record.score_dimensions || {})
    return dimensions[label] ?? '未评分'
  } catch {
    return '未评分'
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
    max_students: 100,
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
    max_students: row.max_students || 100,
  })
  formVisible.value = true
}

async function save() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    if (form.id) {
      await classroomApi.update(form.id, {
        name: form.name,
        course_id: form.course_id,
        semester: form.semester,
        description: form.description,
        max_students: form.max_students,
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
        max_students: form.max_students,
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
    ElMessage.success(`课程码 ${code} 已复制`)
  } catch {
    ElMessage.info(`课程码：${code}`)
  }
}

async function resetInvite(row) {
  try {
    await ElMessageBox.confirm('重置后旧课程码立即失效，确认继续？', '提示', { type: 'warning' })
  } catch { return }
  try {
    const data = await classroomApi.resetInvite(row.id)
    ElMessage.success(`新课程码：${data.invite_code}`)
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

function openDetail(row) {
  router.push(`/teacher/classes/${row.id}`)
}

async function openReport(row) {
  reportVisible.value = true
  reportLoading.value = true
  report.value = null
  try {
    report.value = await classroomApi.report(row.id)
  } catch { /* 拦截器已提示 */ } finally {
    reportLoading.value = false
  }
}

async function openAnnouncements(row) {
  current.value = row
  announcementVisible.value = true
  announcementText.value = ''
  await loadAnnouncements()
}

async function loadAnnouncements() {
  announcementLoading.value = true
  try {
    announcements.value = await classroomApi.announcements(current.value.id)
  } catch { /* 拦截器已提示 */ } finally {
    announcementLoading.value = false
  }
}

async function postAnnouncement() {
  const content = announcementText.value.trim()
  if (!content) return ElMessage.warning('请输入公告内容')
  posting.value = true
  try {
    await classroomApi.createAnnouncement(current.value.id, content)
    ElMessage.success('公告已发布')
    announcementText.value = ''
    await loadAnnouncements()
  } catch { /* 拦截器已提示 */ } finally {
    posting.value = false
  }
}

function formatTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('zh-CN', { hour12: false })
}

async function loadMembers() {
  memberLoading.value = true
  try {
    const data = await classroomApi.members(current.value.id)
    members.value = data.items || []
    const me = members.value.find(m => m.student_id === userStore.user?.id)
    myTitle.value = me?.title || ''
  } catch { /* 拦截器已提示 */ } finally {
    memberLoading.value = false
  }
}

async function invite() {
  const keyword = inviteKeyword.value.trim()
  if (!keyword) return ElMessage.warning('请输入邮箱或 ID')
  if (inviteRole.value === 'custom' && current.value?.my_role === 'teacher') {
    return ElMessage.warning('任课教师只能授予课代表')
  }
  inviting.value = true
  try {
    const payload = {
      ...(/^\d+$/.test(keyword) ? { studentId: Number(keyword) } : { email: keyword }),
      role: inviteRole.value,
      title: inviteTitle.value.trim() || undefined,
    }
    await classroomApi.invite(current.value.id, payload)
    ElMessage.success('已邀请加入班级')
    inviteKeyword.value = ''
    inviteTitle.value = ''
    await Promise.all([loadMembers(), load()])
  } catch { /* 拦截器已提示 */ } finally {
    inviting.value = false
  }
}

function openRole(row) {
  Object.assign(roleForm, {
    userId: row.student_id,
    name: row.name,
    memberType: row.member_type,
    role: row.role,
    title: row.title || '',
    permissions: [...(row.permissions || [])],
  })
  if (current.value?.my_role === 'teacher') {
    roleForm.role = 'representative'
  }
  roleVisible.value = true
}

async function saveRole() {
  roleSaving.value = true
  try {
    await classroomApi.assignRole(current.value.id, roleForm.userId, {
      role: roleForm.role,
      title: roleForm.title.trim() || undefined,
      permissions: roleForm.role === 'custom' ? roleForm.permissions : undefined,
    })
    ElMessage.success('角色已更新')
    roleVisible.value = false
    await loadMembers()
  } catch { /* 拦截器已提示 */ } finally {
    roleSaving.value = false
  }
}

async function saveMyTitle() {
  try {
    await classroomApi.setMyTitle(current.value.id, myTitle.value.trim() || null)
    ElMessage.success('头衔已保存')
    await loadMembers()
  } catch { /* 拦截器已提示 */ }
}

function triggerImport() {
  importInput.value?.click()
}

async function onImportFile(event) {
  const file = event.target.files?.[0]
  if (!file) return
  importing.value = true
  try {
    const res = await classroomApi.importMembers(current.value.id, file)
    ElMessage.success(
      `导入完成：成功 ${res.imported}，跳过 ${res.skipped}，失败 ${res.failed}`,
    )
    const firstFail = (res.items || []).find(item => item.status === 'failed')
    if (firstFail) {
      ElMessage.warning(`第 ${firstFail.row} 行：${firstFail.message}`)
    }
    await Promise.all([loadMembers(), load()])
  } catch { /* 拦截器已提示 */ } finally {
    importing.value = false
    event.target.value = ''
  }
}

function openTransfer(row) {
  Object.assign(transferForm, {
    studentId: row.student_id,
    name: row.name,
    target_class_id: null,
  })
  transferVisible.value = true
}

async function saveTransfer() {
  if (!transferForm.target_class_id) return ElMessage.warning('请选择目标班级')
  transferSaving.value = true
  try {
    await classroomApi.transferMember(
      current.value.id, transferForm.studentId, transferForm.target_class_id,
    )
    ElMessage.success('转班完成')
    transferVisible.value = false
    await Promise.all([loadMembers(), load()])
  } catch { /* 拦截器已提示 */ } finally {
    transferSaving.value = false
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
/* 班级卡片网格：与课程管理保持一致的信息密度 */
.class-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--sp-4);
}
.class-card {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-5);
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-xs);
  transition: box-shadow var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.class-card:hover { box-shadow: var(--shadow-sm); border-color: var(--brand-300); }
.class-card__head { display: flex; align-items: flex-start; gap: var(--sp-3); }
.class-card__seal {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border: 1px solid var(--brand-300);
  border-radius: var(--r-sm);
  color: var(--color-primary);
  background: var(--color-primary-wash);
}
.class-card__title-wrap { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.class-card__title {
  margin: 0;
  font-family: var(--font-serif);
  font-size: var(--fs-md);
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.class-card__sub { font-size: var(--fs-xs); color: var(--text-secondary); }
.class-card__meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
  color: var(--text-secondary);
}
.class-card__stat { color: var(--text-primary); }
.class-card__code { margin-left: auto; font-size: var(--fs-xs); color: var(--text-placeholder); }
.class-card__actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-2);
  padding-top: var(--sp-3);
  border-top: 1px dashed var(--border);
}
.dim { color: var(--text-placeholder); font-size: var(--fs-xs); }
.unit { margin-left: var(--sp-2); color: var(--text-secondary); font-size: var(--fs-sm); }
.invite-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
}
.invite-row :deep(.el-input) { flex: 1 1 150px; }
.perm-group {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-3);
}
.ann-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  min-height: 120px;
}
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
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  margin-bottom: var(--sp-1);
}
.ann-item p {
  margin: 0;
  white-space: pre-wrap;
  line-height: 1.7;
  color: var(--text-primary);
}
.ann-composer {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin-top: var(--sp-4);
}
.assign-hint {
  font-size: var(--fs-xs);
  color: var(--text-secondary);
  margin-top: var(--sp-2);
}
.interview-panel { margin-top: var(--sp-4); }
.record-filter { width: 100%; margin-bottom: var(--sp-3); }
.interview-records { min-height: 160px; }
.interview-record {
  padding: var(--sp-3);
  margin-bottom: var(--sp-3);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--bg-card);
}
.interview-record__head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin-bottom: var(--sp-2);
  color: var(--text-secondary);
  font-size: var(--fs-xs);
}
.interview-record__head strong { color: var(--text-primary); font-size: var(--fs-sm); }
.interview-record__head time { margin-left: auto; }
.interview-record__scores {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-3);
  margin-bottom: var(--sp-3);
  color: var(--brand-700);
  font-size: var(--fs-xs);
}
.interview-record__section { margin-top: var(--sp-2); }
.interview-record__section > span {
  color: var(--text-secondary);
  font-size: var(--fs-xs);
  font-weight: 600;
}
.interview-record__section p {
  margin: var(--sp-1) 0 0;
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--r-sm);
  background: var(--bg-subtle);
  color: var(--text-primary);
  font-size: var(--fs-sm);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.panel :deep(.el-table__inner-wrapper::before) { display: none; }
.report h4 {
  margin: var(--sp-4) 0 var(--sp-2);
  font-size: var(--fs-sm);
  color: var(--text-primary);
}
.report-kpis {
  display: flex;
  gap: var(--sp-3);
  margin-top: var(--sp-3);
}
.report-kpis .kpi {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--sp-3);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--bg-card);
}
.report-kpis .kpi span { font-size: var(--fs-xs); color: var(--text-secondary); }
.report-kpis .kpi strong { font-size: var(--fs-lg); color: var(--text-primary); }
</style>
