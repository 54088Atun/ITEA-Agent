<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">风控审计</h2>
        <p class="page-sub">AI 对话触发的安全策略命中记录，支持按风险类型与用户追溯</p>
      </div>
      <div class="page-head__actions">
        <el-button @click="loadAll"><el-icon><Refresh /></el-icon> 刷新</el-button>
      </div>
    </div>

    <!-- 概览 -->
    <div class="kpi-grid">
      <div class="kpi">
        <div class="kpi__label">风控命中总数</div>
        <div class="kpi__value kpi__value--danger">{{ stats.total || 0 }}</div>
        <div class="kpi__hint">累计触发安全策略的对话次数</div>
      </div>
      <div class="kpi">
        <div class="kpi__label">按风险类型</div>
        <div class="tag-list">
          <el-tag v-for="(v, k) in stats.by_type || {}" :key="k" type="danger" size="small" effect="light">
            {{ k }}: {{ v }}
          </el-tag>
          <span v-if="!Object.keys(stats.by_type || {}).length" class="dim">暂无数据</span>
        </div>
      </div>
      <div class="kpi">
        <div class="kpi__label">按处置方式</div>
        <div class="tag-list">
          <el-tag v-for="(v, k) in stats.by_action || {}" :key="k" type="warning" size="small" effect="light">
            {{ k }}: {{ v }}
          </el-tag>
          <span v-if="!Object.keys(stats.by_action || {}).length" class="dim">暂无数据</span>
        </div>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="filter-bar">
      <el-select v-model="filters.risk_type" placeholder="全部风险类型" clearable style="width: 180px">
        <el-option v-for="t in riskTypes" :key="t" :label="t" :value="t" />
      </el-select>
      <el-input v-model="filters.user_id" placeholder="用户 ID" clearable style="width: 140px" @keyup.enter="reload" />
      <el-button type="primary" @click="reload"><el-icon><Search /></el-icon> 查询</el-button>
      <div class="filter-bar__spacer"></div>
      <span class="filter-bar__count">共 {{ total }} 条命中记录</span>
    </div>

    <div class="panel">
      <SkeletonTable v-if="loading && !items.length" :rows="6" :cols="5" />
      <StateBlock v-else-if="error" state="error" @retry="load" />
      <el-table v-else :data="items">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="用户" width="180">
          <template #default="{ row }">
            {{ row.user_name || '未知用户' }}<span class="dim"> #{{ row.user_id }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="request_content" label="请求内容" min-width="300" show-overflow-tooltip />
        <el-table-column label="风险类型" width="140">
          <template #default="{ row }">
            <el-tag type="danger" size="small" effect="light">{{ row.risk_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="处置方式" width="140">
          <template #default="{ row }">
            <el-tag type="warning" size="small" effect="light">{{ row.action_taken }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="命中时间" width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openContext(row)">上下文</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <StateBlock
            state="empty"
            title="暂无风控命中记录"
            hint="调整筛选条件后重试"
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

    <!-- 风险事件上下文 -->
    <el-drawer v-model="contextVisible" title="风险事件上下文" size="680px">
      <div v-loading="contextLoading" class="ctx-body">
        <template v-if="contextData">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="记录 ID">{{ contextData.risk_log.id }}</el-descriptions-item>
            <el-descriptions-item label="风险类型">{{ contextData.risk_log.risk_type }}</el-descriptions-item>
            <el-descriptions-item label="处置方式">{{ contextData.risk_log.action_taken }}</el-descriptions-item>
            <el-descriptions-item label="命中时间">{{ formatTime(contextData.risk_log.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="用户" :span="2">
              {{ contextData.user?.name || '未知用户' }}
              <span v-if="contextData.user" class="dim">
                #{{ contextData.user.id }} · {{ contextData.user.email }} · {{ contextData.user.status }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="请求内容" :span="2">
              {{ contextData.risk_log.request_content }}
            </el-descriptions-item>
          </el-descriptions>

          <section class="ctx-section">
            <h4 class="ctx-title">命中前 30 分钟（{{ contextData.interaction_context.before.length }}）</h4>
            <ul v-if="contextData.interaction_context.before.length" class="ctx-list">
              <li v-for="log in contextData.interaction_context.before" :key="`b-${log.id}`" class="ctx-item">
                <div class="ctx-item__head">
                  <el-tag size="small" effect="light" :type="log.role === 'user' ? '' : 'success'">
                    {{ log.role === 'user' ? '学生' : '助手' }}
                  </el-tag>
                  <span class="dim">{{ formatTime(log.created_at) }}</span>
                </div>
                <div class="ctx-item__content">{{ log.content }}</div>
              </li>
            </ul>
            <div v-else class="empty-state">无前置对话</div>
          </section>

          <section class="ctx-section">
            <h4 class="ctx-title">命中后 30 分钟（{{ contextData.interaction_context.after.length }}）</h4>
            <ul v-if="contextData.interaction_context.after.length" class="ctx-list">
              <li v-for="log in contextData.interaction_context.after" :key="`a-${log.id}`" class="ctx-item">
                <div class="ctx-item__head">
                  <el-tag size="small" effect="light" :type="log.role === 'user' ? '' : 'success'">
                    {{ log.role === 'user' ? '学生' : '助手' }}
                  </el-tag>
                  <span class="dim">{{ formatTime(log.created_at) }}</span>
                </div>
                <div class="ctx-item__content">{{ log.content }}</div>
              </li>
            </ul>
            <div v-else class="empty-state">无后续对话</div>
          </section>

          <section class="ctx-section">
            <h4 class="ctx-title">管理员处置（{{ contextData.handling.length }}）</h4>
            <el-table :data="contextData.handling" size="small" empty-text="暂无处置记录">
              <el-table-column prop="action" label="动作" width="150" />
              <el-table-column prop="admin_name" label="操作人" width="120" />
              <el-table-column prop="detail" label="详情" min-width="220" show-overflow-tooltip />
              <el-table-column label="时间" width="150">
                <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
              </el-table-column>
            </el-table>
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

const loading = ref(false)
const error = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const stats = ref({})
const filters = reactive({ risk_type: '', user_id: '' })

// 风险事件上下文
const contextVisible = ref(false)
const contextLoading = ref(false)
const contextData = ref(null)

const riskTypes = computed(() => Object.keys(stats.value.by_type || {}))

onMounted(loadAll)

async function loadAll() {
  await Promise.all([loadStats(), load()])
}

async function loadStats() {
  try {
    stats.value = await adminApi.riskStats()
  } catch { /* 拦截器已提示 */ }
}

async function load() {
  loading.value = true
  error.value = false
  try {
    const data = await adminApi.riskLogs({
      page: page.value,
      size: size.value,
      risk_type: filters.risk_type || undefined,
      user_id: filters.user_id || undefined,
    })
    items.value = data.items || []
    total.value = data.total || 0
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}

function reload() {
  page.value = 1
  load()
}

function formatTime(t) {
  if (!t) return '—'
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}

/** 上下文：命中前后的交互片段 + 管理员处置记录 */
async function openContext(row) {
  contextData.value = null
  contextVisible.value = true
  contextLoading.value = true
  try {
    contextData.value = await adminApi.riskContext(row.id)
  } catch { /* 拦截器已提示 */ } finally {
    contextLoading.value = false
  }
}
</script>

<style scoped>
.kpi__value--danger { color: var(--color-danger); }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: var(--sp-2); }
.dim { color: var(--text-placeholder); font-size: var(--fs-xs); }

/* 上下文抽屉 */
.ctx-body { display: flex; flex-direction: column; gap: var(--sp-4); min-height: 120px; }
.ctx-section { display: flex; flex-direction: column; gap: var(--sp-2); }
.ctx-title {
  margin: 0;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-primary);
}
.ctx-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.ctx-item {
  padding: var(--sp-3);
  background: var(--bg-subtle);
  border-radius: var(--r-md);
}
.ctx-item__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-bottom: var(--sp-1);
}
.ctx-item__content {
  font-size: var(--fs-sm);
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
