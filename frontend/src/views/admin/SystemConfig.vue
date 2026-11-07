<template>
  <div class="page">
    <div class="page-head">
      <div class="page-head__main">
        <h2 class="page-title">系统配置</h2>
        <p class="page-sub">维护平台运行参数，修改后需保存生效</p>
      </div>
      <div class="page-head__actions">
        <el-button v-if="userStore.canAdminWrite" @click="addRow"><el-icon><Plus /></el-icon> 新增配置项</el-button>
        <el-button @click="load"><el-icon><Refresh /></el-icon> 重新加载</el-button>
        <el-button
          v-if="userStore.canAdminWrite"
          type="primary"
          :loading="saving"
          @click="save"
        >
          <el-icon><Check /></el-icon> 保存配置
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="!userStore.canAdminWrite"
      type="warning" :closable="false" show-icon
      title="观察者仅可查看配置，修改请联系超级管理员或普通管理员。"
      class="tip-alert"
    />
    <el-alert
      v-else
      type="info" :closable="false" show-icon
      title="配置项修改后点击「保存配置」生效；新增的配置键若不存在将由后端自动创建。"
      class="tip-alert"
    />

    <div class="panel">
      <SkeletonTable v-if="loading && !draft.length" :rows="4" :cols="4" />
      <StateBlock
        v-else-if="error && !draft.length"
        state="error"
        action-label="重新加载"
        @retry="load"
      />
      <el-table v-else :data="draft" v-loading="loading">
        <el-table-column label="配置键" min-width="200">
          <template #default="{ row }">
            <el-input v-model="row.config_key" placeholder="config_key" :disabled="!userStore.canAdminWrite" />
          </template>
        </el-table-column>
        <el-table-column label="配置值" min-width="240">
          <template #default="{ row }">
            <el-input v-model="row.config_value" placeholder="config_value" :disabled="!userStore.canAdminWrite" />
          </template>
        </el-table-column>
        <el-table-column label="说明" min-width="200">
          <template #default="{ row }">
            <span v-if="row.description">{{ row.description }}</span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="更新时间" width="180">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column v-if="userStore.canAdminWrite" label="操作" width="90" fixed="right">
          <template #default="{ $index }">
            <el-button link type="danger" @click="removeRow($index)">移除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <StateBlock state="empty" title="暂无配置项" hint="可点击右上角「新增配置项」添加" />
        </template>
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '../../api/admin'
import { useUserStore } from '../../stores/user'
import SkeletonTable from '../../components/SkeletonTable.vue'
import StateBlock from '../../components/StateBlock.vue'

const userStore = useUserStore()

const loading = ref(false)
const saving = ref(false)
const error = ref(false)
const draft = ref([])

onMounted(load)

async function load() {
  error.value = false
  loading.value = true
  try {
    const data = await adminApi.config()
    draft.value = (data.items || []).map((it) => ({ ...it }))
  } catch {
    error.value = true /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

function addRow() {
  draft.value.push({
    id: null,
    config_key: '',
    config_value: '',
    description: '管理端新增',
    updated_at: null,
  })
}

function removeRow(index) {
  draft.value.splice(index, 1)
}

async function save() {
  const items = draft.value
    .filter((r) => r.config_key && r.config_key.trim())
    .map((r) => ({ config_key: r.config_key.trim(), config_value: r.config_value ?? '' }))
  if (!items.length) return ElMessage.warning('没有可保存的配置项')

  saving.value = true
  try {
    const data = await adminApi.saveConfig(items)
    draft.value = (data.items || []).map((it) => ({ ...it }))
    ElMessage.success('配置已保存')
  } catch { /* 拦截器已提示 */ } finally {
    saving.value = false
  }
}

function formatTime(t) {
  if (!t) return '—'
  return new Date(t).toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.tip-alert { border-radius: var(--r-sm); }
.dim { color: var(--text-placeholder); }
</style>
