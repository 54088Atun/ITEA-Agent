<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <el-button link class="back-link" @click="router.push(`/teacher/classes/${classId}`)">
          <el-icon><ArrowLeft /></el-icon> 返回班级详情
        </el-button>
        <h2 class="page-title">{{ member?.name || '成员详情' }}</h2>
        <p class="page-sub">
          {{ classroom?.name || '' }}
          <template v-if="member"> · {{ roleLabel(member.role) }}{{ member.title ? ` · ${member.title}` : '' }}</template>
        </p>
      </div>
      <div v-if="member" class="page-head__actions">
        <el-tag :type="member.status === 'active' ? 'success' : 'info'" size="small" effect="light">
          {{ member.status === 'active' ? '在班' : '已退出' }}
        </el-tag>
      </div>
    </div>

    <div v-if="loading" class="panel">
      <SkeletonTable :rows="5" :cols="4" />
    </div>
    <StateBlock v-else-if="error" state="error" title="成员详情加载失败" @retry="load" />
    <StateBlock v-else-if="!member" state="empty" title="成员不存在" hint="该成员可能已被移出班级" />
    <template v-else>
      <div class="panel">
        <div class="panel__head">
          <span class="panel__title">基本信息</span>
        </div>
        <el-descriptions :column="descColumns" border size="small">
          <el-descriptions-item label="姓名">{{ member.name }}</el-descriptions-item>
          <el-descriptions-item label="邮箱">{{ member.email || '—' }}</el-descriptions-item>
          <el-descriptions-item label="班级角色">{{ roleLabel(member.role) }}</el-descriptions-item>
          <el-descriptions-item label="头衔">{{ member.title || '—' }}</el-descriptions-item>
          <el-descriptions-item label="加入时间">{{ formatTime(member.joined_at) }}</el-descriptions-item>
          <el-descriptions-item label="成员类型">
            {{ member.member_type === 'teacher' ? '教师' : '学生' }}
          </el-descriptions-item>
        </el-descriptions>
      </div>

      <div v-if="member.member_type === 'teacher'" class="panel">
        <StateBlock state="empty" title="教师成员无学情数据" hint="学情仅统计班级学生成员" />
      </div>
      <div v-else-if="!visibleInReport" class="panel">
        <StateBlock
          state="empty"
          title="该学生学习记录设置为仅自己可见"
          hint="按隐私设置，教师端不展示其学情明细"
        />
      </div>
      <template v-else>
        <div class="kpi-grid">
          <div class="kpi-card">
            <span>学习进度</span>
            <strong>{{ progressPercent }}%</strong>
          </div>
          <div class="kpi-card">
            <span>薄弱知识点</span>
            <strong>{{ weakCount }}</strong>
          </div>
          <div class="kpi-card">
            <span>错题总数</span>
            <strong>{{ overview?.wrong_questions?.total ?? '—' }}</strong>
          </div>
          <div class="kpi-card">
            <span>面试平均分</span>
            <strong>{{ overview?.interviews?.avg_score ?? '—' }}</strong>
          </div>
        </div>

        <div class="panel">
          <div class="panel__head">
            <span class="panel__title">知识点掌握度</span>
          </div>
          <el-table :data="overview?.progress?.mastery || []" size="small" empty-text="暂无掌握度数据">
            <el-table-column prop="kp_name" label="知识点" min-width="180" />
            <el-table-column label="掌握度" min-width="220">
              <template #default="{ row }">
                <el-progress
                  :percentage="row.mastery_level"
                  :stroke-width="8"
                  :status="row.mastery_level < 60 ? 'exception' : 'success'"
                />
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="two-col">
          <div class="panel">
            <div class="panel__head">
              <span class="panel__title">薄弱知识点</span>
            </div>
            <el-table :data="overview?.progress?.weak_points || []" size="small" empty-text="暂无薄弱知识点">
              <el-table-column prop="kp_name" label="知识点" min-width="140" />
              <el-table-column prop="mastery_level" label="掌握度" width="90" />
            </el-table>
          </div>

          <div class="panel">
            <div class="panel__head">
              <span class="panel__title">复习计划</span>
            </div>
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item label="待复习">{{ overview?.review_plans?.pending ?? 0 }} 题</el-descriptions-item>
              <el-descriptions-item label="今日到期">{{ overview?.review_plans?.due ?? 0 }} 题</el-descriptions-item>
              <el-descriptions-item label="下次复习">
                {{ formatTime(overview?.review_plans?.next_review_at) }}
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </div>

        <div class="panel">
          <div class="panel__head">
            <span class="panel__title">最近错题</span>
          </div>
          <el-table :data="overview?.wrong_questions?.recent || []" size="small" empty-text="暂无错题">
            <el-table-column label="知识点" width="150">
              <template #default="{ row }">{{ row.kp_name || '—' }}</template>
            </el-table-column>
            <el-table-column prop="question_content" label="题目" min-width="240" show-overflow-tooltip />
            <el-table-column label="错因" width="110">
              <template #default="{ row }">{{ row.error_type || '—' }}</template>
            </el-table-column>
            <el-table-column label="记录时间" width="150">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </div>

        <div class="panel">
          <div class="panel__head">
            <span class="panel__title">近期面试</span>
          </div>
          <el-table :data="overview?.interviews?.recent || []" size="small" empty-text="暂无面试记录">
            <el-table-column prop="round" label="轮次" width="70" />
            <el-table-column prop="question" label="问题" min-width="240" show-overflow-tooltip />
            <el-table-column prop="score" label="评分" width="80">
              <template #default="{ row }">{{ row.score ?? '—' }}</template>
            </el-table-column>
            <el-table-column label="时间" width="150">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </div>
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { classroomApi } from '../../api/classroom'
import { teacherApi } from '../../api/teacher'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'

const route = useRoute()
const router = useRouter()
const classId = Number(route.params.id)
const memberId = Number(route.params.memberId)
const descColumns = window.matchMedia('(max-width: 767px)').matches ? 1 : 2

const ROLE_LABELS = {
  head_teacher: '班主任',
  teacher: '任课教师',
  monitor: '班长',
  representative: '课代表',
  student: '普通学生',
  custom: '自定义',
}

const loading = ref(true)
const error = ref(false)
const classroom = ref(null)
const member = ref(null)
const report = ref(null)
const overview = ref(null)

const visibleInReport = computed(() => {
  if (!report.value) return true
  return (report.value.students || []).some((row) => row.user_id === memberId)
})

const progressPercent = computed(() => {
  if (overview.value?.progress?.overall_progress != null) {
    return Math.round(overview.value.progress.overall_progress)
  }
  const row = (report.value?.students || []).find((item) => item.user_id === memberId)
  return Math.round(row?.overall_progress || 0)
})

const weakCount = computed(() => {
  if (overview.value?.progress?.weak_points) return overview.value.progress.weak_points.length
  const row = (report.value?.students || []).find((item) => item.user_id === memberId)
  return row?.weak_count ?? 0
})

onMounted(load)

async function load() {
  loading.value = true
  error.value = false
  try {
    const [detail, memberRes, reportRes] = await Promise.all([
      classroomApi.detail(classId),
      classroomApi.members(classId),
      classroomApi.report(classId),
    ])
    classroom.value = detail
    report.value = reportRes
    member.value = (memberRes.items || []).find((row) => row.student_id === memberId) || null
  } catch {
    error.value = true
    loading.value = false
    return
  }
  loading.value = false
  await loadOverview()
}

async function loadOverview() {
  if (!member.value || member.value.member_type === 'teacher') return
  if (!visibleInReport.value || !classroom.value?.course_id) return
  try {
    overview.value = await teacherApi.studentCourseOverview(
      classroom.value.course_id,
      memberId,
    )
  } catch {
    // 无课程权限时降级为班级聚合数据
    overview.value = null
  }
}

function roleLabel(role) {
  return ROLE_LABELS[role] || role || '—'
}

function formatTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}
</script>

<style scoped>
.back-link { padding: 0; margin-bottom: var(--sp-1); color: var(--text-secondary); }
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--sp-3);
  margin: var(--sp-4) 0;
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
.two-col {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: var(--sp-4);
}
.panel { margin-bottom: var(--sp-4); }
</style>
