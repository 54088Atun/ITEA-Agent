<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">平台统计</h2>
        <p class="page-sub">用户、课程、对话与风控的实时概览，数据取自后端</p>
      </div>
      <div class="page-head__actions">
        <el-button @click="loadAll">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
    </div>

    <div v-if="loading && !hasData">
      <SkeletonCard :rows="2" />
      <SkeletonCard :rows="3" />
    </div>
    <StateBlock v-else-if="error && !hasData" state="error" title="平台统计加载失败" @retry="loadAll" />
    <el-tabs v-else v-model="tab">
      <!-- ===== 总览 ===== -->
      <el-tab-pane label="总览" name="overview">
        <div class="tab-body">
          <div class="kpi-grid">
            <div class="kpi">
              <div class="kpi__label">用户总数</div>
              <div class="kpi__value"><CountUp :value="overview.users?.total || 0" /></div>
              <div class="kpi__hint">启用 {{ overview.users?.active || 0 }} · 近 14 天新增 {{ recentUserGrowth }}</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">课程总数</div>
              <div class="kpi__value"><CountUp :value="overview.courses?.total || 0" /></div>
              <div class="kpi__hint">待审核 {{ overview.courses?.pending || 0 }} 门</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">对话消息</div>
              <div class="kpi__value kpi__value--accent"><CountUp :value="overview.interactions?.messages || 0" /></div>
              <div class="kpi__hint">会话数 {{ overview.interactions?.sessions || 0 }}</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">风控命中</div>
              <div class="kpi__value kpi__value--danger"><CountUp :value="overview.risk?.total || 0" /></div>
              <div class="kpi__hint">需人工复核的高风险对话</div>
            </div>
          </div>

          <div class="chart-grid">
            <section class="panel chart-panel">
              <div class="panel__head"><span class="panel__title">用户构成</span></div>
              <div class="panel__body">
                <SvgChart
                  type="donut"
                  :labels="roleChart.labels"
                  :series="roleChart.series"
                  center-label="用户"
                />
              </div>
            </section>

            <section class="panel chart-panel">
              <div class="panel__head"><span class="panel__title">课程审核状态</span></div>
              <div class="panel__body">
                <SvgChart
                  type="donut"
                  :labels="courseStatusChart.labels"
                  :series="courseStatusChart.series"
                  center-label="课程"
                />
              </div>
            </section>
          </div>

          <div class="chart-grid">
            <section class="panel chart-panel">
              <div class="panel__head">
                <span class="panel__title">近 14 天对话量</span>
                <span class="panel__hint">按日统计</span>
              </div>
              <div class="panel__body">
                <SvgChart
                  type="line"
                  :labels="dailyChatChart.labels"
                  :series="dailyChatChart.series"
                  :height="230"
                />
              </div>
            </section>

            <section class="panel chart-panel">
              <div class="panel__head">
                <span class="panel__title">风控类型分布</span>
                <span class="panel__hint">近 8 类</span>
              </div>
              <div class="panel__body">
                <SvgChart
                  type="hbar"
                  :labels="riskTypeChart.labels"
                  :series="riskTypeChart.series"
                  suffix=" 次"
                />
              </div>
            </section>
          </div>
        </div>
      </el-tab-pane>

      <!-- ===== 用户统计 ===== -->
      <el-tab-pane label="用户统计" name="users">
        <div class="tab-body">
          <div class="kpi-grid">
            <div class="kpi">
              <div class="kpi__label">用户总数</div>
              <div class="kpi__value"><CountUp :value="userStats.total || 0" /></div>
              <div class="kpi__hint">平台注册账号</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">教师</div>
              <div class="kpi__value"><CountUp :value="userStats.roles?.teacher || 0" /></div>
              <div class="kpi__hint">占比 {{ percent(userStats.roles?.teacher, userStats.total) }}%</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">学生</div>
              <div class="kpi__value"><CountUp :value="userStats.roles?.student || 0" /></div>
              <div class="kpi__hint">占比 {{ percent(userStats.roles?.student, userStats.total) }}%</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">已停用</div>
              <div class="kpi__value kpi__value--danger"><CountUp :value="userStats.status?.disabled || 0" /></div>
              <div class="kpi__hint">启用 {{ userStats.status?.active || 0 }} 个</div>
            </div>
          </div>

          <div class="chart-grid">
            <section class="panel chart-panel">
              <div class="panel__head"><span class="panel__title">角色分布</span></div>
              <div class="panel__body">
                <SvgChart
                  type="donut"
                  :labels="roleChart.labels"
                  :series="roleChart.series"
                  center-label="账号"
                />
              </div>
            </section>

            <section class="panel chart-panel">
              <div class="panel__head">
                <span class="panel__title">近 14 天新增用户</span>
                <span class="panel__hint">按注册日期</span>
              </div>
              <div class="panel__body">
                <SvgChart
                  type="line"
                  :labels="growthChart.labels"
                  :series="growthChart.series"
                  :height="230"
                />
              </div>
            </section>
          </div>

          <section class="panel chart-panel">
            <div class="panel__head">
              <span class="panel__title">累计用户规模</span>
              <span class="panel__hint">按日累加</span>
            </div>
            <div class="panel__body">
              <SvgChart
                type="line"
                :labels="cumulativeChart.labels"
                :series="cumulativeChart.series"
                :height="220"
              />
            </div>
          </section>

          <section class="panel">
            <div class="panel__head"><span class="panel__title">新增用户明细</span></div>
            <el-table :data="userStats.growth || []" max-height="360">
              <el-table-column prop="date" label="日期" width="180" />
              <el-table-column prop="count" label="新增用户数" />
              <template #empty>
                <StateBlock state="empty" title="暂无数据" />
              </template>
            </el-table>
          </section>
        </div>
      </el-tab-pane>

      <!-- ===== 课程统计 ===== -->
      <el-tab-pane label="课程统计" name="courses">
        <div class="tab-body">
          <div class="kpi-grid">
            <div class="kpi">
              <div class="kpi__label">课程总数</div>
              <div class="kpi__value"><CountUp :value="courseStats.total_courses || 0" /></div>
              <div class="kpi__hint">已建档课程</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">待审核</div>
              <div class="kpi__value kpi__value--accent"><CountUp :value="courseStatusCount('pending')" /></div>
              <div class="kpi__hint">需要处理的课程</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">已通过</div>
              <div class="kpi__value kpi__value--success"><CountUp :value="courseStatusCount('approved')" /></div>
              <div class="kpi__hint">正常开放</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">覆盖学生</div>
              <div class="kpi__value"><CountUp :value="totalStudents" /></div>
              <div class="kpi__hint">按课程选课人数累计</div>
            </div>
          </div>

          <div class="chart-grid">
            <section class="panel chart-panel">
              <div class="panel__head"><span class="panel__title">审核状态构成</span></div>
              <div class="panel__body">
                <SvgChart
                  type="donut"
                  :labels="courseStatusChart.labels"
                  :series="courseStatusChart.series"
                  center-label="课程"
                />
              </div>
            </section>

            <section class="panel chart-panel">
              <div class="panel__head">
                <span class="panel__title">学生平均掌握度分布</span>
                <span class="panel__hint">按人数</span>
              </div>
              <div class="panel__body">
                <SvgChart
                  type="bar"
                  :labels="masteryChart.labels"
                  :series="masteryChart.series"
                  :height="240"
                  suffix=" 人"
                />
              </div>
            </section>
          </div>

          <div class="chart-grid">
            <section class="panel chart-panel">
              <div class="panel__head">
                <span class="panel__title">选课人数 TOP</span>
                <span class="panel__hint">前 8 门</span>
              </div>
              <div class="panel__body">
                <SvgChart
                  type="hbar"
                  :labels="topStudentsChart.labels"
                  :series="topStudentsChart.series"
                  suffix=" 人"
                />
              </div>
            </section>

            <section class="panel chart-panel">
              <div class="panel__head">
                <span class="panel__title">平均进度 TOP</span>
                <span class="panel__hint">前 8 门</span>
              </div>
              <div class="panel__body">
                <SvgChart
                  type="hbar"
                  :labels="topProgressChart.labels"
                  :series="topProgressChart.series"
                  suffix="%"
                />
              </div>
            </section>
          </div>

          <section class="panel">
            <div class="panel__head"><span class="panel__title">课程覆盖与学情</span></div>
            <el-table :data="courseStats.courses || []">
              <el-table-column prop="course_id" label="课程ID" width="90" />
              <el-table-column prop="name" label="课程名称" min-width="180" />
              <el-table-column prop="code" label="代码" width="120" />
              <el-table-column label="审核状态" width="110">
                <template #default="{ row }">
                  <el-tag :type="auditTag(row.audit_status)" size="small" effect="light">{{ auditLabel(row.audit_status) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="student_count" label="学生数" width="100" />
              <el-table-column label="平均进度" width="220">
                <template #default="{ row }">
                  <el-progress :percentage="clamp(row.avg_progress)" :stroke-width="8" />
                </template>
              </el-table-column>
              <template #empty>
                <StateBlock state="empty" title="暂无课程" />
              </template>
            </el-table>
          </section>
        </div>
      </el-tab-pane>

      <!-- ===== Agent 统计 ===== -->
      <el-tab-pane label="Agent 统计" name="agent">
        <div class="tab-body">
          <div class="kpi-grid">
            <div class="kpi">
              <div class="kpi__label">对话消息总数</div>
              <div class="kpi__value"><CountUp :value="agentStats.total_messages || 0" /></div>
              <div class="kpi__hint">全部业务分支累计</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">会话总数</div>
              <div class="kpi__value"><CountUp :value="agentStats.total_sessions || 0" /></div>
              <div class="kpi__hint">平均 {{ avgMessages }} 条 / 会话</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">风控命中</div>
              <div class="kpi__value kpi__value--danger"><CountUp :value="agentStats.risk_hits || 0" /></div>
              <div class="kpi__hint">触发安全策略的对话</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">最活跃分支</div>
              <div class="kpi__value kpi__value--accent">{{ topBranch.label }}</div>
              <div class="kpi__hint">{{ topBranch.value }} 条消息</div>
            </div>
          </div>

          <div class="chart-grid">
            <section class="panel chart-panel">
              <div class="panel__head"><span class="panel__title">分支分布</span></div>
              <div class="panel__body">
                <SvgChart
                  type="donut"
                  :labels="branchChart.labels"
                  :series="branchChart.series"
                  center-label="消息"
                />
              </div>
            </section>

            <section class="panel chart-panel">
              <div class="panel__head">
                <span class="panel__title">近 14 天对话量</span>
                <span class="panel__hint">按日统计</span>
              </div>
              <div class="panel__body">
                <SvgChart
                  type="line"
                  :labels="dailyChatChart.labels"
                  :series="dailyChatChart.series"
                  :height="230"
                />
              </div>
            </section>
          </div>

          <div class="chart-grid">
            <section class="panel chart-panel">
              <div class="panel__head">
                <span class="panel__title">风控处置方式</span>
                <span class="panel__hint">拦截 / 引导</span>
              </div>
              <div class="panel__body">
                <SvgChart
                  type="donut"
                  :labels="riskActionChart.labels"
                  :series="riskActionChart.series"
                  center-label="命中"
                />
              </div>
            </section>

            <section class="panel chart-panel">
              <div class="panel__head">
                <span class="panel__title">近 14 天风控命中</span>
                <span class="panel__hint">按日统计</span>
              </div>
              <div class="panel__body">
                <SvgChart
                  type="line"
                  :labels="riskDailyChart.labels"
                  :series="riskDailyChart.series"
                  :height="230"
                />
              </div>
            </section>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { adminApi } from '../../api/admin'
import SvgChart from '../../components/charts/SvgChart.vue'
import SkeletonCard from '../../components/SkeletonCard.vue'
import StateBlock from '../../components/StateBlock.vue'
import CountUp from '../../components/CountUp.vue'

const tab = ref('overview')
const loading = ref(false)
const error = ref(false)
const overview = ref({})
const userStats = ref({})
const courseStats = ref({})
const agentStats = ref({})
const riskStats = ref({})
const hasData = computed(() => !!(overview.value?.users?.total || userStats.value?.growth?.length || courseStats.value?.courses?.length))

const ROLE_LABELS = { teacher: '教师', student: '学生', admin: '管理员' }
const BRANCH_LABELS = {
  teacher: '备课', tutor: '答疑', review: '复盘',
  interview: '面试', admin: '管理', block: '风控', team: '协作',
}
const STATUS_LABELS = { pending: '待审核', approved: '已通过', rejected: '已驳回' }

onMounted(loadAll)

async function loadAll() {
  error.value = false
  loading.value = true
  const [ov, us, cs, ag, rs] = await Promise.allSettled([
    adminApi.statsOverview(),
    adminApi.statsUsers(),
    adminApi.statsCourses(),
    adminApi.statsAgent(),
    adminApi.riskStats(),
  ])
  if (ov.status === 'fulfilled') overview.value = ov.value || {}
  if (us.status === 'fulfilled') userStats.value = us.value || {}
  if (cs.status === 'fulfilled') courseStats.value = cs.value || {}
  if (ag.status === 'fulfilled') agentStats.value = ag.value || {}
  if (rs.status === 'fulfilled') riskStats.value = rs.value || {}
  if ([ov, us, cs, ag, rs].filter((r) => r.status === 'fulfilled').length === 0) error.value = true
  loading.value = false
}

function tail(list, count) {
  return (list || []).slice(-count)
}

function numberValues(list, key = 'count') {
  return list.map((item) => Number(item?.[key]) || 0)
}

function dateLabels(list) {
  return list.map((item) => String(item?.date || '').slice(5))
}

function percent(value, total) {
  const sum = Number(total) || 0
  if (!sum) return 0
  return Math.round((Number(value) || 0) / sum * 100)
}

const roleChart = computed(() => {
  const roles = overview.value.users || {}
  return {
    labels: ['教师', '学生', '管理员'],
    series: [{
      name: '用户数',
      values: [roles.teacher || 0, roles.student || 0, roles.admin || 0],
    }],
  }
})

const courseStatusChart = computed(() => {
  const status = overview.value.courses?.by_status || {}
  const keys = ['pending', 'approved', 'rejected']
  return {
    labels: keys.map((key) => STATUS_LABELS[key]),
    series: [{ name: '课程数', values: keys.map((key) => status[key] || 0) }],
  }
})

function courseStatusCount(status) {
  return overview.value.courses?.by_status?.[status]
    ?? (courseStats.value.courses || []).filter((course) => course.audit_status === status).length
}

const recentUserGrowth = computed(() => {
  const rows = tail(userStats.value.growth, 14)
  return rows.reduce((sum, item) => sum + (Number(item.count) || 0), 0)
})

const growthChart = computed(() => {
  const rows = tail(userStats.value.growth, 14)
  return {
    labels: dateLabels(rows),
    series: [{ name: '新增用户', values: numberValues(rows) }],
  }
})

const cumulativeChart = computed(() => {
  const rows = tail(userStats.value.growth, 14)
  let running = 0
  const values = rows.map((item) => {
    running += Number(item.count) || 0
    return running
  })
  return {
    labels: dateLabels(rows),
    series: [{ name: '累计用户', values }],
  }
})

const dailyChatChart = computed(() => {
  const rows = tail(agentStats.value.daily, 14)
  return {
    labels: dateLabels(rows),
    series: [{ name: '消息数', values: numberValues(rows) }],
  }
})

const riskDailyChart = computed(() => {
  const rows = tail(riskStats.value.daily, 14)
  return {
    labels: dateLabels(rows),
    series: [{ name: '风控命中', values: numberValues(rows), color: 'var(--danger-600)' }],
  }
})

function mapChart(source, labels) {
  const entries = Object.entries(source || {})
    .filter(([key]) => key)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
  return {
    labels: entries.map(([key]) => labels[key] || key),
    series: [{ name: '数量', values: entries.map(([, value]) => Number(value) || 0) }],
  }
}

const branchChart = computed(() => {
  const chart = mapChart(agentStats.value.by_branch, BRANCH_LABELS)
  const untitled = (agentStats.value.by_branch || {})['']
  if (untitled) {
    chart.labels.push('未标注')
    chart.series[0].values.push(Number(untitled) || 0)
  }
  return chart
})

const riskTypeChart = computed(() => mapChart(riskStats.value.by_type, {}))
const riskActionChart = computed(() => mapChart(riskStats.value.by_action, {}))

const masteryChart = computed(() => {
  const distribution = courseStats.value.mastery_distribution || {}
  const labels = Object.keys(distribution)
  return {
    labels,
    series: [{ name: '学生数', values: labels.map((key) => Number(distribution[key]) || 0) }],
  }
})

function topCourses(metric) {
  const rows = [...(courseStats.value.courses || [])]
    .sort((a, b) => (Number(b?.[metric]) || 0) - (Number(a?.[metric]) || 0))
    .slice(0, 8)
  return {
    labels: rows.map((row) => row.name || `课程 ${row.course_id}`),
    series: [{
      name: metric === 'avg_progress' ? '平均进度' : '学生数',
      values: rows.map((row) => Number(row?.[metric]) || 0),
    }],
  }
}

const topStudentsChart = computed(() => topCourses('student_count'))
const topProgressChart = computed(() => topCourses('avg_progress'))

const totalStudents = computed(() => (
  (courseStats.value.courses || []).reduce(
    (sum, course) => sum + (Number(course.student_count) || 0), 0,
  )
))

const avgMessages = computed(() => {
  const sessions = Number(agentStats.value.total_sessions) || 0
  const messages = Number(agentStats.value.total_messages) || 0
  return sessions ? Math.round(messages / sessions) : 0
})

const topBranch = computed(() => {
  const entries = Object.entries(agentStats.value.by_branch || {})
    .filter(([key]) => key)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
  if (!entries.length) return { label: '—', value: 0 }
  return {
    label: BRANCH_LABELS[entries[0][0]] || entries[0][0],
    value: Number(entries[0][1]) || 0,
  }
})

function clamp(value) {
  return Math.min(100, Math.max(0, Math.round(Number(value) || 0)))
}

function auditLabel(status) {
  return STATUS_LABELS[status] || status
}

function auditTag(status) {
  return { pending: 'warning', approved: 'success', rejected: 'danger' }[status] || 'info'
}
</script>

<style scoped>
.tab-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding-top: var(--sp-2);
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-4);
}

.chart-panel {
  min-width: 0;
}

.chart-panel .panel__body {
  padding: var(--sp-3) var(--sp-4) var(--sp-4);
}

.panel__hint {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--text-placeholder);
}

.kpi__value--accent { color: var(--color-accent); }
.kpi__value--danger { color: var(--color-danger); }
.kpi__value--success { color: var(--color-success); }

.split .panel :deep(.el-table__inner-wrapper::before) { display: none; }

@media (max-width: 1100px) {
  .chart-grid {
    grid-template-columns: 1fr;
  }
}
</style>
