<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">运行回放</h2>
        <p class="page-sub">按 run_id 追溯 Agent 编排链路：route / plan / tool / reflect / answer，定位失败节点</p>
      </div>
      <div class="page-head__actions">
        <el-button @click="reloadAll">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
    </div>

    <div class="kpi-grid">
      <div class="kpi">
        <div class="kpi__label">运行总数</div>
        <div class="kpi__value">{{ totalRuns }}</div>
        <div class="kpi__hint">已记录的 Agent 运行</div>
      </div>
      <div class="kpi">
        <div class="kpi__label">成功</div>
        <div class="kpi__value kpi__value--success">{{ stats.by_status?.success || 0 }}</div>
        <div class="kpi__hint">正常完成</div>
      </div>
      <div class="kpi">
        <div class="kpi__label">失败</div>
        <div class="kpi__value kpi__value--danger">{{ stats.by_status?.failed || 0 }}</div>
        <div class="kpi__hint">需回放定位</div>
      </div>
      <div class="kpi">
        <div class="kpi__label">运行中</div>
        <div class="kpi__value kpi__value--accent">{{ stats.by_status?.running || 0 }}</div>
        <div class="kpi__hint">已取消 {{ stats.by_status?.cancelled || 0 }}</div>
      </div>
      <div class="kpi">
        <div class="kpi__label">平均耗时</div>
        <div class="kpi__value">{{ formatDuration(stats.avg_duration_ms) }}</div>
        <div class="kpi__hint">按已结束运行统计</div>
      </div>
    </div>

    <div class="filter-bar">
      <el-select v-model="filters.status" placeholder="全部状态" clearable style="width: 150px">
        <el-option label="成功 success" value="success" />
        <el-option label="失败 failed" value="failed" />
        <el-option label="运行中 running" value="running" />
        <el-option label="已取消 cancelled" value="cancelled" />
      </el-select>
      <DebouncedInput v-model="filters.user_id" placeholder="用户 ID" clearable style="width: 140px" @keyup.enter="reloadRuns" @debounce="reloadRuns" />
      <el-select v-model="filters.branch" placeholder="全部分支" clearable style="width: 160px">
        <el-option label="备课 teacher" value="teacher" />
        <el-option label="助教 tutor" value="tutor" />
        <el-option label="复盘 review" value="review" />
        <el-option label="面试 interview" value="interview" />
        <el-option label="管理 admin" value="admin" />
        <el-option label="协作 team" value="team" />
        <el-option label="风控 block" value="block" />
      </el-select>
      <el-button type="primary" @click="reloadRuns"><el-icon><Search /></el-icon> 查询</el-button>
      <div class="filter-bar__spacer"></div>
      <span class="filter-bar__count">共 {{ total }} 条运行</span>
    </div>

    <div class="panel">
      <SkeletonTable v-if="loading && !runs.length" :rows="8" :cols="6" />
      <StateBlock v-else-if="error" state="error" @retry="loadRuns" />
      <el-table v-else :data="runs">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small" effect="light">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="用户" width="150">
          <template #default="{ row }">
            {{ row.role || '未知' }}<span class="dim"> #{{ row.user_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="分支" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.branch" size="small" effect="plain">{{ row.branch }}</el-tag>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="request_id" label="请求 ID" width="180" show-overflow-tooltip />
        <el-table-column prop="input_preview" label="输入预览" min-width="300" show-overflow-tooltip />
        <el-table-column label="耗时" width="100">
          <template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template>
        </el-table-column>
        <el-table-column label="开始时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openRun(row)">查看回放</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <StateBlock
            state="empty"
            title="暂无运行记录"
            hint="调整状态、用户或分支筛选后重试"
          />
        </template>
      </el-table>

      <div ref="sentinel" class="load-more">
        <el-button
          v-if="runs.length < total"
          text type="primary" :loading="loading"
          @click="loadMoreRuns"
        >加载更多（已加载 {{ runs.length }} / {{ total }}）</el-button>
        <span v-else-if="runs.length" class="load-more__done">已加载全部 {{ total }} 条</span>
      </div>
    </div>

    <el-drawer v-model="drawer" title="运行回放" size="720px" @closed="resetDetail">
      <div v-loading="detailLoading" class="drawer-body">
        <template v-if="detail">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="运行 ID">{{ detail.id }}</el-descriptions-item>
            <el-descriptions-item label="状态">
              <el-tag :type="statusType(detail.status)" size="small" effect="light">{{ detail.status }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="用户">
              {{ detail.role || '未知' }}<span class="dim"> #{{ detail.user_id }}</span>
            </el-descriptions-item>
            <el-descriptions-item label="分支">{{ detail.branch || '—' }}</el-descriptions-item>
            <el-descriptions-item label="会话 ID">{{ detail.session_id || '—' }}</el-descriptions-item>
            <el-descriptions-item label="请求 ID">{{ detail.request_id || '—' }}</el-descriptions-item>
            <el-descriptions-item label="耗时">{{ formatDuration(detail.duration_ms) }}</el-descriptions-item>
            <el-descriptions-item label="开始时间">{{ formatTime(detail.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="结束时间" :span="2">{{ formatTime(detail.finished_at) }}</el-descriptions-item>
          </el-descriptions>

          <el-alert
            v-if="detail.error"
            class="drawer-alert"
            type="error"
            :closable="false"
            show-icon
            :title="detail.error"
          />

          <section class="drawer-section">
            <div class="drawer-section__title">输入</div>
            <pre class="code-block">{{ detail.input_preview || '（无）' }}</pre>
          </section>

          <section class="drawer-section">
            <div class="drawer-section__title">输出</div>
            <pre class="code-block">{{ detail.output_preview || '（无）' }}</pre>
          </section>

          <section class="drawer-section">
            <div class="drawer-section__title">
              执行链路
              <span class="dim">共 {{ spans.length }} 个节点</span>
            </div>
            <div v-if="!spans.length" class="empty-state" style="padding: 24px 0">暂无埋点数据</div>
            <el-collapse v-else>
              <el-collapse-item v-for="s in spans" :key="s.id" :name="s.id">
                <template #title>
                  <div class="span-head">
                    <span class="span-seq">#{{ s.seq }}</span>
                    <el-tag :type="kindType(s.kind)" size="small" effect="light">{{ s.kind }}</el-tag>
                    <span class="span-name">{{ s.name || '—' }}</span>
                    <el-tag :type="spanStatusType(s.status)" size="small" effect="plain">{{ s.status }}</el-tag>
                    <span class="span-meta">{{ formatDuration(s.duration_ms) }}</span>
                    <span class="span-meta">tokens {{ s.tokens ?? 0 }}</span>
                  </div>
                </template>
                <div class="span-body">
                  <div v-if="s.error" class="span-block">
                    <div class="span-block__label">error</div>
                    <pre class="code-block code-block--danger">{{ s.error }}</pre>
                  </div>
                  <div v-if="s.payload" class="span-block">
                    <div class="span-block__label">payload</div>
                    <pre class="code-block">{{ pretty(s.payload) }}</pre>
                  </div>
                  <div v-if="s.result" class="span-block">
                    <div class="span-block__label">result</div>
                    <pre class="code-block">{{ pretty(s.result) }}</pre>
                  </div>
                  <div v-if="!s.error && !s.payload && !s.result" class="span-block">
                    <span class="dim">该节点无附加数据</span>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
          </section>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { adminApi } from '../../api/admin'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'
import DebouncedInput from '../../components/DebouncedInput.vue'
import { useAutoLoadMore } from '../../composables/useAutoLoadMore.js'

const loading = ref(false)
const error = ref(false)
const runs = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const filters = reactive({ status: '', user_id: '', branch: '' })
const sentinel = ref(null)

const stats = ref({ by_status: {}, avg_duration_ms: 0 })
const totalRuns = computed(() =>
  Object.values(stats.value.by_status || {}).reduce((a, b) => a + (b || 0), 0),
)

const drawer = ref(false)
const detailLoading = ref(false)
const detail = ref(null)
const spans = ref([])

async function loadRuns(reset = true) {
  if (reset) {
    page.value = 1
    error.value = false
  }
  loading.value = true
  try {
    const data = await adminApi.agentRuns({
      page: page.value,
      page_size: size.value,
      status: filters.status || undefined,
      user_id: filters.user_id || undefined,
      branch: filters.branch || undefined,
    })
    const rows = data.items || []
    runs.value = reset ? rows : [...runs.value, ...rows]
    total.value = data.total || 0
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

function loadMoreRuns() {
  if (loading.value || runs.value.length >= total.value) return
  page.value += 1
  loadRuns(false)
}

async function loadStats() {
  try {
    stats.value = (await adminApi.agentRunStats()) || { by_status: {}, avg_duration_ms: 0 }
  } catch { /* 拦截器已提示 */ }
}

function reloadRuns() {
  page.value = 1
  loadRuns()
}

function reloadAll() {
  reloadRuns()
  loadStats()
}

async function openRun(row) {
  detail.value = row
  spans.value = []
  drawer.value = true
  detailLoading.value = true
  try {
    const [run, trace] = await Promise.all([
      adminApi.agentRun(row.id),
      adminApi.agentRunTrace(row.id),
    ])
    detail.value = run || row
    spans.value = trace?.spans || []
  } catch { /* 拦截器已提示 */ } finally {
    detailLoading.value = false
  }
}

function resetDetail() {
  detail.value = null
  spans.value = []
}

function statusType(status) {
  return { success: 'success', failed: 'danger', running: 'warning', cancelled: 'info' }[status] || 'info'
}

function spanStatusType(status) {
  return { ok: 'success', error: 'danger', failed: 'danger' }[status] || 'info'
}

function kindType(kind) {
  return {
    route: 'primary',
    plan: 'success',
    tool: 'warning',
    reflect: 'info',
    answer: 'success',
    block: 'danger',
    expert: 'info',
  }[kind] || 'info'
}

function formatTime(t) {
  if (!t) return '—'
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}

function formatDuration(ms) {
  if (ms === null || ms === undefined) return '—'
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`
  return `${ms} ms`
}

function pretty(text) {
  if (!text) return ''
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}

onMounted(() => {
  loadRuns()
  loadStats()
})

// 滚动到底自动加载下一页；按钮保留为兜底入口
useAutoLoadMore(
  sentinel,
  () => !loading.value && runs.value.length < total.value,
  loadMoreRuns,
)
</script>

<style scoped>
.drawer-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  min-height: 200px;
}
.drawer-alert {
  margin-top: var(--sp-3);
}
.drawer-section__title {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-weight: 600;
  margin-bottom: var(--sp-2);
}
.code-block {
  margin: 0;
  padding: var(--sp-3);
  background: var(--bg-muted, #f6f7f9);
  border-radius: 6px;
  font-size: var(--fs-xs);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 260px;
  overflow: auto;
}
.code-block--danger {
  background: #fef0f0;
  color: #f56c6c;
}
.span-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.span-seq {
  color: var(--text-placeholder);
  font-size: var(--fs-xs);
  min-width: 32px;
}
.span-name {
  font-weight: 600;
}
.span-meta {
  color: var(--text-placeholder);
  font-size: var(--fs-xs);
}
.span-body {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.span-block__label {
  font-size: var(--fs-xs);
  color: var(--text-placeholder);
  margin-bottom: 4px;
}
.load-more {
  display: flex;
  justify-content: center;
  min-height: 40px;
  padding: var(--sp-2) var(--sp-4);
}
.load-more__done { font-size: var(--fs-xs); color: var(--text-placeholder); }
</style>
