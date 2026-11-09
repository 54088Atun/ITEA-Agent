<template>
  <AppShell
    brand="ITEA 智能助教"
    brand-sub="学生学习空间"
    role-label="学生端"
    role-suffix="同学"
    page-title="学生学习空间"
    :active-menu="route.path"
  >
    <template #nav>
      <el-menu-item index="/student/tutor">
        <el-icon><ChatDotRound /></el-icon>
        <span>智能助手</span>
      </el-menu-item>
      <el-menu-item index="/student/classes">
        <el-icon><School /></el-icon>
        <span>我的班级</span>
      </el-menu-item>
      <el-menu-item index="/student/courseware">
        <el-icon><FolderOpened /></el-icon>
        <span>课程资料</span>
      </el-menu-item>
      <el-menu-item v-if="features.feature_assignments" index="/student/assignments">
        <el-icon><EditPen /></el-icon>
        <span>我的作业</span>
      </el-menu-item>
      <el-menu-item v-if="features.feature_exams" index="/student/exams">
        <el-icon><Collection /></el-icon>
        <span>在线考试</span>
      </el-menu-item>
      <el-menu-item index="/student/wrong">
        <el-icon><DocumentDelete /></el-icon>
        <span>错题本</span>
      </el-menu-item>
      <el-menu-item index="/student/review">
        <el-icon><Refresh /></el-icon>
        <span>复习计划</span>
      </el-menu-item>
      <el-menu-item index="/student/interview">
        <el-icon><Microphone /></el-icon>
        <span>面试实训</span>
      </el-menu-item>
      <el-menu-item index="/student/progress">
        <el-icon><TrendCharts /></el-icon>
        <span>我的学情</span>
      </el-menu-item>
      <el-menu-item index="/contact">
        <el-icon><Service /></el-icon>
        <span>联系我们</span>
      </el-menu-item>
      <el-menu-item v-if="userStore.isAdmin" index="/admin/stats">
        <el-icon><Monitor /></el-icon>
        <span>管理后台</span>
      </el-menu-item>
    </template>

    <template #actions>
      <el-badge :value="notifCount" :hidden="notifCount === 0">
        <el-button text circle title="通知" aria-label="通知" @click="openNotifs">
          <el-icon :size="17"><Bell /></el-icon>
        </el-button>
      </el-badge>
    </template>

    <router-view v-slot="{ Component }">
      <Transition name="page-fade" mode="out-in">
        <component :is="Component" />
      </Transition>
    </router-view>
  </AppShell>

  <!-- 通知抽屉 -->
  <el-drawer v-model="drawerVisible" title="通知中心" size="420px">
    <div class="notification-toolbar">
      <el-select v-model="category" size="small" style="width: 112px" @change="loadNotifs">
        <el-option label="全部通知" value="" />
        <el-option label="作业" value="assignment" />
        <el-option label="考试" value="exam" />
        <el-option label="面试" value="interview" />
        <el-option label="复习" value="review" />
      </el-select>
      <el-button size="small" :disabled="notifCount === 0" @click="readAll">全部已读</el-button>
      <el-button size="small" @click="togglePreferences">通知设置</el-button>
    </div>

    <div v-if="preferencesVisible" v-loading="preferencesLoading" class="preferences">
      <h3>分类提醒</h3>
      <div class="preference-row"><span>作业任务</span><el-switch v-model="preferences.assignment_enabled" /></div>
      <div class="preference-row"><span>考试任务</span><el-switch v-model="preferences.exam_enabled" /></div>
      <div class="preference-row"><span>面试任务</span><el-switch v-model="preferences.interview_enabled" /></div>
      <div class="preference-row"><span>错题复习</span><el-switch v-model="preferences.review_enabled" /></div>
      <el-divider />
      <h3>免打扰时段</h3>
      <p class="preference-hint">免打扰期间的通知会保存，并在时段结束后显示。</p>
      <div class="quiet-hours">
        <el-time-picker
          v-model="preferences.quiet_start" value-format="HH:mm" format="HH:mm"
          placeholder="开始时间" size="small"
        />
        <span>至</span>
        <el-time-picker
          v-model="preferences.quiet_end" value-format="HH:mm" format="HH:mm"
          placeholder="结束时间" size="small"
        />
      </div>
      <div class="preference-actions">
        <el-button @click="preferencesVisible = false">返回通知</el-button>
        <el-button type="primary" :loading="savingPreferences" @click="savePreferences">保存设置</el-button>
      </div>
    </div>

    <template v-else>
      <el-empty v-if="notifs.length === 0" description="暂无通知" />
      <div v-else class="notification-list">
        <button
          v-for="n in visibleNotifs" :key="n.id" type="button"
          class="notification-item" :class="{ 'notification-item--unread': !n.is_read }"
          @click="openNotification(n)"
        >
          <span class="notification-item__head">
            <strong>{{ n.title }}</strong>
            <el-tag size="small" effect="plain">{{ categoryLabel(n.category) }}</el-tag>
          </span>
          <span class="notification-item__message">{{ n.message }}</span>
          <span class="notification-item__foot">
            <span>{{ formatTime(n.timestamp) }}</span>
            <span v-if="n.link_url" class="notification-item__link">查看详情</span>
            <span v-else-if="!n.is_read" class="notification-item__link">标记已读</span>
          </span>
        </button>
        <div v-if="visibleCount < notifs.length" ref="sentinelRef" class="notification-sentinel"></div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import AppShell from './AppShell.vue'
import { studentApi } from '../api/student'
import { useUserStore } from '../stores/user'
import { features, loadFeatures } from '../stores/features'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const notifs = ref([])
const notifCount = ref(0)
const drawerVisible = ref(false)
const category = ref('')
const preferencesVisible = ref(false)
const preferencesLoading = ref(false)
const savingPreferences = ref(false)
const preferences = ref(defaultPreferences())
let pollTimer = null

// 通知接口全量返回,数量大时分批增量挂载,避免抽屉一次性渲染长列表
const LIST_INITIAL = 60
const LIST_STEP = 40
const visibleCount = ref(LIST_INITIAL)
const visibleNotifs = computed(() => notifs.value.slice(0, visibleCount.value))
const sentinelRef = ref(null)
let listObserver = null

watch(notifs, () => { visibleCount.value = LIST_INITIAL })

watch(sentinelRef, (el) => {
  if (!el) return
  if (!listObserver) {
    listObserver = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting) visibleCount.value += LIST_STEP
    }, { rootMargin: '120px' })
  }
  listObserver.disconnect()
  listObserver.observe(el)
})

function defaultPreferences() {
  return {
    assignment_enabled: true,
    exam_enabled: true,
    interview_enabled: true,
    review_enabled: true,
    quiet_start: null,
    quiet_end: null,
  }
}

async function loadNotifs() {
  try {
    const data = await studentApi.notifications(category.value ? { category: category.value } : {})
    notifs.value = data.notifications || []
    notifCount.value = data.unread_count || 0
  } catch { /* 静默 */ }
}

async function openNotifs() {
  drawerVisible.value = true
  preferencesVisible.value = false
  await loadNotifs()
}

async function openNotification(notification) {
  if (!notification.is_read) {
    try {
      await studentApi.markNotificationRead(notification.id)
      notification.is_read = true
      notifCount.value = Math.max(0, notifCount.value - 1)
    } catch { /* 已读失败不阻塞任务跳转 */ }
  }
  if (notification.link_url) {
    drawerVisible.value = false
    await router.push(notification.link_url)
  }
}

async function readAll() {
  try {
    await studentApi.markAllNotificationsRead()
    notifs.value.forEach((notification) => { notification.is_read = true })
    notifCount.value = 0
  } catch { /* 拦截器已提示 */ }
}

async function togglePreferences() {
  preferencesVisible.value = !preferencesVisible.value
  if (!preferencesVisible.value) return
  preferencesLoading.value = true
  try {
    preferences.value = await studentApi.notificationPreferences()
  } catch { /* 拦截器已提示 */ } finally {
    preferencesLoading.value = false
  }
}

async function savePreferences() {
  if (Boolean(preferences.value.quiet_start) !== Boolean(preferences.value.quiet_end)) {
    ElMessage.warning('请同时设置免打扰开始和结束时间')
    return
  }
  savingPreferences.value = true
  try {
    preferences.value = await studentApi.updateNotificationPreferences(preferences.value)
    ElMessage.success('通知设置已保存')
  } catch { /* 拦截器已提示 */ } finally {
    savingPreferences.value = false
  }
}

function categoryLabel(value) {
  return { assignment: '作业', exam: '考试', interview: '面试', review: '复习' }[value] || '通知'
}

onMounted(() => {
  loadFeatures()
  loadNotifs()
  pollTimer = setInterval(loadNotifs, 60000)
})

onBeforeUnmount(() => {
  if (pollTimer) clearInterval(pollTimer)
  listObserver?.disconnect()
})

function formatTime(t) {
  if (!t) return ''
  const d = new Date(t)
  return Number.isNaN(d.getTime()) ? t : d.toLocaleString('zh-CN', { hour12: false })
}
</script>

<style scoped>
.notification-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 16px; }
.notification-list { display: flex; flex-direction: column; gap: 10px; }
.notification-sentinel { height: 1px; }
.notification-item {
  display: flex; flex-direction: column; gap: 8px; width: 100%; padding: 14px;
  border: 1px solid var(--border); border-radius: var(--r-sm); background: var(--bg-card);
  color: var(--text-primary); font: inherit; text-align: left; cursor: pointer;
}
.notification-item--unread { border-left: 3px solid var(--primary); background: var(--bg-subtle); }
.notification-item__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.notification-item__head strong { font-size: var(--fs-sm); line-height: 1.5; }
.notification-item__message { color: var(--text-secondary); font-size: var(--fs-xs); line-height: 1.6; }
.notification-item__foot { display: flex; justify-content: space-between; color: var(--text-placeholder); font-size: var(--fs-xs); }
.notification-item__link { color: var(--primary); }
.preferences h3 { margin: 8px 0 12px; font-size: var(--fs-sm); }
.preference-row { display: flex; align-items: center; justify-content: space-between; padding: 10px 0; }
.preference-hint { color: var(--text-secondary); font-size: var(--fs-xs); line-height: 1.6; }
.quiet-hours { display: flex; align-items: center; gap: 8px; margin-top: 14px; }
.quiet-hours :deep(.el-date-editor) { width: 132px; }
.preference-actions { display: flex; justify-content: flex-end; margin-top: 24px; }
</style>
