<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">日志审计</h2>
        <p class="page-sub">AI 对话记录与管理员操作留痕，按用户、分支与会话追溯</p>
      </div>
    </div>

    <el-tabs v-model="tab">
      <!-- 对话日志 -->
      <el-tab-pane label="对话日志" name="interaction">
        <div class="tab-body">
          <div class="filter-bar">
            <el-input v-model="iFilters.user_id" placeholder="用户 ID" clearable style="width: 140px" />
            <el-select v-model="iFilters.branch" placeholder="全部分支" clearable style="width: 160px">
              <el-option label="备课 teacher" value="teacher" />
              <el-option label="助教 tutor" value="tutor" />
              <el-option label="复盘 review" value="review" />
              <el-option label="面试 interview" value="interview" />
              <el-option label="风控 block" value="block" />
            </el-select>
            <el-input v-model="iFilters.session_id" placeholder="会话 ID" clearable style="width: 220px" />
            <el-button type="primary" @click="reloadInteraction"><el-icon><Search /></el-icon> 查询</el-button>
            <div class="filter-bar__spacer"></div>
            <span class="filter-bar__count">共 {{ iTotal }} 条对话</span>
          </div>

          <div class="panel">
            <el-table :data="interactions" v-loading="iLoading">
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column label="用户" width="150">
                <template #default="{ row }">
                  {{ row.user_name || '未知' }}<span class="dim"> #{{ row.user_id }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="session_id" label="会话 ID" width="200" show-overflow-tooltip />
              <el-table-column prop="role" label="角色" width="90" />
              <el-table-column label="分支" width="110">
                <template #default="{ row }">
                  <el-tag v-if="row.branch" size="small" effect="light">{{ row.branch }}</el-tag>
                  <span v-else class="dim">—</span>
                </template>
              </el-table-column>
              <el-table-column prop="content" label="内容" min-width="320" show-overflow-tooltip />
              <el-table-column label="时间" width="180">
                <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
              </el-table-column>
              <template #empty>
                <div class="empty-state">暂无对话日志</div>
              </template>
            </el-table>

            <div class="pager">
              <el-pagination
                v-model:current-page="iPage"
                v-model:page-size="iSize"
                :total="iTotal"
                :page-sizes="[10, 20, 50]"
                layout="total, sizes, prev, pager, next"
                @current-change="loadInteraction"
                @size-change="reloadInteraction"
              />
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- 操作日志 -->
      <el-tab-pane label="操作日志" name="operation">
        <div class="tab-body">
          <div class="filter-bar">
            <el-input v-model="oFilters.admin_id" placeholder="管理员 ID" clearable style="width: 150px" />
            <el-select v-model="oFilters.action" placeholder="全部动作" clearable style="width: 160px">
              <el-option v-for="a in actions" :key="a" :label="a" :value="a" />
            </el-select>
            <el-select v-model="oFilters.target_type" placeholder="全部对象" clearable style="width: 160px">
              <el-option v-for="t in targetTypes" :key="t" :label="t" :value="t" />
            </el-select>
            <el-button type="primary" @click="reloadOperation"><el-icon><Search /></el-icon> 查询</el-button>
            <div class="filter-bar__spacer"></div>
            <span class="filter-bar__count">共 {{ oTotal }} 条操作</span>
          </div>

          <div class="panel">
            <el-table :data="operations" v-loading="oLoading">
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column label="操作人" width="150">
                <template #default="{ row }">
                  {{ row.admin_name || '未知' }}<span class="dim"> #{{ row.admin_id }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="action" label="动作" width="110" />
              <el-table-column prop="target_type" label="对象类型" width="110" />
              <el-table-column prop="target_id" label="对象 ID" width="100" />
              <el-table-column prop="detail" label="详情" min-width="300" show-overflow-tooltip />
              <el-table-column prop="ip" label="IP" width="140" />
              <el-table-column label="时间" width="180">
                <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
              </el-table-column>
              <template #empty>
                <div class="empty-state">暂无操作日志</div>
              </template>
            </el-table>

            <div class="pager">
              <el-pagination
                v-model:current-page="oPage"
                v-model:page-size="oSize"
                :total="oTotal"
                :page-sizes="[10, 20, 50]"
                layout="total, sizes, prev, pager, next"
                @current-change="loadOperation"
                @size-change="reloadOperation"
              />
            </div>
          </div>
        </div>
      </el-tab-pane>
      <!-- 写操作审计 -->
      <el-tab-pane label="写操作审计" name="audit">
        <div class="tab-body">
          <div class="filter-bar">
            <el-select v-model="aAction" placeholder="全部写操作" clearable style="width: 260px">
              <el-option
                v-for="item in actionOptions"
                :key="item.key"
                :label="`${item.label}（${item.level_label}）`"
                :value="item.key"
              />
            </el-select>
            <el-button type="primary" @click="reloadAudit"><el-icon><Search /></el-icon> 查询</el-button>
            <div class="filter-bar__spacer"></div>
            <span class="filter-bar__count">共 {{ aTotal }} 条写操作</span>
          </div>

          <div class="panel">
            <el-table :data="audits" v-loading="aLoading">
              <el-table-column prop="id" label="ID" width="70" />
              <el-table-column label="操作人" width="160">
                <template #default="{ row }">
                  {{ row.user_name || '未知' }}<span class="dim"> #{{ row.user_id }} · {{ row.user_role }}</span>
                </template>
              </el-table-column>
              <el-table-column label="动作" min-width="180">
                <template #default="{ row }">
                  {{ row.action_label }}<span class="dim"> {{ row.action }}</span>
                </template>
              </el-table-column>
              <el-table-column label="审批级别" width="110">
                <template #default="{ row }">
                  <el-tag size="small" :type="levelType(row.approval_mode)" effect="light">
                    {{ row.approval_label }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="90">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.status === 'executed' ? 'success' : 'info'">
                    {{ row.status === 'executed' ? '已执行' : '待确认' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="对象" width="150">
                <template #default="{ row }">
                  {{ row.target_type }}<span class="dim"> #{{ row.target_id ?? '—' }}</span>
                </template>
              </el-table-column>
              <el-table-column prop="detail" label="详情" min-width="240" show-overflow-tooltip />
              <el-table-column label="时间" width="180">
                <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
              </el-table-column>
              <template #empty>
                <div class="empty-state">暂无写操作审计</div>
              </template>
            </el-table>

            <div class="pager">
              <el-pagination
                v-model:current-page="aPage"
                v-model:page-size="aSize"
                :total="aTotal"
                :page-sizes="[10, 20, 50]"
                layout="total, sizes, prev, pager, next"
                @current-change="loadAudit"
                @size-change="reloadAudit"
              />
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, watch } from 'vue'
import { adminApi } from '../../api/admin'
import { approvalsApi } from '../../api/approvals'

const tab = ref('interaction')

// 对话日志
const iLoading = ref(false)
const interactions = ref([])
const iTotal = ref(0)
const iPage = ref(1)
const iSize = ref(20)
const iFilters = reactive({ user_id: '', branch: '', session_id: '' })

// 操作日志
const oLoading = ref(false)
const operations = ref([])
const oTotal = ref(0)
const oPage = ref(1)
const oSize = ref(20)
const oFilters = reactive({ admin_id: '', action: '', target_type: '' })

// 写操作审计
const aLoading = ref(false)
const audits = ref([])
const aTotal = ref(0)
const aPage = ref(1)
const aSize = ref(20)
const aAction = ref('')
const actionOptions = ref([])

const actions = ['create', 'update', 'delete', 'enable', 'disable', 'approve', 'reject', 'config']
const targetTypes = ['user', 'course', 'material', 'config']

onMounted(loadInteraction)

async function loadInteraction() {
  iLoading.value = true
  try {
    const data = await adminApi.interactionLogs({
      page: iPage.value,
      size: iSize.value,
      user_id: iFilters.user_id || undefined,
      branch: iFilters.branch || undefined,
      session_id: iFilters.session_id || undefined,
    })
    interactions.value = data.items || []
    iTotal.value = data.total || 0
  } catch { /* 拦截器已提示 */ } finally {
    iLoading.value = false
  }
}

function reloadInteraction() {
  iPage.value = 1
  loadInteraction()
}

async function loadOperation() {
  oLoading.value = true
  try {
    const data = await adminApi.operationLogs({
      page: oPage.value,
      size: oSize.value,
      admin_id: oFilters.admin_id || undefined,
      action: oFilters.action || undefined,
      target_type: oFilters.target_type || undefined,
    })
    operations.value = data.items || []
    oTotal.value = data.total || 0
  } catch { /* 拦截器已提示 */ } finally {
    oLoading.value = false
  }
}

function reloadOperation() {
  oPage.value = 1
  loadOperation()
}

async function loadAudit() {
  aLoading.value = true
  try {
    const data = await approvalsApi.logs({
      page: aPage.value,
      size: aSize.value,
      scope: 'all',
      action: aAction.value || undefined,
    })
    audits.value = data.items || []
    aTotal.value = data.total || 0
  } catch { /* 拦截器已提示 */ } finally {
    aLoading.value = false
  }
}

async function loadActionCatalog() {
  try {
    const data = await approvalsApi.actions()
    actionOptions.value = data.items || []
  } catch { /* 拦截器已提示 */ }
}

function reloadAudit() {
  aPage.value = 1
  loadAudit()
}

function levelType(level) {
  return { manual: 'danger', auto: 'warning', full: 'success' }[level] || 'info'
}

watch(tab, (v) => {
  if (v === 'operation' && !operations.value.length) loadOperation()
  if (v === 'audit') {
    if (!actionOptions.value.length) loadActionCatalog()
    if (!audits.value.length) loadAudit()
  }
})

function formatTime(t) {
  if (!t) return '—'
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.tab-body { display: flex; flex-direction: column; gap: var(--sp-4); }
.pager { display: flex; justify-content: flex-end; padding: var(--sp-3) var(--sp-4); border-top: 1px solid var(--border); }
.dim { color: var(--text-placeholder); font-size: var(--fs-xs); }
</style>
