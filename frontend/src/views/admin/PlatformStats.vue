<template>
  <div class="page" v-loading="loading">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">平台统计</h2>
        <p class="page-sub">用户、课程与 AI 对话的整体运行概览，数据实时取自后端</p>
      </div>
      <div class="page-head__actions">
        <el-button @click="loadAll">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
    </div>

    <el-tabs v-model="tab">
      <!-- 总览 -->
      <el-tab-pane label="总览" name="overview">
        <div class="tab-body">
          <div class="kpi-grid">
            <div class="kpi">
              <div class="kpi__label">用户总数</div>
              <div class="kpi__value">{{ overview.users?.total || 0 }}</div>
              <div class="kpi__hint">含教师、学生与管理员</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">课程总数</div>
              <div class="kpi__value">{{ overview.courses?.total || 0 }}</div>
              <div class="kpi__hint">待审核 {{ overview.courses?.pending || 0 }} 门</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">对话消息</div>
              <div class="kpi__value kpi__value--accent">{{ overview.interactions?.messages || 0 }}</div>
              <div class="kpi__hint">会话数 {{ overview.interactions?.sessions || 0 }}</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">风控命中</div>
              <div class="kpi__value kpi__value--danger">{{ overview.risk?.total || 0 }}</div>
              <div class="kpi__hint">需人工复核的高风险对话</div>
            </div>
          </div>

          <div class="split">
            <div class="panel">
              <div class="panel__head"><span class="panel__title">用户构成</span></div>
              <div class="panel__body">
                <div class="kv-row"><span>教师</span><b>{{ overview.users?.teacher || 0 }}</b></div>
                <div class="kv-row"><span>学生</span><b>{{ overview.users?.student || 0 }}</b></div>
                <div class="kv-row"><span>管理员</span><b>{{ overview.users?.admin || 0 }}</b></div>
                <div class="kv-row"><span>活跃账号</span><b class="good">{{ overview.users?.active || 0 }}</b></div>
              </div>
            </div>

            <div class="panel">
              <div class="panel__head"><span class="panel__title">课程与对话</span></div>
              <div class="panel__body">
                <div class="kv-row"><span>课程总数</span><b>{{ overview.courses?.total || 0 }}</b></div>
                <div class="kv-row"><span>待审核课程</span><b class="warn">{{ overview.courses?.pending || 0 }}</b></div>
                <div class="kv-row"><span>对话消息数</span><b>{{ overview.interactions?.messages || 0 }}</b></div>
                <div class="kv-row"><span>会话数</span><b>{{ overview.interactions?.sessions || 0 }}</b></div>
                <div class="kv-row"><span>风控命中</span><b class="danger">{{ overview.risk?.total || 0 }}</b></div>
              </div>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- 用户统计 -->
      <el-tab-pane label="用户统计" name="users">
        <div class="tab-body">
          <div class="kpi-grid">
            <div class="kpi">
              <div class="kpi__label">用户总数</div>
              <div class="kpi__value">{{ userStats.total || 0 }}</div>
              <div class="kpi__hint">平台注册账号</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">角色分布</div>
              <div class="tag-list">
                <el-tag v-for="(v, k) in userStats.roles || {}" :key="k" size="small" effect="light">{{ k }}: {{ v }}</el-tag>
                <span v-if="!Object.keys(userStats.roles || {}).length" class="dim">暂无数据</span>
              </div>
            </div>
          </div>

          <div class="panel">
            <div class="panel__head"><span class="panel__title">用户增长（按日）</span></div>
            <el-table :data="userStats.growth || []" max-height="420">
              <el-table-column prop="date" label="日期" width="180" />
              <el-table-column prop="count" label="新增用户数" />
              <template #empty>
                <div class="empty-state">暂无数据</div>
              </template>
            </el-table>
          </div>
        </div>
      </el-tab-pane>

      <!-- 课程统计 -->
      <el-tab-pane label="课程统计" name="courses">
        <div class="tab-body">
          <div class="kpi-grid">
            <div class="kpi">
              <div class="kpi__label">课程总数</div>
              <div class="kpi__value">{{ courseStats.total_courses || 0 }}</div>
              <div class="kpi__hint">已建档课程</div>
            </div>
            <div class="kpi kpi--wide">
              <div class="kpi__label">学生平均掌握度分布</div>
              <div class="dist-list">
                <div v-for="(v, k) in courseStats.mastery_distribution || {}" :key="k" class="dist-item">
                  <span class="dist-label">{{ k }}</span>
                  <el-progress :percentage="distPercent(k, v)" :show-text="false" :stroke-width="8" />
                  <span class="dist-count">{{ v }} 人</span>
                </div>
                <span v-if="!Object.keys(courseStats.mastery_distribution || {}).length" class="dim">暂无数据</span>
              </div>
            </div>
          </div>

          <div class="panel">
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
                <div class="empty-state">暂无课程</div>
              </template>
            </el-table>
          </div>
        </div>
      </el-tab-pane>

      <!-- Agent 统计 -->
      <el-tab-pane label="Agent 统计" name="agent">
        <div class="tab-body">
          <div class="kpi-grid">
            <div class="kpi">
              <div class="kpi__label">对话消息总数</div>
              <div class="kpi__value">{{ agentStats.total_messages || 0 }}</div>
              <div class="kpi__hint">全部业务分支累计</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">会话总数</div>
              <div class="kpi__value">{{ agentStats.total_sessions || 0 }}</div>
              <div class="kpi__hint">独立会话数</div>
            </div>
            <div class="kpi">
              <div class="kpi__label">风控命中</div>
              <div class="kpi__value kpi__value--danger">{{ agentStats.risk_hits || 0 }}</div>
              <div class="kpi__hint">触发安全策略的对话</div>
            </div>
          </div>

          <div class="split split--wide">
            <div class="panel">
              <div class="panel__head"><span class="panel__title">分支分布</span></div>
              <div class="panel__body">
                <div class="kv-row" v-for="(v, k) in agentStats.by_branch || {}" :key="k">
                  <span>{{ k || '未标注' }}</span><b>{{ v }}</b>
                </div>
                <div v-if="!Object.keys(agentStats.by_branch || {}).length" class="empty-state">暂无数据</div>
              </div>
            </div>
            <div class="panel">
              <div class="panel__head"><span class="panel__title">每日对话量</span></div>
              <el-table :data="agentStats.daily || []" max-height="360">
                <el-table-column prop="date" label="日期" width="180" />
                <el-table-column prop="count" label="消息数" />
                <template #empty>
                  <div class="empty-state">暂无数据</div>
                </template>
              </el-table>
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { adminApi } from '../../api/admin'

const tab = ref('overview')
const loading = ref(false)
const overview = ref({})
const userStats = ref({})
const courseStats = ref({})
const agentStats = ref({})

onMounted(loadAll)

async function loadAll() {
  loading.value = true
  const [ov, us, cs, ag] = await Promise.allSettled([
    adminApi.statsOverview(),
    adminApi.statsUsers(),
    adminApi.statsCourses(),
    adminApi.statsAgent(),
  ])
  if (ov.status === 'fulfilled') overview.value = ov.value || {}
  if (us.status === 'fulfilled') userStats.value = us.value || {}
  if (cs.status === 'fulfilled') courseStats.value = cs.value || {}
  if (ag.status === 'fulfilled') agentStats.value = ag.value || {}
  loading.value = false
}

function distPercent(label, count) {
  const total = Object.values(courseStats.value.mastery_distribution || {})
    .reduce((a, b) => a + Number(b || 0), 0)
  if (!total) return 0
  return Math.round((Number(count || 0) / total) * 100)
}

function clamp(v) {
  return Math.min(100, Math.max(0, Math.round(Number(v) || 0)))
}

function auditLabel(s) {
  return { pending: '待审核', approved: '已通过', rejected: '已驳回' }[s] || s
}
function auditTag(s) {
  return { pending: 'warning', approved: 'success', rejected: 'danger' }[s] || 'info'
}
</script>

<style scoped>
.tab-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding-top: var(--sp-2);
}

.kpi--wide { grid-column: span 2; }

.kpi__value--accent { color: var(--color-accent); }
.kpi__value--danger { color: var(--color-danger); }

.split {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: var(--sp-4);
}

.kv-row {
  display: flex;
  justify-content: space-between;
  padding: var(--sp-2) 0;
  border-bottom: 1px dashed var(--border);
  font-size: var(--fs-base);
  color: var(--text-secondary);
}
.kv-row:last-child { border-bottom: none; }
.kv-row b { color: var(--text-primary); font-weight: 600; }
.good { color: var(--color-success); }
.warn { color: var(--color-warning); }
.danger { color: var(--color-danger); }

.tag-list { display: flex; flex-wrap: wrap; gap: var(--sp-2); }
.dist-list { display: flex; flex-direction: column; gap: var(--sp-2); }
.dist-item { display: flex; align-items: center; gap: var(--sp-3); }
.dist-label { width: 60px; font-size: var(--fs-xs); color: var(--text-secondary); }
.dist-item :deep(.el-progress) { flex: 1; }
.dist-count { width: 60px; text-align: right; font-size: var(--fs-xs); color: var(--text-placeholder); }
.dim { color: var(--text-placeholder); font-size: var(--fs-xs); }

.split .panel :deep(.el-table__inner-wrapper::before) { display: none; }
</style>
