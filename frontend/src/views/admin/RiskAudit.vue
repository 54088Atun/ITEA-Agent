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
      <el-table :data="items" v-loading="loading">
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
        <template #empty>
          <div class="empty-state">暂无风控命中记录</div>
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
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { adminApi } from '../../api/admin'

const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const stats = ref({})
const filters = reactive({ risk_type: '', user_id: '' })

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
  try {
    const data = await adminApi.riskLogs({
      page: page.value,
      size: size.value,
      risk_type: filters.risk_type || undefined,
      user_id: filters.user_id || undefined,
    })
    items.value = data.items || []
    total.value = data.total || 0
  } catch { /* 拦截器已提示 */ } finally {
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
</script>

<style scoped>
.kpi__value--danger { color: var(--color-danger); }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: var(--sp-2); }
.dim { color: var(--text-placeholder); font-size: var(--fs-xs); }
</style>
