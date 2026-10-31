<template>
  <AppShell
    brand="ITEA 管理后台"
    brand-sub="Platform Console"
    role-label="管理端"
    :role-suffix="adminLevelLabel"
    page-title="管理后台"
    :active-menu="route.path"
  >
    <template #nav>
      <el-menu-item index="/admin/stats">
        <el-icon><DataAnalysis /></el-icon>
        <span>平台统计</span>
      </el-menu-item>
      <el-menu-item index="/admin/assistant">
        <el-icon><MagicStick /></el-icon>
        <span>智能助手</span>
      </el-menu-item>
      <el-menu-item index="/admin/users">
        <el-icon><User /></el-icon>
        <span>用户管理</span>
      </el-menu-item>
      <el-menu-item index="/admin/courses">
        <el-icon><Notebook /></el-icon>
        <span>课程审核</span>
      </el-menu-item>
      <el-menu-item index="/admin/risk">
        <el-icon><Warning /></el-icon>
        <span>风控审计</span>
      </el-menu-item>
      <el-menu-item index="/admin/logs">
        <el-icon><Document /></el-icon>
        <span>日志审计</span>
      </el-menu-item>
      <el-menu-item index="/admin/config">
        <el-icon><Tools /></el-icon>
        <span>系统配置</span>
      </el-menu-item>
      <el-sub-menu index="workspace">
        <template #title>
          <el-icon><Monitor /></el-icon>
          <span>前台工作台</span>
        </template>
        <el-menu-item index="/teacher/courses">教师工作台</el-menu-item>
        <el-menu-item index="/student/tutor">学生学习空间</el-menu-item>
      </el-sub-menu>
    </template>

    <router-view />
  </AppShell>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from './AppShell.vue'
import { useUserStore } from '../stores/user'

const route = useRoute()
const userStore = useUserStore()

// 顶栏展示当前管理员级别，不再统一写死「管理员」
const adminLevelLabel = computed(() => {
  const labels = { super: '超级管理员', normal: '普通管理员', observer: '观察者' }
  return labels[userStore.adminLevel] || '管理员'
})
</script>
