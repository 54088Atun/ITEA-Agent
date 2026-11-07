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
            <DebouncedInput v-model="iFilters.user_id" placeholder="用户 ID" clearable style="width: 140px" @keyup.enter="reloadInteraction" @debounce="reloadInteraction" />
            <el-select v-model="iFilters.branch" placeholder="全部分支" clearable style="width: 160px">
              <el-option label="备课 teacher" value="teacher" />
              <el-option label="助教 tutor" value="tutor" />
              <el-option label="复盘 review" value="review" />
              <el-option label="面试 interview" value="interview" />
              <el-option label="风控 block" value="block" />
            </el-select>
            <DebouncedInput v-model="iFilters.session_id" placeholder="会话 ID" clearable style="width: 220px" @keyup.enter="reloadInteraction" @debounce="reloadInteraction" />
            <el-button type="primary" @click="reloadInteraction"><el-icon><Search /></el-icon> 查询</el-button>
            <div class="filter-bar__spacer"></div>
            <span class="filter-bar__count">共 {{ iTotal }} 条对话</span>
          </div>

          <div class="panel">
            <SkeletonTable v-if="iLoading && !interactions.length" :rows="6" :cols="5" />
            <StateBlock
              v-else-if="iError"
              state="error"
              title="对话日志加载失败"
              @retry="loadInteraction"
            />
            <el-table v-else :data="interactions">
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
                <StateBlock state="empty" title="暂无对话日志" hint="调整用户或类型筛选后重试" />
              </template>
            </el-table>

            <div ref="iSentinel" class="load-more">
              <el-button
                v-if="interactions.length < iTotal"
                text type="primary" :loading="iLoading"
                @click="loadMoreInteraction"
              >加载更多（已加载 {{ interactions.length }} / {{ iTotal }}）</el-button>
              <span v-else-if="interactions.length" class="load-more__done">已加载全部 {{ iTotal }} 条</span>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- 操作日志 -->
      <el-tab-pane label="操作日志" name="operation">
        <div class="tab-body">
          <div class="filter-bar">
            <DebouncedInput v-model="oFilters.admin_id" placeholder="管理员 ID" clearable style="width: 150px" @keyup.enter="reloadOperation" @debounce="reloadOperation" />
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
            <SkeletonTable v-if="oLoading && !operations.length" :rows="6" :cols="5" />
            <StateBlock
              v-else-if="oError"
              state="error"
              title="操作日志加载失败"
              @retry="loadOperation"
            />
            <el-table v-else :data="operations">
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
                <StateBlock state="empty" title="暂无操作日志" hint="调整筛选条件后重试" />
              </template>
            </el-table>

            <div ref="oSentinel" class="load-more">
              <el-button
                v-if="operations.length < oTotal"
                text type="primary" :loading="oLoading"
                @click="loadMoreOperation"
              >加载更多（已加载 {{ operations.length }} / {{ oTotal }}）</el-button>
              <span v-else-if="operations.length" class="load-more__done">已加载全部 {{ oTotal }} 条</span>
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
            <SkeletonTable v-if="aLoading && !audits.length" :rows="6" :cols="5" />
            <StateBlock
              v-else-if="aError"
              state="error"
              title="写操作审计加载失败"
              @retry="loadAudit"
            />
            <el-table v-else :data="audits">
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
                <StateBlock state="empty" title="暂无写操作审计" hint="调整筛选条件后重试" />
              </template>
            </el-table>

            <div ref="aSentinel" class="load-more">
              <el-button
                v-if="audits.length < aTotal"
                text type="primary" :loading="aLoading"
                @click="loadMoreAudit"
              >加载更多（已加载 {{ audits.length }} / {{ aTotal }}）</el-button>
              <span v-else-if="audits.length" class="load-more__done">已加载全部 {{ aTotal }} 条</span>
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
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'
import DebouncedInput from '../../components/DebouncedInput.vue'
import { useAutoLoadMore } from '../../composables/useAutoLoadMore.js'

const tab = ref('interaction')
const iSentinel = ref(null)
const oSentinel = ref(null)
const aSentinel = ref(null)

// 对话日志
const iLoading = ref(false)
const iError = ref(false)
const interactions = ref([])
const iTotal = ref(0)
const iPage = ref(1)
const iSize = ref(20)
const iFilters = reactive({ user_id: '', branch: '', session_id: '' })

// 操作日志
const oLoading = ref(false)
const oError = ref(false)
const operations = ref([])
const oTotal = ref(0)
const oPage = ref(1)
const oSize = ref(20)
const oFilters = reactive({ admin_id: '', action: '', target_type: '' })

// 写操作审计
const aLoading = ref(false)
const aError = ref(false)
const audits = ref([])
const aTotal = ref(0)
const aPage = ref(1)
const aSize = ref(20)
const aAction = ref('')
const actionOptions = ref([])

const actions = ['create', 'update', 'delete', 'enable', 'disable', 'approve', 'reject', 'config']
const targetTypes = ['user', 'course', 'material', 'config']

onMounted(loadInteraction)

async function loadInteraction(reset = true) {
  if (reset) {
    iPage.value = 1
    iError.value = false
  }
  iLoading.value = true
  try {
    const data = await adminApi.interactionLogs({
      page: iPage.value,
      size: iSize.value,
      user_id: iFilters.user_id || undefined,
      branch: iFilters.branch || undefined,
      session_id: iFilters.session_id || undefined,
    })
    const rows = data.items || []
    interactions.value = reset ? rows : [...interactions.value, ...rows]
    iTotal.value = data.total || 0
  } catch { iError.value = true } finally {
    iLoading.value = false
  }
}

function loadMoreInteraction() {
  if (iLoading.value || interactions.value.length >= iTotal.value) return
  iPage.value += 1
  loadInteraction(false)
}

function reloadInteraction() {
  iPage.value = 1
  loadInteraction()
}

async function loadOperation(reset = true) {
  if (reset) {
    oPage.value = 1
    oError.value = false
  }
  oLoading.value = true
  try {
    const data = await adminApi.operationLogs({
      page: oPage.value,
      size: oSize.value,
      admin_id: oFilters.admin_id || undefined,
      action: oFilters.action || undefined,
      target_type: oFilters.target_type || undefined,
    })
    const rows = data.items || []
    operations.value = reset ? rows : [...operations.value, ...rows]
    oTotal.value = data.total || 0
  } catch { oError.value = true } finally {
    oLoading.value = false
  }
}

function loadMoreOperation() {
  if (oLoading.value || operations.value.length >= oTotal.value) return
  oPage.value += 1
  loadOperation(false)
}

function reloadOperation() {
  oPage.value = 1
  loadOperation()
}

async function loadAudit(reset = true) {
  if (reset) {
    aPage.value = 1
    aError.value = false
  }
  aLoading.value = true
  try {
    const data = await approvalsApi.logs({
      page: aPage.value,
      size: aSize.value,
      scope: 'all',
      action: aAction.value || undefined,
    })
    const rows = data.items || []
    audits.value = reset ? rows : [...audits.value, ...rows]
    aTotal.value = data.total || 0
  } catch { aError.value = true } finally {
    aLoading.value = false
  }
}

function loadMoreAudit() {
  if (aLoading.value || audits.value.length >= aTotal.value) return
  aPage.value += 1
  loadAudit(false)
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

// 滚动到底自动加载下一页；按钮保留为兜底入口
useAutoLoadMore(
  iSentinel,
  () => !iLoading.value && interactions.value.length < iTotal.value,
  loadMoreInteraction,
)
useAutoLoadMore(
  oSentinel,
  () => !oLoading.value && operations.value.length < oTotal.value,
  loadMoreOperation,
)
useAutoLoadMore(
  aSentinel,
  () => !aLoading.value && audits.value.length < aTotal.value,
  loadMoreAudit,
)

function formatTime(t) {
  if (!t) return '—'
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.tab-body { display: flex; flex-direction: column; gap: var(--sp-4); }
.load-more {
  display: flex;
  justify-content: center;
  min-height: 40px;
  padding: var(--sp-2) var(--sp-4);
}
.load-more__done { font-size: var(--fs-xs); color: var(--text-placeholder); }
.dim { color: var(--text-placeholder); font-size: var(--fs-xs); }
</style>
